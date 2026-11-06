/** 뉴스 탭: pure helpers (one Korean day at a time, filters), unit-tested. */
import type { InboxItem, MarketNews } from "../lib/api";

const TZ = "Asia/Seoul";

/** Korean calendar day of a timestamp, "2026-11-06". */
export const kstDay = (iso: string) => new Date(Date.parse(iso)).toLocaleDateString("en-CA", { timeZone: TZ });

/** "11/6(금)". */
export function dayLabel(day: string): string {
  const d = new Date(`${day}T12:00:00+09:00`);
  return `${d.getMonth() + 1}/${d.getDate()}(${"일월화수목금토"[d.getDay()]})`;
}

/** Days that have a briefing, newest first. */
export function briefingDays(items: InboxItem[]): string[] {
  return [...new Set(items.map((i) => kstDay(i.created_at)))].sort().reverse();
}

/** One day's briefings in the order they came (morning, then evening). */
export function briefingsOn(items: InboxItem[], day: string): InboxItem[] {
  return items.filter((i) => kstDay(i.created_at) === day)
    .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
}

/** "아침" before 15:00 KST, "저녁" after; the slot name stays in the title. */
export function slotLabel(item: InboxItem): string {
  const hour = Number(new Date(Date.parse(item.created_at)).toLocaleString("en-US", { timeZone: TZ, hour: "2-digit", hour12: false }));
  return hour < 15 ? "아침" : "저녁";
}

export interface NewsFilter { ours: boolean; market: "all" | "KR" | "US"; direction: "all" | MarketNews["direction"] }
export const ALL: NewsFilter = { ours: false, market: "all", direction: "all" };

export function filterNews(news: MarketNews[], f: NewsFilter): MarketNews[] {
  return news.filter((n) => (!f.ours || (n.our_stocks?.length ?? 0) > 0) &&
    (f.market === "all" || n.markets.includes(f.market)) &&
    (f.direction === "all" || n.direction === f.direction));
}
