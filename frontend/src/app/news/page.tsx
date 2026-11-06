"use client";

import { useEffect, useMemo, useState } from "react";
import { getNews, markRead, type InboxItem } from "../../lib/api";
import { kstDateTime } from "../../inbox/model";
import NewsCards from "../../news/NewsCards";
import { ALL, briefingDays, briefingsOn, dayLabel, filterNews, kstDay, slotLabel, type NewsFilter } from "../../news/model";
import NavBar from "../NavBar";

/** 뉴스: the company's market briefing, one Korean day at a time (morning and evening). */
export default function NewsPage() {
  const [items, setItems] = useState<InboxItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [day, setDay] = useState<string | null>(null);
  const [filter, setFilter] = useState<NewsFilter>(ALL);

  useEffect(() => {
    getNews(40).then((list) => {
      setItems(list);
      // Opened from a notification (/news?id=…): show that briefing's day.
      const id = Number(new URLSearchParams(window.location.search).get("id"));
      const opened = list.find((i) => i.id === id);
      setDay(opened ? kstDay(opened.created_at) : briefingDays(list)[0] ?? null);
    }).catch((e: Error) => setError(`서버에 연결할 수 없습니다: ${e.message}`));
  }, []);

  const days = useMemo(() => briefingDays(items ?? []), [items]);
  const shown = useMemo(() => (items && day ? briefingsOn(items, day) : []), [items, day]);
  useEffect(() => { shown.filter((i) => !i.read_at).forEach((i) => void markRead(i.id)); }, [shown]);

  const at = day ? days.indexOf(day) : -1;
  const older = at >= 0 && at < days.length - 1 ? days[at + 1] : null;
  const newer = at > 0 ? days[at - 1] : null;

  return (
    <main className="mx-auto flex min-h-screen max-w-2xl flex-col pb-20 sm:pb-6">
      <NavBar />
      <div className="flex items-center justify-between gap-2 px-3 pt-3">
        <button type="button" disabled={!older} onClick={() => older && setDay(older)}
                className="rounded border border-[var(--line)] px-3 py-1 text-sm disabled:opacity-30" aria-label="이전 날">◀</button>
        <h1 className="text-base font-bold">{day ? `${dayLabel(day)} 시장 브리핑` : "시장 브리핑"}</h1>
        <button type="button" disabled={!newer} onClick={() => newer && setDay(newer)}
                className="rounded border border-[var(--line)] px-3 py-1 text-sm disabled:opacity-30" aria-label="다음 날">▶</button>
      </div>
      <p className="px-3 pt-1 text-center text-[11px] text-[var(--muted)]">
        장이 열리는 날 아침 07:20(국내장 개장 전)·저녁(해외장 개장 90분 전)에 새로 옵니다 · AI 요약, 투자 권유 아님
      </p>

      <div className="flex flex-wrap items-center gap-1.5 px-3 pt-3 text-[12px]" role="group" aria-label="걸러 보기">
        <Chip on={filter.ours} onClick={() => setFilter({ ...filter, ours: !filter.ours })}>우리 종목 관련만</Chip>
        {(["all", "KR", "US"] as const).map((m) => (
          <Chip key={m} on={filter.market === m} onClick={() => setFilter({ ...filter, market: m })}>
            {m === "all" ? "모든 시장" : m === "KR" ? "국내장" : "해외장"}</Chip>
        ))}
        {(["all", "좋음", "나쁨", "엇갈림"] as const).map((d) => (
          <Chip key={d} on={filter.direction === d} onClick={() => setFilter({ ...filter, direction: d })}>
            {d === "all" ? "모든 방향" : d}</Chip>
        ))}
      </div>

      {error && <p role="alert" className="mx-3 mt-3 rounded bg-rose-900/70 px-3 py-2 text-sm">{error}</p>}
      {!items && !error && <p className="p-6 text-[var(--muted)]">불러오는 중…</p>}
      {items && shown.length === 0 && (
        <p className="m-3 rounded-lg border border-dashed border-[var(--line)] p-4 text-sm text-[var(--muted)]">
          아직 브리핑이 없습니다. 장이 열리는 날 아침 07:20과 저녁에 옵니다.
        </p>
      )}

      <div className="flex flex-col gap-5 px-3 pt-3">
        {shown.map((b) => {
          const news = filterNews(b.payload.news ?? [], filter);
          const ok = b.payload.briefing_status === "OK";
          return (
            <section key={b.id} aria-label={`${slotLabel(b)} 브리핑`}>
              <h2 className="text-sm font-semibold">{slotLabel(b)} 브리핑 <span className="font-normal text-[var(--muted)]">· {kstDateTime(b.created_at)}</span></h2>
              {b.summary && <p className={`mt-1 text-[13px] ${ok ? "text-sky-100" : "text-amber-200"}`}>{b.summary}</p>}
              {ok && (news.length > 0
                ? <div className="mt-2"><NewsCards news={news} /></div>
                : <p className="mt-2 text-[12px] text-[var(--muted)]">이 조건에 맞는 소식이 없습니다.</p>)}
              {ok && (
                <p className="mt-2 text-[11px] text-[var(--muted)]">
                  기사 {b.payload.candidates ?? "여러"}건(국내외 시장·정책, 많이 움직인 종목, 주요 업종, 우리 보유·관심 종목)의 제목과 요약을 읽고 AI가 골라 쉽게 풀었습니다. 비유는 이해를 돕기 위한 것입니다.
                  {b.payload.model ? ` · 모델 ${b.payload.model}` : ""}
                </p>
              )}
            </section>
          );
        })}
      </div>
    </main>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" aria-pressed={on} onClick={onClick}
            className={`rounded-full border px-2.5 py-0.5 ${on ? "border-[var(--accent)] bg-[var(--accent)] text-black" : "border-[var(--line)] text-[var(--muted)]"}`}>
      {children}
    </button>
  );
}
