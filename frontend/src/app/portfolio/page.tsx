"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getMockActivity, getMockPerformance, type MockOrder, type MockPerformance } from "../../lib/api";
import { kstDateTime, MOCK_STATUS_KO, money, pnlTone, ROLE_KO, shares, signedPct } from "../../inbox/model";
import { MARKET_CURRENCY, MARKET_KO, useMarket } from "../../lib/market";
import KiwoomMockPanel from "../KiwoomMockPanel";
import NavBar from "../NavBar";

const BENCH_KO: Record<string, string> = { "^KS11": "코스피", "^NDX": "나스닥100" };

/** One desk's portfolio: its Kiwoom mock account, performance against the benchmark, orders. */
export default function PortfolioPage() {
  const { market } = useMarket();
  const [orders, setOrders] = useState<MockOrder[] | null>(null);
  const [perf, setPerf] = useState<MockPerformance | null>(null);

  useEffect(() => {
    setOrders(null);
    setPerf(null);
    getMockActivity(market).then(setOrders).catch(() => setOrders([]));
    getMockPerformance(market).then(setPerf).catch(() => setPerf(null));
  }, [market]);

  const open = (orders ?? []).filter((o) => ["WAITING", "SENDING", "SENT", "REVIEW"].includes(o.status));
  const done = (orders ?? []).filter((o) => !open.includes(o));

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

        <Card title="성과" sub="장 마감마다 계좌 평가액을 기록하고 비교 지수와 견줍니다. 검증 전 모의투자 결과입니다.">
          <Performance perf={perf} market={market} />
        </Card>

        <Card title={`진행 중인 주문 ${open.length}`} sub="정규장에만 주문합니다. 기한까지 체결되지 않으면 취소하고, 보유 중에는 목표가·손절가를 감시합니다.">
          {orders === null ? <Empty text="불러오는 중…" /> : open.length === 0 ? <Empty text="진행 중인 주문이 없습니다." /> : (
            <ul className="divide-y divide-[var(--line)] text-sm">{open.map((o) => <OrderRow key={o.id} o={o} />)}</ul>
          )}
        </Card>

        <Card title="주문·체결 기록">
          {orders === null ? <Empty text="불러오는 중…" /> : done.length === 0 ? <Empty text="아직 기록이 없습니다." /> : (
            <ul className="divide-y divide-[var(--line)] text-sm">{done.map((o) => <OrderRow key={o.id} o={o} />)}</ul>
          )}
        </Card>
      </div>
    </main>
  );
}

function Performance({ perf, market }: { perf: MockPerformance | null; market: "KR" | "US" }) {
  if (!perf) return <Empty text="불러오는 중…" />;
  const cur = MARKET_CURRENCY[market];
  const last = perf.history[perf.history.length - 1];
  if (!perf.start) return <Empty text="첫 주문 때 시작 자산을 기록하고, 그날 장 마감부터 성과를 계산합니다." />;
  const start = Number(perf.start);
  const ret = last ? (Number(last.nav) / start - 1) * 100 : 0;
  const first = perf.history.find((h) => h.benchmark_close);
  const lastBench = [...perf.history].reverse().find((h) => h.benchmark_close);
  const bench = first && lastBench ? (Number(lastBench.benchmark_close) / Number(first.benchmark_close) - 1) * 100 : null;
  return (
    <dl className="grid grid-cols-1 gap-y-1 text-sm sm:grid-cols-2 sm:gap-x-4">
      <Fact label="시작 자산" value={money(start, cur)} />
      <Fact label={last ? `평가액 (${last.session})` : "평가액"} value={last ? money(last.nav, cur) : "장 마감 후 기록"} />
      <Fact label="수익률" value={last ? signedPct(ret) : "—"} tone={last ? pnlTone(ret) : ""} />
      <Fact label={`비교 지수 (${BENCH_KO[lastBench?.benchmark ?? ""] ?? (market === "KR" ? "코스피" : "나스닥100")})`}
            value={bench === null ? "—" : signedPct(bench)} tone={bench === null ? "" : pnlTone(bench)} />
      <Fact label="기록된 장" value={`${perf.history.length}일`} />
    </dl>
  );
}

function OrderRow({ o }: { o: MockOrder }) {
  const pnl = o.detail.pnl;
  return (
    <li className="py-2">
      <div className="flex justify-between gap-2">
        <span><span className="font-semibold">{o.name} · {ROLE_KO[o.role]}</span> <span className="text-xs text-[var(--muted)]">{MOCK_STATUS_KO[o.status]}</span></span>
        {pnl ? <span className={`font-semibold ${pnlTone(pnl)}`}>{Number(pnl) >= 0 ? "+" : "−"}{money(Math.abs(Number(pnl)), o.currency)}</span> : null}
      </div>
      <div className="text-xs text-[var(--muted)]">
        {o.qty ? `${shares(o.qty)} · ` : ""}{o.limit_price ? `지정가 ${money(o.limit_price, o.currency)}` : "가격은 주문 때 결정"}
        {o.fill_price ? ` · 체결 ${shares(o.filled_qty)} @ ${money(o.fill_price, o.currency)}` : ""}
        {o.status === "WAITING" && o.valid_until ? ` · ${kstDateTime(o.valid_until)}까지` : ""}
        {o.closed_at ? ` · ${kstDateTime(o.closed_at)}` : o.sent_at ? ` · ${kstDateTime(o.sent_at)} 주문` : ""}
        {o.reason ? ` · ${o.reason}` : ""}
        {o.item_id ? <> · <Link href={`/inbox/${o.item_id}`} className="underline">결재 문서</Link></> : null}
      </div>
    </li>
  );
}

function Fact({ label, value, tone = "" }: { label: string; value: string; tone?: string }) {
  return (
    <div className="flex justify-between gap-2">
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
