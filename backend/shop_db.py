"""Read-only database queries for the board routes. Every write goes through the MCP server instead."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from backend.config import FINAL_TICKET_STATUSES, WORKING_DB

CHECKING_ACCOUNT = "checking"


@contextmanager
def read_only() -> Iterator[sqlite3.Connection]:
    if not WORKING_DB.exists():
        raise FileNotFoundError(f"Working database not found: {WORKING_DB}. Reset it first.")
    conn = sqlite3.connect(f"{WORKING_DB.as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def today() -> str:
    with read_only() as conn:
        return conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()["date_today"]


def tickets() -> list[dict[str, Any]]:
    with read_only() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM tickets ORDER BY id")]
        drafts: dict[int, int] = {}
        if _table_exists(conn, "drafts"):
            drafts = {r[0]: r[1] for r in conn.execute("SELECT ticket_id, COUNT(*) FROM drafts GROUP BY ticket_id")}
    for r in rows:
        r["state"] = "resolved" if r["status"] in FINAL_TICKET_STATUSES else "open"
        r["drafts"] = drafts.get(r["id"], 0)
    return rows


def ticket_exists(ticket_id: int) -> bool:
    with read_only() as conn:
        return conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is not None


def checking_account() -> dict[str, Any]:
    with read_only() as conn:
        row = conn.execute("SELECT * FROM cash_accounts WHERE name = ?", (CHECKING_ACCOUNT,)).fetchone()
    if row is None:
        raise LookupError("cash_accounts has no 'checking' row.")
    return {"account": row["name"], "balance": round(float(row["balance"]), 2), "as_of": row["date"]}


def ticket_for(tool: str, args: dict[str, Any]) -> int | None:
    """The ticket an approval belongs to, looked up from the ticket's own invoice or lease link."""
    if "ticket_id" in args:
        return args["ticket_id"]
    column = {"pay_invoice": ("invoice_id", "invoice_id"), "pay_rent": ("lease_id", "lease_id")}.get(tool)
    if not column or args.get(column[1]) is None:
        return None
    with read_only() as conn:
        row = conn.execute(f"SELECT id FROM tickets WHERE {column[0]} = ? ORDER BY id LIMIT 1",
                           (args[column[1]],)).fetchone()
    return row["id"] if row else None


def linked_obligations(ticket_ids: list[int]) -> list[tuple[str, int]]:
    """The invoices and leases the tickets table links to these tickets."""
    marks = ",".join("?" * len(ticket_ids))
    with read_only() as conn:
        rows = conn.execute(f"SELECT invoice_id, lease_id FROM tickets WHERE id IN ({marks}) ORDER BY id",
                            list(ticket_ids)).fetchall()
    links = [("invoice", r["invoice_id"]) for r in rows if r["invoice_id"] is not None]
    return links + [("lease", r["lease_id"]) for r in rows if r["lease_id"] is not None]


def overview() -> dict[str, Any]:
    """Shop snapshot, cash position, purchase orders and drafts, computed by the MCP server's own
    read-only operations so the board shows exactly what the agents see."""
    from mcp_server import operations as ops
    from mcp_server.db import connect

    with connect(read_only=True) as conn:
        return {
            "snapshot": ops.get_shop_snapshot(conn).model_dump(mode="json"),
            "cash_position": ops.get_cash_position(conn).model_dump(mode="json"),
            "purchase_orders": [p.model_dump(mode="json") for p in ops._purchase_orders(conn)],
            "drafts": ops.list_drafts(conn, None).model_dump(mode="json")["drafts"],
        }


def pending_purchase_orders() -> list[dict[str, Any]]:
    with read_only() as conn:
        if not _table_exists(conn, "purchase_orders"):
            return []
        return [dict(r) for r in conn.execute(
            "SELECT p.*, v.name AS vendor_name FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id "
            "WHERE p.status = 'pending_approval' ORDER BY p.id")]
