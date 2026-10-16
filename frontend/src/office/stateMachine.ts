import type { RunEvent } from "../types";
import { adaptEvent, describeEvent, type OfficeCommand } from "./eventAdapter";
import { bubbleText, shortSpeech } from "./explain";

export { bubbleText };

export type CharacterStatus = "idle" | "working" | "talking" | "done" | "failed";
export type Activity = "work" | "meet";

export interface CharacterState {
  agentId: string;
  role: string;
  status: CharacterStatus;
  /** Where the character should be. A pure function of status, never of animation time. */
  activity: Activity | null;
  turn: number;
  bubble: { text: string; stance: string; seq: number } | null;
  summary: string;
  error: string;
  lastSeq: number;
}

export interface OfficeState {
  lastSeq: number;
  outOfOrder: number;
  phase: "IDLE" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED";
  demo: boolean;
  /** Agents with a character in the office. */
  characters: Record<string, CharacterState>;
  /** Agents with events but no character yet (Sprint 2A shows them in the feed only). */
  offstage: Record<string, { role: string; status: CharacterStatus }>;
  feed: { seq: number; time: string; agentId: string | null; text: string }[];
  decision: { action: string; rating: string | null; flags: string[]; execution: string } | null;
}

/** Agents that meet in a room to talk instead of working at their desk. */
const MEETING_AGENTS = new Set(["bull_researcher", "bear_researcher",
  "risk_aggressive", "risk_conservative", "risk_neutral"]);
const BUBBLE_MAX = 160;

export function initialOfficeState(roster: { agentId: string; role: string }[]): OfficeState {
  const characters: Record<string, CharacterState> = {};
  for (const { agentId, role } of roster) {
    characters[agentId] = {
      agentId, role, status: "idle", activity: null, turn: 0, bubble: null, summary: "",
      error: "", lastSeq: 0,
    };
  }
  return { lastSeq: 0, outOfOrder: 0, phase: "IDLE", demo: false, characters, offstage: {},
           feed: [], decision: null };
}

function applyCommand(state: OfficeState, cmd: OfficeCommand, seq: number): OfficeState {
  if (cmd.type === "run") return { ...state, phase: cmd.phase };
  if (cmd.type === "decide") {
    const { type: _t, ...decision } = cmd;
    return { ...state, decision };
  }
  const prev = state.characters[cmd.agentId];
  if (!prev) {
    const status: CharacterStatus = cmd.type === "start" ? "working"
      : cmd.type === "complete" ? "done" : cmd.type === "fail" ? "failed" : "talking";
    const role = "role" in cmd ? cmd.role : (state.offstage[cmd.agentId]?.role ?? cmd.agentId);
    return { ...state, offstage: { ...state.offstage, [cmd.agentId]: { role, status } } };
  }
  let next: CharacterState;
  switch (cmd.type) {
    case "start":
      next = { ...prev, status: "working", turn: cmd.turn, error: "",
               activity: MEETING_AGENTS.has(cmd.agentId) ? "meet" : "work" };
      break;
    case "say":
      next = { ...prev, status: "talking", activity: "meet",
               bubble: { text: truncate(shortSpeech(bubbleText(cmd.text)), BUBBLE_MAX), stance: cmd.stance, seq },
               summary: cmd.text };
      break;
    case "complete":
      next = { ...prev, status: "done", activity: null, bubble: null,
               summary: cmd.summary || prev.summary };
      break;
    case "fail":
      // A failed agent stays where it is (no walking away from the problem).
      next = { ...prev, status: "failed", bubble: null, error: cmd.error };
      break;
  }
  next.lastSeq = seq;
  return { ...state, characters: { ...state.characters, [cmd.agentId]: next } };
}

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}


/**
 * Character State Machine. Deterministic: the state depends only on the ordered events, so a
 * replay of the same log always produces the same office, whatever the playback speed.
 */
export function reduceEvent(state: OfficeState, ev: RunEvent): OfficeState {
  if (ev.seq <= state.lastSeq) return state;                       // duplicate after reconnect
  if (ev.seq !== state.lastSeq + 1) return { ...state, outOfOrder: state.outOfOrder + 1 };
  let next = state;
  for (const cmd of adaptEvent(ev)) next = applyCommand(next, cmd, ev.seq);
  return {
    ...next,
    lastSeq: ev.seq,
    demo: next.demo || ev.payload.demo === true,
    feed: [...next.feed, { seq: ev.seq, time: ev.occurred_at, agentId: ev.agent_id,
                           text: describeEvent(ev) }],
  };
}

export function foldEvents(state: OfficeState, events: RunEvent[]): OfficeState {
  return events.reduce(reduceEvent, state);
}
