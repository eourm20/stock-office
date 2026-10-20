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
  reports: InboxItem[];   // reports, unread first, newest first
  done: InboxItem[];      // decided or expired, newest first
}

const t = (iso: string | null) => (iso ? Date.parse(iso) : Number.POSITIVE_INFINITY);

export function groupInbox(items: InboxItem[]): InboxGroups {
  const pending = items.filter((i) => i.status === "PENDING" || i.status === "DEFERRED")
    .sort((a, b) => t(a.expires_at) - t(b.expires_at));
  const reports = items.filter((i) => i.status === "INFO")
    .sort((a, b) => Number(Boolean(a.read_at)) - Number(Boolean(b.read_at)) ||
                    t(b.created_at) - t(a.created_at));
  const done = items.filter((i) => ["APPROVED", "REJECTED", "EXPIRED"].includes(i.status))
    .sort((a, b) => t(b.decided_at ?? b.expires_at ?? b.created_at) -
                    t(a.decided_at ?? a.expires_at ?? a.created_at));
  return { pending, reports, done };
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
      return main.role === "entry" ? `${base} · 보유 중 (목표가·손절가 감시)` : base;
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

/** "엔비디아 회의" / "국내 장 마감 정산": the next scheduled job, by kind. */
export function nextWorkLabel(n: OfficeNow["next"][number], meeting = "회의"): string {
  return n.kind === "settle" ? n.name : `${n.name} ${meeting}`;
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
  return item?.plan && item.plan.side !== "SELL" ? (item.plan as ApprovalPlan) : null;
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
