import { describe, expect, it } from "vitest";
import { urlBase64ToBytes } from "./push";

describe("urlBase64ToBytes", () => {
  it("decodes base64url without padding (VAPID public key format)", () => {
    expect(Array.from(urlBase64ToBytes("-_8"))).toEqual([0xfb, 0xff]);
    expect(urlBase64ToBytes("B".padEnd(87, "A"))).toHaveLength(65);
  });
});
