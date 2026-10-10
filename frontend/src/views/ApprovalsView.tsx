import { useMemo, useState } from "react";
import { ArrowRight, Check, CheckCircle2, Inbox, KeyRound, ShieldCheck, X, XCircle } from "lucide-react";
import type { BoardApproval } from "../api/types";
import { useBoard } from "../state/BoardContext";
import { ago, humanize, money } from "../lib/format";
import { ApprovalDialog, cashImpact } from "../components/ApprovalDialog";
import { AgentAvatar, Empty, Pill } from "../components/ui";

type Tab = "pending" | "decided" | "all";

export function ApprovalsView({ onOpenTicket }: { onOpenTicket: (id: number) => void }) {
  const { approvals, cash, overview, tickets } = useBoard();
  const [tab, setTab] = useState<Tab>("pending");
  const [selected, setSelected] = useState<number | null>(null);
  const [dialog, setDialog] = useState<{ a: BoardApproval; mode: "approve" | "deny" } | null>(null);

  const sorted = useMemo(
    () => [...approvals].sort((a, b) => (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1) || b.id - a.id),
    [approvals],
  );
  const list = sorted.filter((a) => tab === "all" || (tab === "pending" ? a.status === "pending" : a.status !== "pending"));
  const current = list.find((a) => a.id === selected) ?? list[0] ?? null;
  const pending = approvals.filter((a) => a.status === "pending");
  const pendingTotal = pending.reduce((s, a) => s + (a.amount ?? 0), 0);

  return (
    <div className="approvals">
      <div className="kpi-row compact">
        <Kpi label="Waiting for you" value={String(pending.length)} tone={pending.length ? "warn" : undefined} />
        <Kpi label="Cash it would move" value={money(pendingTotal)} />
        <Kpi label="Checking now" value={money(cash?.balance)} />
        <Kpi label="If you approve all" value={cash ? money(cash.balance - pendingTotal) : "—"} tone={cash && cash.balance - pendingTotal < 0 ? "bad" : undefined} />
      </div>

      <div className="split">
        <section className="split-list">
          <div className="seg seg-wide">
            {(["pending", "decided", "all"] as Tab[]).map((t) => (
              <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {humanize(t)}
                <span className="seg-count">{t === "pending" ? pending.length : t === "decided" ? approvals.length - pending.length : approvals.length}</span>
              </button>
            ))}
          </div>
          {list.length === 0 ? (
            <Empty icon={<Inbox size={22} />} title={tab === "pending" ? "Nothing waiting for you" : "No decisions yet"}>
              {tab === "pending" ? "When an agent prepares a payment or purchase, it lands here for your decision." : "Approved and denied items will show up here."}
            </Empty>
          ) : (
            <ul className="appr-list">
              {list.map((a) => (
                <li key={a.id}>
                  <button className={`appr-row ${current?.id === a.id ? "selected" : ""}`} onClick={() => setSelected(a.id)}>
                    <AgentAvatar id={a.requested_by} size={30} />
                    <div className="appr-main">
                      <strong>{a.title}</strong>
                      <span>#{a.id} · ticket {a.ticket_id ?? "—"} · {humanize(a.kind)} · {ago(a.created_at)}</span>
                    </div>
                    <div className="appr-side">
                      <strong className="num">{money(a.amount)}</strong>
                      <Pill value={a.status} />
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="split-detail">
          {current ? (
            <Detail
              a={current}
              ticketSubject={tickets.find((t) => t.id === current.ticket_id)?.subject}
              impact={cashImpact(current, cash?.balance, overview?.cash_position.cash_after_obligations)}
              onDecide={(mode) => setDialog({ a: current, mode })}
              onOpenTicket={onOpenTicket}
            />
          ) : (
            <Empty icon={<ShieldCheck size={22} />} title="Agents prepare, you decide">
              Payments, large discounts and purchase orders never execute on their own. Each one waits here with the Boss's reason and its cash impact.
            </Empty>
          )}
        </section>
      </div>
      {dialog && <ApprovalDialog approval={dialog.a} initialMode={dialog.mode} onClose={() => setDialog(null)} />}
    </div>
  );
}

function Detail({ a, impact, onDecide, onOpenTicket, ticketSubject }: {
  a: BoardApproval;
  impact: ReturnType<typeof cashImpact>;
  onDecide: (mode: "approve" | "deny") => void;
  onOpenTicket: (id: number) => void;
  ticketSubject?: string;
}) {
  const pending = a.status === "pending";
  return (
    <article className="appr-detail">
      <header>
        <span className="eyebrow">{humanize(a.kind)} · approval #{a.id}</span>
        <h2>{a.title}</h2>
        <div className="appr-amount">{money(a.amount)}</div>
        {a.ticket_id && (
          <button className="link" onClick={() => onOpenTicket(a.ticket_id!)}>Ticket #{a.ticket_id}{ticketSubject ? ` · ${ticketSubject}` : ""} <ArrowRight size={13} /></button>
        )}
      </header>

      {impact && (
        <div className={`impact ${impact.overdraft ? "impact-bad" : ""}`}>
          <div><span>Checking now</span><strong>{money(impact.before)}</strong></div>
          <div className="impact-arrow">→</div>
          <div><span>{pending ? "If approved" : "Payment amount"}</span><strong>{pending ? money(impact.after) : money(a.amount)}</strong></div>
          {pending && impact.afterAll !== null && <div className="impact-all"><span>After all known bills</span><strong className={impact.afterAll < 0 ? "bad" : ""}>{money(impact.afterAll)}</strong></div>}
        </div>
      )}

      <h4>Why this is on your desk</h4>
      <ol className="chain-steps">
        {a.boss_authorization && (
          <li>
            <AgentAvatar id="boss" size={24} />
            <div><strong>Boss authorized {a.boss_authorization.kind} {a.boss_authorization.ref_id} for {money(a.boss_authorization.amount)}</strong> <KeyRound size={12} className="muted" /><p>{a.boss_authorization.reason}</p></div>
          </li>
        )}
        <li>
          <AgentAvatar id={a.requested_by} size={24} />
          <div><strong>{humanize(a.requested_by)} prepared it</strong><p>{a.reason}</p></div>
        </li>
        <li>
          <AgentAvatar id="human" size={24} />
          <div>
            {pending ? (
              <><strong>Your decision</strong><p>Approving executes it on the shop systems with your name. The server still refuses wrong amounts, double payments and overdrafts.</p></>
            ) : (
              <>
                <strong>{humanize(a.status)} by {a.decided_by ?? "—"}</strong> <span className="muted">{ago(a.decided_at)}</span>
                {a.comment && <p>“{a.comment}”</p>}
                {a.result?.message && <p className="receipt">{a.result.message}</p>}
              </>
            )}
          </div>
        </li>
      </ol>

      <details className="details">
        <summary>Exact action sent to the shop systems</summary>
        <pre className="json">{JSON.stringify({ tool: a.tool, arguments: a.arguments }, null, 2)}</pre>
      </details>

      {pending ? (
        <div className="appr-actions">
          <button className="btn danger ghost" onClick={() => onDecide("deny")}><X size={15} /> Deny…</button>
          <button className="btn success" onClick={() => onDecide("approve")}><Check size={15} /> Review and approve…</button>
        </div>
      ) : (
        <div className={`appr-final appr-final-${a.status}`}>
          {a.status === "approved" ? <CheckCircle2 size={16} /> : <XCircle size={16} />}
          {a.status === "approved" ? "Executed. Cash moved and the shop records were updated." : a.status === "denied" ? "Denied. Nothing was executed." : "The shop server refused it. No cash moved."}
        </div>
      )}
    </article>
  );
}

export function Kpi({ label, value, tone, hint }: { label: string; value: string; tone?: string; hint?: string }) {
  return (
    <div className={`kpi ${tone ? `kpi-${tone}` : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {hint && <em>{hint}</em>}
    </div>
  );
}
