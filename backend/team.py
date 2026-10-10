"""Runs the whole team for a set of tickets: one MCP connection, one shared budget, one audited run."""

from __future__ import annotations

import hashlib
import shutil
import uuid
from pathlib import Path

from backend import agents  # noqa: F401  (registers all agents)
from backend.agents.base import run_agent
from backend.approvals import Approver
from backend.audit import AuditTrail, usage_dict
from backend.config import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_TEAM_RUN,
    MAX_OUTPUT_TOKENS_PER_RESPONSE,
    MAX_STEPS,
    MODEL_NAME,
    ORIGINAL_DB,
    TEAM_USAGE_LIMITS,
    WORKING_DB,
)
from backend.mcp_tools import TeamToolsets
from backend.models import AgentDeps, AuditEvent, BossReport, TeamContext, TeamRunResult
from backend.shop_db import linked_obligations


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reset_working_db() -> str:
    """Restore the working copy from the untouched original (shop rule before a full run)."""
    if ORIGINAL_DB.resolve() == WORKING_DB.resolve():
        raise RuntimeError("Refusing to reset: original and working database are the same file.")
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    return sha256(WORKING_DB)


def boss_prompt(ticket_ids: list[int] | None) -> str:
    if not ticket_ids:
        return (
            "Resolve every open ticket on the board (use list_tickets to find them) for Campus Customs. Start with "
            "get_shop_snapshot so you see all tickets, cash and obligations together, then plan holistically: the "
            "same cash serves every ticket. Delegate the analysis and execution to the right specialists, make the "
            "final call on each ticket, record status changes with notes, have customer service draft any customer "
            "reply, and return your BossReport."
        )
    scope = ", ".join(map(str, ticket_ids))
    links = [f"{kind} {ref}" for kind, ref in linked_obligations(ticket_ids)]
    owned = (f" The tickets table links ticket {scope} to {' and '.join(links)}, so deciding whether to pay "
             f"{'it' if len(links) == 1 else 'them'} is part of this run: once the facts are in, either authorize "
             "the payment now so it reaches the human approval board, or record why not." if links else "")
    return (
        f"Resolve ticket {scope} for Campus Customs, and only that ticket. Start with get_shop_snapshot so you "
        "see cash and every obligation: other tickets matter for cash planning only." + owned + " Do not "
        "authorize payments, record discounts, save drafts or change the status of any other ticket; each "
        "ticket gets its own run, and the tools refuse such changes. Delegate the analysis and execution to the right specialists, make "
        f"the final call on ticket {scope}, record its status change with a note, have customer service draft "
        f"any customer reply, and return your BossReport covering ticket {scope} only."
    )


async def run_team(ticket_ids: list[int] | None, approver: Approver, audit: AuditTrail | None = None,
                   team_run_id: str | None = None) -> TeamRunResult:
    audit = audit or AuditTrail()
    team_run_id = team_run_id or uuid.uuid4().hex[:12]
    db_before = sha256(WORKING_DB)
    await audit.log(AuditEvent(team_run_id=team_run_id, event="team_run_start", model=MODEL_NAME, detail={
        "tickets": ticket_ids or "all_open",
        "approver": type(approver).__name__,
        "working_db": str(WORKING_DB),
        "db_sha256": db_before,
        "limits": {
            "request_limit": TEAM_USAGE_LIMITS.request_limit,
            "tool_calls_limit": TEAM_USAGE_LIMITS.tool_calls_limit,
            "total_tokens_limit": TEAM_USAGE_LIMITS.total_tokens_limit,
            "max_output_tokens_per_response": MAX_OUTPUT_TOKENS_PER_RESPONSE,
            "max_steps": MAX_STEPS,
            "max_delegation_depth": MAX_DELEGATION_DEPTH,
            "max_delegations": MAX_DELEGATIONS_PER_TEAM_RUN,
        },
    }))

    report, stop_reason = None, "error"
    toolsets = TeamToolsets()
    team = TeamContext(team_run_id=team_run_id, audit=audit, approver=approver, toolsets=toolsets,
                       focus_tickets=frozenset(ticket_ids) if ticket_ids else None)
    try:
        async with toolsets:
            deps = AgentDeps(team=team, agent="boss", agent_run_id=uuid.uuid4().hex[:12], chain=("boss",), depth=0)
            report, stop_reason = await run_agent("boss", boss_prompt(ticket_ids), deps)
    finally:
        db_after = sha256(WORKING_DB)
        await audit.log(AuditEvent(team_run_id=team_run_id, event="team_run_end", model=MODEL_NAME, status=stop_reason,
                                   usage=usage_dict(team.usage), detail={
                                       "delegations_used": team.delegations_used,
                                       "denied_actions": sorted(team.denied_actions),
                                       "db_sha256": db_after,
                                       "db_changed": db_after != db_before,
                                   }))
    return TeamRunResult(
        team_run_id=team_run_id, stop_reason=stop_reason,
        report=report if isinstance(report, BossReport) else None,
        usage=usage_dict(team.usage), db_sha256_before=db_before, db_sha256_after=db_after,
    )
