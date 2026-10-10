import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, CircleDollarSign, Info, X, XCircle } from "lucide-react";

export type ToastTone = "success" | "error" | "info" | "money";

interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  body?: string;
}

interface ToastApi {
  push: (t: Omit<Toast, "id">) => void;
}

const Ctx = createContext<ToastApi | null>(null);
const ICON = { success: CheckCircle2, error: XCircle, info: Info, money: CircleDollarSign };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  const push = useCallback(
    (t: Omit<Toast, "id">) => {
      const id = Date.now() + Math.random();
      setToasts((prev) => [...prev.slice(-3), { ...t, id }]);
      window.setTimeout(() => dismiss(id), t.tone === "error" ? 9000 : 5500);
    },
    [dismiss],
  );
  const api = useMemo(() => ({ push }), [push]);
  return (
    <Ctx.Provider value={api}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => {
          const Icon = ICON[t.tone];
          return (
            <div key={t.id} className={`toast toast-${t.tone}`}>
              <Icon size={18} className="toast-icon" />
              <div className="toast-text">
                <strong>{t.title}</strong>
                {t.body && <span>{t.body}</span>}
              </div>
              <button className="icon-btn ghost" onClick={() => dismiss(t.id)} aria-label="Dismiss">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
    </Ctx.Provider>
  );
}

export function useToasts() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useToasts must be used inside ToastProvider");
  return ctx;
}
