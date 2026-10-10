"""End-to-end tests: real MCP client, real tools, a temporary copy of the original database."""

from __future__ import annotations

import asyncio
import hashlib
import shutil

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server.config import DB_ENV_VAR, ORIGINAL_DB, WORKING_DB
from mcp_server.server import mcp


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "campus_customs_test.db"
    shutil.copy(ORIGINAL_DB, path)
    monkeypatch.setenv(DB_ENV_VAR, str(path))
    return path


def call(name: str, args: dict) -> dict:
    async def run():
        async with Client(mcp) as client:
            return (await client.call_tool(name, args)).structured_content
    return asyncio.run(run())


def sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


WRITE_TOOLS = {"update_ticket_status", "record_discount_decision", "ship_order_from_stock", "pay_invoice",
               "pay_rent", "create_purchase_order", "decide_purchase_order", "save_customer_draft"}


def test_lists_all_tools_with_correct_annotations():
    async def run():
        async with Client(mcp) as client:
            return await client.list_tools()
    listed = {t.name: t for t in asyncio.run(run())}
    assert len(listed) == 23
    assert {"check_order_fulfillment", "review_rent_payment", "evaluate_bulk_discount_request"} <= set(listed)
    for name, tool in listed.items():
        assert tool.output_schema is not None
        assert tool.annotations.read_only_hint is (name not in WRITE_TOOLS), name
    assert listed["pay_invoice"].annotations.destructive_hint is True
    assert listed["pay_rent"].annotations.destructive_hint is True
    assert listed["decide_purchase_order"].annotations.destructive_hint is True


def test_ticket_101_blocked_by_overdue_invoice():
    r = call("check_order_fulfillment", {"ticket_id": 101})
    assert r["outcome"] == "blocked_by_unpaid_invoice"
    assert r["today"] == "2026-08-31"
    assert (r["qty_on_hand"], r["qty_shortfall"], r["can_ship_now"]) == (0, 1, False)
    assert r["linked_invoice"]["id"] == 501
    assert r["linked_invoice"]["days_overdue"] == 3
    assert r["supplier"]["name"] == "Bulldog Print Co"
    assert r["amount_to_unblock_supplier"] == 840.0
    assert r["cash_after_unblocking"] == 2560.0
    assert r["earliest_arrival_if_unblocked_today"] == "2026-09-05"
    [proposal] = r["payments_to_approve"]
    assert proposal == {
        "kind": "invoice", "ref_id": 501, "payee": "Bulldog Print Co", "amount": 840.0,
        "account": "checking", "pay_on": "2026-08-31", "requires_human_approval": True, "approved": False,
    }
    assert {s["size"] for s in r["other_sizes_in_stock"]} == {"M", "L", "XL"}


def test_ticket_102_ready_for_approval_and_shows_competing_invoice():
    r = call("review_rent_payment", {"ticket_id": 102})
    assert r["outcome"] == "ready_for_approval"
    assert (r["days_until_due"], r["due_status"]) == (2, "due_soon")
    assert r["requester_matches_landlord"] is True
    assert r["already_paid_this_period"] is False
    assert r["cash_after_rent"] == 1000.0
    assert r["other_open_invoices_total"] == 840.0
    assert r["cash_after_rent_and_open_invoices"] == 160.0
    assert r["payment_proposal"]["amount"] == 2400.0
    assert r["payment_proposal"]["payee"] == "Elm City Properties"
    assert r["next_due_after_payment"] == "2026-10-02"


def test_ticket_103_partial_stock_cost_floor_and_blocked_vendor():
    r = call("evaluate_bulk_discount_request", {"ticket_id": 103})
    assert r["outcome"] == "partial_stock"
    assert (r["qty_on_hand"], r["qty_fillable_now"], r["qty_shortfall"]) == (8, 8, 12)
    assert (r["list_total"], r["cost_total"]) == (1160.0, 440.0)
    assert r["max_discount_pct_above_cost"] == 62.0
    assert r["boss_discount_authority_pct"] == 15.0
    assert r["min_margin_pct_after_discount"] == 20.0
    assert r["restock_cost_for_shortfall"] == 264.0
    assert r["known_obligations_total"] == 3240.0
    assert r["cash_after_known_obligations"] == 160.0
    assert r["can_afford_restock_after_obligations"] is False
    bulldog = next(o for o in r["restock_options"] if o["vendor"]["id"] == 1)
    assert bulldog["blocked"] is True
    assert all(s["above_cost"] for s in r["discount_scenarios"])


def test_custom_discounts_flag_prices_below_cost():
    r = call("evaluate_bulk_discount_request", {"ticket_id": 103, "discount_percents": [10, 70]})
    below = {s["discount_pct"]: s["above_cost"] for s in r["discount_scenarios"]}
    assert below == {10.0: True, 70.0: False}


def test_max_discount_is_never_below_cost():
    r = call("evaluate_bulk_discount_request", {"ticket_id": 103, "discount_percents": [62.0, 62.1]})
    at = {s["discount_pct"]: s for s in r["discount_scenarios"]}
    assert at[r["max_discount_pct_above_cost"]]["above_cost"] is True
    assert at[62.1]["above_cost"] is False


def test_wrong_ticket_type_points_to_the_right_tool():
    with pytest.raises(ToolError, match="review_rent_payment"):
        call("check_order_fulfillment", {"ticket_id": 102})


def test_unknown_ticket_is_a_clear_error():
    with pytest.raises(ToolError, match="does not exist"):
        call("review_rent_payment", {"ticket_id": 999})


def test_rent_already_paid_is_detected(temp_db):
    import sqlite3
    con = sqlite3.connect(temp_db)
    con.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
        "VALUES ('rent', 1, 2400, 'checking', '2026-08-31', 'test')"
    )
    con.commit()
    con.close()
    r = call("review_rent_payment", {"ticket_id": 102})
    assert r["outcome"] == "already_paid"
    assert r["payment_proposal"] is None


def test_read_tools_never_change_the_database(temp_db):
    before = sha(temp_db)
    call("check_order_fulfillment", {"ticket_id": 101})
    call("review_rent_payment", {"ticket_id": 102})
    call("evaluate_bulk_discount_request", {"ticket_id": 103})
    assert sha(temp_db) == before


def test_refuses_to_open_the_original_database(monkeypatch):
    monkeypatch.setenv(DB_ENV_VAR, str(ORIGINAL_DB))
    with pytest.raises(ToolError, match="Refusing"):
        call("check_order_fulfillment", {"ticket_id": 101})


def test_default_path_is_the_working_copy(monkeypatch):
    from mcp_server.config import db_path
    monkeypatch.delenv(DB_ENV_VAR)
    assert db_path() == WORKING_DB
