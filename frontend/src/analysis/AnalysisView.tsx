"use client";

/**
 * Building blocks of a meeting's minutes (decision card, team reports, sources, run facts).
 * The page itself is MinutesView.tsx.
 */
import { useState } from "react";
import Markdown from "../app/Markdown";
import type { Briefing, Decision, RunDetail, Snapshot } from "../lib/api";
import { INSTRUMENT_KO } from "../office/auto";
import { ACTION_KO, FLAG_KO, RATING_KO } from "../office/explain";
import { agentName, humanizeTickers, PHASE_KO, toolNames } from "../office/names";
import type { RunEvent } from "../types";
import { FLOW_NODES, formatDuration, plainGap, summarizeAgents, tokenTotals } from "./model";

export const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};
export const FINISHED = new Set(["COMPLETED", "FAILED", "INSUFFICIENT_DATA"]);
const REPORT_AGENTS = FLOW_NODES.map((n) => n.id)
  .filter((id) => !["decision", "data_collector", "memory_log"].includes(id));

export const kst = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", {
  timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit",
}) : "—");

export interface Loaded {
  run: RunDetail;
  events: RunEvent[];
  decision: Decision | null;
  snapshots: Snapshot[];
  reports: { available: boolean; reports: Record<string, string> };
  briefing: Briefing | null;
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
export function DecisionCard({ run, decision, briefing }: { run: RunDetail; decision: Decision | null; briefing: Briefing | null }) {
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
export function AgentBody({ data, agentId, summary, lineShown = false }: { data: Loaded; agentId: string; summary?: ReturnType<typeof summarizeAgents>[string]; lineShown?: boolean }) {
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
 * Agents grouped by team in working order, each with its one-line conclusion; tapping one expands
 * its key points and the collapsed original in place.
 */
export function ReportsTab({ data, agents }: { data: Loaded; agents: ReturnType<typeof summarizeAgents> }) {
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
                  <li key={id} className={`rounded-lg border ${isOpen ? "border-[#ffd98a88] bg-[#141f38]" : "border-[var(--line)]"}`}>
                    <button onClick={() => setOpen(isOpen ? null : id)} aria-expanded={isOpen}
                            className="flex w-full items-start gap-2 px-3 py-2.5 text-left">
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-semibold">{agentName(id)}</span>
                        {line && <span className="mt-0.5 block text-[13px] leading-snug text-[#c7d7ee]">{humanizeTickers(line)}</span>}
                      </span>
                      <span aria-hidden="true" className="mt-0.5 text-xs text-[var(--muted)]">{isOpen ? "▲" : "▼"}</span>
                    </button>
                    {isOpen && (
                      <div className="border-t border-[var(--line)] px-3 py-2">
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

export function EvidenceTab({ run, snapshots }: { run: RunDetail; snapshots: Snapshot[] }) {
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

export function FactsTab({ run, decision }: { run: RunDetail; decision: Decision | null }) {
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
