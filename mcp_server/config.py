"""Where the server finds its database.

The working copy is the only file the server may open. The original database is
the reset source and must never be touched, so pointing the server at it is an
error rather than a warning.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
ORIGINAL_DB = DATA_DIR / "campus_customs.db"
WORKING_DB = DATA_DIR / "campus_customs_new.db"

DB_ENV_VAR = "CAMPUS_CUSTOMS_DB"

DEFAULT_ACCOUNT = "checking"
DUE_SOON_DAYS = 7
OBLIGATION_WINDOW_DAYS = 30
DEFAULT_DISCOUNT_PERCENTS: tuple[float, ...] = (0, 5, 10, 15, 20, 25)

# Business rules enforced by the server, not just by prompts.
BOSS_DISCOUNT_AUTHORITY_PCT = 15.0  # above this, a discount needs a named human approver
MIN_MARGIN_PCT_AFTER_DISCOUNT = 20.0  # no discount may push margin below this
LOW_STOCK_THRESHOLD = 3
MAX_TEXT_FIELD = 2000
RESERVED_APPROVER_NAMES = frozenset({
    "", "ai", "agent", "assistant", "bot", "system", "auto", "automatic", "pending", "none", "n/a",
    "boss", "inventory", "accounting", "facilities", "customer_service", "customer service",
})
AGENT_NAMES = frozenset({"boss", "inventory", "accounting", "facilities", "customer_service"})


class ConfigError(RuntimeError):
    pass


def db_path() -> Path:
    """Resolve the database path, read at call time so tests can override it."""
    raw = os.environ.get(DB_ENV_VAR)
    path = Path(raw).expanduser().resolve() if raw else WORKING_DB
    if path == ORIGINAL_DB.resolve():
        raise ConfigError(
            f"Refusing to open the original database {ORIGINAL_DB.name}. "
            f"The server only works on the copy {WORKING_DB.name}."
        )
    if not path.exists():
        raise ConfigError(f"Database not found: {path}")
    return path
