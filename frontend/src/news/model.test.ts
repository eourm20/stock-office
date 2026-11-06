import { describe, expect, it } from "vitest";
import type { InboxItem, MarketNews } from "../lib/api";
import { ALL, briefingDays, briefingsOn, dayLabel, filterNews, kstDay, slotLabel } from "./model";

const item = (id: number, created_at: string) => ({ id, created_at, payload: {} }) as unknown as InboxItem;
const news = (over: Partial<MarketNews>): MarketNews => ({
  rank: 1, title: "t", summary: "", story: "", why: "", markets: ["KR"], sectors: [], direction: "나쁨",
  sources: [], ...over,
});

describe("one day at a time", () => {
  // 11/5 22:00 KST evening, 11/6 07:20 morning, 11/6 22:00 evening (UTC stamps)
  const items = [item(3, "2026-11-06T13:00:00Z"), item(1, "2026-11-05T13:00:00Z"), item(2, "2026-11-05T22:20:00Z")];

  it("groups by Korean calendar day, newest day first, morning before evening", () => {
    expect(kstDay("2026-11-05T22:20:00Z")).toBe("2026-11-06");
    expect(briefingDays(items)).toEqual(["2026-11-06", "2026-11-05"]);
    expect(briefingsOn(items, "2026-11-06").map((i) => i.id)).toEqual([2, 3]);
    expect(briefingsOn(items, "2026-11-06").map(slotLabel)).toEqual(["아침", "저녁"]);
    expect(dayLabel("2026-11-06")).toBe("11/6(금)");
  });
});

describe("filterNews", () => {
  const list = [news({ rank: 1, our_stocks: [{ name: "삼성전자", role: "보유" }] }),
                news({ rank: 2, markets: ["US"], direction: "좋음" })];
  it("keeps our stocks, a market or a direction", () => {
    expect(filterNews(list, ALL)).toHaveLength(2);
    expect(filterNews(list, { ...ALL, ours: true }).map((n) => n.rank)).toEqual([1]);
    expect(filterNews(list, { ...ALL, market: "US" }).map((n) => n.rank)).toEqual([2]);
    expect(filterNews(list, { ...ALL, direction: "나쁨" }).map((n) => n.rank)).toEqual([1]);
  });
});
