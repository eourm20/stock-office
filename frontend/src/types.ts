// Mirrors backend/src/stock_office/domain/models.py (RunEvent).
export type EventType =
  | "run.created" | "run.started"
  | "agent.started" | "agent.completed" | "agent.failed"
  | "debate.message" | "tool.called" | "decision.created"
  | "run.completed" | "run.failed";

export interface RunEvent {
  event_id: string;
  run_id: string;
  seq: number;
  type: EventType;
  agent_id: string | null;
  occurred_at: string;
  payload: Record<string, unknown> & { demo?: boolean };
}

export type AgentStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED" | "BLOCKED";
export type RunPhase = "IDLE" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
