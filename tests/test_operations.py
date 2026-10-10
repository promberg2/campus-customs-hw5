"""Tests for the agent-team tools added in Problem 5, run through a real MCP client on a temp DB copy."""

from __future__ import annotations

import asyncio
import shutil
import sqlite3

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from mcp_server.config import DB_ENV_VAR, ORIGINAL_DB
from mcp_server.server import mcp


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    path = tmp_path / "campus_customs_test.db"
    shutil.copy(ORIGINAL_DB, path)
    monkeypatch.setenv(DB_ENV_VAR, str(path))
    return path


def call(name: str, args: dict | None = None) -> dict:
    async def run():
        async with Client(mcp) as client:
            return (await client.call_tool(name, args or {})).structured_content
    return asyncio.run(run())


def q(path, sql, *params):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# ------------------------------------------------------------------ shared


def test_snapshot_matches_database():
    s = call("get_shop_snapshot")
    assert s["today"] == "2026-08-31"
    assert s["cash_total"] == 3400.0
    assert [t["id"] for t in s["open_tickets"]] == [101, 102, 103]
    assert s["open_invoices_total"] == 840.0 and s["overdue_invoices_total"] == 840.0
    assert s["obligations_next_30_days"] == 3240.0
    assert s["cash_after_obligations"] == 160.0
    assert {(r["sku"], r["size"]) for r in s["out_of_stock"]} == {("CC-TEE-WHITE", "S"), ("CC-MUG-CREST", "OS")}
    assert {(r["sku"], r["size"]) for r in s["low_stock"]} == {("CC-TEE-WHITE", "L"), ("CC-TEE-WHITE", "XL")}


def test_list_tickets_filters_by_status():
    assert [t["id"] for t in call("list_tickets")["tickets"]] == [101, 102, 103]
    assert [t["id"] for t in call("list_tickets", {"status": "open"})["tickets"]] == [101, 102, 103]
    assert call("list_tickets", {"status": "resolved"})["tickets"] == []
    with pytest.raises(ToolError, match="Unknown status"):
        call("list_tickets", {"status": "done"})


def test_get_ticket_links_everything():
    t = call("get_ticket", {"ticket_id": 101})
    assert t["linked_invoice"]["id"] == 501
    assert t["handled_by"] == "check_order_fulfillment"
    assert [s["size"] for s in t["product_stock"]] == ["S", "M", "L", "XL"]


def test_update_ticket_status_keeps_original_notes(temp_db):
    r = call("update_ticket_status", {"ticket_id": 102, "status": "waiting_on_approval",
                                      "note": "Rent verified; awaiting approval.", "acting_agent": "boss"})
    assert r["previous_status"] == "open" and r["new_status"] == "waiting_on_approval"
    notes = q(temp_db, "SELECT notes FROM tickets WHERE id=102")[0][0]
    assert notes.startswith("Email: shop rent due in 2 days.")
    assert "boss: open -> waiting_on_approval" in notes


# ------------------------------------------------------------------ inventory


def test_check_stock_and_unknown_sku():
    r = call("check_stock", {"sku": "CC-HOOD-NAVY", "size": "M"})
    assert r["requested_size"]["qty"] == 8 and r["total_units"] == 32
    with pytest.raises(ToolError, match="Known SKUs"):
        call("check_stock", {"sku": "NOPE"})


def test_shortfalls_link_tickets():
    r = call("find_stock_shortfalls")
    short = {(i["sku"], i["size"]): i for i in r["items"]}
    assert short[("CC-HOOD-NAVY", "M")]["shortfall"] == 12
    assert short[("CC-HOOD-NAVY", "M")]["ticket_ids"] == [103]
    assert short[("CC-TEE-WHITE", "S")]["shortfall"] == 1
    assert r["rows_short_for_open_tickets"] == 2


def test_vendor_status_flags_blocked_vendor():
    r = call("get_vendor_status")
    blocked = {v["vendor"]["name"]: v["blocked"] for v in r["vendors"]}
    assert blocked == {"Bulldog Print Co": True, "Elm City Gifts": False, "QuickShip CT": False}


def test_ship_guards(temp_db):
    with pytest.raises(ToolError, match="Only 0"):
        call("ship_order_from_stock", {"ticket_id": 101, "qty": 1})
    with pytest.raises(ToolError, match="no recorded price decision"):
        call("ship_order_from_stock", {"ticket_id": 103, "qty": 8})
    with pytest.raises(ToolError, match="only customer orders"):
        call("ship_order_from_stock", {"ticket_id": 102, "qty": 1})


def test_ship_after_price_decision_moves_stock_once(temp_db):
    call("record_discount_decision", {"ticket_id": 103, "discount_pct": 10, "rationale": "bulk", "acting_agent": "boss"})
    m = call("ship_order_from_stock", {"ticket_id": 103, "qty": 8, "acting_agent": "inventory"})
    assert m["qty_after"] == 0 and m["created_by"] == "inventory"
    assert q(temp_db, "SELECT qty FROM inventory WHERE sku='CC-HOOD-NAVY' AND size='M'")[0][0] == 0
    with pytest.raises(ToolError, match="Only 0"):
        call("ship_order_from_stock", {"ticket_id": 103, "qty": 1})


# ------------------------------------------------------------------ accounting: payments


def test_cash_position_and_invoice_list_match_database():
    c = call("get_cash_position")
    assert c["cash_total"] == 3400.0 and c["obligations_total"] == 3240.0 and c["cash_after_obligations"] == 160.0
    assert c["open_invoices_total"] == 840.0 and c["unpaid_rent_due_within_30_days_total"] == 2400.0
    assert c["payments"] == []
    inv = call("list_invoices")
    assert [(i["id"], i["vendor_name"], i["amount"], i["days_overdue"]) for i in inv["invoices"]] == \
        [(501, "Bulldog Print Co", 840.0, 3)]
    assert call("list_invoices", {"status": "paid"})["invoices"] == []


def test_pay_invoice_requires_named_human(temp_db):
    for who in (None, "", "boss", "accounting", "AI", "pending"):
        with pytest.raises(ToolError, match="named human approver"):
            call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": who})
    assert q(temp_db, "SELECT COUNT(*) FROM payments")[0][0] == 0


def test_pay_invoice_updates_all_tables_atomically(temp_db):
    r = call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "unblock vendor",
                             "approved_by": "Philipp"})
    assert (r["cash_before"], r["cash_after"]) == (3400.0, 2560.0)
    assert r["vendor_unblocked"] is True
    assert q(temp_db, "SELECT status FROM invoices WHERE id=501")[0][0] == "paid"
    assert q(temp_db, "SELECT balance, date FROM cash_accounts")[0] == (2560.0, "2026-08-31")
    assert q(temp_db, "SELECT kind, ref_id, amount, account, paid_at, approved_by FROM payments")[0] == (
        "invoice", 501, 840.0, "checking", "2026-08-31", "Philipp")
    with pytest.raises(ToolError, match="not be paid twice"):
        call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})


def test_pay_invoice_amount_must_match(temp_db):
    with pytest.raises(ToolError, match="does not match"):
        call("pay_invoice", {"invoice_id": 501, "expected_amount": 800, "reason": "x", "approved_by": "Philipp"})
    assert q(temp_db, "SELECT balance FROM cash_accounts")[0][0] == 3400.0


def test_pay_rent_advances_lease_and_refuses_overdraft(temp_db):
    r = call("pay_rent", {"lease_id": 1, "expected_amount": 2400, "reason": "rent", "approved_by": "Philipp"})
    assert r["cash_after"] == 1000.0 and r["lease_next_due_after"] == "2026-10-02"
    assert q(temp_db, "SELECT next_due FROM leases WHERE id=1")[0][0] == "2026-10-02"
    con = sqlite3.connect(temp_db)
    con.execute("UPDATE leases SET next_due='2026-10-30'")
    con.execute("UPDATE cash_accounts SET balance=100")
    con.commit()
    con.close()
    with pytest.raises(ToolError, match="overdraw"):
        call("pay_rent", {"lease_id": 1, "expected_amount": 2400, "reason": "rent", "approved_by": "Philipp"})
    assert q(temp_db, "SELECT balance FROM cash_accounts")[0][0] == 100.0
    assert q(temp_db, "SELECT COUNT(*) FROM payments")[0][0] == 1


def test_rent_review_after_pay_rent_says_the_notice_is_paid(temp_db):
    call("pay_rent", {"lease_id": 1, "expected_amount": 2400, "reason": "rent", "approved_by": "Philipp"})
    r = call("review_rent_payment", {"ticket_id": 102})
    assert r["outcome"] == "already_paid" and r["already_paid_this_period"] is True
    assert r["payment_proposal"] is None
    assert (r["notice_period_due"], r["lease"]["next_due"], r["next_due_after_payment"]) == (
        "2026-09-02", "2026-10-02", "2026-10-02")
    assert "approved by Philipp" in r["summary"]
    lease = call("get_lease_status", {"lease_id": 1})["leases"][0]
    assert lease["paid_this_period"] is False and lease["lease"]["next_due"] == "2026-10-02"
    assert (lease["last_rent_payment"]["amount"], lease["last_rent_payment"]["approved_by"]) == (2400.0, "Philipp")


def test_pay_rent_twice_is_refused():
    call("pay_rent", {"lease_id": 1, "expected_amount": 2400, "reason": "rent", "approved_by": "Philipp"})
    r = call("get_lease_status", {"lease_id": 1})
    assert r["leases"][0]["lease"]["next_due"] == "2026-10-02"


# ------------------------------------------------------------------ accounting: orders and margins


def test_purchase_order_refused_for_blocked_vendor_then_allowed(temp_db):
    args = {"vendor_id": 1, "sku": "CC-HOOD-NAVY", "size": "M", "qty": 12, "reason": "ticket 103", "ticket_id": 103,
            "acting_agent": "accounting"}
    with pytest.raises(ToolError, match="will not ship"):
        call("create_purchase_order", args)
    call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})
    r = call("create_purchase_order", args)
    po = r["purchase_order"]
    assert (po["total_cost"], po["status"], po["expected_arrival"]) == (264.0, "pending_approval", "2026-09-05")
    assert r["cash_after_known_obligations"] == 160.0 and r["affordable_after_obligations"] is False
    assert q(temp_db, "SELECT balance FROM cash_accounts")[0][0] == 2560.0


def test_purchase_order_decision_needs_a_human_and_moves_cash_once(temp_db):
    call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})
    po = call("create_purchase_order", {"vendor_id": 1, "sku": "CC-HOOD-NAVY", "size": "M", "qty": 12,
                                        "reason": "ticket 103", "ticket_id": 103, "acting_agent": "accounting"})
    po_id = po["purchase_order"]["id"]
    with pytest.raises(ToolError, match="named human approver"):
        call("decide_purchase_order", {"purchase_order_id": po_id, "approve": True, "approved_by": "accounting"})
    r = call("decide_purchase_order", {"purchase_order_id": po_id, "approve": True, "approved_by": "Philipp"})
    assert r["purchase_order"]["status"] == "approved" and r["receipt"]["cash_after"] == 2296.0
    assert q(temp_db, "SELECT balance FROM cash_accounts")[0][0] == 2296.0
    assert q(temp_db, "SELECT kind, ref_id, amount, approved_by FROM payments WHERE kind='purchase_order'") == [
        ("purchase_order", po_id, 264.0, "Philipp")]
    with pytest.raises(ToolError, match="not pending"):
        call("decide_purchase_order", {"purchase_order_id": po_id, "approve": True, "approved_by": "Philipp"})


def test_order_fulfillment_follows_the_purchase_order_through_approval(temp_db):
    call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})
    assert call("check_order_fulfillment", {"ticket_id": 101})["outcome"] == "awaiting_restock"
    po = call("create_purchase_order", {"vendor_id": 1, "sku": "CC-TEE-WHITE", "size": "S", "qty": 1,
                                        "reason": "ticket 101", "ticket_id": 101, "acting_agent": "accounting"})
    r = call("check_order_fulfillment", {"ticket_id": 101})
    assert r["outcome"] == "restock_pending_approval" and r["payments_to_approve"] == []
    assert [p["status"] for p in r["purchase_orders"]] == ["pending_approval"]
    call("decide_purchase_order", {"purchase_order_id": po["purchase_order"]["id"], "approve": True,
                                   "approved_by": "Philipp"})
    r = call("check_order_fulfillment", {"ticket_id": 101})
    assert r["outcome"] == "restock_ordered" and r["earliest_arrival_if_unblocked_today"] == "2026-09-05"
    assert [p["status"] for p in r["purchase_orders"]] == ["approved"]
    t = call("get_ticket", {"ticket_id": 101})
    assert [p["status"] for p in t["purchase_orders"]] == ["approved"]
    assert [(p["kind"], p["ref_id"], p["amount"], p["approved_by"]) for p in t["payments"]] == [
        ("invoice", 501, 840.0, "Philipp"), ("purchase_order", po["purchase_order"]["id"], 8.0, "Philipp")]


def test_rejected_purchase_order_moves_no_cash(temp_db):
    call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})
    po = call("create_purchase_order", {"vendor_id": 1, "sku": "CC-HOOD-NAVY", "size": "M", "qty": 12,
                                        "reason": "ticket 103", "acting_agent": "accounting"})
    r = call("decide_purchase_order", {"purchase_order_id": po["purchase_order"]["id"], "approve": False,
                                       "comment": "not now", "approved_by": "Philipp"})
    assert r["purchase_order"]["status"] == "rejected" and r["receipt"] is None
    assert q(temp_db, "SELECT balance FROM cash_accounts")[0][0] == 2560.0


def test_margin_limits():
    r = call("analyze_margin", {"sku": "CC-HOOD-NAVY", "qty": 20, "discount_percents": [10, 15, 20, 52.5, 53]})
    s = {x["discount_pct"]: x for x in r["scenarios"]}
    assert r["max_discount_pct_allowed"] == 52.5
    assert s[15.0]["within_boss_authority"] and not s[20.0]["within_boss_authority"]
    assert s[52.5]["allowed"] and not s[53.0]["allowed"]


def test_discount_decision_rules(temp_db):
    with pytest.raises(ToolError, match="named human approver"):
        call("record_discount_decision", {"ticket_id": 103, "discount_pct": 20, "rationale": "x", "acting_agent": "boss"})
    with pytest.raises(ToolError, match="below the minimum"):
        call("record_discount_decision", {"ticket_id": 103, "discount_pct": 55, "rationale": "x",
                                          "acting_agent": "boss", "approved_by": "Philipp"})
    with pytest.raises(ToolError, match="only recorded on price_override"):
        call("record_discount_decision", {"ticket_id": 101, "discount_pct": 5, "rationale": "x"})
    r = call("record_discount_decision", {"ticket_id": 103, "discount_pct": 10, "rationale": "bulk", "acting_agent": "boss"})
    assert (r["unit_price"], r["order_total"], r["approved_by"]) == (52.2, 1044.0, None)
    with pytest.raises(ToolError, match="already recorded"):
        call("record_discount_decision", {"ticket_id": 103, "discount_pct": 5, "rationale": "x"})


# ------------------------------------------------------------------ customer service


def test_customer_view_has_no_internal_data():
    v = call("get_customer_order_view", {"ticket_id": 101})
    assert v["availability"] == "backordered" and v["expected_ready_date"] == "2026-09-05"
    assert not {"unit_cost", "cash", "invoice", "vendor", "margin"} & set(v)
    facts = {k: val for k, val in v.items() if k != "sharing_rules"}
    numbers = [x for x in facts.values() if isinstance(x, float)]
    assert all(n not in (22.0, 8.0, 3400.0, 840.0) for n in numbers)
    assert "bulldog print" not in str(facts).lower()
    with pytest.raises(ToolError, match="not a customer request"):
        call("get_customer_order_view", {"ticket_id": 102})


def test_draft_leak_guard(temp_db):
    for body in ("Our unit cost is low.", "We owe Bulldog Print Co money.", "Price is $22.00 at cost.",
                 "Cash is 3,400.00 right now."):
        with pytest.raises(ToolError, match="internal information"):
            call("save_customer_draft", {"ticket_id": 101, "subject": "Your tee", "body": body})
    d = call("save_customer_draft", {"ticket_id": 101, "subject": "Your Bulldog tee",
                                     "body": "Hi Tauhid, size S is expected by 2026-09-05. Price $28.00.",
                                     "acting_agent": "customer_service"})
    assert d["status"] == "draft" and d["recipient"] == "Tauhid Zaman" and d["created_by"] == "customer_service"
    assert len(call("list_drafts", {"ticket_id": 101})["drafts"]) == 1


def test_draft_guard_allows_quantities_and_the_agreed_price(temp_db):
    small_costs = [r[0] for r in q(temp_db, "SELECT unit_cost FROM pricing") if float(r[0]).is_integer() and r[0] < 21]
    n = int(small_costs[0]) if small_costs else 8
    call("record_discount_decision", {"ticket_id": 103, "discount_pct": 15, "rationale": "bulk"})
    body = f"We have {n} hoodies available now. The agreed price is $49.30 each, list price $58.00."
    d = call("save_customer_draft", {"ticket_id": 103, "subject": "Your hoodies", "body": body})
    assert d["status"] == "draft"
    with pytest.raises(ToolError, match="internal information"):
        call("save_customer_draft", {"ticket_id": 103, "subject": "Your hoodies", "body": "They cost us 22 dollars."})


def test_unknown_acting_agent_is_not_trusted(temp_db):
    d = call("save_customer_draft", {"ticket_id": 101, "subject": "Hi", "body": "Hello", "acting_agent": "ceo"})
    assert d["created_by"] == "unknown"


def test_original_database_untouched_by_writes():
    import hashlib
    before = hashlib.sha256(ORIGINAL_DB.read_bytes()).hexdigest()
    call("pay_invoice", {"invoice_id": 501, "expected_amount": 840, "reason": "x", "approved_by": "Philipp"})
    assert hashlib.sha256(ORIGINAL_DB.read_bytes()).hexdigest() == before
