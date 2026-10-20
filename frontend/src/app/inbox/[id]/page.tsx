"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { decideInbox, getBriefing, getInboxItem, markRead, type Briefing, type InboxItem } from "../../../lib/api";
import { approvalLine, buyPlan, deadlineLabel, kstDateTime, mockLine, MOCK_STATUS_KO, money, ORDER_STATUS_KO, paperLine, pnlTone, ROLE_KO,
         sellPlan, shares, signedWon, STATUS_KO, STATUS_TONE } from "../../../inbox/model";
import { FLAG_KO, RATING_KO } from "../../../office/explain";
import { humanizeTickers } from "../../../office/names";
import { MARKET_KO, marketOf, useMarket } from "../../../lib/market";
import NavBar from "../../NavBar";

type Act = "approve" | "defer" | "reject";
const ACT_KO: Record<Act, string> = { approve: "승인", defer: "보류", reject: "반려" };
/** On an auto-approved request the buttons record the CEO's view only; the order follows the model. */
const OPINION_KO: Record<Act, string> = { approve: "동의", defer: "보류", reject: "반대" };

/** 결재 문서: one approval request (or report) laid out like a paper document. */
export default function InboxDocument() {
  const { id } = useParams<{ id: string }>();
  const { setMarket, refreshPending } = useMarket();
  const [item, setItem] = useState<InboxItem | null>(null);
  const [briefing, setBriefing] = useState<Briefing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheet, setSheet] = useState<Act | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const requestIds = useMemo(() => ({ approve: crypto.randomUUID(), defer: crypto.randomUUID(),
                                      reject: crypto.randomUUID() }), []);

  useEffect(() => {
    getInboxItem(id).then((it) => {
      setItem(it);
      const m = marketOf(it.instrument_id);
      if (m) setMarket(m);  // opened from a notification: the switch follows the document
      if (!it.read_at) void markRead(it.id);
      if (it.run_id) getBriefing(it.run_id).then((b) => setBriefing(b.briefing?.status === "OK" ? b.briefing : null)).catch(() => {});
    }).catch((e: Error) => setError(e.message));
  }, [id, setMarket]);

  const decide = async (act: Act) => {
    if (!item) return;
    setBusy(true);
    try {
      setItem(await decideInbox(item.id, act, comment, requestIds[act]));
      refreshPending();
      setSheet(null);
    } catch (e) {
      setError(`처리하지 못했습니다: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const opinion = !!item?.opinion_open;
  const open = item && (item.status === "PENDING" || item.status === "DEFERRED" || opinion);
  const label = opinion ? OPINION_KO : ACT_KO;
  const p = buyPlan(item);
  const sp = sellPlan(item);
  const a = p?.allocation;
  const acct = p?.account_currency ?? "KRW";

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col">
      <NavBar />
      <div className="px-3 pt-3"><Link href="/" className="text-sm text-[var(--muted)]">← 결재함</Link></div>
      {error && <p role="alert" className="mx-3 mt-2 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!item && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}

      {item && (
        <article className={`m-3 rounded-xl border border-[var(--line)] bg-[#f6f3ea] text-[#1c1b17] shadow ${open ? "mb-28" : ""}`}>
          <header className="border-b border-[#d8d2c2] p-4">
            <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#6b6455]">
              {marketOf(item.instrument_id) && <span className="rounded bg-[#1c2a48] px-1.5 font-bold text-white">{MARKET_KO[marketOf(item.instrument_id)!]}</span>}
              <span>문서 #{item.id}</span><span>· 작성 {kstDateTime(item.created_at)}</span>
              {item.payload.demo && <span className="rounded bg-amber-400 px-1.5 font-bold text-black">DEMO · 연습 데이터</span>}
              {item.payload.trigger === "schedule" && <span className="rounded bg-[#e5efe6] px-1.5 text-[#2f6b3d]">정기 회의</span>}
            </div>
            <h1 className="mt-1 text-xl font-bold">{item.title}</h1>
            {item.kind === "approval" && <Stamps item={item} />}
            {item.kind === "approval" && item.mock_orders && item.mock_orders.length > 0 && (
              <p className="mt-3 rounded bg-[#e5efe6] px-2 py-1.5 text-sm font-semibold text-[#2f6b3d]">{mockLine(item.mock_orders)}</p>
            )}
            {item.kind === "approval" && item.paper && item.paper.length > 0 && (
              <p className="mt-3 rounded bg-[#e5efe6] px-2 py-1.5 text-sm font-semibold text-[#2f6b3d]">{paperLine(item.paper)}</p>
            )}
            {item.ceo_opinion && (
              <p className="mt-2 text-[13px] text-[#6b6455]">CEO 의견: <b className="text-[#1c1b17]">{OPINION_KO[item.ceo_opinion as Act]}</b> (기록만 · 모의 주문은 결재안대로)</p>
            )}
          </header>

          {p && a && !a.blocked && <BuySummary p={p} a={a} acct={acct} expires={item.expires_at} />}
          {sp && (
            <section className="border-b border-[#d8d2c2] bg-[#fbf9f3] p-4">
              <div className="text-[11px] font-semibold text-[#6b6455]">핵심 요약 · 매도</div>
              <div className="mt-1 text-lg font-bold">전량 매도 {shares(sp.qty)}</div>
              <div className="text-sm text-[#6b6455]">평가 {money(sp.value_krw, sp.account_currency ?? "KRW")} · 평균 매수가 {money(sp.avg_price, sp.currency)} · {sp.venue === "kiwoom_mock" ? "장중 키움 모의 매도" : "다음 장 시가"}</div>
            </section>
          )}

          <section className="space-y-3 p-4">
            {(item.summary || briefing?.headline) && (
              <p className="border-l-4 border-[#c9bfa6] pl-3 text-[15px] font-semibold leading-snug">{humanizeTickers(briefing?.headline || item.summary)}</p>
            )}
            {item.payload.note && <p className="rounded bg-[#ece7da] p-2 text-sm">{item.payload.note}</p>}
            {item.payload.review_reasons && item.payload.review_reasons.length > 0 && (
              <div className="rounded border border-amber-600 bg-amber-50 p-2 text-sm">
                <div className="font-semibold text-amber-800">검토 필요 · 결재할 수 없음</div>
                <ul className="mt-1 list-disc pl-5">{item.payload.review_reasons.map((r) => <li key={r}>{r}</li>)}</ul>
              </div>
            )}
            {briefing && (
              <>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Points title="이유" items={briefing.key_reasons} tone="text-[#2f6b3d]" />
                  <Points title="위험" items={briefing.risks} tone="text-[#9b2f3a]" />
                </div>
                {briefing.watch_next.length > 0 && (
                  <Fold title={`확인할 것 ${briefing.watch_next.length}`}>
                    <ul className="space-y-1 text-[13px] leading-snug">{briefing.watch_next.map((x) => <li key={x}>· {humanizeTickers(x)}</li>)}</ul>
                  </Fold>
                )}
              </>
            )}
          </section>

          {p && a && (
            <section className="space-y-2 border-t border-[#d8d2c2] p-4">
              {a.blocked && <p className="rounded bg-[#ece7da] p-2 text-sm"><b>매수 불가</b> · {a.blocked}</p>}
              <Fold title="매매 조건 상세" hint={`${p.rating ? `${RATING_KO[p.rating] ?? p.rating} · ` : ""}AI 제시와 규정 기본값 구분`}>
                <table className="w-full text-sm">
                  <tbody className="[&_td]:py-1.5 [&_tr]:border-b [&_tr]:border-[#e4dfd1]">
                    <Row label="진입 (지정가)" value={money(p.limit, p.currency)} source={p.sources.limit} />
                    <Row label="목표가" value={money(p.target, p.currency)} source={p.sources.target}
                         note={`+${(((Number(p.target) / Number(p.limit)) - 1) * 100).toFixed(1)}%`} />
                    <Row label="손절가" value={money(p.stop, p.currency)} source={p.sources.stop}
                         note={`−${(Number(p.stop_distance) * 100).toFixed(1)}%`} />
                    {!a.blocked && (
                      <>
                        <Row label="수량" value={shares(a.qty)} note={Number.isInteger(Number(a.qty)) ? undefined : "소수점 수량"} />
                        <Row label="금액" value={money(a.notional_krw, acct)}
                             note={p.currency === "USD" && acct === "KRW" ? `${money(a.notional, "USD")} · 환율 ${Number(p.fx_krw_per_unit).toLocaleString("ko-KR")}원` : undefined} />
                        <Row label="최대 손실" value={money(a.max_loss_krw, acct)} note="손절 시" />
                      </>
                    )}
                    <Row label="유효기간" value={item.expires_at ? kstDateTime(item.expires_at) + "까지" : "—"} />
                  </tbody>
                </table>
                <p className="mt-1 text-[11px] text-[#6b6455]">기준가 {money(p.ref_price, p.currency)} ({kstDateTime(p.ref_at)}, 회의에 쓰인 시세)
                  {p.horizon ? ` · 기간 ${p.horizon}` : ""}</p>
              </Fold>
              <Fold title="비중 계산" hint={`${a.binding} 적용 · ${p.policy_version}`}>
                <ul className="space-y-1 text-[13px]">
                  {a.lines.map(([label, value]) => (
                    <li key={label} className={`flex justify-between gap-2 rounded px-2 py-1 ${label === a.binding ? "bg-[#fff3c4] font-semibold" : ""}`}>
                      <span>{label}{label === a.binding ? " ← 적용" : ""}</span><span className="whitespace-nowrap">{money(value, acct)} 이하</span>
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-[11px] text-[#6b6455]">AI 제시 비중: {p.sizing_text ?? "없음"} → 배수 {p.multiplier} ({p.multiplier_source === "ai" ? "AI 제시" : "규정 기본값"}). {p.account_basis}</p>
              </Fold>
            </section>
          )}

          {item.mock_orders && item.mock_orders.length > 0 && (
            <section className="border-t border-[#d8d2c2] p-4">
              <h2 className="mb-2 text-sm font-bold">키움 모의 주문 <span className="font-normal text-[#6b6455]">({marketOf(item.instrument_id) === "US" ? "미장" : "국장"} 계좌 · 모의투자 서버)</span></h2>
              <ul className="space-y-1.5 text-[13px]">
                {item.mock_orders.map((o) => (
                  <li key={o.id} className="flex flex-wrap items-baseline justify-between gap-x-2 rounded bg-[#ece7da] px-2 py-1.5">
                    <span><b>{ROLE_KO[o.role]}</b> {o.qty ? shares(o.qty) : "수량 계산 전"}{o.limit_price ? ` · 지정가 ${money(o.limit_price, o.currency)}` : ""}</span>
                    <span className={o.status === "FILLED" ? "font-semibold text-[#2f6b3d]" : o.status === "SENT" || o.status === "WAITING" ? "text-[#2b5c8a]" : "text-[#6b6455]"}>
                      {MOCK_STATUS_KO[o.status]}{o.fill_price ? ` @ ${money(o.fill_price, o.currency)}` : ""}{o.ext_order_no ? ` · #${o.ext_order_no}` : ""}
                    </span>
                    {o.reason && <span className="w-full text-[11px] text-[#6b6455]">{o.reason}</span>}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-[#6b6455]">정규장에만 주문합니다. 체결은 키움 모의 계좌의 체결 내역으로 확인하고, 보유 중에는 목표가·손절가에 닿으면 매도합니다. <Link href="/portfolio" className="underline">포트폴리오 보기</Link></p>
            </section>
          )}

          {item.paper && item.paper.length > 0 && (
            <section className="border-t border-[#d8d2c2] p-4">
              <h2 className="mb-2 text-sm font-bold">모의 주문 <span className="font-normal text-[#6b6455]">(가상 계좌 · 실제 주문 아님)</span></h2>
              <ul className="space-y-1.5 text-[13px]">
                {item.paper.map((o) => (
                  <li key={o.id} className="flex flex-wrap items-baseline justify-between gap-x-2 rounded bg-[#ece7da] px-2 py-1.5">
                    <span><b>{ROLE_KO[o.role]}</b> {shares(o.qty)}{o.price ? ` · ${o.role === "stop" ? "손절가" : o.role === "take_profit" ? "목표가" : "지정가"} ${money(o.price, o.currency)}` : " · 시가"}</span>
                    <span className={o.status === "FILLED" ? "font-semibold text-[#2f6b3d]" : o.status === "OPEN" ? "text-[#2b5c8a]" : "text-[#6b6455]"}>
                      {ORDER_STATUS_KO[o.status]}
                      {o.fill ? ` @ ${money(o.fill.price, o.currency)} · ${o.fill.session}` : ""}
                      {o.fill?.realized_krw ? <span className={`ml-1 ${pnlTone(o.fill.realized_krw).replace("300", "700")}`}>{signedWon(o.fill.realized_krw)}</span> : null}
                    </span>
                    {o.reason && <span className="w-full text-[11px] text-[#6b6455]">{o.reason}</span>}
                  </li>
                ))}
              </ul>
              <p className="mt-2 text-[11px] text-[#6b6455]">장 마감 후 그날 일봉으로 체결을 판정합니다 (같은 날 목표가·손절가가 모두 닿으면 손절로 처리). <Link href="/portfolio" className="underline">포트폴리오 보기</Link></p>
            </section>
          )}

          {item.payload.risk_flags && item.payload.risk_flags.length > 0 && (
            <section className="border-t border-[#d8d2c2] p-4 text-[13px]">
              <Fold title={`데이터 주의 ${item.payload.risk_flags.length}`}>
                <ul className="list-disc pl-5 text-[#6b6455]">{item.payload.risk_flags.map((f) => <li key={f}>{FLAG_KO[f] ?? f}</li>)}</ul>
              </Fold>
            </section>
          )}

          <footer className="flex flex-wrap items-center justify-between gap-2 border-t border-[#d8d2c2] p-4 text-sm">
            {item.run_id && <Link href={`/records/${item.run_id}`} className="font-semibold text-[#2b5c8a] underline">📎 회의록 보기</Link>}
            {(item.kind === "execution" || item.kind === "closing") && <Link href="/portfolio" className="font-semibold text-[#2b5c8a] underline">📊 포트폴리오 보기</Link>}
            <span className={`rounded border px-2 py-0.5 text-xs ${STATUS_TONE[item.status].replace(/text-[^ ]+/, "")} text-[#1c1b17]`}>
              {STATUS_KO[item.status]}{item.decided_at ? ` · ${kstDateTime(item.decided_at)}` : ""}
            </span>
          </footer>
          {item.approvals.length > 0 && (
            <ul className="border-t border-[#d8d2c2] px-4 py-3 text-[13px] text-[#6b6455]">
              {item.approvals.map((ap) => (
                <li key={ap.decided_at}>{ap.auto ? "자동 승인" : ap.opinion ? `CEO 의견 · ${OPINION_KO[ap.action as Act] ?? ap.action}` : `CEO ${ACT_KO[ap.action as Act] ?? ap.action}`} · {kstDateTime(ap.decided_at)}{ap.comment ? ` — “${ap.comment}”` : ""}</li>
              ))}
            </ul>
          )}
          {item.status === "APPROVED" && item.payload.demo && (
            <p className="border-t border-[#d8d2c2] px-4 py-3 text-[12px] text-[#6b6455]">DEMO 문서는 연습 데이터라 모의 계좌에 주문을 넣지 않습니다.</p>
          )}
        </article>
      )}

      {open && item && (
        <div className="fixed inset-x-0 bottom-[calc(3.6rem+env(safe-area-inset-bottom))] z-40 border-t border-[var(--line)] bg-[#0b1020]/95 p-3 backdrop-blur sm:bottom-0">
          <div className="mx-auto max-w-2xl">
            <p className="mb-2 text-center text-xs text-amber-200">
              {opinion ? `자동 승인됨 · 모의 주문은 결재안대로 진행, CEO 의견만 기록 · ${deadlineLabel(item.expires_at)}` : deadlineLabel(item.expires_at)}
            </p>
            {sheet ? (
              <div className="space-y-2">
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={2} maxLength={500}
                          placeholder="의견 (선택)" className="w-full rounded bg-[var(--panel)] p-2 text-sm" />
                <div className="flex gap-2">
                  <button onClick={() => setSheet(null)} className="flex-1 rounded border border-[var(--line)] py-2 text-sm">취소</button>
                  <button disabled={busy} onClick={() => void decide(sheet)}
                          className={`flex-[2] rounded py-2 text-sm font-semibold text-black disabled:opacity-50 ${sheet === "approve" ? "bg-emerald-400" : sheet === "reject" ? "bg-rose-400" : "bg-sky-300"}`}>
                    {label[sheet]} 확정
                  </button>
                </div>
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-2">
                <button onClick={() => setSheet("reject")} className="rounded border border-rose-400 py-2.5 text-sm font-semibold text-rose-300">{label.reject}</button>
                <button onClick={() => setSheet("defer")} className="rounded border border-sky-400 py-2.5 text-sm font-semibold text-sky-200">{label.defer}</button>
                <button onClick={() => setSheet("approve")} className="rounded bg-emerald-400 py-2.5 text-sm font-semibold text-black">{label.approve}</button>
              </div>
            )}
          </div>
        </div>
      )}
    </main>
  );
}

function Stamps({ item }: { item: InboxItem }) {
  const line = approvalLine(item);
  return (
    <ol aria-label="결재선" className="mt-3 flex flex-wrap items-center gap-0.5 sm:gap-1.5">
      {line.map((s, i) => {
        const look = s.state === "done" ? "border-[#2f6b3d] text-[#2f6b3d]"
          : s.state === "draft" ? "border-[#2b5c8a] text-[#2b5c8a]"
          : s.state === "waiting" ? "border-dashed border-amber-600 text-amber-700"
          : s.state === "APPROVED" ? "border-[#2f6b3d] bg-[#2f6b3d] text-white"
          : s.state === "REJECTED" ? "border-[#9b2f3a] bg-[#9b2f3a] text-white"
          : "border-[#9a9384] text-[#9a9384]";
        const mark = s.state === "done" ? "✓" : s.state === "draft" ? "기안" : s.state === "waiting" ? "대기"
          : s.state === "APPROVED" && item.auto_approved ? "자동"
          : STATUS_KO[s.state as keyof typeof STATUS_KO] ?? "";
        return (
          <li key={s.who} className="flex items-center gap-0.5 sm:gap-1.5">
            <span className={`flex h-11 w-11 flex-col items-center justify-center rounded-full border-2 text-[9px] leading-tight sm:h-12 sm:w-12 sm:text-[10px] ${look}`}>
              <span className="font-bold">{s.who}</span><span>{mark}</span>
            </span>
            {i < line.length - 1 && <span aria-hidden="true" className="text-[11px] text-[#b9b2a2]">›</span>}
          </li>
        );
      })}
    </ol>
  );
}

function Points({ title, items, tone }: { title: string; items: string[]; tone: string }) {
  if (items.length === 0) return null;
  return (
    <div>
      <h3 className={`mb-1 text-xs font-bold ${tone}`}>{title}</h3>
      <ul className="space-y-1 text-[13px] leading-snug">{items.map((x) => <li key={x}>· {humanizeTickers(x)}</li>)}</ul>
    </div>
  );
}

/** The decision in a glance: what, how much, upside, downside, worst case, deadline. */
function BuySummary({ p, a, acct, expires }: { p: NonNullable<ReturnType<typeof buyPlan>>; a: NonNullable<ReturnType<typeof buyPlan>>["allocation"];
                                               acct: "KRW" | "USD"; expires: string | null }) {
  const up = ((Number(p.target) / Number(p.limit)) - 1) * 100;
  const down = Number(p.stop_distance) * 100;
  return (
    <section className="border-b border-[#d8d2c2] bg-[#fbf9f3] p-4">
      <div className="text-[11px] font-semibold text-[#6b6455]">핵심 요약 · 매수</div>
      <div className="mt-1 flex flex-wrap items-baseline gap-x-2">
        <span className="text-lg font-bold">{shares(a.qty)} × {money(p.limit, p.currency)}</span>
        <span className="text-sm text-[#6b6455]">지정가 · 총 {money(a.notional_krw, acct)}</span>
      </div>
      <dl className="mt-2 grid grid-cols-3 gap-2 text-center">
        <Tile label="목표가" value={money(p.target, p.currency)} sub={`+${up.toFixed(1)}%`} tone="text-[#2f6b3d]" />
        <Tile label="손절가" value={money(p.stop, p.currency)} sub={`−${down.toFixed(1)}%`} tone="text-[#9b2f3a]" />
        <Tile label="최대 손실" value={money(a.max_loss_krw, acct)} sub="손절 시" tone="text-[#9b2f3a]" />
      </dl>
      <p className="mt-2 text-[12px] text-[#6b6455]">
        {p.rating ? `AI 등급 ${RATING_KO[p.rating] ?? p.rating}` : ""}{p.horizon ? ` · 기간 ${p.horizon}` : ""}{expires ? ` · ${kstDateTime(expires)}까지 유효` : ""}
      </p>
    </section>
  );
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: string }) {
  return (
    <div className="rounded-lg bg-[#efe9da] px-1 py-1.5">
      <dt className="text-[10px] text-[#6b6455]">{label}</dt>
      <dd className="text-[13px] font-bold leading-tight">{value}</dd>
      <dd className={`text-[11px] font-semibold ${tone}`}>{sub}</dd>
    </div>
  );
}

/** A folded section: the title (and a one-line hint) shows; the details open on tap. */
function Fold({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <details className="group rounded-lg border border-[#e1dac9] bg-[#faf7ef] px-3 py-2">
      <summary className="flex cursor-pointer list-none items-baseline justify-between gap-2">
        <span className="shrink-0 whitespace-nowrap text-sm font-bold">{title}</span>
        <span className="min-w-0 flex-1 truncate text-right text-[11px] text-[#6b6455]">{hint}</span>
        <span aria-hidden="true" className="text-[#6b6455] transition-transform group-open:rotate-90">›</span>
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

function Row({ label, value, source, note }: { label: string; value: string; source?: "ai" | "policy"; note?: string }) {
  return (
    <tr>
      <td className="whitespace-nowrap pr-3 text-[#6b6455]">{label}</td>
      <td className="font-semibold">{value}{note && <span className="ml-1 text-xs font-normal text-[#6b6455]">{note}</span>}</td>
      <td className="whitespace-nowrap text-right">
        {source && <span className={`whitespace-nowrap rounded px-1 py-0.5 text-[10px] ${source === "ai" ? "bg-[#dde8f3] text-[#2b5c8a]" : "bg-[#efe6cf] text-[#7a5a17]"}`}>
          {source === "ai" ? "AI 제시" : "규정 기본값"}</span>}
      </td>
    </tr>
  );
}
