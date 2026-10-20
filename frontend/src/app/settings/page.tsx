"use client";

import { useEffect, useState } from "react";
import { getCompanySettings, getOfficeNow, setAutoApprove, type CompanySettings, type OfficeNow } from "../../lib/api";
import { kstDateTime } from "../../inbox/model";
import { INSTRUMENT_KO } from "../../office/auto";
import { disablePush, enablePush, getNotifyStatus, pushState, sendTestPush, type NotifyStatus,
         type PushState } from "../../lib/push";
import { MARKET_KO, marketOf, useMarket } from "../../lib/market";
import KiwoomMockPanel from "../KiwoomMockPanel";
import NavBar from "../NavBar";

/** ⚙ 회사 운영: the selected desk (account, watched stocks) first, then what both desks share. */
export default function SettingsPage() {
  const { market } = useMarket();
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

        <h2 className="-mb-2 text-sm font-semibold text-[var(--accent)]">{MARKET_KO[market]}</h2>
        <Card title={`${MARKET_KO[market]} 계좌 · 키움 모의투자`} sub={market === "KR" ? "국장 운용 자금(원화). 지금은 조회만 하고, 다음 단계에서 승인된 국장 결재안을 이 계좌로 모의 주문합니다." : "미장 운용 자금(달러, 환전 없음). 지금은 조회만 하고, 다음 단계에서 승인된 미장 결재안을 이 계좌로 모의 주문합니다."}>
          <KiwoomMockPanel market={market} />
        </Card>

        <Card title={`${MARKET_KO[market]} 관심 종목`} sub="매일 정기 회의하는 종목. 리서치팀이 고르는 관찰·집중 종목은 다음 단계에서 추가됩니다.">
          <ul className="divide-y divide-[var(--line)] text-sm">
            {Object.entries(INSTRUMENT_KO).filter(([id]) => marketOf(id) === market).map(([id, name]) => {
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

        <h2 className="-mb-2 mt-2 text-sm font-semibold text-[var(--muted)]">공통</h2>
        <Card title="AI 예산 (공통)" sub="두 시장 회의를 합친 이번 달 AI 사용료. 한도에 닿으면 유료 회의를 시작하지 않습니다.">
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

        <Card title="자동 승인 (모의투자)" sub="모델 성능만 재기 위해, 국장·미장 모두 결재안이 올라오는 즉시 그대로 승인해 모의 주문을 넣습니다.">
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
            </>
          ) : <p className="text-sm text-[var(--muted)]">불러오는 중…</p>}
        </Card>

        <NotifyCard />

        <Card title="자산운용 규정" sub="자산운용 담당이 매수 비중을 정하는 기준. 결재 문서에 계산 과정이 표시됩니다.">
          <ul className="space-y-1.5 text-sm">
            <li>· 국장과 미장은 <b>따로 운영하는 두 포트폴리오</b>입니다. 계좌 사이에 돈을 옮기지 않고, 비중은 각 계좌의 자산 기준으로 계산합니다(키움 모의 주문 연결 시 POLICY_V3).</li>
            <li>· 기본 비중: 계좌 자산의 10% × 등급 계수(매수 1.0, 비중확대 0.6) × AI 제시 배수</li>
            <li>· 손절 시 손실은 계좌 자산의 <b>1%</b> 이내</li>
            <li>· 한 종목 최대 <b>20%</b>, 현금 <b>20%</b> 이상 유지</li>
            <li>· 수량: 국장·미장 모두 <b>1주 단위</b> (키움 API로 소수점 주문 확인 전)</li>
            <li>· AI가 가격을 주지 않으면: 지정가 = 종가 +0.5%, 손절 = 변동성(ATR)×2 (3~12%), 목표 = 손절 폭의 2배</li>
            <li>· 결재하지 않은 문서는 국장 당일 장 마감, 미장 다음 장 마감에 자동 만료 (자동 승인이 켜져 있으면 올라오는 즉시 승인)</li>
          </ul>
        </Card>
      </div>
    </main>
  );
}

const PUSH_TEXT: Record<PushState, string> = {
  unsupported: "이 브라우저는 알림을 지원하지 않습니다.",
  "install-first": "아이폰은 Safari에서 공유 → '홈 화면에 추가'로 설치한 앱에서만 알림을 켤 수 있습니다.",
  blocked: "알림이 차단되어 있습니다. 설정 → 알림 → Stock Office에서 허용해 주세요.",
  off: "꺼짐",
  on: "켜짐 · 이 기기로 받습니다",
};

/** Phone notifications: only approval requests, fills/exits and problems. */
function NotifyCard() {
  const [status, setStatus] = useState<NotifyStatus | null>(null);
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const refresh = () => {
    getNotifyStatus().then(setStatus).catch(() => setStatus(null));
    pushState().then(setState).catch(() => setState("unsupported"));
  };
  useEffect(refresh, []);
  const act = async (fn: () => Promise<string>) => {
    setBusy(true);
    setNote(null);
    try {
      setNote(await fn());
    } catch (e) {
      setNote(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      refresh();
    }
  };
  const ready = status?.enabled && status.public_key;
  return (
    <Card title="휴대폰 알림 (공통)" sub="회의 시작·끝과 결재 요청만 보냅니다. 체결·청산·정산 같은 나머지는 결재함과 포트폴리오에서 확인합니다.">
      {status && (
        <ul className="mb-3 space-y-0.5 text-sm">
          {status.categories.map((c) => <li key={c}>· {c}</li>)}
          <li className="text-xs text-[var(--muted)]">방해 금지 {status.quiet} (한국 시간): 그동안 온 알림은 끝나는 시각에 한 번에 묶어서 보냅니다.</li>
        </ul>
      )}
      {!status ? <p className="text-sm text-[var(--muted)]">불러오는 중…</p>
        : !ready ? <p className="text-sm text-amber-200">서버에 알림 키가 아직 없습니다 (관리자 설정 필요).</p>
        : (
          <>
            <div className="flex items-center justify-between gap-3">
              <span className="text-sm">{state ? PUSH_TEXT[state] : "확인 중…"}</span>
              {state === "off" && (
                <button disabled={busy} onClick={() => void act(async () => { await enablePush(status.public_key!); return "알림을 켰습니다."; })}
                        className="shrink-0 rounded bg-[var(--mint)] px-3 py-1.5 text-sm font-semibold text-black disabled:opacity-50">알림 켜기</button>
              )}
              {state === "on" && (
                <button disabled={busy} onClick={() => void act(async () => { await disablePush(); return "알림을 껐습니다."; })}
                        className="shrink-0 rounded border border-[var(--line)] px-3 py-1.5 text-sm disabled:opacity-50">끄기</button>
              )}
            </div>
            {state === "on" && (
              <button disabled={busy} onClick={() => void act(async () => `테스트 알림 ${await sendTestPush()}건 보냄`)}
                      className="mt-2 text-xs underline disabled:opacity-50">테스트 알림 보내기</button>
            )}
            {note && <p role="status" className="mt-2 text-xs text-[var(--muted)]">{note}</p>}
          </>
        )}
    </Card>
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
