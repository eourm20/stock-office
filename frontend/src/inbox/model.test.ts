import { describe, expect, it } from "vitest";
import type { InboxItem, RecordRow } from "../lib/api";
import { approvalLine, deadlineLabel, groupInbox, groupRecordsByDay, money, shares } from "./model";

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
