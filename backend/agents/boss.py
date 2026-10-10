"""The Boss: reads every ticket, delegates to the specialists, and makes the final calls."""

from __future__ import annotations

from pydantic_ai import RunContext

from backend.agents.base import agent_event, build_agent, delegate
from backend.mcp_tools import out_of_scope
from backend.models import AgentDeps, BossReport, PaymentAuthorization, SpecialistName, SpecialistReport

boss_agent = build_agent("boss", BossReport)


@boss_agent.tool
async def delegate_task(
    ctx: RunContext[AgentDeps],
    colleague: SpecialistName,
    task: str,
    authorize_payments: list[PaymentAuthorization] | None = None,
) -> SpecialistReport | str:
    """Assign a clearly scoped task to a specialist and receive their structured report.

    Args:
        colleague: inventory, accounting, facilities or customer_service.
        task: What to do, including ticket ids, which actions they may take, and what to report back.
        authorize_payments: Your final call on payments, only for accounting. Accounting can submit exactly
            these payments (kind, id, exact amount) for human approval and nothing else.
    """
    authorize_payments = authorize_payments or []
    if authorize_payments and colleague != "accounting":
        return "Payment authorizations can only be given to accounting. Nothing was delegated."
    team = ctx.deps.team
    for auth in authorize_payments:
        tool, field = ("pay_invoice", "invoice_id") if auth.kind == "invoice" else ("pay_rent", "lease_id")
        refusal = await out_of_scope(ctx.deps, tool, {field: auth.ref_id})
        if refusal:
            return f"Authorization for {auth.kind} {auth.ref_id} refused: {refusal} Nothing was delegated."
    for auth in authorize_payments:
        team.payment_authorizations[auth.key] = auth
        await team.audit.log(agent_event(ctx.deps, "boss_authorization", detail=auth.model_dump(mode="json")))
    if authorize_payments:
        lines = "; ".join(f"{a.kind} {a.ref_id} for ${a.amount:,.2f} ({a.reason})" for a in authorize_payments)
        task = f"{task}\n\nBoss-authorized payments (submit each for human approval): {lines}."
    return await delegate(ctx, colleague, task)
