"""The approval board: actions the agents prepared that only a human may execute.

Stored as a JSON array in output/approval_queue.json so pending approvals survive a server reload.
Agents add payments and large discounts while they run; pending purchase orders are picked up from the
database. Nothing on the board has happened until a human approves it through the API.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from backend.audit import write_json_atomic
from backend.config import APPROVAL_QUEUE_FILE
from backend.models import ApprovalRequest, BoardApproval, utc_now


def _target(tool: str, args: dict[str, Any]) -> str:
    keys = ("invoice_id", "lease_id", "ticket_id", "purchase_order_id")
    return f"{tool}:{json.dumps({k: args[k] for k in keys if k in args}, sort_keys=True)}"


def describe(tool: str, args: dict[str, Any]) -> tuple[str, str, float | None]:
    """(kind, title, amount) for a gated action, built only from its arguments."""
    if tool == "pay_invoice":
        amount = float(args.get("expected_amount", 0))
        return "invoice", f"Pay invoice {args.get('invoice_id')} (${amount:,.2f})", amount
    if tool == "pay_rent":
        amount = float(args.get("expected_amount", 0))
        return "rent", f"Pay rent for lease {args.get('lease_id')} (${amount:,.2f})", amount
    if tool == "record_discount_decision":
        return "discount", f"{float(args.get('discount_pct', 0)):g}% discount on ticket {args.get('ticket_id')}", None
    raise ValueError(f"{tool} is not an action that goes on the approval board.")


class ApprovalQueue:
    def __init__(self, path: Path = APPROVAL_QUEUE_FILE) -> None:
        self.path = path
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.awaited: set[int] = set()     # approvals a running team is waiting on right now

    def _load(self) -> list[BoardApproval]:
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            return []
        return [BoardApproval.model_validate(x) for x in json.loads(self.path.read_text(encoding="utf-8"))]

    def _save(self, items: list[BoardApproval]) -> None:
        write_json_atomic(self.path, [i.model_dump(mode="json") for i in items])

    def items(self, status: str | None = None) -> list[BoardApproval]:
        with self._lock:
            return [i for i in self._load() if status is None or i.status == status]

    def get(self, approval_id: int) -> BoardApproval | None:
        return next((i for i in self.items() if i.id == approval_id), None)

    def _add(self, items: list[BoardApproval], **fields: Any) -> BoardApproval:
        item = BoardApproval(id=max((i.id for i in items), default=0) + 1, **fields)
        items.append(item)
        self._save(items)
        return item

    def submit(self, request: ApprovalRequest, ticket_id: int | None) -> tuple[BoardApproval, bool]:
        """Queue an agent's gated action. Returns (item, created); an identical pending action is reused."""
        with self._lock:
            items = self._load()
            key = _target(request.tool, request.arguments)
            for i in items:
                if i.status == "pending" and _target(i.tool, i.arguments) == key:
                    return i, False
            kind, title, amount = describe(request.tool, request.arguments)
            return self._add(
                items, kind=kind, tool=request.tool, arguments=request.arguments, ticket_id=ticket_id, title=title,
                amount=amount, reason=request.reason + (f" Agent's reason: {request.arguments['reason']}"
                                                        if request.arguments.get("reason") else ""),
                requested_by=request.requested_by, chain=request.chain, team_run_id=request.team_run_id,
                boss_authorization=request.boss_authorization,
            ), True

    def sync_purchase_orders(self, pending_pos: list[dict[str, Any]]) -> None:
        """Put every purchase order that is pending in the database on the board once."""
        with self._lock:
            items = self._load()
            known = {i.arguments.get("purchase_order_id") for i in items if i.kind == "purchase_order"}
            for po in pending_pos:
                if po["id"] in known:
                    continue
                self._add(
                    items, kind="purchase_order", tool="decide_purchase_order",
                    arguments={"purchase_order_id": po["id"]}, ticket_id=po.get("ticket_id"),
                    title=f"Purchase order {po['id']}: {po['qty']} x {po['sku']} {po['size']} from "
                          f"{po['vendor_name']} (${float(po['total_cost']):,.2f})",
                    amount=float(po["total_cost"]), reason=f"Restock order prepared by {po['created_by']}: {po['reason']}",
                    requested_by=po["created_by"],
                )

    def decide(self, approval_id: int, status: str, decided_by: str | None, comment: str, result: Any = None
               ) -> BoardApproval:
        with self._lock:
            items = self._load()
            item = next(i for i in items if i.id == approval_id)
            item.status, item.decided_by, item.comment, item.result = status, decided_by, comment, result
            item.decided_at = utc_now()
            self._save(items)
            return item

    def clear(self) -> int:
        """Empty the board (used when the database is reset; the audit trail keeps the history)."""
        with self._lock:
            count = len(self._load())
            self._save([])
            return count
