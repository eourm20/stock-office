"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { getRecords, type RecordRow } from "../../lib/api";
import { approvalNote, groupRecordsByDay, STATUS_KO, STATUS_TONE } from "../../inbox/model";
import { MARKET_KO, marketOf, useMarket } from "../../lib/market";
import { ACTION_KO } from "../../office/explain";
import { humanizeTickers, PHASE_KO } from "../../office/names";
import NavBar from "../NavBar";

const ACTION_BADGE: Record<string, string> = {
  BUY: "bg-emerald-900/60 text-emerald-200", SELL: "bg-rose-900/60 text-rose-200",
  HOLD: "bg-sky-900/60 text-sky-200", REVIEW: "bg-amber-900/60 text-amber-200",
};
const time = (iso: string) => new Date(iso).toLocaleTimeString("ko-KR", { timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit", hour12: false });

/** 기록: one market's meeting minutes, by day, with each decision and what the CEO did with it. */
export default function RecordsPage() {
  const { market } = useMarket();
  const [rows, setRows] = useState<RecordRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stock, setStock] = useState("all");
  const [action, setAction] = useState("all");
  const [demo, setDemo] = useState(false);

  useEffect(() => {
    getRecords().then(setRows).catch((e: Error) => setError(`서버에 연결할 수 없습니다: ${e.message}`));
  }, []);

  const mine = useMemo(() => (rows ?? []).filter((r) => marketOf(r.instrument_id) === market), [rows, market]);
  const stocks = useMemo(() => [...new Map(mine.map((r) => [r.instrument_id, r.name])).entries()], [mine]);
  useEffect(() => setStock("all"), [market]);
  const filtered = mine.filter((r) => (stock === "all" || r.instrument_id === stock) &&
    (action === "all" || r.action === action) && (demo || !r.demo));
  const days = groupRecordsByDay(filtered);

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col">
      <NavBar />
      <div className="flex flex-wrap items-center gap-2 p-3">
        <h1 className="mr-auto text-lg font-bold">{MARKET_KO[market]} 회의록</h1>
        <select aria-label="종목" value={stock} onChange={(e) => setStock(e.target.value)} className="rounded bg-[var(--panel)] px-2 py-1 text-sm">
          <option value="all">전체 종목</option>
          {stocks.map(([id, name]) => <option key={id} value={id}>{name}</option>)}
        </select>
        <select aria-label="결정" value={action} onChange={(e) => setAction(e.target.value)} className="rounded bg-[var(--panel)] px-2 py-1 text-sm">
          <option value="all">전체 결정</option>
          {Object.entries(ACTION_KO).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
        </select>
        <label className="flex items-center gap-1 text-xs text-[var(--muted)]">
          <input type="checkbox" checked={demo} onChange={(e) => setDemo(e.target.checked)} /> 연습(DEMO) 포함
        </label>
      </div>
      {error && <p role="alert" className="mx-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!rows && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}
      {rows && days.length === 0 && <p className="p-6 text-sm text-[var(--muted)]">조건에 맞는 회의록이 없습니다.</p>}

      <div className="flex flex-col gap-4 px-3 pb-6">
        {days.map((d) => (
          <section key={d.day} aria-label={d.label}>
            <h2 className="mb-1.5 text-xs font-semibold text-[var(--muted)]">{d.label}</h2>
            <ul className="divide-y divide-[var(--line)] overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--panel)]">
              {d.rows.map((r) => (
                <li key={r.run_id}>
                  <Link href={`/records/${r.run_id}`} className="flex items-start gap-3 px-3 py-2.5 hover:bg-[#1d2944]">
                    <span className="w-11 shrink-0 pt-0.5 text-xs text-[var(--muted)]">{time(r.requested_at)}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5 text-sm">
                        <span className="font-semibold">{r.name}</span>
                        {r.action ? <span className={`rounded px-1.5 text-xs ${ACTION_BADGE[r.action] ?? ""}`}>{ACTION_KO[r.action]?.label ?? r.action}</span>
                          : <span className="rounded px-1.5 text-xs text-[var(--muted)]">{PHASE_KO[r.status] ?? r.status}</span>}
                        {r.trigger === "schedule" && <span className="text-[11px] text-[var(--muted)]">정기</span>}
                        {r.demo && <span className="rounded bg-amber-400 px-1 text-[10px] font-bold text-black">DEMO</span>}
                      </span>
                      {r.headline && <span className="mt-0.5 block line-clamp-2 text-[12px] leading-snug text-[#c7d7ee]">{humanizeTickers(r.headline)}</span>}
                    </span>
                    {r.approval && (
                      <span className="flex shrink-0 flex-col items-end gap-0.5">
                        <span className={`rounded border px-1.5 text-[11px] ${STATUS_TONE[r.approval]}`}>{STATUS_KO[r.approval]}</span>
                        {approvalNote(r.approval_auto, r.paper, r.ceo_opinion) && (
                          <span className="text-[10px] text-[var(--muted)]">{approvalNote(r.approval_auto, r.paper, r.ceo_opinion)}</span>
                        )}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </main>
  );
}
