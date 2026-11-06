import { describe, expect, it } from "vitest";
import { GLOSSARY, splitTerms } from "./glossary";

describe("splitTerms", () => {
  it("marks known terms once, longest first, English only as whole words", () => {
    const pieces = splitTerms("점수 5: 눌림 6.5% (20일 고점 대비), RSI 58, 50일선 지지, RSI 재확인");
    expect(pieces.filter((p) => p.term).map((p) => p.term)).toEqual(["눌림", "20일 고점", "RSI", "50일선"]);
    expect(pieces.map((p) => p.text).join("")).toBe("점수 5: 눌림 6.5% (20일 고점 대비), RSI 58, 50일선 지지, RSI 재확인");
    expect(splitTerms("PERFORMANCE 좋음").some((p) => p.term)).toBe(false);
    expect(splitTerms("본전 손절로 바꿈").map((p) => p.term).filter(Boolean)).toEqual(["본전 손절"]);
  });

  it("has a plain meaning for every term", () => {
    for (const [term, meaning] of Object.entries(GLOSSARY)) expect(meaning.length, term).toBeGreaterThan(10);
  });
});
