"use client";

import { useEffect, useState } from "react";
import { getOfficeNow, type OfficeNow } from "../../lib/api";
import { kstDateTime } from "../../inbox/model";
import { INSTRUMENT_KO } from "../../office/auto";
import NavBar from "../NavBar";

/** ⚙ 회사 운영: budget, watched stocks, the asset-allocation policy (read-only for now). */
export default function SettingsPage() {
  const [now, setNow] = useState<OfficeNow | null>(null);
  useEffect(() => { getOfficeNow().then(setNow).catch(() => setNow(null)); }, []);
  const b = now?.budget;
  const spentPct = b ? Math.min(100, (Number(b.spent_usd) + Number(b.reserved_usd)) / Number(b.budget_usd) * 100) : 0;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col">
      <NavBar />
      <div className="flex flex-col gap-4 p-3">
        <h1 className="text-lg font-bold">회사 운영</h1>

        <Card title="이번 달 예산" sub="AI 사용료. 한도에 닿으면 유료 회의를 시작하지 않습니다.">
          {b ? (
            <>
              <div className="flex items-baseline justify-between text-sm">
                <span>${Number(b.spent_usd).toFixed(2)} 사용{Number(b.reserved_usd) > 0 ? ` (+$${Number(b.reserved_usd).toFixed(2)} 진행 중)` : ""}</span>
                <span className="text-[var(--muted)]">한도 ${b.budget_usd} (약 1만 원)</span>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#0f1729]" role="progressbar" aria-valuenow={Math.round(spentPct)} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full rounded-full bg-[var(--mint)]" style={{ width: `${spentPct}%` }} />
              </div>
              <p className="mt-1 text-xs text-[var(--muted)]">{b.month} · 유료 회의 {b.paid_runs}회 · 남은 금액 ${Number(b.remaining_usd).toFixed(2)}</p>
            </>
          ) : <p className="text-sm text-[var(--muted)]">불러오는 중…</p>}
        </Card>

        <Card title="관심 종목" sub="지금은 아래 종목을 매일 정기 회의합니다. 리서치팀이 고르는 관찰·집중 종목은 다음 단계에서 추가됩니다.">
          <ul className="divide-y divide-[var(--line)] text-sm">
            {Object.entries(INSTRUMENT_KO).map(([id, name]) => {
              const next = now?.next.find((n) => n.instrument_id === id);
              return (
                <li key={id} className="flex items-center justify-between py-2">
                  <span>{name} <span className="text-xs text-[var(--muted)]">{id}</span></span>
                  <span className="text-xs text-[var(--muted)]">{next ? `다음 회의 ${kstDateTime(next.at)}` : ""}</span>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card title="자산운용 규정 (POLICY_V1)" sub="자산운용 담당이 매수 비중을 정하는 기준. 결재 문서에 계산 과정이 표시됩니다.">
          <ul className="space-y-1.5 text-sm">
            <li>· 가상 계좌 시작 금액: <b>10,000,000원</b> (모의투자, 실제 돈 아님)</li>
            <li>· 기본 비중: 자산의 10% × 등급 계수(매수 1.0, 비중확대 0.6) × AI 제시 배수</li>
            <li>· 손절 시 손실은 자산의 <b>1%</b> 이내</li>
            <li>· 한 종목 최대 <b>20%</b>, 현금 <b>20%</b> 이상 유지</li>
            <li>· 10만 원 미만이면 매수하지 않음</li>
            <li>· AI가 가격을 주지 않으면: 지정가 = 종가 +0.5%, 손절 = 변동성(ATR)×2 (3~12%), 목표 = 손절 폭의 2배</li>
            <li>· 결재하지 않은 문서는 국내 당일 장 마감, 미국 다음 장 마감에 자동 만료</li>
          </ul>
        </Card>
      </div>
    </main>
  );
}

function Card({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <h2 className="font-semibold">{title}</h2>
      {sub && <p className="mb-3 mt-0.5 text-xs text-[var(--muted)]">{sub}</p>}
      {children}
    </section>
  );
}
