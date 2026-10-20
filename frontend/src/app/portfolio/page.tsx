"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getPortfolio, getPortfolioActivity, type Holding, type PaperOrder, type Portfolio } from "../../lib/api";
import { FILL_RULE_KO, kstDateTime, money, ORDER_STATUS_KO, pnlTone, ROLE_KO, shares, signedPct, signedWon } from "../../inbox/model";
import KiwoomMockPanel from "../KiwoomMockPanel";
import NavBar from "../NavBar";

const MARKET_KO: Record<string, string> = { KR: "국내", US: "미국" };

/** Paper account details: everything here is simulated (no order leaves this app). */
export default function PortfolioPage() {
  const [book, setBook] = useState<Portfolio | null>(null);
  const [activity, setActivity] = useState<PaperOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPortfolio().then(setBook).catch((e: Error) => setError(`불러오지 못했습니다: ${e.message}`));
    getPortfolioActivity().then(setActivity).catch(() => setActivity([]));
  }, []);

  const history = (activity ?? []).filter((o) => o.status !== "OPEN");

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col">
      <NavBar />
      <div className="px-3 pt-3"><Link href="/" className="text-sm text-[var(--muted)]">← 결재함</Link></div>
      {error && <p role="alert" className="mx-3 mt-2 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!book && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {book && (
        <div className="flex flex-col gap-3 p-3">
          <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
            <div className="flex flex-wrap items-center gap-2 text-[11px]">
              <span className="rounded bg-amber-400 px-1.5 font-bold text-black">모의투자 · 실제 돈 아님</span>
              <span className="rounded border border-[var(--line)] px-1.5 text-[var(--muted)]">검증 전 성과</span>
              <span className="text-[var(--muted)]">{book.auto_approve ? "자동 승인 켜짐" : "자동 승인 꺼짐"} · {book.policy_version}</span>
            </div>
            <h1 className="mt-2 text-sm text-[var(--muted)]">총자산</h1>
            <div className="flex items-baseline gap-2">
              <span className="text-2xl font-bold">{money(book.nav_krw, "KRW")}</span>
              <span className={`font-semibold ${pnlTone(book.return_pct)}`}>{signedPct(book.return_pct)}</span>
            </div>
            <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
              <Fact label="시작 금액" value={money(book.initial_krw, "KRW")} />
              <Fact label="현금" value={`${money(book.cash_krw, "KRW")} (${Number(book.cash_weight_pct).toFixed(0)}%)`} />
              <Fact label="예약금" value={money(book.reserved_krw, "KRW")} />
              <Fact label="실현 손익" value={signedWon(book.realized_krw)} tone={pnlTone(book.realized_krw)} />
            </dl>
            <p className="mt-3 text-[11px] text-[var(--muted)]">
              {book.started_at ? `거래 시작 ${kstDateTime(book.started_at)}` : "아직 거래 없음"}
              {book.last_settles.map((s) => ` · ${MARKET_KO[s.market] ?? s.market} 정산 ${s.session}${s.status === "OK" ? "" : ` (${s.status}${s.note ? `: ${s.note}` : ""})`}`)}
              . 평가는 마지막 정산 종가 기준, 달러 보유는 그날 환율로 원화 환산.
            </p>
          </section>

          <Card title={`보유 종목 ${book.holdings.length}`}>
            {book.holdings.length === 0 ? <Empty text="보유 중인 종목이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)]">{book.holdings.map((h) => <HoldingRow key={h.instrument_id} h={h} />)}</ul>
            )}
          </Card>

          <Card title={`대기 중인 예약 ${book.pending.length}`} sub="장 마감 후 그날 일봉으로 체결 여부를 판정합니다.">
            {book.pending.length === 0 ? <Empty text="대기 중인 예약이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)] text-sm">
                {book.pending.map((o) => (
                  <li key={o.id} className="py-2">
                    <div className="flex justify-between gap-2">
                      <span className="font-semibold">{o.name} · {ROLE_KO[o.role]} {shares(o.qty)}</span>
                      <span>{o.role === "exit" ? "시가" : `지정가 ${money(o.price ?? 0, o.currency)}`}</span>
                    </div>
                    <div className="text-xs text-[var(--muted)]">
                      {kstDateTime(o.active_from)}부터{o.valid_until ? ` ${kstDateTime(o.valid_until)}까지` : ""}
                      {o.reserved_krw && Number(o.reserved_krw) > 0 ? ` · 예약금 ${money(o.reserved_krw, "KRW")}` : ""}
                      {o.item_id ? <> · <Link href={`/inbox/${o.item_id}`} className="underline">결재 문서</Link></> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card title="체결·청산 기록">
            {activity === null ? <Empty text="불러오는 중…" /> : history.length === 0 ? <Empty text="아직 기록이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)] text-sm">{history.map((o) => <ActivityRow key={o.id} o={o} />)}</ul>
            )}
          </Card>

          <Card title="키움 모의투자 계좌" sub="곧 위 내부 모의 장부를 대신할 키움 모의 계좌입니다(전환 전, 조회만).">
            <KiwoomMockPanel />
          </Card>

          <Card title="비용 가정" sub="모의 체결에 적용하는 가정값입니다. 실제 증권사 수수료와 다를 수 있습니다.">
            <ul className="space-y-1 text-sm">
              {book.costs.map((c) => <li key={c.label} className="flex justify-between gap-2"><span>{c.label}</span><span className="text-[var(--muted)]">{c.value}</span></li>)}
            </ul>
          </Card>
        </div>
      )}
    </main>
  );
}

function HoldingRow({ h }: { h: Holding }) {
  const last = Number(h.last_price);
  const away = (price: string | null) => (price ? `${money(price, h.currency)} (${signedPct((Number(price) / last - 1) * 100)})` : "—");
  return (
    <li className="py-2.5 text-sm">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-semibold">{h.name} <span className="text-xs font-normal text-[var(--muted)]">{shares(h.qty)}</span></span>
        <span className={`font-semibold ${pnlTone(h.pnl_krw)}`}>{signedWon(h.pnl_krw)} ({signedPct(h.pnl_pct)})</span>
      </div>
      <dl className="mt-1 grid grid-cols-1 gap-x-4 gap-y-0.5 text-xs sm:grid-cols-2">
        <Fact label="평균가" value={money(h.avg_price, h.currency)} />
        <Fact label="현재가" value={`${money(h.last_price, h.currency)} (${h.marked_session.slice(5).replace("-", "/")} 종가)`} />
        <Fact label="평가액" value={money(h.value_krw, "KRW")} />
        <Fact label="매입 원가" value={money(h.cost_krw, "KRW")} />
        <Fact label="목표가" value={away(h.take_profit)} />
        <Fact label="손절가" value={away(h.stop)} />
      </dl>
    </li>
  );
}

function ActivityRow({ o }: { o: PaperOrder }) {
  const f = o.fill;
  return (
    <li className="py-2">
      <div className="flex justify-between gap-2">
        <span><span className="font-semibold">{o.name} · {ROLE_KO[o.role]}</span> <span className="text-xs text-[var(--muted)]">{ORDER_STATUS_KO[o.status]}</span></span>
        {f?.realized_krw ? <span className={`font-semibold ${pnlTone(f.realized_krw)}`}>{signedWon(f.realized_krw)}</span> : null}
      </div>
      <div className="text-xs text-[var(--muted)]">
        {f ? `${f.session} · ${shares(f.qty)} @ ${money(f.price, o.currency)} · ${FILL_RULE_KO[f.rule] ?? f.rule} · 수수료 ${money(f.fee, o.currency)}${Number(f.tax) > 0 ? ` · 세금 ${money(f.tax, o.currency)}` : ""} · ${money(f.amount_krw, "KRW")}`
           : `${kstDateTime(o.closed_at ?? o.created_at)}${o.reason ? ` · ${o.reason}` : ""}`}
        {o.item_id ? <> · <Link href={`/inbox/${o.item_id}`} className="underline">결재 문서</Link></> : null}
      </div>
    </li>
  );
}

function Fact({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex justify-between gap-2 sm:block">
      <dt className="text-[var(--muted)]">{label}</dt>
      <dd className={`font-medium ${tone}`}>{value}</dd>
    </div>
  );
}

function Card({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
      <h2 className="font-semibold">{title}</h2>
      {sub && <p className="mt-0.5 text-xs text-[var(--muted)]">{sub}</p>}
      <div className="mt-2">{children}</div>
    </section>
  );
}

function Empty({ text }: { text: string }) {
  return <p className="text-sm text-[var(--muted)]">{text}</p>;
}
