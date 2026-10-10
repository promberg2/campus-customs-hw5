import { useState } from "react";
import {
  Activity,
  ArrowRight,
  Bell,
  CalendarDays,
  ChevronDown,
  LayoutDashboard,
  LineChart,
  RotateCcw,
  ShieldCheck,
  UserRound,
  Wallet,
  WifiOff,
} from "lucide-react";
import { useBoard } from "../state/BoardContext";
import { money, shopDate } from "../lib/format";
import { RESERVED_NAMES } from "../lib/agents";
import { AnimatedMoney, Modal } from "./ui";

export type View = "desk" | "approvals" | "finance" | "activity";

const NAV: Array<{ id: View; label: string; icon: typeof LayoutDashboard; hint: string }> = [
  { id: "desk", label: "Desk", icon: LayoutDashboard, hint: "Tickets and the live agent team" },
  { id: "approvals", label: "Approvals", icon: ShieldCheck, hint: "Decisions waiting for you" },
  { id: "finance", label: "Finance", icon: LineChart, hint: "Cash, obligations and payments" },
  { id: "activity", label: "Activity", icon: Activity, hint: "Full audit trail" },
];

export function Sidebar({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) {
  const { approvals, health, connected } = useBoard();
  const pending = approvals.filter((a) => a.status === "pending").length;
  return (
    <nav className="sidebar" aria-label="Main">
      <div className="brand">
        <div className="brand-mark">CC</div>
        <div className="brand-text">
          <strong>Campus Customs</strong>
          <span>Back-office desk</span>
        </div>
      </div>
      <ul className="nav">
        {NAV.map(({ id, label, icon: Icon, hint }) => (
          <li key={id}>
            <button className={`nav-item ${view === id ? "active" : ""}`} onClick={() => onNavigate(id)} title={hint}>
              <Icon size={18} />
              <span>{label}</span>
              {id === "approvals" && pending > 0 && <span className="nav-badge">{pending}</span>}
            </button>
          </li>
        ))}
      </ul>
      <div className="sidebar-foot">
        <div className="model-chip" title="Every agent runs on this model through Portkey">
          <span className={`status-dot ${connected ? "ok" : "bad"}`} />
          <div>
            <strong>{health?.model ?? "gpt-6-luna"}</strong>
            <span>{connected ? "via Portkey · API live" : "API offline"}</span>
          </div>
        </div>
      </div>
    </nav>
  );
}

const TITLES: Record<View, [string, string]> = {
  desk: ["Desk", "Choose a ticket, put the team on it, and watch them work"],
  approvals: ["Approvals", "Agents prepare. You decide. Cash moves only here."],
  finance: ["Finance", "What we have, what we owe, and what is left"],
  activity: ["Activity", "Every step, message and decision, as recorded in the audit trail"],
};

export function TopBar({ view, onNavigate }: { view: View; onNavigate: (v: View) => void }) {
  const { cash, today, approvals, approverName, setApproverName, reset, activeRun, overview } = useBoard();
  const [menu, setMenu] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [editName, setEditName] = useState(false);
  const pending = approvals.filter((a) => a.status === "pending").length;
  const after = overview?.cash_position.cash_after_obligations;
  const [title, subtitle] = TITLES[view];

  return (
    <header className="topbar">
      <div className="topbar-title">
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <div className="topbar-right">
        <div className="chip" title="The shop's 'today' (desk.date_today). Overdue is measured from this date.">
          <CalendarDays size={15} />
          <span className="chip-label">Shop date</span>
          <strong>{shopDate(today, { weekday: "short", month: "short", day: "numeric", year: "numeric" })}</strong>
        </div>
        <button className="chip chip-cash" onClick={() => onNavigate("finance")} title="Checking balance from cash_accounts">
          <Wallet size={15} />
          <span className="chip-label">Checking</span>
          <AnimatedMoney value={cash?.balance} className="chip-money" />
          {after !== undefined && (
            <span className={`chip-sub ${after < 0 ? "bad" : after < 500 ? "warn" : ""}`}>{money(after)} after bills</span>
          )}
        </button>
        <button
          className="chip chip-reset"
          disabled={!!activeRun}
          onClick={() => setConfirmReset(true)}
          title={activeRun ? "Wait until the team has finished" : "Homework only: restore the original database so the tickets can be run again"}
        >
          <RotateCcw size={15} />
          <span>Reset</span>
        </button>
        <button className={`icon-btn bell ${pending ? "has" : ""}`} onClick={() => onNavigate("approvals")} title={`${pending} decision(s) waiting`}>
          <Bell size={17} />
          {pending > 0 && <span className="bell-badge">{pending}</span>}
        </button>
        <div className="user-menu">
          <button className="user-btn" onClick={() => setMenu((m) => !m)}>
            <span className="user-initials">{(approverName || "?").slice(0, 2).toUpperCase()}</span>
            <span className="user-name">{approverName || "Set your name"}</span>
            <ChevronDown size={14} />
          </button>
          {menu && (
            <div className="menu" onMouseLeave={() => setMenu(false)}>
              <div className="menu-label">Approving as</div>
              <button className="menu-item" onClick={() => { setEditName(true); setMenu(false); }}>
                <UserRound size={15} /> {approverName ? "Change approver name" : "Set approver name"}
              </button>
              <div className="menu-sep" />
              <button className="menu-item danger" disabled={!!activeRun} onClick={() => { setConfirmReset(true); setMenu(false); }}>
                <RotateCcw size={15} /> Reset database…
              </button>
            </div>
          )}
        </div>
      </div>

      {confirmReset && (
        <Modal
          title="Start fresh?"
          tone="danger"
          onClose={() => setConfirmReset(false)}
          footer={
            <>
              <button className="btn ghost" onClick={() => setConfirmReset(false)}>Keep current state</button>
              <button className="btn danger" onClick={async () => { if (await reset()) setConfirmReset(false); }}>
                <RotateCcw size={15} /> Reset to original values
              </button>
            </>
          }
        >
          <p>This copies the original database over the working copy. Payments, ticket statuses, drafts and purchase orders return to their starting values, and the approval board and run history are cleared.</p>
          <p className="muted">The audit trail is append-only and keeps everything that happened.</p>
        </Modal>
      )}
      {editName && <ApproverNameModal initial={approverName} onSave={(n) => { setApproverName(n); setEditName(false); }} onClose={() => setEditName(false)} />}
    </header>
  );
}

export function ApproverNameModal({ initial, onSave, onClose }: { initial: string; onSave: (name: string) => void; onClose: () => void }) {
  const [name, setName] = useState(initial);
  const invalid = RESERVED_NAMES.has(name.trim().toLowerCase());
  return (
    <Modal
      title="Who is approving?"
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={invalid} onClick={() => onSave(name.trim())}>Save</button>
        </>
      }
    >
      <p>Every payment is recorded with the real name of the person who approved it. Agent names are not accepted.</p>
      <label className="field">
        <span>Your name</span>
        <input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Philipp" onKeyDown={(e) => e.key === "Enter" && !invalid && onSave(name.trim())} />
      </label>
      {invalid && name.trim() && <p className="field-error">Use a person's name, not an agent or system name.</p>}
    </Modal>
  );
}

export function NeedsYouBanner({ onNavigate }: { onNavigate: (v: View) => void }) {
  const { approvals } = useBoard();
  const pending = approvals.filter((a) => a.status === "pending");
  if (!pending.length) return null;
  const total = pending.reduce((s, a) => s + (a.amount ?? 0), 0);
  return (
    <div className="needs-you">
      <ShieldCheck size={18} />
      <div>
        <strong>{pending.length === 1 ? "1 decision needs you" : `${pending.length} decisions need you`}</strong>
        <span>{pending.map((a) => a.title).join(" · ")}{total > 0 && ` — ${money(total)} in total`}</span>
      </div>
      <button className="btn warn sm" onClick={() => onNavigate("approvals")}>
        Review <ArrowRight size={14} />
      </button>
    </div>
  );
}

export function OfflineBanner() {
  const { connected } = useBoard();
  if (connected) return null;
  return (
    <div className="offline">
      <WifiOff size={16} />
      <span>
        Cannot reach the backend at <code>localhost:8000</code>. Start it from <code>backend/</code> with{" "}
        <code>uvicorn main:app --reload --port 8000</code>. Retrying automatically…
      </span>
    </div>
  );
}
