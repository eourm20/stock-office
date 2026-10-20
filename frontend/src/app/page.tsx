"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getInbox, getKiwoomMock, getOfficeNow, type InboxItem, type MockAccount, type OfficeNow } from "../lib/api";
import { MARKET_KO, marketOf, useMarket, type Market } from "../lib/market";
import { buyPlan, deadlineLabel, groupInbox, kstDateTime, money, nextWorkLabel, paperLine, pnlTone, sellPlan, shares,
         STATUS_KO, STATUS_TONE } from "../inbox/model";
import ConveneButton from "./ConveneButton";
import NavBar from "./NavBar";

const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

/** 결재함: the CEO's desk for one market (국장 or 미장). Decisions first, then reports, then handled. */
export default function InboxPage() {
  const { market, refreshPending } = useMarket();
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [now, setNow] = useState<OfficeNow | null>(null);
  const [accounts, setAccounts] = useState<Record<Market, MockAccount | null> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now());

  useEffect(() => {
    const load = () => Promise.all([getInbox(), getOfficeNow()]).then(([i, n]) => {
      setItems(i); setNow(n); setClock(Date.now()); setError(null);
      refreshPending();
      getKiwoomMock().then((k) => setAccounts(k.accounts)).catch(() => setAccounts(null));
    }).catch((e: Error) => setError(`서버에 연결할 수 없습니다: ${e.message}`));
    void load();
    const timer = setInterval(() => void load(), 60_000);
    return () => clearInterval(timer);
  }, [refreshPending]);

  const mine = (items ?? []).filter((i) => marketOf(i.instrument_id) === market);
  const g = groupInbox(mine);
  const unread = g.reports.filter((r) => !r.read_at).length;
  const next = now?.next.find((n) => n.market === market);
  const active = now?.active;
  const activeHere = active && marketOf(active.instrument_id) === market;

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col">
      <NavBar><ConveneButton onStarted={(id) => { window.location.href = `/office?run=${id}`; }} /></NavBar>

      <AccountCard market={market} acc={accounts ? accounts[market] : undefined} />

      <section aria-label="오늘 현황" className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
        <Stat label="결재 대기" value={`${g.pending.length}건`} tone={g.pending.length ? "text-amber-200" : ""} />
        <Stat label="보고" value={`${g.reports.length}건`} sub={unread ? `안 읽음 ${unread}` : "모두 읽음"} />
        <Stat label="AI 예산 (공통)" value={now?.budget ? `$${Number(now.budget.remaining_usd).toFixed(2)} 남음` : "—"}
              sub={now?.budget ? `$${Number(now.budget.spent_usd).toFixed(2)} / $${now.budget.budget_usd}` : undefined} />
        {active ? (
          <Link href="/office" className={`rounded-lg border p-3 ${activeHere ? "border-sky-700 bg-sky-950/40" : "border-[var(--line)] bg-[var(--panel)]"}`}>
            <div className="text-[11px] text-sky-200">● 지금 회의 중{activeHere ? "" : ` · ${MARKET_KO[marketOf(active.instrument_id) ?? "KR"]}`}</div>
            <div className="mt-0.5 font-semibold">{active.name}</div>
          </Link>
        ) : (
          <Stat label="다음 업무" value={next ? `${kstDateTime(next.at)}` : "—"} sub={next ? nextWorkLabel(next) : undefined} />
        )}
      </section>

      {error && <p role="alert" className="mx-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!items && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {items && (
        <div className="flex flex-col gap-5 px-3 pb-6">
          <section aria-label="결재 대기">
            <h2 className="mb-2 text-sm font-semibold">{MARKET_KO[market]} 결재 대기 <span className="text-[var(--muted)]">{g.pending.length}</span></h2>
            {g.pending.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--line)] p-4 text-sm text-[var(--muted)]">
                결재할 문서가 없습니다.{next ? ` 다음 업무: ${kstDateTime(next.at)} ${nextWorkLabel(next)}` : ""}
              </p>
            ) : (
              <ul className="space-y-2">
                {g.pending.map((i) => <ApprovalCard key={i.id} item={i} now={clock} />)}
              </ul>
            )}
          </section>

          <section aria-label="보고">
            <h2 className="mb-2 text-sm font-semibold">보고 <span className="text-[var(--muted)]">{g.reports.length}</span></h2>
            {g.reports.length === 0 ? <p className="text-sm text-[var(--muted)]">아직 보고가 없습니다.</p> : (
              <ul className="divide-y divide-[var(--line)] overflow-hidden rounded-lg border border-[var(--line)] bg-[var(--panel)]">
                {g.reports.map((i) => <ReportRow key={i.id} item={i} />)}
              </ul>
            )}
          </section>

          {g.done.length > 0 && (
            <details className="rounded-lg border border-[var(--line)]">
              <summary className="cursor-pointer px-3 py-2 text-sm font-semibold">처리됨 <span className="text-[var(--muted)]">{g.done.length}</span></summary>
              <ul className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
                {g.done.map((i) => <ReportRow key={i.id} item={i} />)}
              </ul>
            </details>
          )}
          <p className="text-center text-[11px] text-[var(--muted)]">모든 결정은 AI 위원회의 제안이며 검증된 투자 신호가 아닙니다. 모의투자 전용 · 실계좌 주문 없음.</p>
        </div>
      )}
    </main>
  );
}

/** This market's Kiwoom mock account at a glance; details on /portfolio. */
function AccountCard({ market, acc }: { market: Market; acc: MockAccount | null | undefined }) {
  const cur = market === "KR" ? "KRW" : "USD";
  const total = acc?.ok && acc.cash !== null ? Number(acc.cash) + Number(acc.total_value ?? 0) : null;
  return (
    <Link href="/portfolio" className="mx-3 mt-3 block rounded-xl border border-[var(--line)] bg-[var(--panel)] p-3 hover:bg-[#1d2944]">
      <div className="flex items-center justify-between text-[11px] text-[var(--muted)]">
        <span>{MARKET_KO[market]} 계좌 · 키움 모의투자 · 검증 전</span><span aria-hidden="true">포트폴리오 →</span>
      </div>
      {acc === undefined ? <div className="mt-1 text-sm text-[var(--muted)]">계좌 조회 중…</div>
        : !acc ? <div className="mt-1 text-sm text-[var(--muted)]">모의 계좌가 연결되지 않았습니다 (⚙)</div>
        : !acc.ok ? <div className="mt-1 text-sm text-rose-300">계좌 조회 오류: {acc.error}</div>
        : (
          <>
            <div className="mt-0.5 text-xl font-bold">{total === null ? "—" : money(total, cur)}</div>
            <div className="text-xs text-[var(--muted)]">
              예수금 {acc.cash === null ? "—" : money(acc.cash, cur)} · 보유 {acc.holdings.length}종목
              {acc.fills_today ? ` · 오늘 체결 ${acc.fills_today}건` : ""}
            </div>
          </>
        )}
    </Link>
  );
}

function Stat({ label, value, sub, tone = "" }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--panel)] p-3">
      <div className="text-[11px] text-[var(--muted)]">{label}</div>
      <div className={`mt-0.5 font-semibold ${tone}`}>{value}</div>
      {sub && <div className="text-[11px] text-[var(--muted)]">{sub}</div>}
    </div>
  );
}

function ApprovalCard({ item, now }: { item: InboxItem; now: number }) {
  const plan = buyPlan(item);
  const sell = sellPlan(item);
  const a = plan?.allocation;
  const due = deadlineLabel(item.expires_at, now);
  const urgent = item.expires_at ? Date.parse(item.expires_at) - now < 3 * 3_600_000 : false;
  return (
    <li>
      <Link href={`/inbox/${item.id}`} className="block rounded-lg border border-l-4 border-[var(--line)] border-l-amber-400 bg-[var(--panel)] p-3 hover:bg-[#1d2944]">
        <div className="flex items-start justify-between gap-2">
          <span className="font-semibold leading-snug">{item.title}</span>
          {item.payload.demo && <span className="shrink-0 rounded bg-amber-400 px-1.5 text-[10px] font-bold text-black">DEMO</span>}
        </div>
        {plan && a && (
          <div className="mt-1 text-sm text-[#c7d7ee]">
            {money(plan.limit, plan.currency)} 지정가 · {plan.currency === "USD" ? money(a.notional, "USD") : money(a.notional_krw, "KRW")}
            <span className="text-[var(--muted)]"> · 손절 시 최대 {money(a.max_loss_krw, "KRW")}</span>
          </div>
        )}
        {sell && (
          <div className="mt-1 text-sm text-[#c7d7ee]">
            {shares(sell.qty)} · 평가 {money(sell.value_krw, "KRW")}
            <span className="text-[var(--muted)]"> · 다음 장 시가에 매도</span>
          </div>
        )}
        {item.summary && <p className="mt-1 line-clamp-2 text-[13px] text-[var(--muted)]">{item.summary}</p>}
        <div className={`mt-2 flex items-center justify-between text-xs ${urgent ? "text-amber-300" : "text-[var(--muted)]"}`}>
          <span>기안 PM · {item.status === "DEFERRED" ? "보류 중 · " : ""}{due}</span>
          <span aria-hidden="true">결재하기 →</span>
        </div>
      </Link>
    </li>
  );
}

function ReportRow({ item }: { item: InboxItem }) {
  const action = item.payload.action;
  const realized = item.payload.realized_krw;
  const tone = realized !== undefined ? pnlTone(realized) : action ? ACTION_COLOR[action] ?? "" : "";
  const paper = item.kind === "approval" ? paperLine(item.paper) : null;
  const href = item.kind === "approval" ? `/inbox/${item.id}` : item.run_id ? `/records/${item.run_id}` : `/inbox/${item.id}`;
  return (
    <li>
      <Link href={href} className="flex items-start gap-2 px-3 py-2.5 hover:bg-[#1d2944]">
        <span aria-hidden="true" className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.read_at || item.status !== "INFO" ? "bg-transparent" : "bg-[var(--accent)]"}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm">
            <span className={`truncate font-medium ${tone}`}>{item.title}</span>
            {item.payload.demo && <span className="rounded bg-amber-400 px-1 text-[10px] font-bold text-black">DEMO</span>}
          </span>
          {(paper || item.summary) && <span className="mt-0.5 block line-clamp-1 text-[12px] text-[var(--muted)]">{paper ?? item.summary}</span>}
        </span>
        <span className="shrink-0 text-right text-[11px] text-[var(--muted)]">
          <span className={`inline-block rounded border px-1 ${STATUS_TONE[item.status]}`}>{item.auto_approved ? "자동 승인" : STATUS_KO[item.status]}</span>
          <span className="mt-0.5 block">{kstDateTime(item.created_at)}</span>
        </span>
      </Link>
    </li>
  );
}
