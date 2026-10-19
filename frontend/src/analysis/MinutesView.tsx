"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import NavBar from "../app/NavBar";
import { fetchRunEvents, getBriefing, getDecision, getInbox, getReports, getRunDetail, getSnapshots,
  getToolResults, type InboxItem, type ToolResult } from "../lib/api";
import { STATUS_KO, STATUS_TONE } from "../inbox/model";
import { INSTRUMENT_KO } from "../office/auto";
import { ACTION_KO } from "../office/explain";
import { humanizeTickers, PHASE_KO } from "../office/names";
import { ACTION_COLOR, DecisionCard, EvidenceTab, FactsTab, FINISHED, kst, type Loaded, ReportsTab }
  from "./AnalysisView";
import DebateChat from "./DebateChat";
import { debateTranscript, formatDuration, summarizeAgents } from "./model";

const FlowGraph = dynamic(() => import("./FlowGraph"), { ssr: false });

const TEAMS: [string, string[]][] = [
  ["분석팀", ["market_analyst", "news_analyst", "fundamentals_analyst", "sentiment_analyst"]],
  ["리서치", ["bull_researcher", "bear_researcher", "research_manager"]],
  ["트레이딩", ["trader"]],
  ["리스크", ["risk_aggressive", "risk_conservative", "risk_neutral"]],
  ["PM", ["portfolio_manager"]],
];
const SECTIONS = [["reports", "부서별 보고"], ["debate", "토론"], ["decision", "결론과 결재"], ["attach", "첨부"]];

/** 회의록: one meeting written up in the order a company records it. */
export default function MinutesView({ runId }: { runId: string }) {
  const [data, setData] = useState<Loaded | null>(null);
  const [doc, setDoc] = useState<InboxItem | null>(null);
  const [toolResults, setToolResults] = useState<ToolResult[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const run = await getRunDetail(runId);
      if (!FINISHED.has(run.status)) {
        setData({ run, events: [], decision: null, snapshots: [], reports: { available: false, reports: {} }, briefing: null });
        return;
      }
      const [events, decision, snapshots, reports, brief, inbox, tools] = await Promise.all([
        fetchRunEvents(runId), getDecision(runId), getSnapshots(runId), getReports(runId), getBriefing(runId),
        getInbox().catch(() => [] as InboxItem[]), getToolResults(runId).catch(() => null)]);
      setToolResults(tools?.available ? tools.results : null);
      setData({ run, events, decision, snapshots, reports, briefing: brief.briefing?.status === "OK" ? brief.briefing : null });
      setDoc(inbox.find((i) => i.run_id === runId) ?? null);
    })().catch((e: Error) => setError(e.message));
  }, [runId]);

  const agents = useMemo(() => summarizeAgents(data?.events ?? [], data ? FINISHED.has(data.run.status) : false), [data]);
  const debate = useMemo(() => debateTranscript(data?.events ?? []), [data]);
  const attended = TEAMS.filter(([, ids]) => ids.some((id) => agents[id] && agents[id]!.status !== "skipped" && agents[id]!.status !== "pending"))
    .map(([team]) => team);

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col">
      <NavBar />
      <div className="px-3 pt-3"><Link href="/records" className="text-sm text-[var(--muted)]">← 기록</Link></div>
      {error && <p role="alert" className="mx-3 mt-2 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!data && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {data && !FINISHED.has(data.run.status) && (
        <div className="m-3 rounded-lg border border-sky-700 bg-sky-950/40 p-4">
          <p className="font-semibold text-sky-200">이 회의는 아직 진행 중입니다 ({PHASE_KO[data.run.status] ?? data.run.status}).</p>
          <p className="mt-1 text-sm"><Link className="underline" href="/office">오피스에서 실시간으로 보기</Link> · 끝나면 회의록이 정리됩니다.</p>
        </div>
      )}

      {data && FINISHED.has(data.run.status) && (
        <>
          <header className="m-3 rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
            <div className="text-[11px] tracking-widest text-[var(--muted)]">회의록</div>
            <h1 className="mt-0.5 text-xl font-bold">{INSTRUMENT_KO[data.run.instrument_id] ?? data.run.instrument_id} 투자 판단 회의</h1>
            <dl className="mt-3 grid grid-cols-[4.5rem_1fr] gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-[var(--muted)]">일시</dt>
              <dd>{kst(data.run.started_at ?? data.run.requested_at)} · {formatDuration(data.run.latency_ms ?? 0)}
                {data.run.trigger === "schedule" ? " · 정기 회의" : " · 소집 회의"}
                {data.run.demo && <span className="ml-1 rounded bg-amber-400 px-1 text-[10px] font-bold text-black">DEMO</span>}</dd>
              <dt className="text-[var(--muted)]">참석</dt>
              <dd>{attended.join(" · ") || "—"}</dd>
              <dt className="text-[var(--muted)]">결론</dt>
              <dd>
                {data.decision ? (
                  <><span className={`font-bold ${ACTION_COLOR[data.decision.action] ?? ""}`}>{ACTION_KO[data.decision.action]?.label ?? data.decision.action}</span>
                    {data.briefing && <span className="ml-1">— {humanizeTickers(data.briefing.headline)}</span>}</>
                ) : `결정 없음 (${PHASE_KO[data.run.status] ?? data.run.status})`}
              </dd>
              <dt className="text-[var(--muted)]">결재</dt>
              <dd>
                {doc ? (
                  <Link href={doc.kind === "approval" ? `/inbox/${doc.id}` : `/inbox/${doc.id}`} className="inline-flex items-center gap-2">
                    <span className={`rounded border px-1.5 text-xs ${STATUS_TONE[doc.status]}`}>{STATUS_KO[doc.status]}</span>
                    <span className="text-xs underline">{doc.title}</span>
                  </Link>
                ) : <span className="text-[var(--muted)]">결재함 문서 없음</span>}
              </dd>
            </dl>
          </header>

          <nav aria-label="회의록 목차" className="sticky top-0 z-10 flex gap-1 overflow-x-auto border-y border-[var(--line)] bg-[#0b1020]/95 px-3 py-2 backdrop-blur">
            {SECTIONS.map(([id, label], i) => (
              <a key={id} href={`#${id}`} className="shrink-0 whitespace-nowrap rounded-full border border-[var(--line)] px-3 py-1 text-xs">{i + 1}. {label}</a>
            ))}
          </nav>

          <div className="flex flex-col gap-6 p-3">
            <Section id="reports" n={1} title="부서별 보고" sub="팀마다 무엇을 봤고 어떻게 판단했는지 (누르면 핵심과 원문)">
              <ReportsTab data={data} agents={agents} />
            </Section>
            <Section id="debate" n={2} title="토론" sub={`발언 ${debate.length}건`}>
              <DebateChat lines={debate} gists={data.briefing?.debate ?? {}} fullTranscripts={data.reports.reports} />
            </Section>
            <Section id="decision" n={3} title="결론과 결재">
              <DecisionCard run={data.run} decision={data.decision} briefing={data.briefing} />
              {doc && (
                <Link href={`/inbox/${doc.id}`} className="mt-2 block rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3 text-sm">
                  📎 {doc.title} <span className={`ml-1 rounded border px-1.5 text-xs ${STATUS_TONE[doc.status]}`}>{STATUS_KO[doc.status]}</span>
                </Link>
              )}
            </Section>
            <Section id="attach" n={4} title="첨부">
              <div className="space-y-2">
                <Attachment title={`출처 데이터 (${data.snapshots.length + (toolResults?.length ?? 0)}건)`}>
                  <EvidenceTab run={data.run} snapshots={data.snapshots} toolResults={toolResults} />
                </Attachment>
                <Attachment title="실행 정보"><FactsTab run={data.run} decision={data.decision} /></Attachment>
                <div className="hidden md:block">
                  <Attachment title="위원회 흐름 (그래프)">
                    <FlowGraph agents={agents} action={data.decision?.action ?? null} selected={null} onSelect={() => {}} />
                  </Attachment>
                </div>
              </div>
            </Section>
          </div>
        </>
      )}
    </main>
  );
}

function Section({ id, n, title, sub, children }: { id: string; n: number; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="scroll-mt-14">
      <h2 className="mb-2 flex items-baseline gap-2"><span className="text-lg font-bold">{n}. {title}</span>
        {sub && <span className="text-xs text-[var(--muted)]">{sub}</span>}</h2>
      {children}
    </section>
  );
}

function Attachment({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <details className="rounded-lg border border-[var(--line)] bg-[var(--panel)]">
      <summary className="cursor-pointer px-3 py-2 text-sm font-semibold">{title}</summary>
      <div className="border-t border-[var(--line)] p-3">{children}</div>
    </details>
  );
}
