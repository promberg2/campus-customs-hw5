"""All backend datatypes: agent dependencies, agent outputs, approvals and audit events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field
from pydantic_ai.usage import RunUsage

if TYPE_CHECKING:
    from backend.approvals import Approver
    from backend.audit import AuditTrail
    from backend.mcp_tools import TeamToolsets

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
SpecialistName = Literal["inventory", "accounting", "facilities", "customer_service"]
TicketStatus = Literal[
    "open", "in_progress", "waiting_on_approval", "waiting_on_vendor", "waiting_on_customer", "resolved", "rejected",
]


# ---------------------------------------------------------------- runtime dependencies

@dataclass
class TeamContext:
    """State shared by every agent in one team run."""

    team_run_id: str
    audit: AuditTrail
    approver: Approver
    toolsets: TeamToolsets
    usage: RunUsage = field(default_factory=RunUsage)
    delegations_used: int = 0
    denied_actions: set[str] = field(default_factory=set)
    payment_authorizations: dict[str, PaymentAuthorization] = field(default_factory=dict)
    approval_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    focus_tickets: frozenset[int] | None = None   # None = every open ticket; otherwise writes stay on these


@dataclass
class AgentDeps:
    """Per-agent-run dependencies passed to PydanticAI as `deps`."""

    team: TeamContext
    agent: AgentName
    agent_run_id: str
    chain: tuple[str, ...]
    depth: int
    step: int = 0


# ---------------------------------------------------------------- agent outputs

class Fact(BaseModel):
    label: str = Field(description="What the number or fact is, e.g. 'Cash on hand'.")
    value: str = Field(description="The value exactly as returned by an MCP tool.")
    source_tool: str = Field(description="The MCP tool that returned it.")


class SpecialistReport(BaseModel):
    """What a specialist hands back to whoever delegated the task."""

    agent: str = Field(default="", description="Filled in by the backend.")
    status: Literal["done", "blocked", "needs_decision", "incomplete"]
    summary: str = Field(description="Two to four sentences answering the task.")
    facts: list[Fact] = Field(default_factory=list, description="Key facts, each traced to a tool.")
    actions_taken: list[str] = Field(default_factory=list, description="Writes that actually happened.")
    recommendations: list[str] = Field(default_factory=list)
    needs_human_approval: list[str] = Field(default_factory=list, description="Actions waiting for a human.")
    needs_boss_decision: list[str] = Field(default_factory=list)


class TicketOutcome(BaseModel):
    ticket_id: int
    final_status: TicketStatus
    decision: str = Field(description="The Boss's final call in one or two sentences.")
    actions_taken: list[str] = Field(default_factory=list)
    awaiting_human: list[str] = Field(default_factory=list)
    draft_ids: list[int] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)


class BossReport(BaseModel):
    """The Boss's final output for a team run."""

    summary: str
    cash_plan: str = Field(description="How the cash is used, with the remaining balance from the tools.")
    tickets: list[TicketOutcome]
    risks: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- approvals

class PaymentAuthorization(BaseModel):
    """The Boss's final call on one payment. Accounting can only submit payments the Boss authorized."""

    kind: Literal["invoice", "rent"]
    ref_id: int = Field(ge=1, description="invoice id for an invoice, lease id for rent.")
    amount: float = Field(gt=0, description="Exact amount, as reported by the tools.")
    reason: str = Field(min_length=1, max_length=400, description="Why the Boss wants this paid now.")

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ref_id}"


class ApprovalRequest(BaseModel):
    team_run_id: str
    requested_by: str
    chain: list[str]
    tool: str
    arguments: dict[str, Any]
    reason: str
    boss_authorization: PaymentAuthorization | None = None


class ApprovalDecision(BaseModel):
    approved: bool
    approver: str | None = None
    comment: str = ""
    queued: bool = Field(False, description="Put on the approval board for a human; nothing executed yet.")
    approval_id: int | None = None
    executed: bool = Field(False, description="The board already executed the approved action under the human's name.")
    result: Any = None


ApprovalKind = Literal["invoice", "rent", "discount", "purchase_order"]
ApprovalStatus = Literal["pending", "approved", "denied", "failed"]


class BoardApproval(BaseModel):
    """One action waiting on the approval board. Agents prepare it; only a human decision executes it."""

    id: int
    kind: ApprovalKind
    tool: str
    arguments: dict[str, Any]
    ticket_id: int | None = None
    title: str
    amount: float | None = None
    reason: str
    requested_by: str
    chain: list[str] = Field(default_factory=list)
    team_run_id: str | None = None
    boss_authorization: PaymentAuthorization | None = None
    status: ApprovalStatus = "pending"
    created_at: str = Field(default_factory=lambda: utc_now())
    decided_at: str | None = None
    decided_by: str | None = None
    comment: str | None = None
    result: Any = None
    follow_up_run_id: str | None = None


# ---------------------------------------------------------------- audit trail

AuditEventType = Literal[
    "team_run_start", "team_run_end",
    "agent_run_start", "agent_run_end",
    "model_step", "tool_call",
    "boss_authorization", "approval_requested", "approval_decision",
    "delegation_request", "delegation_result", "delegation_refused",
    "db_reset", "error",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuditEvent(BaseModel):
    ts: str = Field(default_factory=utc_now)
    team_run_id: str
    event: AuditEventType
    agent: str | None = None
    agent_run_id: str | None = None
    parent_agent: str | None = None
    chain: list[str] | None = None
    depth: int | None = None
    step: int | None = None
    model: str | None = None
    tool: str | None = None
    arguments: dict[str, Any] | None = None
    result: Any = None
    status: str | None = None
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None


class TeamRunResult(BaseModel):
    team_run_id: str
    stop_reason: str
    report: BossReport | None
    usage: dict[str, Any]
    db_sha256_before: str
    db_sha256_after: str
