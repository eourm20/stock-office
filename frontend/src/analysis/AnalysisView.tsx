"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import Markdown from "../app/Markdown";
import NavBar from "../app/NavBar";
import { fetchRunEvents, getBriefing, getDecision, getReports, getRunDetail, getSnapshots, getSummary,
  startRun, type Briefing, type Decision, type RunDetail, type Snapshot } from "../lib/api";
import { chooseAutoRun, INSTRUMENT_KO, timeAgo, type InstrumentSummary } from "../office/auto";
import { ACTION_KO, FLAG_KO, RATING_KO } from "../office/explain";
import { agentName, humanizeTickers, PHASE_KO, toolNames } from "../office/names";
import type { RunEvent } from "../types";
import DebateChat from "./DebateChat";
import { debateTranscript, FLOW_NODES, formatDuration, plainGap, summarizeAgents, tokenTotals } from "./model";

const FlowGraph = dynamic(() => import("./FlowGraph"), { ssr: false });

const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};
const FINISHED = new Set(["COMPLETED", "FAILED", "INSUFFICIENT_DATA"]);
const REPORT_AGENTS = FLOW_NODES.map((n) => n.id)
  .filter((id) => !["decision", "data_collector", "memory_log"].includes(id));

const kst = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", {
  timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
}) : "—");

interface Loaded {
  run: RunDetail;
  events: RunEvent[];
  decision: Decision | null;
  snapshots: Snapshot[];
  reports: { available: boolean; reports: Record<string, string> };
  briefing: Briefing | null;
}

type Tab = "reports" | "debate" | "evidence" | "facts";

/**
 * Main screen: one run's decision, the committee graph, reports, debate, evidence and run facts.
 * `runId === null` follows the newest decision (or the meeting in progress).
 */
export default function AnalysisView({ runId }: { runId: string | null }) {
  const router = useRouter();
  const [summary, setSummary] = useState<InstrumentSummary[]>([]);
  const [resolved, setResolved] = useState<string | null>(runId);
  const [data, setData] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>("portfolio_manager");
  const [tab, setTab] = useState<Tab>("reports");

  useEffect(() => {
    getSummary().then((items) => {
      setSummary(items);
      if (!runId) setResolved(chooseAutoRun(items)?.runId ?? null);
    }).catch((e: Error) => setError(`API에 연결할 수 없습니다: ${e.message}`));
  }, [runId]);

  const load = useCallback(async (id: string) => {
    const run = await getRunDetail(id);
    if (!FINISHED.has(run.status)) {
      // The event stream of a running run stays open; show its state and refresh until it ends.
      setData({ run, events: [], decision: null, snapshots: [], reports: { available: false, reports: {} },
                briefing: null });
      return false;
    }
    const [events, decision, snapshots, reports, brief] = await Promise.all([
      fetchRunEvents(id), getDecision(id), getSnapshots(id), getReports(id), getBriefing(id)]);
    const briefing = brief.briefing?.status === "OK" ? brief.briefing : null;
    setData({ run, events, decision, snapshots, reports, briefing });
    return true;
  }, []);

  useEffect(() => {
    if (!resolved) return;
    setData(null);
    let timer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;
    const tick = () => load(resolved).then((done) => {
      if (!done && !cancelled) timer = setTimeout(tick, 10_000);
    }).catch((e: Error) => setError(e.message));
    void tick();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [resolved, load]);

  const agents = useMemo(() => summarizeAgents(data?.events ?? [],
    data ? FINISHED.has(data.run.status) : false), [data]);
  const debate = useMemo(() => debateTranscript(data?.events ?? []), [data]);

  return (
    <main className="flex min-h-screen flex-col">
      <NavBar><StartControls onStarted={(id) => router.push(`/office?run=${id}`)} /></NavBar>

      <section className="flex gap-2 overflow-x-auto border-b border-[var(--line)] px-3 py-3 sm:px-4" aria-label="종목별 최신 결정">
        {summary.map((s) => {
          const id = s.active_run_id ?? s.latest?.run_id;
          const active = id && id === resolved;
          return (
            <Link key={s.instrument_id} href={id ? `/analysis/${id}` : "/"}
                  className={`min-w-40 shrink-0 rounded-lg border px-3 py-2 text-left ${active ? "border-[#ffd98a] bg-[#1d2944]" : "border-[var(--line)] bg-[var(--panel)]"}`}>
              <div className="text-sm font-semibold">{INSTRUMENT_KO[s.instrument_id] ?? s.name ?? s.instrument_id}</div>
              {s.active_run_id ? <div className="mt-0.5 text-sky-300">● 회의 중</div>
                : s.latest ? (
                  <div className="mt-0.5 flex items-baseline gap-2">
                    <span className={`text-lg font-bold ${ACTION_COLOR[s.latest.action] ?? ""}`}>{ACTION_KO[s.latest.action]?.label ?? s.latest.action}</span>
                    <span className="text-xs text-[var(--muted)]">{timeAgo(s.latest.decided_at)}</span>
                  </div>
                ) : <div className="mt-0.5 text-xs text-[var(--muted)]">아직 결정 없음</div>}
            </Link>
          );
        })}
      </section>

      {error && <p role="alert" className="mx-4 mt-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!resolved && !error && <p className="p-6 text-[var(--muted)]">아직 분석 기록이 없습니다. 위에서 새 분석을 시작해 보세요.</p>}
      {resolved && !data && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {data && !FINISHED.has(data.run.status) && (
        <div className="m-4 rounded-lg border border-sky-700 bg-sky-950/40 p-4">
          <p className="font-semibold text-sky-200">이 회의는 지금 진행 중입니다 ({PHASE_KO[data.run.status] ?? data.run.status}).</p>
          <p className="mt-1 text-sm text-[var(--muted)]">끝나면 이 화면이 자동으로 결과를 보여 줍니다. 진행 과정을 실시간으로 보려면
            {" "}<Link className="underline" href={`/office?run=${data.run.id}`}>사무실에서 보기</Link>.</p>
        </div>
      )}

      {data && FINISHED.has(data.run.status) && (
        <div className="grid flex-1 gap-3 p-3 sm:gap-4 sm:p-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="flex min-w-0 flex-col gap-3 sm:gap-4">
            <DecisionCard run={data.run} decision={data.decision} briefing={data.briefing} />
            {/* The graph needs width; on phones the team list below carries the same content. */}
            <section className="hidden rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3 md:block">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-semibold">위원회 흐름</h2>
                <p className="text-xs text-[var(--muted)]">왼쪽에서 오른쪽 순서로 일했습니다. 칸을 누르면 오른쪽에 그 직원의 보고서가 나옵니다.{" "}
                  <Link className="underline" href={`/office?run=${data.run.id}`}>사무실 애니메이션으로 다시보기</Link></p>
              </div>
              <FlowGraph agents={agents} action={data.decision?.action ?? null} selected={selected}
                         onSelect={(id) => { setSelected(id); }} />
            </section>
            <section className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
              <div role="tablist" aria-label="세부 내용"
                   className="sticky top-0 z-10 flex gap-1 overflow-x-auto rounded-t-lg border-b border-[var(--line)] bg-[var(--panel)] p-2">
                {([["reports", "팀별 의견"], ["debate", `토론 ${debate.length}`],
                   ["evidence", `출처 ${data.snapshots.length}`], ["facts", "실행 정보"]] as [Tab, string][])
                  .map(([t, label]) => (
                    <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                            className={`shrink-0 whitespace-nowrap rounded px-3 py-1.5 text-sm ${tab === t ? "bg-[var(--accent)] text-black" : "hover:bg-[#1d2944]"}`}>{label}</button>
                  ))}
              </div>
              <div className="p-3">
                {tab === "reports" && <ReportsTab data={data} agents={agents} selected={selected} onSelect={setSelected} />}
                {tab === "debate" && <DebateChat lines={debate} gists={data.briefing?.debate ?? {}}
                                                 fullTranscripts={data.reports.reports} />}
                {tab === "evidence" && <EvidenceTab run={data.run} snapshots={data.snapshots} />}
                {tab === "facts" && <FactsTab run={data.run} decision={data.decision} />}
              </div>
            </section>
            <Link href={`/office?run=${data.run.id}`} className="py-1 text-center text-sm text-[var(--muted)] underline md:hidden">
              사무실 애니메이션으로 이 회의 다시보기
            </Link>
          </div>
          {/* Desktop: the selected agent beside the content. Phones expand agents in place instead. */}
          <aside className="hidden min-w-0 flex-col gap-2 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3 xl:sticky xl:top-2 xl:flex xl:max-h-[calc(100vh-1rem)] xl:overflow-y-auto">
            <h2 className="text-lg font-semibold">{agentName(selected)}</h2>
            <AgentBody data={data} agentId={selected} summary={agents[selected]} />
          </aside>
        </div>
      )}
    </main>
  );
}

function StartControls({ onStarted }: { onStarted: (runId: string) => void }) {
  const [instrument, setInstrument] = useState("US:NASDAQ:NVDA");
  const [engine, setEngine] = useState<"demo" | "tradingagents">("demo");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const start = async () => {
    if (engine === "tradingagents" && !window.confirm(
      `${INSTRUMENT_KO[instrument] ?? instrument}: 실제 분석은 OpenAI API 비용이 발생합니다 (실측 약 $0.05/회, 3~4분). 실행할까요?`)) return;
    setBusy(true);
    try { onStarted(await startRun(instrument, engine)); } catch (e) { window.alert((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="ml-auto flex flex-wrap items-center justify-end gap-1">
      {/* Phones: starting a run is rare (and can cost money), so it sits behind one button. */}
      <button onClick={() => setOpen(!open)} aria-expanded={open}
              className="rounded border border-[var(--mint)] px-2 py-1 text-xs text-[var(--mint)] sm:hidden">{open ? "닫기" : "＋ 새 분석"}</button>
      <div className={`${open ? "flex" : "hidden"} w-full flex-wrap items-center gap-1 sm:flex sm:w-auto`}>
        <select aria-label="종목" className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={instrument} onChange={(e) => setInstrument(e.target.value)}>
          {Object.entries(INSTRUMENT_KO).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <select aria-label="분석 종류" className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={engine} onChange={(e) => setEngine(e.target.value as "demo" | "tradingagents")}>
          <option value="demo">DEMO (무료)</option><option value="tradingagents">실제 분석 (유료)</option>
        </select>
        <button disabled={busy} onClick={() => void start()} className="shrink-0 whitespace-nowrap rounded bg-[var(--mint)] px-3 py-1 font-semibold text-black disabled:opacity-50">새 분석 시작</button>
      </div>
    </div>
  );
}

const BRIEF_SECTIONS = [
  { key: "key_reasons", label: "이유", tone: "text-emerald-300", dot: "bg-emerald-400" },
  { key: "risks", label: "위험", tone: "text-rose-300", dot: "bg-rose-400" },
  { key: "watch_next", label: "확인할 것", tone: "text-sky-300", dot: "bg-sky-400" },
] as const;

/**
 * The verdict and the one-page briefing in one card: action, one-line conclusion, then reasons /
 * risks / what to watch (one list at a time on phones, three columns on wide screens).
 */
function DecisionCard({ run, decision, briefing }: { run: RunDetail; decision: Decision | null; briefing: Briefing | null }) {
  const [seg, setSeg] = useState<(typeof BRIEF_SECTIONS)[number]["key"]>("key_reasons");
  const name = INSTRUMENT_KO[run.instrument_id] ?? run.instrument_id;
  if (!decision) {
    return (
      <section className="rounded-lg border border-amber-600 bg-amber-950/30 p-4">
        <h2 className="text-lg font-semibold">{name} · 결정 없음</h2>
        <p className="mt-1 text-sm">이 실행은 결정을 내지 못했습니다: {PHASE_KO[run.status] ?? run.status}
          {run.error_code ? ` (${run.error_code}${run.error_message ? `: ${run.error_message}` : ""})` : ""}</p>
      </section>
    );
  }
  const a = ACTION_KO[decision.action];
  return (
    <section className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-4" aria-label="최종 결정">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--muted)]">
        <span className="text-sm font-semibold text-[var(--ink)]">{name}</span>
        <span>{kst(decision.created_at)}</span>
        {run.trigger === "schedule" && <span className="rounded bg-[#1e3a2f] px-1.5 text-[var(--mint)]">매일 자동</span>}
        {decision.demo && <span className="rounded bg-amber-400 px-1.5 font-bold text-black">DEMO · 분석 결과 아님</span>}
      </div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-3">
        <span className={`text-4xl font-bold ${ACTION_COLOR[decision.action] ?? ""}`}>{a?.label ?? decision.action}</span>
        {decision.engine_rating && <span className="text-sm text-[var(--muted)]">{RATING_KO[decision.engine_rating] ?? decision.engine_rating}</span>}
      </div>
      <p className="mt-2 text-[15px] font-semibold leading-snug text-[#fff3d6]">{briefing ? humanizeTickers(briefing.headline) : a?.plain}</p>
      {decision.action === "REVIEW" && <p className="mt-1 text-sm text-amber-300">근거가 부족하거나 결론을 읽을 수 없어 사람이 확인해야 합니다.</p>}

      {briefing && (
        <div className="mt-3 border-t border-[var(--line)] pt-3">
          <div role="tablist" aria-label="브리핑 항목" className="mb-2 grid grid-cols-3 gap-1 rounded-lg bg-[#0f1729] p-1 sm:hidden">
            {BRIEF_SECTIONS.map((b) => (
              <button key={b.key} role="tab" aria-selected={seg === b.key} onClick={() => setSeg(b.key)}
                      className={`rounded-md px-2 py-1.5 text-xs font-semibold ${seg === b.key ? `bg-[#26324f] ${b.tone}` : "text-[var(--muted)]"}`}>
                {b.label}
              </button>
            ))}
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            {BRIEF_SECTIONS.map((b) => briefing[b.key].length > 0 && (
              <div key={b.key} className={`${seg === b.key ? "block" : "hidden"} sm:block`}>
                <h3 className={`mb-1.5 hidden text-xs font-semibold sm:block ${b.tone}`}>{b.label === "확인할 것" ? "다음에 확인할 것" : `핵심 ${b.label}`}</h3>
                <ul className="space-y-2 text-sm leading-relaxed">
                  {briefing[b.key].map((x) => (
                    <li key={x} className="flex gap-2"><span aria-hidden="true" className={`mt-2 h-1.5 w-1.5 shrink-0 rounded-full ${b.dot}`} /><span>{humanizeTickers(x)}</span></li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-[var(--muted)]">
        <span className="rounded border border-[var(--line)] px-1.5 py-0.5">{decision.execution === "PROPOSED_ONLY" ? "제안만 · 주문 없음" : decision.execution}</span>
        {briefing && <span title={`모델: ${briefing.model}`}>AI 요약 · 이번 회의 보고서 기준</span>}
        <span>· 검증된 투자 신호 아님</span>
      </div>
      {decision.risk_flags.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-xs text-amber-200">⚠ 데이터 주의 {decision.risk_flags.length}개</summary>
          <ul className="mt-1 space-y-0.5 text-[13px] text-amber-100/90">
            {decision.risk_flags.map((f) => <li key={f}>· {FLAG_KO[f] ?? f}</li>)}
          </ul>
        </details>
      )}
    </section>
  );
}

/** Reports and debate lines start with an English speaker tag ("Bull Analyst: "); drop it. */
const stripSpeaker = (text: string) => text.replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "");

/** An agent's summary first (AI), its lookups, and the long original collapsed at the end. */
function AgentBody({ data, agentId, summary, lineShown = false }: { data: Loaded; agentId: string; summary?: ReturnType<typeof summarizeAgents>[string]; lineShown?: boolean }) {
  const full = data.reports.reports[agentId];
  const line = data.briefing?.agents[agentId];
  const points = data.briefing?.agent_points?.[agentId] ?? [];
  return (
    <div className="flex flex-col gap-2">
      {summary && (
        <p className="text-xs text-[var(--muted)]">
          {({ done: "완료", failed: "실패", running: "진행 중", pending: "대기", skipped: "이번 분석에 참여하지 않음" })[summary.status]}
          {summary.turns > 1 ? ` · ${summary.turns}번 발언` : ""} · {formatDuration(summary.durationMs)}
          {summary.lookups.length > 0 ? ` · 🔍 ${summary.lookups.map((l) => toolNames(l.tools)).join(" → ")}` : ""}
        </p>
      )}
      {summary?.error && <p className="text-sm text-rose-300">{summary.error}</p>}
      {line ? (
        <div className="rounded-lg border border-[#ffd98a44] bg-[#17203a] p-3">
          {!lineShown && <p className="font-semibold leading-snug text-[#fff3d6]">{humanizeTickers(line)}</p>}
          {points.length > 0 && (
            <ul className={`${lineShown ? "" : "mt-2"} space-y-1.5 text-sm leading-relaxed`}>
              {points.map((x) => <li key={x} className="flex gap-2"><span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[#ffd98a]" /><span>{humanizeTickers(x)}</span></li>)}
            </ul>
          )}
          <p className="mt-2 text-[10px] text-[var(--muted)]">AI 요약 · 이 직원의 보고서 기준</p>
        </div>
      ) : summary?.status !== "skipped" && (
        <p className="text-xs text-[var(--muted)]">이 실행에는 아직 요약이 없어 원문을 보여 줍니다.</p>
      )}
      {full || summary?.summary ? (
        <details open={!line} className="text-sm">
          <summary className="cursor-pointer text-xs text-[var(--muted)]">{full ? "원문 보기" : "원문 보기 (앞부분 600자만 저장됨)"}</summary>
          <div className="mt-2"><Markdown text={humanizeTickers(stripSpeaker(full || summary!.summary))} /></div>
        </details>
      ) : summary?.status !== "skipped" && <p className="text-sm text-[var(--muted)]">보고서가 없습니다.</p>}
    </div>
  );
}

const TEAMS: { title: string; agents: string[] }[] = [
  { title: "분석팀", agents: ["market_analyst", "news_analyst", "fundamentals_analyst", "sentiment_analyst"] },
  { title: "리서치 (강세 vs 약세)", agents: ["bull_researcher", "bear_researcher", "research_manager"] },
  { title: "실행", agents: ["trader"] },
  { title: "리스크 검토", agents: ["risk_aggressive", "risk_conservative", "risk_neutral"] },
  { title: "최종 결정", agents: ["portfolio_manager"] },
];

/**
 * Agents grouped by team in working order, each with its one-line conclusion. Desktop: selecting
 * opens the side panel. Phones: the agent expands in place (no jump to the bottom of the page).
 */
function ReportsTab({ data, agents, selected, onSelect }: { data: Loaded; agents: ReturnType<typeof summarizeAgents>; selected: string; onSelect: (id: string) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const skipped = REPORT_AGENTS.filter((id) => agents[id]?.status === "skipped");
  return (
    <div className="space-y-4">
      {TEAMS.map((team) => {
        const members = team.agents.filter((id) => agents[id]?.status !== "skipped");
        if (members.length === 0) return null;
        return (
          <div key={team.title}>
            <h3 className="mb-1.5 text-xs font-semibold text-[var(--muted)]">{team.title}</h3>
            <ul className="grid gap-1.5 lg:grid-cols-2">
              {members.map((id) => {
                const line = data.briefing?.agents[id];
                const isOpen = open === id;
                return (
                  <li key={id} className={`rounded-lg border ${isOpen ? "border-[#ffd98a88] bg-[#141f38]" : selected === id ? "border-[var(--line)] xl:border-[#ffd98a]" : "border-[var(--line)]"}`}>
                    <button onClick={() => { onSelect(id); setOpen(isOpen ? null : id); }} aria-expanded={isOpen}
                            className="flex w-full items-start gap-2 px-3 py-2.5 text-left">
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold">{agentName(id)}</span>
                        {line && <span className="mt-0.5 block text-[13px] leading-snug text-[#c7d7ee]">{humanizeTickers(line)}</span>}
                      </span>
                      <span aria-hidden="true" className="mt-0.5 text-xs text-[var(--muted)] xl:hidden">{isOpen ? "▲" : "▼"}</span>
                    </button>
                    {isOpen && (
                      <div className="border-t border-[var(--line)] px-3 py-2 xl:hidden">
                        <AgentBody data={data} agentId={id} summary={agents[id]} lineShown />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
      {skipped.length > 0 && (
        <p className="text-xs text-[var(--muted)]">이번 분석에 참여하지 않음: {skipped.map((id) => agentName(id)).join(", ")}</p>
      )}
    </div>
  );
}

function snapshotValue(s: Snapshot): string {
  const p = s.payload;
  if (s.kind === "price_bar") return `종가 ${Number(p.close).toLocaleString("ko-KR")} ${s.currency ?? ""}`;
  if (s.kind === "disclosure") return `${String(p.report_nm ?? "공시")}${p.flr_nm ? ` · ${String(p.flr_nm)}` : ""}`;
  return String(p.title ?? p.headline ?? s.kind);
}

const KIND_KO: Record<string, string> = {
  price_bar: "시세", disclosure: "공시", news: "뉴스", quote: "호가", fundamentals: "재무",
};

const shortDate = (iso: string) => new Date(iso).toLocaleDateString("ko-KR", {
  timeZone: "Asia/Seoul", month: "numeric", day: "numeric" });

function EvidenceTab({ run, snapshots }: { run: RunDetail; snapshots: Snapshot[] }) {
  const gaps = [...new Set(run.coverage_gaps.map(plainGap))];
  const kinds = [...new Set(snapshots.map((s) => s.kind))];
  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-[var(--muted)]">분석 시점({kst(run.as_of)})보다 <b>먼저 공개된</b> 데이터만 위원회에 넘겼습니다. AI가 분석 중 스스로 찾아본 자료(🔍)는 여기에 없습니다.</p>
      {gaps.length > 0 && (
        <div className="rounded-lg border border-amber-700/60 bg-amber-950/20 p-3">
          <div className="mb-1 text-xs font-semibold text-amber-200">구하지 못한 데이터</div>
          <ul className="space-y-0.5 text-[13px]">{gaps.map((g) => <li key={g}>· {g}</li>)}</ul>
          <details className="mt-1 text-[11px] text-[var(--muted)]">
            <summary className="cursor-pointer">기술적 원문</summary>
            <ul className="mt-1 space-y-1 break-all">{run.coverage_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
          </details>
        </div>
      )}
      {kinds.map((kind) => {
        const items = snapshots.filter((s) => s.kind === kind);
        return (
          <details key={kind} open={kind === "disclosure"} className="rounded-lg border border-[var(--line)]">
            <summary className="cursor-pointer px-3 py-2 font-semibold">{KIND_KO[kind] ?? kind} {items.length}건
              <span className="ml-2 text-xs font-normal text-[var(--muted)]">{items[0]?.source}{items[0]?.demo ? " (DEMO)" : ""}</span></summary>
            <ul className="divide-y divide-[var(--line)]/60 border-t border-[var(--line)]">
              {[...items].reverse().map((s) => (
                <li key={s.id} className="flex items-start gap-3 px-3 py-2">
                  <span className="w-12 shrink-0 text-xs text-[var(--muted)]">{shortDate(s.observed_at)}</span>
                  <span className="min-w-0 flex-1 text-[13px]">{snapshotValue(s)}
                    <span className="block text-[11px] text-[var(--muted)]">공개 {kst(s.available_at)}</span></span>
                  {s.source_url && <a className="shrink-0 text-xs underline" href={s.source_url} target="_blank" rel="noopener noreferrer">원문</a>}
                </li>
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

function FactsTab({ run, decision }: { run: RunDetail; decision: Decision | null }) {
  const rows: [string, string][] = [
    ["실행 ID", run.id],
    ["종목", INSTRUMENT_KO[run.instrument_id] ?? run.instrument_id],
    ["종류", run.demo ? "DEMO (합성 데이터)" : "실제 분석 (TradingAgents)"],
    ["시작 방식", run.trigger === "schedule" ? `매일 자동 (${run.schedule_slot ?? ""})` : "수동"],
    ["분석 기준 시각", kst(run.as_of)],
    ["상태", `${PHASE_KO[run.status] ?? run.status}${run.error_code ? ` · ${run.error_code}` : ""}`],
    ["걸린 시간", formatDuration(run.latency_ms ?? 0)],
    ["엔진", run.engine_version ?? "—"],
    ["모델·설정", decision?.model_version ?? "—"],
    ["설정 해시", run.config_hash ?? "—"],
    ...tokenTotals(run.token_usage).map(({ model, tokens }): [string, string] =>
      [`토큰 (${model})`, tokens.toLocaleString("ko-KR")]),
  ];
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => [<dt key={`${k}-k`} className="text-[var(--muted)]">{k}</dt>, <dd key={`${k}-v`} className="break-all">{v}</dd>])}
    </dl>
  );
}
