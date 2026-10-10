"""Backend configuration: model, credentials, MCP launch settings, tool allowlists and limits."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pydantic_ai.usage import UsageLimits

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
MCP_CONFIG_FILE = PROJECT_ROOT / ".mcp.json"
MCP_SERVER_NAME = "campus-customs"
AUDIT_TRAIL_FILE = PROJECT_ROOT / "output" / "audit_trail.json"
MCP_SERVER_LOG = PROJECT_ROOT / "output" / "mcp_server.log"   # keeps server logs out of the approval console
APPROVAL_QUEUE_FILE = PROJECT_ROOT / "output" / "approval_queue.json"
RUNS_FILE = PROJECT_ROOT / "output" / "runs.json"
FRONTEND_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")   # the Vite dev server (npm run dev)
ORIGINAL_DB = PROJECT_ROOT / "data" / "campus_customs.db"
WORKING_DB = PROJECT_ROOT / "data" / "campus_customs_new.db"

# The assignment allows exactly one model. It is hard-wired and never read from the environment.
MODEL_NAME = "gpt-6-luna"
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"
PORTKEY_KEY_VAR = "PORTKEY_API_KEY"
REQUEST_TIMEOUT_S = 120

for _env in (PROJECT_ROOT / ".env", PROJECT_ROOT.parent.parent / ".env"):
    if _env.exists():
        load_dotenv(_env, override=False)
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

AGENT_NAMES = ("boss", "inventory", "accounting", "facilities", "customer_service")
SPECIALISTS = ("inventory", "accounting", "facilities", "customer_service")

# Least privilege: each agent only sees the MCP tools its job needs.
TOOLS_BY_AGENT: dict[str, frozenset[str]] = {
    "boss": frozenset({
        "get_shop_snapshot", "list_tickets", "get_ticket", "update_ticket_status",
        "record_discount_decision", "list_drafts",
    }),
    "inventory": frozenset({
        "get_ticket", "check_stock", "find_stock_shortfalls", "get_vendor_status",
        "check_order_fulfillment", "ship_order_from_stock",
    }),
    "accounting": frozenset({
        "get_ticket", "get_cash_position", "list_invoices", "analyze_margin",
        "evaluate_bulk_discount_request", "get_vendor_status", "pay_invoice", "pay_rent",
        "create_purchase_order",
    }),
    "facilities": frozenset({"get_ticket", "get_lease_status", "review_rent_payment"}),
    "customer_service": frozenset({"get_customer_order_view", "save_customer_draft", "list_drafts"}),
}

# Parameters the backend fills in itself; they are removed from the schema the model sees.
INJECTED_AGENT_PARAM = "acting_agent"
INJECTED_APPROVER_PARAM = "approved_by"
HIDDEN_PARAMS = frozenset({INJECTED_AGENT_PARAM, INJECTED_APPROVER_PARAM})
TOOLS_WITH_ACTING_AGENT = frozenset({
    "update_ticket_status", "record_discount_decision", "ship_order_from_stock",
    "create_purchase_order", "save_customer_draft",
})

# Human approval gate (enforced in the backend and again inside the MCP server).
ALWAYS_APPROVAL_TOOLS = frozenset({"pay_invoice", "pay_rent"})
# Writes that belong to one ticket; a run on one ticket may read anything but only write for its own ticket.
TICKET_SCOPED_TOOLS = frozenset({
    "update_ticket_status", "record_discount_decision", "save_customer_draft",
    "pay_invoice", "pay_rent", "create_purchase_order", "ship_order_from_stock",
})
BOSS_DISCOUNT_AUTHORITY_PCT = 15.0
# Called only by the human approval routes in backend/main.py, never offered to an agent.
HUMAN_ONLY_TOOLS = frozenset({"decide_purchase_order"})
FINAL_TICKET_STATUSES = frozenset({"resolved", "rejected"})

# Agent-loop guards.
MAX_DELEGATION_DEPTH = 2          # boss (0) -> specialist (1) -> consulted colleague (2)
MAX_DELEGATIONS_PER_TEAM_RUN = 14
MAX_STEPS = {"boss": 16, "inventory": 8, "accounting": 10, "facilities": 6, "customer_service": 8}
DELEGATION_BUDGET_RESERVE = 0.2   # stop new delegations when less than 20% of the team budget is left

# Token and request budget, shared by every agent in one team run.
TEAM_USAGE_LIMITS = UsageLimits(
    request_limit=60,
    tool_calls_limit=90,
    total_tokens_limit=600_000,
)
MAX_OUTPUT_TOKENS_PER_RESPONSE = 4_000

AUDIT_TEXT_LIMIT = 1_500


def portkey_api_key() -> str:
    key = os.environ.get(PORTKEY_KEY_VAR, "").strip()
    if not key:
        raise RuntimeError(f"{PORTKEY_KEY_VAR} is not set (copy .env.example to .env and add your key).")
    return key


def mcp_launch_config() -> dict:
    """Server launch settings, read from the same .mcp.json that Cursor uses.

    The paths in .mcp.json are machine-specific, so on a fresh clone the project paths are rebuilt
    from PROJECT_ROOT and the interpreter falls back to the one running the backend.
    """
    servers = json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))["mcpServers"]
    cfg = dict(servers[MCP_SERVER_NAME])
    if not Path(cfg.get("command", "")).exists():
        cfg["command"] = sys.executable
    cfg["env"] = {
        **cfg.get("env", {}),
        "PYTHONPATH": str(PROJECT_ROOT),
        "CAMPUS_CUSTOMS_DB": str(WORKING_DB),
    }
    return cfg
