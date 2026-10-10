"""Accounting agent: cash, invoices, margins, and payments or purchase orders behind human approval."""

from backend.agents.specialist import build_specialist

accounting_agent = build_specialist("accounting")
