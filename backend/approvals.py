"""Human-in-the-loop approval for payments and large discounts."""

from __future__ import annotations

import asyncio
import json
from typing import Protocol

from backend.approval_queue import ApprovalQueue
from backend.models import ApprovalDecision, ApprovalRequest
from backend.shop_db import pending_purchase_orders, ticket_for


class Approver(Protocol):
    async def decide(self, request: ApprovalRequest) -> ApprovalDecision: ...


class ConsoleApprover:
    """A person at the terminal approves or denies each request; only a typed 'yes' approves."""

    def __init__(self, approver_name: str) -> None:
        if not approver_name.strip():
            raise ValueError("ConsoleApprover needs the human approver's name.")
        self.approver_name = approver_name.strip()

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        print("\n" + "=" * 70)
        print("HUMAN APPROVAL REQUIRED")
        print(f"  Requested by : {request.requested_by}  (chain: {' -> '.join(request.chain)})")
        print(f"  Action       : {request.tool}")
        print(f"  Details      : {json.dumps(request.arguments, indent=2)}")
        print(f"  Why gated    : {request.reason}")
        if request.boss_authorization:
            a = request.boss_authorization
            print(f"  Boss's call  : authorized {a.kind} {a.ref_id} for ${a.amount:,.2f} - {a.reason}")
        print("=" * 70)
        answer = (await asyncio.to_thread(input, f"{self.approver_name}, approve? Type 'yes' to approve: ")).strip()
        if answer.lower() != "yes":
            comment = (await asyncio.to_thread(input, "Reason for denial (optional): ")).strip()
            return ApprovalDecision(approved=False, approver=self.approver_name, comment=comment or "Denied at console.")
        return ApprovalDecision(approved=True, approver=self.approver_name, comment="Approved at console.")


class DenyAllApprover:
    """Unattended runs: nothing that needs a human is ever executed."""

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        return ApprovalDecision(approved=False, approver=None, comment="Unattended run: no human available, action denied.")


class BoardApprover:
    """Web runs: the action goes on the approval board and runs only when a human approves it there.

    With wait_for_human (the board's setting) the agent's tool call waits until the human decides, so the
    team continues in the same run. The board executes an approved action itself, under the human's name;
    the waiting agent only receives that result, so nothing is ever executed twice."""

    def __init__(self, queue: ApprovalQueue, wait_for_human: bool = False, poll_s: float = 1.0) -> None:
        self.queue = queue
        self.wait_for_human = wait_for_human
        self.poll_s = poll_s

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        ticket_id = await asyncio.to_thread(ticket_for, request.tool, request.arguments)
        item, created = await asyncio.to_thread(self.queue.submit, request, ticket_id)
        if self.wait_for_human:
            return await self._wait(item.id)
        return ApprovalDecision(
            approved=False, queued=True, approval_id=item.id,
            comment=("Queued on the approval board" if created else "Already waiting on the approval board")
                    + f" as #{item.id}: {item.title}.",
        )

    async def await_purchase_order(self, purchase_order_id: int) -> ApprovalDecision | None:
        """Wait for the human's decision on a purchase order the team just created."""
        if not self.wait_for_human:
            return None
        await asyncio.to_thread(self.queue.sync_purchase_orders, await asyncio.to_thread(pending_purchase_orders))
        item = next((i for i in self.queue.items("pending") if i.kind == "purchase_order"
                     and i.arguments.get("purchase_order_id") == purchase_order_id), None)
        return None if item is None else await self._wait(item.id)

    async def _wait(self, approval_id: int) -> ApprovalDecision:
        self.queue.awaited.add(approval_id)
        try:
            while True:
                item = await asyncio.to_thread(self.queue.get, approval_id)
                if item is None:
                    return ApprovalDecision(approved=False, approval_id=approval_id,
                                            comment="The approval board was cleared before a human decided.")
                if item.status != "pending":
                    break
                await asyncio.sleep(self.poll_s)
        finally:
            self.queue.awaited.discard(approval_id)
        if item.status == "approved":
            return ApprovalDecision(approved=True, approver=item.decided_by, comment=item.comment or "",
                                    approval_id=item.id, executed=True, result=item.result)
        if item.status == "failed":
            return ApprovalDecision(approved=False, approver=item.decided_by, approval_id=item.id,
                                    comment=item.comment or "The shop server refused the approved action.")
        return ApprovalDecision(approved=False, approver=item.decided_by, approval_id=item.id,
                                comment=item.comment or "Denied on the board.")
