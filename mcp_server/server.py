"""FastMCP server exposing the Campus Customs back-office tools.

Run over stdio (default, for an agent that starts the server as a subprocess):
    python -m mcp_server
Run over HTTP (for an agent or backend that connects to a URL):
    python -m mcp_server --transport http --port 8765
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, operations as ops, tools
from .db import connect, transaction
from .models import (
    BulkDiscountReport,
    CashPositionReport,
    CustomerOrderView,
    DraftList,
    DraftRecord,
    InvoiceList,
    LeaseStatusReport,
    MarginReport,
    OrderFulfillmentReport,
    PaymentReceipt,
    PriceOverrideRecord,
    PurchaseOrderDecision,
    PurchaseOrderResult,
    RentReviewReport,
    ShopSnapshot,
    ShortfallReport,
    StockMovementRecord,
    StockReport,
    TicketDetail,
    TicketList,
    TicketUpdateResult,
    VendorStatusReport,
)

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("campus_customs_mcp")

INSTRUCTIONS = """\
Back-office tools for the Campus Customs shop, used by a team of agents (boss, inventory,
accounting, facilities, customer_service). Every value comes from the shop database.

Ticket analysis: customer_order -> check_order_fulfillment, rent_notice -> review_rent_payment,
price_override -> evaluate_bulk_discount_request.

Rules enforced by the server: "today" is desk.date_today. Lead times come from vendors. A vendor with
an open unpaid invoice will not ship and cannot receive a purchase order. pay_invoice and pay_rent
need a named human approver, refuse overdrafts and double payments, and update payments, cash and the
invoice or lease together. Discounts never go below cost or the minimum margin; above the Boss's
authority they need a human approver. Customer drafts are refused if they contain internal figures.
Nothing is ever sent to customers or vendors: drafts and purchase orders stay on the board.
"""

TicketId = Annotated[int, Field(ge=1, description="The id of the ticket in the tickets table, e.g. 101.")]
Sku = Annotated[str, Field(min_length=1, max_length=40, description="Product code, e.g. CC-HOOD-NAVY.")]
Size = Annotated[str, Field(min_length=1, max_length=8, description="Size code, e.g. S, M, L, XL or OS.")]
Discounts = Annotated[
    list[Annotated[float, Field(ge=0, le=100)]] | None,
    Field(description="Discounts to compare, in percent off list price. Defaults to 0, 5, 10, 15, 20, 25.",
          max_length=20),
]
Reason = Annotated[str, Field(min_length=1, max_length=600, description="Why this action is needed; shown to the approver and audited.")]
ActingAgent = Annotated[str, Field(description="Set by the agent runtime to the calling agent's name.")]
ApprovedBy = Annotated[str | None, Field(description="Set by the human-approval system to the approving person's name.")]

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
MONEY = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)
APPROVAL = {"requires_human_approval": True}

mcp = FastMCP(name="campus-customs", instructions=INSTRUCTIONS, version=__version__, mask_error_details=True)


def _read(fn, *args):
    with connect() as conn:
        return fn(conn, *args)


def _write(fn, *args):
    with transaction() as conn:
        return fn(conn, *args)


# =========================================================================== shared and boss


@mcp.tool(name="get_shop_snapshot", title="Shop snapshot", annotations=READ_ONLY, tags={"shared", "boss"})
def get_shop_snapshot() -> ShopSnapshot:
    """One-call overview of the shop today: date and desk notes, cash, open tickets, open and overdue
    invoices, rent due within 30 days, obligations and cash left after them, out-of-stock and low-stock
    rows, pending purchase orders and drafts. Start every planning session here."""
    log.info("get_shop_snapshot")
    return _read(ops.get_shop_snapshot)


@mcp.tool(name="list_tickets", title="List tickets", annotations=READ_ONLY, tags={"shared", "boss"})
def list_tickets(
    status: Annotated[str | None, Field(description="Filter by status, e.g. 'open'. Omit for all tickets.")] = "open",
) -> TicketList:
    """List tickets (id, type, requester, subject, status, created_at), oldest first. Defaults to open tickets."""
    log.info("list_tickets status=%s", status)
    return _read(ops.list_tickets, status)


@mcp.tool(name="get_ticket", title="Get ticket", annotations=READ_ONLY, tags={"shared"})
def get_ticket(ticket_id: TicketId) -> TicketDetail:
    """Full ticket with everything linked to it: the invoice or lease it references, stock of its product in
    every size, drafts already written for it, any recorded discount decision, and which analysis tool
    handles its type."""
    log.info("get_ticket ticket_id=%s", ticket_id)
    return _read(ops.get_ticket, ticket_id)


@mcp.tool(name="update_ticket_status", title="Update ticket status", annotations=WRITE, tags={"boss"})
def update_ticket_status(
    ticket_id: TicketId,
    status: Annotated[
        Literal["open", "in_progress", "waiting_on_approval", "waiting_on_vendor", "waiting_on_customer",
                "resolved", "rejected"],
        Field(description="New status."),
    ],
    note: Annotated[str, Field(min_length=1, max_length=600, description="Decision and reason, appended to the ticket notes.")],
    acting_agent: ActingAgent = "unknown",
) -> TicketUpdateResult:
    """Set a ticket's status and append a dated decision note (the original request text is kept). Boss only:
    this is how final calls are recorded on the board."""
    log.info("update_ticket_status ticket_id=%s status=%s", ticket_id, status)
    return _write(ops.update_ticket_status, ticket_id, status, note, acting_agent)


@mcp.tool(name="record_discount_decision", title="Record discount decision", annotations=WRITE,
          tags={"boss", "pricing"}, meta={"requires_human_approval_above_pct": 15.0})
def record_discount_decision(
    ticket_id: TicketId,
    discount_pct: Annotated[float, Field(ge=0, le=100, description="Discount in percent off list price.")],
    rationale: Reason,
    acting_agent: ActingAgent = "unknown",
    approved_by: ApprovedBy = None,
) -> PriceOverrideRecord:
    """Record the final price for a price_override ticket. Refuses prices below cost or below the minimum
    margin, refuses a second decision for the same ticket, and requires a named human approver for any
    discount above the Boss's authority (15%)."""
    log.info("record_discount_decision ticket_id=%s pct=%s", ticket_id, discount_pct)
    return _write(ops.record_discount_decision, ticket_id, discount_pct, rationale, acting_agent, approved_by)


# =========================================================================== ticket analysis


@mcp.tool(name="check_order_fulfillment", title="Check order fulfillment", annotations=READ_ONLY,
          tags={"orders", "inventory", "vendors"})
def check_order_fulfillment(ticket_id: TicketId) -> OrderFulfillmentReport:
    """Decide whether a customer_order ticket can ship, and if not, exactly what blocks it.

    Reads the ticket, stock for the requested SKU and size, the list price, the invoice linked to the
    ticket, the supplier on that invoice and all of its open invoices, the supplier's lead time, the cash
    balance and desk.date_today. Returns the outcome (ready_to_ship, blocked_by_unpaid_invoice,
    awaiting_restock, no_supplier_on_record), the shortfall, the amount needed to unblock the supplier and
    whether cash covers it, the earliest honest arrival date, payment proposals for human approval, and
    next steps.
    """
    log.info("check_order_fulfillment ticket_id=%s", ticket_id)
    return _read(tools.check_order_fulfillment, ticket_id)


@mcp.tool(name="review_rent_payment", title="Review rent payment", annotations=READ_ONLY,
          tags={"rent", "cash", "payments"})
def review_rent_payment(ticket_id: TicketId) -> RentReviewReport:
    """Check a rent_notice ticket and prepare the rent payment for human approval.

    Reads the ticket, the lease it references, rent payments already recorded, the cash balance, every
    open invoice and desk.date_today. Verifies that the requester is the landlord on the lease, that this
    period's rent is not already paid, and that cash covers it without going negative. Shows the cash left
    after the rent and after all open invoices, so competing bills are visible. Returns a payment proposal
    (never pays), the new lease due date after payment, and next steps.
    """
    log.info("review_rent_payment ticket_id=%s", ticket_id)
    return _read(tools.review_rent_payment, ticket_id)


@mcp.tool(name="evaluate_bulk_discount_request", title="Evaluate bulk discount request", annotations=READ_ONLY,
          tags={"pricing", "inventory", "vendors"})
def evaluate_bulk_discount_request(ticket_id: TicketId, discount_percents: Discounts = None) -> BulkDiscountReport:
    """Give the decision-maker everything needed for a price_override (bulk discount) ticket.

    Reads the ticket, stock for the SKU in every size, cost and list price, every vendor with its lead
    time and open invoices, leases due in the next 30 days, the cash balance and desk.date_today. Returns
    units fillable now and short, the cost floor, a margin table per discount with whether each is allowed
    and within the Boss's authority, restock options (blocked vendors flagged), restock cost against cash
    left after known obligations, and next steps.
    """
    log.info("evaluate_bulk_discount_request ticket_id=%s discounts=%s", ticket_id, discount_percents)
    return _read(tools.evaluate_bulk_discount_request, ticket_id, discount_percents)


# =========================================================================== inventory


@mcp.tool(name="check_stock", title="Check stock", annotations=READ_ONLY, tags={"inventory"})
def check_stock(sku: Sku, size: Annotated[str | None, Field(description="Optional size to highlight.")] = None) -> StockReport:
    """Stock of one SKU in every size (qty, location, out_of_stock/low/in_stock), total units and list price.
    Pass a size to highlight that row. Unknown SKUs or sizes return the valid ones."""
    log.info("check_stock sku=%s size=%s", sku, size)
    return _read(ops.check_stock, sku, size)


@mcp.tool(name="find_stock_shortfalls", title="Find stock shortfalls", annotations=READ_ONLY, tags={"inventory"})
def find_stock_shortfalls(
    low_stock_threshold: Annotated[int, Field(ge=0, le=100, description="Rows at or below this qty count as low.")] = 3,
) -> ShortfallReport:
    """Scan all inventory against open customer tickets. Returns every row that is out of stock, low, or short
    for the quantity open tickets ask for, with the ticket ids behind the demand."""
    log.info("find_stock_shortfalls threshold=%s", low_stock_threshold)
    return _read(ops.find_stock_shortfalls, low_stock_threshold)


@mcp.tool(name="get_vendor_status", title="Get vendor status", annotations=READ_ONLY, tags={"inventory", "accounting"})
def get_vendor_status(
    vendor_id: Annotated[int | None, Field(ge=1, description="One vendor, or omit for all.")] = None,
) -> VendorStatusReport:
    """Vendors with specialty, lead time, open invoices, whether they are blocked (unpaid invoice = no
    shipping), earliest arrival if ordered today, and pending purchase orders."""
    log.info("get_vendor_status vendor_id=%s", vendor_id)
    return _read(ops.get_vendor_status, vendor_id)


@mcp.tool(name="ship_order_from_stock", title="Ship order from stock", annotations=WRITE, tags={"inventory"})
def ship_order_from_stock(
    ticket_id: TicketId,
    qty: Annotated[int, Field(ge=1, le=1000, description="Units to ship now.")],
    acting_agent: ActingAgent = "unknown",
) -> StockMovementRecord:
    """Take units off the shelf for a customer ticket and log the stock movement. SKU and size come from the
    ticket. Refuses more than is on hand, more than the ticket still needs, and price_override tickets
    without a recorded price decision."""
    log.info("ship_order_from_stock ticket_id=%s qty=%s", ticket_id, qty)
    return _write(ops.ship_order_from_stock, ticket_id, qty, acting_agent)


# =========================================================================== accounting


@mcp.tool(name="get_cash_position", title="Get cash position", annotations=READ_ONLY, tags={"accounting"})
def get_cash_position() -> CashPositionReport:
    """Cash in every account, open and overdue invoices, unpaid rent due within 30 days, total obligations,
    cash left after them, pending purchase orders and every payment made so far."""
    log.info("get_cash_position")
    return _read(ops.get_cash_position)


@mcp.tool(name="list_invoices", title="List invoices", annotations=READ_ONLY, tags={"accounting"})
def list_invoices(
    status: Annotated[Literal["open", "paid"] | None, Field(description="Filter by status, or omit for all.")] = "open",
) -> InvoiceList:
    """Vendor invoices with vendor name, amount, due date, status and days overdue (as of desk.date_today)."""
    log.info("list_invoices status=%s", status)
    return _read(ops.list_invoices, status)


@mcp.tool(name="analyze_margin", title="Analyze margin", annotations=READ_ONLY, tags={"accounting", "pricing"})
def analyze_margin(
    sku: Sku,
    qty: Annotated[int, Field(ge=1, le=10000, description="Units in the deal.")],
    discount_percents: Discounts = None,
) -> MarginReport:
    """Margin analysis for any SKU and quantity: cost, list price, margin, break-even discount, largest allowed
    discount under the minimum-margin rule, the Boss's authority, and a scenario table."""
    log.info("analyze_margin sku=%s qty=%s", sku, qty)
    return _read(ops.analyze_margin, sku, qty, discount_percents)


@mcp.tool(name="pay_invoice", title="Pay vendor invoice", annotations=MONEY, tags={"accounting", "payments"}, meta=APPROVAL)
def pay_invoice(
    invoice_id: Annotated[int, Field(ge=1, description="invoices.id")],
    expected_amount: Annotated[float, Field(gt=0, description="Must equal the invoice amount exactly.")],
    reason: Reason,
    approved_by: ApprovedBy = None,
) -> PaymentReceipt:
    """Pay an open vendor invoice. REQUIRES HUMAN APPROVAL. In one transaction: records the payment, lowers the
    cash balance and marks the invoice paid. Refuses without a named human approver, if the amount differs,
    if the invoice is not open, or if cash would go negative."""
    log.info("pay_invoice invoice_id=%s amount=%s", invoice_id, expected_amount)
    return _write(ops.pay_invoice, invoice_id, expected_amount, reason, approved_by)


@mcp.tool(name="pay_rent", title="Pay rent", annotations=MONEY, tags={"accounting", "payments"}, meta=APPROVAL)
def pay_rent(
    lease_id: Annotated[int, Field(ge=1, description="leases.id")],
    expected_amount: Annotated[float, Field(gt=0, description="Must equal leases.monthly_rent exactly.")],
    reason: Reason,
    approved_by: ApprovedBy = None,
) -> PaymentReceipt:
    """Pay the current rent on a lease. REQUIRES HUMAN APPROVAL. In one transaction: records the payment, lowers
    the cash balance and moves the lease's next due date forward one month. Refuses without a named human
    approver, if the amount differs, if this period is already paid, or if cash would go negative."""
    log.info("pay_rent lease_id=%s amount=%s", lease_id, expected_amount)
    return _write(ops.pay_rent, lease_id, expected_amount, reason, approved_by)


@mcp.tool(name="create_purchase_order", title="Create purchase order", annotations=WRITE, tags={"accounting", "inventory"})
def create_purchase_order(
    vendor_id: Annotated[int, Field(ge=1, description="vendors.id")],
    sku: Sku,
    size: Size,
    qty: Annotated[int, Field(ge=1, le=1000)],
    reason: Reason,
    ticket_id: Annotated[int | None, Field(ge=1, description="Ticket this restock serves, if any.")] = None,
    acting_agent: ActingAgent = "unknown",
) -> PurchaseOrderResult:
    """Prepare a restock purchase order at unit cost for human approval. Nothing is sent and no money moves.
    Refuses vendors that are blocked by an open invoice and products that are not in inventory; reports
    whether cash after known obligations covers it."""
    log.info("create_purchase_order vendor_id=%s sku=%s size=%s qty=%s", vendor_id, sku, size, qty)
    return _write(ops.create_purchase_order, vendor_id, sku, size, qty, reason, ticket_id, acting_agent)


@mcp.tool(name="decide_purchase_order", title="Human decision on a purchase order", annotations=MONEY,
          tags={"human", "payments"}, meta=APPROVAL)
def decide_purchase_order(
    purchase_order_id: Annotated[int, Field(ge=1, description="purchase_orders.id")],
    approve: Annotated[bool, Field(description="True pays and releases the order; False rejects it.")],
    comment: Annotated[str, Field(max_length=600, description="The human's note for the audit trail.")] = "",
    approved_by: ApprovedBy = None,
) -> PurchaseOrderDecision:
    """HUMAN ONLY, never given to an agent. A named human approves or rejects a pending purchase order.
    Approving pays it in one transaction: records the payment, lowers the cash balance and marks the order
    approved. Refuses without a named human, if the order is not pending, if the vendor still has an open
    invoice, or if cash would go negative. Rejecting moves no money. Nothing is ever sent to the vendor."""
    log.info("decide_purchase_order id=%s approve=%s", purchase_order_id, approve)
    return _write(ops.decide_purchase_order, purchase_order_id, approve, comment, approved_by)


# =========================================================================== facilities


@mcp.tool(name="get_lease_status", title="Get lease status", annotations=READ_ONLY, tags={"facilities"})
def get_lease_status(
    lease_id: Annotated[int | None, Field(ge=1, description="One lease, or omit for all.")] = None,
) -> LeaseStatusReport:
    """Leases with space, landlord, rent, next due date, days until due, due status and whether this period is
    already paid."""
    log.info("get_lease_status lease_id=%s", lease_id)
    return _read(ops.get_lease_status, lease_id)


# =========================================================================== customer service


@mcp.tool(name="get_customer_order_view", title="Customer-safe order view", annotations=READ_ONLY,
          tags={"customer_service"})
def get_customer_order_view(ticket_id: TicketId) -> CustomerOrderView:
    """Only the facts that may be shared with the customer on an order or price request: product, size, qty,
    list price, availability, expected ready date, other sizes, any agreed price and the sharing rules.
    Contains no costs, margins, cash, invoices or vendor names by design."""
    log.info("get_customer_order_view ticket_id=%s", ticket_id)
    return _read(ops.get_customer_order_view, ticket_id)


@mcp.tool(name="save_customer_draft", title="Save draft message", annotations=WRITE, tags={"customer_service"})
def save_customer_draft(
    ticket_id: TicketId,
    subject: Annotated[str, Field(min_length=1, max_length=200)],
    body: Annotated[str, Field(min_length=1, max_length=2000)],
    acting_agent: ActingAgent = "unknown",
) -> DraftRecord:
    """Save a reply to the ticket's requester as a draft on the board. It is never sent. Drafts on customer
    tickets are refused if they contain internal information (costs, margins, cash, invoices, vendor names)."""
    log.info("save_customer_draft ticket_id=%s", ticket_id)
    return _write(ops.save_customer_draft, ticket_id, subject, body, acting_agent)


@mcp.tool(name="list_drafts", title="List drafts", annotations=READ_ONLY, tags={"customer_service", "boss"})
def list_drafts(ticket_id: Annotated[int | None, Field(ge=1, description="One ticket, or omit for all.")] = None) -> DraftList:
    """Drafts saved on the board, optionally for one ticket."""
    log.info("list_drafts ticket_id=%s", ticket_id)
    return _read(ops.list_drafts, ticket_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port, show_banner=False)
    else:
        mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
