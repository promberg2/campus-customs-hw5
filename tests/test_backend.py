"""Offline tests for the agent backend: no model calls, no real database writes."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace

from fastmcp import Client

from backend.agents.base import AGENTS, _refusal
from backend.approvals import DenyAllApprover
from backend.audit import AuditTrail
from backend.config import (
    AGENT_NAMES,
    HUMAN_ONLY_TOOLS,
    MAX_DELEGATIONS_PER_TEAM_RUN,
    MODEL_NAME,
    PROJECT_ROOT,
    PROMPTS_DIR,
    TOOLS_BY_AGENT,
)
from backend.mcp_tools import _strip_hidden, approval_reason, process_tool_call
from backend.agents.boss import delegate_task
from backend.models import AgentDeps, ApprovalDecision, AuditEvent, PaymentAuthorization, TeamContext
from mcp_server.server import mcp

import backend.agents  # noqa: F401  (registers agents)


class FixedApprover:
    def __init__(self, approved: bool, name: str = "Philipp") -> None:
        self.approved, self.name, self.requests = approved, name, []

    async def decide(self, request):
        self.requests.append(request)
        return ApprovalDecision(approved=self.approved, approver=self.name if self.approved else None, comment="test")


def make_deps(tmp_path: Path, agent: str = "accounting", approver=None, chain=("boss", "accounting"), depth=1) -> AgentDeps:
    team = TeamContext(team_run_id="test", audit=AuditTrail(tmp_path / "audit.json"),
                       approver=approver or DenyAllApprover(), toolsets=None)
    return AgentDeps(team=team, agent=agent, agent_run_id="r1", chain=chain, depth=depth)


def run_call(deps: AgentDeps, name: str, args: dict):
    calls = []

    async def fake_call_tool(tool, tool_args):
        calls.append((tool, tool_args))
        return {"ok": True}

    result = asyncio.run(process_tool_call(SimpleNamespace(deps=deps), fake_call_tool, name, args))
    return result, calls


def events(deps: AgentDeps) -> list[dict]:
    return json.loads(deps.team.audit.path.read_text(encoding="utf-8"))


def server_tools() -> dict:
    async def run():
        async with Client(mcp) as client:
            return await client.list_tools()
    return {t.name: t for t in asyncio.run(run())}


# ------------------------------------------------------------------ model and team wiring

def test_only_gpt_6_luna_is_used_anywhere():
    assert MODEL_NAME == "gpt-6-luna"
    pattern = re.compile(r"\b(gpt-[0-9][\w.-]*|o[0-9]-[\w-]+)\b", re.I)
    for path in [*PROJECT_ROOT.joinpath("backend").rglob("*.py"), *PROJECT_ROOT.joinpath("mcp_server").rglob("*.py")]:
        found = {m.lower() for m in pattern.findall(path.read_text(encoding="utf-8"))}
        assert found <= {"gpt-6-luna"}, f"{path.name}: {found}"


def test_all_five_agents_registered_with_prompt_files():
    assert set(AGENTS) == set(AGENT_NAMES)
    for name in AGENT_NAMES:
        text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
        assert "## My agent prompt (Philipp's own words)" in text
        assert "## Optimized and expanded prompt" in text


def test_every_agent_tool_comes_from_the_mcp_server_and_every_server_tool_has_an_owner():
    names = set(server_tools())
    used = set().union(*TOOLS_BY_AGENT.values())
    assert used <= names
    assert used | HUMAN_ONLY_TOOLS == names
    assert not used & HUMAN_ONLY_TOOLS, "human-only tools must never be given to an agent"


def test_customer_service_cannot_see_internal_tools():
    cs = TOOLS_BY_AGENT["customer_service"]
    assert not cs & {"get_ticket", "get_cash_position", "list_invoices", "analyze_margin", "get_vendor_status"}


def test_money_tools_belong_to_accounting_only():
    for agent, tools in TOOLS_BY_AGENT.items():
        if agent != "accounting":
            assert not tools & {"pay_invoice", "pay_rent", "create_purchase_order"}


def test_backend_params_are_hidden_from_the_model():
    tools = server_tools()
    from pydantic_ai.tools import ToolDefinition
    for name in ("pay_invoice", "record_discount_decision", "save_customer_draft"):
        td = ToolDefinition(name=name, parameters_json_schema=tools[name].input_schema)
        props = _strip_hidden(td).parameters_json_schema["properties"]
        assert "approved_by" not in props and "acting_agent" not in props


# ------------------------------------------------------------------ approval gate

def test_approval_rules():
    assert approval_reason("pay_invoice", {})
    assert approval_reason("pay_rent", {})
    assert approval_reason("record_discount_decision", {"discount_pct": 20})
    assert approval_reason("record_discount_decision", {"discount_pct": 15}) is None
    assert approval_reason("check_stock", {}) is None


def authorize(deps: AgentDeps, kind: str = "invoice", ref_id: int = 501, amount: float = 840.0) -> None:
    auth = PaymentAuthorization(kind=kind, ref_id=ref_id, amount=amount, reason="unblock vendor")
    deps.team.payment_authorizations[auth.key] = auth


def test_payment_without_boss_authorization_is_refused_before_asking_a_human(tmp_path):
    approver = FixedApprover(approved=True)
    deps = make_deps(tmp_path, approver=approver)
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x"})
    assert calls == [] and approver.requests == [] and result["status"] == "refused_not_authorized_by_boss"


def test_payment_amount_must_match_the_boss_authorization(tmp_path):
    approver = FixedApprover(approved=True)
    deps = make_deps(tmp_path, approver=approver)
    authorize(deps, amount=840.0)
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 900, "reason": "x"})
    assert calls == [] and approver.requests == [] and result["status"] == "refused_not_authorized_by_boss"
    authorize(deps, kind="rent", ref_id=1, amount=2400.0)
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 1, "expected_amount": 2400, "reason": "x"})
    assert calls == [], "a rent authorization must not unlock invoice 1"


def test_denied_payment_never_reaches_the_server(tmp_path):
    deps = make_deps(tmp_path)
    authorize(deps)
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x"})
    assert calls == [] and result["status"] == "denied_by_human"
    kinds = [e["event"] for e in events(deps)]
    assert kinds == ["approval_requested", "approval_decision"]


def test_repeat_of_a_denied_action_is_not_asked_again(tmp_path):
    approver = FixedApprover(approved=False)
    deps = make_deps(tmp_path, approver=approver)
    authorize(deps)
    run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x"})
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "again"})
    assert len(approver.requests) == 1 and calls == [] and result["status"] == "denied_by_human"


def test_approved_payment_carries_the_human_name_not_the_agent(tmp_path):
    approver = FixedApprover(approved=True, name="Philipp")
    deps = make_deps(tmp_path, approver=approver)
    authorize(deps)
    _, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x",
                                               "approved_by": "accounting"})
    assert calls == [("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})]
    assert approver.requests[0].boss_authorization.ref_id == 501
    assert events(deps)[-1]["event"] == "tool_call" and events(deps)[-1]["status"] == "ok"


def test_a_run_on_one_ticket_cannot_change_another_ticket(tmp_path, monkeypatch):
    import backend.mcp_tools as tools_mod
    monkeypatch.setattr(tools_mod, "ticket_for", lambda tool, args: args.get("ticket_id") or
                        {"pay_invoice": 101, "pay_rent": 102}.get(tool))
    deps = make_deps(tmp_path, agent="customer_service", chain=("boss", "customer_service"))
    deps.team.focus_tickets = frozenset({101})
    result, calls = run_call(deps, "save_customer_draft", {"ticket_id": 103, "subject": "s", "body": "b"})
    assert calls == [] and result["status"] == "refused_out_of_scope"
    _, calls = run_call(deps, "save_customer_draft", {"ticket_id": 101, "subject": "s", "body": "b"})
    assert len(calls) == 1

    boss = make_deps(tmp_path, agent="boss", chain=("boss",), depth=0)
    boss.team.focus_tickets = frozenset({101})
    rent = PaymentAuthorization(kind="rent", ref_id=1, amount=2400, reason="rent due")
    result = asyncio.run(delegate_task(SimpleNamespace(deps=boss), "accounting", "pay rent", [rent]))
    assert "refused" in result and boss.team.payment_authorizations == {}


def test_only_accounting_can_receive_payment_authorizations(tmp_path):
    deps = make_deps(tmp_path, agent="boss", chain=("boss",), depth=0)
    auth = PaymentAuthorization(kind="rent", ref_id=1, amount=2400, reason="rent due")
    result = asyncio.run(delegate_task(SimpleNamespace(deps=deps), "facilities", "pay rent", [auth]))
    assert "only be given to accounting" in result and deps.team.payment_authorizations == {}


def test_acting_agent_is_injected_and_cannot_be_spoofed(tmp_path):
    deps = make_deps(tmp_path, agent="customer_service", chain=("boss", "customer_service"))
    _, calls = run_call(deps, "save_customer_draft", {"ticket_id": 101, "subject": "s", "body": "b", "acting_agent": "boss"})
    assert calls[0][1]["acting_agent"] == "customer_service"


def test_tool_outside_the_allowlist_is_refused(tmp_path):
    deps = make_deps(tmp_path, agent="customer_service", chain=("boss", "customer_service"))
    result, calls = run_call(deps, "pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x"})
    assert calls == [] and result["status"] == "refused"


# ------------------------------------------------------------------ loop guards

def test_delegation_guards(tmp_path):
    deps = make_deps(tmp_path, agent="inventory", chain=("boss", "inventory"), depth=1)
    assert "yourself" in _refusal(deps, "inventory")
    assert "loop" in _refusal(deps, "boss")
    assert _refusal(deps, "accounting") is None
    deep = make_deps(tmp_path, agent="accounting", chain=("boss", "inventory", "accounting"), depth=2)
    assert "depth" in _refusal(deep, "facilities")
    deps.team.delegations_used = MAX_DELEGATIONS_PER_TEAM_RUN
    assert "delegations" in _refusal(deps, "accounting")


# ------------------------------------------------------------------ audit trail

def test_audit_trail_is_append_only(tmp_path):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps([{"event": "older_run"}]), encoding="utf-8")
    trail = AuditTrail(path)
    asyncio.run(trail.log(AuditEvent(team_run_id="t", event="team_run_start")))
    asyncio.run(trail.log(AuditEvent(team_run_id="t", event="team_run_end")))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert [e["event"] for e in data] == ["older_run", "team_run_start", "team_run_end"]


def test_locked_audit_file_holds_events_and_merges_them_later(tmp_path, monkeypatch):
    import backend.audit as audit_mod
    path = tmp_path / "audit_trail.json"
    trail = AuditTrail(path)
    real_replace = audit_mod.os.replace

    def locked(*_):
        raise PermissionError("locked by another process")

    monkeypatch.setattr(audit_mod.time, "sleep", lambda _: None)
    monkeypatch.setattr(audit_mod.os, "replace", locked)
    asyncio.run(trail.log(AuditEvent(team_run_id="t", event="tool_call")))
    assert trail.pending.exists() and not path.exists()
    monkeypatch.setattr(audit_mod.os, "replace", real_replace)
    asyncio.run(trail.log(AuditEvent(team_run_id="t", event="agent_run_end")))
    assert [e["event"] for e in json.loads(path.read_text(encoding="utf-8"))] == ["tool_call", "agent_run_end"]
    assert not trail.pending.exists()


def test_unreadable_audit_trail_is_preserved_not_wiped(tmp_path):
    path = tmp_path / "audit_trail.json"
    path.write_text("{not json", encoding="utf-8")
    asyncio.run(AuditTrail(path).log(AuditEvent(team_run_id="t", event="team_run_start")))
    backups = list(tmp_path.glob("audit_trail.unreadable-*.json"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{not json"
