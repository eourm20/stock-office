"use client";

import { useState } from "react";
import { GLOSSARY, splitTerms } from "../lib/glossary";
import { humanizeTickers } from "../office/names";

/** Text whose hard words are dotted-underlined; tapping one shows its plain meaning in place. */
export function Explained({ text, extra }: { text: string; extra?: Record<string, string> }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <>
      {splitTerms(text, Object.keys(extra ?? {})).map((p, i) => p.term ? (
        <span key={i}>
          <button type="button" aria-expanded={open === p.term} onClick={() => setOpen(open === p.term ? null : p.term!)}
                  className="cursor-help underline decoration-dotted underline-offset-4">{p.text}</button>
          {open === p.term && (
            <span role="note" className="mx-1 inline rounded bg-[#fff6dc] px-1.5 py-0.5 text-[12px] font-normal text-[#5c4a14]">
              {extra?.[p.term] ?? GLOSSARY[p.term]}
            </span>
          )}
        </span>
      ) : <span key={i}>{p.text}</span>)}
    </>
  );
}

/** "이야기로 보기": the meeting told as a short story, then the hard words that came up. A sentence
 *  that retells an expert phrase gets a small 🔍; tapping it shows that phrase from the records. */
export function EasyStory({ story, lines, terms, dark = false }: {
  story: string; lines?: { text: string; basis: string }[]; terms?: Record<string, string>; dark?: boolean;
}) {
  const words = Object.entries(terms ?? {});
  const [shown, setShown] = useState<number | null>(null);
  const sentences = lines && lines.length > 0 ? lines : [{ text: story, basis: "" }];
  const basis = shown === null ? null : sentences[shown]?.basis;
  return (
    <section aria-label="이야기로 보기"
             className={`rounded-xl p-4 ${dark ? "border border-amber-700/50 bg-amber-950/30 text-[#f3ead2]" : "bg-[#fff6dc] text-[#3a3220]"}`}>
      <h2 className={`text-[12px] font-bold ${dark ? "text-amber-300" : "text-[#7a5a17]"}`}>이야기로 보기</h2>
      <p className="mt-1 text-[15px] leading-relaxed">
        {sentences.map((l, i) => (
          <span key={i} className={shown === i ? (dark ? "rounded bg-amber-900/60" : "rounded bg-[#f4e2a8]") : ""}>
            <Explained text={humanizeTickers(l.text)} extra={terms} />
            {l.basis && (
              <button type="button" aria-expanded={shown === i} aria-label="원문 표현 보기"
                      onClick={() => setShown(shown === i ? null : i)}
                      className="mx-0.5 align-super text-[11px] opacity-80">🔍</button>
            )}{" "}
          </span>
        ))}
      </p>
      {basis && (
        <p role="note" className={`mt-2 rounded-lg px-3 py-2 text-[13px] ${dark ? "bg-[#0b1020]/70" : "bg-white/70"}`}>
          <span className={`text-[11px] font-semibold ${dark ? "text-amber-300" : "text-[#7a5a17]"}`}>회의 기록의 원래 표현</span><br />
          「<Explained text={basis} extra={terms} />」
        </p>
      )}
      {words.length > 0 && (
        <details className="mt-3">
          <summary className={`cursor-pointer text-[12px] font-semibold ${dark ? "text-amber-300" : "text-[#7a5a17]"}`}>
            이 회의에 나온 어려운 말 {words.length}개
          </summary>
          <dl className="mt-1 space-y-1 text-[13px]">
            {words.map(([t, m]) => (
              <div key={t}><dt className="inline font-semibold">{t}</dt><dd className="inline"> — {m}</dd></div>
            ))}
          </dl>
        </details>
      )}
      <p className={`mt-2 text-[11px] ${dark ? "text-amber-200/60" : "text-[#8a7a52]"}`}>AI가 회의 기록만 보고 쉽게 다시 쓴 설명이에요. 비유는 이해를 돕기 위한 것이에요. 밑줄 친 말은 누르면 뜻이, 🔍는 누르면 회의 기록의 원래 표현이 나와요.</p>
    </section>
  );
}
