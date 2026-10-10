import { useEffect, useRef } from "react";
import { AGENTS, type NodeId } from "../lib/agents";
import { edgeKey, type Bubble, type GraphState, type Pulse } from "../lib/runModel";
import { truncate } from "../lib/format";

const W = 1000;
const H = 470;
const R = 34;

const POS: Record<NodeId, { x: number; y: number }> = {
  boss: { x: 430, y: 82 },
  human: { x: 880, y: 82 },
  inventory: { x: 110, y: 250 },
  facilities: { x: 320, y: 250 },
  customer_service: { x: 540, y: 250 },
  accounting: { x: 750, y: 250 },
  mcp: { x: 430, y: 410 },
};

const SPECIALISTS: NodeId[] = ["inventory", "facilities", "customer_service", "accounting"];

/** Edges leave a node below its name and caption so lines never cross the labels. */
const BELOW_LABEL = R + 46;

function pathFor(a: NodeId, b: NodeId): string {
  const p = POS[a], q = POS[b];
  if (b === "mcp" && a !== "human") {
    const top = POS.mcp.y - 26;
    const sy = p.y + BELOW_LABEL;
    return `M${p.x},${sy} C${p.x},${sy + 50} ${q.x + (p.x - q.x) * 0.25},${top - 50} ${q.x + (p.x - q.x) * 0.18},${top}`;
  }
  if (a === "human" && b === "mcp") return `M${p.x},${p.y + BELOW_LABEL} C${p.x + 60},${p.y + 240} ${q.x + 300},${q.y + 10} ${q.x + 112},${q.y}`;
  if (a === "boss" && b === "human") return `M${p.x + R},${p.y} L${q.x - R},${q.y}`;
  if (a === "boss") return `M${p.x},${p.y + BELOW_LABEL} C${p.x},${p.y + BELOW_LABEL + 40} ${q.x},${q.y - R - 40} ${q.x},${q.y - R}`;
  if (b === "human") return `M${p.x + R * 0.7},${p.y - R * 0.7} C${p.x + 50},${p.y - 90} ${q.x - 40},${q.y + 70} ${q.x - R * 0.6},${q.y + R * 0.8}`;
  // specialist <-> specialist consultations bend below the row
  const mid = (p.x + q.x) / 2;
  return `M${p.x},${p.y + BELOW_LABEL} Q${mid},${p.y + 150} ${q.x},${q.y + BELOW_LABEL}`;
}

/** The fixed edge for a pair, always drawn in the same direction. */
function canonical(a: NodeId, b: NodeId): [NodeId, NodeId] {
  const order: NodeId[] = ["boss", "inventory", "facilities", "customer_service", "accounting", "human", "mcp"];
  if (a === "human" && b !== "mcp") return [b, a];
  if (b === "human" && a !== "mcp") return [a, b];
  if (a === "mcp") return [b, a];
  if (b === "mcp") return [a, b];
  return order.indexOf(a) <= order.indexOf(b) ? [a, b] : [b, a];
}

const STATIC_EDGES: Array<[NodeId, NodeId]> = [
  ...SPECIALISTS.map((s) => ["boss", s] as [NodeId, NodeId]),
  ["boss", "mcp"],
  ...SPECIALISTS.map((s) => [s, "mcp"] as [NodeId, NodeId]),
  ["boss", "human"],
  ["accounting", "human"],
  ["human", "mcp"],
];

export function TeamGraph({
  graph,
  pulses,
  bubble,
  onPulseDone,
  focus,
}: {
  graph: GraphState;
  pulses: Pulse[];
  bubble: Bubble | null;
  onPulseDone: (id: string) => void;
  focus?: NodeId | null;
}) {
  const dynamic = Object.values(graph.edges)
    .map((e) => e.key.split("~") as [NodeId, NodeId])
    .filter(([a, b]) => !STATIC_EDGES.some(([x, y]) => edgeKey(x, y) === edgeKey(a, b)))
    .map(([a, b]) => canonical(a, b));
  const edges = [...STATIC_EDGES, ...dynamic];

  return (
    <svg className="team-graph" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Agent team graph">
      <defs>
        <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="4" result="b" />
          <feMerge>
            <feMergeNode in="b" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <radialGradient id="nodeFill" cx="50%" cy="35%" r="70%">
          <stop offset="0%" stopColor="#1e2636" />
          <stop offset="100%" stopColor="#121824" />
        </radialGradient>
        <pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="1" fill="#ffffff" opacity="0.045" />
        </pattern>
      </defs>
      <rect width={W} height={H} fill="url(#dots)" />

      {edges.map(([a, b]) => {
        const key = edgeKey(a, b);
        const st = graph.edges[key];
        const d = pathFor(a, b);
        return (
          <g key={key} className={`edge ${st ? "used" : ""} ${st?.active ? "active" : ""}`}>
            <path id={`edge-${key}`} d={d} className="edge-base" />
            {st && (
              <path
                key={`${key}-${st.lastSeq}`}
                d={d}
                pathLength={1}
                className="edge-fill"
                style={{ stroke: st.color }}
                filter={st.active ? "url(#glow)" : undefined}
              />
            )}
            {st?.active && <path d={d} className="edge-flow" style={{ stroke: st.color }} />}
          </g>
        );
      })}

      {pulses.map((p) => (
        <PulseDot key={p.id} pulse={p} onDone={onPulseDone} />
      ))}

      {(Object.keys(POS) as NodeId[]).map((id) =>
        id === "mcp" ? (
          <McpNode key={id} calls={graph.nodes.mcp.toolCalls} caption={graph.nodes.mcp.caption} />
        ) : (
          <AgentNode key={id} id={id} state={graph.nodes[id]} dim={!!focus && focus !== id} />
        ),
      )}

      {bubble && <SpeechBubble bubble={bubble} />}
    </svg>
  );
}

function AgentNode({ id, state, dim }: { id: NodeId; state: GraphState["nodes"][NodeId]; dim: boolean }) {
  const meta = AGENTS[id];
  const { x, y } = POS[id];
  const Icon = meta.icon;
  return (
    <g className={`node node-${state.status} ${dim ? "dim" : ""}`} transform={`translate(${x},${y})`} style={{ ["--c" as string]: meta.color }}>
      <circle r={R + 12} className="node-halo" />
      <circle r={R} className="node-body" fill="url(#nodeFill)" />
      <circle r={R} className="node-ring" />
      {state.status === "working" && <circle r={R + 6} className="node-spin" />}
      <Icon x={-13} y={-13} width={26} height={26} color={meta.color} strokeWidth={1.8} />
      {state.toolCalls + state.messages > 0 && id !== "human" && (
        <g transform={`translate(${R * 0.72},${-R * 0.72})`} className="node-count">
          <circle r={11} />
          <text y={4} textAnchor="middle">{state.toolCalls + state.messages}</text>
        </g>
      )}
      <text y={R + 22} textAnchor="middle" className="node-name">{meta.name}</text>
      <text y={R + 39} textAnchor="middle" className="node-caption">{truncate(state.caption, 30)}</text>
    </g>
  );
}

function McpNode({ calls, caption }: { calls: number; caption: string }) {
  const { x, y } = POS.mcp;
  const Icon = AGENTS.mcp.icon;
  return (
    <g className={`mcp-node ${calls ? "used" : ""}`} transform={`translate(${x},${y})`}>
      <rect x={-112} y={-26} width={224} height={52} rx={14} />
      <Icon x={-98} y={-11} width={22} height={22} color="#94a3b8" />
      <text x={-66} y={-3} className="node-name" textAnchor="start">Shop systems · MCP</text>
      <text x={-66} y={14} className="node-caption" textAnchor="start">
        {calls ? `${calls} tool call${calls === 1 ? "" : "s"} · ${truncate(caption, 18)}` : "23 tools · shop database"}
      </text>
    </g>
  );
}

function SpeechBubble({ bubble }: { bubble: Bubble }) {
  const p = POS[bubble.node];
  const meta = AGENTS[bubble.node];
  const w = 270;
  const left = bubble.node === "human" || bubble.node === "accounting";
  const bx = left ? p.x - w - R - 8 : p.x + R + 10;
  const by = bubble.node === "boss" || bubble.node === "human" ? p.y - 30 : p.y - 110;
  return (
    <foreignObject key={bubble.seq} x={Math.max(4, bx)} y={Math.max(4, by)} width={w} height={110} className="bubble-fo">
      <div className="bubble" style={{ ["--c" as string]: meta.color }}>
        <span className="bubble-who">{meta.name}</span>
        {bubble.text}
      </div>
    </foreignObject>
  );
}

function PulseDot({ pulse, onDone }: { pulse: Pulse; onDone: (id: string) => void }) {
  const head = useRef<SVGCircleElement>(null);
  const tail1 = useRef<SVGCircleElement>(null);
  const tail2 = useRef<SVGCircleElement>(null);

  useEffect(() => {
    const [a, b] = canonical(pulse.from, pulse.to);
    const path = document.getElementById(`edge-${edgeKey(a, b)}`) as SVGPathElement | null;
    if (!path || document.hidden) {
      onDone(pulse.id);
      return;
    }
    const reverse = a !== pulse.from;
    const len = path.getTotalLength();
    const dur = pulse.kind === "tool" ? 650 : 1100;
    const start = performance.now();
    let raf = 0;
    const place = (el: SVGCircleElement | null, t: number) => {
      if (!el) return;
      const c = Math.min(1, Math.max(0, t));
      const pt = path.getPointAtLength((reverse ? 1 - c : c) * len);
      el.setAttribute("cx", String(pt.x));
      el.setAttribute("cy", String(pt.y));
      el.style.opacity = t < 0 || t > 1 ? "0" : "1";
    };
    const frame = (now: number) => {
      const t = (now - start) / dur;
      const ease = t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      place(head.current, ease);
      place(tail1.current, ease - 0.05);
      place(tail2.current, ease - 0.1);
      if (t < 1.12) raf = requestAnimationFrame(frame);
      else onDone(pulse.id);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [pulse, onDone]);

  const r = pulse.kind === "tool" ? 4 : 6;
  return (
    <g className="pulse" style={{ color: pulse.color }}>
      <circle ref={tail2} r={r * 0.55} fill="currentColor" opacity={0} className="pulse-tail" />
      <circle ref={tail1} r={r * 0.75} fill="currentColor" opacity={0} className="pulse-tail" />
      <circle ref={head} r={r} fill="currentColor" opacity={0} filter="url(#glow)" />
    </g>
  );
}
