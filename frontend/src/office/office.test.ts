import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EventType, RunEvent } from "../types";
import { adaptEvent } from "./eventAdapter";
import { decisionLines, narrate, shortSpeech } from "./explain";
import { facing, isoToWorld, parseTiledMap, planPath, targetSpot, zoneOf, type TiledMap }
  from "./layout";
import { characterFor, frameRange, resolveAnimation, type Registry, type SpriteMetadata }
  from "./registry";
import { DEBATE_DWELL_MS, LIVE_CATCH_UP_BACKLOG, playbackDelayMs, ReplayPlayer } from "./replay";
import { bubbleText, foldEvents, initialOfficeState, reduceEvent } from "./stateMachine";

const PUBLIC = join(__dirname, "..", "..", "public");
const map = JSON.parse(readFileSync(join(PUBLIC, "office", "office.tmj"), "utf8")) as TiledMap;
const registry = JSON.parse(readFileSync(join(PUBLIC, "characters", "registry.json"), "utf8")) as Registry;
const layout = parseTiledMap(map);

const ROSTER = [
  { agentId: "market_analyst", role: "Market Analyst" },
  { agentId: "news_analyst", role: "News Analyst" },
  { agentId: "bull_researcher", role: "Bull Researcher" },
  { agentId: "bear_researcher", role: "Bear Researcher" },
];

let seq = 0;
const t0 = Date.parse("2026-10-16T07:18:25Z");
function ev(type: EventType, agent: string | null = null, payload: Record<string, unknown> = {},
            atSec = seq): RunEvent {
  seq += 1;
  return { event_id: `r-${seq}`, run_id: "r", seq, type, agent_id: agent,
           occurred_at: new Date(t0 + atSec * 1000).toISOString(), payload };
}

/** Same shape and order as a real TradingAgents run (see sprint-0-report §10). */
function realisticRun(): RunEvent[] {
  seq = 0;
  return [
    ev("run.created"), ev("run.started"),
    ev("agent.started", "data_collector", { role: "Data Collection" }),
    ev("agent.completed", "data_collector", { role: "Data Collection" }),
    ev("agent.started", "market_analyst", { role: "Market Analyst", turn: 1 }, 13),
    ev("agent.started", "news_analyst", { role: "News Analyst", turn: 1 }, 13),
    ev("agent.started", "fundamentals_analyst", { role: "Fundamentals Analyst" }, 13),
    ev("agent.completed", "market_analyst", { role: "Market Analyst", summary: "trend up" }, 46),
    ev("agent.completed", "news_analyst", { role: "News Analyst", summary: "news ok" }, 47),
    ev("agent.completed", "fundamentals_analyst", { role: "Fundamentals Analyst" }, 56),
    ev("agent.started", "bull_researcher", { role: "Bull Researcher", turn: 1 }, 56),
    ev("debate.message", "bull_researcher", { debate: "investment", stance: "bull",
                                              text: "Bull Analyst: upside" }, 77),
    ev("agent.completed", "bull_researcher", { role: "Bull Researcher" }, 77),
    ev("agent.started", "bear_researcher", { role: "Bear Researcher", turn: 1 }, 77),
    ev("debate.message", "bear_researcher", { debate: "investment", stance: "bear",
                                              text: "x".repeat(400) }, 95),
    ev("agent.completed", "bear_researcher", { role: "Bear Researcher" }, 95),
    ev("decision.created", "portfolio_manager", { action: "BUY", engine_rating: "Overweight",
                                                  risk_flags: ["COVERAGE_GAP"],
                                                  execution: "PROPOSED_ONLY" }, 160),
    ev("run.completed", null, { status: "COMPLETED" }, 161),
  ];
}

describe("event adapter", () => {
  it("maps every event type it knows and ignores the rest", () => {
    const [created, , , , start] = realisticRun();
    expect(adaptEvent(created!)).toEqual([{ type: "run", phase: "QUEUED" }]);
    expect(adaptEvent(start!)).toEqual([{ type: "start", agentId: "market_analyst",
                                          role: "Market Analyst", turn: 1 }]);
    expect(adaptEvent({ ...start!, type: "tool.called" as EventType })).toEqual([]);
  });
});

describe("character state machine", () => {
  it("follows the run: work at desk, meet to debate, done, decision", () => {
    const events = realisticRun();
    const s = foldEvents(initialOfficeState(ROSTER), events);
    expect(s.phase).toBe("COMPLETED");
    expect(s.characters.market_analyst).toMatchObject({ status: "done", activity: null,
                                                        summary: "trend up" });
    expect(s.decision).toMatchObject({ action: "BUY", execution: "PROPOSED_ONLY" });
    // Agents without a character are tracked offstage, never invented in the office.
    expect(Object.keys(s.offstage).sort()).toEqual(["data_collector", "fundamentals_analyst"]);

    const mid = foldEvents(initialOfficeState(ROSTER), events.slice(0, 12));
    expect(mid.characters.bull_researcher).toMatchObject({ status: "talking", activity: "meet" });
    expect(mid.characters.bull_researcher!.bubble!.text).toBe("upside");
    expect(mid.characters.bull_researcher!.summary).toBe("Bull Analyst: upside");  // full text kept
    const bear = foldEvents(initialOfficeState(ROSTER), events.slice(0, 15));
    expect(bear.characters.bear_researcher!.bubble!.text.length).toBeLessThanOrEqual(160);
  });

  it("is deterministic: whole, chunked, duplicated and replayed logs give identical state", () => {
    const events = realisticRun();
    const whole = foldEvents(initialOfficeState(ROSTER), events);
    let chunked = initialOfficeState(ROSTER);
    for (let i = 0; i < events.length; i += 3) chunked = foldEvents(chunked, events.slice(i, i + 3));
    const withDupes = foldEvents(initialOfficeState(ROSTER), [...events.slice(0, 9),
      ...events.slice(4, 9), ...events.slice(9)]);
    expect(chunked).toEqual(whole);
    expect(withDupes).toEqual(whole);
    expect(foldEvents(initialOfficeState(ROSTER), events)).toEqual(whole);
  });

  it("flags gaps instead of guessing, and keeps failed agents in place", () => {
    const events = realisticRun();
    const gap = reduceEvent(foldEvents(initialOfficeState(ROSTER), events.slice(0, 5)), events[7]!);
    expect(gap.outOfOrder).toBe(1);
    expect(gap.lastSeq).toBe(5);
    seq = 5;
    const failed = foldEvents(foldEvents(initialOfficeState(ROSTER), events.slice(0, 5)),
                              [ev("agent.failed", "market_analyst", { error: "timeout" })]);
    expect(failed.characters.market_analyst).toMatchObject({ status: "failed", activity: "work" });
  });

  it("strips speaker prefixes and markdown from bubbles only", () => {
    expect(bubbleText("Bear Analyst: ## Bear case on 005930.KS: **stale** evidence"))
      .toBe("Bear case on 005930.KS: stale evidence");
  });

  it("explains the current stage and the decision in plain Korean", () => {
    const events = realisticRun();
    const at = (n: number) => narrate(foldEvents(initialOfficeState(ROSTER), events.slice(0, n)));
    expect(at(0)).toContain("새 분석 시작");
    expect(at(6)).toContain("분석가들이");
    expect(at(12)).toContain("토론");
    const done = foldEvents(initialOfficeState(ROSTER), events);
    expect(narrate(done)).toContain("'매수'");
    expect(narrate(done)).toContain("실제 주문은 하지 않았어요");
    expect(decisionLines(done.decision!)).toContain("AI 등급: 비중 확대 — 조금 더 사기");
  });

  it("shortens long speech to its first sentence", () => {
    expect(shortSpeech("삼성전자는 단기 차트가 약합니다. 하지만 메모리 업황이 좋아집니다.")).toBe("삼성전자는 단기 차트가 약합니다.");
    expect(shortSpeech("NVDA has pulled back sharply. Rates are high.")).toBe("NVDA has pulled back sharply.");
    expect(shortSpeech("x".repeat(200)).length).toBe(70);
  });

  it("marks DEMO runs", () => {
    const events = realisticRun().map((e) => ({ ...e, payload: { ...e.payload, demo: true } }));
    expect(foldEvents(initialOfficeState(ROSTER), events).demo).toBe(true);
  });
});

describe("office layout (Tiled map)", () => {
  it("has spots for every 2A character and resolves them inside the map", () => {
    for (const { agentId } of ROSTER) {
      for (const status of ["idle", "working", "talking", "done"] as const) {
        const activity = status === "working" ? "work" : status === "talking" ? "meet" : null;
        const spot = targetSpot(layout, agentId, status, activity, null);
        const p = layout.spots[spot]!;
        expect(p.x).toBeGreaterThan(0);
        expect(p.x).toBeLessThan(layout.width);
        expect(p.y).toBeLessThan(layout.height);
      }
    }
    expect(targetSpot(layout, "bull_researcher", "talking", "meet", null)).toBe("meet:bull_researcher");
    expect(targetSpot(layout, "market_analyst", "working", "work", null)).toBe("desk:market_analyst");
    expect(targetSpot(layout, "market_analyst", "failed", "work", "desk:market_analyst"))
      .toBe("desk:market_analyst");
  });

  it("routes between rooms through doors and the corridor", () => {
    expect(zoneOf(layout, layout.spots["desk:market_analyst"]!)?.name).toBe("analyst_office");
    const path = planPath(layout, "desk:market_analyst", "inbox:research_room");
    expect(path).toEqual([layout.spots["door:analyst_office"], layout.spots["corridor:center"],
                          layout.spots["door:research_room"], layout.spots["inbox:research_room"]]);
    expect(planPath(layout, "home:bull_researcher", "meet:bull_researcher"))
      .toEqual([layout.spots["meet:bull_researcher"]]);
  });

  it("projects isometrically and picks a facing", () => {
    expect(isoToWorld(layout, { x: 1, y: 0 })).toEqual({ x: 32, y: 16 });
    expect(isoToWorld(layout, { x: 0, y: 1 })).toEqual({ x: -32, y: 16 });
    expect(facing({ x: 0, y: 0 }, { x: 0, y: 10 })).toBe("down");
    expect(facing({ x: 0, y: 0 }, { x: -50, y: 5 })).toBe("left");
  });
});

describe("character registry", () => {
  it("separates appearance from agents and falls back to the default character", () => {
    expect(characterFor(registry, "market_analyst").id).toBe("ph-market");
    expect(characterFor(registry, "trader").id).toBe(registry.default_character);
    for (const c of registry.characters) {
      expect(c.license.license).toBe("CC0-1.0");
      expect(c.license.placeholder).toBe(true);
    }
  });

  it("falls back for partial sprite sheets and static PNGs", () => {
    const partial: SpriteMetadata = { frame_width: 64, frame_height: 64,
      animations: { idle: { down: { row: 2, frames: 2, fps: 2 } } } };
    expect(resolveAnimation(partial, "walk", "left")).toEqual({ row: 2, frames: 2, fps: 2 });
    expect(resolveAnimation(null, "talk", "up")).toEqual({ row: 0, frames: 1, fps: 1 });
    expect(frameRange(partial, { row: 2, frames: 2, fps: 2 }, 256)).toEqual({ start: 8, end: 9 });
    expect(frameRange(null, { row: 0, frames: 1, fps: 1 }, 40)).toEqual({ start: 0, end: 0 });
  });
});

describe("replay timing", () => {
  afterEach(() => vi.useRealTimers());

  it("compresses and clamps real gaps without reordering", () => {
    const [a, b] = realisticRun();
    expect(playbackDelayMs(null, a!, 1)).toBe(0);
    expect(playbackDelayMs(a!, b!, "instant")).toBe(0);
    const late = { ...b!, occurred_at: new Date(t0 + 600_000).toISOString() };
    expect(playbackDelayMs(a!, late, 1)).toBe(2500);
    expect(playbackDelayMs(a!, late, 4)).toBe(625);
  });

  it("holds a debate line long enough to read even when the speaker completes instantly", () => {
    const events = realisticRun();
    const say = events.find((e) => e.type === "debate.message")!;
    const done = events[events.indexOf(say) + 1]!;
    expect(done.occurred_at).toBe(say.occurred_at);           // same instant in real logs
    expect(playbackDelayMs(say, done, 1)).toBe(DEBATE_DWELL_MS);
    expect(playbackDelayMs(say, done, 4)).toBe(DEBATE_DWELL_MS / 2);
    expect(playbackDelayMs(say, done, "instant")).toBe(0);
  });

  it("live mode keeps order and catches up on a backlog without animation", () => {
    vi.useFakeTimers();
    const events = realisticRun();
    const seen: [number, boolean][] = [];
    const p = new ReplayPlayer([], (e, animate) => seen.push([e.seq, animate]), 1, () => {}, true);
    p.push(events[0]!);
    p.push(events[1]!);
    vi.runAllTimers();
    expect(p.done).toBe(false);                                // stream still open
    for (const e of events.slice(2, 2 + LIVE_CATCH_UP_BACKLOG + 1)) p.push(e);
    expect(seen.map(([s]) => s)).toEqual(Array.from({ length: seen.length }, (_, i) => i + 1));
    expect(seen.slice(2).every(([, animate]) => !animate)).toBe(true);
    for (const e of events.slice(2 + LIVE_CATCH_UP_BACKLOG + 1)) p.push(e);
    p.close();
    vi.runAllTimers();
    expect(p.done).toBe(true);
    expect(seen.map(([s]) => s)).toEqual(events.map((e) => e.seq));
  });

  it("ends in the same state at any speed", () => {
    vi.useFakeTimers();
    const events = realisticRun();
    const run = (speed: 1 | 4 | "instant") => {
      let s = initialOfficeState(ROSTER);
      const player = new ReplayPlayer(events, (e) => { s = reduceEvent(s, e); }, speed);
      player.play();
      vi.runAllTimers();
      expect(player.done).toBe(true);
      return s;
    };
    expect(run(1)).toEqual(run("instant"));
    expect(run(4)).toEqual(run("instant"));
  });
});
