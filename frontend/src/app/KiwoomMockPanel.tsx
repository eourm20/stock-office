"use client";

import { useEffect, useState } from "react";
import { getKiwoomMock, type KiwoomMockStatus, type MockAccount } from "../lib/api";
import { kstDateTime, money, pnlTone } from "../inbox/model";
import type { Market } from "../lib/market";

const TITLE: Record<"KR" | "US", string> = { KR: "국내 모의 계좌", US: "해외 모의 계좌" };

/** Kiwoom 모의투자 accounts, read-only (step K1): deposits, holdings, today's fills. One market or both. */
export default function KiwoomMockPanel({ market }: { market?: Market }) {
  const [status, setStatus] = useState<KiwoomMockStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = (refresh: boolean) => {
    setBusy(true);
    getKiwoomMock(refresh).then((s) => { setStatus(s); setError(null); })
      .catch((e: Error) => setError(e.message)).finally(() => setBusy(false));
  };
  useEffect(() => load(false), []);

  if (error) return <p className="text-sm text-rose-300">불러오지 못했습니다: {error}</p>;
  if (!status) return <p className="text-sm text-[var(--muted)]">{busy ? "키움 모의 서버에 조회 중… (최대 10초)" : "불러오는 중…"}</p>;
  const shown: Market[] = market ? [market] : ["KR", "US"];
  const checked = shown.map((m) => status.accounts[m]).find((a) => a?.checked_at)?.checked_at;
  return (
    <div className="space-y-3">
      {shown.map((m) => (
        <AccountBlock key={m} title={TITLE[m]} configured={status.configured[m]} acc={status.accounts[m]} />
      ))}
      <div className="flex items-center justify-between gap-2 text-[11px] text-[var(--muted)]">
        <span>조회만 · 모의 서버 {status.server.replace("https://", "")} · 주문 연결은 다음 단계(K2){checked ? ` · ${kstDateTime(checked)} 확인` : ""}</span>
        <button disabled={busy} onClick={() => load(true)} className="shrink-0 underline disabled:opacity-50">{busy ? "조회 중…" : "새로 조회"}</button>
      </div>
    </div>
  );
}

function AccountBlock({ title, configured, acc }: { title: string; configured: boolean; acc: MockAccount | null }) {
  if (!configured || !acc) {
    return (
      <div className="rounded-lg border border-[var(--line)] p-3 text-sm">
        <div className="font-semibold">{title}</div>
        <p className="text-xs text-[var(--muted)]">모의투자 앱키가 서버에 없습니다.</p>
      </div>
    );
  }
  const cur = acc.currency;
  return (
    <div className="rounded-lg border border-[var(--line)] p-3 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-semibold">{title} <span className="text-xs font-normal text-[var(--muted)]">({cur})</span></span>
        <span className={`rounded px-1.5 text-[11px] ${acc.ok ? "bg-emerald-900/60 text-emerald-200" : "bg-rose-900/60 text-rose-200"}`}>
          {acc.ok ? "연결됨" : "오류"}
        </span>
      </div>
      {!acc.ok ? <p className="mt-1 text-xs text-rose-300">{acc.error}</p> : (
        <>
          <dl className="mt-2 grid grid-cols-1 gap-y-0.5 text-[13px] sm:grid-cols-2 sm:gap-x-4">
            <Fact label="예수금" value={acc.cash === null ? "—" : money(acc.cash, cur)} />
            <Fact label="주문 가능" value={acc.orderable === null ? "—" : money(acc.orderable, cur)} />
            <Fact label="보유 평가" value={acc.total_value === null ? "—" : money(acc.total_value, cur)} />
            <Fact label="보유 · 오늘 체결" value={`${acc.holdings.length}종목 · ${acc.fills_today ?? "—"}건`} />
          </dl>
          {acc.holdings.length > 0 && (
            <ul className="mt-2 divide-y divide-[var(--line)] text-[13px]">
              {acc.holdings.map((h) => (
                <li key={h.code} className="flex justify-between gap-2 py-1">
                  <span>{h.name || h.code} <span className="text-xs text-[var(--muted)]">{h.qty ?? "?"}주 · 평균 {h.avg_price ? money(h.avg_price, cur) : "—"}</span></span>
                  <span className={pnlTone(h.pnl ?? 0)}>{h.value ? money(h.value, cur) : "—"}{h.pnl_pct ? ` (${h.pnl_pct}%)` : ""}</span>
                </li>
              ))}
            </ul>
          )}
          {acc.notes.length > 0 && <p className="mt-1 text-[11px] text-amber-200">{acc.notes.join(" · ")}</p>}
        </>
      )}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd className="font-medium">{value}</dd>
    </div>
  );
}
