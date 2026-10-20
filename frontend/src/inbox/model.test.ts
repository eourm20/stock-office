import { describe, expect, it } from "vitest";
import type { InboxItem, PaperOrder, RecordRow } from "../lib/api";
import { approvalLine, approvalNote, buyPlan, deadlineLabel, groupInbox, groupRecordsByDay, money, paperLine, sellPlan, shares, signedPct, signedWon } from "./model";

function item(id: number, status: InboxItem["status"], extra: Partial<InboxItem> = {}): InboxItem {
  return { id, kind: status === "INFO" ? "daily" : "approval", run_id: `r${id}`, instrument_id: null,
           title: `#${id}`, summary: "", payload: {}, status, expires_at: null, read_at: null,
           created_at: `2026-10-19T0${id}:00:00Z`, decided_at: null, plan: null, approvals: [],
           ...extra };
}

// 2026-10-20 09:00 KST
const NOW = Date.parse("2026-10-20T00:00:00Z");

describe("inbox model", () => {
  it("puts decisions first by deadline, unread reports before read, and history last", () => {
    const g = groupInbox([
      item(1, "PENDING", { expires_at: "2026-10-20T20:00:00Z" }),
      item(2, "PENDING", { expires_at: "2026-10-20T06:30:00Z" }),
      item(3, "INFO", { read_at: "2026-10-19T05:00:00Z" }),
      item(4, "INFO"),
      item(5, "APPROVED", { decided_at: "2026-10-19T08:00:00Z" }),
      item(6, "DEFERRED", { expires_at: "2026-10-21T06:30:00Z" }),
      item(7, "EXPIRED", { expires_at: "2026-10-19T06:30:00Z" }),
    ]);
    expect(g.pending.map((i) => i.id)).toEqual([2, 1, 6]);
    expect(g.reports.map((i) => i.id)).toEqual([4, 3]);
    expect(g.done.map((i) => i.id)).toEqual([5, 7]);
  });

  it("says when a decision is due in Korean time", () => {
    expect(deadlineLabel("2026-10-20T06:30:00Z", NOW)).toBe("오늘 15:30까지 · 6시간 남음");
    expect(deadlineLabel("2026-10-20T20:00:00Z", NOW)).toBe("내일 05:00까지 · 20시간 남음");
    expect(deadlineLabel("2026-10-20T00:30:00Z", NOW)).toBe("오늘 09:30까지 · 30분 남음");
    expect(deadlineLabel("2026-10-19T06:30:00Z", NOW)).toBe("만료");
    expect(deadlineLabel(null, NOW)).toBe("");
  });

  it("formats money per currency", () => {
    expect(money("240000", "KRW")).toBe("240,000원");
    expect(money("224.33", "USD")).toBe("$224.33");
    expect(shares("9")).toBe("9주");
    expect(shares("0.4967")).toBe("0.4967주");
  });

  it("draws the approval line with the CEO's stamp state", () => {
    expect(approvalLine(item(1, "PENDING")).map((s) => s.state))
      .toEqual(["done", "done", "done", "done", "draft", "waiting"]);
    expect(approvalLine(item(1, "APPROVED")).at(-1)).toEqual({ who: "CEO", state: "APPROVED" });
  });

  it("groups minutes by Korean day", () => {
    const row = (id: string, at: string): RecordRow => ({ run_id: id, instrument_id: "x", name: "x",
      status: "COMPLETED", demo: false, trigger: null, requested_at: at, action: "BUY", rating: null,
      headline: null, approval: null });
    const g = groupRecordsByDay([row("a", "2026-10-19T22:30:00Z"), row("b", "2026-10-19T21:00:00Z"),
                                 row("c", "2026-10-18T22:30:00Z")]);
    // a = 10/20 07:30 KST, b = 10/20 06:00 KST, c = 10/19 07:30 KST
    expect(g.map((d) => [d.day, d.rows.map((r) => r.run_id)]))
      .toEqual([["2026-10-20", ["a", "b"]], ["2026-10-19", ["c"]]]);
    expect(g[0]!.label).toMatch(/^10\. 20\./);
  });
});

function order(role: PaperOrder["role"], status: PaperOrder["status"], extra: Partial<PaperOrder> = {}): PaperOrder {
  return { id: 1, item_id: 1, parent_id: null, instrument_id: "KR:KRX:005930", name: "삼성전자", market: "KR",
           currency: "KRW", role, side: role === "entry" ? "BUY" : "SELL", qty: "3", price: "51300",
           reserved_krw: "0", status, reason: "", detail: {}, active_from: "2026-10-20T00:00:00Z",
           valid_until: "2026-10-20T06:30:00Z", created_at: "2026-10-19T22:35:00Z", closed_at: null, fill: null,
           ...extra };
}
const fill = (price: string, realized: string | null = null) => ({
  session: "2026-10-20", price, qty: "3", gross: "0", fee: "0", tax: "0", fx: "1", amount_krw: "0",
  realized_krw: realized, rule: "low_touched_limit", filled_at: "2026-10-20T07:10:00Z" });

describe("paper book lines", () => {
  it("signs money and percentages", () => {
    expect(signedWon("12300.4")).toBe("+12,300원");
    expect(signedWon(-4500)).toBe("−4,500원");
    expect(signedWon(0)).toBe("0원");
    expect(signedPct("-0.4")).toBe("−0.40%");
  });

  it("says what happened to an approved document", () => {
    expect(paperLine([])).toBeNull();
    expect(paperLine([order("entry", "OPEN")])).toBe("모의 예약 주문 접수 · 매수 3주 지정가 51,300원 · 10. 20. 09:00~10. 20. 15:30");
    expect(paperLine([order("entry", "FILLED", { fill: fill("51000") })])).toBe("매수 3주 체결 @ 51,000원 · 보유 중");
    expect(paperLine([order("entry", "FILLED", { fill: fill("51000") }),
                      order("take_profit", "FILLED", { fill: fill("56000", "14200") }),
                      order("stop", "CANCELLED")])).toBe("매수 3주 체결 @ 51,000원 → 익절 +14,200원");
    expect(paperLine([order("entry", "EXPIRED", { reason: "장중 가격이 지정가에 닿지 않음" })])).toBe("미체결 · 장중 가격이 지정가에 닿지 않음");
    expect(paperLine([order("entry", "REJECTED", { reason: "현금 부족" })])).toBe("리스크 거절 · 현금 부족");
  });

  it("tells buy and sell plans apart", () => {
    const sell = item(1, "APPROVED", { plan: { side: "SELL", currency: "KRW", qty: "3", avg_price: "51000", cost_krw: "153000",
      last_price: "52000", last_fx: "1", marked_session: "2026-10-20", value_krw: "156000", rating: "Sell",
      policy_version: "POLICY_V2", execution: "" } });
    expect(sellPlan(sell)?.qty).toBe("3");
    expect(buyPlan(sell)).toBeNull();
    expect(sellPlan(item(2, "INFO"))).toBeNull();
  });
});

describe("approvalNote", () => {
  it("joins what applies", () => {
    expect(approvalNote(true, "FILLED", "reject")).toBe("자동 승인 · 모의 체결 · CEO 반대");
    expect(approvalNote(false, "EXPIRED", null)).toBe("모의 미체결");
    expect(approvalNote(undefined, null, undefined)).toBe("");
  });
});
