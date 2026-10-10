// Shapes returned by the FastAPI backend (backend/main.py). Mirrors backend/models.py and mcp_server/models.py.

export type TicketState = "open" | "running" | "resolved";
export type RunStatus = "running" | "finished" | "failed" | "cancelled" | "interrupted";

export interface RunBrief {
  run_id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
}

export interface Ticket {
  id: number;
  type: "customer_order" | "rent_notice" | "price_override" | string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  lease_id: number | null;
  invoice_id: number | null;
  status: string;
  notes: string | null;
  created_at: string;
  state: TicketState;
  drafts: number;
  pending_approvals: number;
  agent_running: boolean;
  last_run: RunBrief | null;
}

export interface TicketsResponse {
  today: string;
  tickets: Ticket[];
}

export interface Cash {
  account: string;
  balance: number;
  as_of: string;
  today: string;
}

export interface TicketOutcome {
  ticket_id: number;
  final_status: string;
  decision: string;
  actions_taken: string[];
  awaiting_human: string[];
  draft_ids: number[];
  next_steps: string[];
}

export interface BossReport {
  summary: string;
  cash_plan: string;
  tickets: TicketOutcome[];
  risks: string[];
}

export interface RunRecord {
  run_id: string;
  ticket_id: number;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  stop_reason: string | null;
  report: BossReport | null;
  usage: Record<string, number> | null;
  error: string | null;
  ticket_status_after: string | null;
}

export interface PaymentAuthorization {
  kind: "invoice" | "rent";
  ref_id: number;
  amount: number;
  reason: string;
}

export type ApprovalStatus = "pending" | "approved" | "denied" | "failed";

export interface BoardApproval {
  id: number;
  kind: "invoice" | "rent" | "discount" | "purchase_order";
  tool: string;
  arguments: Record<string, unknown>;
  ticket_id: number | null;
  title: string;
  amount: number | null;
  reason: string;
  requested_by: string;
  chain: string[];
  team_run_id: string | null;
  boss_authorization: PaymentAuthorization | null;
  status: ApprovalStatus;
  created_at: string;
  decided_at: string | null;
  decided_by: string | null;
  comment: string | null;
  result: any;
  follow_up_run_id?: string | null;
}

export interface AuditEvent {
  seq: number;
  category: "run" | "communication" | "tool" | "approval" | "error" | "other";
  summary: string;
  ts: string;
  team_run_id: string;
  event: string;
  agent?: string;
  agent_run_id?: string;
  parent_agent?: string;
  chain?: string[];
  depth?: number;
  step?: number;
  model?: string;
  tool?: string;
  arguments?: Record<string, any>;
  result?: any;
  status?: string;
  duration_ms?: number;
  usage?: Record<string, number>;
  detail?: Record<string, any>;
}

export interface EventsResponse {
  events: AuditEvent[];
  next_since: number;
  total: number;
}

export interface Invoice {
  id: number;
  vendor_id: number;
  vendor_name: string;
  amount: number;
  due_date: string;
  status: string;
  description: string | null;
  is_overdue: boolean;
  days_overdue: number;
}

export interface LeaseDue {
  lease: { id: number; space_name: string; landlord: string; monthly_rent: number; next_due: string; notes: string | null };
  days_until_due: number;
  due_status: "overdue" | "due_today" | "due_soon" | "upcoming";
  paid_this_period: boolean;
}

export interface Payment {
  id: number;
  kind: string;
  ref_id: number | null;
  amount: number;
  account: string;
  paid_at: string;
  approved_by: string;
}

export interface StockRow {
  sku: string;
  name: string;
  size: string;
  qty: number;
  location: string;
  stock_status: "out_of_stock" | "low" | "in_stock";
}

export interface PurchaseOrder {
  id: number;
  vendor_id: number;
  vendor_name: string;
  sku: string;
  size: string;
  qty: number;
  unit_cost: number;
  total_cost: number;
  ticket_id: number | null;
  status: string;
  expected_arrival: string;
  reason: string;
  created_by: string;
  created_at: string;
}

export interface Draft {
  id: number;
  ticket_id: number;
  recipient: string;
  subject: string;
  body: string;
  status: string;
  created_by: string;
  created_at: string;
}

export interface Overview {
  snapshot: {
    today: string;
    desk_notes: string | null;
    cash_total: number;
    open_invoices_total: number;
    overdue_invoices_total: number;
    obligations_next_30_days: number;
    cash_after_obligations: number;
    out_of_stock: StockRow[];
    low_stock: StockRow[];
    pending_purchase_orders: number;
    customer_drafts: number;
  };
  cash_position: {
    today: string;
    cash_total: number;
    open_invoices: Invoice[];
    open_invoices_total: number;
    overdue_invoices_total: number;
    rent_due_within_30_days: LeaseDue[];
    unpaid_rent_due_within_30_days_total: number;
    obligations_total: number;
    cash_after_obligations: number;
    pending_purchase_orders_total: number;
    payments: Payment[];
  };
  purchase_orders: PurchaseOrder[];
  drafts: Draft[];
}

export interface Health {
  ok: boolean;
  model: string;
  active_run: string | null;
}
