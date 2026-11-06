/** CEO inbox and records: pure helpers (sorting, deadlines, stamps, grouping), unit-tested. */
import type { ApprovalPlan, InboxItem, InboxStatus, MockOrder, MockOrderStatus, OfficeNow, OrderRole, OrderStatus, PaperOrder, RecordRow,
              SellPlan } from "../lib/api";

const TZ = "Asia/Seoul";

export const STATUS_KO: Record<InboxStatus, string> = {
  PENDING: "결재 대기", DEFERRED: "보류", APPROVED: "승인", REJECTED: "반려", EXPIRED: "만료",
  INFO: "참고",
};

export const STATUS_TONE: Record<InboxStatus, string> = {
  PENDING: "border-amber-400 text-amber-200", DEFERRED: "border-sky-400 text-sky-200",
  APPROVED: "border-emerald-400 text-emerald-300", REJECTED: "border-rose-400 text-rose-300",
  EXPIRED: "border-slate-500 text-slate-400", INFO: "border-[var(--line)] text-[var(--muted)]",
};

export interface InboxGroups {
  pending: InboxItem[];   // needs a decision, soonest deadline first
  active: InboxItem[];    // approved, and its orders are not finished (waiting, sent, held)
  reports: InboxItem[];   // reports, unread first, newest first (order news lives on the cards)
  done: InboxItem[];      // decided or expired, newest first
}

const OPEN_ORDER = new Set(["WAITING", "SENDING", "SENT", "REVIEW"]);

/** An approved plan whose Kiwoom orders are still going: waiting, sent, or a position held
 *  (bought, not yet sold and not folded into a later add-on). */
export function isActive(item: InboxItem): boolean {
  if (item.kind !== "approval" || item.status !== "APPROVED") return false;
  const orders = item.mock_orders ?? [];
  if (orders.some((o) => OPEN_ORDER.has(o.status))) return true;
  const entry = orders.find((o) => o.role === "entry" && o.status === "FILLED");
  const sold = orders.some((o) => o.side === "SELL" && o.status === "FILLED");
  return Boolean(entry && !entry.detail?.closed && !sold);
}

const t = (iso: string | null) => (iso ? Date.parse(iso) : Number.POSITIVE_INFINITY);

export function groupInbox(items: InboxItem[]): InboxGroups {
  const pending = items.filter((i) => i.status === "PENDING" || i.status === "DEFERRED")
    .sort((a, b) => t(a.expires_at) - t(b.expires_at));
  const active = items.filter(isActive)
    .sort((a, b) => t(b.created_at) - t(a.created_at));
  // Order news ([주문]·[체결]·[미체결]·[청산]) is shown on its plan's card and in the closing
  // report, so the report list keeps the desk's reports only (owner, 2026-10-21).
  const reports = items.filter((i) => i.status === "INFO" && i.kind !== "execution")
    .sort((a, b) => Number(Boolean(a.read_at)) - Number(Boolean(b.read_at)) ||
                    t(b.created_at) - t(a.created_at));
  const done = items.filter((i) => ["APPROVED", "REJECTED", "EXPIRED"].includes(i.status) &&
                                   !isActive(i))
    .sort((a, b) => t(b.decided_at ?? b.expires_at ?? b.created_at) -
                    t(a.decided_at ?? a.expires_at ?? a.created_at));
  return { pending, active, reports, done };
}

function kstParts(ms: number): { day: string; time: string; md: string } {
  const d = new Date(ms);
  return {
    day: d.toLocaleDateString("en-CA", { timeZone: TZ }),
    time: d.toLocaleTimeString("ko-KR", { timeZone: TZ, hour: "2-digit", minute: "2-digit", hour12: false }),
    md: d.toLocaleDateString("ko-KR", { timeZone: TZ, month: "numeric", day: "numeric" }),
  };
}

/** "오늘 15:30까지 · 3시간 남음", "내일 05:00까지", "만료". */
export function deadlineLabel(expiresIso: string | null, nowMs: number = Date.now()): string {
  if (!expiresIso) return "";
  const end = Date.parse(expiresIso);
  if (end <= nowMs) return "만료";
  const e = kstParts(end);
  const today = kstParts(nowMs).day;
  const tomorrow = kstParts(nowMs + 86_400_000).day;
  const when = e.day === today ? "오늘" : e.day === tomorrow ? "내일" : e.md;
  const mins = Math.round((end - nowMs) / 60_000);
  const left = mins < 60 ? `${mins}분 남음` : mins < 48 * 60 ? `${Math.floor(mins / 60)}시간 남음` : "";
  return `${when} ${e.time}까지${left ? ` · ${left}` : ""}`;
}

export function kstDateTime(iso: string | null): string {
  if (!iso) return "—";
  const p = kstParts(Date.parse(iso));
  return `${p.md} ${p.time}`;
}

/** "4" → "4주", "0.4967" → "0.4967주" (fractional US shares). */
export function shares(qty: string | number): string {
  const n = Number(qty);
  if (!Number.isFinite(n)) return `${qty}주`;
  return `${Number.isInteger(n) ? n.toLocaleString("ko-KR") : n.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}주`;
}

/** 240000 KRW → "240,000원"; USD → "$224.33". */
export function money(value: string | number, currency: "KRW" | "USD"): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return currency === "KRW"
    ? `${Math.round(n).toLocaleString("ko-KR")}원`
    : `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export interface Stamp { who: string; state: "done" | "draft" | "waiting" | InboxStatus }

/** Approval line: the departments that worked on it, the drafter, then the CEO. */
export function approvalLine(item: InboxItem): Stamp[] {
  const ceo: Stamp["state"] = item.status === "PENDING" ? "waiting" : item.status;
  return [
    { who: "분석팀", state: "done" }, { who: "리서치", state: "done" },
    { who: "트레이딩", state: "done" }, { who: "리스크", state: "done" },
    { who: "PM", state: "draft" }, { who: "CEO", state: ceo },
  ];
}

/** Records grouped by Korean calendar day, newest day first (rows keep their order). */
export function groupRecordsByDay(rows: RecordRow[]): { day: string; label: string; rows: RecordRow[] }[] {
  const out: { day: string; label: string; rows: RecordRow[] }[] = [];
  for (const r of rows) {
    const p = kstParts(Date.parse(r.requested_at));
    const last = out[out.length - 1];
    if (last && last.day === p.day) last.rows.push(r);
    else {
      const weekday = new Date(Date.parse(r.requested_at)).toLocaleDateString("ko-KR", { timeZone: TZ, weekday: "short" });
      out.push({ day: p.day, label: `${p.md} (${weekday})`, rows: [r] });
    }
  }
  return out;
}

// ---------------------------------------------------------------- paper book

export const ROLE_KO: Record<OrderRole, string> = { entry: "매수", take_profit: "익절", stop: "손절", exit: "매도" };
export const ORDER_STATUS_KO: Record<OrderStatus, string> = {
  OPEN: "대기", FILLED: "체결", CANCELLED: "취소", EXPIRED: "미체결", REJECTED: "거절",
};

export const MOCK_STATUS_KO: Record<MockOrderStatus, string> = {
  WAITING: "주문 대기", SENDING: "주문 중", SENT: "주문 접수", FILLED: "체결", CANCELLED: "취소(재주문)",
  EXPIRED: "미체결 취소", REJECTED: "거절", REVIEW: "확인 필요",
};

/** One line on what the Kiwoom mock desk did with an approved document. */
export function mockLine(orders: MockOrder[] | undefined): string | null {
  const main = orders?.find((o) => o.role === "entry" || o.role === "exit");
  if (!main) return null;
  const what = main.role === "exit" ? "전량 매도" : "매수";
  const qty = main.qty ? `${shares(main.qty)} ` : "";
  const px = main.limit_price ? `지정가 ${money(main.limit_price, main.currency)}` : "";
  switch (main.status) {
    case "WAITING":
      return `키움 모의 ${what} 대기 · 장이 열리면 계좌 기준으로 수량을 다시 계산해 주문`;
    case "SENDING":
    case "SENT":
      return `키움 모의 ${what} 주문 접수 · ${qty}${px}${main.valid_until ? ` · ${kstDateTime(main.valid_until)}까지` : ""}`;
    case "FILLED": {
      const exit = orders?.find((o) => (o.role === "take_profit" || o.role === "stop") && o.status === "FILLED");
      const base = `키움 모의 ${what} 체결 ${shares(main.filled_qty)} @ ${money(main.fill_price ?? 0, main.currency)}`;
      if (exit?.fill_price) return `${base} → ${ROLE_KO[exit.role]} @ ${money(exit.fill_price, exit.currency)}`;
      if (main.role !== "entry") return base;
      return main.detail?.breakeven
        ? `${base} · 보유 중 · 손절가를 매수가로 올림`
        : `${base} · 보유 중 (목표가·손절가 감시)`;
    }
    case "EXPIRED":
      return `미체결 · ${main.reason || "기한까지 가격이 닿지 않음"}`;
    case "REJECTED":
      return `주문 안 함 · ${main.reason}`;
    case "REVIEW":
      return `확인 필요 · ${main.reason}`;
    default:
      return `${MOCK_STATUS_KO[main.status]} · ${main.reason}`;
  }
}

export interface ActiveStock {
  item: InboxItem;        // the newest plan for the stock (the card links to it)
  plans: number;          // how many running plans are folded into this card
  line: string;           // the stock's state now
}

/** 진행 중, one card per stock (owner, 2026-10-21): an add-on plan joins the held position when
 *  it fills, so the card shows the position as it is now plus what is still waiting. */
export function groupActive(items: InboxItem[]): ActiveStock[] {
  const by = new Map<string, InboxItem[]>();
  for (const i of items) {
    const key = i.instrument_id ?? `#${i.id}`;
    by.set(key, [...(by.get(key) ?? []), i]);
  }
  const out: ActiveStock[] = [];
  for (const group of by.values()) {
    const plans = [...group].sort((a, b) => t(a.created_at) - t(b.created_at));
    const newest = plans[plans.length - 1]!;
    if (plans.length === 1) {
      out.push({ item: newest, plans: 1, line: mockLine(newest.mock_orders) ?? "" });
      continue;
    }
    const parts: string[] = [];
    let held = 0;
    let cost = 0;
    let cur: "KRW" | "USD" = "USD";
    let breakeven = false;
    for (const p of plans) {
      for (const o of p.mock_orders ?? []) {
        cur = o.currency;
        if (o.role === "entry" && o.status === "FILLED" && !o.detail?.closed) {
          held += Number(o.filled_qty);
          cost += Number(o.filled_qty) * Number(o.fill_price ?? 0);
          breakeven = breakeven || Boolean(o.detail?.breakeven);
        }
      }
    }
    if (held > 0) {
      parts.push(`보유 ${shares(String(held))} · 평균 ${money(String(cost / held), cur)}`
                 + (breakeven ? " · 손절가를 매수가로 올림" : " · 목표가·손절가 감시"));
    }
    for (const p of plans) {
      for (const o of p.mock_orders ?? []) {
        if (!["WAITING", "SENDING", "SENT", "REVIEW"].includes(o.status)) continue;
        const what = o.side === "SELL" ? "매도" : held > 0 ? "추가 매수" : "매수";
        const qty = o.qty ? ` ${shares(o.qty)}` : "";
        const px = o.limit_price ? ` 지정가 ${money(o.limit_price, o.currency)}` : "";
        const state = o.status === "WAITING" ? "대기(장이 열리면 주문)" : o.status === "REVIEW" ? "확인 필요" : "주문 중";
        parts.push(`${what}${qty}${px} ${state}`);
      }
    }
    out.push({ item: newest, plans: plans.length, line: parts.join(" · ") });
  }
  return out.sort((a, b) => t(b.item.created_at) - t(a.item.created_at));
}

/** "엔비디아 회의" / "국내 장 마감 정산": the next scheduled job, by kind. */
export function nextWorkLabel(n: OfficeNow["next"][number], meeting = "회의"): string {
  return n.kind === "settle" || n.kind === "research" ? n.name : `${n.name} ${meeting}`;
}

const OPINION_SHORT: Record<string, string> = { approve: "CEO 동의", reject: "CEO 반대", defer: "CEO 보류" };

/** Small print beside an approval status: "자동 승인 · 체결 · CEO 반대" (records and minutes). */
export function approvalNote(auto: boolean | undefined, paper: OrderStatus | null | undefined,
                             opinion: string | null | undefined): string {
  return [auto ? "자동 승인" : null, paper ? `모의 ${ORDER_STATUS_KO[paper]}` : null,
          opinion ? OPINION_SHORT[opinion] ?? null : null].filter(Boolean).join(" · ");
}

/** The paper status of a document's main order (entry or exit). */
export function mainPaperStatus(item: InboxItem): OrderStatus | null {
  return item.paper?.find((o) => o.role === "entry" || o.role === "exit")?.status ?? null;
}

/** How a simulated fill was decided from the day's bar (paper/fills.py). */
export const FILL_RULE_KO: Record<string, string> = {
  open_at_or_below_limit: "시가가 지정가 이하 → 시가 체결",
  low_touched_limit: "저가가 지정가 도달",
  gap_below_stop: "시가가 손절가 아래 → 시가 손절",
  gap_above_target: "시가가 목표가 위 → 시가 익절",
  low_touched_stop: "저가가 손절가 도달",
  high_touched_target: "고가가 목표가 도달",
  sold_at_open: "시가 매도",
};

export function sellPlan(item: InboxItem | null): SellPlan | null {
  return item?.plan && item.plan.side === "SELL" ? (item.plan as SellPlan) : null;
}

export function buyPlan(item: InboxItem | null): ApprovalPlan | null {
  return item?.plan && item.plan.side !== "SELL" && item.plan.side !== "ADJUST"
    ? (item.plan as ApprovalPlan) : null;
}

/** A held stock's stop/target change (the meeting said 유지 and gave new levels). */
export interface AdjustPlan {
  side: "ADJUST";
  currency: "KRW" | "USD";
  stop_from: string;
  stop: string;
  target_from: string;
  target: string;
  qty: string | null;
  avg_price: string | null;
  last_price: string | null;
  rule: string;
  execution: string;
}

export function adjustPlan(item: InboxItem | null): AdjustPlan | null {
  return item?.plan && (item.plan.side as string) === "ADJUST" ? (item.plan as unknown as AdjustPlan) : null;
}

/** "손절가 $520.00 → $530.00 · 목표가 $580.00 → $600.00" (unchanged levels say so). */
export function adjustLine(p: AdjustPlan): string {
  const part = (label: string, from: string, to: string) =>
    from === to ? `${label} ${money(to, p.currency)} 유지` : `${label} ${money(from, p.currency)} → ${money(to, p.currency)}`;
  return `${part("손절가", p.stop_from, p.stop)} · ${part("목표가", p.target_from, p.target)}`;
}

/** "+12,300원" / "−4,500원" (whole won, explicit sign). */
export function signedWon(value: string | number): string {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return String(value);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toLocaleString("ko-KR")}원`;
}

/** "+1.25%" / "−0.40%". */
export function signedPct(value: string | number): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(2)}%`;
}

export function pnlTone(value: string | number): string {
  const n = Number(value);
  return n > 0 ? "text-emerald-300" : n < 0 ? "text-rose-300" : "";
}

/** One line on what the paper book did with an approved document. */
export function paperLine(orders: PaperOrder[] | undefined): string | null {
  const main = orders?.find((o) => o.role === "entry" || o.role === "exit");
  if (!main) return null;
  const what = main.role === "exit" ? "전량 매도" : `매수 ${shares(main.qty)}`;
  switch (main.status) {
    case "OPEN":
      return main.role === "exit"
        ? `모의 매도 예약 · ${kstDateTime(main.active_from)} 장 시작 시가에 ${shares(main.qty)}`
        : `모의 예약 주문 접수 · ${what} 지정가 ${money(main.price ?? 0, main.currency)} · ${kstDateTime(main.active_from)}~${kstDateTime(main.valid_until)}`;
    case "FILLED": {
      const exit = orders?.find((o) => (o.role === "take_profit" || o.role === "stop") && o.status === "FILLED");
      const base = `${what} 체결 @ ${money(main.fill?.price ?? main.price ?? 0, main.currency)}`;
      if (exit?.fill?.realized_krw) return `${base} → ${ROLE_KO[exit.role]} ${signedWon(exit.fill.realized_krw)}`;
      if (main.fill?.realized_krw) return `${base} · ${signedWon(main.fill.realized_krw)}`;
      return main.role === "entry" ? `${base} · 보유 중` : base;
    }
    case "EXPIRED":
      return `미체결 · ${main.reason || "가격이 닿지 않음"}`;
    case "REJECTED":
      return `리스크 거절 · ${main.reason}`;
    default:
      return `${ORDER_STATUS_KO[main.status]} · ${main.reason}`;
  }
}

/** The approval in plain words, from the plan's own numbers (owner, 2026-11-06: the approval
 *  document is the easy version; the expert plan stays below as the record). No model. */
export function plainPlan(item: InboxItem, deadline = ""): string[] {
  const name = item.payload.name ?? "이 종목";
  const buy = buyPlan(item);
  const sell = sellPlan(item);
  const adj = adjustPlan(item);
  if (adj) {
    const line = (what: string, from: string, to: string) =>
      from === to ? `'${what}' 선은 ${money(to, adj.currency)} 그대로 둬요.`
                  : `'${what}' 선을 ${money(from, adj.currency)}에서 ${money(to, adj.currency)}${adj.currency === "KRW" ? "으로" : "로"} 바꿔요.`;
    return [`${name}을(를) 계속 갖고 가요.`, line("여기까지 떨어지면 판다", adj.stop_from, adj.stop),
            line("여기까지 오르면 판다", adj.target_from, adj.target),
            "회사 규칙상 '떨어지면 판다' 선은 올리기만 해요. 손해 볼 수 있는 폭을 줄이는 쪽으로만 움직여요."];
  }
  if (sell) {
    const acct = sell.account_currency ?? "KRW";
    return [`${name} 갖고 있는 ${shares(sell.qty)}를 전부 팔아요.`,
            `지금 값어치는 약 ${money(sell.value_krw, acct)}이고, 평균 ${money(sell.avg_price, sell.currency)}에 샀어요.`,
            sell.venue === "kiwoom_mock" ? "장이 열려 있는 동안 지금 가격 근처로 팔아요." : "다음 장이 열릴 때 팔아요."];
  }
  if (!buy) return [];
  const a = buy.allocation;
  const acct = buy.account_currency ?? "KRW";
  if (a.blocked) return [`${name}을(를) 사자는 의견이었지만, 이번에는 살 수 없어요: ${a.blocked}`];
  const up = ((Number(buy.target) / Number(buy.limit)) - 1) * 100;
  const down = Number(buy.stop_distance) * 100;
  const addOn = (item.plan as { add_on?: boolean; held_qty?: string } | null);
  return [
    `${name} ${shares(a.qty)}를 한 주에 ${money(buy.limit, buy.currency)} 이하로 사요. 모두 ${money(a.notional_krw, acct)}이에요.`
      + (addOn?.add_on ? ` 이미 ${shares(addOn.held_qty ?? "0")}를 갖고 있어서 조금 더 사는 거예요.` : ""),
    `${money(buy.target, buy.currency)}까지 오르면 팔아서 이익을 챙겨요(산 값보다 약 ${up.toFixed(1)}% 위).`,
    `${money(buy.stop, buy.currency)}까지 떨어지면 팔아서 손해를 막아요(약 ${down.toFixed(1)}% 아래). 그때 손해는 최대 ${money(a.max_loss_krw, acct)}이에요.`,
    ...(deadline ? [`${deadline}까지 그 가격에 사지 못하면 주문은 취소돼요.`] : []),
  ];
}
