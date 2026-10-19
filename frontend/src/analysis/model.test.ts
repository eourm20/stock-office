import { describe, expect, it } from "vitest";
import type { EventType, RunEvent } from "../types";
import { debateTranscript, FLOW_EDGES, FLOW_NODES, formatDuration, summarizeAgents, tokenTotals }
  from "./model";

let seq = 0;
function ev(type: EventType, agent: string | null, payload: Record<string, unknown> = {}): RunEvent {
  seq += 1;
  return { event_id: `r-${seq}`, run_id: "r", seq, type, agent_id: agent,
           occurred_at: new Date(Date.UTC(2026, 9, 19, 0, 0, seq)).toISOString(), payload };
}

function run(): RunEvent[] {
  seq = 0;
  return [
    ev("run.created", null), ev("run.started", null),
    ev("agent.started", "market_analyst", { turn: 1 }),
    ev("tool.called", "market_analyst", { round: 1, tools: ["get_stock_data"] }),
    ev("tool.called", "market_analyst", { round: 2, tools: ["get_indicators"] }),
    ev("agent.completed", "market_analyst", { summary: "trend up", duration_ms: 4000 }),
    ev("agent.started", "bull_researcher", { turn: 1 }),
    ev("debate.message", "bull_researcher", { debate: "investment", stance: "bull", turn: 1,
                                              text: "Bull Analyst: up" }),
    ev("agent.completed", "bull_researcher", { summary: "up", duration_ms: 2000 }),
    ev("agent.started", "bull_researcher", { turn: 2 }),
    ev("agent.completed", "bull_researcher", { summary: "still up", duration_ms: 1500 }),
    ev("agent.started", "trader", { turn: 1 }),
    ev("agent.failed", "trader", { error: "timeout" }),
  ];
}

describe("analysis model", () => {
  it("summarizes each agent from the log only", () => {
    const s = summarizeAgents(run(), true);
    expect(s.market_analyst).toMatchObject({ status: "done", turns: 1, durationMs: 4000,
                                             summary: "trend up" });
    expect(s.market_analyst!.lookups.map((l) => l.tools)).toEqual([["get_stock_data"], ["get_indicators"]]);
    expect(s.bull_researcher).toMatchObject({ status: "done", turns: 2, durationMs: 3500,
                                              summary: "still up" });
    expect(s.trader).toMatchObject({ status: "failed", error: "timeout" });
    // Never started in a finished run → skipped, not pending or invented.
    expect(s.sentiment_analyst!.status).toBe("skipped");
  });

  it("keeps not-yet-started agents pending while the run is in progress", () => {
    const events = run().slice(0, 7);                 // bull researcher just started
    const s = summarizeAgents(events, false);
    expect(s.bull_researcher!.status).toBe("running");
    expect(s.portfolio_manager!.status).toBe("pending");
  });

  it("never leaves an agent running after the run ended", () => {
    const events = run().slice(0, 7);
    expect(summarizeAgents(events, true).bull_researcher!.status).toBe("failed");
  });

  it("is independent of arrival order (sorted by seq)", () => {
    const events = run();
    expect(summarizeAgents([...events].reverse(), true)).toEqual(summarizeAgents(events, true));
  });

  it("extracts the debate transcript in order", () => {
    expect(debateTranscript(run())).toEqual([{ seq: 8, agentId: "bull_researcher",
      debate: "investment", stance: "bull", turn: 1, text: "Bull Analyst: up",
      at: "2026-10-19T00:00:08.000Z" }]);
  });

  it("has a consistent graph: every edge joins two laid-out nodes, no shared cells", () => {
    const ids = new Set(FLOW_NODES.map((n) => n.id));
    for (const e of FLOW_EDGES) {
      expect(ids.has(e.source), e.source).toBe(true);
      expect(ids.has(e.target), e.target).toBe(true);
    }
    const cells = FLOW_NODES.map((n) => `${n.col},${n.row}`);
    expect(new Set(cells).size).toBe(cells.length);
  });

  it("formats durations and token totals", () => {
    expect(formatDuration(0)).toBe("—");
    expect(formatDuration(42_000)).toBe("42초");
    expect(formatDuration(186_253)).toBe("3분 6초");
    expect(tokenTotals({ a: { total_tokens: 10 }, b: {} })).toEqual(
      [{ model: "a", tokens: 10 }, { model: "b", tokens: 0 }]);
    expect(tokenTotals(null)).toEqual([]);
  });
});

describe("plain coverage gaps", () => {
  it("turns raw engine messages into one Korean line each", async () => {
    const { plainGap } = await import("./model");
    expect(plainGap("tradingagents: Vendor 'yfinance' unavailable for get_news: Yahoo Finance has no news articles tagged 005930.KS"))
      .toContain("뉴스가 없어");
    expect(plainGap("tradingagents: Polymarket search failed for 'Fed rate cut': 451 Client Error"))
      .toContain("예측시장");
    expect(plainGap("something else")).toBe("일부 데이터를 가져오지 못했어요");
  });
});
