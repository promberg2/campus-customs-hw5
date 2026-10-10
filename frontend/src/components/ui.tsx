import { useEffect, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { agentMeta } from "../lib/agents";
import { humanize, money } from "../lib/format";

export function Panel({
  title, icon, actions, children, className = "", subtitle,
}: { title: ReactNode; icon?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; subtitle?: ReactNode }) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <div className="panel-title">
          {icon}
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
        </div>
        {actions && <div className="panel-actions">{actions}</div>}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

const STATUS_TONE: Record<string, string> = {
  open: "neutral", in_progress: "info", waiting_on_approval: "warn", waiting_on_vendor: "info",
  waiting_on_customer: "info", resolved: "ok", rejected: "bad",
  pending: "warn", approved: "ok", denied: "neutral", failed: "bad",
  running: "live", finished: "ok", cancelled: "neutral", interrupted: "bad",
  done: "ok", blocked: "bad", needs_decision: "warn", incomplete: "warn",
  overdue: "bad", due_today: "bad", due_soon: "warn", upcoming: "neutral",
};

export function Pill({ value, label, tone }: { value?: string; label?: ReactNode; tone?: string }) {
  const t = tone ?? STATUS_TONE[value ?? ""] ?? "neutral";
  return (
    <span className={`pill pill-${t}`}>
      {t === "live" && <span className="live-dot" />}
      {label ?? humanize(value)}
    </span>
  );
}

export function AgentAvatar({ id, size = 28 }: { id: string | undefined; size?: number }) {
  const m = agentMeta(id);
  const Icon = m.icon;
  return (
    <span className="avatar" style={{ width: size, height: size, ["--c" as string]: m.color }} title={`${m.name} · ${m.role}`}>
      <Icon size={Math.round(size * 0.55)} strokeWidth={2} />
    </span>
  );
}

export function AgentName({ id }: { id: string | undefined }) {
  const m = agentMeta(id);
  return <span className="agent-name" style={{ color: m.color }}>{m.name}</span>;
}

export function Modal({ title, onClose, children, footer, tone }: { title: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; tone?: "warn" | "danger" }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${tone ? `modal-${tone}` : ""}`} role="dialog" aria-modal="true">
        <header className="modal-head">
          <h3>{title}</h3>
          <button className="icon-btn ghost" onClick={onClose} aria-label="Close"><X size={16} /></button>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>
  );
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className={`empty ${icon ? "" : "empty-sm"}`}>
      {icon && <div className="empty-icon">{icon}</div>}
      <strong>{title}</strong>
      {children && <p>{children}</p>}
      {action}
    </div>
  );
}

/** Money that counts smoothly to its new value, so a balance change is noticed. */
export function AnimatedMoney({ value, className }: { value: number | null | undefined; className?: string }) {
  const [shown, setShown] = useState(value ?? 0);
  const [flash, setFlash] = useState<"" | "down" | "up">("");
  const from = useRef<number | null>(value ?? null);
  useEffect(() => {
    if (value === null || value === undefined) return;
    const start = from.current;
    if (start === null || Math.abs(start - value) < 0.005 || document.hidden) {
      from.current = value;
      setShown(value);
      return;
    }
    setFlash(value < start ? "down" : "up");
    const t0 = performance.now();
    let raf = 0;
    const step = (now: number) => {
      const k = Math.min(1, (now - t0) / 900);
      const ease = 1 - Math.pow(1 - k, 3);
      setShown(start + (value - start) * ease);
      if (k < 1) raf = requestAnimationFrame(step);
      else {
        from.current = value;
        window.setTimeout(() => setFlash(""), 900);
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [value]);
  if (value === null || value === undefined) return <span className={className}>—</span>;
  return <span className={`${className ?? ""} money-anim ${flash ? `flash-${flash}` : ""}`}>{money(shown)}</span>;
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="kbd">{children}</kbd>;
}
