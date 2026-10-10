import type { AuditEvent } from "../api/types";
import { AGENTS, type NodeId } from "./agents";
import { money, truncate } from "./format";

/* ------------------------------------------------------------------ graph state */

export type NodeStatus = "idle" | "working" | "waiting" | "done";

export interface NodeState {
  status: NodeStatus;
  caption: string;
  toolCalls: number;
  messages: number;
}

export interface EdgeState {
  key: string;
  count: number;
  active: boolean;
  lastSeq: number;
  color: string;
}

export interface GraphState {
  nodes: Record<NodeId, NodeState>;
  edges: Record<string, EdgeState>;
  started: boolean;
  finished: boolean;
}

export const edgeKey = (a: string, b: string) => [a, b].sort().join("~");

const asNode = (id: string | undefined): NodeId | null =>
  id && id in AGENTS ? (id as NodeId) : null;

function emptyGraph(): GraphState {
  const nodes = {} as Record<NodeId, NodeState>;
  (Object.keys(AGENTS) as NodeId[]).forEach((id) => {
    nodes[id] = { status: "idle", caption: id === "human" ? "No decision needed yet" : "Idle", toolCalls: 0, messages: 0 };
  });
  return { nodes, edges: {}, started: false, finished: false };
}

function touchEdge(g: GraphState, a: NodeId, b: NodeId, seq: number, color: string, active?: boolean) {
  const key = edgeKey(a, b);
  const e = g.edges[key] ?? { key, count: 0, active: false, lastSeq: seq, color };
  e.count += 1;
  e.lastSeq = seq;
  e.color = color;
  if (active !== undefined) e.active = active;
  g.edges[key] = e;
}

/** Fold the events of one run (in order) into what the team graph shows at that moment. */
export function buildGraph(events: AuditEvent[]): GraphState {
  const g = emptyGraph();
  const openRuns: Partial<Record<NodeId, number>> = {};
  for (const e of events) {
    const agent = asNode(e.agent);
    const d = e.detail ?? {};
    switch (e.event) {
      case "team_run_start":
        g.started = true;
        break;
      case "agent_run_start":
        if (agent) {
          openRuns[agent] = (openRuns[agent] ?? 0) + 1;
          g.nodes[agent].status = "working";
          g.nodes[agent].caption = agent === "boss" ? "Reading the desk" : "Working on the task";
        }
        break;
      case "agent_run_end":
        if (agent) {
          openRuns[agent] = Math.max(0, (openRuns[agent] ?? 1) - 1);
          if (!openRuns[agent]) {
            g.nodes[agent].status = "done";
            g.nodes[agent].caption = e.status === "final_output" ? "Reported back" : `Stopped (${e.status})`;
          }
        }
        break;
      case "model_step":
        if (agent) {
          const tools: string[] = (d.tool_calls ?? []).map((c: any) => c.tool);
          const handoff = tools.find((t) => t === "delegate_task" || t === "consult_colleague");
          const real = tools.filter((t) => t !== "final_result" && t !== handoff);
          g.nodes[agent].caption = handoff
            ? "Handing off work"
            : real.length
              ? `Calling ${real.join(", ")}`
              : tools.includes("final_result")
                ? "Writing the report"
                : "Thinking";
        }
        break;
      case "tool_call":
        if (agent && agent !== "human") {
          g.nodes[agent].toolCalls += 1;
          g.nodes[agent].caption = `Used ${e.tool}`;
          g.nodes.mcp.toolCalls += 1;
          g.nodes.mcp.caption = `${e.tool} · ${e.status}`;
          g.nodes.mcp.status = "done";
          touchEdge(g, agent, "mcp", e.seq, AGENTS[agent].color);
        } else if (agent === "human") {
          g.nodes.human.caption = e.status === "ok" ? "Executed on the shop systems" : "Refused by the shop systems";
          touchEdge(g, "human", "mcp", e.seq, AGENTS.human.color);
        }
        break;
      case "delegation_request": {
        const to = asNode(d.to);
        if (agent && to) {
          touchEdge(g, agent, to, e.seq, AGENTS[agent].color, true);
          g.nodes[agent].messages += 1;
          g.nodes[agent].caption = `Asked ${AGENTS[to].name}`;
        }
        break;
      }
      case "delegation_result": {
        const from = asNode(d.from);
        if (agent && from) {
          touchEdge(g, from, agent, e.seq, AGENTS[from].color, false);
          g.nodes[from].messages += 1;
        }
        break;
      }
      case "delegation_refused":
        if (agent) g.nodes[agent].caption = "Delegation refused";
        break;
      case "boss_authorization":
        g.nodes.boss.caption = `Authorized ${d.kind} ${d.ref_id} · ${money(Number(d.amount))}`;
        break;
      case "approval_requested":
        if (agent) {
          touchEdge(g, agent, "human", e.seq, AGENTS.human.color, true);
          g.nodes.human.status = "waiting";
          g.nodes.human.caption = "Approval requested";
        }
        break;
      case "approval_decision":
        if (agent === "human") {
          g.nodes.human.status = "done";
          g.nodes.human.caption = e.status === "approved" ? "Approved" : "Denied";
        } else if (agent) {
          const key = edgeKey(agent, "human");
          if (g.edges[key]) g.edges[key].active = false;
          g.nodes.human.status = e.status === "queued_for_human" ? "waiting" : "done";
          g.nodes.human.caption =
            e.status === "queued_for_human" ? "Waiting for your decision" : e.status === "approved" ? "Approved" : "Denied";
        }
        break;
      case "team_run_end":
        g.finished = true;
        Object.values(g.edges).forEach((ed) => (ed.active = false));
        TEAM.forEach((id) => {
          if (g.nodes[id].status === "working") g.nodes[id].status = "done";
        });
        break;
    }
  }
  return g;
}

const TEAM: NodeId[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];

/* ------------------------------------------------------------------ animation */

export interface Pulse {
  id: string;
  from: NodeId;
  to: NodeId;
  color: string;
  kind: "message" | "tool" | "approval" | "result";
}

/** The particles one event sends along the graph when it is played. */
export function pulsesFor(e: AuditEvent): Omit<Pulse, "id">[] {
  const agent = asNode(e.agent);
  const d = e.detail ?? {};
  switch (e.event) {
    case "delegation_request": {
      const to = asNode(d.to);
      return agent && to ? [{ from: agent, to, color: AGENTS[agent].color, kind: "message" }] : [];
    }
    case "delegation_result": {
      const from = asNode(d.from);
      return agent && from ? [{ from, to: agent, color: AGENTS[from].color, kind: "result" }] : [];
    }
    case "tool_call":
      if (!agent) return [];
      return [
        { from: agent, to: "mcp", color: AGENTS[agent].color, kind: "tool" },
        { from: "mcp", to: agent, color: AGENTS.mcp.color, kind: "tool" },
      ];
    case "approval_requested":
      return agent ? [{ from: agent, to: "human", color: AGENTS.human.color, kind: "approval" }] : [];
    case "approval_decision":
      return agent && agent !== "human" && e.status !== "queued_for_human"
        ? [{ from: "human", to: agent, color: AGENTS.human.color, kind: "approval" }]
        : [];
    default:
      return [];
  }
}

export interface Bubble {
  node: NodeId;
  text: string;
  seq: number;
}

/** A short speech bubble for events where someone says something. */
export function bubbleFor(e: AuditEvent): Bubble | null {
  const agent = asNode(e.agent);
  const d = e.detail ?? {};
  const say = (node: NodeId | null, text: string | undefined) =>
    node && text ? { node, text: truncate(text.replace(/\s+/g, " "), 150), seq: e.seq } : null;
  switch (e.event) {
    case "delegation_request":
      return say(agent, `@${AGENTS[asNode(d.to) ?? "mcp"].name}: ${d.task}`);
    case "delegation_result":
      return say(asNode(d.from), e.result?.summary);
    case "boss_authorization":
      return say("boss", `I authorize ${d.kind} ${d.ref_id} for ${money(Number(d.amount))}. ${d.reason}`);
    case "approval_requested":
      return say(agent, `This needs a human: ${e.tool}.`);
    case "approval_decision":
      return e.status === "queued_for_human" ? say("human", "Waiting on my decision in Approvals.") : null;
    case "model_step":
      return d.text ? say(agent, d.text) : null;
    case "agent_run_end":
      return agent === "boss" ? say("boss", e.result?.summary) : null;
    default:
      return null;
  }
}

/* ------------------------------------------------------------------ run statistics and stages */

export interface RunStats {
  agents: NodeId[];
  delegations: number;
  toolCalls: number;
  tokens: number;
  approvals: number;
  startedAt: string | null;
  endedAt: string | null;
}

export function runStats(events: AuditEvent[]): RunStats {
  const agents = new Set<NodeId>();
  let delegations = 0, toolCalls = 0, tokens = 0, approvals = 0;
  for (const e of events) {
    const a = asNode(e.agent);
    if (e.event === "agent_run_start" && a) agents.add(a);
    if (e.event === "delegation_request") delegations++;
    if (e.event === "tool_call" && e.agent !== "human") toolCalls++;
    if (e.event === "model_step") tokens += e.usage?.total_tokens ?? 0;
    if (e.event === "approval_requested") approvals++;
  }
  const start = events.find((e) => e.event === "team_run_start");
  const end = [...events].reverse().find((e) => e.event === "team_run_end");
  return {
    agents: TEAM.filter((a) => agents.has(a)),
    delegations, toolCalls, tokens, approvals,
    startedAt: start?.ts ?? null,
    endedAt: end?.ts ?? null,
  };
}

export type StageState = "done" | "current" | "waiting" | "upcoming" | "skipped";

export interface Stage {
  id: string;
  label: string;
  hint: string;
  state: StageState;
}

export function runStages(events: AuditEvent[], pendingApprovals: number, live: boolean): Stage[] {
  const has = (name: string) => events.some((e) => e.event === name);
  const requests = events.filter((e) => e.event === "delegation_request").length;
  const results = events.filter((e) => e.event === "delegation_result").length;
  const read = events.some((e) => e.event === "tool_call" && e.agent === "boss");
  const asked = has("approval_requested");
  const ended = has("team_run_end");
  const raw: Array<[string, string, string, boolean | "skip" | "wait"]> = [
    ["read", "Read the desk", "Boss checks tickets, cash and obligations", read],
    ["delegate", "Delegate", "Boss hands work to the right specialists", requests > 0],
    ["report", "Specialists report", "Findings come back with facts from the tools", requests > 0 && results >= requests],
    ["approve", "Human approval", "Payments wait for a named person", !asked ? (ended ? "skip" : false) : pendingApprovals > 0 ? "wait" : true],
    ["close", "Boss's report", "Final decision and ticket status", ended],
  ];
  let currentSet = false;
  return raw.map(([id, label, hint, v]) => {
    let state: StageState;
    if (v === true) state = "done";
    else if (v === "skip") state = "skipped";
    else if (v === "wait") state = "waiting";
    else if (!currentSet && live) {
      state = "current";
      currentSet = true;
    } else state = "upcoming";
    return { id, label, hint, state };
  });
}
