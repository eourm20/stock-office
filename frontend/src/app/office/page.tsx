"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import Link from "next/link";
import { fetchRunEvents, getRun, getSummary, startRun, API_BASE, type RunSummary } from "../../lib/api";
import { chooseAutoRun, INSTRUMENT_KO, timeAgo, type InstrumentSummary } from "../../office/auto";
import { ReplayPlayer, type Speed } from "../../office/replay";
import { ROSTER } from "../../office/roster";
import { initialOfficeState, reduceEvent, type OfficeState } from "../../office/stateMachine";
import type { EventType, RunEvent } from "../../types";
import { agentName, humanizeTickers, PHASE_KO, STATUS_KO, toolNames } from "../../office/names";
import { ACTION_KO, decisionLines, FLAG_KO, narrate } from "../../office/explain";
import HelpPanel from "../HelpPanel";
import Markdown from "../Markdown";
import NavBar from "../NavBar";

const OfficeCanvas = dynamic(() => import("../../game/OfficeCanvas"), { ssr: false });

type Action = { kind: "reset" } | { kind: "event"; ev: RunEvent };
const reducer = (s: OfficeState, a: Action): OfficeState =>
  a.kind === "reset" ? initialOfficeState(ROSTER) : reduceEvent(s, a.ev);

const TERMINAL = new Set(["COMPLETED", "FAILED", "INSUFFICIENT_DATA"]);
const EVENT_TYPES: EventType[] = ["run.created", "run.started", "agent.started", "agent.completed",
  "agent.failed", "debate.message", "decision.created", "run.completed", "run.failed"];
const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

export default function OfficePage() {
  const [summary, setSummary] = useState<InstrumentSummary[]>([]);
  const [current, setCurrent] = useState<RunSummary | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  /** Auto mode: follow a meeting in progress, otherwise show the newest decision. */
  const [auto, setAuto] = useState(true);
  const [now, setNow] = useState(() => Date.now());
  const [speed, setSpeed] = useState<Speed>(1);
  const [playing, setPlaying] = useState(false);
  const [mode, setMode] = useState<"replay" | "live" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [reducedMotion, setReducedMotion] = useState(false);
  /** Whether the latest change may be animated (false while catching up). */
  const [animateLast, setAnimateLast] = useState(true);
  const [instrument, setInstrument] = useState("US:NASDAQ:NVDA");
  const [engine, setEngine] = useState<"demo" | "tradingagents">("demo");
  const [help, setHelp] = useState(false);
  const [state, dispatch] = useReducer(reducer, ROSTER, initialOfficeState);
  const player = useRef<ReplayPlayer | null>(null);
  const source = useRef<EventSource | null>(null);
  const loadToken = useRef(0);
  /** Speed for the next load (e.g. "instant" to show a past result at once). */
  const pendingSpeed = useRef<Speed | null>(null);
  const runIdRef = useRef<string | null>(null);
  runIdRef.current = runId;
  const autoRef = useRef(auto);
  autoRef.current = auto;

  const show = useCallback((id: string, sp: Speed) => {
    pendingSpeed.current = sp;
    setRunId(id);
  }, []);

  /** Refresh the per-instrument summary; in auto mode, jump to a meeting that just started. */
  const refreshRuns = useCallback(async (initial = false) => {
    try {
      const items = await getSummary();
      setSummary(items);
      setNow(Date.now());
      if (!autoRef.current) return;
      const choice = chooseAutoRun(items);
      if (!choice) return;
      if (choice.live && choice.runId !== runIdRef.current) show(choice.runId, 1);
      else if (initial && !runIdRef.current) show(choice.runId, "instant");
    } catch (e) {
      setError(`API에 연결할 수 없습니다 (${API_BASE}): ${(e as Error).message}`);
    }
  }, [show]);

  useEffect(() => {
    const fromUrl = new URLSearchParams(window.location.search).get("run");
    if (fromUrl) {
      setAuto(false);
      autoRef.current = false;
      setRunId(fromUrl);
    }
    void refreshRuns(true);
    const timer = setInterval(() => void refreshRuns(), 15_000);
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => {
      clearInterval(timer);
      mq.removeEventListener("change", onChange);
    };
  }, [refreshRuns]);

  const stop = useCallback(() => {
    player.current?.pause();
    player.current = null;
    source.current?.close();
    source.current = null;
    setPlaying(false);
  }, []);

  /** Load a run: finished runs are replayed with timing; running runs are followed live. */
  const load = useCallback(async (id: string) => {
    stop();
    dispatch({ kind: "reset" });
    setSelected(null);
    setError(null);
    const token = ++loadToken.current;
    const sp = pendingSpeed.current ?? speed;
    pendingSpeed.current = null;
    if (sp !== speed) setSpeed(sp);
    // Ask the server for the run's current status: a cached list can be stale, and a running
    // run must be followed live (a replay request would wait until the run finishes).
    let run: RunSummary;
    try {
      run = await getRun(id);
    } catch (e) {
      setError((e as Error).message);
      return;
    }
    if (token !== loadToken.current) return;           // a newer selection won the race
    setCurrent(run);
    const apply = (ev: RunEvent, animate: boolean) => {
      setAnimateLast(animate);
      dispatch({ kind: "event", ev });
    };
    const live = !TERMINAL.has(run.status);
    if (live) {
      // Live events go through the same paced queue; a backlog is applied at once.
      setMode("live");
      const p = new ReplayPlayer([], apply, 1, () => setPlaying(false), true);
      player.current = p;
      setPlaying(true);
      const es = new EventSource(`${API_BASE}/api/v1/analysis-runs/${id}/events`);
      source.current = es;
      const onEvent = (msg: MessageEvent<string>) => {
        const ev = JSON.parse(msg.data) as RunEvent;
        p.push(ev);
        if (ev.type === "run.completed" || ev.type === "run.failed") {
          es.close();
          p.close();
          void refreshRuns();
        }
      };
      for (const t of EVENT_TYPES) es.addEventListener(t, onEvent as EventListener);
      return;
    }
    setMode("replay");
    try {
      const events = await fetchRunEvents(id);
      if (token !== loadToken.current) return;
      const p = new ReplayPlayer(events, apply, sp, () => setPlaying(false));
      player.current = p;
      setPlaying(true);
      p.play();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [refreshRuns, speed, stop]);

  useEffect(() => {
    if (!runId) return;
    void load(runId);
    // Only reload when the selected run changes, not when the list refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useEffect(() => () => stop(), [stop]);

  const changeSpeed = (s: Speed) => {
    setSpeed(s);
    player.current?.setSpeed(s);
  };
  const togglePlay = () => {
    if (!player.current) return;
    if (playing) player.current.pause();
    else player.current.play();
    setPlaying(!playing && !player.current.done);
  };

  const start = async () => {
    if (engine === "tradingagents" && !window.confirm(
      `${instrument}: 실제 TradingAgents 분석은 OpenAI API 비용이 발생합니다 (economy 실측 약 $0.04/회, 2~3분). 실행할까요?`)) {
      return;
    }
    try {
      const id = await startRun(instrument, engine);
      show(id, 1);
      void refreshRuns();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const animate = animateLast && speed !== "instant";
  const sel = selected ? state.characters[selected] : undefined;
  const offstage = useMemo(() => Object.entries(state.offstage), [state.offstage]);

  return (
    <main className="flex min-h-screen flex-col md:h-screen">
      <NavBar>
        {auto ? (
          <span className="rounded bg-[#1e3a2f] px-2 py-1 text-xs text-[var(--mint)]" title="진행 중인 회의를 자동으로 따라가고, 없으면 최신 결정을 보여 줍니다">자동 모드</span>
        ) : (
          <button onClick={() => { setAuto(true); autoRef.current = true; setRunId(null); void refreshRuns(true); }}
                  className="rounded border border-[var(--mint)] px-2 py-1 text-xs text-[var(--mint)]">자동 모드로</button>
        )}
        <div className="flex items-center gap-1" role="group" aria-label="재생 속도">
          {([1, 4, "instant"] as Speed[]).map((s) => (
            <button key={String(s)} onClick={() => changeSpeed(s)}
                    className={`rounded px-2 py-1 ${speed === s ? "bg-[var(--accent)] text-black" : "bg-[var(--panel)]"}`}>
              {s === "instant" ? "즉시" : `${s}×`}
            </button>
          ))}
          <button onClick={togglePlay} disabled={mode !== "replay"}
                  className="rounded bg-[var(--panel)] px-2 py-1 disabled:opacity-40">
            {playing ? "일시정지" : "재생"}
          </button>
          <button onClick={() => { if (runId) { pendingSpeed.current = speed === "instant" ? 1 : speed; void load(runId); } }}
                  disabled={!runId || mode === "live"}
                  className="rounded bg-[var(--panel)] px-2 py-1 disabled:opacity-40">▶ 회의 다시보기</button>
        </div>
        <div className="flex w-full flex-wrap items-center gap-1 sm:ml-auto sm:w-auto">
          <select className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={instrument}
                  onChange={(e) => setInstrument(e.target.value)} aria-label="종목">
            {Object.entries(INSTRUMENT_KO).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
          </select>
          <select className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={engine} aria-label="엔진"
                  onChange={(e) => setEngine(e.target.value as "demo" | "tradingagents")}>
            <option value="demo">DEMO (무료)</option>
            <option value="tradingagents">TradingAgents (유료)</option>
          </select>
          <button onClick={() => void start()} className="shrink-0 whitespace-nowrap rounded bg-[var(--mint)] px-3 py-1 font-semibold text-black"
                  title="고른 종목으로 AI 투자위원회 회의(분석)를 새로 시작합니다">새 분석 시작</button>
          <button onClick={() => setHelp(true)} className="shrink-0 whitespace-nowrap rounded border border-[var(--line)] px-3 py-1">보는 법</button>
        </div>
      </NavBar>

      <nav aria-label="종목별 최신 결정" className="flex flex-wrap gap-2 border-b border-[var(--line)] bg-[#0d1426] px-4 py-2">
        {summary.map((s) => {
          const active = Boolean(s.active_run_id);
          const target = s.active_run_id ?? s.latest?.run_id ?? null;
          const isCurrent = target !== null && target === runId;
          const a = s.latest ? ACTION_KO[s.latest.action] : undefined;
          return (
            <button key={s.instrument_id} disabled={!target}
                    onClick={() => { if (!target) return; setAuto(false); autoRef.current = false; show(target, active ? 1 : "instant"); }}
                    className={`min-w-[220px] rounded-lg border px-3 py-2 text-left text-sm disabled:opacity-50 ${isCurrent ? "border-[#ffd98a]" : "border-[var(--line)]"} bg-[var(--panel)]`}>
              <div className="flex items-center justify-between gap-2">
                <span className="font-semibold">{INSTRUMENT_KO[s.instrument_id] ?? s.name}</span>
                {active && <span className="animate-pulse text-xs text-[var(--mint)]">● 회의 중</span>}
              </div>
              {s.latest ? (
                <div className="mt-0.5">
                  <span className={`text-lg font-bold ${ACTION_COLOR[s.latest.action] ?? ""}`}>{a?.label ?? s.latest.action}</span>
                  <span className="ml-2 text-xs text-[var(--muted)]">{timeAgo(s.latest.decided_at, now)} · 제안만</span>
                </div>
              ) : <div className="mt-0.5 text-xs text-[var(--muted)]">아직 실제 분석 결과 없음</div>}
            </button>
          );
        })}
      </nav>

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <section className="relative h-[58vh] min-w-0 md:h-auto md:flex-1" aria-label="사무실">
          <OfficeCanvas state={state} animate={animate} speed={speed === "instant" ? 8 : speed}
                        reducedMotion={reducedMotion} selected={selected}
                        onAgentClick={(id) => setSelected(id)} />
          <div className="pointer-events-none absolute left-1/2 top-3 w-[min(720px,90%)] -translate-x-1/2 rounded-xl border border-[#ffd98a66] bg-[#0b1020e6] px-4 py-2 text-center text-[15px] text-[#fff3d6] shadow-lg"
               role="status" aria-live="polite">
            <span className="mr-2 text-[var(--warn)]">지금</span>{narrate(state)}
          </div>
          <div className="pointer-events-none absolute left-3 top-16 flex gap-2 text-xs">
            {state.demo && <span className="rounded bg-amber-400 px-2 py-1 font-bold text-black">DEMO · 합성 데이터, 분석 결과 아님</span>}
            {mode && <span className="rounded bg-[var(--panel)] px-2 py-1">{mode === "live" ? "● 실시간" : "▶ 다시보기"} · {PHASE_KO[state.phase] ?? state.phase}</span>}
            {current && <span className="rounded bg-[var(--panel)] px-2 py-1">{current.instrument_id}</span>}
          </div>
          <p className="pointer-events-none absolute bottom-3 left-3 text-xs text-[var(--muted)]">드래그로 이동 · 휠/±로 확대 · 방향키 이동 · 직원 클릭 시 상세</p>
          {error && <p role="alert" className="absolute bottom-10 left-3 rounded bg-rose-900/80 px-3 py-2 text-sm">{error}</p>}
        </section>

        <aside className="flex w-full shrink-0 flex-col gap-3 border-t border-[var(--line)] bg-[#0d1426] p-3 text-sm md:w-[360px] md:overflow-y-auto md:border-l md:border-t-0">
          <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
            <h2 className="mb-1 text-xs uppercase tracking-widest text-[var(--muted)]">최종 결정</h2>
            {state.decision ? (
              <div>
                <p className={`text-2xl font-bold ${ACTION_COLOR[state.decision.action] ?? ""}`}>
                  {ACTION_KO[state.decision.action]?.label ?? state.decision.action}
                  <span className="ml-2 text-sm font-normal text-[var(--muted)]">({state.decision.action})</span>
                </p>
                <ul className="mt-1 space-y-0.5 text-[13px] text-[#dce6f7]">
                  {decisionLines(state.decision).map((l) => <li key={l}>{l}</li>)}
                </ul>
                <p className="mt-1 text-xs text-[var(--warn)]">{state.decision.execution === "PROPOSED_ONLY" ? "제안만 했고, 실제 주문은 하지 않았어요." : state.decision.execution}</p>
                {state.decision.flags.length > 0 && (
                  <details className="mt-2 text-xs text-[var(--muted)]">
                    <summary className="cursor-pointer">주의할 점 {state.decision.flags.length}개</summary>
                    <ul className="mt-1 list-disc pl-4">
                      {state.decision.flags.map((f) => <li key={f}>{FLAG_KO[f] ?? f}</li>)}
                    </ul>
                  </details>
                )}
              </div>
            ) : <p className="text-[var(--muted)]">아직 결정 없음</p>}
          </div>

          {sel && (
            <div className="rounded-lg border border-[#ffd98a55] bg-[var(--panel)] p-3">
              <div className="flex items-center justify-between">
                <h2 className="font-semibold">{agentName(sel.agentId, sel.role)}</h2>
                <button onClick={() => setSelected(null)} className="text-xs text-[var(--muted)]">닫기</button>
              </div>
              <p className="text-xs text-[var(--muted)]">상태: {STATUS_KO[sel.status]}{sel.turn > 1 ? ` · ${sel.turn}번째 차례` : ""}</p>
              {sel.lookup && sel.status === "working" && (
                <p className="mt-1 text-xs text-amber-200">🔍 {sel.lookup.round}번째 자료 조회: {toolNames(sel.lookup.tools)}</p>
              )}
              {sel.bubble && <p className="mt-2 font-semibold">“{sel.bubble.text}”</p>}
              {sel.summary && (
                <details className="mt-2 text-xs text-[#c7d7ee]" open={!sel.bubble}>
                  <summary className="cursor-pointer text-[var(--muted)]">전체 내용 보기</summary>
                  <div className="mt-1 max-h-80 overflow-y-auto pr-1"><Markdown text={humanizeTickers(sel.summary).replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "")} /></div>
                </details>
              )}
              {sel.error && <p className="mt-2 text-xs text-rose-300">{sel.error}</p>}
            </div>
          )}

          {offstage.length > 0 && (
            <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
              <h2 className="mb-1 text-xs uppercase tracking-widest text-[var(--muted)]">사무실 설비 (데이터 수집·기록 보관)</h2>
              <ul className="space-y-0.5 text-xs">
                {offstage.map(([id, o]) => <li key={id}>{agentName(id, o.role)}: {STATUS_KO[o.status]}</li>)}
              </ul>
            </div>
          )}

          <div className="min-h-0 flex-1 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
            <h2 className="mb-1 text-xs uppercase tracking-widest text-[var(--muted)]">활동 기록</h2>
            <ol aria-live="polite" className="space-y-1 text-xs">
              {state.feed.slice().reverse().map((f) => (
                <li key={f.seq} className="border-b border-[var(--line)]/50 pb-1">
                  <span className="text-[var(--muted)]">#{f.seq} {f.time.slice(11, 19)}</span> {f.text}
                </li>
              ))}
            </ol>
          </div>
        </aside>
      </div>
      {help && <HelpPanel onClose={() => setHelp(false)} />}
    </main>
  );
}
