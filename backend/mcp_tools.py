"""The only source of agent tools: the Campus Customs MCP server.

One stdio MCP connection is shared by the team. Every call passes through `process_tool_call`, which
enforces the agent's allowlist, injects the acting agent, runs the human approval gate and writes
the audit trail. Each agent receives a filtered view that only lists its own tools.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import RunContext
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from backend.audit import clip
from backend.config import (
    ALWAYS_APPROVAL_TOOLS,
    BOSS_DISCOUNT_AUTHORITY_PCT,
    HIDDEN_PARAMS,
    INJECTED_AGENT_PARAM,
    INJECTED_APPROVER_PARAM,
    MCP_SERVER_LOG,
    PROJECT_ROOT,
    TICKET_SCOPED_TOOLS,
    TOOLS_BY_AGENT,
    TOOLS_WITH_ACTING_AGENT,
    mcp_launch_config,
)
from backend.models import AgentDeps, ApprovalRequest, AuditEvent
from backend.shop_db import ticket_for


def approval_reason(tool: str, args: dict[str, Any]) -> str | None:
    """Why a call needs a human, or None if it does not."""
    if tool in ALWAYS_APPROVAL_TOOLS:
        return "Shop rule: every payment needs human approval before cash leaves the account."
    if tool == "record_discount_decision" and float(args.get("discount_pct", 0) or 0) > BOSS_DISCOUNT_AUTHORITY_PCT:
        return f"Discount above the Boss's {BOSS_DISCOUNT_AUTHORITY_PCT:g}% authority needs human approval."
    return None


def _action_key(tool: str, args: dict[str, Any]) -> str:
    target = {k: args[k] for k in ("invoice_id", "lease_id", "ticket_id") if k in args}
    return f"{tool}:{json.dumps(target, sort_keys=True)}"


PAYMENT_TARGET = {"pay_invoice": ("invoice", "invoice_id"), "pay_rent": ("rent", "lease_id")}


def _boss_authorization(deps: AgentDeps, tool: str, args: dict[str, Any]):
    """Maker-checker: a payment needs the Boss's authorization (final call) before a human is asked."""
    kind, id_field = PAYMENT_TARGET[tool]
    auth = deps.team.payment_authorizations.get(f"{kind}:{args.get(id_field)}")
    if auth is None:
        return None, (f"The Boss has not authorized paying {kind} {args.get(id_field)} in this run. Nothing was "
                      "submitted. Report it to the Boss as a recommendation instead.")
    if round(float(args.get("expected_amount", 0) or 0), 2) != round(auth.amount, 2):
        return None, (f"The Boss authorized ${auth.amount:,.2f} for {kind} {auth.ref_id}, not "
                      f"${float(args.get('expected_amount', 0) or 0):,.2f}. Nothing was submitted.")
    return auth, None


async def out_of_scope(deps: AgentDeps, tool: str, args: dict[str, Any]) -> str | None:
    """A run on one ticket must not change another ticket; that ticket gets its own run."""
    focus = deps.team.focus_tickets
    if not focus or tool not in TICKET_SCOPED_TOOLS:
        return None
    ticket = await asyncio.to_thread(ticket_for, tool, args)
    if ticket is None or int(ticket) in focus:
        return None
    return (f"{tool} belongs to ticket {ticket}, but this run only works on ticket "
            f"{', '.join(map(str, sorted(focus)))}. Nothing was changed. Mention it as a risk or next step; "
            f"ticket {ticket} gets its own run.")


def _plain(result: Any) -> Any:
    if hasattr(result, "model_dump"):
        return result.model_dump(mode="json")
    return result


def _event(deps: AgentDeps, event: str, **fields: Any) -> AuditEvent:
    return AuditEvent(
        team_run_id=deps.team.team_run_id, event=event, agent=deps.agent, agent_run_id=deps.agent_run_id,
        chain=list(deps.chain), depth=deps.depth, step=deps.step, **fields,
    )


async def process_tool_call(ctx: RunContext[AgentDeps], call_tool, name: str, tool_args: dict[str, Any]) -> Any:
    deps = ctx.deps
    audit = deps.team.audit
    args = {k: v for k, v in tool_args.items() if k not in HIDDEN_PARAMS}

    if name not in TOOLS_BY_AGENT[deps.agent]:
        await audit.log(_event(deps, "tool_call", tool=name, arguments=args, status="refused_not_allowed"))
        return {"status": "refused", "message": f"{name} is not one of the {deps.agent} agent's tools."}

    refusal = await out_of_scope(deps, name, args)
    if refusal:
        await audit.log(_event(deps, "tool_call", tool=name, arguments=args, status="refused_out_of_scope",
                               detail={"message": refusal}))
        return {"status": "refused_out_of_scope", "message": refusal}

    if name in TOOLS_WITH_ACTING_AGENT:
        args[INJECTED_AGENT_PARAM] = deps.agent

    authorization = None
    if name in ALWAYS_APPROVAL_TOOLS:
        authorization, refusal = _boss_authorization(deps, name, args)
        if refusal:
            await audit.log(_event(deps, "tool_call", tool=name, arguments=args, status="refused_not_authorized_by_boss",
                                   detail={"message": refusal}))
            return {"status": "refused_not_authorized_by_boss", "message": refusal}

    reason = approval_reason(name, args)
    if reason:
        key = _action_key(name, args)
        if key in deps.team.denied_actions:
            await audit.log(_event(deps, "approval_decision", tool=name, arguments=args, status="auto_denied_repeat",
                                   detail={"message": "A human already denied this action in this run."}))
            return {"status": "denied_by_human", "message": "A human already denied this exact action in this run. "
                    "Do not ask again; report it as waiting on approval."}
        request = ApprovalRequest(team_run_id=deps.team.team_run_id, requested_by=deps.agent, chain=list(deps.chain),
                                  tool=name, arguments={k: v for k, v in args.items() if k != INJECTED_AGENT_PARAM},
                                  reason=reason, boss_authorization=authorization)
        await audit.log(_event(deps, "approval_requested", tool=name, arguments=request.arguments, detail={"reason": reason}))
        async with deps.team.approval_lock:
            decision = await deps.team.approver.decide(request)
        if decision.queued:
            await audit.log(_event(deps, "approval_decision", tool=name, arguments=request.arguments,
                                   status="queued_for_human",
                                   detail={"approval_id": decision.approval_id, "comment": decision.comment}))
            return {"status": "queued_for_human_approval", "approval_id": decision.approval_id,
                    "message": f"{decision.comment} Nothing has been executed yet: a human approves or denies it on "
                    "the board. Do not resubmit; report this action as waiting on approval."}
        await audit.log(_event(deps, "approval_decision", tool=name, arguments=request.arguments,
                               status="approved" if decision.approved else "denied",
                               detail={"approval_id": decision.approval_id, "approver": decision.approver,
                                       "comment": decision.comment, "executed_on_board": decision.executed}))
        if not decision.approved:
            deps.team.denied_actions.add(key)
            return {"status": "denied_by_human", "message": f"Human approval was not given ({decision.comment}). "
                    "Nothing was executed. Do not retry; report this action as waiting on approval."}
        if decision.executed:
            return {"status": "approved_and_executed", "approved_by": decision.approver, "result": decision.result,
                    "message": f"{decision.approver} approved this on the board and it was executed. Continue with "
                    "the next step for the ticket."}
        args[INJECTED_APPROVER_PARAM] = decision.approver

    started = time.perf_counter()
    try:
        result = await call_tool(name, args)
    except Exception as exc:
        await audit.log(_event(deps, "tool_call", tool=name, arguments=args, status="error",
                               duration_ms=int((time.perf_counter() - started) * 1000),
                               result={"error": f"{type(exc).__name__}: {exc}"}))
        raise
    await audit.log(_event(deps, "tool_call", tool=name, arguments=args, status="ok",
                           duration_ms=int((time.perf_counter() - started) * 1000), result=clip(_plain(result))))
    if name == "create_purchase_order":
        return await _await_purchase_order_decision(deps, result)
    return result


async def _await_purchase_order_decision(deps: AgentDeps, result: Any) -> Any:
    """On the board, the team waits for the human's decision on the purchase order it just created."""
    wait = getattr(deps.team.approver, "await_purchase_order", None)
    plain = _plain(result)
    po_id = (plain.get("purchase_order") or {}).get("id") if isinstance(plain, dict) else None
    if wait is None or po_id is None:
        return result
    await deps.team.audit.log(_event(deps, "approval_requested", tool="decide_purchase_order",
                                     arguments={"purchase_order_id": po_id},
                                     detail={"reason": "Every purchase order needs a human decision."}))
    decision = await wait(po_id)
    if decision is None:
        return result
    await deps.team.audit.log(_event(deps, "approval_decision", tool="decide_purchase_order",
                                     arguments={"purchase_order_id": po_id},
                                     status="approved" if decision.approved else "denied",
                                     detail={"approval_id": decision.approval_id, "approver": decision.approver,
                                             "comment": decision.comment, "executed_on_board": decision.executed}))
    cost = (plain.get("purchase_order") or {}).get("total_cost")
    verdict = (f"{decision.approver} approved purchase order {po_id} on the board. Approving a purchase order is "
               f"how the shop pays for it, so its cost (${cost:,.2f}) has left checking; this is the order itself, "
               "not an extra payment. Continue with the next step for the ticket.") if decision.approved else (
               f"Purchase order {po_id} was not approved ({decision.comment}). Nothing was paid; do not retry.")
    return {**plain, "human_decision": {"approved": decision.approved, "approved_by": decision.approver,
                                        "result": decision.result}, "message": verdict}


def _strip_hidden(tool_def: ToolDefinition) -> ToolDefinition:
    schema = json.loads(json.dumps(tool_def.parameters_json_schema))
    props = schema.get("properties", {})
    for param in HIDDEN_PARAMS:
        props.pop(param, None)
    if "required" in schema:
        schema["required"] = [r for r in schema["required"] if r not in HIDDEN_PARAMS]
    return replace(tool_def, parameters_json_schema=schema)


async def _hide_backend_params(ctx: RunContext[AgentDeps], tool_defs: list[ToolDefinition]) -> list[ToolDefinition]:
    return [_strip_hidden(t) for t in tool_defs]


class TeamToolsets:
    """Owns the MCP connection for one team run and hands out per-agent views."""

    def __init__(self) -> None:
        cfg = mcp_launch_config()
        transport = StdioTransport(command=cfg["command"], args=cfg["args"], env=cfg["env"], cwd=str(PROJECT_ROOT),
                                   log_file=MCP_SERVER_LOG)
        self.server = MCPToolset(
            Client(transport),
            process_tool_call=process_tool_call,
            tool_error_behavior="failed",
            max_retries=2,
        )
        shared = self.server.prepared(_hide_backend_params)
        self._views: dict[str, AbstractToolset] = {
            agent: shared.filtered(lambda ctx, tool_def, allowed=allowed: tool_def.name in allowed)
            for agent, allowed in TOOLS_BY_AGENT.items()
        }

    def for_agent(self, agent: str) -> AbstractToolset:
        return self._views[agent]

    async def __aenter__(self) -> TeamToolsets:
        await self.server.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.server.__aexit__(*exc)
