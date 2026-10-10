const usd = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });

export const money = (n: number | null | undefined) => (n === null || n === undefined ? "—" : usd.format(n));

export const signedMoney = (n: number) => (n < 0 ? `−${usd.format(-n)}` : `+${usd.format(n)}`);

export const compact = (n: number) =>
  new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);

/** Shop dates (desk.date_today, due dates) are plain YYYY-MM-DD days, never shifted by time zone. */
export function shopDate(iso: string | null | undefined, opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric", year: "numeric" }) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", { ...opts, timeZone: "UTC" });
}

export const clock = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export function ago(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return "";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function duration(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

export const humanize = (s: string | null | undefined) => (s ?? "").replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const truncate = (s: string, n: number) => (s.length <= n ? s : `${s.slice(0, n - 1).trimEnd()}…`);

/** Ticket notes: the original note, then lines like "[2026-08-31 boss: open -> waiting_on_approval] note". */
export function splitNotes(notes: string | null) {
  const lines = (notes ?? "").split("\n").filter(Boolean);
  const history = lines
    .map((l) => l.match(/^\[(\S+) (\S+): (\S+) -> (\S+)\] (.*)$/))
    .filter((m): m is RegExpMatchArray => !!m)
    .map((m) => ({ date: m[1], agent: m[2], from: m[3], to: m[4], note: m[5] }));
  return { original: lines.filter((l) => !l.startsWith("[")).join(" "), history };
}
