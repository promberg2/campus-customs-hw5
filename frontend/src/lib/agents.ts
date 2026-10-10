import {
  Building2,
  Calculator,
  Crown,
  Database,
  MessagesSquare,
  Package,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

export type NodeId = "boss" | "inventory" | "accounting" | "facilities" | "customer_service" | "human" | "mcp";

export interface AgentMeta {
  id: NodeId;
  name: string;
  role: string;
  color: string;
  icon: LucideIcon;
}

export const AGENTS: Record<NodeId, AgentMeta> = {
  boss: { id: "boss", name: "Boss", role: "Plans, delegates, makes the final call", color: "#6ea8ff", icon: Crown },
  inventory: { id: "inventory", name: "Inventory", role: "Stock, vendors, fulfilment", color: "#34d399", icon: Package },
  accounting: { id: "accounting", name: "Accounting", role: "Cash, invoices, payments", color: "#a78bfa", icon: Calculator },
  facilities: { id: "facilities", name: "Facilities", role: "Lease and rent", color: "#22d3ee", icon: Building2 },
  customer_service: { id: "customer_service", name: "Customer Service", role: "Customer drafts", color: "#f472b6", icon: MessagesSquare },
  human: { id: "human", name: "You", role: "Human approver", color: "#fbbf24", icon: UserCheck },
  mcp: { id: "mcp", name: "Shop systems", role: "MCP server · shop database", color: "#94a3b8", icon: Database },
};

export const TEAM: NodeId[] = ["boss", "inventory", "accounting", "facilities", "customer_service"];

export function agentMeta(id: string | undefined | null): AgentMeta {
  return (id && (AGENTS as Record<string, AgentMeta>)[id]) || { ...AGENTS.mcp, id: "mcp", name: id ?? "System" };
}

export const RESERVED_NAMES = new Set([
  "", "ai", "agent", "assistant", "bot", "system", "auto", "automatic", "pending", "none", "n/a",
  "boss", "inventory", "accounting", "facilities", "customer_service", "customer service",
]);
