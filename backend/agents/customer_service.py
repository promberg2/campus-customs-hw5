"""Customer service agent: customer-safe order view and reply drafts that stay on the board."""

from backend.agents.specialist import build_specialist

customer_service_agent = build_specialist("customer_service")
