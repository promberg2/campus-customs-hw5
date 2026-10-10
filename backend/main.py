"""FastAPI routes for the Campus Customs board (the React frontend talks only to these).

Start from the backend/ folder:
    uvicorn main:app --reload --port 8000
Interactive docs: http://127.0.0.1:8000/docs
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import FastAPI, Query, Request          # noqa: E402
from fastapi.middleware.cors import CORSMiddleware   # noqa: E402
from fastapi.responses import JSONResponse           # noqa: E402
from pydantic import BaseModel, Field                # noqa: E402

from backend.board import Board, BoardError, RunRecord   # noqa: E402
from backend.config import FRONTEND_ORIGINS, MODEL_NAME   # noqa: E402
from backend.models import ApprovalStatus, BoardApproval  # noqa: E402

board = Board()


@asynccontextmanager
async def lifespan(_: FastAPI):
    board.start()
    yield
    board.stop()


app = FastAPI(title="Campus Customs board API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(FRONTEND_ORIGINS),
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BoardError)
async def board_error(_: Request, exc: BoardError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(FileNotFoundError)
async def missing_db(_: Request, exc: FileNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


class HumanDecision(BaseModel):
    approver_name: str = Field(min_length=1, max_length=80, description="The real name of the human who decides.")
    comment: str = Field("", max_length=600)


@app.get("/api/health")
def health() -> dict:
    """Is the API up, which model the agents use, and is a team run in progress."""
    active = board.active_run()
    return {"ok": True, "model": MODEL_NAME, "active_run": active.run_id if active else None}


@app.get("/api/tickets")
def list_tickets() -> dict:
    """All tickets with their status, open/resolved state, pending approvals and whether agents are on it."""
    return board.tickets()


@app.post("/api/tickets/{ticket_id}/run", status_code=202)
def run_ticket(ticket_id: int) -> RunRecord:
    """Start the agent team on one ticket in the background. Poll /api/runs/{run_id} and /api/events."""
    return board.start_run(ticket_id)


@app.get("/api/runs")
def list_runs() -> list[RunRecord]:
    """Every board run since the last reset, newest first, with the Boss's report once finished."""
    return board.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> RunRecord:
    """Status of a team run: running, finished (with the Boss's report and token usage) or failed."""
    return board.get_run(run_id)


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: str) -> RunRecord:
    """Stop a running team run. Anything already executed stays; nothing new starts."""
    return board.cancel_run(run_id)


@app.get("/api/events")
def list_events(
    since: int | None = Query(None, ge=0, description="Return events from this seq on (use next_since from the last call)."),
    limit: int = Query(200, ge=1, le=2000),
    run_id: str | None = Query(None, description="Only events of one team run."),
) -> dict:
    """Recent audit-trail events: delegations, messages, tool calls, approvals, each with a one-line summary."""
    return board.events(since, limit, run_id)


@app.get("/api/approvals")
def list_approvals(status: ApprovalStatus | None = Query(None)) -> list[BoardApproval]:
    """Actions the agents prepared that wait for a human: payments, large discounts and purchase orders."""
    return board.approvals(status)


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: HumanDecision) -> BoardApproval:
    """A human approves: the prepared payment, discount or purchase order is executed and cash actually moves."""
    return await board.decide(approval_id, True, body.approver_name, body.comment)


@app.post("/api/approvals/{approval_id}/deny")
async def deny(approval_id: int, body: HumanDecision) -> BoardApproval:
    """A human denies: nothing is paid; a purchase order is marked rejected."""
    return await board.decide(approval_id, False, body.approver_name, body.comment)


@app.get("/api/cash")
def cash() -> dict:
    """The current checking balance from cash_accounts."""
    return board.cash()


@app.get("/api/overview")
def overview() -> dict:
    """The financial picture: cash, open invoices, rent due, obligations, payments, purchase orders, drafts, stock alerts."""
    return board.overview()


@app.post("/api/reset")
async def reset() -> dict:
    """Restore the working database from the original and clear the approval board and run history."""
    return await board.reset()
