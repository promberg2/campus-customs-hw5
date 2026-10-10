"""Inventory agent: stock by SKU and size, shortfalls, vendor restock options, shipping from stock."""

from backend.agents.specialist import build_specialist

inventory_agent = build_specialist("inventory")
