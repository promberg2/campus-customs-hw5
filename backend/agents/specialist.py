"""Factory for specialist agents: same report format, plus a tool to consult any other specialist.

The Boss is always the root of a team run, so specialists escalate to the Boss through the
`needs_boss_decision` field of their report instead of calling it.
"""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from backend.agents.base import build_agent, delegate
from backend.models import AgentDeps, SpecialistName, SpecialistReport


def build_specialist(name: str) -> Agent[AgentDeps, SpecialistReport]:
    agent = build_agent(name, SpecialistReport)

    @agent.tool
    async def consult_colleague(ctx: RunContext[AgentDeps], colleague: SpecialistName, question: str) -> SpecialistReport | str:
        """Ask another specialist for facts or an action that only their tools can provide, and receive their report.

        Args:
            colleague: inventory, accounting, facilities or customer_service (not yourself or anyone already in the chain).
            question: A precise, self-contained request including ticket ids and the facts you already have.
        """
        return await delegate(ctx, colleague, question)

    return agent
