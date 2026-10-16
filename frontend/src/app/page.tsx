"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { fetchRunEvents, getRun, listRuns, startRun, API_BASE, type RunSummary } from "../lib/api";
import { ReplayPlayer, type Speed } from "../office/replay";
import { ROSTER_2A } from "../office/roster";
import { initialOfficeState, reduceEvent, type OfficeState } from "../office/stateMachine";
import type { EventType, RunEvent } from "../types";
import { agentName, humanizeTickers, PHASE_KO, STATUS_KO } from "../office/names";
import { ACTION_KO, decisionLines, FLAG_KO, narrate } from "../office/explain";
import HelpPanel from "./HelpPanel";
import Markdown from "./Markdown";

const OfficeCanvas = dynamic(() => import("../game/OfficeCanvas"), { ssr: false });

type Action = { kind: "reset" } | { kind: "event"; ev: RunEvent };
const reducer = (s: OfficeState, a: Action): OfficeState =>
  a.kind === "reset" ? initialOfficeState(ROSTER_2A) : reduceEvent(s, a.ev);

const TERMINAL = new Set(["COMPLETED", "FAILED", "INSUFFICIENT_DATA"]);
const EVENT_TYPES: EventType[] = ["run.created", "run.started", "agent.started", "agent.completed",
  "agent.failed", "debate.message", "decision.created", "run.completed", "run.failed"];
const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

export default function OfficePage() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
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
  const [state, dispatch] = useReducer(reducer, ROSTER_2A, initialOfficeState);
  const player = useRef<ReplayPlayer | null>(null);
  const source = useRef<EventSource | null>(null);
  const loadToken = useRef(0);

  const refreshRuns = useCallback(() => {
    listRuns().then(setRuns).catch((e: Error) => setError(`API에 연결할 수 없습니다 (${API_BASE}): ${e.message}`));
  }, []);

  useEffect(() => {
    refreshRuns();
    const fromUrl = new URLSearchParams(window.location.search).get("run");
    if (fromUrl) setRunId(fromUrl);
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReducedMotion(mq.matches);
    const onChange = () => setReducedMotion(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
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
          refreshRuns();
        }
      };
      for (const t of EVENT_TYPES) es.addEventListener(t, onEvent as EventListener);
      return;
    }
    setMode("replay");
    try {
      const events = await fetchRunEvents(id);
      if (token !== loadToken.current) return;
      const p = new ReplayPlayer(events, apply, speed, () => setPlaying(false));
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
      const list = await listRuns();
      setRuns(list);
      setRunId(id);
      void load(id);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const animate = animateLast && speed !== "instant";
  const sel = selected ? state.characters[selected] : undefined;
  const offstage = useMemo(() => Object.entries(state.offstage), [state.offstage]);
  const current = runs.find((r) => r.id === runId);

  return (
    <main className="flex h-screen flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-[var(--line)] bg-[#0b1020]/90 px-4 py-2 text-sm">
        <h1 className="pixel text-[13px] text-[var(--mint)]">STOCK OFFICE</h1>
        <span className="rounded-full border border-[var(--line)] px-2 py-0.5 text-xs text-[var(--muted)]">PAPER ONLY · 결정은 제안이며 주문 없음</span>
        <label className="flex items-center gap-1">
          <span className="text-[var(--muted)]">실행</span>
          <select className="max-w-[340px] rounded bg-[var(--panel)] px-2 py-1" value={runId ?? ""}
                  onChange={(e) => setRunId(e.target.value || null)}>
            <option value="">— 저장된 실행 선택 —</option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {r.instrument_id} · {r.engine === "demo" ? "DEMO" : "TradingAgents"} · {PHASE_KO[r.status] ?? r.status} · {r.requested_at.slice(5, 16).replace("T", " ")}
              </option>
            ))}
          </select>
        </label>
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
          <button onClick={() => runId && void load(runId)} disabled={!runId}
                  className="rounded bg-[var(--panel)] px-2 py-1 disabled:opacity-40">처음부터</button>
        </div>
        <div className="ml-auto flex items-center gap-1">
          <select className="rounded bg-[var(--panel)] px-2 py-1" value={instrument}
                  onChange={(e) => setInstrument(e.target.value)} aria-label="종목">
            <option>US:NASDAQ:NVDA</option><option>KR:KRX:005930</option>
          </select>
          <select className="rounded bg-[var(--panel)] px-2 py-1" value={engine} aria-label="엔진"
                  onChange={(e) => setEngine(e.target.value as "demo" | "tradingagents")}>
            <option value="demo">DEMO (무료)</option>
            <option value="tradingagents">TradingAgents (유료)</option>
          </select>
          <button onClick={() => void start()} className="rounded bg-[var(--mint)] px-3 py-1 font-semibold text-black"
                  title="고른 종목으로 AI 투자위원회 회의(분석)를 새로 시작합니다">새 분석 시작</button>
          <button onClick={() => setHelp(true)} className="rounded border border-[var(--line)] px-3 py-1">보는 법</button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <section className="relative min-w-0 flex-1" aria-label="사무실">
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

        <aside className="flex w-[360px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-[var(--line)] bg-[#0d1426] p-3 text-sm">
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
              <h2 className="mb-1 text-xs uppercase tracking-widest text-[var(--muted)]">사무실 밖 직원 (Sprint 2B에서 입장)</h2>
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
