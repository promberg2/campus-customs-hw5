import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "../api/client";
import type { AuditEvent, BoardApproval, Cash, Health, Overview, RunRecord, Ticket } from "../api/types";
import { money, signedMoney } from "../lib/format";
import { useToasts } from "./Toasts";

const FAST_MS = 1200;
const SLOW_MS = 4000;
const APPROVER_KEY = "cc.approverName";

interface BoardState {
  connected: boolean;
  loaded: boolean;
  health: Health | null;
  today: string | null;
  tickets: Ticket[];
  cash: Cash | null;
  approvals: BoardApproval[];
  runs: RunRecord[];
  overview: Overview | null;
  events: AuditEvent[];
  activeRun: RunRecord | null;
  approverName: string;
  setApproverName: (name: string) => void;
  runTicket: (ticketId: number) => Promise<RunRecord | null>;
  cancelRun: (runId: string) => Promise<void>;
  decide: (approval: BoardApproval, approve: boolean, comment: string, name?: string) => Promise<boolean>;
  reset: () => Promise<boolean>;
  refresh: () => void;
}

const Ctx = createContext<BoardState | null>(null);

export function BoardProvider({ children }: { children: ReactNode }) {
  const toast = useToasts();
  const [connected, setConnected] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [today, setToday] = useState<string | null>(null);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cash, setCash] = useState<Cash | null>(null);
  const [approvals, setApprovals] = useState<BoardApproval[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [approverName, setApproverNameState] = useState(() => localStorage.getItem(APPROVER_KEY) ?? "");

  const cursor = useRef<number | null>(null);
  const prevRuns = useRef<Map<string, RunRecord>>(new Map());
  const prevBalance = useRef<number | null>(null);
  const tickCount = useRef(0);
  const timer = useRef<number | undefined>(undefined);
  const wake = useRef<() => void>(() => {});

  const activeRun = useMemo(() => runs.find((r) => r.status === "running") ?? null, [runs]);

  const setApproverName = useCallback((name: string) => {
    setApproverNameState(name);
    localStorage.setItem(APPROVER_KEY, name);
  }, []);

  const notifyRunChanges = useCallback(
    (next: RunRecord[]) => {
      const before = prevRuns.current;
      if (before.size || loaded) {
        for (const r of next) {
          const old = before.get(r.run_id);
          if (old?.status === "running" && r.status !== "running") {
            if (r.status === "finished") toast.push({ tone: "success", title: `Team finished ticket #${r.ticket_id}`, body: "The team finished. The summary is ready on the desk." });
            else if (r.status === "cancelled") toast.push({ tone: "info", title: `Run on #${r.ticket_id} stopped`, body: "Nothing new was started after you stopped it." });
            else toast.push({ tone: "error", title: `Run on #${r.ticket_id} ${r.status}`, body: r.error ?? "The team stopped without a final report." });
          }
        }
      }
      prevRuns.current = new Map(next.map((r) => [r.run_id, r]));
    },
    [loaded, toast],
  );

  const tick = useCallback(async () => {
    tickCount.current += 1;
    try {
      const withOverview = tickCount.current === 1 || tickCount.current % 3 === 0;
      const [t, c, a, r, ev, h, o] = await Promise.all([
        api.tickets(),
        api.cash(),
        api.approvals(),
        api.runs(),
        api.events(cursor.current, 2000),
        tickCount.current % 5 === 1 ? api.health() : Promise.resolve(null),
        withOverview ? api.overview() : Promise.resolve(null),
      ]);
      setTickets(t.tickets);
      setToday(t.today);
      setCash(c);
      if (prevBalance.current !== null && Math.abs(prevBalance.current - c.balance) >= 0.005) {
        toast.push({ tone: "money", title: `Cash moved ${signedMoney(c.balance - prevBalance.current)}`, body: `Checking is now ${money(c.balance)}.` });
      }
      prevBalance.current = c.balance;
      setApprovals(a);
      notifyRunChanges(r);
      setRuns(r);
      if (ev.events.length) {
        setEvents((prev) => {
          const seen = new Set(prev.map((e) => e.seq));
          const fresh = ev.events.filter((e) => !seen.has(e.seq));
          return fresh.length ? [...prev, ...fresh] : prev;
        });
      }
      if (cursor.current === null || ev.next_since > cursor.current) cursor.current = ev.next_since;
      if (ev.total < (cursor.current ?? 0)) {
        cursor.current = null;
        setEvents([]);
      }
      if (h) setHealth(h);
      if (o) setOverview(o);
      setConnected(true);
      setLoaded(true);
      return r.some((x) => x.status === "running");
    } catch {
      setConnected(false);
      return false;
    }
  }, [notifyRunChanges, toast]);

  useEffect(() => {
    let alive = true;
    const loop = async () => {
      const busy = await tick();
      if (!alive) return;
      timer.current = window.setTimeout(loop, busy ? FAST_MS : SLOW_MS);
    };
    wake.current = () => {
      window.clearTimeout(timer.current);
      loop();
    };
    loop();
    return () => {
      alive = false;
      window.clearTimeout(timer.current);
    };
  }, [tick]);

  const refresh = useCallback(() => wake.current(), []);

  const fail = useCallback(
    (title: string, err: unknown) => {
      toast.push({ tone: "error", title, body: err instanceof ApiError ? err.message : String(err) });
    },
    [toast],
  );

  const runTicket = useCallback(
    async (ticketId: number) => {
      try {
        const run = await api.runTicket(ticketId);
        toast.push({ tone: "info", title: `Team started on #${ticketId}`, body: "Watch the agents work together in real time." });
        setRuns((prev) => [run, ...prev]);
        prevRuns.current.set(run.run_id, run);
        refresh();
        return run;
      } catch (err) {
        fail("Could not start the team", err);
        return null;
      }
    },
    [fail, refresh, toast],
  );

  const cancelRun = useCallback(
    async (runId: string) => {
      try {
        await api.cancelRun(runId);
        refresh();
      } catch (err) {
        fail("Could not stop the run", err);
      }
    },
    [fail, refresh],
  );

  const decide = useCallback(
    async (approval: BoardApproval, approve: boolean, comment: string, name?: string) => {
      const who = (name ?? approverName).trim();
      try {
        const res = approve ? await api.approve(approval.id, who, comment) : await api.deny(approval.id, who, comment);
        toast.push({
          tone: approve ? "success" : "info",
          title: approve ? `Approved #${approval.id}` : `Denied #${approval.id}`,
          body: approve ? res.result?.message ?? res.title : "Nothing was executed and no cash moved.",
        });
        if (approve && res.ticket_id != null) {
          toast.push({
            tone: "info",
            title: `The team continues on #${res.ticket_id}`,
            body: res.follow_up_run_id
              ? "A new run started with your decision."
              : "The team picks up your decision and keeps working.",
          });
        }
        refresh();
        return true;
      } catch (err) {
        fail(approve ? "Approval was not executed" : "Could not deny", err);
        refresh();
        return false;
      }
    },
    [approverName, fail, refresh, toast],
  );

  const reset = useCallback(async () => {
    try {
      const r = await api.reset();
      prevBalance.current = r.balance;
      toast.push({ tone: "success", title: "Fresh start", body: `Database restored. Checking is back to ${money(r.balance)}.` });
      refresh();
      return true;
    } catch (err) {
      fail("Reset failed", err);
      return false;
    }
  }, [fail, refresh, toast]);

  const value: BoardState = {
    connected, loaded, health, today, tickets, cash, approvals, runs, overview, events, activeRun,
    approverName, setApproverName, runTicket, cancelRun, decide, reset, refresh,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useBoard() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useBoard must be used inside BoardProvider");
  return ctx;
}
