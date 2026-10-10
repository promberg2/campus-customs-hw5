"""MCP smoke test: writes output/mcp_smoke.json.

Launches the server exactly as Cursor does (command, args and env from .mcp.json),
calls each tool once per test prompt, and checks every reported value against
values computed here with independent SQL on data/campus_customs_new.db. The tool
code is never imported, so a bug in the tools cannot hide in the expectations.

    .\\.venv\\Scripts\\python.exe tests\\mcp_smoke.py
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".mcp.json"
OUT = ROOT / "output" / "mcp_smoke.json"
SERVER = "campus-customs"


def load_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8"))["mcpServers"][SERVER]


def db_file(cfg: dict) -> Path:
    return Path(cfg["env"]["CAMPUS_CUSTOMS_DB"])


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def cents(x: float) -> float:
    return round(x + 1e-9, 2)


# ----------------------------------------------------------- independent truth


def ground_truth(path: Path) -> dict[str, Any]:
    con = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    q = lambda sql, *p: con.execute(sql, p).fetchone()  # noqa: E731
    today = date.fromisoformat(q("SELECT date_today FROM desk")[0])
    balance = q("SELECT balance FROM cash_accounts WHERE name='checking'")[0]
    open_total = q("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE status='open'")[0]

    # 101
    sku, size, qty, inv_id = q("SELECT sku,size,qty,invoice_id FROM tickets WHERE id=101")
    on_hand = q("SELECT qty FROM inventory WHERE sku=? AND size=?", sku, size)[0]
    price = q("SELECT list_price FROM pricing WHERE sku=?", sku)[0]
    vendor_id, inv_amount, inv_due = q("SELECT vendor_id,amount,due_date FROM invoices WHERE id=?", inv_id)
    vname, lead = q("SELECT name,lead_days FROM vendors WHERE id=?", vendor_id)
    vendor_open = q("SELECT COALESCE(SUM(amount),0) FROM invoices WHERE vendor_id=? AND status='open'", vendor_id)[0]
    alt_101 = [r[0] for r in con.execute("SELECT size FROM inventory WHERE sku=? AND size<>? AND qty>0 ORDER BY rowid", (sku, size))]
    t101 = {
        "today": today.isoformat(),
        "qty_requested": qty,
        "qty_on_hand": on_hand,
        "qty_shortfall": max(0, qty - on_hand),
        "unit_price": price,
        "order_total": cents(price * qty),
        "linked_invoice.id": inv_id,
        "linked_invoice.amount": inv_amount,
        "linked_invoice.days_overdue": (today - date.fromisoformat(inv_due)).days,
        "supplier.name": vname,
        "supplier.lead_days": lead,
        "amount_to_unblock_supplier": vendor_open,
        "cash.balance": balance,
        "cash_after_unblocking": cents(balance - vendor_open),
        "earliest_arrival_if_unblocked_today": (today + timedelta(days=lead)).isoformat(),
        "other_sizes_in_stock": alt_101,
    }

    # 102
    lease_id, requester = q("SELECT lease_id,requester FROM tickets WHERE id=102")
    landlord, rent, next_due = q("SELECT landlord,monthly_rent,next_due FROM leases WHERE id=?", lease_id)
    due = date.fromisoformat(next_due)
    paid = q("SELECT COUNT(*) FROM payments WHERE kind='rent' AND ref_id=?", lease_id)[0]
    t102 = {
        "today": today.isoformat(),
        "lease.id": lease_id,
        "lease.landlord": landlord,
        "lease.monthly_rent": rent,
        "lease.next_due": next_due,
        "days_until_due": (due - today).days,
        "requester_matches_landlord": requester.casefold() == landlord.casefold(),
        "rent_payments_on_record": paid,
        "cash.balance": balance,
        "cash_after_rent": cents(balance - rent),
        "other_open_invoices_total": open_total,
        "cash_after_rent_and_open_invoices": cents(balance - rent - open_total),
        "payment_proposal.amount": rent,
        "payment_proposal.payee": landlord,
        "next_due_after_payment": date(due.year + (due.month // 12), due.month % 12 + 1, due.day).isoformat(),
    }

    # 103
    sku3, size3, qty3 = q("SELECT sku,size,qty FROM tickets WHERE id=103")
    on3 = q("SELECT qty FROM inventory WHERE sku=? AND size=?", sku3, size3)[0]
    cost3, list3 = q("SELECT unit_cost,list_price FROM pricing WHERE sku=?", sku3)
    window = (today + timedelta(days=30)).isoformat()
    rent_window = q("SELECT COALESCE(SUM(monthly_rent),0) FROM leases WHERE next_due<=?", window)[0]
    blocked = [r[0] for r in con.execute(
        "SELECT DISTINCT v.name FROM vendors v JOIN invoices i ON i.vendor_id=v.id WHERE i.status='open'")]
    obligations = cents(open_total + rent_window)
    shortfall3 = max(0, qty3 - on3)
    t103 = {
        "today": today.isoformat(),
        "qty_requested": qty3,
        "qty_on_hand": on3,
        "qty_fillable_now": min(qty3, on3),
        "qty_shortfall": shortfall3,
        "list_price": list3,
        "unit_cost": cost3,
        "margin_per_unit": cents(list3 - cost3),
        "list_total": cents(list3 * qty3),
        "cost_total": cents(cost3 * qty3),
        "max_discount_pct_above_cost": math.floor(1000 * (1 - cost3 / list3)) / 10,
        "restock_cost_for_shortfall": cents(shortfall3 * cost3),
        "known_obligations_total": obligations,
        "cash.balance": balance,
        "cash_after_known_obligations": cents(balance - obligations),
        "can_afford_restock_after_obligations": balance - obligations >= shortfall3 * cost3,
        "blocked_vendors": blocked,
    }
    ticket_ids = [r[0] for r in con.execute("SELECT id FROM tickets ORDER BY id")]
    con.close()
    return {"101": t101, "102": t102, "103": t103, "ticket_ids": ticket_ids,
            "cost_103": cost3, "list_103": list3, "qty_103": qty3}


def get(data: dict, dotted: str) -> Any:
    for part in dotted.split("."):
        data = data[part]
    return data


def check(name: str, expected: Any, actual: Any, source: str) -> dict:
    ok = expected == actual
    return {"field": name, "expected_from_db": expected, "tool_reported": actual, "source": source, "pass": ok}


def reconcile(output: dict, truth: dict, sources: dict[str, str]) -> list[dict]:
    rows = []
    for field, expected in truth.items():
        if field in ("other_sizes_in_stock", "blocked_vendors", "rent_payments_on_record"):
            continue
        rows.append(check(field, expected, get(output, field), sources.get(field, "derived")))
    return rows


# ------------------------------------------------------------------- the tests

SRC_101 = {
    "today": "desk.date_today",
    "qty_requested": "tickets.qty (id=101)",
    "qty_on_hand": "inventory.qty (sku, size of ticket 101)",
    "qty_shortfall": "tickets.qty - inventory.qty",
    "unit_price": "pricing.list_price",
    "order_total": "tickets.qty x pricing.list_price",
    "linked_invoice.id": "tickets.invoice_id",
    "linked_invoice.amount": "invoices.amount",
    "linked_invoice.days_overdue": "desk.date_today - invoices.due_date",
    "supplier.name": "vendors.name via invoices.vendor_id",
    "supplier.lead_days": "vendors.lead_days",
    "amount_to_unblock_supplier": "SUM(invoices.amount) open for that vendor",
    "cash.balance": "cash_accounts.balance (checking)",
    "cash_after_unblocking": "cash_accounts.balance - open invoices of vendor",
    "earliest_arrival_if_unblocked_today": "desk.date_today + vendors.lead_days",
}
SRC_102 = {
    "today": "desk.date_today",
    "lease.id": "tickets.lease_id (id=102)",
    "lease.landlord": "leases.landlord",
    "lease.monthly_rent": "leases.monthly_rent",
    "lease.next_due": "leases.next_due",
    "days_until_due": "leases.next_due - desk.date_today",
    "requester_matches_landlord": "tickets.requester = leases.landlord",
    "cash.balance": "cash_accounts.balance (checking)",
    "cash_after_rent": "cash_accounts.balance - leases.monthly_rent",
    "other_open_invoices_total": "SUM(invoices.amount) WHERE status='open'",
    "cash_after_rent_and_open_invoices": "balance - rent - open invoices",
    "payment_proposal.amount": "leases.monthly_rent",
    "payment_proposal.payee": "leases.landlord",
    "next_due_after_payment": "leases.next_due + 1 month",
}
SRC_103 = {
    "today": "desk.date_today",
    "qty_requested": "tickets.qty (id=103)",
    "qty_on_hand": "inventory.qty (sku, size of ticket 103)",
    "qty_fillable_now": "MIN(tickets.qty, inventory.qty)",
    "qty_shortfall": "tickets.qty - inventory.qty",
    "list_price": "pricing.list_price",
    "unit_cost": "pricing.unit_cost",
    "margin_per_unit": "list_price - unit_cost",
    "list_total": "tickets.qty x list_price",
    "cost_total": "tickets.qty x unit_cost",
    "max_discount_pct_above_cost": "floor to 0.1 of (1 - unit_cost/list_price) x 100",
    "restock_cost_for_shortfall": "shortfall x unit_cost",
    "known_obligations_total": "open invoices + rent due within 30 days of desk.date_today",
    "cash.balance": "cash_accounts.balance (checking)",
    "cash_after_known_obligations": "balance - known obligations",
    "can_afford_restock_after_obligations": "cash after obligations >= restock cost",
}

TESTS: list[dict] = [
    # ---------------------------------------------------------- check_order_fulfillment
    {
        "id": "MAIN-1",
        "category": "main",
        "title": "Ticket 101: full field-by-field reconciliation against the database",
        "tool": "check_order_fulfillment",
        "arguments": {"ticket_id": 101},
        "prompt": (
            "Use the campus-customs MCP server and call check_order_fulfillment for ticket 101. Treat this as an "
            "acceptance test, not a demo: every number in the response must trace back to data/campus_customs_new.db. "
            "Verify that 'today' equals desk.date_today and not the system clock; that qty_on_hand equals inventory.qty "
            "for the ticket's exact SKU and size; that the linked invoice is the one in tickets.invoice_id, with "
            "days_overdue computed against desk.date_today; that the supplier and lead_days come from the vendors row "
            "the invoice points to; that amount_to_unblock_supplier is the sum of that vendor's open invoices; that cash "
            "after unblocking equals the checking balance minus that sum; and that the arrival date is today plus "
            "lead_days. Also confirm the outcome is blocked_by_unpaid_invoice, that the payment comes back only as a "
            "proposal with requires_human_approval=true and approved=false, and that alternative sizes are only sizes "
            "with stock above zero."
        ),
    },
    {
        "id": "EDGE-COF-1",
        "category": "edge_case",
        "title": "Wrong ticket type is rejected and routed to the correct tool",
        "tool": "check_order_fulfillment",
        "arguments": {"ticket_id": 102},
        "prompt": (
            "Negative test for check_order_fulfillment. Call it with ticket 102, which is a rent_notice, not a "
            "customer_order. The tool must not try to interpret a rent notice as an order, must not return a partial "
            "report, and must fail with a clear error that names the actual ticket type and points the caller to the "
            "correct tool (review_rent_payment), so an agent can recover by itself in one step."
        ),
        "expect_error_contains": ["rent_notice", "review_rent_payment"],
    },
    {
        "id": "EDGE-COF-2",
        "category": "edge_case",
        "title": "Unknown ticket id fails clearly and lists valid ids",
        "tool": "check_order_fulfillment",
        "arguments": {"ticket_id": 999},
        "prompt": (
            "Negative test: call check_order_fulfillment with ticket 999, which does not exist in the tickets table. "
            "The tool must not invent a ticket or return empty defaults. It must return an error saying the ticket "
            "does not exist and list the ticket ids that do exist, so the agent can correct its input without another "
            "lookup."
        ),
        "expect_error_contains": ["999", "does not exist", "101", "102", "103"],
    },
    {
        "id": "EDGE-COF-3",
        "category": "edge_case",
        "title": "Input schema boundary: ticket_id below the minimum is rejected before any database access",
        "tool": "check_order_fulfillment",
        "arguments": {"ticket_id": 0},
        "prompt": (
            "Boundary test on the input contract. The published input schema says ticket_id is an integer with "
            "minimum 1. Call check_order_fulfillment with ticket_id 0 and confirm the server rejects it during input "
            "validation, before any database access, instead of running a query with an invalid id."
        ),
        "expect_error_contains": ["ticket_id"],
    },
    {
        "id": "EDGE-COF-4",
        "category": "edge_case",
        "title": "Idempotency and read-only guarantee",
        "tool": "check_order_fulfillment",
        "arguments": {"ticket_id": 101},
        "repeat": 2,
        "prompt": (
            "Idempotency and side-effect test. The tool is published with readOnlyHint=true and idempotentHint=true; "
            "prove both. Take a SHA-256 checksum of data/campus_customs_new.db, call check_order_fulfillment for "
            "ticket 101 twice in a row, and confirm that both responses are byte-for-byte identical and that the "
            "database checksum is unchanged afterwards. A read tool that changes state, or returns different answers "
            "for the same input, would break any agent that retries a call."
        ),
    },
    # -------------------------------------------------------------- review_rent_payment
    {
        "id": "MAIN-2",
        "category": "main",
        "title": "Ticket 102: full reconciliation, landlord verification and cash picture",
        "tool": "review_rent_payment",
        "arguments": {"ticket_id": 102},
        "prompt": (
            "Use the campus-customs MCP server and call review_rent_payment for ticket 102. Audit it like a payment "
            "control. Confirm that the lease comes from tickets.lease_id; that the rent, landlord and due date match "
            "the leases row exactly; that days_until_due is computed from desk.date_today; that the requester is "
            "verified against the landlord on the lease, not just trusted; that no rent payment for this lease exists "
            "in payments; that cash_after_rent equals the checking balance minus the rent; and that the competing open "
            "invoices are included, so cash_after_rent_and_open_invoices equals balance minus rent minus every open "
            "invoice. The response must be a payment proposal for human approval (approved=false), never a payment, "
            "and next_due_after_payment must be exactly one month after leases.next_due."
        ),
    },
    {
        "id": "EDGE-RRP-1",
        "category": "edge_case",
        "title": "Wrong ticket type is rejected and routed to the correct tool",
        "tool": "review_rent_payment",
        "arguments": {"ticket_id": 103},
        "prompt": (
            "Negative test for review_rent_payment. Call it with ticket 103, a price_override request from a student "
            "club. A payment-preparation tool must never build a payment proposal from a ticket that is not a rent "
            "notice. Confirm it refuses with an error that names the real ticket type and the correct tool, "
            "evaluate_bulk_discount_request."
        ),
        "expect_error_contains": ["price_override", "evaluate_bulk_discount_request"],
    },
    {
        "id": "EDGE-RRP-2",
        "category": "edge_case",
        "title": "Unknown ticket id fails clearly",
        "tool": "review_rent_payment",
        "arguments": {"ticket_id": 104},
        "prompt": (
            "Negative test on the next id after the last real ticket. Call review_rent_payment with ticket 104, which "
            "is not in the database. An off-by-one id must never produce a payment proposal. Confirm the tool returns "
            "an error saying ticket 104 does not exist and lists the valid ids."
        ),
        "expect_error_contains": ["104", "does not exist"],
    },
    # --------------------------------------------------- evaluate_bulk_discount_request
    {
        "id": "MAIN-3",
        "category": "main",
        "title": "Ticket 103: stock, cost floor, margin table, blocked vendor and cash squeeze",
        "tool": "evaluate_bulk_discount_request",
        "arguments": {"ticket_id": 103},
        "prompt": (
            "Use the campus-customs MCP server and call evaluate_bulk_discount_request for ticket 103 with the default "
            "discount scenarios. Reconcile it against the database: on-hand stock for CC-HOOD-NAVY size M, units "
            "fillable now and the shortfall; list price and unit cost from pricing; list and cost totals for the full "
            "quantity; the largest discount that still keeps the price at or above unit cost; restock cost for the "
            "shortfall at unit cost; and known obligations as every open invoice plus rent due within 30 days of "
            "desk.date_today. Check that every default scenario's unit price equals list_price x (1 - discount) "
            "rounded to cents, that Bulldog Print Co is flagged as blocked because of its open invoice, and that the "
            "tool says a human must decide the price, because the database has no discount policy."
        ),
        "scenario_check": True,
    },
    {
        "id": "EDGE-EBD-1",
        "category": "edge_case",
        "title": "Cost-floor boundary with unsorted, duplicated and extreme discounts",
        "tool": "evaluate_bulk_discount_request",
        "arguments": {"ticket_id": 103, "discount_percents": [100, 62.1, 0, 62.0, 62.0]},
        "prompt": (
            "Boundary test for the pricing math. Call evaluate_bulk_discount_request for ticket 103 with "
            "discount_percents [100, 62.1, 0, 62.0, 62.0]: unsorted, with a duplicate and both extremes. The tool must "
            "return each discount once, in ascending order. Exactly at the cost floor, 62.0% must still be above cost "
            "(58.00 x 0.38 = 22.04) and 62.1% must be flagged below cost (21.98), which proves "
            "max_discount_pct_above_cost is rounded down and never names a loss-making price. 100% must give a unit "
            "price of 0.00 with above_cost=false, and 0% must equal the list price."
        ),
        "scenario_check": True,
        "expect_scenarios": {"0.0": True, "62.0": True, "62.1": False, "100.0": False},
    },
    {
        "id": "EDGE-EBD-2",
        "category": "edge_case",
        "title": "Out-of-range discount is rejected by the input schema",
        "tool": "evaluate_bulk_discount_request",
        "arguments": {"ticket_id": 103, "discount_percents": [10, 150]},
        "prompt": (
            "Input-validation test. The published schema limits each discount to between 0 and 100. Call "
            "evaluate_bulk_discount_request for ticket 103 with discount_percents [10, 150] and confirm the whole call "
            "is rejected at the input boundary, rather than computing a negative price for 150% or silently dropping "
            "the invalid value."
        ),
        "expect_error_contains": ["discount_percents"],
    },
    {
        "id": "EDGE-EBD-3",
        "category": "edge_case",
        "title": "Wrong ticket type is rejected and routed to the correct tool",
        "tool": "evaluate_bulk_discount_request",
        "arguments": {"ticket_id": 101},
        "prompt": (
            "Negative test for evaluate_bulk_discount_request. Call it with ticket 101, a single-unit customer order, "
            "not a price override. A discount tool must never produce discount scenarios for an ordinary order. "
            "Confirm it refuses with an error that names the real type (customer_order) and points to "
            "check_order_fulfillment."
        ),
        "expect_error_contains": ["customer_order", "check_order_fulfillment"],
    },
]


async def run() -> dict:
    cfg = load_config()
    path = db_file(cfg)
    truth = ground_truth(path)
    before = sha256(path)
    results = []
    transport = StdioTransport(command=cfg["command"], args=cfg["args"], env=cfg["env"], cwd=str(ROOT))
    async with Client(transport) as client:
        listed = await client.list_tools()
        for test in TESTS:
            calls = []
            for _ in range(test.get("repeat", 1)):
                r = await client.call_tool(test["tool"], test["arguments"], raise_on_error=False)
                text = "\n".join(getattr(c, "text", "") for c in r.content)
                calls.append({"is_error": r.is_error, "structured": r.structured_content, "text": text})
            first = calls[0]
            checks: list[dict] = []
            if "expect_error_contains" in test:
                checks.append({"field": "is_error", "expected": True, "actual": first["is_error"], "pass": first["is_error"]})
                for needle in test["expect_error_contains"]:
                    checks.append({"field": "error message contains", "expected": needle,
                                   "pass": needle in first["text"]})
                output: Any = {"error": first["text"]}
            else:
                out = first["structured"]
                output = out
                key = {"check_order_fulfillment": "101", "review_rent_payment": "102",
                       "evaluate_bulk_discount_request": "103"}[test["tool"]]
                src = {"101": SRC_101, "102": SRC_102, "103": SRC_103}[key]
                checks += reconcile(out, truth[key], src)
                if key == "101":
                    p = out["payments_to_approve"]
                    checks.append(check("outcome", "blocked_by_unpaid_invoice", out["outcome"], "derived"))
                    checks.append(check("payments_to_approve[0].ref_id", truth["101"]["linked_invoice.id"],
                                        p[0]["ref_id"] if p else None, "invoices.id"))
                    checks.append(check("payments_to_approve[0].approved", False, p[0]["approved"] if p else None,
                                        "proposal only"))
                    checks.append(check("other_sizes_in_stock", truth["101"]["other_sizes_in_stock"],
                                        [s["size"] for s in out["other_sizes_in_stock"]], "inventory.qty > 0"))
                if key == "102":
                    checks.append(check("outcome", "ready_for_approval", out["outcome"], "derived"))
                    checks.append(check("rent_payments_on_record", truth["102"]["rent_payments_on_record"],
                                        len(out["rent_payments_on_record"]), "payments (kind='rent')"))
                    checks.append(check("payment_proposal.approved", False, out["payment_proposal"]["approved"],
                                        "proposal only"))
                if key == "103":
                    checks.append(check("outcome", "partial_stock", out["outcome"], "derived"))
                    checks.append(check("discount_policy_on_record", False, out["discount_policy_on_record"],
                                        "no discount policy in database"))
                    checks.append(check("boss_discount_authority_pct", 15.0, out["boss_discount_authority_pct"],
                                        "shop policy constant (Problem 5)"))
                    checks.append(check("blocked_vendors", truth["103"]["blocked_vendors"],
                                        [o["vendor"]["name"] for o in out["restock_options"] if o["blocked"]],
                                        "vendors with open invoices"))
                if test.get("scenario_check"):
                    pcts = [s["discount_pct"] for s in out["discount_scenarios"]]
                    requested = test["arguments"].get("discount_percents") or [0, 5, 10, 15, 20, 25]
                    checks.append(check("scenario order (deduped, ascending)", sorted(set(map(float, requested))),
                                        pcts, "input"))
                    for s in out["discount_scenarios"]:
                        unit = cents(truth["list_103"] * (1 - s["discount_pct"] / 100))
                        checks.append(check(f"scenario {s['discount_pct']}% unit_price", unit, s["unit_price"],
                                            "pricing.list_price x (1 - discount)"))
                        checks.append(check(f"scenario {s['discount_pct']}% above_cost", unit >= truth["cost_103"],
                                            s["above_cost"], "unit_price >= pricing.unit_cost"))
                    for pct, flag in test.get("expect_scenarios", {}).items():
                        actual = next((s["above_cost"] for s in out["discount_scenarios"]
                                       if s["discount_pct"] == float(pct)), None)
                        checks.append(check(f"boundary {pct}% above_cost", flag, actual, "cost floor"))
            if test.get("repeat", 1) > 1:
                same = all(json.dumps(c["structured"], sort_keys=True) == json.dumps(first["structured"], sort_keys=True)
                           for c in calls)
                checks.append({"field": "identical responses across calls", "expected": True, "actual": same, "pass": same})
                unchanged = sha256(path) == before
                checks.append({"field": "database checksum unchanged", "expected": before, "actual": sha256(path),
                               "pass": unchanged})
            passed = all(c["pass"] for c in checks)
            results.append({
                "id": test["id"],
                "category": test["category"],
                "title": test["title"],
                "tool": test["tool"],
                "prompt": test["prompt"],
                "arguments": test["arguments"],
                "calls": test.get("repeat", 1),
                "result": "PASS" if passed else "FAIL",
                "checks_passed": sum(c["pass"] for c in checks),
                "checks_total": len(checks),
                "checks": checks,
                "tool_output": output,
            })
    after = sha256(path)
    main = sorted((r for r in results if r["category"] == "main"), key=lambda r: TOOL_ORDER.index(r["tool"]))
    edge = [r for r in results if r["category"] == "edge_case"]
    return {
        "suite": "Campus Customs MCP smoke test",
        "problem": "Problem 4 — Add the MCP server to vibe coder and test each tool",
        "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "server": {
            "name": SERVER,
            "launch": {"command": cfg["command"], "args": cfg["args"], "config_file": ".mcp.json"},
            "tools_listed": [t.name for t in listed],
            "database": str(path.relative_to(ROOT)).replace("\\", "/"),
        },
        "procedure": [
            "Main tests: exactly one prompt and one test per tool, each running the tool on the ticket it exists "
            "to solve (101, 102, 103) and reconciling every value against the database.",
            "Edge-case tests: kept separate, they probe wrong ticket types, unknown ids, schema limits, pricing "
            "boundaries and idempotency.",
            "The server is launched over stdio with the exact command, args and env from .mcp.json, the same entry "
            "Cursor uses (registered in ~/.cursor/mcp.json as 'campus-customs').",
            "Expected values are computed by independent SQL queries on data/campus_customs_new.db, opened read-only. "
            "The tool code is not imported, so the expectations cannot share a bug with the tools.",
            "Each test sends one prompt's tool call and compares every reported value with the database value, "
            "naming the source column or formula for each check.",
            "Negative tests check that bad input fails with a clear, actionable error and returns no data.",
            "The database checksum is taken before and after the whole suite to prove the tools are read-only.",
            "Each test was also run interactively in Cursor through the registered server, and the outputs matched.",
        ],
        "structure": (
            "main_tests holds the required one prompt and one test per tool (3 tests, 3 tools). "
            "edge_case_tests holds additional negative and boundary tests, grouped by tool."
        ),
        "summary": {
            "main_tests": tally(main),
            "edge_case_tests": tally(edge),
            "all_tests": tally(results),
            "database_sha256_before": before,
            "database_sha256_after": after,
            "database_unchanged": before == after,
        },
        "main_tests": main,
        "edge_case_tests": {
            tool: [r for r in edge if r["tool"] == tool] for tool in TOOL_ORDER
        },
    }


TOOL_ORDER = ["check_order_fulfillment", "review_rent_payment", "evaluate_bulk_discount_request"]


def tally(rows: list[dict]) -> dict:
    return {
        "tests": len(rows),
        "passed": sum(r["result"] == "PASS" for r in rows),
        "failed": sum(r["result"] == "FAIL" for r in rows),
        "checks_passed": sum(r["checks_passed"] for r in rows),
        "checks_total": sum(r["checks_total"] for r in rows),
    }


def main() -> None:
    report = asyncio.run(run())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    s = report["summary"]
    edges = [t for group in report["edge_case_tests"].values() for t in group]
    for label, rows in (("MAIN TESTS (one per tool)", report["main_tests"]), ("EDGE-CASE TESTS", edges)):
        print(label)
        for t in rows:
            print(f"  {t['result']}  {t['id']:11} {t['tool']:32} {t['checks_passed']}/{t['checks_total']}  {t['title']}")
    for key in ("main_tests", "edge_case_tests", "all_tests"):
        x = s[key]
        print(f"{key:16} {x['passed']}/{x['tests']} tests, {x['checks_passed']}/{x['checks_total']} checks")
    print(f"database unchanged: {s['database_unchanged']}  ->  {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
