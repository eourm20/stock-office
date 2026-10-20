"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getPortfolio, getPortfolioActivity, type Holding, type PaperOrder, type Portfolio } from "../../lib/api";
import { FILL_RULE_KO, kstDateTime, money, ORDER_STATUS_KO, pnlTone, ROLE_KO, shares, signedPct, signedWon } from "../../inbox/model";
import { MARKET_KO, marketOf, useMarket } from "../../lib/market";
import KiwoomMockPanel from "../KiwoomMockPanel";
import NavBar from "../NavBar";

// Cost lines that apply to each desk (the rest belong to the other market).
const COST_FOR = { KR: /국내|미끄러짐/, US: /미국|환전|미끄러짐/ } as const;

/** One desk's portfolio: its Kiwoom mock account first; the internal paper book (being replaced) below. */
export default function PortfolioPage() {
  const { market } = useMarket();
  const [book, setBook] = useState<Portfolio | null>(null);
  const [activity, setActivity] = useState<PaperOrder[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getPortfolio().then(setBook).catch((e: Error) => setError(`불러오지 못했습니다: ${e.message}`));
    getPortfolioActivity().then(setActivity).catch(() => setActivity([]));
  }, []);

  const holdings = (book?.holdings ?? []).filter((h) => marketOf(h.instrument_id) === market);
  const pending = (book?.pending ?? []).filter((o) => o.market === market);
  const history = (activity ?? []).filter((o) => o.status !== "OPEN" && o.market === market);
  const settle = book?.last_settles.find((x) => x.market === market);

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col">
      <NavBar />
      <div className="flex items-center justify-between px-3 pt-3">
        <Link href="/" className="text-sm text-[var(--muted)]">← 결재함</Link>
        <span className="rounded bg-amber-400 px-1.5 text-[11px] font-bold text-black">모의투자 · 검증 전</span>
      </div>
      <h1 className="px-3 pt-2 text-lg font-bold">{MARKET_KO[market]} 포트폴리오</h1>

      <div className="flex flex-col gap-3 p-3">
        <Card title="키움 모의 계좌" sub={market === "KR" ? "국장 운용 자금(원화). 계좌 잔고가 곧 회사가 굴리는 돈입니다." : "미장 운용 자금(달러, 환전 없음). 계좌 잔고가 곧 회사가 굴리는 돈입니다."}>
          <KiwoomMockPanel market={market} />
        </Card>

        {error && <p role="alert" className="rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
        {book && (
          <details className="rounded-xl border border-[var(--line)] bg-[var(--panel)] p-4">
            <summary className="cursor-pointer font-semibold">
              내부 모의 장부 <span className="text-xs font-normal text-[var(--muted)]">(전환 전 · 보유 {holdings.length} · 대기 {pending.length} · 기록 {history.length})</span>
            </summary>
            <p className="mt-1 text-xs text-[var(--muted)]">
              키움 모의 주문을 연결하기 전까지 승인된 결재안을 기록하는 앱 내부 장부입니다. 연결 뒤에는 위 키움 계좌로 바뀌고, 이 기록은 성과에 섞지 않습니다.
              {settle ? ` 마지막 정산 ${settle.session}${settle.status === "OK" ? "" : ` (${settle.status})`}.` : ""}
            </p>

            <h3 className="mt-3 text-sm font-semibold">보유 {holdings.length}</h3>
            {holdings.length === 0 ? <Empty text="보유 중인 종목이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)]">{holdings.map((h) => <HoldingRow key={h.instrument_id} h={h} />)}</ul>
            )}

            <h3 className="mt-3 text-sm font-semibold">대기 중인 예약 {pending.length}</h3>
            {pending.length === 0 ? <Empty text="대기 중인 예약이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)] text-sm">
                {pending.map((o) => (
                  <li key={o.id} className="py-2">
                    <div className="flex justify-between gap-2">
                      <span className="font-semibold">{o.name} · {ROLE_KO[o.role]} {shares(o.qty)}</span>
                      <span>{o.role === "exit" ? "시가" : `지정가 ${money(o.price ?? 0, o.currency)}`}</span>
                    </div>
                    <div className="text-xs text-[var(--muted)]">
                      {kstDateTime(o.active_from)}부터{o.valid_until ? ` ${kstDateTime(o.valid_until)}까지` : ""}
                      {o.item_id ? <> · <Link href={`/inbox/${o.item_id}`} className="underline">결재 문서</Link></> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}

            <h3 className="mt-3 text-sm font-semibold">체결·청산 기록</h3>
            {activity === null ? <Empty text="불러오는 중…" /> : history.length === 0 ? <Empty text="아직 기록이 없습니다." /> : (
              <ul className="divide-y divide-[var(--line)] text-sm">{history.map((o) => <ActivityRow key={o.id} o={o} />)}</ul>
            )}

            <h3 className="mt-3 text-sm font-semibold">비용 가정 (내부 장부)</h3>
            <ul className="space-y-1 text-sm">
              {book.costs.filter((c) => COST_FOR[market].test(c.label)).map((c) => (
                <li key={c.label} className="flex justify-between gap-2"><span>{c.label}</span><span className="text-[var(--muted)]">{c.value}</span></li>
              ))}
            </ul>
          </details>
        )}
      </div>
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
