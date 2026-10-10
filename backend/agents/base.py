"""Shared agent machinery: construction, the audited agent loop, and guarded peer-to-peer delegation."""

from __future__ import annotations

import uuid
from typing import Any

from openai import AsyncOpenAI
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from backend.audit import clip, usage_dict
from backend.config import (
    DELEGATION_BUDGET_RESERVE,
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_TEAM_RUN,
    MAX_OUTPUT_TOKENS_PER_RESPONSE,
    MAX_STEPS,
    MODEL_NAME,
    PORTKEY_BASE_URL,
    PROMPTS_DIR,
    REQUEST_TIMEOUT_S,
    TEAM_USAGE_LIMITS,
    TOOLS_BY_AGENT,
    portkey_api_key,
)
from backend.models import AgentDeps, AuditEvent, SpecialistReport

AGENTS: dict[str, Agent[AgentDeps, Any]] = {}

_model: OpenAIResponsesModel | None = None


def build_model() -> OpenAIResponsesModel:
    """gpt-6-luna through Portkey; the only model used anywhere in this project."""
    global _model
    if _model is None:
        # a cached gateway answer would replay an earlier run instead of letting the agent decide again
        client = AsyncOpenAI(
            api_key=portkey_api_key(),
            base_url=PORTKEY_BASE_URL,
            timeout=REQUEST_TIMEOUT_S,
            default_headers={"x-portkey-cache-force-refresh": "true"},
        )
        _model = OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))
    return _model


def load_prompt(agent: str) -> str:
    charter = (PROMPTS_DIR / "team_charter.md").read_text(encoding="utf-8")
    own = (PROMPTS_DIR / f"{agent}.md").read_text(encoding="utf-8")
    return f"{own}\n\n---\n\n{charter}"


def build_agent(name: str, output_type: type) -> Agent[AgentDeps, Any]:
    agent: Agent[AgentDeps, Any] = Agent(
        None,
        name=name,
        deps_type=AgentDeps,
        output_type=output_type,
        instructions=load_prompt(name),
        model_settings=OpenAIResponsesModelSettings(
            max_tokens=MAX_OUTPUT_TOKENS_PER_RESPONSE,
            parallel_tool_calls=True,
        ),
        retries=2,
    )

    @agent.instructions
    def runtime_context(ctx: RunContext[AgentDeps]) -> str:
        d = ctx.deps
        others = [a for a in AGENTS if a not in d.chain and a != "boss"]
        can_delegate = d.depth < MAX_DELEGATION_DEPTH
        return (
            f"Runtime context: you are the {d.agent} agent. Delegation chain so far: {' -> '.join(d.chain)}. "
            f"Depth {d.depth} of max {MAX_DELEGATION_DEPTH}. Your MCP tools: {', '.join(sorted(TOOLS_BY_AGENT[d.agent]))}. "
            f"You have at most {MAX_STEPS[d.agent]} model steps in this run. "
            + (f"You may hand work to colleagues ({', '.join(others)}) except anyone already in the chain."
               if can_delegate else "You are at maximum depth: answer with your own tools, do not delegate.")
        )

    AGENTS[name] = agent
    return agent


def agent_event(deps: AgentDeps, event: str, **fields: Any) -> AuditEvent:
    parent = deps.chain[-2] if len(deps.chain) > 1 else None
    return AuditEvent(team_run_id=deps.team.team_run_id, event=event, agent=deps.agent, agent_run_id=deps.agent_run_id,
                      parent_agent=parent, chain=list(deps.chain), depth=deps.depth, step=deps.step, **fields)


async def run_agent(name: str, prompt: str, deps: AgentDeps) -> tuple[Any, str]:
    """Run one agent loop with a step cap, logging every model step. Returns (output or None, stop_reason)."""
    agent = AGENTS[name]
    audit = deps.team.audit
    max_steps = MAX_STEPS[name]
    await audit.log(agent_event(deps, "agent_run_start", model=MODEL_NAME, detail={"prompt": prompt, "max_steps": max_steps}))
    output, stop_reason = None, "unknown"
    before = usage_dict(deps.team.usage)
    try:
        async with agent.iter(prompt, model=build_model(), deps=deps, usage=deps.team.usage, usage_limits=TEAM_USAGE_LIMITS,
                              toolsets=[deps.team.toolsets.for_agent(name)]) as run:
            async for node in run:
                if Agent.is_model_request_node(node):
                    deps.step += 1
                    if deps.step > max_steps:
                        stop_reason = "step_limit"
                        break
                elif Agent.is_call_tools_node(node):
                    response = node.model_response
                    await audit.log(agent_event(
                        deps, "model_step", model=MODEL_NAME,
                        status=str(response.finish_reason) if response.finish_reason else None,
                        usage=usage_dict(response.usage),
                        detail={
                            "provider_model_label": response.model_name,
                            "tool_calls": [{"tool": p.tool_name, "arguments": p.args_as_dict(), "call_id": p.tool_call_id}
                                           for p in response.parts if isinstance(p, ToolCallPart)],
                            "text": " ".join(p.content for p in response.parts if isinstance(p, TextPart)).strip() or None,
                        },
                    ))
            if run.result is not None:
                output, stop_reason = run.result.output, "final_output"
    except UsageLimitExceeded as exc:
        stop_reason = "usage_limit"
        await audit.log(agent_event(deps, "error", status="usage_limit", detail={"message": str(exc)}))
    except Exception as exc:
        stop_reason = "error"
        await audit.log(agent_event(deps, "error", status="exception", detail={"message": f"{type(exc).__name__}: {exc}"}))
        if deps.depth == 0:
            raise
    finally:
        after = usage_dict(deps.team.usage)
        await audit.log(agent_event(
            deps, "agent_run_end", model=MODEL_NAME, status=stop_reason,
            usage={k: after[k] - before[k] for k in after},
            result=clip(output.model_dump(mode="json")) if hasattr(output, "model_dump") else None,
            detail={"steps": min(deps.step, max_steps), "team_usage_so_far": after},
        ))
    return output, stop_reason


def _refusal(deps: AgentDeps, colleague: str) -> str | None:
    team = deps.team
    if colleague == deps.agent:
        return "You cannot delegate to yourself."
    if colleague in deps.chain:
        return f"Refused to prevent a loop: {colleague} is already working on this chain ({' -> '.join(deps.chain)})."
    if deps.depth >= MAX_DELEGATION_DEPTH:
        return f"Refused: maximum delegation depth {MAX_DELEGATION_DEPTH} reached. Use your own tools."
    if team.delegations_used >= MAX_DELEGATIONS_PER_TEAM_RUN:
        return f"Refused: the team used all {MAX_DELEGATIONS_PER_TEAM_RUN} delegations for this run. Conclude with what you have."
    limits = TEAM_USAGE_LIMITS
    used = usage_dict(team.usage)
    if (limits.request_limit and used["requests"] >= limits.request_limit * (1 - DELEGATION_BUDGET_RESERVE)) or (
        limits.total_tokens_limit and used["total_tokens"] >= limits.total_tokens_limit * (1 - DELEGATION_BUDGET_RESERVE)
    ):
        return "Refused: the team's token/request budget is nearly used up. Conclude with what you have."
    return None


async def delegate(ctx: RunContext[AgentDeps], colleague: str, task: str) -> SpecialistReport | str:
    """Hand a task to a colleague and wait for their report, with loop and budget guards."""
    deps = ctx.deps
    audit = deps.team.audit
    refusal = _refusal(deps, colleague)
    if refusal:
        await audit.log(agent_event(deps, "delegation_refused", detail={"to": colleague, "task": task, "reason": refusal}))
        return refusal
    deps.team.delegations_used += 1
    child = AgentDeps(team=deps.team, agent=colleague, agent_run_id=uuid.uuid4().hex[:12],
                      chain=(*deps.chain, colleague), depth=deps.depth + 1)
    await audit.log(agent_event(deps, "delegation_request", detail={
        "to": colleague, "child_agent_run_id": child.agent_run_id, "task": task,
        "delegations_used": deps.team.delegations_used}))
    output, stop_reason = await run_agent(colleague, f"Task from {deps.agent}: {task}", child)
    if isinstance(output, SpecialistReport):
        output.agent = colleague
        report = output
    else:
        report = SpecialistReport(agent=colleague, status="incomplete",
                                  summary=f"{colleague} stopped before finishing (reason: {stop_reason}).")
    await audit.log(agent_event(deps, "delegation_result", status=report.status, result=report.model_dump(mode="json"),
                           detail={"from": colleague, "child_agent_run_id": child.agent_run_id, "stop_reason": stop_reason}))
    return report
