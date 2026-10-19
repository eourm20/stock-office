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
import { debateTranscript, FLOW_NODES, formatDuration, summarizeAgents, tokenTotals } from "./model";

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

  /** Select an agent; on one-column (phone) layouts the panel is below, so bring it into view. */
  const selectAndShow = useCallback((id: string) => {
    setSelected(id);
    if (window.matchMedia("(max-width: 1279px)").matches) {
      requestAnimationFrame(() => document.getElementById("agent-panel")?.scrollIntoView({ behavior: "smooth" }));
    }
  }, []);

  const agents = useMemo(() => summarizeAgents(data?.events ?? [],
    data ? FINISHED.has(data.run.status) : false), [data]);
  const debate = useMemo(() => debateTranscript(data?.events ?? []), [data]);

  return (
    <main className="flex min-h-screen flex-col">
      <NavBar><StartControls onStarted={(id) => router.push(`/office?run=${id}`)} /></NavBar>

      <section className="flex gap-2 overflow-x-auto border-b border-[var(--line)] px-4 py-3" aria-label="종목별 최신 결정">
        {summary.map((s) => {
          const id = s.active_run_id ?? s.latest?.run_id;
          const active = id && id === resolved;
          return (
            <Link key={s.instrument_id} href={id ? `/analysis/${id}` : "/"}
                  className={`min-w-52 rounded-lg border p-3 text-left ${active ? "border-[#ffd98a] bg-[#1d2944]" : "border-[var(--line)] bg-[var(--panel)]"}`}>
              <div className="text-sm font-semibold">{INSTRUMENT_KO[s.instrument_id] ?? s.name ?? s.instrument_id}</div>
              {s.active_run_id ? <div className="mt-1 text-sky-300">● 회의 중</div>
                : s.latest ? (
                  <div className="mt-1 flex items-baseline gap-2">
                    <span className={`text-xl font-bold ${ACTION_COLOR[s.latest.action] ?? ""}`}>{ACTION_KO[s.latest.action]?.label ?? s.latest.action}</span>
                    <span className="text-xs text-[var(--muted)]">{timeAgo(s.latest.decided_at)} · 제안만</span>
                  </div>
                ) : <div className="mt-1 text-xs text-[var(--muted)]">아직 결정 없음</div>}
            </Link>
          );
        })}
      </section>

      {error && <p role="alert" className="mx-4 mt-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!resolved && !error && <p className="p-6 text-[var(--muted)]">아직 분석 기록이 없습니다. 오른쪽 위에서 새 분석을 시작해 보세요.</p>}
      {resolved && !data && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {data && !FINISHED.has(data.run.status) && (
        <div className="m-4 rounded-lg border border-sky-700 bg-sky-950/40 p-4">
          <p className="font-semibold text-sky-200">이 회의는 지금 진행 중입니다 ({PHASE_KO[data.run.status] ?? data.run.status}).</p>
          <p className="mt-1 text-sm text-[var(--muted)]">끝나면 이 화면이 자동으로 결과를 보여 줍니다. 진행 과정을 실시간으로 보려면
            {" "}<Link className="underline" href={`/office?run=${data.run.id}`}>사무실에서 보기</Link>.</p>
        </div>
      )}

      {data && FINISHED.has(data.run.status) && (
        <div className="grid flex-1 gap-4 p-4 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="flex min-w-0 flex-col gap-4">
            <DecisionCard run={data.run} decision={data.decision} />
            {data.briefing && <BriefingCard briefing={data.briefing} />}
            <section className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
              <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
                <h2 className="font-semibold">위원회 흐름</h2>
                <p className="text-xs text-[var(--muted)]"><span className="hidden md:inline">왼쪽에서 오른쪽 순서로 일했습니다. 칸을 누르면 오른쪽에 그 직원의 보고서가 나옵니다.{" "}</span>
                  <Link className="underline" href={`/office?run=${data.run.id}`}>사무실 애니메이션으로 다시보기</Link></p>
              </div>
              <div className="hidden md:block">
                <FlowGraph agents={agents} action={data.decision?.action ?? null} selected={selected}
                           onSelect={(id) => { setSelected(id); }} />
              </div>
              <p className="text-sm text-[var(--muted)] md:hidden">큰 화면에서는 여기에 흐름 그래프가 나옵니다. 휴대폰에서는 아래 목록에서 직원을 눌러 보고서를 보세요.</p>
            </section>
            <section className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
              <div role="tablist" aria-label="세부 내용" className="flex gap-1 overflow-x-auto border-b border-[var(--line)] p-2">
                {([["reports", "보고서"], ["debate", `토론 (${debate.length})`],
                   ["evidence", `근거 데이터 (${data.snapshots.length})`], ["facts", "실행 정보"]] as [Tab, string][])
                  .map(([t, label]) => (
                    <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}
                            className={`shrink-0 whitespace-nowrap rounded px-3 py-1 text-sm ${tab === t ? "bg-[var(--accent)] text-black" : "hover:bg-[#1d2944]"}`}>{label}</button>
                  ))}
              </div>
              <div className="p-3">
                {tab === "reports" && <ReportsTab data={data} agents={agents} selected={selected} onSelect={selectAndShow} />}
                {tab === "debate" && <DebateChat lines={debate} gists={data.briefing?.debate ?? {}}
                                                 fullTranscripts={data.reports.reports} />}
                {tab === "evidence" && <EvidenceTab run={data.run} snapshots={data.snapshots} />}
                {tab === "facts" && <FactsTab run={data.run} decision={data.decision} />}
              </div>
            </section>
          </div>
          <div id="agent-panel" className="min-w-0 scroll-mt-2"><AgentPanel data={data} agentId={selected} summary={agents[selected]} /></div>
        </div>
      )}
    </main>
  );
}

function StartControls({ onStarted }: { onStarted: (runId: string) => void }) {
  const [instrument, setInstrument] = useState("US:NASDAQ:NVDA");
  const [engine, setEngine] = useState<"demo" | "tradingagents">("demo");
  const [busy, setBusy] = useState(false);
  const start = async () => {
    if (engine === "tradingagents" && !window.confirm(
      `${INSTRUMENT_KO[instrument] ?? instrument}: 실제 분석은 OpenAI API 비용이 발생합니다 (실측 약 $0.05/회, 3~4분). 실행할까요?`)) return;
    setBusy(true);
    try { onStarted(await startRun(instrument, engine)); } catch (e) { window.alert((e as Error).message); } finally { setBusy(false); }
  };
  return (
    <div className="flex w-full flex-wrap items-center gap-1 sm:ml-auto sm:w-auto">
      <select aria-label="종목" className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={instrument} onChange={(e) => setInstrument(e.target.value)}>
        {Object.entries(INSTRUMENT_KO).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
      </select>
      <select aria-label="분석 종류" className="min-w-0 flex-1 rounded bg-[var(--panel)] px-2 py-1 sm:flex-none" value={engine} onChange={(e) => setEngine(e.target.value as "demo" | "tradingagents")}>
        <option value="demo">DEMO (무료)</option><option value="tradingagents">실제 분석 (유료)</option>
      </select>
      <button disabled={busy} onClick={() => void start()} className="shrink-0 whitespace-nowrap rounded bg-[var(--mint)] px-3 py-1 font-semibold text-black disabled:opacity-50">새 분석 시작</button>
    </div>
  );
}

function DecisionCard({ run, decision }: { run: RunDetail; decision: Decision | null }) {
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
      <div className="flex flex-wrap items-center gap-2 text-sm text-[var(--muted)]">
        <span className="font-semibold text-[var(--ink)]">{name}</span>
        <span>· {kst(decision.created_at)} 결정</span>
        {run.trigger === "schedule" && <span className="rounded bg-[#1e3a2f] px-1.5 text-xs text-[var(--mint)]">매일 자동 분석</span>}
        {decision.demo && <span className="rounded bg-amber-400 px-1.5 text-xs font-bold text-black">DEMO · 합성 데이터, 분석 결과 아님</span>}
        <span className="rounded border border-[var(--line)] px-1.5 text-xs">{decision.execution === "PROPOSED_ONLY" ? "제안만 · 주문 없음" : decision.execution}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-baseline gap-3">
        <span className={`text-4xl font-bold ${ACTION_COLOR[decision.action] ?? ""}`}>{a?.label ?? decision.action}</span>
        {decision.engine_rating && <span className="text-[var(--muted)]">AI 등급: {RATING_KO[decision.engine_rating] ?? decision.engine_rating}</span>}
      </div>
      <p className="mt-1">{a?.plain}</p>
      {decision.action === "REVIEW" && <p className="mt-1 text-amber-300">근거가 부족하거나 결론을 읽을 수 없어 사람이 확인해야 합니다.</p>}
      <p className="mt-1 text-xs text-[var(--muted)]">AI 위원회의 1회 의견일 뿐, 검증된 투자 신호가 아닙니다. 수익을 보장하지 않습니다.</p>
      {decision.risk_flags.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-sm text-amber-200">
          {decision.risk_flags.map((f) => <li key={f}>⚠ {FLAG_KO[f] ?? f} <span className="text-xs text-[var(--muted)]">({f})</span></li>)}
        </ul>
      )}
    </section>
  );
}

/** The one-page briefing: an AI summary of this run's stored reports, read first. */
function BriefingCard({ briefing }: { briefing: Briefing }) {
  const block = (title: string, items: string[], tone: string) => items.length > 0 && (
    <div>
      <h3 className={`mb-1 text-xs font-semibold ${tone}`}>{title}</h3>
      <ul className="space-y-1 text-sm">{items.map((x) => <li key={x} className="flex gap-1.5"><span aria-hidden="true">·</span><span>{humanizeTickers(x)}</span></li>)}</ul>
    </div>
  );
  return (
    <section className="rounded-lg border border-[#ffd98a55] bg-[#17203a] p-4" aria-label="한눈에 보기">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">한눈에 보기</h2>
        <span className="rounded border border-[var(--line)] px-1.5 text-[11px] text-[var(--muted)]"
              title={`모델: ${briefing.model}`}>AI 요약 · 이번 회의 보고서만 사용</span>
      </div>
      <p className="mb-3 text-[15px] font-semibold text-[#fff3d6]">{humanizeTickers(briefing.headline)}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {block("핵심 근거", briefing.key_reasons, "text-emerald-300")}
        {block("주요 위험", briefing.risks, "text-rose-300")}
        {block("다음에 확인할 것", briefing.watch_next, "text-sky-300")}
      </div>
    </section>
  );
}

/** Reports and debate lines start with an English speaker tag ("Bull Analyst: "); drop it. */
const stripSpeaker = (text: string) => text.replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "");

function AgentPanel({ data, agentId, summary }: { data: Loaded; agentId: string; summary?: ReturnType<typeof summarizeAgents>[string] }) {
  const full = data.reports.reports[agentId];
  const line = data.briefing?.agents[agentId];
  return (
    <aside className="flex min-w-0 flex-col gap-2 rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3 xl:sticky xl:top-2 xl:max-h-[calc(100vh-1rem)] xl:overflow-y-auto">
      <h2 className="text-lg font-semibold">{agentName(agentId)}</h2>
      {summary && (
        <p className="text-xs text-[var(--muted)]">
          {({ done: "완료", failed: "실패", running: "진행 중", pending: "대기", skipped: "이번 분석에 참여하지 않음" })[summary.status]}
          {summary.turns > 1 ? ` · ${summary.turns}번 발언` : ""} · 걸린 시간 {formatDuration(summary.durationMs)}
        </p>
      )}
      {summary?.error && <p className="text-sm text-rose-300">{summary.error}</p>}
      {summary && summary.lookups.length > 0 && (
        <div className="rounded border border-amber-700/60 bg-amber-950/20 p-2 text-xs">
          <div className="mb-1 font-semibold text-amber-200">🔍 찾아본 자료 (도구 이름만 기록)</div>
          <ol className="list-decimal space-y-0.5 pl-4">
            {summary.lookups.map((l) => <li key={l.round}>{toolNames(l.tools)}</li>)}
          </ol>
        </div>
      )}
      {line && (
        <p className="rounded border border-[#ffd98a55] bg-[#17203a] p-2 text-sm">
          <span className="mr-1 text-[11px] text-[var(--muted)]">AI 요약</span>{humanizeTickers(line)}
        </p>
      )}
      {full || summary?.summary ? (
        <details open={!line} className="text-sm">
          <summary className="cursor-pointer text-[var(--muted)]">{full ? "보고서 원문" : "보고서 원문 (앞부분 600자)"}</summary>
          <div className="mt-2"><Markdown text={humanizeTickers(stripSpeaker(full || summary!.summary))} /></div>
          {!full && <p className="mt-1 text-xs text-[var(--muted)]">이 실행은 전체 보고서 저장 기능이 생기기 전 기록이라 앞부분만 있습니다.</p>}
        </details>
      ) : <p className="text-sm text-[var(--muted)]">보고서가 없습니다.</p>}
    </aside>
  );
}

function ReportsTab({ data, agents, selected, onSelect }: { data: Loaded; agents: ReturnType<typeof summarizeAgents>; selected: string; onSelect: (id: string) => void }) {
  return (
    <ul className="grid gap-1 sm:grid-cols-2 lg:grid-cols-3">
      {REPORT_AGENTS.map((id) => {
        const s = agents[id];
        const has = Boolean(data.reports.reports[id] || s?.summary);
        return (
          <li key={id}>
            <button onClick={() => onSelect(id)} disabled={!has}
                    className={`w-full rounded border px-3 py-2 text-left text-sm disabled:opacity-40 ${selected === id ? "border-[#ffd98a] bg-[#1d2944]" : "border-[var(--line)] hover:bg-[#1d2944]"}`}>
              <span className="font-semibold">{agentName(id)}</span>
              <span className="ml-2 text-xs text-[var(--muted)]">{s?.status === "skipped" ? "참여 안 함" : has ? "보고서 보기 →" : "없음"}</span>
              {data.briefing?.agents[id] && <span className="mt-0.5 block text-xs text-[#c7d7ee]">{humanizeTickers(data.briefing.agents[id]!)}</span>}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function snapshotValue(s: Snapshot): string {
  const p = s.payload;
  if (s.kind === "price_bar") return `종가 ${Number(p.close).toLocaleString("ko-KR")} ${s.currency ?? ""} (${String(p.date ?? "")})`;
  if (s.kind === "disclosure") return `${String(p.report_nm ?? "공시")}${p.flr_nm ? ` · ${String(p.flr_nm)}` : ""}`;
  return String(p.title ?? p.headline ?? s.kind);
}

function EvidenceTab({ run, snapshots }: { run: RunDetail; snapshots: Snapshot[] }) {
  return (
    <div className="space-y-3 text-sm">
      <p className="text-[var(--muted)]">Stock Office가 분석 시점({kst(run.as_of)}) 이전에 <b>공개된</b> 데이터만 골라 위원회에 넘긴 근거입니다.
        AI가 분석 중에 스스로 찾아본 자료(🔍)는 여기에 저장되지 않습니다.</p>
      {run.coverage_gaps.length > 0 && (
        <div className="rounded border border-amber-700/60 bg-amber-950/20 p-2">
          <div className="font-semibold text-amber-200">구하지 못한 데이터</div>
          <ul className="list-disc pl-5 text-xs">{run.coverage_gaps.map((g) => <li key={g}>{g}</li>)}</ul>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-xs">
          <thead><tr className="border-b border-[var(--line)] text-left text-[var(--muted)]">
            <th className="py-1">종류</th><th>출처</th><th>내용</th><th>발생 시각</th><th>공개 시각</th><th>링크</th></tr></thead>
          <tbody>
            {snapshots.map((s) => (
              <tr key={s.id} className="border-b border-[var(--line)]/50">
                <td className="py-1">{({ price_bar: "시세", disclosure: "공시", news: "뉴스", quote: "호가", fundamentals: "재무" } as Record<string, string>)[s.kind] ?? s.kind}</td>
                <td>{s.source}{s.demo ? " (DEMO)" : ""}</td>
                <td>{snapshotValue(s)}</td>
                <td>{kst(s.observed_at)}</td>
                <td>{kst(s.available_at)}</td>
                <td>{s.source_url ? <a className="underline" href={s.source_url} target="_blank" rel="noopener noreferrer">원문</a> : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
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
