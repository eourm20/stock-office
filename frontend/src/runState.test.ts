import { describe, expect, it } from "vitest";
import { applyEvent, initialRunView } from "./runState";
import type { EventType, RunEvent } from "./types";

const ev = (seq: number, type: EventType, agent_id: string | null = null,
            payload: Record<string, unknown> = {}): RunEvent => ({
  event_id: `r-${seq}`, run_id: "r", seq, type, agent_id,
  occurred_at: "2026-10-16T00:00:00Z", payload: { demo: true, ...payload },
});

describe("applyEvent", () => {
  it("derives agent status only from events", () => {
    let v = initialRunView;
    const events = [
      ev(1, "run.created"), ev(2, "run.started"),
      ev(3, "agent.started", "market_analyst", { role: "Market Analyst" }),
      ev(4, "agent.completed", "market_analyst", { role: "Market Analyst", summary: "ok" }),
      ev(5, "run.completed"),
    ];
    for (const e of events) v = applyEvent(v, e);
    expect(v.phase).toBe("COMPLETED");
    expect(v.agents.market_analyst).toMatchObject({ status: "COMPLETED", summary: "ok", turns: 1 });
    expect(v.demo).toBe(true);
  });

  it("ignores duplicates after reconnect and flags gaps", () => {
    let v = applyEvent(initialRunView, ev(1, "run.created"));
    v = applyEvent(v, ev(1, "run.created"));
    expect(v.feed).toHaveLength(1);
    v = applyEvent(v, ev(3, "run.started"));
    expect(v.outOfOrder).toBe(1);
    expect(v.lastSeq).toBe(1);
  });

  it("counts debate turns and failures", () => {
    let v = initialRunView;
    const events = [
      ev(1, "agent.started", "bull_researcher"), ev(2, "agent.completed", "bull_researcher"),
      ev(3, "agent.started", "bull_researcher"), ev(4, "agent.failed", "bull_researcher"),
    ];
    for (const e of events) v = applyEvent(v, e);
    expect(v.agents.bull_researcher).toMatchObject({ status: "FAILED", turns: 2 });
  });
});
