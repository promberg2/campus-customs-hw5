"""Services behind the board API: team runs, human approvals, the event feed and database resets.

Agent work (team runs and the MCP calls that execute an approval) runs on one worker thread with its own
event loop. On Windows that loop is a ProactorEventLoop, which can start the stdio MCP server subprocess
even when uvicorn itself runs on a selector loop (as it does with --reload).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Coroutine, Literal

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from backend import shop_db
from backend.approval_queue import ApprovalQueue
from backend.approvals import BoardApprover
from backend.audit import AuditTrail, clip, write_json_atomic
from backend.config import (
    AUDIT_TRAIL_FILE,
    RUNS_FILE,
    INJECTED_AGENT_PARAM,
    INJECTED_APPROVER_PARAM,
    MCP_SERVER_LOG,
    MODEL_NAME,
    PROJECT_ROOT,
    TOOLS_WITH_ACTING_AGENT,
    mcp_launch_config,
)
from backend.models import AuditEvent, BoardApproval, utc_now
from backend.team import reset_working_db, run_team
from mcp_server.config import RESERVED_APPROVER_NAMES


class BoardError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code, self.message = status_code, message


# ---------------------------------------------------------------- worker loop

class Worker:
    def __init__(self) -> None:
        self.loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="agent-worker", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def start(self) -> None:
        if not self.thread.is_alive():
            self.thread.start()

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)

    def submit(self, coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def call(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return await asyncio.wrap_future(self.submit(coro))


# ---------------------------------------------------------------- runs

class RunRecord(BaseModel):
    run_id: str
    ticket_id: int
    status: Literal["running", "finished", "failed", "cancelled", "interrupted"] = "running"
    started_at: str
    finished_at: str | None = None
    stop_reason: str | None = None
    report: dict[str, Any] | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None
    ticket_status_after: str | None = None


class Board:
    def __init__(self, runs_path: Path = RUNS_FILE) -> None:
        self.worker = Worker()
        self.queue = ApprovalQueue()
        self.audit = AuditTrail()          # used only on the worker loop, so its lock is never shared across loops
        self.runs_path = runs_path
        self.runs: dict[str, RunRecord] = self._load_runs()
        self._futures: dict[str, concurrent.futures.Future] = {}
        self._lock = threading.Lock()
        self._continue_after_run: set[int] = set()     # tickets approved while another run was still active

    def _load_runs(self) -> dict[str, RunRecord]:
        if not self.runs_path.exists() or not self.runs_path.read_text(encoding="utf-8").strip():
            return {}
        runs = {r["run_id"]: RunRecord.model_validate(r) for r in json.loads(self.runs_path.read_text(encoding="utf-8"))}
        for r in runs.values():
            if r.status == "running":       # the server stopped while this run was in progress
                r.status, r.finished_at = "interrupted", r.finished_at or utc_now()
        return runs

    def _save_runs(self) -> None:
        write_json_atomic(self.runs_path, [r.model_dump(mode="json") for r in self.runs.values()])

    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()

    # ---------------------------------------------------------- tickets and cash

    def active_run(self) -> RunRecord | None:
        with self._lock:
            return next((r for r in self.runs.values() if r.status == "running"), None)

    def latest_run(self, ticket_id: int) -> RunRecord | None:
        with self._lock:
            mine = [r for r in self.runs.values() if r.ticket_id == ticket_id]
        return max(mine, key=lambda r: r.started_at) if mine else None

    def tickets(self) -> dict[str, Any]:
        """Ticket state for the board: running while the team works on it, resolved once a team run on it
        finished (or the status itself is final), otherwise open. The database status is kept as is."""
        self.queue.sync_purchase_orders(shop_db.pending_purchase_orders())
        pending: dict[int, int] = {}
        for item in self.queue.items("pending"):
            if item.ticket_id is not None:
                pending[item.ticket_id] = pending.get(item.ticket_id, 0) + 1
        rows = shop_db.tickets()
        for r in rows:
            last = self.latest_run(r["id"])
            r["pending_approvals"] = pending.get(r["id"], 0)
            r["agent_running"] = bool(last and last.status == "running")
            r["last_run"] = last.model_dump(mode="json", include={"run_id", "status", "started_at", "finished_at"}) if last else None
            if r["agent_running"]:
                r["state"] = "running"
            elif r["state"] == "resolved" or (last and last.status == "finished"):
                r["state"] = "resolved"
        return {"today": shop_db.today(), "tickets": rows}

    def cash(self) -> dict[str, Any]:
        return {**shop_db.checking_account(), "today": shop_db.today()}

    def overview(self) -> dict[str, Any]:
        return shop_db.overview()

    def list_runs(self) -> list[RunRecord]:
        with self._lock:
            return sorted(self.runs.values(), key=lambda r: r.started_at, reverse=True)

    # ---------------------------------------------------------- team runs

    def start_run(self, ticket_id: int) -> RunRecord:
        if not shop_db.ticket_exists(ticket_id):
            raise BoardError(404, f"Ticket {ticket_id} does not exist.")
        with self._lock:
            busy = next((r for r in self.runs.values() if r.status == "running"), None)
            if busy:
                raise BoardError(409, f"The team is already working on ticket {busy.ticket_id} (run {busy.run_id}). "
                                      "Wait until it finishes.")
            record = RunRecord(run_id=uuid.uuid4().hex[:12], ticket_id=ticket_id, started_at=utc_now())
            self.runs[record.run_id] = record
            self._save_runs()
            self._futures[record.run_id] = self.worker.submit(self._run(record))
        return record

    async def _run(self, record: RunRecord) -> None:
        try:
            result = await run_team([record.ticket_id], BoardApprover(self.queue, wait_for_human=True), audit=self.audit,
                                    team_run_id=record.run_id)
            finished = result.stop_reason == "final_output" and result.report is not None
            update = {"status": "finished" if finished else "failed", "stop_reason": result.stop_reason,
                      "usage": result.usage, "report": result.report.model_dump(mode="json") if result.report else None,
                      "error": None if finished else f"The team stopped without a final report ({result.stop_reason})."}
        except asyncio.CancelledError:
            update = {"status": "cancelled", "stop_reason": "cancelled_by_human"}
        except Exception as exc:
            update = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        status_after = next((t["status"] for t in await asyncio.to_thread(shop_db.tickets)
                             if t["id"] == record.ticket_id), None)
        with self._lock:
            for key, value in {**update, "finished_at": utc_now(), "ticket_status_after": status_after}.items():
                setattr(record, key, value)
            self._futures.pop(record.run_id, None)
            self._save_runs()
            waiting = sorted(self._continue_after_run)
            self._continue_after_run.clear()
        for ticket_id in waiting:
            self._continue_ticket(ticket_id)

    def _continue_ticket(self, ticket_id: int | None) -> str | None:
        """Put the team back on a ticket once a human has approved its last pending action and no run was
        waiting for that decision (for example after a server restart). If another run is still active, the
        follow-up starts when that run finishes."""
        if ticket_id is None or any(i.ticket_id == ticket_id for i in self.queue.items("pending")):
            return None
        try:
            return self.start_run(ticket_id).run_id
        except BoardError:
            with self._lock:
                self._continue_after_run.add(ticket_id)
            return None

    def cancel_run(self, run_id: str) -> RunRecord:
        record = self.get_run(run_id)
        if record.status != "running":
            raise BoardError(409, f"Run {run_id} is already {record.status}.")
        future = self._futures.get(run_id)
        if future is not None:
            future.cancel()
        return record

    def get_run(self, run_id: str) -> RunRecord:
        with self._lock:
            record = self.runs.get(run_id)
        if record is None:
            raise BoardError(404, f"No run {run_id} since the server started.")
        return record

    # ---------------------------------------------------------- approvals

    def approvals(self, status: str | None) -> list[BoardApproval]:
        self.queue.sync_purchase_orders(shop_db.pending_purchase_orders())
        return self.queue.items(status)

    def _pending(self, approval_id: int) -> BoardApproval:
        item = self.queue.get(approval_id)
        if item is None:
            raise BoardError(404, f"Approval #{approval_id} does not exist.")
        if item.status != "pending":
            raise BoardError(409, f"Approval #{approval_id} is already {item.status}.")
        return item

    @staticmethod
    def _human_name(name: str) -> str:
        name = name.strip()
        if name.lower() in RESERVED_APPROVER_NAMES:
            raise BoardError(422, "approver_name must be the real name of the human who decides.")
        return name

    async def decide(self, approval_id: int, approve: bool, approver_name: str, comment: str) -> BoardApproval:
        item = self._pending(approval_id)
        name = self._human_name(approver_name)
        return await self.worker.call(self._decide(item, approve, name, comment))

    async def _decide(self, item: BoardApproval, approve: bool, name: str, comment: str) -> BoardApproval:
        status = "approved" if approve else "denied"
        await self.audit.log(AuditEvent(
            team_run_id=item.team_run_id or "board", event="approval_decision", agent="human", tool=item.tool,
            arguments=item.arguments, status=status,
            detail={"approval_id": item.id, "approver": name, "comment": comment, "via": "board"}))

        if item.kind == "purchase_order":
            args = {"purchase_order_id": item.arguments["purchase_order_id"], "approve": approve, "comment": comment}
        elif approve:
            args = dict(item.arguments)
            if item.tool in TOOLS_WITH_ACTING_AGENT:
                args[INJECTED_AGENT_PARAM] = item.requested_by
        else:
            return self.queue.decide(item.id, "denied", name, comment or "Denied on the board. Nothing was executed.")

        args[INJECTED_APPROVER_PARAM] = name
        started = time.perf_counter()
        try:
            result = await call_mcp_tool(item.tool, args)
        except ToolError as exc:
            await self.audit.log(AuditEvent(
                team_run_id=item.team_run_id or "board", event="tool_call", agent="human", tool=item.tool,
                arguments=args, status="refused_by_server", duration_ms=int((time.perf_counter() - started) * 1000),
                result={"error": str(exc)}, detail={"approval_id": item.id}))
            self.queue.decide(item.id, "failed", name, f"The shop server refused: {exc}")
            raise BoardError(409, f"The shop server refused approval #{item.id}: {exc}") from exc
        await self.audit.log(AuditEvent(
            team_run_id=item.team_run_id or "board", event="tool_call", agent="human", tool=item.tool, arguments=args,
            status="ok", duration_ms=int((time.perf_counter() - started) * 1000), result=clip(result),
            detail={"approval_id": item.id}))
        awaited = item.id in self.queue.awaited
        decided = self.queue.decide(item.id, status, name, comment, result)
        if approve and not awaited:
            decided.follow_up_run_id = self._continue_ticket(item.ticket_id)
        return decided

    # ---------------------------------------------------------- reset

    async def reset(self) -> dict[str, Any]:
        if self.active_run():
            raise BoardError(409, "A team run is in progress. Reset after it finishes.")
        sha = reset_working_db()
        cleared = self.queue.clear()
        with self._lock:
            runs_cleared = len(self.runs)
            self.runs.clear()
            self._continue_after_run.clear()
            self._save_runs()
        await self.worker.call(self.audit.log(AuditEvent(
            team_run_id="board", event="db_reset", agent="human", model=MODEL_NAME,
            detail={"db_sha256": sha, "approvals_cleared": cleared, "runs_cleared": runs_cleared})))
        return {"db_sha256": sha, "approvals_cleared": cleared, "runs_cleared": runs_cleared, **self.cash()}

    # ---------------------------------------------------------- events

    def events(self, since: int | None, limit: int, team_run_id: str | None) -> dict[str, Any]:
        raw = read_audit_trail()
        indexed = [(seq, e) for seq, e in enumerate(raw) if not team_run_id or e.get("team_run_id") == team_run_id]
        if since is not None:
            indexed = [(seq, e) for seq, e in indexed if seq >= since][:limit]
        else:
            indexed = indexed[-limit:]
        return {
            "events": [{"seq": seq, **describe_event(e), **e} for seq, e in indexed],
            "next_since": (indexed[-1][0] + 1) if indexed else (since if since is not None else len(raw)),
            "total": len(raw),
        }


# ---------------------------------------------------------------- helpers

async def call_mcp_tool(tool: str, args: dict[str, Any]) -> Any:
    """One short MCP session for a human-approved action, through the same server the agents use."""
    cfg = mcp_launch_config()
    transport = StdioTransport(command=cfg["command"], args=cfg["args"], env=cfg["env"], cwd=str(PROJECT_ROOT),
                               log_file=MCP_SERVER_LOG)
    async with Client(transport) as client:
        result = await client.call_tool(tool, args)
    return result.structured_content


def read_audit_trail() -> list[dict[str, Any]]:
    for attempt in range(20):
        try:
            if not AUDIT_TRAIL_FILE.exists():
                return []
            data = json.loads(AUDIT_TRAIL_FILE.read_text(encoding="utf-8") or "[]")
            return data if isinstance(data, list) else []
        except (PermissionError, json.JSONDecodeError):
            time.sleep(0.05 * (1 + attempt % 5))
    return []


def _short(text: Any, n: int = 220) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def describe_event(e: dict[str, Any]) -> dict[str, str]:
    """A category and a one-line, human-readable summary for the board, taken from the event's own fields."""
    ev, agent, d = e.get("event"), e.get("agent") or "", e.get("detail") or {}
    result = e.get("result") if isinstance(e.get("result"), dict) else {}
    if ev == "team_run_start":
        return {"category": "run", "summary": f"Team run started on tickets {d.get('tickets')}"}
    if ev == "team_run_end":
        tokens = (e.get("usage") or {}).get("total_tokens")
        return {"category": "run", "summary": f"Team run finished ({e.get('status')}), {tokens} tokens"}
    if ev == "agent_run_start":
        return {"category": "run", "summary": f"{agent} started: {_short(d.get('prompt'))}"}
    if ev == "agent_run_end":
        said = result.get("summary") or ""
        return {"category": "communication",
                "summary": f"{agent} finished ({e.get('status')})" + (f": {_short(said)}" if said else "")}
    if ev == "model_step":
        if d.get("text"):
            return {"category": "communication", "summary": f"{agent}: {_short(d['text'])}"}
        tools = ", ".join(c.get("tool", "") for c in d.get("tool_calls") or [])
        return {"category": "tool", "summary": f"{agent} decides to call {tools or 'no tools'}"}
    if ev == "tool_call":
        return {"category": "tool", "summary": f"{agent} used {e.get('tool')} ({e.get('status')})"}
    if ev == "boss_authorization":
        return {"category": "communication", "summary": f"boss authorizes paying {d.get('kind')} {d.get('ref_id')} "
                                                         f"for ${float(d.get('amount', 0)):,.2f}: {_short(d.get('reason'))}"}
    if ev == "approval_requested":
        return {"category": "approval", "summary": f"{agent} needs a human for {e.get('tool')}: {_short(d.get('reason'))}"}
    if ev == "approval_decision":
        who = d.get("approver") or ("approval board" if e.get("status") == "queued_for_human" else "human")
        return {"category": "approval", "summary": f"{e.get('tool')}: {e.get('status')} by {who}"
                                                   + (f" ({_short(d.get('comment'), 120)})" if d.get("comment") else "")}
    if ev == "delegation_request":
        return {"category": "communication", "summary": f"{agent} → {d.get('to')}: {_short(d.get('task'))}"}
    if ev == "delegation_result":
        return {"category": "communication",
                "summary": f"{d.get('from')} → {agent} ({e.get('status')}): {_short(result.get('summary'))}"}
    if ev == "delegation_refused":
        return {"category": "communication", "summary": f"{agent} → {d.get('to')} refused: {_short(d.get('reason'))}"}
    if ev == "db_reset":
        return {"category": "run", "summary": "Database reset to the original values"}
    if ev == "error":
        return {"category": "error", "summary": f"{agent or 'system'} error: {_short(d.get('message'))}"}
    return {"category": "other", "summary": str(ev)}
