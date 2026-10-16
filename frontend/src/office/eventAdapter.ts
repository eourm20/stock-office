import type { RunEvent } from "../types";

/** What an event means for the office, independent of any rendering. */
export type OfficeCommand =
  | { type: "run"; phase: "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED"; status?: string }
  | { type: "start"; agentId: string; role: string; turn: number }
  | { type: "complete"; agentId: string; role: string; summary: string }
  | { type: "fail"; agentId: string; role: string; error: string }
  | { type: "say"; agentId: string; text: string; stance: string; debate: string }
  | { type: "decide"; action: string; rating: string | null; flags: string[]; execution: string };

const str = (v: unknown, fallback = ""): string => (typeof v === "string" ? v : fallback);

/** Event Adapter: one normalized run event → office commands. Pure; no I/O, no timing. */
export function adaptEvent(ev: RunEvent): OfficeCommand[] {
  const p = ev.payload;
  const agentId = ev.agent_id ?? "";
  const role = str(p.role, agentId);
  switch (ev.type) {
    case "run.created":
      return [{ type: "run", phase: "QUEUED" }];
    case "run.started":
      return [{ type: "run", phase: "RUNNING" }];
    case "run.completed":
      return [{ type: "run", phase: "COMPLETED", status: str(p.status) }];
    case "run.failed":
      return [{ type: "run", phase: "FAILED", status: str(p.status) }];
    case "agent.started":
      return [{ type: "start", agentId, role, turn: typeof p.turn === "number" ? p.turn : 1 }];
    case "agent.completed":
      return [{ type: "complete", agentId, role, summary: str(p.summary) }];
    case "agent.failed":
      return [{ type: "fail", agentId, role, error: str(p.error, "failed") }];
    case "debate.message":
      return [{ type: "say", agentId, text: str(p.text), stance: str(p.stance),
                debate: str(p.debate) }];
    case "decision.created":
      return [{
        type: "decide",
        action: str(p.action, "REVIEW"),
        rating: typeof p.engine_rating === "string" ? p.engine_rating : null,
        flags: Array.isArray(p.risk_flags) ? p.risk_flags.map(String) : [],
        execution: str(p.execution, "PROPOSED_ONLY"),
      }];
    default:
      return [];
  }
}

/** One line for the Activity Feed (the canvas's text equivalent). */
export function describeEvent(ev: RunEvent): string {
  const who = ev.agent_id ? ` ${String(ev.payload.role ?? ev.agent_id)}` : "";
  switch (ev.type) {
    case "agent.started": return `▶${who} 업무 시작`;
    case "agent.completed": return `✓${who} 완료`;
    case "agent.failed": return `✗${who} 실패: ${String(ev.payload.error ?? "")}`;
    case "debate.message": return `💬${who}: ${String(ev.payload.text ?? "").slice(0, 120)}`;
    case "decision.created":
      return `★ 최종 결정 ${String(ev.payload.action)} (${String(ev.payload.engine_rating ?? "-")}) · 제안만, 주문 없음`;
    case "run.created": return "실행 등록";
    case "run.started": return "위원회 소집";
    case "run.completed": return `실행 종료 (${String(ev.payload.status ?? "")})`;
    case "run.failed": return `실행 실패 (${String(ev.payload.error_code ?? ev.payload.status ?? "")})`;
    default: return ev.type;
  }
}
