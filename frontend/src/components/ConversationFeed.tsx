import { useEffect, useRef, useState, type ReactNode } from "react";
import { AlertTriangle, ChevronRight, KeyRound, Flag, PlayCircle, ShieldAlert, Wrench } from "lucide-react";
import type { AuditEvent } from "../api/types";
import { agentMeta } from "../lib/agents";
import { clock, duration, humanize, money } from "../lib/format";
import { AgentAvatar, AgentName, Pill } from "./ui";

/** The team's conversation for one run, written for a person: who said what to whom, and what they used. */
export function ConversationFeed({ events, live, onOpenApprovals }: { events: AuditEvent[]; live: boolean; onOpenApprovals: () => void }) {
  const box = useRef<HTMLDivElement>(null);
  const [stick, setStick] = useState(true);

  useEffect(() => {
    if (stick && box.current) box.current.scrollTo({ top: box.current.scrollHeight, behavior: live ? "smooth" : "auto" });
  }, [events.length, stick, live]);

  const visible = events.filter((e) => !(e.event === "model_step" && !e.detail?.text) && e.event !== "agent_run_start");

  return (
    <div
      className="feed"
      ref={box}
      onScroll={(e) => {
        const el = e.currentTarget;
        setStick(el.scrollHeight - el.scrollTop - el.clientHeight < 60);
      }}
    >
      {visible.map((e) => (
        <FeedItem key={e.seq} e={e} onOpenApprovals={onOpenApprovals} />
      ))}
      {live && (
        <div className="feed-typing">
          <span /><span /><span />
          <em>The team is working…</em>
        </div>
      )}
    </div>
  );
}

function Time({ ts }: { ts: string }) {
  return <time className="feed-time">{clock(ts)}</time>;
}

function FeedItem({ e, onOpenApprovals }: { e: AuditEvent; onOpenApprovals: () => void }) {
  const d = e.detail ?? {};
  switch (e.event) {
    case "team_run_start":
      return <Divider icon={<PlayCircle size={14} />} text={`Team run started on ticket ${(d.tickets ?? []).join(", ")}`} ts={e.ts} />;
    case "team_run_end":
      return (
        <Divider
          icon={<Flag size={14} />}
          text={`Run ${e.status === "final_output" ? "complete" : humanize(e.status)} · ${(e.usage?.total_tokens ?? 0).toLocaleString()} tokens · ${d.delegations_used ?? 0} delegations`}
          ts={e.ts}
        />
      );
    case "delegation_request":
      return (
        <Message from={e.agent} to={d.to} ts={e.ts} label="Task">
          <Expandable text={d.task} />
        </Message>
      );
    case "delegation_result": {
      const r = e.result ?? {};
      return (
        <Message from={d.from} to={e.agent} ts={e.ts} label="Report" status={e.status}>
          <p>{r.summary}</p>
          {(r.facts?.length || r.actions_taken?.length || r.needs_human_approval?.length || r.recommendations?.length) ? (
            <Details label={`${r.facts?.length ?? 0} facts · evidence`}>
              {r.facts?.length > 0 && (
                <table className="facts">
                  <tbody>
                    {r.facts.map((f: any, i: number) => (
                      <tr key={i}>
                        <td>{f.label}</td>
                        <td><strong>{f.value}</strong></td>
                        <td><code>{f.source_tool}</code></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <ListBlock title="Done" items={r.actions_taken} />
              <ListBlock title="Recommends" items={r.recommendations} />
              <ListBlock title="Needs a human" items={r.needs_human_approval} />
              <ListBlock title="Needs the Boss" items={r.needs_boss_decision} />
            </Details>
          ) : null}
        </Message>
      );
    }
    case "delegation_refused":
      return <Note tone="warn" icon={<AlertTriangle size={14} />} ts={e.ts}><AgentName id={e.agent} /> could not reach {agentMeta(d.to).name}: {d.reason}</Note>;
    case "model_step":
      return (
        <div className="thought">
          <AgentAvatar id={e.agent} size={22} />
          <p><AgentName id={e.agent} /> <span className="muted">thinks</span> {d.text}</p>
          <Time ts={e.ts} />
        </div>
      );
    case "tool_call":
      return <ToolRow e={e} />;
    case "boss_authorization":
      return (
        <Note tone="key" icon={<KeyRound size={14} />} ts={e.ts}>
          <strong>Boss authorizes</strong> paying {d.kind} {d.ref_id} for <strong>{money(Number(d.amount))}</strong>. <span className="muted">{d.reason}</span>
          <div className="note-sub">First key of two. A human still has to approve.</div>
        </Note>
      );
    case "approval_requested":
      return (
        <Note tone="warn" icon={<ShieldAlert size={14} />} ts={e.ts}>
          <AgentName id={e.agent} /> needs a human for <code>{e.tool}</code>{" "}
          {e.arguments?.expected_amount !== undefined && <strong>{money(Number(e.arguments.expected_amount))}</strong>}
          <div className="note-sub">{d.reason}</div>
        </Note>
      );
    case "approval_decision":
      if (e.status === "queued_for_human")
        return (
          <Note tone="warn" icon={<ShieldAlert size={14} />} ts={e.ts}>
            <strong>On your approval board</strong> as #{d.approval_id}. Nothing has been paid.
            <button className="link" onClick={onOpenApprovals}>Review now →</button>
          </Note>
        );
      return (
        <Note tone={e.status === "approved" ? "ok" : "neutral"} icon={<ShieldAlert size={14} />} ts={e.ts}>
          <strong>{d.approver ?? "Human"}</strong> {e.status} <code>{e.tool}</code>
          {d.comment && <span className="muted"> — {d.comment}</span>}
        </Note>
      );
    case "agent_run_end":
      if (e.agent !== "boss" || !e.result) return null;
      return (
        <Message from="boss" ts={e.ts} label="Final report" status={e.status === "final_output" ? "done" : e.status}>
          <p>{e.result.summary}</p>
        </Message>
      );
    case "error":
      return <Note tone="bad" icon={<AlertTriangle size={14} />} ts={e.ts}><AgentName id={e.agent} />: {d.message}</Note>;
    case "db_reset":
      return <Divider icon={<Flag size={14} />} text="Database reset to the original values" ts={e.ts} />;
    default:
      return null;
  }
}

function Message({ from, to, ts, label, status, children }: { from?: string; to?: string; ts: string; label: string; status?: string; children: ReactNode }) {
  const m = agentMeta(from);
  return (
    <article className="msg" style={{ ["--c" as string]: m.color }}>
      <AgentAvatar id={from} />
      <div className="msg-body">
        <header>
          <AgentName id={from} />
          {to && (
            <>
              <ChevronRight size={13} className="muted" />
              <AgentName id={to} />
            </>
          )}
          <span className="msg-label">{label}</span>
          {status && <Pill value={status} />}
          <Time ts={ts} />
        </header>
        <div className="msg-text">{children}</div>
      </div>
    </article>
  );
}

function Note({ tone, icon, ts, children }: { tone: string; icon: ReactNode; ts: string; children: ReactNode }) {
  return (
    <div className={`note note-${tone}`}>
      <span className="note-icon">{icon}</span>
      <div className="note-text">{children}</div>
      <Time ts={ts} />
    </div>
  );
}

function Divider({ icon, text, ts }: { icon: ReactNode; text: string; ts: string }) {
  return (
    <div className="feed-divider">
      <span>{icon}{text}</span>
      <Time ts={ts} />
    </div>
  );
}

function ToolRow({ e }: { e: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const ok = e.status === "ok";
  const args = Object.entries(e.arguments ?? {}).filter(([k]) => k !== "acting_agent" && k !== "approved_by");
  return (
    <div className={`tool-row ${ok ? "" : "tool-bad"}`}>
      <button className="tool-head" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <Wrench size={13} style={{ color: agentMeta(e.agent).color }} />
        <AgentName id={e.agent} />
        <span className="muted">used</span>
        <code>{e.tool}</code>
        {args.length > 0 && <span className="tool-args">{args.map(([k, v]) => `${k}=${typeof v === "object" ? "…" : v}`).join(", ")}</span>}
        <span className="tool-meta">
          {!ok && <Pill value={e.status} tone="bad" />}
          {e.duration_ms !== undefined && <span>{duration(e.duration_ms) === "0s" ? `${e.duration_ms} ms` : duration(e.duration_ms)}</span>}
          <ChevronRight size={13} className={`chev ${open ? "open" : ""}`} />
        </span>
      </button>
      {open && <pre className="json">{JSON.stringify({ arguments: e.arguments, result: e.result }, null, 2)}</pre>}
    </div>
  );
}

function Expandable({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = (text ?? "").length > 320;
  return (
    <p className={`expandable ${open || !long ? "open" : ""}`}>
      {text}
      {long && <button className="link" onClick={() => setOpen((o) => !o)}>{open ? "Show less" : "Show more"}</button>}
    </p>
  );
}

function Details({ label, children }: { label: string; children: ReactNode }) {
  return (
    <details className="details">
      <summary>{label}</summary>
      <div className="details-body">{children}</div>
    </details>
  );
}

function ListBlock({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="list-block">
      <span>{title}</span>
      <ul>{items.map((x, i) => <li key={i}>{x}</li>)}</ul>
    </div>
  );
}
