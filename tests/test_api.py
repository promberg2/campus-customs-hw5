"""Tests for the board API (backend/main.py) on a temp database copy. No model calls."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

import backend.board as board_mod
import backend.main as main
import backend.shop_db as shop_db
import backend.team as team_mod
from backend.approval_queue import ApprovalQueue
from backend.approvals import BoardApprover
from backend.audit import AuditTrail
from backend.board import Board
from backend.mcp_tools import process_tool_call
from backend.models import AgentDeps, PaymentAuthorization, TeamContext
from mcp_server.config import DB_ENV_VAR, ORIGINAL_DB
from mcp_server.server import mcp


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "campus_customs_new.db"
    shutil.copy(ORIGINAL_DB, db)
    monkeypatch.setenv(DB_ENV_VAR, str(db))
    monkeypatch.setattr(shop_db, "WORKING_DB", db)
    monkeypatch.setattr(team_mod, "WORKING_DB", db)
    monkeypatch.setattr(board_mod, "AUDIT_TRAIL_FILE", tmp_path / "audit.json")

    async def in_memory_mcp(tool, args):
        async with Client(mcp) as client:
            return (await client.call_tool(tool, args)).structured_content

    monkeypatch.setattr(board_mod, "call_mcp_tool", in_memory_mcp)
    monkeypatch.setattr(board_mod, "run_team", fake_run_team(0))
    board = Board(runs_path=tmp_path / "runs.json")
    board.queue = ApprovalQueue(tmp_path / "queue.json")
    board.audit = AuditTrail(tmp_path / "audit.json")
    monkeypatch.setattr(main, "board", board)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, board=board, db=db)


def balance(db) -> float:
    con = sqlite3.connect(db)
    try:
        return con.execute("SELECT balance FROM cash_accounts WHERE name='checking'").fetchone()[0]
    finally:
        con.close()


def queue_payment(board: Board, tool: str = "pay_invoice", args: dict | None = None) -> int:
    """What a web run does when accounting submits a Boss-authorized payment."""
    args = args or {"invoice_id": 501, "expected_amount": 840.0, "reason": "unblock the tee reprint"}
    team = TeamContext(team_run_id="run1", audit=board.audit, approver=BoardApprover(board.queue), toolsets=None)
    auth = PaymentAuthorization(kind="invoice" if tool == "pay_invoice" else "rent",
                                ref_id=args.get("invoice_id") or args.get("lease_id"),
                                amount=args["expected_amount"], reason="Boss call")
    team.payment_authorizations[auth.key] = auth
    deps = AgentDeps(team=team, agent="accounting", agent_run_id="r1", chain=("boss", "accounting"), depth=1)
    calls = []

    async def fake_call(name, a):
        calls.append(name)

    result = asyncio.run(process_tool_call(SimpleNamespace(deps=deps), fake_call, tool, args))
    assert calls == [], "a queued payment must never reach the server during the agent run"
    assert result["status"] == "queued_for_human_approval"
    return result["approval_id"]


def test_tickets_show_status_and_open_or_resolved(env):
    r = env.client.get("/api/tickets").json()
    assert r["today"] == "2026-08-31"
    assert [(t["id"], t["status"], t["state"]) for t in r["tickets"]] == [
        (101, "open", "open"), (102, "open", "open"), (103, "open", "open")]


def test_cash_returns_checking_balance(env):
    assert env.client.get("/api/cash").json() == {"account": "checking", "balance": 3400.0, "as_of": "2026-08-31",
                                                  "today": "2026-08-31"}


def test_agent_payment_is_only_prepared_until_a_human_approves(env):
    approval_id = queue_payment(env.board)
    assert queue_payment(env.board) == approval_id, "the same pending action is not queued twice"
    pending = env.client.get("/api/approvals", params={"status": "pending"}).json()
    assert [(a["id"], a["kind"], a["ticket_id"], a["amount"]) for a in pending] == [(approval_id, "invoice", 101, 840.0)]
    assert balance(env.db) == 3400.0
    assert env.client.get("/api/tickets").json()["tickets"][0]["pending_approvals"] == 1

    r = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["decided_by"] == "Philipp"
    assert balance(env.db) == 2560.0
    assert env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"}).status_code == 409


def test_denied_payment_moves_no_cash(env):
    approval_id = queue_payment(env.board, "pay_rent", {"lease_id": 1, "expected_amount": 2400.0, "reason": "rent"})
    r = env.client.post(f"/api/approvals/{approval_id}/deny", json={"approver_name": "Philipp", "comment": "later"})
    assert r.json()["status"] == "denied" and balance(env.db) == 3400.0


def test_an_agent_name_cannot_approve(env):
    approval_id = queue_payment(env.board)
    r = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "accounting"})
    assert r.status_code == 422 and balance(env.db) == 3400.0


def test_server_refusal_marks_the_approval_failed(env):
    approval_id = queue_payment(env.board, "pay_rent", {"lease_id": 1, "expected_amount": 9999.0, "reason": "x"})
    r = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"})
    assert r.status_code == 409 and "does not match" in r.json()["detail"]
    assert env.board.queue.get(approval_id).status == "failed" and balance(env.db) == 3400.0


def test_purchase_orders_from_the_database_appear_and_can_be_approved(env):
    asyncio.run(board_mod.call_mcp_tool("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x",
                                                        "approved_by": "Philipp"}))
    asyncio.run(board_mod.call_mcp_tool("create_purchase_order", {
        "vendor_id": 1, "sku": "CC-HOOD-NAVY", "size": "M", "qty": 12, "reason": "ticket 103", "ticket_id": 103,
        "acting_agent": "accounting"}))
    [po] = env.client.get("/api/approvals").json()
    assert po["kind"] == "purchase_order" and po["amount"] == 264.0 and po["ticket_id"] == 103
    r = env.client.post(f"/api/approvals/{po['id']}/approve", json={"approver_name": "Philipp"})
    assert r.json()["result"]["purchase_order"]["status"] == "approved" and balance(env.db) == 2296.0


def test_events_are_summarized_and_paged(env):
    approval_id = queue_payment(env.board)
    env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"})
    r = env.client.get("/api/events").json()
    summaries = [e["summary"] for e in r["events"]]
    assert any("queued_for_human" in s for s in summaries) and any("approved by Philipp" in s for s in summaries)
    assert env.client.get("/api/events", params={"since": r["next_since"]}).json()["events"] == []
    assert all(e["team_run_id"] == "run1" for e in env.client.get("/api/events", params={"run_id": "run1"}).json()["events"])


def test_reset_restores_the_original_values_and_clears_the_board(env):
    approval_id = queue_payment(env.board)
    approved = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"}).json()
    assert balance(env.db) == 2560.0
    wait_until_done(env.client, approved["follow_up_run_id"])
    r = env.client.post("/api/reset").json()
    assert r["balance"] == 3400.0 and r["approvals_cleared"] == 1
    assert env.client.get("/api/approvals").json() == []


def fake_run_team(seconds: float):
    async def run(ticket_ids, approver, audit=None, team_run_id=None):
        await asyncio.sleep(seconds)
        report = SimpleNamespace(model_dump=lambda mode=None: {"summary": "done", "tickets": []})
        return SimpleNamespace(stop_reason="final_output", usage={"total_tokens": 1}, report=report)
    return run


def wait_until_done(client, run_id: str) -> dict:
    for _ in range(100):
        run = client.get(f"/api/runs/{run_id}").json()
        if run["status"] != "running":
            return run
        time.sleep(0.05)
    return run


def test_run_rejects_unknown_ticket_and_parallel_runs(env, monkeypatch):
    assert env.client.post("/api/tickets/999/run").status_code == 404
    monkeypatch.setattr(board_mod, "run_team", fake_run_team(0.5))
    first = env.client.post("/api/tickets/101/run")
    assert first.status_code == 202 and first.json()["status"] == "running"
    assert env.client.get("/api/tickets").json()["tickets"][0]["state"] == "running"
    assert env.client.post("/api/tickets/102/run").status_code == 409
    assert env.client.post("/api/reset").status_code == 409
    assert wait_until_done(env.client, first.json()["run_id"])["status"] == "finished"


def test_ticket_is_resolved_when_the_run_finishes_and_runs_survive_a_restart(env, monkeypatch):
    monkeypatch.setattr(board_mod, "run_team", fake_run_team(0.05))
    run_id = env.client.post("/api/tickets/102/run").json()["run_id"]
    run = wait_until_done(env.client, run_id)
    assert run["report"]["summary"] == "done" and run["ticket_status_after"] == "open"
    t102 = env.client.get("/api/tickets").json()["tickets"][1]
    assert t102["state"] == "resolved" and t102["status"] == "open" and t102["last_run"]["run_id"] == run_id
    reloaded = Board(runs_path=env.board.runs_path)
    assert [r.run_id for r in reloaded.list_runs()] == [run_id]
    assert env.client.post("/api/reset").json()["runs_cleared"] == 1
    assert env.client.get("/api/runs").json() == []
    assert env.client.get("/api/tickets").json()["tickets"][1]["state"] == "open"


def test_a_running_team_can_be_stopped(env, monkeypatch):
    monkeypatch.setattr(board_mod, "run_team", fake_run_team(5))
    run_id = env.client.post("/api/tickets/101/run").json()["run_id"]
    assert env.client.post(f"/api/runs/{run_id}/cancel").status_code == 200
    run = wait_until_done(env.client, run_id)
    assert run["status"] == "cancelled"
    assert env.client.get("/api/tickets").json()["tickets"][0]["state"] == "open"
    assert env.client.post(f"/api/runs/{run_id}/cancel").status_code == 409


def test_the_team_continues_on_the_ticket_after_an_approval(env):
    approval_id = queue_payment(env.board)
    r = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"}).json()
    assert r["follow_up_run_id"] and balance(env.db) == 2560.0
    run = wait_until_done(env.client, r["follow_up_run_id"])
    assert run["ticket_id"] == 101 and run["status"] == "finished"


def test_an_approval_during_a_run_continues_after_that_run(env, monkeypatch):
    monkeypatch.setattr(board_mod, "run_team", fake_run_team(0.5))
    busy = env.client.post("/api/tickets/102/run").json()["run_id"]
    approval_id = queue_payment(env.board)
    r = env.client.post(f"/api/approvals/{approval_id}/approve", json={"approver_name": "Philipp"}).json()
    assert r["follow_up_run_id"] is None
    wait_until_done(env.client, busy)
    [follow_up] = [x for x in env.client.get("/api/runs").json() if x["run_id"] != busy]
    assert follow_up["ticket_id"] == 101
    assert wait_until_done(env.client, follow_up["run_id"])["status"] == "finished"


def test_a_waiting_run_continues_with_the_boards_result_and_never_pays_twice(env):
    team = TeamContext(team_run_id="run1", audit=env.board.audit,
                       approver=BoardApprover(env.board.queue, wait_for_human=True, poll_s=0.05), toolsets=None)
    auth = PaymentAuthorization(kind="invoice", ref_id=501, amount=840.0, reason="Boss call")
    team.payment_authorizations[auth.key] = auth
    deps = AgentDeps(team=team, agent="accounting", agent_run_id="r1", chain=("boss", "accounting"), depth=1)
    calls = []

    async def fake_call(name, a):
        calls.append(name)

    async def scenario():
        agent_call = asyncio.create_task(process_tool_call(
            SimpleNamespace(deps=deps), fake_call, "pay_invoice",
            {"invoice_id": 501, "expected_amount": 840.0, "reason": "unblock the tee reprint"}))
        while not env.board.queue.items("pending"):
            await asyncio.sleep(0.02)
        assert not agent_call.done() and balance(env.db) == 3400.0, "the agent waits; nothing is paid yet"
        [item] = env.board.queue.items("pending")
        r = await asyncio.to_thread(env.client.post, f"/api/approvals/{item.id}/approve",
                                    json={"approver_name": "Philipp"})
        assert r.json()["follow_up_run_id"] is None, "the waiting run continues; no extra run is started"
        return await asyncio.wait_for(agent_call, 5)

    result = asyncio.run(scenario())
    assert result["status"] == "approved_and_executed" and result["approved_by"] == "Philipp"
    assert calls == [] and balance(env.db) == 2560.0, "the board paid once; the agent did not pay again"


def test_a_denial_does_not_start_a_run(env):
    approval_id = queue_payment(env.board)
    r = env.client.post(f"/api/approvals/{approval_id}/deny", json={"approver_name": "Philipp"}).json()
    assert r["follow_up_run_id"] is None and env.client.get("/api/runs").json() == []


def test_overview_shows_the_financial_picture(env):
    o = env.client.get("/api/overview").json()
    cp = o["cash_position"]
    assert (cp["cash_total"], cp["obligations_total"], cp["cash_after_obligations"]) == (3400.0, 3240.0, 160.0)
    assert [i["id"] for i in cp["open_invoices"]] == [501] and cp["open_invoices"][0]["days_overdue"] == 3
    assert o["snapshot"]["today"] == "2026-08-31" and o["purchase_orders"] == [] and o["drafts"] == []


def test_vite_dev_server_origin_is_allowed(env):
    r = env.client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"
