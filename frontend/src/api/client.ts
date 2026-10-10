import type {
  BoardApproval,
  Cash,
  EventsResponse,
  Health,
  Overview,
  RunRecord,
  TicketsResponse,
} from "./types";

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
  } catch {
    throw new ApiError(0, `Cannot reach the backend at ${API_BASE}. Is uvicorn running?`);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/health"),
  tickets: () => request<TicketsResponse>("/api/tickets"),
  cash: () => request<Cash>("/api/cash"),
  overview: () => request<Overview>("/api/overview"),
  runs: () => request<RunRecord[]>("/api/runs"),
  approvals: () => request<BoardApproval[]>("/api/approvals"),
  events: (since: number | null, limit = 2000) =>
    request<EventsResponse>(`/api/events?limit=${limit}${since !== null ? `&since=${since}` : ""}`),
  runTicket: (ticketId: number) => request<RunRecord>(`/api/tickets/${ticketId}/run`, { method: "POST" }),
  cancelRun: (runId: string) => request<RunRecord>(`/api/runs/${runId}/cancel`, { method: "POST" }),
  approve: (id: number, approver_name: string, comment: string) =>
    request<BoardApproval>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approver_name, comment }),
    }),
  deny: (id: number, approver_name: string, comment: string) =>
    request<BoardApproval>(`/api/approvals/${id}/deny`, {
      method: "POST",
      body: JSON.stringify({ approver_name, comment }),
    }),
  reset: () => request<Cash & { approvals_cleared: number; runs_cleared: number }>("/api/reset", { method: "POST" }),
};
