/**
 * Analysis screen model: pure functions over the stored event log, so the graph and panels show
 * exactly what the events say (unit-tested, no I/O).
 */
import type { RunEvent } from "../types";

export type NodeStatus = "pending" | "running" | "done" | "failed" | "skipped";

export interface AgentSummary {
  agentId: string;
  status: NodeStatus;
  turns: number;
  startedAt: string | null;
  completedAt: string | null;
  /** Sum of the agent's own turn durations (ms), from agent.completed payloads. */
  durationMs: number;
  lookups: { round: number; tools: string[]; at: string }[];
  /** Latest event summary (capped at 600 chars by the backend). */
  summary: string;
  error: string;
}

export interface DebateLine {
  seq: number;
  agentId: string;
  debate: string;
  stance: string;
  turn: number;
  text: string;
  at: string;
}

/** Graph layout: one column per stage, in the committee's real order. */
export const FLOW_NODES: { id: string; col: number; row: number }[] = [
  { id: "data_collector", col: 0, row: 2 },
  { id: "market_analyst", col: 1, row: 0 },
  { id: "news_analyst", col: 1, row: 1 },
  { id: "fundamentals_analyst", col: 1, row: 2 },
  { id: "sentiment_analyst", col: 1, row: 3 },
  { id: "memory_log", col: 1, row: 4 },
  { id: "bull_researcher", col: 2, row: 1 },
  { id: "bear_researcher", col: 2, row: 3 },
  { id: "research_manager", col: 3, row: 2 },
  { id: "trader", col: 4, row: 2 },
  { id: "risk_aggressive", col: 5, row: 1 },
  { id: "risk_conservative", col: 5, row: 2 },
  { id: "risk_neutral", col: 5, row: 3 },
  { id: "portfolio_manager", col: 6, row: 2 },
  { id: "decision", col: 7, row: 2 },
];

const ANALYSTS = ["market_analyst", "news_analyst", "fundamentals_analyst", "sentiment_analyst"];
const RISK = ["risk_aggressive", "risk_conservative", "risk_neutral"];

/** Hand-offs between stages. `debate` edges are the back-and-forth of a debate. */
export const FLOW_EDGES: { source: string; target: string; kind: "flow" | "debate" | "context" }[] = [
  ...ANALYSTS.map((a) => ({ source: "data_collector", target: a, kind: "flow" as const })),
  ...ANALYSTS.flatMap((a) => ["bull_researcher", "bear_researcher"]
    .map((r) => ({ source: a, target: r, kind: "flow" as const }))),
  { source: "bull_researcher", target: "bear_researcher", kind: "debate" },
  { source: "bull_researcher", target: "research_manager", kind: "flow" },
  { source: "bear_researcher", target: "research_manager", kind: "flow" },
  { source: "research_manager", target: "trader", kind: "flow" },
  ...RISK.map((r) => ({ source: "trader", target: r, kind: "flow" as const })),
  { source: "risk_aggressive", target: "risk_conservative", kind: "debate" },
  { source: "risk_conservative", target: "risk_neutral", kind: "debate" },
  ...RISK.map((r) => ({ source: r, target: "portfolio_manager", kind: "flow" as const })),
  { source: "memory_log", target: "portfolio_manager", kind: "context" },
  { source: "portfolio_manager", target: "decision", kind: "flow" },
];

const str = (v: unknown): string => (typeof v === "string" ? v : "");
const num = (v: unknown, d = 0): number => (typeof v === "number" ? v : d);

/**
 * Per-agent status from the ordered log. An agent that never started in a finished run is
 * `skipped` (e.g. the sentiment analyst is not configured); in a running run it is `pending`.
 */
export function summarizeAgents(events: RunEvent[], runFinished: boolean):
    Record<string, AgentSummary> {
  const out: Record<string, AgentSummary> = {};
  const get = (id: string): AgentSummary => (out[id] ??= {
    agentId: id, status: "pending", turns: 0, startedAt: null, completedAt: null, durationMs: 0,
    lookups: [], summary: "", error: "",
  });
  for (const ev of [...events].sort((a, b) => a.seq - b.seq)) {
    if (!ev.agent_id) continue;
    const a = get(ev.agent_id);
    const p = ev.payload;
    switch (ev.type) {
      case "agent.started":
        a.status = "running";
        a.turns = Math.max(a.turns, num(p.turn, a.turns + 1));
        a.startedAt ??= ev.occurred_at;
        break;
      case "tool.called":
        a.lookups.push({ round: num(p.round, a.lookups.length + 1),
                         tools: Array.isArray(p.tools) ? p.tools.map(String) : [],
                         at: ev.occurred_at });
        break;
      case "agent.completed":
        a.status = "done";
        a.completedAt = ev.occurred_at;
        a.durationMs += num(p.duration_ms);
        a.summary = str(p.summary) || a.summary;
        break;
      case "agent.failed":
        a.status = "failed";
        a.completedAt = ev.occurred_at;
        a.error = str(p.error);
        break;
    }
  }
  for (const { id } of FLOW_NODES) {
    if (id === "decision") continue;
    const a = get(id);
    if (a.status === "pending" && runFinished) a.status = "skipped";
    // A run that ended while an agent was still open: never show it as running.
    if (a.status === "running" && runFinished) a.status = "failed";
  }
  return out;
}

export function debateTranscript(events: RunEvent[]): DebateLine[] {
  return events.filter((e) => e.type === "debate.message" && e.agent_id)
    .sort((a, b) => a.seq - b.seq)
    .map((e) => ({ seq: e.seq, agentId: e.agent_id!, debate: str(e.payload.debate),
                   stance: str(e.payload.stance), turn: num(e.payload.turn, 1),
                   text: str(e.payload.text), at: e.occurred_at }));
}

export function formatDuration(ms: number): string {
  if (ms <= 0) return "—";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}초` : `${Math.floor(s / 60)}분 ${s % 60}초`;
}

/** Total tokens per model, for the run facts panel. */
export function tokenTotals(usage: Record<string, { total_tokens?: number }> | null):
    { model: string; tokens: number }[] {
  return Object.entries(usage ?? {}).map(([model, u]) => ({ model, tokens: u.total_tokens ?? 0 }));
}
