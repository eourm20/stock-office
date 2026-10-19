/** CEO inbox and records: pure helpers (sorting, deadlines, stamps, grouping), unit-tested. */
import type { InboxItem, InboxStatus, RecordRow } from "../lib/api";

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
