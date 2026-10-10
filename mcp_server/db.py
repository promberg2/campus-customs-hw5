"""SQLite access and the small helpers every tool shares.

Each tool call opens its own short-lived connection. Read-only tools open the
file with SQLite's `mode=ro`, so a bug in a read tool cannot change the data.
Write tools use `transaction()`, which takes the write lock up front and either
commits every change of the call or none of them.
"""

from __future__ import annotations

import calendar
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from fastmcp.exceptions import ToolError

from .config import DEFAULT_ACCOUNT, ConfigError, db_path


@contextmanager
def connect(*, read_only: bool = True) -> Iterator[sqlite3.Connection]:
    try:
        path = db_path()
    except ConfigError as exc:
        raise ToolError(str(exc)) from exc
    mode = "ro" if read_only else "rw"
    conn = sqlite3.connect(f"{path.as_uri()}?mode={mode}", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


# Operational tables the agents write to. The original schema has nowhere to keep
# drafts, purchase orders, stock movements or discount decisions. They are created
# in the working copy only; resetting the copy from the original removes them.
OPERATIONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL CHECK (qty > 0),
    unit_cost REAL NOT NULL,
    total_cost REAL NOT NULL,
    ticket_id INTEGER REFERENCES tickets(id),
    status TEXT NOT NULL DEFAULT 'pending_approval',
    expected_arrival TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stock_movements (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(id),
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty_change INTEGER NOT NULL,
    qty_after INTEGER NOT NULL CHECK (qty_after >= 0),
    reason TEXT NOT NULL,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_overrides (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(id),
    sku TEXT NOT NULL,
    qty INTEGER NOT NULL,
    list_price REAL NOT NULL,
    discount_pct REAL NOT NULL,
    unit_price REAL NOT NULL,
    order_total REAL NOT NULL,
    decided_by TEXT NOT NULL,
    approved_by TEXT,
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    with connect(read_only=False) as conn:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in OPERATIONAL_SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def now_stamp(conn: sqlite3.Connection) -> str:
    """Shop date for records the agents create. Shop time is desk.date_today, not the wall clock."""
    return today(conn).isoformat()


def money(value: float | int | Decimal) -> float:
    """Round to cents. Money is stored as REAL, so every result passes through here."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_date(value: str) -> date:
    """Accept `YYYY-MM-DD` or a full ISO timestamp; only the date part is used."""
    return date.fromisoformat(value[:10])


def add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def today(conn: sqlite3.Connection) -> date:
    """The shop's "today" comes from desk.date_today, never from the system clock."""
    row = conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()
    if row is None:
        raise ToolError("The desk table has no date_today, so 'today' is unknown.")
    return parse_date(row["date_today"])


def ticket(conn: sqlite3.Connection, ticket_id: int, expected_type: str, tool_for_type: dict[str, str]) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        known = [r["id"] for r in conn.execute("SELECT id FROM tickets ORDER BY id")]
        raise ToolError(f"Ticket {ticket_id} does not exist. Known ticket ids: {known}.")
    if row["type"] != expected_type:
        hint = tool_for_type.get(row["type"])
        suggestion = f" Use {hint} instead." if hint else ""
        raise ToolError(
            f"Ticket {ticket_id} is a '{row['type']}' ticket, but this tool handles "
            f"'{expected_type}' tickets.{suggestion}"
        )
    return row


def cash_account(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (DEFAULT_ACCOUNT,)).fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM cash_accounts ORDER BY balance DESC LIMIT 1").fetchone()
    if row is None:
        raise ToolError("The cash_accounts table is empty, so no cash position is available.")
    return row


def open_invoices(conn: sqlite3.Connection, vendor_id: int | None = None) -> list[sqlite3.Row]:
    sql = (
        "SELECT i.*, v.name AS vendor_name FROM invoices i "
        "JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open'"
    )
    params: tuple = ()
    if vendor_id is not None:
        sql += " AND i.vendor_id = ?"
        params = (vendor_id,)
    return conn.execute(sql + " ORDER BY i.due_date, i.id", params).fetchall()


def stock_by_size(conn: sqlite3.Connection, sku: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT size, qty, location FROM inventory WHERE sku = ? ORDER BY rowid", (sku,)
    ).fetchall()


def pricing(conn: sqlite3.Connection, sku: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if row is None:
        raise ToolError(f"No pricing row for SKU {sku}.")
    return row
