import { useEffect, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCircle2,
  Circle,
  Clock,
  Coins,
  FileText,
  History,
  ListChecks,
  Loader2,
  MessagesSquare,
  MinusCircle,
  ShieldAlert,
  Sparkles,
  Users,
  Wrench,
} from "lucide-react";
import type { AuditEvent, BoardApproval, Draft, RunRecord, Ticket } from "../api/types";
import { compact, duration, humanize, shopDate, splitNotes } from "../lib/format";
import { runStages, runStats } from "../lib/runModel";
import { AgentAvatar, Pill } from "./ui";

function useNow(active: boolean) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [active]);
  return now;
}

export function RunInspector({
  ticket, run, events, approvals, drafts, onReview, onCancel, onRun, canRun,
}: {
  ticket: Ticket;
  run: RunRecord | null;
  events: AuditEvent[];
  approvals: BoardApproval[];
  drafts: Draft[];
  onReview: (a: BoardApproval) => void;
  onCancel: () => void;
  onRun: () => void;
  canRun: boolean;
}) {
  const live = run?.status === "running";
  const now = useNow(live);
  const stats = runStats(events);
  const pending = approvals.filter((a) => a.status === "pending");
  const stages = runStages(events, pending.length, live);
  const startMs = run ? new Date(run.started_at).getTime() : 0;
  const endMs = run?.finished_at ? new Date(run.finished_at).getTime() : now;
  const outcome = run?.report?.tickets.find((t) => t.ticket_id === ticket.id) ?? run?.report?.tickets[0];
  const decidedAfterRun = approvals.filter((a) => a.status === "approved" && run?.finished_at && a.decided_at && a.decided_at > run.finished_at);
  const decidedBeforeRun = approvals.filter((a) => a.status !== "pending" && run && a.decided_at && a.decided_at < run.started_at);
  const skippedCaption = decidedBeforeRun.length
    ? `No new request · ${decidedBeforeRun.map((a) => `#${a.id}`).join(", ")} decided before this run`
    : "No approval was needed";
  const { history } = splitNotes(ticket.notes);

  return (
    <div className="inspector">
      {!run && (
        <section className="insp-card insp-hero">
          <Sparkles size={22} />
          <h3>The team hasn't worked on this ticket yet</h3>
          <p>The Boss reads the desk, hands work to the right specialists, and reports back. Payments wait for you.</p>
          <button className="btn primary" disabled={!canRun} onClick={onRun}>Put the team on #{ticket.id} <ArrowRight size={15} /></button>
        </section>
      )}

      {run && (
        <section className={`insp-card run-status run-${run.status}`}>
          <div className="run-status-top">
            <div>
              <span className="eyebrow">Run {run.run_id}</span>
              <h3>
                {live && <><Loader2 size={17} className="spin" /> Team is working</>}
                {run.status === "finished" && <><CheckCircle2 size={17} /> Finished by the team</>}
                {run.status === "failed" && <><AlertTriangle size={17} /> Run failed</>}
                {run.status === "cancelled" && <><MinusCircle size={17} /> Stopped by you</>}
                {run.status === "interrupted" && <><AlertTriangle size={17} /> Interrupted</>}
              </h3>
            </div>
            <div className="run-clock"><Clock size={14} /> {duration(endMs - startMs)}</div>
          </div>
          {live && (
            <button className="btn ghost danger sm stop-btn" onClick={onCancel}>
              <MinusCircle size={14} /> Stop the run
            </button>
          )}
          {run.error && <p className="run-error">{run.error}</p>}

          <ol className="stages">
            {stages.map((s) => (
              <li key={s.id} className={`stage stage-${s.state}`}>
                <span className="stage-icon">
                  {s.state === "done" ? <Check size={12} /> : s.state === "current" ? <Loader2 size={12} className="spin" /> : s.state === "waiting" ? <ShieldAlert size={12} /> : s.state === "skipped" ? <MinusCircle size={12} /> : <Circle size={8} />}
                </span>
                <div>
                  <strong>{s.label}</strong>
                  <span>{s.state === "skipped" ? skippedCaption : s.state === "waiting" ? "Waiting for your decision" : s.hint}</span>
                </div>
              </li>
            ))}
          </ol>

          <div className="stat-grid">
            <Stat icon={<Users size={14} />} label="Agents" value={String(stats.agents.length)}>
              <span className="avatars">{stats.agents.map((a) => <AgentAvatar key={a} id={a} size={18} />)}</span>
            </Stat>
            <Stat icon={<MessagesSquare size={14} />} label="Hand-offs" value={String(stats.delegations)} />
            <Stat icon={<Wrench size={14} />} label="Tool calls" value={String(stats.toolCalls)} />
            <Stat icon={<Coins size={14} />} label="Tokens" value={compact(run.usage?.total_tokens ?? stats.tokens)} />
          </div>
        </section>
      )}

      {pending.length > 0 && (
        <section className="insp-card insp-approvals">
          <h4><ShieldAlert size={15} /> Waiting for your decision</h4>
          {pending.map((a) => (
            <div key={a.id} className="mini-approval">
              <div>
                <strong>{a.title}</strong>
                <span>Requested by {humanize(a.requested_by)}{a.boss_authorization ? " · authorized by the Boss" : ""}</span>
              </div>
              <button className="btn warn sm" onClick={() => onReview(a)}>Review</button>
            </div>
          ))}
        </section>
      )}

      {run?.status === "finished" && run.report && (
        <section className="insp-card summary">
          <h4><ListChecks size={15} /> What the team did</h4>
          <p className="summary-lead">{run.report.summary}</p>
          {outcome && (
            <>
              <div className="summary-decision">
                <span className="eyebrow">Boss's decision</span>
                <p>{outcome.decision}</p>
                <div className="summary-status">Ticket status after the run: <Pill value={outcome.final_status} /></div>
              </div>
              <Bullets title="Actions taken" items={outcome.actions_taken} icon={<Check size={13} />} />
              <Bullets title="Waiting on a human" items={outcome.awaiting_human} icon={<ShieldAlert size={13} />} tone="warn" />
              <Bullets title="Next steps" items={outcome.next_steps} icon={<ArrowRight size={13} />} />
            </>
          )}
          {run.report.cash_plan && (
            <div className="summary-cash">
              <span className="eyebrow">Cash plan</span>
              <p>{run.report.cash_plan}</p>
            </div>
          )}
          <Bullets title="Risks" items={run.report.risks} icon={<AlertTriangle size={13} />} tone="bad" />
          {decidedAfterRun.length > 0 && (
            <div className="follow-up">
              <p><strong>You approved {decidedAfterRun.map((a) => `#${a.id}`).join(", ")} after this run.</strong> Put the team on it again so the Boss can confirm the payment and close the ticket.</p>
              <button className="btn primary sm" disabled={!canRun} onClick={onRun}>Run follow-up <ArrowRight size={14} /></button>
            </div>
          )}
        </section>
      )}

      {drafts.length > 0 && (
        <section className="insp-card">
          <h4><FileText size={15} /> Customer drafts <span className="muted">· saved, never sent</span></h4>
          {drafts.map((d) => (
            <details key={d.id} className="draft">
              <summary>
                <strong>{d.subject}</strong>
                <span>To {d.recipient} · by {humanize(d.created_by)}</span>
              </summary>
              <p>{d.body}</p>
            </details>
          ))}
        </section>
      )}

      {history.length > 0 && (
        <section className="insp-card">
          <h4><History size={15} /> Ticket history</h4>
          <ol className="history">
            {history.map((h, i) => (
              <li key={i}>
                <AgentAvatar id={h.agent} size={20} />
                <div>
                  <span><strong>{humanize(h.agent)}</strong> moved it {humanize(h.from).toLowerCase()} → <strong>{humanize(h.to).toLowerCase()}</strong> · {shopDate(h.date, { month: "short", day: "numeric" })}</span>
                  <p>{h.note}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

function Stat({ icon, label, value, children }: { icon: ReactNode; label: string; value: string; children?: ReactNode }) {
  return (
    <div className="stat">
      <span className="stat-label">{icon}{label}</span>
      <strong>{value}</strong>
      {children}
    </div>
  );
}

function Bullets({ title, items, icon, tone }: { title: string; items?: string[]; icon: ReactNode; tone?: string }) {
  if (!items?.length) return null;
  return (
    <div className={`bullets ${tone ? `bullets-${tone}` : ""}`}>
      <span className="eyebrow">{title}</span>
      <ul>
        {items.map((x, i) => (
          <li key={i}><span className="b-icon">{icon}</span>{x}</li>
        ))}
      </ul>
    </div>
  );
}
