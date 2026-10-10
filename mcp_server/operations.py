"""Tool logic for the agent team, grouped by the agent that owns it.

Read functions take a read-only connection. Write functions take a connection
from `db.transaction()`, so each call commits completely or not at all. Every
write is guarded here, in code, so a mistaken or manipulated agent cannot break
a business rule even if its prompt is ignored.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Sequence
from datetime import timedelta

from fastmcp.exceptions import ToolError

from . import db
from .config import (
    AGENT_NAMES,
    BOSS_DISCOUNT_AUTHORITY_PCT,
    DEFAULT_DISCOUNT_PERCENTS,
    LOW_STOCK_THRESHOLD,
    MAX_TEXT_FIELD,
    OBLIGATION_WINDOW_DAYS,
    RESERVED_APPROVER_NAMES,
)
from .db import money
from .models import (
    CashPositionReport,
    CustomerOrderView,
    DraftList,
    DraftRecord,
    InvoiceList,
    LeaseDue,
    LeaseStatusReport,
    MarginReport,
    PaymentReceipt,
    PaymentRecord,
    PriceOverrideRecord,
    PurchaseOrderRecord,
    PurchaseOrderDecision,
    PurchaseOrderResult,
    ShopSnapshot,
    ShortfallItem,
    ShortfallReport,
    StockMovementRecord,
    StockReport,
    StockRow,
    TicketBrief,
    TicketDetail,
    TicketList,
    TicketUpdateResult,
    Lease,
    Vendor,
    VendorStatus,
    VendorStatusReport,
)
from .tools import (
    TOOL_FOR_TICKET_TYPE,
    _cash,
    _invoice,
    _ticket,
    _vendor,
    discount_scenario,
    max_allowed_discount,
)

TICKET_STATUSES = (
    "open",
    "in_progress",
    "waiting_on_approval",
    "waiting_on_vendor",
    "waiting_on_customer",
    "resolved",
    "rejected",
)
CUSTOMER_TICKET_TYPES = {"customer_order", "price_override"}
INTERNAL_TERMS = (
    "unit cost", "unit_cost", "our cost", "cost price", "margin", "markup", "cash balance", "bank balance",
    "checking account", "invoice", "overdue", "unpaid", "owe ", "purchase order", "approved_by", "landlord",
)


# --------------------------------------------------------------------------- guards


def require_text(value: str, field: str, *, max_len: int = MAX_TEXT_FIELD) -> str:
    text = (value or "").strip()
    if not text:
        raise ToolError(f"{field} must not be empty.")
    if len(text) > max_len:
        raise ToolError(f"{field} is {len(text)} characters; the limit is {max_len}.")
    return text


def require_human_approver(approved_by: str | None) -> str:
    name = (approved_by or "").strip()
    if name.casefold() in RESERVED_APPROVER_NAMES or len(name) < 2 or len(name) > 80:
        raise ToolError(
            "This action needs a named human approver. approved_by is filled in by the approval system "
            "after a person says yes; agents cannot approve their own actions."
        )
    return name


def acting(agent: str | None) -> str:
    name = (agent or "").strip().casefold()
    return name if name in AGENT_NAMES else "unknown"


def _ticket_row(conn: sqlite3.Connection, ticket_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        known = [r["id"] for r in conn.execute("SELECT id FROM tickets ORDER BY id")]
        raise ToolError(f"Ticket {ticket_id} does not exist. Known ticket ids: {known}.")
    return row


def _stock_status(qty: int, threshold: int = LOW_STOCK_THRESHOLD) -> str:
    if qty <= 0:
        return "out_of_stock"
    if qty <= threshold:
        return "low"
    return "in_stock"


def _stock_row(row: sqlite3.Row, threshold: int = LOW_STOCK_THRESHOLD) -> StockRow:
    return StockRow(
        sku=row["sku"], name=row["name"], size=row["size"], qty=row["qty"], location=row["location"],
        stock_status=_stock_status(row["qty"], threshold),
    )


def _lease_due(conn: sqlite3.Connection, row: sqlite3.Row) -> LeaseDue:
    now = db.today(conn)
    due = db.parse_date(row["next_due"])
    days = (due - now).days
    status = "overdue" if days < 0 else "due_today" if days == 0 else "due_soon" if days <= 7 else "upcoming"
    period_start = db.add_months(due, -1)
    rows = conn.execute("SELECT * FROM payments WHERE kind='rent' AND ref_id=? ORDER BY paid_at DESC, id DESC",
                        (row["id"],)).fetchall()
    paid = any(db.parse_date(p["paid_at"]) > period_start and p["amount"] >= row["monthly_rent"] for p in rows)
    last = PaymentRecord(**{**dict(rows[0]), "amount": money(rows[0]["amount"])}) if rows else None
    lease = Lease(**{**dict(row), "monthly_rent": money(row["monthly_rent"])})
    return LeaseDue(lease=lease, days_until_due=days, due_status=status, paid_this_period=paid,
                    last_rent_payment=last)


def _brief(row: sqlite3.Row) -> TicketBrief:
    return TicketBrief(**{k: row[k] for k in TicketBrief.model_fields})


def _drafts(conn: sqlite3.Connection, ticket_id: int | None = None) -> list[DraftRecord]:
    if not db.table_exists(conn, "drafts"):
        return []
    sql, params = "SELECT * FROM drafts", ()
    if ticket_id is not None:
        sql, params = sql + " WHERE ticket_id = ?", (ticket_id,)
    return [DraftRecord(**dict(r)) for r in conn.execute(sql + " ORDER BY id", params)]


def _price_override(conn: sqlite3.Connection, ticket_id: int) -> PriceOverrideRecord | None:
    if not db.table_exists(conn, "price_overrides"):
        return None
    row = conn.execute("SELECT * FROM price_overrides WHERE ticket_id = ?", (ticket_id,)).fetchone()
    return PriceOverrideRecord(**dict(row)) if row else None


def _purchase_orders(conn: sqlite3.Connection, vendor_id: int | None = None, status: str | None = None
                     ) -> list[PurchaseOrderRecord]:
    if not db.table_exists(conn, "purchase_orders"):
        return []
    sql = "SELECT p.*, v.name AS vendor_name FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id WHERE 1=1"
    params: list = []
    if vendor_id is not None:
        sql += " AND p.vendor_id = ?"
        params.append(vendor_id)
    if status is not None:
        sql += " AND p.status = ?"
        params.append(status)
    return [PurchaseOrderRecord(**dict(r)) for r in conn.execute(sql + " ORDER BY p.id", params)]


def _obligations(conn: sqlite3.Connection) -> tuple[list, float, float, list[LeaseDue], float]:
    now = db.today(conn)
    invoices = [_invoice(r, now) for r in db.open_invoices(conn)]
    inv_total = money(sum(i.amount for i in invoices))
    overdue = money(sum(i.amount for i in invoices if i.is_overdue))
    window_end = now + timedelta(days=OBLIGATION_WINDOW_DAYS)
    leases = [_lease_due(conn, r) for r in conn.execute("SELECT * FROM leases ORDER BY next_due")]
    due = [ld for ld in leases if db.parse_date(ld.lease.next_due) <= window_end]
    rent = money(sum(ld.lease.monthly_rent for ld in due if not ld.paid_this_period))
    return invoices, inv_total, overdue, due, rent


def _accounts(conn: sqlite3.Connection):
    from .models import CashPosition
    return [CashPosition(account=r["name"], balance=money(r["balance"]), as_of=r["date"])
            for r in conn.execute("SELECT * FROM cash_accounts ORDER BY name")]


# --------------------------------------------------------------------------- shared / boss


def get_shop_snapshot(conn: sqlite3.Connection) -> ShopSnapshot:
    now = db.today(conn)
    desk = conn.execute("SELECT notes FROM desk LIMIT 1").fetchone()
    accounts = _accounts(conn)
    cash_total = money(sum(a.balance for a in accounts))
    invoices, inv_total, overdue, rent_due, rent_total = _obligations(conn)
    obligations = money(inv_total + rent_total)
    stock = [_stock_row(r) for r in conn.execute("SELECT * FROM inventory ORDER BY rowid")]
    tickets = [_brief(r) for r in conn.execute(
        "SELECT * FROM tickets WHERE status NOT IN ('resolved','rejected') ORDER BY created_at, id")]
    return ShopSnapshot(
        today=now.isoformat(),
        desk_notes=desk["notes"] if desk else None,
        accounts=accounts,
        cash_total=cash_total,
        open_tickets=tickets,
        open_invoices=invoices,
        open_invoices_total=inv_total,
        overdue_invoices_total=overdue,
        rent_due_within_30_days=rent_due,
        obligations_next_30_days=obligations,
        cash_after_obligations=money(cash_total - obligations),
        out_of_stock=[s for s in stock if s.stock_status == "out_of_stock"],
        low_stock=[s for s in stock if s.stock_status == "low"],
        pending_purchase_orders=len(_purchase_orders(conn, status="pending_approval")),
        customer_drafts=len(_drafts(conn)),
    )


def list_tickets(conn: sqlite3.Connection, status: str | None) -> TicketList:
    if status is not None and status not in TICKET_STATUSES:
        raise ToolError(f"Unknown status '{status}'. Use one of {list(TICKET_STATUSES)} or omit it.")
    sql, params = "SELECT * FROM tickets", ()
    if status:
        sql, params = sql + " WHERE status = ?", (status,)
    return TicketList(status_filter=status, tickets=[_brief(r) for r in conn.execute(sql + " ORDER BY created_at, id", params)])


def get_ticket(conn: sqlite3.Connection, ticket_id: int) -> TicketDetail:
    now = db.today(conn)
    row = _ticket_row(conn, ticket_id)
    invoice = None
    if row["invoice_id"] is not None:
        inv = conn.execute(
            "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.id=?",
            (row["invoice_id"],),
        ).fetchone()
        invoice = _invoice(inv, now) if inv else None
    lease = None
    if row["lease_id"] is not None:
        lr = conn.execute("SELECT * FROM leases WHERE id = ?", (row["lease_id"],)).fetchone()
        lease = Lease(**{**dict(lr), "monthly_rent": money(lr["monthly_rent"])}) if lr else None
    stock = [
        _stock_row(r) for r in conn.execute("SELECT * FROM inventory WHERE sku = ? ORDER BY rowid", (row["sku"],))
    ] if row["sku"] else []
    pos = [p for p in _purchase_orders(conn) if p.ticket_id == ticket_id]
    paid = [("invoice", row["invoice_id"]), ("rent", row["lease_id"])] + [("purchase_order", p.id) for p in pos]
    payments = [
        PaymentRecord(**{**dict(r), "amount": money(r["amount"])}) for kind, ref in paid if ref is not None
        for r in conn.execute("SELECT * FROM payments WHERE kind = ? AND ref_id = ? ORDER BY id", (kind, ref))
    ]
    return TicketDetail(
        ticket=_ticket(row),
        today=now.isoformat(),
        handled_by=TOOL_FOR_TICKET_TYPE.get(row["type"], "none"),
        linked_invoice=invoice,
        linked_lease=lease,
        product_stock=stock,
        drafts=_drafts(conn, ticket_id),
        price_override=_price_override(conn, ticket_id),
        purchase_orders=pos,
        payments=payments,
    )


def update_ticket_status(conn: sqlite3.Connection, ticket_id: int, status: str, note: str, agent: str
                         ) -> TicketUpdateResult:
    if status not in TICKET_STATUSES:
        raise ToolError(f"Unknown status '{status}'. Use one of {list(TICKET_STATUSES)}.")
    note = require_text(note, "note", max_len=600)
    row = _ticket_row(conn, ticket_id)
    stamp = f"[{db.now_stamp(conn)} {acting(agent)}: {row['status']} -> {status}] {note}"
    notes = f"{row['notes']}\n{stamp}" if row["notes"] else stamp
    conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
    return TicketUpdateResult(ticket_id=ticket_id, previous_status=row["status"], new_status=status,
                              note_appended=stamp, notes_after=notes)


def record_discount_decision(conn: sqlite3.Connection, ticket_id: int, discount_pct: float, rationale: str,
                             agent: str, approved_by: str | None) -> PriceOverrideRecord:
    row = _ticket_row(conn, ticket_id)
    if row["type"] != "price_override":
        raise ToolError(f"Ticket {ticket_id} is a '{row['type']}' ticket; discounts are only recorded on price_override tickets.")
    if not row["sku"] or not row["qty"]:
        raise ToolError(f"Ticket {ticket_id} has no sku or qty.")
    if _price_override(conn, ticket_id):
        raise ToolError(f"A discount decision for ticket {ticket_id} is already recorded; it cannot be changed by an agent.")
    rationale = require_text(rationale, "rationale", max_len=600)
    p = db.pricing(conn, row["sku"])
    s = discount_scenario(money(p["list_price"]), money(p["unit_cost"]), int(row["qty"]), float(discount_pct))
    if not s.above_cost:
        raise ToolError(f"{discount_pct}% off gives ${s.unit_price:.2f}, below the unit cost. Refused.")
    if not s.allowed:
        cap = max_allowed_discount(money(p["list_price"]), money(p["unit_cost"]))
        raise ToolError(f"{discount_pct}% off leaves a {s.margin_pct}% margin, below the minimum. The maximum is {cap}%.")
    approver = None
    if discount_pct > BOSS_DISCOUNT_AUTHORITY_PCT:
        approver = require_human_approver(approved_by)
    stamp = db.now_stamp(conn)
    cur = conn.execute(
        "INSERT INTO price_overrides (ticket_id, sku, qty, list_price, discount_pct, unit_price, order_total, "
        "decided_by, approved_by, rationale, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticket_id, row["sku"], row["qty"], money(p["list_price"]), float(discount_pct), s.unit_price,
         s.order_total, acting(agent), approver, rationale, stamp),
    )
    return PriceOverrideRecord(**dict(conn.execute("SELECT * FROM price_overrides WHERE id=?", (cur.lastrowid,)).fetchone()))


# --------------------------------------------------------------------------- inventory


def check_stock(conn: sqlite3.Connection, sku: str, size: str | None) -> StockReport:
    rows = conn.execute("SELECT * FROM inventory WHERE sku = ? ORDER BY rowid", (sku,)).fetchall()
    if not rows:
        known = [r["sku"] for r in conn.execute("SELECT DISTINCT sku FROM inventory ORDER BY sku")]
        raise ToolError(f"SKU {sku} is not in inventory. Known SKUs: {known}.")
    sizes = [_stock_row(r) for r in rows]
    requested = None
    if size is not None:
        requested = next((s for s in sizes if s.size == size), None)
        if requested is None:
            raise ToolError(f"SKU {sku} has no size {size}. Sizes on record: {[s.size for s in sizes]}.")
    return StockReport(
        sku=sku, product_name=rows[0]["name"], list_price=money(db.pricing(conn, sku)["list_price"]),
        total_units=sum(s.qty for s in sizes), sizes=sizes, requested_size=requested,
    )


def find_stock_shortfalls(conn: sqlite3.Connection, threshold: int) -> ShortfallReport:
    demand: dict[tuple[str, str], tuple[int, list[int]]] = {}
    for t in conn.execute(
        "SELECT id, sku, size, qty FROM tickets WHERE sku IS NOT NULL AND size IS NOT NULL AND qty IS NOT NULL "
        "AND type IN ('customer_order','price_override') AND status NOT IN ('resolved','rejected')"
    ):
        qty, ids = demand.get((t["sku"], t["size"]), (0, []))
        demand[(t["sku"], t["size"])] = (qty + t["qty"], ids + [t["id"]])
    items = []
    for r in conn.execute("SELECT * FROM inventory ORDER BY rowid"):
        need, ids = demand.get((r["sku"], r["size"]), (0, []))
        short = max(0, need - r["qty"])
        status = _stock_status(r["qty"], threshold)
        if short or status != "in_stock":
            items.append(ShortfallItem(
                sku=r["sku"], name=r["name"], size=r["size"], location=r["location"], qty_on_hand=r["qty"],
                open_ticket_demand=need, shortfall=short, ticket_ids=ids, stock_status=status,
            ))
    return ShortfallReport(
        today=db.today(conn).isoformat(), low_stock_threshold=threshold, items=items,
        out_of_stock_count=sum(i.stock_status == "out_of_stock" for i in items),
        low_stock_count=sum(i.stock_status == "low" for i in items),
        rows_short_for_open_tickets=sum(i.shortfall > 0 for i in items),
    )


def get_vendor_status(conn: sqlite3.Connection, vendor_id: int | None) -> VendorStatusReport:
    now = db.today(conn)
    rows = conn.execute("SELECT * FROM vendors" + (" WHERE id = ?" if vendor_id is not None else "") + " ORDER BY id",
                        (vendor_id,) if vendor_id is not None else ()).fetchall()
    if vendor_id is not None and not rows:
        raise ToolError(f"Vendor {vendor_id} does not exist.")
    vendors = []
    for v in rows:
        inv = [_invoice(r, now) for r in db.open_invoices(conn, v["id"])]
        vendors.append(VendorStatus(
            vendor=Vendor(**dict(v)), open_invoices=inv, open_invoice_total=money(sum(i.amount for i in inv)),
            blocked=bool(inv), earliest_arrival_if_ordered_today=(now + timedelta(days=v["lead_days"])).isoformat(),
            pending_purchase_orders=_purchase_orders(conn, v["id"], "pending_approval"),
        ))
    return VendorStatusReport(
        today=now.isoformat(), vendors=vendors,
        note="A vendor with an open unpaid invoice will not ship. The database does not link products to vendors; "
             "match by vendors.specialty and say so.",
    )


def ship_order_from_stock(conn: sqlite3.Connection, ticket_id: int, qty: int, agent: str) -> StockMovementRecord:
    t = _ticket_row(conn, ticket_id)
    if t["type"] not in CUSTOMER_TICKET_TYPES:
        raise ToolError(f"Ticket {ticket_id} is a '{t['type']}' ticket; only customer orders ship stock.")
    if t["status"] in ("resolved", "rejected"):
        raise ToolError(f"Ticket {ticket_id} is already {t['status']}.")
    if qty < 1:
        raise ToolError("qty must be at least 1.")
    if t["type"] == "price_override" and _price_override(conn, ticket_id) is None:
        raise ToolError(f"Ticket {ticket_id} has no recorded price decision yet; the Boss must decide the price first.")
    shipped = -(conn.execute(
        "SELECT COALESCE(SUM(qty_change),0) FROM stock_movements WHERE ticket_id = ?", (ticket_id,)).fetchone()[0])
    remaining = int(t["qty"]) - shipped
    if qty > remaining:
        raise ToolError(f"Ticket {ticket_id} asks for {t['qty']}; {shipped} already shipped, so at most {remaining} more.")
    row = conn.execute("SELECT qty FROM inventory WHERE sku=? AND size=?", (t["sku"], t["size"])).fetchone()
    if row is None or row["qty"] < qty:
        raise ToolError(f"Only {row['qty'] if row else 0} of {t['sku']} size {t['size']} on hand; cannot ship {qty}.")
    after = row["qty"] - qty
    conn.execute("UPDATE inventory SET qty = ? WHERE sku=? AND size=?", (after, t["sku"], t["size"]))
    cur = conn.execute(
        "INSERT INTO stock_movements (ticket_id, sku, size, qty_change, qty_after, reason, created_by, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (ticket_id, t["sku"], t["size"], -qty, after, f"shipped for ticket {ticket_id}", acting(agent), db.now_stamp(conn)),
    )
    return StockMovementRecord(**dict(conn.execute("SELECT * FROM stock_movements WHERE id=?", (cur.lastrowid,)).fetchone()))


# --------------------------------------------------------------------------- accounting


def get_cash_position(conn: sqlite3.Connection) -> CashPositionReport:
    accounts = _accounts(conn)
    cash_total = money(sum(a.balance for a in accounts))
    invoices, inv_total, overdue, rent_due, rent_total = _obligations(conn)
    obligations = money(inv_total + rent_total)
    payments = [PaymentRecord(**{**dict(p), "amount": money(p["amount"])})
                for p in conn.execute("SELECT * FROM payments ORDER BY id")]
    return CashPositionReport(
        today=db.today(conn).isoformat(), accounts=accounts, cash_total=cash_total, open_invoices=invoices,
        open_invoices_total=inv_total, overdue_invoices_total=overdue, rent_due_within_30_days=rent_due,
        unpaid_rent_due_within_30_days_total=rent_total, obligations_total=obligations,
        cash_after_obligations=money(cash_total - obligations),
        pending_purchase_orders_total=money(sum(p.total_cost for p in _purchase_orders(conn, status="pending_approval"))),
        payments=payments,
    )


def list_invoices(conn: sqlite3.Connection, status: str | None) -> InvoiceList:
    if status not in (None, "open", "paid"):
        raise ToolError("status must be 'open', 'paid' or omitted.")
    now = db.today(conn)
    sql = "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id"
    rows = conn.execute(sql + (" WHERE i.status = ?" if status else "") + " ORDER BY i.due_date, i.id",
                        (status,) if status else ()).fetchall()
    invoices = [_invoice(r, now) for r in rows]
    return InvoiceList(today=now.isoformat(), status_filter=status, invoices=invoices,
                       total=money(sum(i.amount for i in invoices)))


def analyze_margin(conn: sqlite3.Connection, sku: str, qty: int, discount_percents: Sequence[float] | None
                   ) -> MarginReport:
    if qty < 1:
        raise ToolError("qty must be at least 1.")
    p = db.pricing(conn, sku)
    name_row = conn.execute("SELECT name FROM inventory WHERE sku=? LIMIT 1", (sku,)).fetchone()
    lp, uc = money(p["list_price"]), money(p["unit_cost"])
    pcts = sorted(set(discount_percents or DEFAULT_DISCOUNT_PERCENTS))
    return MarginReport(
        sku=sku, product_name=name_row["name"] if name_row else sku, qty=qty, list_price=lp, unit_cost=uc,
        margin_per_unit=money(lp - uc), margin_pct=round(100 * (lp - uc) / lp, 1) if lp else 0.0,
        max_discount_pct_above_cost=(int(1000 * (1 - uc / lp)) / 10) if lp else 0.0,
        max_discount_pct_allowed=max_allowed_discount(lp, uc),
        boss_discount_authority_pct=BOSS_DISCOUNT_AUTHORITY_PCT,
        scenarios=[discount_scenario(lp, uc, qty, d) for d in pcts],
    )


def _debit(conn: sqlite3.Connection, amount: float) -> tuple[str, float, float]:
    acct = db.cash_account(conn)
    before = money(acct["balance"])
    if amount > before:
        raise ToolError(
            f"Refused: paying ${amount:,.2f} would overdraw {acct['name']} (balance ${before:,.2f}). "
            "Balances may never go negative."
        )
    after = money(before - amount)
    conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = ?", (after, db.now_stamp(conn), acct["name"]))
    return acct["name"], before, after


def _record_payment(conn, kind: str, ref_id: int, amount: float, account: str, approver: str) -> PaymentRecord:
    cur = conn.execute(
        "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) VALUES (?,?,?,?,?,?)",
        (kind, ref_id, amount, account, db.now_stamp(conn), approver),
    )
    p = conn.execute("SELECT * FROM payments WHERE id = ?", (cur.lastrowid,)).fetchone()
    return PaymentRecord(**{**dict(p), "amount": money(p["amount"])})


def pay_invoice(conn: sqlite3.Connection, invoice_id: int, expected_amount: float, reason: str,
                approved_by: str | None) -> PaymentReceipt:
    approver = require_human_approver(approved_by)
    require_text(reason, "reason", max_len=600)
    inv = conn.execute(
        "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.id=?",
        (invoice_id,),
    ).fetchone()
    if inv is None:
        raise ToolError(f"Invoice {invoice_id} does not exist.")
    if inv["status"] != "open":
        raise ToolError(f"Invoice {invoice_id} is '{inv['status']}', not open. It will not be paid twice.")
    amount = money(inv["amount"])
    if money(expected_amount) != amount:
        raise ToolError(f"expected_amount ${money(expected_amount):,.2f} does not match invoice {invoice_id} "
                        f"(${amount:,.2f}). Nothing was paid.")
    account, before, after = _debit(conn, amount)
    payment = _record_payment(conn, "invoice", invoice_id, amount, account, approver)
    conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (invoice_id,))
    still_open = conn.execute("SELECT COUNT(*) FROM invoices WHERE vendor_id=? AND status='open'",
                              (inv["vendor_id"],)).fetchone()[0]
    return PaymentReceipt(
        payment=payment, payee=inv["vendor_name"], cash_before=before, cash_after=after,
        invoice_status_after="paid", vendor_unblocked=still_open == 0,
        message=f"Paid invoice {invoice_id} (${amount:,.2f}) to {inv['vendor_name']}, approved by {approver}. "
                f"{account}: ${before:,.2f} -> ${after:,.2f}."
                + (f" {inv['vendor_name']} has no open invoices left and can ship again." if still_open == 0 else ""),
    )


def pay_rent(conn: sqlite3.Connection, lease_id: int, expected_amount: float, reason: str,
             approved_by: str | None) -> PaymentReceipt:
    approver = require_human_approver(approved_by)
    require_text(reason, "reason", max_len=600)
    row = conn.execute("SELECT * FROM leases WHERE id = ?", (lease_id,)).fetchone()
    if row is None:
        raise ToolError(f"Lease {lease_id} does not exist.")
    due = _lease_due(conn, row)
    if due.paid_this_period:
        raise ToolError(f"Rent for lease {lease_id} due {row['next_due']} is already paid. It will not be paid twice.")
    amount = money(row["monthly_rent"])
    if money(expected_amount) != amount:
        raise ToolError(f"expected_amount ${money(expected_amount):,.2f} does not match the lease rent "
                        f"(${amount:,.2f}). Nothing was paid.")
    account, before, after = _debit(conn, amount)
    payment = _record_payment(conn, "rent", lease_id, amount, account, approver)
    next_due = db.add_months(db.parse_date(row["next_due"]), 1).isoformat()
    conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (next_due, lease_id))
    return PaymentReceipt(
        payment=payment, payee=row["landlord"], cash_before=before, cash_after=after, lease_next_due_after=next_due,
        message=f"Paid rent ${amount:,.2f} for {row['space_name']} to {row['landlord']}, approved by {approver}. "
                f"{account}: ${before:,.2f} -> ${after:,.2f}. Next rent due {next_due}.",
    )


def create_purchase_order(conn: sqlite3.Connection, vendor_id: int, sku: str, size: str, qty: int, reason: str,
                          ticket_id: int | None, agent: str) -> PurchaseOrderResult:
    if qty < 1:
        raise ToolError("qty must be at least 1.")
    reason = require_text(reason, "reason", max_len=600)
    vendor = _vendor(conn, vendor_id)
    if conn.execute("SELECT 1 FROM inventory WHERE sku=? AND size=?", (sku, size)).fetchone() is None:
        raise ToolError(f"{sku} size {size} is not a product in inventory.")
    if ticket_id is not None:
        _ticket_row(conn, ticket_id)
    open_inv = db.open_invoices(conn, vendor_id)
    if open_inv:
        ids = ", ".join(str(r["id"]) for r in open_inv)
        raise ToolError(f"{vendor.name} has open unpaid invoice(s) {ids} and will not ship new product. "
                        "Pay them (with human approval) before ordering.")
    unit_cost = money(db.pricing(conn, sku)["unit_cost"])
    total = money(unit_cost * qty)
    now = db.today(conn)
    arrival = (now + timedelta(days=vendor.lead_days)).isoformat()
    cur = conn.execute(
        "INSERT INTO purchase_orders (vendor_id, sku, size, qty, unit_cost, total_cost, ticket_id, status, "
        "expected_arrival, reason, created_by, created_at) VALUES (?,?,?,?,?,?,?,'pending_approval',?,?,?,?)",
        (vendor_id, sku, size, qty, unit_cost, total, ticket_id, arrival, reason, acting(agent), now.isoformat()),
    )
    po = next(p for p in _purchase_orders(conn) if p.id == cur.lastrowid)
    accounts = _accounts(conn)
    _, inv_total, _, _, rent_total = _obligations(conn)
    after = money(sum(a.balance for a in accounts) - inv_total - rent_total)
    return PurchaseOrderResult(
        purchase_order=po, cash_after_known_obligations=after, affordable_after_obligations=after >= total,
        message=f"Purchase order {po.id} for {qty} x {sku} {size} from {vendor.name} (${total:,.2f}, arrives {arrival} "
                "once released) is pending human approval. No money has moved and nothing was sent to the vendor.",
    )


def decide_purchase_order(conn: sqlite3.Connection, purchase_order_id: int, approve: bool, comment: str,
                          approved_by: str | None) -> PurchaseOrderDecision:
    approver = require_human_approver(approved_by)
    po = next((p for p in _purchase_orders(conn) if p.id == purchase_order_id), None)
    if po is None:
        raise ToolError(f"Purchase order {purchase_order_id} does not exist.")
    if po.status != "pending_approval":
        raise ToolError(f"Purchase order {purchase_order_id} is '{po.status}', not pending approval. "
                        "It will not be decided twice.")
    if not approve:
        conn.execute("UPDATE purchase_orders SET status = 'rejected' WHERE id = ?", (purchase_order_id,))
        po = next(p for p in _purchase_orders(conn) if p.id == purchase_order_id)
        return PurchaseOrderDecision(
            purchase_order=po, decided_by=approver, comment=comment,
            message=f"Purchase order {po.id} rejected by {approver}. No money moved and nothing was sent.",
        )
    open_inv = db.open_invoices(conn, po.vendor_id)
    if open_inv:
        ids = ", ".join(str(r["id"]) for r in open_inv)
        raise ToolError(f"{po.vendor_name} has open unpaid invoice(s) {ids} and will not ship. "
                        "Pay them before approving this purchase order.")
    account, before, after = _debit(conn, po.total_cost)
    payment = _record_payment(conn, "purchase_order", po.id, po.total_cost, account, approver)
    conn.execute("UPDATE purchase_orders SET status = 'approved' WHERE id = ?", (purchase_order_id,))
    po = next(p for p in _purchase_orders(conn) if p.id == purchase_order_id)
    return PurchaseOrderDecision(
        purchase_order=po, decided_by=approver, comment=comment,
        receipt=PaymentReceipt(
            payment=payment, payee=po.vendor_name, cash_before=before, cash_after=after,
            message=f"Paid purchase order {po.id} (${po.total_cost:,.2f}) to {po.vendor_name}, approved by {approver}. "
                    f"{account}: ${before:,.2f} -> ${after:,.2f}.",
        ),
        message=f"Purchase order {po.id} approved by {approver}: ${po.total_cost:,.2f} paid, "
                f"{po.qty} x {po.sku} {po.size} expected {po.expected_arrival}. Nothing was sent to the vendor.",
    )


# --------------------------------------------------------------------------- facilities


def get_lease_status(conn: sqlite3.Connection, lease_id: int | None) -> LeaseStatusReport:
    rows = conn.execute("SELECT * FROM leases" + (" WHERE id = ?" if lease_id is not None else "") + " ORDER BY id",
                        (lease_id,) if lease_id is not None else ()).fetchall()
    if lease_id is not None and not rows:
        raise ToolError(f"Lease {lease_id} does not exist.")
    return LeaseStatusReport(
        today=db.today(conn).isoformat(), leases=[_lease_due(conn, r) for r in rows],
        note="The database records leases and rent only; it has no upkeep or maintenance records.",
    )


# --------------------------------------------------------------------------- customer service


def get_customer_order_view(conn: sqlite3.Connection, ticket_id: int) -> CustomerOrderView:
    t = _ticket_row(conn, ticket_id)
    if t["type"] not in CUSTOMER_TICKET_TYPES:
        raise ToolError(f"Ticket {ticket_id} is a '{t['type']}' ticket, not a customer request.")
    now = db.today(conn)
    rows = conn.execute("SELECT * FROM inventory WHERE sku=? ORDER BY rowid", (t["sku"],)).fetchall()
    row = next((r for r in rows if r["size"] == t["size"]), None)
    if row is None:
        raise ToolError(f"{t['sku']} size {t['size']} is not in inventory.")
    on_hand, qty = row["qty"], int(t["qty"])
    availability = "ready_to_ship" if on_hand >= qty else "partially_available" if on_hand > 0 else "backordered"
    ready = None
    if availability != "ready_to_ship":
        lead = None
        if t["invoice_id"] is not None:
            v = conn.execute("SELECT v.lead_days FROM invoices i JOIN vendors v ON v.id=i.vendor_id WHERE i.id=?",
                             (t["invoice_id"],)).fetchone()
            lead = v["lead_days"] if v else None
        pos = [p for p in _purchase_orders(conn) if p.sku == t["sku"] and p.size == t["size"]
               and p.status in ("pending_approval", "approved")]
        if pos:
            ready = min(p.expected_arrival for p in pos)
        elif lead is not None:
            ready = (now + timedelta(days=lead)).isoformat()
    override = _price_override(conn, ticket_id)
    return CustomerOrderView(
        ticket_id=ticket_id, customer_name=t["requester"], request_type=t["type"], product_name=row["name"],
        size=t["size"], qty=qty, unit_list_price=money(db.pricing(conn, t["sku"])["list_price"]),
        available_now=min(on_hand, qty), availability=availability, expected_ready_date=ready,
        other_sizes_available=[r["size"] for r in rows if r["size"] != t["size"] and r["qty"] > 0],
        agreed_unit_price=override.unit_price if override else None, ticket_status=t["status"],
        sharing_rules=[
            "Share product, size, quantity, list price, availability and dates only.",
            "Never share costs, margins, cash, invoices, vendor names or payment details.",
            "Give a date as 'expected' unless the Boss has confirmed the restock; never promise a discount the Boss has not recorded.",
        ],
    )


MONEY_PATTERN = re.compile(
    r"\$\s?(\d[\d,]*(?:\.\d+)?)"            # $22 or $3,400.00
    r"|(\d[\d,]*\.\d{2})\b"                 # 22.00
    r"|(\d[\d,]*(?:\.\d+)?)\s*(?:dollars|usd)\b",
    re.IGNORECASE,
)


def _customer_safe_amounts(conn: sqlite3.Connection, t: sqlite3.Row) -> set[str]:
    """Prices this customer may see: list price, the Boss's agreed price, and their order totals."""
    if not t["sku"]:
        return set()
    qty = t["qty"] or 1
    list_price = money(db.pricing(conn, t["sku"])["list_price"])
    safe = {list_price, money(list_price * qty)}
    override = _price_override(conn, t["id"])
    if override:
        safe |= {money(override.unit_price), money(override.order_total)}
    return {f"{v:.2f}" for v in safe}


def _leaks(conn: sqlite3.Connection, text: str, t: sqlite3.Row) -> list[str]:
    low = text.casefold()
    found = [term.strip() for term in INTERNAL_TERMS if term in low]
    found += [v["name"] for v in conn.execute("SELECT name FROM vendors") if v["name"].casefold() in low]
    figures = {f"{money(r['unit_cost']):.2f}" for r in conn.execute("SELECT unit_cost FROM pricing")}
    figures |= {f"{money(r['balance']):.2f}" for r in conn.execute("SELECT balance FROM cash_accounts")}
    figures |= {f"{money(r['amount']):.2f}" for r in conn.execute("SELECT amount FROM invoices")}
    figures -= _customer_safe_amounts(conn, t)
    amounts = {f"{float(next(g for g in m.groups() if g).replace(',', '')):.2f}" for m in MONEY_PATTERN.finditer(text)}
    found += [f"${f}" for f in sorted(figures & amounts)]
    return found


def save_customer_draft(conn: sqlite3.Connection, ticket_id: int, subject: str, body: str, agent: str) -> DraftRecord:
    t = _ticket_row(conn, ticket_id)
    subject = require_text(subject, "subject", max_len=200)
    body = require_text(body, "body")
    if t["type"] in CUSTOMER_TICKET_TYPES:
        leaks = _leaks(conn, f"{subject}\n{body}", t)
        if leaks:
            raise ToolError(
                f"Draft refused: it contains internal information a customer must not see: {leaks}. "
                "Rewrite it without costs, margins, cash, invoices or vendor details."
            )
    cur = conn.execute(
        "INSERT INTO drafts (ticket_id, recipient, subject, body, status, created_by, created_at) "
        "VALUES (?,?,?,?,'draft',?,?)",
        (ticket_id, t["requester"], subject, body, acting(agent), db.now_stamp(conn)),
    )
    return DraftRecord(**dict(conn.execute("SELECT * FROM drafts WHERE id = ?", (cur.lastrowid,)).fetchone()))


def list_drafts(conn: sqlite3.Connection, ticket_id: int | None) -> DraftList:
    if ticket_id is not None:
        _ticket_row(conn, ticket_id)
    return DraftList(drafts=_drafts(conn, ticket_id))
