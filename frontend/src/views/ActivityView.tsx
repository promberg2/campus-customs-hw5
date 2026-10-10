import { useMemo, useState } from "react";
import { Download, Search, X } from "lucide-react";
import type { AuditEvent } from "../api/types";
import { useBoard } from "../state/BoardContext";
import { clock, duration, humanize, shopDate } from "../lib/format";
import { AgentAvatar, Empty, Panel, Pill } from "../components/ui";

const CATEGORIES: Array<{ id: AuditEvent["category"] | "all"; label: string }> = [
  { id: "all", label: "All" },
  { id: "communication", label: "Messages" },
  { id: "tool", label: "Tool calls" },
  { id: "approval", label: "Approvals" },
  { id: "run", label: "Runs" },
  { id: "error", label: "Errors" },
];

export function ActivityView() {
  const { events, runs } = useBoard();
  const [cat, setCat] = useState<(typeof CATEGORIES)[number]["id"]>("all");
  const [runId, setRunId] = useState("all");
  const [agent, setAgent] = useState("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<AuditEvent | null>(null);

  const agents = useMemo(() => [...new Set(events.map((e) => e.agent).filter(Boolean))] as string[], [events]);
  const runIds = useMemo(() => [...new Set(events.map((e) => e.team_run_id))].reverse(), [events]);
  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return events
      .filter((e) => (cat === "all" || e.category === cat) && (runId === "all" || e.team_run_id === runId) && (agent === "all" || e.agent === agent))
      .filter((e) => !needle || `${e.summary} ${e.tool ?? ""} ${e.event}`.toLowerCase().includes(needle))
      .slice()
      .reverse();
  }, [events, cat, runId, agent, q]);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(filtered, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = Object.assign(document.createElement("a"), { href: url, download: `campus-customs-audit-${Date.now()}.json` });
    a.click();
    URL.revokeObjectURL(url);
  };

  const runLabel = (id: string) => {
    const r = runs.find((x) => x.run_id === id);
    return r ? `#${r.ticket_id} · ${id}` : id;
  };

  return (
    <div className="activity">
      <div className="filters">
        <div className="seg">
          {CATEGORIES.map((c) => (
            <button key={c.id} className={cat === c.id ? "on" : ""} onClick={() => setCat(c.id)}>
              {c.label}<span className="seg-count">{c.id === "all" ? events.length : events.filter((e) => e.category === c.id).length}</span>
            </button>
          ))}
        </div>
        <select className="select" value={runId} onChange={(e) => setRunId(e.target.value)}>
          <option value="all">All runs</option>
          {runIds.map((id) => <option key={id} value={id}>{runLabel(id)}</option>)}
        </select>
        <select className="select" value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="all">All agents</option>
          {agents.map((a) => <option key={a} value={a}>{humanize(a)}</option>)}
        </select>
        <label className="search">
          <Search size={14} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search events" />
        </label>
        <button className="btn ghost sm" onClick={exportJson} disabled={!filtered.length}><Download size={14} /> Export JSON</button>
      </div>

      <Panel title="Audit trail" subtitle={`${filtered.length} of ${events.length} events · newest first · append-only`}>
        {filtered.length === 0 ? <Empty title="No events match" /> : (
          <div className="table-wrap">
            <table className="table events-table">
              <thead><tr><th>#</th><th>Time</th><th>Agent</th><th>Type</th><th>What happened</th><th className="r">Took</th></tr></thead>
              <tbody>
                {filtered.slice(0, 600).map((e) => (
                  <tr key={e.seq} className={`clickable cat-${e.category} ${open?.seq === e.seq ? "selected" : ""}`} onClick={() => setOpen(e)}>
                    <td className="muted num">{e.seq}</td>
                    <td className="num" title={e.ts}>{shopDate(e.ts, { month: "short", day: "numeric" })} {clock(e.ts)}</td>
                    <td>{e.agent ? <span className="agent-cell"><AgentAvatar id={e.agent} size={20} /> {humanize(e.agent)}</span> : <span className="muted">—</span>}</td>
                    <td><span className={`cat-tag cat-${e.category}`}>{humanize(e.event)}</span></td>
                    <td className="ev-summary">{e.summary}</td>
                    <td className="r muted num">{e.duration_ms ? duration(e.duration_ms) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {filtered.length > 600 && <p className="muted center">Showing the newest 600. Narrow the filters or export to see everything.</p>}
          </div>
        )}
      </Panel>

      {open && (
        <aside className="drawer">
          <header>
            <div>
              <span className="eyebrow">Event #{open.seq} · {humanize(open.category)}</span>
              <h3>{humanize(open.event)}</h3>
            </div>
            <button className="icon-btn ghost" onClick={() => setOpen(null)} aria-label="Close"><X size={16} /></button>
          </header>
          <p className="drawer-summary">{open.summary}</p>
          <dl className="kv">
            <dt>Time</dt><dd>{new Date(open.ts).toLocaleString()}</dd>
            <dt>Run</dt><dd>{runLabel(open.team_run_id)}</dd>
            {open.agent && <><dt>Agent</dt><dd>{humanize(open.agent)}</dd></>}
            {open.chain && <><dt>Chain</dt><dd>{open.chain.map(humanize).join(" → ")}</dd></>}
            {open.tool && <><dt>Tool</dt><dd><code>{open.tool}</code></dd></>}
            {open.status && <><dt>Status</dt><dd><Pill value={open.status} /></dd></>}
            {open.model && <><dt>Model</dt><dd>{open.model}</dd></>}
          </dl>
          <pre className="json">{JSON.stringify(open, null, 2)}</pre>
        </aside>
      )}
    </div>
  );
}
