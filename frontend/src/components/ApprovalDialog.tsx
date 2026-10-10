import { useState } from "react";
import { AlertTriangle, Check, KeyRound, ShieldCheck, X } from "lucide-react";
import type { BoardApproval } from "../api/types";
import { useBoard } from "../state/BoardContext";
import { RESERVED_NAMES } from "../lib/agents";
import { humanize, money } from "../lib/format";
import { AgentAvatar, Modal } from "./ui";

export function cashImpact(a: BoardApproval, balance: number | undefined, afterObligations: number | undefined) {
  if (a.amount === null || balance === undefined) return null;
  const after = balance - a.amount;
  // invoices and rent are already counted in the obligations; a purchase order would come on top
  const afterAll = afterObligations === undefined ? null : a.kind === "purchase_order" ? afterObligations - a.amount : afterObligations;
  return { before: balance, after, afterAll, overdraft: after < 0 };
}

export function ApprovalDialog({ approval, initialMode = "approve", onClose }: { approval: BoardApproval; initialMode?: "approve" | "deny"; onClose: () => void }) {
  const { approverName, setApproverName, decide, cash, overview } = useBoard();
  const [mode, setMode] = useState(initialMode);
  const [name, setName] = useState(approverName);
  const [comment, setComment] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const impact = cashImpact(approval, cash?.balance, overview?.cash_position.cash_after_obligations);
  const badName = RESERVED_NAMES.has(name.trim().toLowerCase());
  const approve = mode === "approve";
  const moneyMoves = approve && approval.amount !== null;
  const canSubmit = !busy && !badName && name.trim().length > 1 && (approve ? !moneyMoves || reviewed : comment.trim().length > 2);

  const submit = async () => {
    setBusy(true);
    setApproverName(name.trim());
    const ok = await decide(approval, approve, comment.trim(), name.trim());
    setBusy(false);
    if (ok) onClose();
  };

  return (
    <Modal
      title={approve ? `Approve #${approval.id}` : `Deny #${approval.id}`}
      tone={approve ? "warn" : undefined}
      onClose={onClose}
      footer={
        <>
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className={`btn ${approve ? "success" : "danger"}`} disabled={!canSubmit} onClick={submit}>
            {approve ? <Check size={15} /> : <X size={15} />}
            {busy ? "Working…" : approve ? (moneyMoves ? `Approve and pay ${money(approval.amount)}` : "Approve") : "Deny"}
          </button>
        </>
      }
    >
      <div className="seg seg-wide" role="tablist">
        <button className={approve ? "on ok" : ""} onClick={() => setMode("approve")}><Check size={14} /> Approve</button>
        <button className={!approve ? "on bad" : ""} onClick={() => setMode("deny")}><X size={14} /> Deny</button>
      </div>
      <div className="dialog-action">
        <span className="eyebrow">{humanize(approval.kind)} · ticket {approval.ticket_id ?? "—"}</span>
        <strong>{approval.title}</strong>
      </div>

      {impact && approve && (
        <div className={`impact ${impact.overdraft ? "impact-bad" : ""}`}>
          <div><span>Checking now</span><strong>{money(impact.before)}</strong></div>
          <div className="impact-arrow">→</div>
          <div><span>After this payment</span><strong>{money(impact.after)}</strong></div>
          {impact.afterAll !== null && (
            <div className="impact-all"><span>After all known bills</span><strong className={impact.afterAll < 0 ? "bad" : ""}>{money(impact.afterAll)}</strong></div>
          )}
        </div>
      )}
      {impact?.overdraft && approve && (
        <p className="field-error"><AlertTriangle size={14} /> This would overdraw checking. The shop server will refuse it.</p>
      )}

      <ol className="chain-steps">
        {approval.boss_authorization && (
          <li>
            <AgentAvatar id="boss" size={22} />
            <div><strong>Boss authorized</strong> <KeyRound size={12} className="muted" /> {approval.boss_authorization.reason}</div>
          </li>
        )}
        <li>
          <AgentAvatar id={approval.requested_by} size={22} />
          <div><strong>{humanize(approval.requested_by)} prepared it</strong> {approval.reason}</div>
        </li>
        <li>
          <AgentAvatar id="human" size={22} />
          <div><strong>You decide</strong> {approve ? "Approving executes it on the shop systems right away. Payments cannot be undone." : "Denying records your reason. Nothing is executed and no cash moves."}</div>
        </li>
      </ol>

      <label className="field">
        <span>Approver name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Your real name" />
      </label>
      {badName && name.trim() && <p className="field-error">Use a person's name, not an agent or system name.</p>}
      <label className="field">
        <span>{approve ? "Note (optional)" : "Reason for denying (required)"}</span>
        <textarea rows={2} value={comment} onChange={(e) => setComment(e.target.value)} placeholder={approve ? "Anything the record should show" : "Why this should not happen now"} />
      </label>
      {moneyMoves && (
        <label className="check">
          <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
          <span><ShieldCheck size={14} /> I checked the amount, the reason and the cash impact.</span>
        </label>
      )}
    </Modal>
  );
}
