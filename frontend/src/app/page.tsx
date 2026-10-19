"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { getInbox, getOfficeNow, type InboxItem, type OfficeNow } from "../lib/api";
import { deadlineLabel, groupInbox, kstDateTime, money, STATUS_KO, STATUS_TONE } from "../inbox/model";
import ConveneButton from "./ConveneButton";
import NavBar from "./NavBar";

const ACTION_COLOR: Record<string, string> = {
  BUY: "text-emerald-300", SELL: "text-rose-300", HOLD: "text-sky-200", REVIEW: "text-amber-300",
};

/** 결재함: the CEO's desk. Decisions first, then reports, then what was already handled. */
export default function InboxPage() {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [now, setNow] = useState<OfficeNow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now());

  useEffect(() => {
    const load = () => Promise.all([getInbox(), getOfficeNow()]).then(([i, n]) => {
      setItems(i); setNow(n); setClock(Date.now()); setError(null);
    }).catch((e: Error) => setError(`서버에 연결할 수 없습니다: ${e.message}`));
    void load();
    const timer = setInterval(() => void load(), 60_000);
    return () => clearInterval(timer);
  }, []);

  const g = groupInbox(items ?? []);
  const unread = g.reports.filter((r) => !r.read_at).length;
  const next = now?.next[0];

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col">
      <NavBar><ConveneButton onStarted={(id) => { window.location.href = `/office?run=${id}`; }} /></NavBar>

      <section aria-label="오늘 현황" className="grid grid-cols-2 gap-2 p-3 sm:grid-cols-4">
        <Stat label="결재 대기" value={`${g.pending.length}건`} tone={g.pending.length ? "text-amber-200" : ""} />
        <Stat label="보고" value={`${g.reports.length}건`} sub={unread ? `안 읽음 ${unread}` : "모두 읽음"} />
        <Stat label="이번 달 예산" value={now?.budget ? `$${Number(now.budget.remaining_usd).toFixed(2)} 남음` : "—"}
              sub={now?.budget ? `$${Number(now.budget.spent_usd).toFixed(2)} / $${now.budget.budget_usd}` : undefined} />
        {now?.active ? (
          <Link href="/office" className="rounded-lg border border-sky-700 bg-sky-950/40 p-3">
            <div className="text-[11px] text-sky-200">● 지금 회의 중</div>
            <div className="mt-0.5 font-semibold">{now.active.name}</div>
          </Link>
        ) : (
          <Stat label="다음 업무" value={next ? `${kstDateTime(next.at)}` : "—"} sub={next ? `${next.name} 회의` : undefined} />
        )}
      </section>

      {error && <p role="alert" className="mx-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!items && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {items && (
        <div className="flex flex-col gap-5 px-3 pb-6">
          <section aria-label="결재 대기">
            <h2 className="mb-2 text-sm font-semibold">결재 대기 <span className="text-[var(--muted)]">{g.pending.length}</span></h2>
            {g.pending.length === 0 ? (
              <p className="rounded-lg border border-dashed border-[var(--line)] p-4 text-sm text-[var(--muted)]">
                결재할 문서가 없습니다.{next ? ` 다음 회의는 ${kstDateTime(next.at)} ${next.name}입니다.` : ""}
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
          <p className="text-center text-[11px] text-[var(--muted)]">모든 결정은 AI 위원회의 제안이며 검증된 투자 신호가 아닙니다. 실제 주문은 하지 않습니다.</p>
        </div>
      )}
    </main>
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
  const a = item.plan?.allocation;
  const due = deadlineLabel(item.expires_at, now);
  const urgent = item.expires_at ? Date.parse(item.expires_at) - now < 3 * 3_600_000 : false;
  return (
    <li>
      <Link href={`/inbox/${item.id}`} className="block rounded-lg border border-l-4 border-[var(--line)] border-l-amber-400 bg-[var(--panel)] p-3 hover:bg-[#1d2944]">
        <div className="flex items-start justify-between gap-2">
          <span className="font-semibold leading-snug">{item.title}</span>
          {item.payload.demo && <span className="shrink-0 rounded bg-amber-400 px-1.5 text-[10px] font-bold text-black">DEMO</span>}
        </div>
        {item.plan && a && (
          <div className="mt-1 text-sm text-[#c7d7ee]">
            {money(item.plan.limit, item.plan.currency)} 지정가 · {money(a.notional_krw, "KRW")}
            <span className="text-[var(--muted)]"> · 손절 시 최대 {money(a.max_loss_krw, "KRW")}</span>
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
  const href = item.kind === "approval" ? `/inbox/${item.id}` : item.run_id ? `/records/${item.run_id}` : `/inbox/${item.id}`;
  return (
    <li>
      <Link href={href} className="flex items-start gap-2 px-3 py-2.5 hover:bg-[#1d2944]">
        <span aria-hidden="true" className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${item.read_at || item.status !== "INFO" ? "bg-transparent" : "bg-[var(--accent)]"}`} />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-sm">
            <span className={`truncate font-medium ${action ? ACTION_COLOR[action] ?? "" : ""}`}>{item.title}</span>
            {item.payload.demo && <span className="rounded bg-amber-400 px-1 text-[10px] font-bold text-black">DEMO</span>}
          </span>
          {item.summary && <span className="mt-0.5 block line-clamp-1 text-[12px] text-[var(--muted)]">{item.summary}</span>}
        </span>
        <span className="shrink-0 text-right text-[11px] text-[var(--muted)]">
          <span className={`inline-block rounded border px-1 ${STATUS_TONE[item.status]}`}>{STATUS_KO[item.status]}</span>
          <span className="mt-0.5 block">{kstDateTime(item.created_at)}</span>
        </span>
      </Link>
    </li>
  );
}
