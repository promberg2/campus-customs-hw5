"""Tool logic. One function per ticket type, each taking an open connection.

The functions only read. Anything that would move money is returned as a
PaymentProposal for a human to approve.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Sequence
from datetime import date, timedelta

from fastmcp.exceptions import ToolError

from . import db
from .config import (
    BOSS_DISCOUNT_AUTHORITY_PCT,
    DEFAULT_DISCOUNT_PERCENTS,
    DUE_SOON_DAYS,
    MIN_MARGIN_PCT_AFTER_DISCOUNT,
    OBLIGATION_WINDOW_DAYS,
)
from .db import money
from .models import (
    BulkDiscountReport,
    CashPosition,
    DiscountScenario,
    Invoice,
    Lease,
    OrderFulfillmentReport,
    PaymentProposal,
    PaymentRecord,
    PurchaseOrderRecord,
    RentReviewReport,
    RestockOption,
    SizeStock,
    Ticket,
    Vendor,
)

TOOL_FOR_TICKET_TYPE = {
    "customer_order": "check_order_fulfillment",
    "rent_notice": "review_rent_payment",
    "price_override": "evaluate_bulk_discount_request",
}


def _open_purchase_orders(conn: sqlite3.Connection, sku: str, size: str) -> list[PurchaseOrderRecord]:
    """Pending or approved purchase orders for one SKU and size; rejected ones bring nothing in."""
    if not db.table_exists(conn, "purchase_orders"):
        return []
    rows = conn.execute(
        "SELECT p.*, v.name AS vendor_name FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id "
        "WHERE p.sku = ? AND p.size = ? AND p.status IN ('pending_approval', 'approved') ORDER BY p.id",
        (sku, size),
    ).fetchall()
    return [PurchaseOrderRecord(**dict(r)) for r in rows]


def discount_scenario(list_price: float, unit_cost: float, qty: int, pct: float) -> DiscountScenario:
    unit_price = money(list_price * (1 - pct / 100))
    margin_pct = round(100 * (unit_price - unit_cost) / unit_price, 1) if unit_price else 0.0
    above_cost = unit_price >= unit_cost
    allowed = above_cost and margin_pct >= MIN_MARGIN_PCT_AFTER_DISCOUNT
    return DiscountScenario(
        discount_pct=pct,
        unit_price=unit_price,
        order_total=money(unit_price * qty),
        total_margin=money((unit_price - unit_cost) * qty),
        margin_pct=margin_pct,
        above_cost=above_cost,
        allowed=allowed,
        within_boss_authority=allowed and pct <= BOSS_DISCOUNT_AUTHORITY_PCT,
    )


def max_allowed_discount(list_price: float, unit_cost: float) -> float:
    """Largest discount (rounded down to 0.1) that keeps margin >= MIN_MARGIN_PCT_AFTER_DISCOUNT."""
    if not list_price:
        return 0.0
    floor_price = unit_cost / (1 - MIN_MARGIN_PCT_AFTER_DISCOUNT / 100)
    pct = math.floor(1000 * (1 - floor_price / list_price)) / 10
    while pct > 0 and not discount_scenario(list_price, unit_cost, 1, pct).allowed:
        pct = round(pct - 0.1, 1)
    return max(pct, 0.0)


def _ticket(row: sqlite3.Row) -> Ticket:
    return Ticket(**dict(row))


def _invoice(row: sqlite3.Row, today: date) -> Invoice:
    due = db.parse_date(row["due_date"])
    overdue = row["status"] == "open" and due < today
    return Invoice(
        id=row["id"],
        vendor_id=row["vendor_id"],
        vendor_name=row["vendor_name"],
        amount=money(row["amount"]),
        due_date=row["due_date"],
        status=row["status"],
        description=row["description"],
        is_overdue=overdue,
        days_overdue=(today - due).days if overdue else 0,
    )


def _invoice_by_id(conn: sqlite3.Connection, invoice_id: int, today: date) -> Invoice:
    row = conn.execute(
        "SELECT i.*, v.name AS vendor_name FROM invoices i "
        "JOIN vendors v ON v.id = i.vendor_id WHERE i.id = ?",
        (invoice_id,),
    ).fetchone()
    if row is None:
        raise ToolError(f"Invoice {invoice_id} referenced by the ticket does not exist.")
    return _invoice(row, today)


def _vendor(conn: sqlite3.Connection, vendor_id: int) -> Vendor:
    row = conn.execute("SELECT * FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
    if row is None:
        raise ToolError(f"Vendor {vendor_id} does not exist.")
    return Vendor(**dict(row))


def _cash(conn: sqlite3.Connection) -> CashPosition:
    row = db.cash_account(conn)
    return CashPosition(account=row["name"], balance=money(row["balance"]), as_of=row["date"])


def _require_product_fields(t: sqlite3.Row) -> tuple[str, str, int]:
    if not t["sku"] or not t["size"] or t["qty"] is None:
        raise ToolError(f"Ticket {t['id']} is missing sku, size or qty, so stock cannot be checked.")
    if t["qty"] <= 0:
        raise ToolError(f"Ticket {t['id']} asks for qty {t['qty']}; it must be at least 1.")
    return t["sku"], t["size"], int(t["qty"])


def _size_row(stock: list[sqlite3.Row], sku: str, size: str) -> sqlite3.Row:
    for row in stock:
        if row["size"] == size:
            return row
    sizes = [r["size"] for r in stock]
    if not sizes:
        raise ToolError(f"SKU {sku} is not in inventory.")
    raise ToolError(f"SKU {sku} has no size {size} in inventory. Sizes on record: {sizes}.")


def _product_name(conn: sqlite3.Connection, sku: str) -> str:
    row = conn.execute("SELECT name FROM inventory WHERE sku = ? LIMIT 1", (sku,)).fetchone()
    return row["name"] if row else sku


def _other_sizes(stock: list[sqlite3.Row], size: str) -> list[SizeStock]:
    return [SizeStock(**dict(r)) for r in stock if r["size"] != size and r["qty"] > 0]


# --------------------------------------------------------------------------- 101


def check_order_fulfillment(conn: sqlite3.Connection, ticket_id: int) -> OrderFulfillmentReport:
    now = db.today(conn)
    t = db.ticket(conn, ticket_id, "customer_order", TOOL_FOR_TICKET_TYPE)
    sku, size, qty = _require_product_fields(t)

    stock = db.stock_by_size(conn, sku)
    row = _size_row(stock, sku, size)
    on_hand = int(row["qty"])
    shortfall = max(0, qty - on_hand)
    price = money(db.pricing(conn, sku)["list_price"])
    name = _product_name(conn, sku)

    linked = _invoice_by_id(conn, t["invoice_id"], now) if t["invoice_id"] is not None else None
    supplier = _vendor(conn, linked.vendor_id) if linked else None
    supplier_open = [_invoice(r, now) for r in db.open_invoices(conn, supplier.id)] if supplier else []
    blocked = bool(supplier_open)
    to_unblock = money(sum(i.amount for i in supplier_open))

    cash = _cash(conn)
    cash_after = money(cash.balance - to_unblock)
    affordable = cash_after >= 0

    arrival = None
    if shortfall and supplier:
        arrival = (now + timedelta(days=supplier.lead_days)).isoformat()

    pos = _open_purchase_orders(conn, sku, size)
    approved = [p for p in pos if p.status == "approved"]
    pending = [p for p in pos if p.status == "pending_approval"]
    covered_by = (approved if sum(p.qty for p in approved) >= shortfall
                  else pending if sum(p.qty for p in approved + pending) >= shortfall else [])
    if shortfall and covered_by:
        arrival = max(p.expected_arrival for p in covered_by)

    proposals = [
        PaymentProposal(
            kind="invoice",
            ref_id=i.id,
            payee=i.vendor_name,
            amount=i.amount,
            account=cash.account,
            pay_on=now.isoformat(),
        )
        for i in supplier_open
    ] if shortfall and not covered_by else []

    steps: list[str] = []
    if shortfall == 0:
        outcome = "ready_to_ship"
        summary = f"{qty} x {name} ({size}) is in stock ({on_hand} on hand at {row['location']}). The order can ship today."
        steps.append(f"Pick {qty} x {sku} size {size} from {row['location']} and ship to {t['requester']}.")
        steps.append(f"Reduce inventory for {sku} size {size} from {on_hand} to {on_hand - qty}.")
    elif covered_by and covered_by is approved:
        outcome = "restock_ordered"
        ids = ", ".join(str(p.id) for p in approved)
        summary = (
            f"{name} ({size}) is short by {shortfall}. Purchase order {ids} for it is approved and paid; expected "
            f"arrival {arrival}. Nothing is left to approve for this order."
        )
        steps.append(f"Draft (do not send) a reply to {t['requester']}: size {size} is expected on {arrival}.")
        steps.append("Set the ticket to waiting_on_vendor until the restock arrives, then ship.")
    elif covered_by:
        outcome = "restock_pending_approval"
        ids = ", ".join(str(p.id) for p in pending)
        summary = (
            f"{name} ({size}) is short by {shortfall}. Purchase order {ids} for it waits for a human decision; "
            f"if approved, expected arrival {arrival}."
        )
        steps.append(f"Wait for the human decision on purchase order {ids}; do not create another one.")
    elif supplier is None:
        outcome = "no_supplier_on_record"
        summary = (
            f"Only {on_hand} of {qty} x {name} ({size}) in stock and the ticket names no invoice or supplier, "
            "so the database cannot say who restocks it or when."
        )
        steps.append("Ask a human which vendor should restock this item before promising a date.")
    elif blocked:
        outcome = "blocked_by_unpaid_invoice"
        ids = ", ".join(str(i.id) for i in supplier_open)
        summary = (
            f"{name} ({size}) is short by {shortfall}. The restock comes from {supplier.name}, who will not ship "
            f"while invoice(s) {ids} totalling ${to_unblock:,.2f} are unpaid. If paid today, it can arrive by {arrival}."
        )
        if affordable:
            steps.append(
                f"Request human approval to pay ${to_unblock:,.2f} to {supplier.name} (invoice {ids}); "
                f"cash would go from ${cash.balance:,.2f} to ${cash_after:,.2f}."
            )
        else:
            steps.append(
                f"Cash (${cash.balance:,.2f}) cannot cover ${to_unblock:,.2f} owed to {supplier.name}; escalate to a human."
            )
        steps.append(f"After payment, mark invoice {ids} as paid so {supplier.name} ships again.")
        steps.append(
            f"Draft (do not send) a reply to {t['requester']}: size {size} is out of stock and can arrive by {arrival}."
        )
    else:
        outcome = "awaiting_restock"
        summary = (
            f"{name} ({size}) is short by {shortfall}. {supplier.name} has no open invoices and can deliver by {arrival}."
        )
        steps.append(f"Draft (do not send) a reply to {t['requester']} with the expected date {arrival}.")
    if shortfall and (alts := _other_sizes(stock, size)):
        steps.append(
            "Optionally offer sizes in stock now: " + ", ".join(f"{a.size} ({a.qty})" for a in alts) + "."
        )

    return OrderFulfillmentReport(
        ticket=_ticket(t),
        today=now.isoformat(),
        outcome=outcome,
        summary=summary,
        sku=sku,
        product_name=name,
        size=size,
        location=row["location"],
        qty_requested=qty,
        qty_on_hand=on_hand,
        qty_shortfall=shortfall,
        can_ship_now=shortfall == 0,
        unit_price=price,
        order_total=money(price * qty),
        other_sizes_in_stock=_other_sizes(stock, size),
        linked_invoice=linked,
        supplier=supplier,
        supplier_open_invoices=supplier_open,
        supplier_blocked=blocked,
        amount_to_unblock_supplier=to_unblock,
        cash=cash,
        cash_after_unblocking=cash_after,
        can_afford_to_unblock=affordable,
        earliest_arrival_if_unblocked_today=arrival,
        payments_to_approve=proposals,
        purchase_orders=pos,
        next_steps=steps,
    )


# --------------------------------------------------------------------------- 102


def review_rent_payment(conn: sqlite3.Connection, ticket_id: int) -> RentReviewReport:
    now = db.today(conn)
    t = db.ticket(conn, ticket_id, "rent_notice", TOOL_FOR_TICKET_TYPE)
    if t["lease_id"] is None:
        raise ToolError(f"Ticket {ticket_id} does not reference a lease, so the rent cannot be checked.")
    row = conn.execute("SELECT * FROM leases WHERE id = ?", (t["lease_id"],)).fetchone()
    if row is None:
        raise ToolError(f"Lease {t['lease_id']} referenced by ticket {ticket_id} does not exist.")
    lease = Lease(**{**dict(row), "monthly_rent": money(row["monthly_rent"])})

    due = db.parse_date(lease.next_due)
    days = (due - now).days
    if days < 0:
        due_status = "overdue"
    elif days == 0:
        due_status = "due_today"
    elif days <= DUE_SOON_DAYS:
        due_status = "due_soon"
    else:
        due_status = "upcoming"

    matches = t["requester"].strip().casefold() == lease.landlord.strip().casefold()

    payments = [
        PaymentRecord(**{**dict(p), "amount": money(p["amount"])})
        for p in conn.execute(
            "SELECT * FROM payments WHERE kind = 'rent' AND ref_id = ? ORDER BY paid_at DESC, id DESC",
            (lease.id,),
        )
    ]
    # pay_rent moves next_due forward, so after payment the notice's period lies before next_due
    notice_day = db.parse_date(t["created_at"])
    notice_due = due
    while db.add_months(notice_due, -1) >= notice_day:
        notice_due = db.add_months(notice_due, -1)
    period_start = db.add_months(notice_due, -1)
    paid_by = next(
        (p for p in payments if db.parse_date(p.paid_at) > period_start and p.amount >= lease.monthly_rent), None
    )
    paid = paid_by is not None

    cash = _cash(conn)
    after_rent = money(cash.balance - lease.monthly_rent)
    sufficient = after_rent >= 0
    others = [_invoice(r, now) for r in db.open_invoices(conn)]
    others_total = money(sum(i.amount for i in others))
    after_all = money(after_rent - others_total)

    if paid:
        outcome = "already_paid"
    elif not matches:
        outcome = "requester_does_not_match_landlord"
    elif not sufficient:
        outcome = "insufficient_funds"
    else:
        outcome = "ready_for_approval"

    proposal = None
    if outcome == "ready_for_approval":
        proposal = PaymentProposal(
            kind="rent",
            ref_id=lease.id,
            payee=lease.landlord,
            amount=lease.monthly_rent,
            account=cash.account,
            pay_on=now.isoformat(),
        )

    when = {
        "overdue": f"{-days} day(s) overdue",
        "due_today": "due today",
        "due_soon": f"due in {days} day(s)",
        "upcoming": f"due in {days} day(s)",
    }[due_status]
    next_due = lease.next_due if paid else db.add_months(due, 1).isoformat()

    steps: list[str] = []
    if outcome == "already_paid":
        summary = (
            f"Rent of ${lease.monthly_rent:,.2f} for {lease.space_name} due {notice_due.isoformat()}, the period this "
            f"notice is about, was paid on {paid_by.paid_at} (payment {paid_by.id}, approved by {paid_by.approved_by}). "
            f"The next rent is due {lease.next_due}. Do not pay again."
        )
        steps.append(f"Close ticket {ticket_id} as resolved: the rent in the notice is paid.")
    elif outcome == "requester_does_not_match_landlord":
        summary = (
            f"The notice comes from '{t['requester']}', but the lease landlord is '{lease.landlord}'. "
            "Do not pay until a human verifies it."
        )
        steps.append("Escalate to a human: the requester does not match the landlord on the lease.")
    elif outcome == "insufficient_funds":
        summary = (
            f"Rent of ${lease.monthly_rent:,.2f} is {when}, but {cash.account} holds only ${cash.balance:,.2f}. "
            "The payment would overdraw the account."
        )
        steps.append("Escalate to a human: there is not enough cash to pay the rent.")
    else:
        summary = (
            f"Rent of ${lease.monthly_rent:,.2f} for {lease.space_name} to {lease.landlord} is {when} "
            f"({lease.next_due}). The requester matches the lease and cash covers it "
            f"(${cash.balance:,.2f} -> ${after_rent:,.2f})."
        )
        steps.append(
            f"Request human approval to pay ${lease.monthly_rent:,.2f} rent to {lease.landlord} from {cash.account}."
        )
        steps.append(
            f"After payment: record it in payments, set {cash.account} to ${after_rent:,.2f}, "
            f"move lease {lease.id} next_due to {next_due}, and close ticket {ticket_id}."
        )
    if others:
        ids = ", ".join(str(i.id) for i in others)
        steps.append(
            f"Plan cash together with open invoice(s) {ids} (${others_total:,.2f}): paying everything leaves "
            f"${after_all:,.2f}."
            + (" That is not enough for all of them; a human must choose the order." if after_all < 0 else "")
        )

    return RentReviewReport(
        ticket=_ticket(t),
        today=now.isoformat(),
        outcome=outcome,
        summary=summary,
        lease=lease,
        days_until_due=days,
        due_status=due_status,
        requester_matches_landlord=matches,
        notice_period_due=notice_due.isoformat(),
        already_paid_this_period=paid,
        rent_payments_on_record=payments,
        cash=cash,
        cash_after_rent=after_rent,
        sufficient_funds=sufficient,
        other_open_invoices=others,
        other_open_invoices_total=others_total,
        cash_after_rent_and_open_invoices=after_all,
        covers_all_known_obligations=after_all >= 0,
        payment_proposal=proposal,
        next_due_after_payment=next_due,
        next_steps=steps,
    )


# --------------------------------------------------------------------------- 103


def evaluate_bulk_discount_request(
    conn: sqlite3.Connection,
    ticket_id: int,
    discount_percents: Sequence[float] | None = None,
) -> BulkDiscountReport:
    now = db.today(conn)
    t = db.ticket(conn, ticket_id, "price_override", TOOL_FOR_TICKET_TYPE)
    sku, size, qty = _require_product_fields(t)

    stock = db.stock_by_size(conn, sku)
    row = _size_row(stock, sku, size)
    on_hand = int(row["qty"])
    fillable = min(qty, on_hand)
    shortfall = qty - fillable
    name = _product_name(conn, sku)

    p = db.pricing(conn, sku)
    list_price = money(p["list_price"])
    unit_cost = money(p["unit_cost"])
    margin_unit = money(list_price - unit_cost)
    margin_pct = round(100 * margin_unit / list_price, 1) if list_price else 0.0
    # Rounded down: rounding up could name a discount that already sells below cost.
    max_discount = math.floor(1000 * (1 - unit_cost / list_price)) / 10 if list_price else 0.0

    percents = sorted(set(discount_percents if discount_percents else DEFAULT_DISCOUNT_PERCENTS))
    if any(not 0 <= d <= 100 for d in percents):
        raise ToolError("discount_percents must be between 0 and 100.")
    scenarios = [discount_scenario(list_price, unit_cost, qty, d) for d in percents]

    options = []
    for v in conn.execute("SELECT * FROM vendors ORDER BY id"):
        vendor = Vendor(**dict(v))
        inv = [_invoice(r, now) for r in db.open_invoices(conn, vendor.id)]
        options.append(
            RestockOption(
                vendor=vendor,
                open_invoices=inv,
                open_invoice_total=money(sum(i.amount for i in inv)),
                blocked=bool(inv),
                earliest_arrival_if_ordered_today=(now + timedelta(days=vendor.lead_days)).isoformat(),
            )
        )

    cash = _cash(conn)
    window_end = now + timedelta(days=OBLIGATION_WINDOW_DAYS)
    invoices_total = sum(i.amount for o in options for i in o.open_invoices)
    rent_total = sum(
        r["monthly_rent"]
        for r in conn.execute("SELECT monthly_rent, next_due FROM leases")
        if db.parse_date(r["next_due"]) <= window_end
    )
    obligations = money(invoices_total + rent_total)
    cash_after = money(cash.balance - obligations)
    restock_cost = money(shortfall * unit_cost)

    if shortfall == 0:
        outcome = "can_fill_in_full"
    elif fillable > 0:
        outcome = "partial_stock"
    else:
        outcome = "out_of_stock"

    max_allowed = max_allowed_discount(list_price, unit_cost)
    summary = (
        f"{t['requester']} asks for {qty} x {name} ({size}) at a discount. {on_hand} in stock"
        + (f", {shortfall} short." if shortfall else ", enough to fill the order.")
        + f" List total ${money(list_price * qty):,.2f}; cost floor ${unit_cost:,.2f}/unit "
        f"(break-even at {max_discount}% off). Business rules: margin must stay at or above "
        f"{MIN_MARGIN_PCT_AFTER_DISCOUNT:g}% (max {max_allowed}% off); the Boss may grant up to "
        f"{BOSS_DISCOUNT_AUTHORITY_PCT:g}%, anything above needs a named human approver."
    )

    steps = [
        f"Boss decides the discount: up to {BOSS_DISCOUNT_AUTHORITY_PCT:g}% alone, up to {max_allowed}% with human "
        "approval, never more; the scenarios show margin and authority for each option."
    ]
    if shortfall:
        steps.append(f"Reserve the {fillable} in stock at {row['location']} and offer them now.")
        blocked = [o for o in options if o.blocked]
        if blocked:
            names = ", ".join(f"{o.vendor.name} (${o.open_invoice_total:,.2f} open)" for o in blocked)
            steps.append(
                f"The remaining {shortfall} need a restock (${restock_cost:,.2f} at cost). "
                f"Blocked vendors until paid: {names}. Pick the vendor whose specialty fits the product."
            )
        else:
            steps.append(f"The remaining {shortfall} need a restock (${restock_cost:,.2f} at cost).")
        if cash_after < restock_cost:
            steps.append(
                f"Cash after known obligations is ${cash_after:,.2f}, below the ${restock_cost:,.2f} restock cost: "
                "flag this to a human before committing to the full quantity."
            )
    else:
        steps.append(f"All {qty} can be picked from {row['location']} once the price is approved.")
    alts = _other_sizes(stock, size)
    if shortfall and alts:
        steps.append("Sizes in stock now: " + ", ".join(f"{a.size} ({a.qty})" for a in alts) + ".")
    steps.append(f"Draft (do not send) a reply to {t['requester']} with the approved price and delivery plan.")

    return BulkDiscountReport(
        ticket=_ticket(t),
        today=now.isoformat(),
        outcome=outcome,
        summary=summary,
        sku=sku,
        product_name=name,
        size=size,
        location=row["location"],
        qty_requested=qty,
        qty_on_hand=on_hand,
        qty_fillable_now=fillable,
        qty_shortfall=shortfall,
        other_sizes_in_stock=alts,
        list_price=list_price,
        unit_cost=unit_cost,
        margin_per_unit=margin_unit,
        margin_pct=margin_pct,
        list_total=money(list_price * qty),
        cost_total=money(unit_cost * qty),
        max_discount_pct_above_cost=max_discount,
        discount_scenarios=scenarios,
        boss_discount_authority_pct=BOSS_DISCOUNT_AUTHORITY_PCT,
        min_margin_pct_after_discount=MIN_MARGIN_PCT_AFTER_DISCOUNT,
        restock_cost_for_shortfall=restock_cost,
        restock_options=options,
        cash=cash,
        known_obligations_total=obligations,
        cash_after_known_obligations=cash_after,
        can_afford_restock_after_obligations=cash_after >= restock_cost,
        next_steps=steps,
    )
