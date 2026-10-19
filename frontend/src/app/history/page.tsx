"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { API_BASE, listRuns, type RunSummary } from "../../lib/api";
import { INSTRUMENT_KO } from "../../office/auto";
import { ACTION_KO } from "../../office/explain";
import { PHASE_KO } from "../../office/names";
import NavBar from "../NavBar";

interface Row extends RunSummary { action?: string; rating?: string | null }

const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

/** Every meeting ever held, newest first. Records are kept for later evaluation (Sprint 4). */
export default function HistoryPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const runs = await listRuns();
      const withDecisions = await Promise.all(runs.map(async (r): Promise<Row> => {
        if (r.status !== "COMPLETED") return r;
        const resp = await fetch(`${API_BASE}/api/v1/analysis-runs/${r.id}/decision`);
        if (!resp.ok) return r;
        const d = (await resp.json()) as { action: string; engine_rating: string | null };
        return { ...r, action: d.action, rating: d.engine_rating };
      }));
      setRows(withDecisions);
    })().catch((e: Error) => setError(`API에 연결할 수 없습니다 (${API_BASE}): ${e.message}`));
  }, []);

  return (
    <>
    <NavBar />
    <main className="mx-auto max-w-5xl p-6">
      <h1 className="mb-4 text-xl font-bold">회의 기록</h1>
      <p className="mb-4 text-sm text-[var(--muted)]">
        지금까지 연 모든 회의입니다. <b>실제 분석</b>은 TradingAgents가 실제 데이터로 분석한 기록이고, <b>DEMO</b>는 화면 시험용 가짜 데이터입니다.
        결정은 모두 제안이며 실제 주문은 하지 않았습니다. 시각을 누르면 그 회의의 분석 화면이 열립니다.
      </p>
      {error && <p role="alert" className="rounded bg-rose-900/70 px-3 py-2">{error}</p>}
      {!rows && !error && <p className="text-[var(--muted)]">불러오는 중…</p>}
      {rows && (
        <table className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-[var(--line)] text-left text-[var(--muted)]">
              <th className="py-2">시각 (한국)</th><th>종목</th><th>종류</th><th>상태</th><th>AI 의견</th><th>걸린 시간</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="border-b border-[var(--line)]/60 hover:bg-[var(--panel)]">
                <td className="py-2">
                  <Link href={`/analysis/${r.id}`} className="underline decoration-dotted">
                    {new Date(r.requested_at).toLocaleString("ko-KR", { timeZone: "Asia/Seoul", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </Link>
                </td>
                <td>{INSTRUMENT_KO[r.instrument_id] ?? r.instrument_id}</td>
                <td>{r.engine === "demo"
                  ? <span className="rounded bg-amber-400 px-1.5 text-xs font-bold text-black">DEMO</span>
                  : "실제 분석"}</td>
                <td>{PHASE_KO[r.status] ?? r.status}</td>
                <td className={`font-semibold ${r.action ? ACTION_COLOR[r.action] ?? "" : ""}`}>
                  {r.action ? ACTION_KO[r.action]?.label ?? r.action : "—"}
                </td>
                <td className="text-[var(--muted)]">{r.latency_ms ? `${Math.round(r.latency_ms / 1000)}초` : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
    </>
  );
}
