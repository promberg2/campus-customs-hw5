import { CheckCircle2, FileText, Home, Loader2, RotateCw, ShieldAlert, ShoppingBag, Tag } from "lucide-react";
import type { Ticket } from "../api/types";
import { humanize } from "../lib/format";

/** The team's run is done and every approval is decided, but the database still waits for the Boss to close it. */
export const needsFollowUp = (t: Ticket) =>
  t.state === "resolved" && t.status === "waiting_on_approval" && t.pending_approvals === 0;

export const TICKET_TYPE: Record<string, { label: string; icon: typeof Tag }> = {
  customer_order: { label: "Customer order", icon: ShoppingBag },
  rent_notice: { label: "Rent notice", icon: Home },
  price_override: { label: "Price request", icon: Tag },
};

export function ticketItemLine(t: Ticket) {
  if (t.sku) return `${t.qty ?? "?"} × ${t.sku}${t.size ? ` · size ${t.size}` : ""}`;
  if (t.lease_id) return `Lease ${t.lease_id}`;
  if (t.invoice_id) return `Invoice ${t.invoice_id}`;
  return "";
}

export function StatePill({ ticket }: { ticket: Ticket }) {
  if (ticket.state === "running")
    return <span className="state state-running"><Loader2 size={13} className="spin" /> Team working</span>;
  if (ticket.status === "resolved")
    return <span className="state state-resolved"><CheckCircle2 size={13} /> Resolved</span>;
  if (ticket.state === "resolved")
    return (
      <span className="state state-done" title={`The team finished its run; the ticket is ${humanize(ticket.status).toLowerCase()}.`}>
        <CheckCircle2 size={13} /> Team done
      </span>
    );
  return <span className="state state-open"><span className="state-dot" /> Open</span>;
}

export function TicketCard({ ticket, selected, onSelect, index }: { ticket: Ticket; selected: boolean; onSelect: () => void; index: number }) {
  const type = TICKET_TYPE[ticket.type] ?? { label: humanize(ticket.type), icon: FileText };
  const Icon = type.icon;
  const note = (ticket.notes ?? "").split("\n")[0];
  return (
    <button className={`ticket-card ${selected ? "selected" : ""} ticket-${ticket.state}`} onClick={onSelect} aria-pressed={selected}>
      <div className="ticket-top">
        <span className="ticket-type"><Icon size={14} /> {type.label}</span>
        <StatePill ticket={ticket} />
      </div>
      <div className="ticket-title">
        <span className="ticket-id">#{ticket.id}</span> {ticket.subject}
      </div>
      <div className="ticket-meta">
        <span>{ticket.requester}</span>
        {ticketItemLine(ticket) && <span className="dot-sep">{ticketItemLine(ticket)}</span>}
      </div>
      {note && <p className="ticket-note">“{note}”</p>}
      <div className="ticket-foot">
        <span className="db-status" title="Status in the tickets table">{humanize(ticket.status)}</span>
        <span className="ticket-badges">
          {ticket.pending_approvals > 0 && (
            <span className="mini-badge warn"><ShieldAlert size={12} /> {ticket.pending_approvals} approval</span>
          )}
          {needsFollowUp(ticket) && (
            <span className="mini-badge info" title="You decided the approvals. Run the team again so the Boss confirms and closes the ticket."><RotateCw size={12} /> Follow-up run</span>
          )}
          {ticket.drafts > 0 && <span className="mini-badge"><FileText size={12} /> {ticket.drafts} draft</span>}
          <span className="kbd-hint">{index + 1}</span>
        </span>
      </div>
    </button>
  );
}
