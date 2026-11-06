import { describe, expect, it } from "vitest";
import { marketOf, onDesk } from "./market";

describe("onDesk", () => {
  it("shows a stock's document on its desk and the market briefing on both", () => {
    const stock = { instrument_id: "KR:KRX:005930", payload: {} };
    const briefing = { instrument_id: null, payload: { type: "market_briefing" } };
    expect(onDesk(stock, "KR")).toBe(true);
    expect(onDesk(stock, "US")).toBe(false);
    expect(onDesk(briefing, "KR") && onDesk(briefing, "US")).toBe(true);
    expect(onDesk({ instrument_id: null, payload: { market: "US" } }, "KR")).toBe(false);
  });
});

describe("marketOf", () => {
  it("reads the desk from the instrument id", () => {
    expect(marketOf("KR:KRX:005930")).toBe("KR");
    expect(marketOf("US:NASDAQ:NVDA")).toBe("US");
    expect(marketOf(null)).toBeNull();
    expect(marketOf("JP:TSE:7203")).toBeNull();
  });
});
