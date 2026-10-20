/**
 * Department status board: what each department is doing right now and how far it is, derived only
 * from the office state (i.e. from stored events). Pure, so it is unit-tested.
 */
import type { OfficeState } from "./stateMachine";

export interface Department {
  zone: string;            // office room, for the camera tabs
  name: string;
  agents: string[];
}

/** Departments by function, in the order the committee works. */
export const DEPARTMENTS: Department[] = [
  { zone: "analyst_office", name: "분석실",
    agents: ["data_collector", "market_analyst", "news_analyst", "fundamentals_analyst", "sentiment_analyst", "memory_log"] },
  { zone: "research_room", name: "리서치", agents: ["bull_researcher", "bear_researcher", "research_manager"] },
  { zone: "trading_desk", name: "트레이딩", agents: ["trader"] },
  { zone: "risk_executive", name: "리스크·임원실",
    agents: ["risk_aggressive", "risk_conservative", "risk_neutral", "portfolio_manager"] },
];

export type DeptPhase = "idle" | "working" | "done" | "failed";

export interface DeptStatus {
  zone: string;
  name: string;
  phase: DeptPhase;
  /** Short task label, e.g. "자료 조사 중". */
  task: string;
  done: number;
  /** Agents of this department that took part in this run so far. */
  total: number;
  /** Where the camera should look: the boardroom while the department is in a meeting there. */
  room: string;
}

type Status = "idle" | "working" | "talking" | "done" | "failed";

function statusOf(state: OfficeState, agentId: string): { status: Status; lookup: boolean } {
  const c = state.characters[agentId];
  if (c) return { status: c.status, lookup: c.status === "working" && c.lookup !== null };
  const o = state.offstage[agentId];
  return { status: o ? o.status : "idle", lookup: false };
}

function taskLabel(zone: string, busy: Set<string>, lookup: boolean): string {
  switch (zone) {
    case "analyst_office":
      if (busy.has("data_collector")) return "정보 수집 중";
      return lookup ? "자료 조회 중" : "자료 조사 중";
    case "research_room":
      return busy.has("research_manager") ? "토론 정리 중" : "강세·약세 토론 중";
    case "trading_desk":
      return "거래안 작성 중";
    default:
      return busy.has("portfolio_manager") ? "최종 결정 중" : "리스크 토론 중";
  }
}

export function departmentStatus(state: OfficeState): DeptStatus[] {
  return DEPARTMENTS.map((d) => {
    // memory_log is a quick bookkeeping step, and data collection is not an analyst turn: neither
    // counts toward the analysts' "n of m" (they still drive the task label).
    const counted = d.agents.filter((a) => a !== "memory_log" && a !== "data_collector");
    const all = d.agents.map((a) => ({ id: a, ...statusOf(state, a) }));
    const busy = new Set(all.filter((a) => a.status === "working" || a.status === "talking").map((a) => a.id));
    const took = all.filter((a) => counted.includes(a.id) && a.status !== "idle");
    const done = took.filter((a) => a.status === "done").length;
    const failed = all.some((a) => a.status === "failed");
    let phase: DeptPhase = "idle";
    if (failed) phase = "failed";
    else if (busy.size > 0) phase = "working";
    else if (took.length > 0 && done === took.length) phase = "done";
    const task = phase === "working" ? taskLabel(d.zone, busy, all.some((a) => a.lookup))
      : phase === "done" ? "완료" : phase === "failed" ? "문제 발생" : "대기";
    const meeting = d.agents.some((a) => state.characters[a]?.activity === "meet");
    return { zone: d.zone, name: d.name, phase, task, done, total: took.length,
             room: meeting ? "boardroom" : d.zone };
  });
}

/** One thing an operating desk (research team, Kiwoom mock desk) did, as stored. */
export interface TopicDeskEvent {
  market: "KR" | "US";
  title: string;
  created_at: string;
}

const DAY_START_KST_HOUR = 6;   // the company day runs 06:00–06:00 KST, so a US night session is one day

/** Start of the company day containing `now` (06:00 KST). */
export function companyDayStart(now: Date): Date {
  const kst = new Date(now.getTime() + 9 * 3600_000);
  const start = Date.UTC(kst.getUTCFullYear(), kst.getUTCMonth(), kst.getUTCDate(), DAY_START_KST_HOUR) - 9 * 3600_000;
  return new Date(start > now.getTime() ? start - 24 * 3600_000 : start);
}

/** What one market's desk did today, topics only, oldest first. */
export function deskToday<T extends TopicDeskEvent>(market: "KR" | "US", events: T[], now: Date): T[] {
  const since = companyDayStart(now).getTime();
  return events.filter((e) => e.market === market && new Date(e.created_at).getTime() >= since)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}
