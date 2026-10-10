"""Importing this package registers all five agents in `AGENTS`."""

from backend.agents.base import AGENTS, run_agent
from backend.agents.boss import boss_agent
from backend.agents.inventory import inventory_agent
from backend.agents.accounting import accounting_agent
from backend.agents.facilities import facilities_agent
from backend.agents.customer_service import customer_service_agent

__all__ = [
    "AGENTS", "run_agent", "boss_agent", "inventory_agent", "accounting_agent",
    "facilities_agent", "customer_service_agent",
]
