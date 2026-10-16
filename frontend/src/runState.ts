import type { AgentStatus, RunEvent, RunPhase } from "./types";

export interface AgentView {
  agentId: string;
  role: string;
  status: AgentStatus;
  turns: number;
  summary?: string;
}

export interface RunView {
  lastSeq: number;
  phase: RunPhase;
  demo: boolean;
  agents: Record<string, AgentView>;
  feed: RunEvent[];
  outOfOrder: number;
}

export const initialRunView: RunView = {
  lastSeq: 0, phase: "IDLE", demo: false, agents: {}, feed: [], outOfOrder: 0,
};

/** Agent state is derived ONLY from stored events; nothing is animated without one. */
export function applyEvent(view: RunView, ev: RunEvent): RunView {
  if (ev.seq <= view.lastSeq) return view; // duplicate after reconnect: ignore
  if (ev.seq !== view.lastSeq + 1) return { ...view, outOfOrder: view.outOfOrder + 1 };

  const agents = { ...view.agents };
  const id = ev.agent_id;
  const role = typeof ev.payload.role === "string" ? ev.payload.role : (id ?? "");
  const prev = id ? agents[id] : undefined;
  const summary = typeof ev.payload.summary === "string" ? ev.payload.summary : prev?.summary;
  let phase = view.phase;

  switch (ev.type) {
    case "run.created": phase = "QUEUED"; break;
    case "run.started": phase = "RUNNING"; break;
    case "run.completed": phase = "COMPLETED"; break;
    case "run.failed": phase = "FAILED"; break;
    case "agent.started":
      if (id) agents[id] = { agentId: id, role, status: "RUNNING", turns: (prev?.turns ?? 0) + 1, summary };
      break;
    case "agent.completed":
      if (id) agents[id] = { agentId: id, role, status: "COMPLETED", turns: prev?.turns ?? 1, summary };
      break;
    case "agent.failed":
      if (id) agents[id] = { agentId: id, role, status: "FAILED", turns: prev?.turns ?? 1, summary };
      break;
    default:
      break;
  }
  return {
    lastSeq: ev.seq,
    phase,
    agents,
    outOfOrder: view.outOfOrder,
    demo: view.demo || ev.payload.demo === true,
    feed: [...view.feed, ev],
  };
}
