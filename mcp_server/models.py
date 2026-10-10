"""Structured results returned by the MCP tools.

Every value is either read from the database or calculated from database
values. Nothing here is a guess.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Ticket(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    sku: str | None = None
    size: str | None = None
    qty: int | None = None
    lease_id: int | None = None
    invoice_id: int | None = None
    status: str
    notes: str | None = None
    created_at: str


class SizeStock(BaseModel):
    size: str
    qty: int
    location: str


class Vendor(BaseModel):
    id: int
    name: str
    specialty: str
    lead_days: int = Field(description="Days from order to arrival, from vendors.lead_days.")


class Invoice(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    amount: float
    due_date: str
    status: str
    description: str | None = None
    is_overdue: bool = Field(description="Open and due before desk.date_today.")
    days_overdue: int = Field(description="Days past due as of desk.date_today; 0 if not overdue.")


class CashPosition(BaseModel):
    account: str
    balance: float
    as_of: str = Field(description="cash_accounts.date: when the balance was last updated.")


class Lease(BaseModel):
    id: int
    space_name: str
    landlord: str
    monthly_rent: float
    next_due: str
    notes: str | None = None


class PaymentRecord(BaseModel):
    id: int
    kind: str
    ref_id: int | None = None
    amount: float
    account: str
    paid_at: str
    approved_by: str


class PaymentProposal(BaseModel):
    """A payment prepared for a human to approve. It has not been paid."""

    kind: Literal["invoice", "rent"]
    ref_id: int = Field(description="invoices.id for kind='invoice', leases.id for kind='rent'.")
    payee: str
    amount: float
    account: str
    pay_on: str = Field(description="desk.date_today.")
    requires_human_approval: Literal[True] = True
    approved: Literal[False] = False


class OrderFulfillmentReport(BaseModel):
    """Result of check_order_fulfillment (customer_order tickets, e.g. ticket 101)."""

    ticket: Ticket
    today: str = Field(description="desk.date_today.")
    outcome: Literal[
        "ready_to_ship",
        "blocked_by_unpaid_invoice",
        "awaiting_restock",
        "restock_pending_approval",
        "restock_ordered",
        "no_supplier_on_record",
    ]
    summary: str
    sku: str
    product_name: str
    size: str
    location: str
    qty_requested: int
    qty_on_hand: int
    qty_shortfall: int
    can_ship_now: bool
    unit_price: float = Field(description="pricing.list_price.")
    order_total: float = Field(description="qty_requested x unit_price.")
    other_sizes_in_stock: list[SizeStock] = Field(description="Same SKU, other sizes with qty > 0.")
    linked_invoice: Invoice | None = Field(description="The invoice named in tickets.invoice_id.")
    supplier: Vendor | None = Field(description="The vendor on the linked invoice.")
    supplier_open_invoices: list[Invoice]
    supplier_blocked: bool = Field(description="The supplier has at least one open invoice and will not ship.")
    amount_to_unblock_supplier: float
    cash: CashPosition
    cash_after_unblocking: float
    can_afford_to_unblock: bool
    earliest_arrival_if_unblocked_today: str | None = Field(
        description="desk.date_today + supplier lead_days, if a restock is needed and a supplier is known."
    )
    payments_to_approve: list[PaymentProposal]
    purchase_orders: list[PurchaseOrderRecord] = Field(
        description="Purchase orders recorded for this ticket's SKU and size, with their current status."
    )
    next_steps: list[str]


class RentReviewReport(BaseModel):
    """Result of review_rent_payment (rent_notice tickets, e.g. ticket 102)."""

    ticket: Ticket
    today: str
    outcome: Literal[
        "ready_for_approval",
        "already_paid",
        "insufficient_funds",
        "requester_does_not_match_landlord",
    ]
    summary: str
    lease: Lease
    days_until_due: int = Field(description="Negative when the rent is overdue.")
    due_status: Literal["overdue", "due_today", "due_soon", "upcoming"]
    requester_matches_landlord: bool
    notice_period_due: str = Field(
        description="The lease due date this notice is about: the first due date on or after the day the notice arrived."
    )
    already_paid_this_period: bool = Field(description="The rent for notice_period_due is recorded as paid.")
    rent_payments_on_record: list[PaymentRecord]
    cash: CashPosition
    cash_after_rent: float
    sufficient_funds: bool
    other_open_invoices: list[Invoice]
    other_open_invoices_total: float
    cash_after_rent_and_open_invoices: float = Field(
        description="What would be left if the rent and every open invoice were paid."
    )
    covers_all_known_obligations: bool
    payment_proposal: PaymentProposal | None = Field(
        description="Ready for human approval; null when the review found a reason not to pay."
    )
    next_due_after_payment: str = Field(description="leases.next_due moved forward by one month.")
    next_steps: list[str]


class DiscountScenario(BaseModel):
    discount_pct: float
    unit_price: float
    order_total: float
    total_margin: float = Field(description="(unit_price - unit_cost) x qty_requested.")
    margin_pct: float = Field(description="Margin as a percent of the discounted price.")
    above_cost: bool
    allowed: bool = Field(description="Above cost and margin at or above the minimum margin rule.")
    within_boss_authority: bool = Field(description="Allowed and at or below the Boss's discount authority.")


class RestockOption(BaseModel):
    vendor: Vendor
    open_invoices: list[Invoice]
    open_invoice_total: float
    blocked: bool = Field(description="True while the vendor has an open unpaid invoice.")
    earliest_arrival_if_ordered_today: str = Field(
        description="desk.date_today + lead_days. Only reachable once the vendor is unblocked."
    )


class BulkDiscountReport(BaseModel):
    """Result of evaluate_bulk_discount_request (price_override tickets, e.g. ticket 103)."""

    ticket: Ticket
    today: str
    outcome: Literal["can_fill_in_full", "partial_stock", "out_of_stock"]
    summary: str
    sku: str
    product_name: str
    size: str
    location: str
    qty_requested: int
    qty_on_hand: int
    qty_fillable_now: int
    qty_shortfall: int
    other_sizes_in_stock: list[SizeStock]
    list_price: float
    unit_cost: float
    margin_per_unit: float
    margin_pct: float
    list_total: float = Field(description="qty_requested x list_price, no discount.")
    cost_total: float = Field(description="qty_requested x unit_cost.")
    max_discount_pct_above_cost: float = Field(
        description="Largest discount that still keeps the price at or above unit_cost."
    )
    discount_scenarios: list[DiscountScenario]
    discount_policy_on_record: Literal[False] = Field(
        False, description="The database holds no discount policy; the limits below are server business rules."
    )
    boss_discount_authority_pct: float = Field(
        description="The Boss may grant up to this discount alone; anything above needs a named human approver."
    )
    min_margin_pct_after_discount: float = Field(
        description="No discount may push the margin below this percentage of the discounted price."
    )
    restock_cost_for_shortfall: float = Field(description="qty_shortfall x unit_cost.")
    restock_options: list[RestockOption] = Field(
        description="Every vendor. The database does not link products to vendors; choose by specialty."
    )
    cash: CashPosition
    known_obligations_total: float = Field(
        description="All open invoices plus rent due within the next 30 days of desk.date_today."
    )
    cash_after_known_obligations: float
    can_afford_restock_after_obligations: bool
    next_steps: list[str]


# --------------------------------------------------------------------------- shared views


class TicketBrief(BaseModel):
    id: int
    type: str
    requester: str
    subject: str
    status: str
    created_at: str


class TicketList(BaseModel):
    status_filter: str | None
    tickets: list[TicketBrief]


class StockRow(BaseModel):
    sku: str
    name: str
    size: str
    qty: int
    location: str
    stock_status: Literal["out_of_stock", "low", "in_stock"]


class LeaseDue(BaseModel):
    lease: Lease
    days_until_due: int = Field(description="Negative when overdue.")
    due_status: Literal["overdue", "due_today", "due_soon", "upcoming"]
    paid_this_period: bool = Field(
        description="The rent due on lease.next_due is already paid. pay_rent moves next_due one month forward, "
                    "so right after a payment this is false for the new, later due date."
    )
    last_rent_payment: PaymentRecord | None = Field(
        default=None, description="The most recent rent payment for this lease, with its date and approver."
    )


class ShopSnapshot(BaseModel):
    today: str
    desk_notes: str | None
    accounts: list[CashPosition]
    cash_total: float
    open_tickets: list[TicketBrief]
    open_invoices: list[Invoice]
    open_invoices_total: float
    overdue_invoices_total: float
    rent_due_within_30_days: list[LeaseDue]
    obligations_next_30_days: float = Field(description="Open invoices + unpaid rent due within 30 days.")
    cash_after_obligations: float
    out_of_stock: list[StockRow]
    low_stock: list[StockRow]
    pending_purchase_orders: int
    customer_drafts: int


class DraftRecord(BaseModel):
    id: int
    ticket_id: int
    recipient: str
    subject: str
    body: str
    status: str
    created_by: str
    created_at: str


class PriceOverrideRecord(BaseModel):
    id: int
    ticket_id: int
    sku: str
    qty: int
    list_price: float
    discount_pct: float
    unit_price: float
    order_total: float
    decided_by: str
    approved_by: str | None
    rationale: str
    created_at: str


class TicketDetail(BaseModel):
    ticket: Ticket
    today: str
    handled_by: str = Field(description="The MCP tool that analyses this ticket type.")
    linked_invoice: Invoice | None
    linked_lease: Lease | None
    product_stock: list[StockRow]
    drafts: list[DraftRecord]
    price_override: PriceOverrideRecord | None
    purchase_orders: list[PurchaseOrderRecord] = Field(
        description="Purchase orders created for this ticket with their current status. This is the live record; "
                    "ticket notes are history and may describe an older status."
    )
    payments: list[PaymentRecord] = Field(
        description="Payments already made for this ticket's invoice, lease and purchase orders, with the approver."
    )


class TicketUpdateResult(BaseModel):
    ticket_id: int
    previous_status: str
    new_status: str
    note_appended: str
    notes_after: str


# --------------------------------------------------------------------------- inventory


class StockReport(BaseModel):
    sku: str
    product_name: str
    list_price: float
    total_units: int
    sizes: list[StockRow]
    requested_size: StockRow | None


class ShortfallItem(BaseModel):
    sku: str
    name: str
    size: str
    location: str
    qty_on_hand: int
    open_ticket_demand: int
    shortfall: int = Field(description="max(0, open_ticket_demand - qty_on_hand).")
    ticket_ids: list[int]
    stock_status: Literal["out_of_stock", "low", "in_stock"]


class ShortfallReport(BaseModel):
    today: str
    low_stock_threshold: int
    items: list[ShortfallItem] = Field(description="Rows that are out of stock, low, or short for open tickets.")
    out_of_stock_count: int
    low_stock_count: int
    rows_short_for_open_tickets: int


class PurchaseOrderRecord(BaseModel):
    id: int
    vendor_id: int
    vendor_name: str
    sku: str
    size: str
    qty: int
    unit_cost: float
    total_cost: float
    ticket_id: int | None
    status: str
    expected_arrival: str
    reason: str
    created_by: str
    created_at: str


class VendorStatus(BaseModel):
    vendor: Vendor
    open_invoices: list[Invoice]
    open_invoice_total: float
    blocked: bool
    earliest_arrival_if_ordered_today: str
    pending_purchase_orders: list[PurchaseOrderRecord]


class VendorStatusReport(BaseModel):
    today: str
    vendors: list[VendorStatus]
    note: str


class StockMovementRecord(BaseModel):
    id: int
    ticket_id: int | None
    sku: str
    size: str
    qty_change: int
    qty_after: int
    reason: str
    created_by: str
    created_at: str


# --------------------------------------------------------------------------- accounting


class CashPositionReport(BaseModel):
    today: str
    accounts: list[CashPosition]
    cash_total: float
    open_invoices: list[Invoice]
    open_invoices_total: float
    overdue_invoices_total: float
    rent_due_within_30_days: list[LeaseDue]
    unpaid_rent_due_within_30_days_total: float
    obligations_total: float
    cash_after_obligations: float
    pending_purchase_orders_total: float = Field(description="Not yet committed; shown for planning only.")
    payments: list[PaymentRecord]


class InvoiceList(BaseModel):
    today: str
    status_filter: str | None
    invoices: list[Invoice]
    total: float


class MarginReport(BaseModel):
    sku: str
    product_name: str
    qty: int
    list_price: float
    unit_cost: float
    margin_per_unit: float
    margin_pct: float
    max_discount_pct_above_cost: float
    max_discount_pct_allowed: float = Field(description="Largest discount that keeps the minimum margin rule.")
    boss_discount_authority_pct: float
    scenarios: list[DiscountScenario]


class PaymentReceipt(BaseModel):
    payment: PaymentRecord
    payee: str
    cash_before: float
    cash_after: float
    invoice_status_after: str | None = None
    vendor_unblocked: bool | None = Field(None, description="True when the vendor has no open invoices left.")
    lease_next_due_after: str | None = None
    message: str


class PurchaseOrderResult(BaseModel):
    purchase_order: PurchaseOrderRecord
    cash_after_known_obligations: float
    affordable_after_obligations: bool
    message: str


class PurchaseOrderDecision(BaseModel):
    """A human's decision on a pending purchase order. Only an approval moves cash."""

    purchase_order: PurchaseOrderRecord
    decided_by: str
    comment: str
    receipt: PaymentReceipt | None = Field(None, description="Present only when the order was approved and paid.")
    message: str


# --------------------------------------------------------------------------- facilities


class LeaseStatusReport(BaseModel):
    today: str
    leases: list[LeaseDue]
    note: str


# --------------------------------------------------------------------------- customer service


class CustomerOrderView(BaseModel):
    """Only facts that are safe to share with the customer. No costs, cash, vendors or invoices."""

    ticket_id: int
    customer_name: str
    request_type: str
    product_name: str
    size: str
    qty: int
    unit_list_price: float
    available_now: int
    availability: Literal["ready_to_ship", "partially_available", "backordered"]
    expected_ready_date: str | None = Field(
        description="Earliest date if restocking starts today; only a promise once the Boss confirms the restock."
    )
    other_sizes_available: list[str]
    agreed_unit_price: float | None = Field(description="Set only when the Boss has recorded a discount decision.")
    ticket_status: str
    sharing_rules: list[str]


class DraftList(BaseModel):
    drafts: list[DraftRecord]
