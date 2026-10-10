import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, FastForward, Inbox, Network, PackageX, Play, RotateCcw, Square } from "lucide-react";
import type { BoardApproval } from "../api/types";
import { useBoard } from "../state/BoardContext";
import { usePlayer } from "../hooks/usePlayer";
import { buildGraph } from "../lib/runModel";
import { AGENTS } from "../lib/agents";
import { ago, humanize } from "../lib/format";
import { TicketCard, TICKET_TYPE, StatePill, ticketItemLine } from "../components/TicketCard";
import { TeamGraph } from "../components/TeamGraph";
import { ConversationFeed } from "../components/ConversationFeed";
import { RunInspector } from "../components/RunInspector";
import { ApprovalDialog } from "../components/ApprovalDialog";
import { Empty, Kbd, Panel } from "../components/ui";

export function DeskView({ selectedId, onSelect, onOpenApprovals }: { selectedId: number | null; onSelect: (id: number) => void; onOpenApprovals: () => void }) {
  const { tickets, runs, events, approvals, overview, activeRun, runTicket, cancelRun, loaded } = useBoard();
  const [reviewing, setReviewing] = useState<BoardApproval | null>(null);
  const [runChoice, setRunChoice] = useState<string | null>(null);

  const ticket = tickets.find((t) => t.id === selectedId) ?? tickets[0] ?? null;
  const ticketRuns = useMemo(() => runs.filter((r) => r.ticket_id === ticket?.id), [runs, ticket?.id]);
  const run = ticketRuns.find((r) => r.run_id === runChoice) ?? ticketRuns[0] ?? null;
  const live = run?.status === "running";
  const runEvents = useMemo(() => (run ? events.filter((e) => e.team_run_id === run.run_id) : []), [events, run]);
  const player = usePlayer(run?.run_id ?? null, runEvents, live);
  const graph = useMemo(() => buildGraph(player.playedEvents), [player.playedEvents]);
  const ticketApprovals = approvals.filter((a) => a.ticket_id === ticket?.id);
  if (ticketApprovals.some((a) => a.status === "pending")) {
    graph.nodes.human.status = "waiting";
    graph.nodes.human.caption = "Your decision is needed";
  }
  const drafts = (overview?.drafts ?? []).filter((d) => d.ticket_id === ticket?.id);
  const canRun = !activeRun && !!ticket;

  useEffect(() => setRunChoice(null), [ticket?.id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest("input, textarea, select") || e.metaKey || e.ctrlKey || e.altKey) return;
      const n = Number(e.key);
      if (n >= 1 && n <= tickets.length) onSelect(tickets[n - 1].id);
      if (e.key.toLowerCase() === "r" && canRun && ticket) runTicket(ticket.id);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tickets, onSelect, canRun, ticket, runTicket]);

  if (!loaded) return <div className="desk-loading"><div className="skeleton" /><div className="skeleton" /><div className="skeleton" /></div>;
  if (!ticket) return <Empty icon={<Inbox size={22} />} title="No tickets on the desk" />;

  const type = TICKET_TYPE[ticket.type];
  const alerts = [...(overview?.snapshot.out_of_stock ?? []), ...(overview?.snapshot.low_stock ?? [])];

  return (
    <div className="desk">
      <aside className="desk-col desk-tickets">
        <div className="col-head">
          <h2>Tickets</h2>
          <span className="muted">
            {tickets.filter((t) => t.state !== "resolved").length} open · {tickets.filter((t) => t.state === "resolved" && t.status !== "resolved").length} waiting · {tickets.filter((t) => t.status === "resolved").length} resolved
          </span>
        </div>
        <div className="ticket-list">
          {tickets.map((t, i) => (
            <TicketCard key={t.id} index={i} ticket={t} selected={t.id === ticket.id} onSelect={() => onSelect(t.id)} />
          ))}
        </div>
        {alerts.length > 0 && (
          <div className="alerts">
            <h3><PackageX size={14} /> Stock alerts</h3>
            {alerts.map((s) => (
              <div key={`${s.sku}-${s.size}`} className="alert-row">
                <span>{s.name} · {s.size}</span>
                <span className={s.stock_status === "out_of_stock" ? "bad" : "warn"}>{s.qty === 0 ? "out of stock" : `${s.qty} left`}</span>
              </div>
            ))}
          </div>
        )}
        <p className="shortcut-hint"><Kbd>1</Kbd>–<Kbd>{tickets.length}</Kbd> select · <Kbd>R</Kbd> run team</p>
      </aside>

      <section className="desk-col desk-main">
        <div className="ticket-header">
          <div className="th-left">
            <span className="th-type">{type ? <type.icon size={15} /> : null} {type?.label ?? humanize(ticket.type)} · #{ticket.id}</span>
            <h2>{ticket.subject}</h2>
            <p>
              <strong>{ticket.requester}</strong>
              {ticketItemLine(ticket) && <> · {ticketItemLine(ticket)}</>}
              {" · "}<span className="muted">“{(ticket.notes ?? "").split("\n")[0]}”</span>
            </p>
          </div>
          <div className="th-right">
            <StatePill ticket={ticket} />
            {live ? (
              <button className="btn danger" onClick={() => run && cancelRun(run.run_id)}><Square size={14} /> Stop</button>
            ) : (
              <button className="btn primary" disabled={!canRun} onClick={() => runTicket(ticket.id)} title={activeRun ? `The team is busy with #${activeRun.ticket_id}` : "Start the agent team on this ticket"}>
                <Play size={15} /> {run ? "Run team again" : "Run team"}
              </button>
            )}
          </div>
        </div>
        {activeRun && activeRun.ticket_id !== ticket.id && (
          <div className="busy-note"><AlertTriangle size={14} /> The team is busy on ticket #{activeRun.ticket_id}. <button className="link" onClick={() => onSelect(activeRun.ticket_id)}>Watch it →</button></div>
        )}

        <Panel
          className="graph-panel"
          icon={<Network size={16} />}
          title="Agent team"
          subtitle={live ? "Live: every hand-off lights up as it happens" : run ? `Run ${run.run_id} · ${ago(run.finished_at ?? run.started_at)}` : "Who works with whom"}
          actions={
            <>
              {ticketRuns.length > 1 && (
                <select className="select sm" value={run?.run_id ?? ""} onChange={(e) => setRunChoice(e.target.value)}>
                  {ticketRuns.map((r, i) => <option key={r.run_id} value={r.run_id}>{i === 0 ? "Latest run" : `Run ${r.run_id}`} · {humanize(r.status)}</option>)}
                </select>
              )}
              {live && <span className="live-badge"><span className="live-dot" /> LIVE</span>}
              {!live && run && runEvents.length > 0 && (
                player.replaying ? (
                  <>
                    <div className="seg">
                      {[1, 2, 4].map((s) => <button key={s} className={player.speed === s ? "on" : ""} onClick={() => player.setSpeed(s)}>{s}×</button>)}
                    </div>
                    <button className="btn ghost sm" onClick={player.skip}><FastForward size={14} /> Skip</button>
                  </>
                ) : (
                  <button className="btn ghost sm" onClick={player.replay}><RotateCcw size={14} /> Replay run</button>
                )
              )}
            </>
          }
        >
          <TeamGraph graph={graph} pulses={player.pulses} bubble={player.bubble} onPulseDone={player.removePulse} />
          <div className="graph-legend">
            <span><i className="lg lg-msg" /> Task or report</span>
            <span><i className="lg lg-tool" /> Tool call to the shop systems</span>
            <span><i className="lg lg-appr" /> Human approval</span>
            <span className="muted">Badge = messages + tool calls per agent</span>
            {player.replaying && <span className="replay-progress">Replaying {player.played}/{runEvents.length}</span>}
          </div>
        </Panel>

        <Panel
          className="feed-panel"
          title="Team conversation"
          subtitle={run ? `${runEvents.filter((e) => e.event === "delegation_request" || e.event === "delegation_result").length} messages · ${runEvents.filter((e) => e.event === "tool_call").length} tool calls` : undefined}
          actions={<div className="feed-agents">{Object.values(AGENTS).slice(0, 5).map((a) => <span key={a.id} style={{ color: a.color }}>● {a.name}</span>)}</div>}
        >
          {run ? (
            <ConversationFeed events={player.playedEvents} live={live || player.replaying} onOpenApprovals={onOpenApprovals} />
          ) : (
            <Empty icon={<Network size={22} />} title="No conversation yet" action={<button className="btn primary sm" disabled={!canRun} onClick={() => runTicket(ticket.id)}>Run team on #{ticket.id} <ArrowRight size={14} /></button>}>
              When the team works on this ticket, every task, report, tool call and approval appears here as it happens.
            </Empty>
          )}
        </Panel>
      </section>

      <aside className="desk-col desk-inspector">
        <RunInspector
          ticket={ticket}
          run={run}
          events={runEvents}
          approvals={ticketApprovals}
          drafts={drafts}
          canRun={canRun}
          onRun={() => runTicket(ticket.id)}
          onCancel={() => run && cancelRun(run.run_id)}
          onReview={(a) => setReviewing(a)}
        />
        {ticketApprovals.filter((a) => a.status !== "pending").length > 0 && (
          <div className="insp-card decided">
            <h4>Decisions on this ticket</h4>
            {ticketApprovals.filter((a) => a.status !== "pending").map((a) => (
              <div key={a.id} className="decided-row">
                <span>{a.title}</span>
                <span className={`decided-${a.status}`}>{humanize(a.status)} by {a.decided_by ?? "—"}</span>
              </div>
            ))}
          </div>
        )}
      </aside>

      {reviewing && <ApprovalDialog approval={reviewing} onClose={() => setReviewing(null)} />}
    </div>
  );
}
