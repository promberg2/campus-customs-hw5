import { useState } from "react";
import { Banknote, Info, Landmark, PackageX, Receipt, ShoppingCart, TrendingDown } from "lucide-react";
import { useBoard } from "../state/BoardContext";
import { money, shopDate, truncate, humanize } from "../lib/format";
import { Empty, Panel, Pill } from "../components/ui";
import { Kpi } from "./ApprovalsView";

interface Step { label: string; sub?: string; amount: number; kind: "start" | "out" | "total" | "pending"; overdue?: boolean }

export function FinanceView() {
  const { overview, cash, approvals } = useBoard();
  if (!overview || !cash) return <div className="desk-loading"><div className="skeleton" /><div className="skeleton" /></div>;
  const cp = overview.cash_position;
  const pendingPay = approvals.filter((a) => a.status === "pending").reduce((s, a) => s + (a.amount ?? 0), 0);
  const unpaidRent = cp.rent_due_within_30_days.filter((r) => !r.paid_this_period);

  const steps: Step[] = [
    { label: "Checking", sub: `as of ${shopDate(cash.as_of)}`, amount: cp.cash_total, kind: "start" },
    ...cp.open_invoices.map((i) => ({ label: i.vendor_name, sub: `Invoice #${i.id} · due ${shopDate(i.due_date)}`, amount: -i.amount, kind: "out" as const, overdue: i.is_overdue })),
    ...unpaidRent.map((r) => ({ label: r.lease.landlord, sub: `Rent · due ${shopDate(r.lease.next_due)}`, amount: -r.lease.monthly_rent, kind: "out" as const, overdue: r.due_status === "overdue" })),
    { label: "After bills", sub: "if every bill is paid", amount: cp.cash_after_obligations, kind: "total" },
  ];
  if (cp.pending_purchase_orders_total > 0) {
    steps.push({ label: "Pending orders", sub: "purchase orders awaiting you", amount: -cp.pending_purchase_orders_total, kind: "pending" });
    steps.push({ label: "After orders", sub: "bills and orders paid", amount: cp.cash_after_obligations - cp.pending_purchase_orders_total, kind: "total" });
  }
  const covered = cp.cash_after_obligations >= 0;

  return (
    <div className="finance">
      <div className={`fin-verdict ${covered ? "ok" : "bad"}`}>
        <Landmark size={18} />
        <div>
          <strong>{covered ? `Checking covers every known bill, with ${money(cp.cash_after_obligations)} left.` : `Known bills exceed checking by ${money(-cp.cash_after_obligations)}.`}</strong>
          <span>
            {cp.open_invoices.length} open invoice{cp.open_invoices.length === 1 ? "" : "s"} ({money(cp.open_invoices_total)}
            {cp.overdue_invoices_total > 0 && <>, {money(cp.overdue_invoices_total)} overdue</>}) and {money(cp.unpaid_rent_due_within_30_days_total)} rent due within 30 days.
          </span>
        </div>
      </div>

      <div className="kpi-row">
        <Kpi label="Checking balance" value={money(cp.cash_total)} hint={`as of ${shopDate(cash.as_of)}`} />
        <Kpi label="Bills due · 30 days" value={money(cp.obligations_total)} hint="open invoices + unpaid rent" tone={cp.overdue_invoices_total > 0 ? "warn" : undefined} />
        <Kpi label="Cash after bills" value={money(cp.cash_after_obligations)} tone={covered ? "ok" : "bad"} hint="checking minus bills" />
        <Kpi label="Awaiting your approval" value={money(pendingPay)} hint={`${approvals.filter((a) => a.status === "pending").length} item(s) on the board`} tone={pendingPay ? "warn" : undefined} />
      </div>

      <Panel icon={<TrendingDown size={16} />} title="Where the cash goes" subtitle="From today's checking balance through every known bill">
        <Waterfall steps={steps} />
        <p className="fin-note"><Info size={13} /> Only outgoing cash is modeled. Sales income is not in the shop data, so the balance can only go down from here.</p>
      </Panel>

      <div className="fin-grid">
        <Panel icon={<Receipt size={16} />} title="Bills to pay" subtitle="Open invoices and rent within 30 days">
          {cp.open_invoices.length + cp.rent_due_within_30_days.length === 0 ? <Empty title="No open bills" /> : (
            <table className="table">
              <thead><tr><th>Payee</th><th>What</th><th>Due</th><th>Status</th><th className="r">Amount</th></tr></thead>
              <tbody>
                {cp.open_invoices.map((i) => (
                  <tr key={`i${i.id}`}>
                    <td><strong>{i.vendor_name}</strong></td>
                    <td className="muted">Invoice #{i.id}{i.description ? ` · ${truncate(i.description, 40)}` : ""}</td>
                    <td>{shopDate(i.due_date)}</td>
                    <td>{i.is_overdue ? <Pill value="overdue" label={`${i.days_overdue}d overdue`} /> : <Pill value={i.status} />}</td>
                    <td className="r num">{money(i.amount)}</td>
                  </tr>
                ))}
                {cp.rent_due_within_30_days.map((r) => (
                  <tr key={`l${r.lease.id}`}>
                    <td><strong>{r.lease.landlord}</strong></td>
                    <td className="muted">Rent · {r.lease.space_name}</td>
                    <td>{shopDate(r.lease.next_due)}</td>
                    <td>{r.paid_this_period ? <Pill value="paid" /> : <Pill value={r.due_status} label={r.due_status === "due_soon" ? `in ${r.days_until_due}d` : undefined} />}</td>
                    <td className="r num">{money(r.lease.monthly_rent)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel icon={<Banknote size={16} />} title="Payments made" subtitle="Every payment and who approved it">
          {cp.payments.length === 0 ? <Empty title="No payments yet">Payments appear here after a human approves them on the board.</Empty> : (
            <table className="table">
              <thead><tr><th>When</th><th>What</th><th>Approved by</th><th className="r">Amount</th></tr></thead>
              <tbody>
                {cp.payments.map((p) => (
                  <tr key={p.id}>
                    <td>{shopDate(p.paid_at)}</td>
                    <td>{humanize(p.kind)}{p.ref_id ? ` #${p.ref_id}` : ""}</td>
                    <td>{p.approved_by}</td>
                    <td className="r num bad">−{money(p.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel icon={<ShoppingCart size={16} />} title="Purchase orders">
          {overview.purchase_orders.length === 0 ? <Empty title="No purchase orders" /> : (
            <table className="table">
              <thead><tr><th>#</th><th>Vendor</th><th>Item</th><th>Arrives</th><th>Status</th><th className="r">Total</th></tr></thead>
              <tbody>
                {overview.purchase_orders.map((po) => (
                  <tr key={po.id}>
                    <td>{po.id}</td>
                    <td>{po.vendor_name}</td>
                    <td className="muted">{po.qty} × {po.sku} {po.size}</td>
                    <td>{shopDate(po.expected_arrival)}</td>
                    <td><Pill value={po.status} /></td>
                    <td className="r num">{money(po.total_cost)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>

        <Panel icon={<PackageX size={16} />} title="Stock that needs attention">
          {overview.snapshot.out_of_stock.length + overview.snapshot.low_stock.length === 0 ? <Empty title="All stock healthy" /> : (
            <table className="table">
              <thead><tr><th>Item</th><th>Size</th><th>Where</th><th className="r">Qty</th></tr></thead>
              <tbody>
                {[...overview.snapshot.out_of_stock, ...overview.snapshot.low_stock].map((s) => (
                  <tr key={`${s.sku}-${s.size}`}>
                    <td><strong>{s.name}</strong> <span className="muted">{s.sku}</span></td>
                    <td>{s.size}</td>
                    <td className="muted">{s.location}</td>
                    <td className={`r num ${s.qty === 0 ? "bad" : "warn"}`}>{s.qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Waterfall({ steps }: { steps: Step[] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 1600, H = 280, top = 30, bottom = 64, colW = W / steps.length;
  let running = 0;
  const bars = steps.map((s) => {
    let from: number, to: number;
    if (s.kind === "start" || s.kind === "total") { from = 0; to = s.amount; running = s.amount; }
    else { from = running; to = running + s.amount; running = to; }
    return { ...s, from, to };
  });
  const values = bars.flatMap((b) => [b.from, b.to, 0]);
  const max = Math.max(...values), min = Math.min(...values);
  const y = (v: number) => top + ((max - v) / (max - min || 1)) * (H - top - bottom);

  return (
    <svg className="waterfall" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cash waterfall">
      <line x1={0} x2={W} y1={y(0)} y2={y(0)} className="wf-zero" />
      {bars.map((b, i) => {
        const w = Math.min(170, colW * 0.6), x = i * colW + (colW - w) / 2;
        const y1 = y(Math.max(b.from, b.to)), y2 = y(Math.min(b.from, b.to));
        const next = bars[i + 1];
        return (
          <g key={i} className={`wf-bar wf-${b.kind} ${b.overdue ? "wf-overdue" : ""} ${b.to < 0 && b.kind === "total" ? "wf-neg" : ""} ${hover === i ? "hover" : ""}`}
             onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} style={{ animationDelay: `${i * 70}ms` }}>
            <rect x={x} y={y1} width={w} height={Math.max(2, y2 - y1)} rx={5} />
            {next && next.kind !== "start" && next.kind !== "total" && <line className="wf-link" x1={x + w} x2={(i + 1) * colW + (colW - w) / 2} y1={y(b.to)} y2={y(b.to)} />}
            <text x={x + w / 2} y={y1 - 8} className="wf-value">{b.kind === "out" || b.kind === "pending" ? `−${money(-b.amount)}` : money(b.amount)}</text>
            <text x={x + w / 2} y={H - bottom + 22} className="wf-label">{truncate(b.label, 24)}</text>
            <text x={x + w / 2} y={H - bottom + 40} className="wf-sub">{b.overdue ? "overdue" : truncate(b.sub ?? "", 24)}</text>
          </g>
        );
      })}
    </svg>
  );
}
