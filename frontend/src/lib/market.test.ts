import { describe, expect, it } from "vitest";
import { marketOf } from "./market";

describe("marketOf", () => {
  it("reads the desk from the instrument id", () => {
    expect(marketOf("KR:KRX:005930")).toBe("KR");
    expect(marketOf("US:NASDAQ:NVDA")).toBe("US");
    expect(marketOf(null)).toBeNull();
    expect(marketOf("JP:TSE:7203")).toBeNull();
  });
});
