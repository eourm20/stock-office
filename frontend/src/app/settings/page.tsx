"use client";

import { useEffect, useState } from "react";
import { getCompanySettings, getOfficeNow, setAutoApprove, type CompanySettings, type OfficeNow } from "../../lib/api";
import { kstDateTime } from "../../inbox/model";
import { INSTRUMENT_KO } from "../../office/auto";
import NavBar from "../NavBar";

/** ⚙ 회사 운영: budget, paper-trading switch, watched stocks, the asset-allocation policy. */
export default function SettingsPage() {
  const [now, setNow] = useState<OfficeNow | null>(null);
  const [company, setCompany] = useState<CompanySettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    getOfficeNow().then(setNow).catch(() => setNow(null));
    getCompanySettings().then(setCompany).catch(() => setCompany(null));
  }, []);
  const toggleAuto = async () => {
    if (!company) return;
    setSaving(true);
    setError(null);
    try {
      setCompany({ ...company, auto_approve: await setAutoApprove(!company.auto_approve) });
    } catch (e) {
      setError(`바꾸지 못했습니다: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };
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

        <Card title="자동 승인 (모의투자)" sub="모델 성능만 재기 위해, 결재안이 올라오는 즉시 그대로 승인해 모의 예약 주문을 넣습니다.">
          {company ? (
            <>
              <div className="flex items-center justify-between gap-3">
                <span className="text-sm">{company.auto_approve ? "켜짐 · 결재안을 그대로 따름" : "꺼짐 · CEO가 직접 결재"}</span>
                <button role="switch" aria-checked={company.auto_approve} aria-label="자동 승인" disabled={saving}
                        onClick={() => void toggleAuto()}
                        className={`relative h-7 w-12 shrink-0 rounded-full transition-colors disabled:opacity-50 ${company.auto_approve ? "bg-[var(--mint)]" : "bg-[#3a4560]"}`}>
                  <span className={`absolute top-0.5 h-6 w-6 rounded-full bg-white transition-all ${company.auto_approve ? "left-[1.375rem]" : "left-0.5"}`} />
                </button>
              </div>
              {error && <p role="alert" className="mt-2 text-xs text-rose-300">{error}</p>}
              <p className="mt-2 text-xs text-[var(--muted)]">
                켜져 있어도 결재 문서의 버튼은 남습니다. 기한 안에 누르면 <b>CEO 의견(동의·보류·반대)</b>으로만 기록되고 모의 주문은 바뀌지 않습니다. 나중에 모델 판단과 CEO 판단을 비교하는 데 씁니다.
                DEMO(연습) 회의는 모의 계좌에 들어가지 않습니다.
              </p>
              <h3 className="mb-1 mt-3 text-xs font-semibold text-[var(--muted)]">모의 체결 비용 가정</h3>
              <ul className="space-y-0.5 text-sm">
                {company.costs.map((c) => <li key={c.label} className="flex justify-between gap-2"><span>{c.label}</span><span className="text-[var(--muted)]">{c.value}</span></li>)}
              </ul>
            </>
          ) : <p className="text-sm text-[var(--muted)]">불러오는 중…</p>}
        </Card>

        <Card title="관심 종목" sub="지금은 아래 종목을 매일 정기 회의합니다. 리서치팀이 고르는 관찰·집중 종목은 다음 단계에서 추가됩니다.">
          <ul className="divide-y divide-[var(--line)] text-sm">
            {Object.entries(INSTRUMENT_KO).map(([id, name]) => {
              const next = now?.next.find((n) => n.instrument_id === id && n.kind !== "settle");
              return (
                <li key={id} className="flex items-center justify-between py-2">
                  <span>{name} <span className="text-xs text-[var(--muted)]">{id}</span></span>
                  <span className="text-xs text-[var(--muted)]">{next ? `다음 회의 ${kstDateTime(next.at)}` : ""}</span>
                </li>
              );
            })}
          </ul>
        </Card>

        <Card title="자산운용 규정 (POLICY_V2)" sub="자산운용 담당이 매수 비중을 정하는 기준. 결재 문서에 계산 과정이 표시됩니다.">
          <ul className="space-y-1.5 text-sm">
            <li>· 가상 계좌 시작 금액: <b>10,000,000원</b> (모의투자, 실제 돈 아님)</li>
            <li>· 기본 비중: 자산의 10% × 등급 계수(매수 1.0, 비중확대 0.6) × AI 제시 배수</li>
            <li>· 손절 시 손실은 자산의 <b>1%</b> 이내</li>
            <li>· 한 종목 최대 <b>20%</b>, 현금 <b>20%</b> 이상 유지</li>
            <li>· 수량: 국내 주식은 1주 단위, <b>미국 주식은 소수점(0.0001주) 단위</b></li>
            <li>· 10만 원 미만이면 매수하지 않음</li>
            <li>· AI가 가격을 주지 않으면: 지정가 = 종가 +0.5%, 손절 = 변동성(ATR)×2 (3~12%), 목표 = 손절 폭의 2배</li>
            <li>· 결재하지 않은 문서는 국내 당일 장 마감, 미국 다음 장 마감에 자동 만료 (자동 승인이 켜져 있으면 올라오는 즉시 승인)</li>
            <li>· 승인된 매수는 다음 장에 지정가 예약 → 장 마감 후 일봉으로 체결 판정 → 목표가·손절가에 자동 청산 (같은 날 둘 다 닿으면 손절)</li>
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
