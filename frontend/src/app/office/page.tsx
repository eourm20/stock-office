"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { API_BASE, getOfficeNow, type OfficeNow } from "../../lib/api";
import { kstDateTime, nextWorkLabel } from "../../inbox/model";
import { DEPARTMENTS, departmentStatus } from "../../office/departments";
import { ACTION_KO, narrate } from "../../office/explain";
import { agentName, humanizeTickers, STATUS_KO, toolNames } from "../../office/names";
import { ReplayPlayer } from "../../office/replay";
import { ROSTER } from "../../office/roster";
import { initialOfficeState, reduceEvent, type OfficeState } from "../../office/stateMachine";
import type { EventType, RunEvent } from "../../types";
import ConveneButton from "../ConveneButton";
import Markdown from "../Markdown";
import NavBar from "../NavBar";

const OfficeCanvas = dynamic(() => import("../../game/OfficeCanvas"), { ssr: false });

type Action = { kind: "reset" } | { kind: "event"; ev: RunEvent };
const reducer = (s: OfficeState, a: Action): OfficeState =>
  a.kind === "reset" ? initialOfficeState(ROSTER) : reduceEvent(s, a.ev);

const EVENT_TYPES: EventType[] = ["run.created", "run.started", "agent.started", "agent.completed",
  "agent.failed", "debate.message", "tool.called", "decision.created", "run.completed", "run.failed"];
const PHASE_DOT: Record<string, string> = {
  working: "bg-sky-300 animate-pulse", done: "bg-emerald-400", failed: "bg-rose-400", idle: "bg-slate-600",
};

/**
 * 오피스: a CCTV of the company. Only work happening now is shown (a meeting in progress, live from
 * its events); past meetings are records, not replays. When nobody is working the office says so.
 */
export default function OfficePage() {
  const [now, setNow] = useState<OfficeNow | null>(null);
  const [following, setFollowing] = useState<{ runId: string; name: string; demo: boolean } | null>(null);
  const [finished, setFinished] = useState<string | null>(null);   // run that ended while watching
  const [state, dispatch] = useReducer(reducer, ROSTER, initialOfficeState);
  const [animate, setAnimate] = useState(true);
  const [zone, setZone] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState<Date | null>(null);   // client only: no SSR time mismatch
  const source = useRef<EventSource | null>(null);
  const followingRef = useRef<string | null>(null);

  const follow = useCallback((runId: string, name: string, demo: boolean) => {
    if (followingRef.current === runId) return;
    source.current?.close();
    followingRef.current = runId;
    dispatch({ kind: "reset" });
    setFinished(null);
    setFollowing({ runId, name, demo });
    // Live events go through the paced queue; a backlog (joining mid-meeting) is applied at once.
    const player = new ReplayPlayer([], (ev, anim) => { setAnimate(anim); dispatch({ kind: "event", ev }); },
                                    1, () => {}, true);
    const es = new EventSource(`${API_BASE}/api/v1/analysis-runs/${runId}/events`);
    source.current = es;
    const onEvent = (msg: MessageEvent<string>) => {
      const ev = JSON.parse(msg.data) as RunEvent;
      player.push(ev);
      if (ev.type === "run.completed" || ev.type === "run.failed") {
        es.close();
        player.close();
        setFinished(runId);
      }
    };
    for (const t of EVENT_TYPES) es.addEventListener(t, onEvent as EventListener);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const n = await getOfficeNow();
      setNow(n);
      setError(null);
      if (n.active) follow(n.active.run_id, n.active.name, n.active.demo);
    } catch (e) {
      setError(`서버에 연결할 수 없습니다: ${(e as Error).message}`);
    }
  }, [follow]);

  useEffect(() => {
    void refresh();
    const poll = setInterval(() => void refresh(), 15_000);
    setClock(new Date());
    const tick = setInterval(() => setClock(new Date()), 1_000);
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => { clearInterval(poll); clearInterval(tick); mq.removeEventListener("change", onChange); source.current?.close(); };
  }, [refresh]);

  const live = Boolean(following && !finished);
  const board = departmentStatus(state);
  const lastAt = (agents: string[]) => {
    const f = [...state.feed].reverse().find((e) => e.agentId && agents.includes(e.agentId));
    return f ? new Date(f.time).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false }) : null;
  };
  const next = now?.next[0];
  const sel = selected ? state.characters[selected] : undefined;
  const idleText = next ? `지금 진행 중인 업무 없음 · 다음: ${kstDateTime(next.at)} ${nextWorkLabel(next)}` : "지금 진행 중인 업무 없음";

  return (
    <main className="flex min-h-screen flex-col md:h-screen">
      <NavBar><ConveneButton onStarted={() => void refresh()} /></NavBar>

      {/* Department monitors: what each department is doing now. Tap to point the camera. */}
      <section aria-label="부서 모니터" className="grid grid-cols-2 gap-2 border-b border-[var(--line)] bg-[#0d1426] p-2 md:grid-cols-4">
        {board.map((d) => {
          const dept = DEPARTMENTS.find((x) => x.zone === d.zone)!;
          const at = lastAt(dept.agents);
          const on = zone === d.zone;
          return (
            <button key={d.zone} onClick={() => setZone(on ? null : d.zone)} aria-pressed={on}
                    className={`rounded-lg border p-2 text-left ${on ? "border-[#ffd98a] bg-[#1d2944]" : "border-[var(--line)] bg-[var(--panel)]"}`}>
              <div className="flex items-center justify-between text-[11px]">
                <span className="font-semibold text-[var(--ink)]">{d.name}</span>
                <span className={`flex items-center gap-1 ${d.phase === "working" ? "text-sky-300" : "text-[var(--muted)]"}`}>
                  <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${PHASE_DOT[d.phase]}`} />
                  {d.phase === "working" ? "LIVE" : d.phase === "done" ? "완료" : d.phase === "failed" ? "문제" : "대기"}
                </span>
              </div>
              <div className={`mt-1 text-[13px] leading-tight ${d.phase === "working" ? "text-sky-100" : "text-[var(--muted)]"}`}>
                {d.phase === "idle"
                  ? (next ? `다음 ${new Date(next.at).toLocaleTimeString("en-GB", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" })} ${nextWorkLabel(next)}` : "예정 없음")
                  : d.task}
                {d.total > 0 && d.phase !== "idle" && <span className="ml-1 text-[var(--muted)]">({d.done}/{d.total})</span>}
              </div>
              <div className="mt-0.5 truncate text-[10px] text-[var(--muted)]">
                {following && d.phase !== "idle" ? following.name : ""}{at ? ` · ${at}` : ""}
              </div>
            </button>
          );
        })}
      </section>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className="relative h-[50vh] min-w-0 md:h-auto md:flex-1" aria-label="사무실 CCTV">
          <OfficeCanvas state={state} animate={animate} speed={1} reducedMotion={reducedMotion}
                        selected={selected} onAgentClick={(id) => setSelected(id)} zone={zone} />
          {/* CCTV overlay: recording mark and the current time (presentation only). */}
          <div className="pointer-events-none absolute left-2 top-2 flex items-center gap-2 rounded bg-black/60 px-2 py-1 font-mono text-[11px] text-white">
            <span className={live ? "text-rose-400" : "text-slate-400"}>{live ? "● REC" : "○ 대기"}</span>
            <span>{clock?.toLocaleTimeString("en-GB", { timeZone: "Asia/Seoul", hour12: false }) ?? "--:--:--"}</span>
            {zone && <span className="text-[#ffd98a]">{board.find((b) => b.zone === zone)?.name}</span>}
          </div>
          <div className="pointer-events-none absolute left-1/2 top-10 w-[min(640px,92%)] -translate-x-1/2 rounded-xl border border-[#ffd98a55] bg-[#0b1020e6] px-3 py-1.5 text-center text-[13px] text-[#fff3d6] sm:text-[14px]"
               role="status" aria-live="polite">
            {live && following ? (
              <><span className="mr-1 text-[var(--warn)]">{following.name}</span>{narrate(state)}</>
            ) : finished && following ? (
              <>{following.name} 회의가 끝났습니다 · <Link href="/" className="pointer-events-auto underline">결재함 확인</Link></>
            ) : idleText}
          </div>
          {following?.demo && <span className="pointer-events-none absolute bottom-3 left-3 rounded bg-amber-400 px-2 py-1 text-xs font-bold text-black">DEMO · 연습 회의</span>}
          {error && <p role="alert" className="absolute bottom-12 left-3 rounded bg-rose-900/80 px-3 py-2 text-sm">{error}</p>}
        </section>

        <aside className="flex w-full shrink-0 flex-col gap-3 border-t border-[var(--line)] bg-[#0d1426] p-3 text-sm md:w-[340px] md:overflow-y-auto md:border-l md:border-t-0">
          {!following && (
            <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
              <h2 className="text-xs text-[var(--muted)]">오늘 일정</h2>
              <ul className="mt-1 space-y-1">
                {(now?.next ?? []).map((n) => <li key={n.instrument_id + n.at}>{kstDateTime(n.at)} · {nextWorkLabel(n, "정기 회의")}</li>)}
              </ul>
              <Link href="/records" className="mt-2 inline-block text-xs underline">지난 회의록 보기 →</Link>
            </div>
          )}
          {state.decision && (
            <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
              <h2 className="text-xs text-[var(--muted)]">이번 회의 결론</h2>
              <p className="mt-0.5 text-xl font-bold">{ACTION_KO[state.decision.action]?.label ?? state.decision.action}</p>
              {finished && <Link href={`/records/${finished}`} className="text-xs underline">회의록 보기 →</Link>}
            </div>
          )}
          {sel && (
            <div className="rounded-lg border border-[#ffd98a55] bg-[var(--panel)] p-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">{agentName(sel.agentId, sel.role)}</h2>
                <button onClick={() => setSelected(null)} className="text-xs text-[var(--muted)]">닫기</button>
              </div>
              <p className="text-xs text-[var(--muted)]">{STATUS_KO[sel.status]}</p>
              {sel.lookup && sel.status === "working" && <p className="mt-1 text-xs text-amber-200">🔍 {toolNames(sel.lookup.tools)} 조회 중</p>}
              {sel.bubble && <p className="mt-2 font-semibold">“{sel.bubble.text}”</p>}
              {sel.summary && !sel.bubble && (
                <div className="mt-2 max-h-60 overflow-y-auto text-xs"><Markdown text={humanizeTickers(sel.summary).replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "")} /></div>
              )}
            </div>
          )}
          <div className="min-h-0 flex-1 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
            <h2 className="mb-1 text-xs text-[var(--muted)]">활동 기록 {live ? "· 실시간" : ""}</h2>
            {state.feed.length === 0 ? <p className="text-xs text-[var(--muted)]">{idleText}</p> : (
              <ol aria-live="polite" className="space-y-1 text-xs">
                {state.feed.slice().reverse().map((f) => (
                  <li key={f.seq} className="border-b border-[var(--line)]/50 pb-1">
                    <span className="text-[var(--muted)]">{new Date(f.time).toLocaleTimeString("en-GB", { timeZone: "Asia/Seoul", hour12: false })}</span> {f.text}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </aside>
      </div>
    </main>
  );
}
