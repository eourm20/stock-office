import type { MarketNews } from "../lib/api";
import { MARKET_KO } from "../lib/market";

const DIRECTION_TONE: Record<MarketNews["direction"], string> = {
  좋음: "bg-[#e5efe6] text-[#2f6b3d]", 나쁨: "bg-[#f6e3e3] text-[#9b2f3a]", 엇갈림: "bg-[#ece7da] text-[#6b6455]",
};

/** Only web links from the collected headlines are opened (never other schemes). */
const webUrl = (url: string) => (/^https?:\/\//i.test(url) ? url : null);

/** [시장 브리핑] stories: what happened, an everyday analogy, why it matters, our stocks, sources. */
export default function NewsCards({ news, breaking = false }: { news: MarketNews[]; breaking?: boolean }) {
  return (
    <ol className="space-y-3">
      {news.map((n) => (
        <li key={`${n.rank}-${n.title}`} className={`rounded-lg border bg-[#fbf9f3] p-3 text-[#1c1b17] ${breaking ? "border-l-4 border-[#e1dac9] border-l-rose-500" : "border-[#e1dac9]"}`}>
          <div className="flex items-start gap-2">
            {breaking
              ? <span className="mt-0.5 shrink-0 rounded bg-rose-600 px-1.5 text-[11px] font-bold leading-6 text-white">속보</span>
              : <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[#1c2a48] text-[12px] font-bold text-white">{n.rank}</span>}
            <h2 className="min-w-0 flex-1 text-[15px] font-bold leading-snug">{n.title}</h2>
          </div>
          <div className="mt-1.5 flex flex-wrap gap-1 pl-8 text-[11px]">
            {n.our_stocks?.map((s) => (
              <span key={s.name} className={`rounded px-1.5 font-semibold ${s.role === "보유" ? "bg-amber-200 text-amber-900" : "bg-[#dde8f3] text-[#2b5c8a]"}`}>{s.role} {s.name}</span>
            ))}
            <span className={`rounded px-1.5 font-semibold ${DIRECTION_TONE[n.direction]}`}>{n.direction}</span>
            {n.markets.map((m) => <span key={m} className="rounded bg-[#dde8f3] px-1.5 text-[#2b5c8a]">{MARKET_KO[m]}</span>)}
            {n.sectors.map((s) => <span key={s} className="rounded bg-[#efe9da] px-1.5 text-[#6b6455]">{s}</span>)}
          </div>
          <p className="mt-2 text-[13px] leading-relaxed">{n.summary}</p>
          {n.story && (
            <div className="mt-2 rounded-lg bg-[#fff6dc] px-3 py-2 text-[13px] leading-relaxed">
              <div className="mb-0.5 text-[11px] font-bold text-[#7a5a17]">쉽게 말하면</div>
              {n.story}
            </div>
          )}
          {n.why && <p className="mt-2 text-[13px] leading-relaxed"><b>왜 중요해요?</b> {n.why}</p>}
          <ul className="mt-2 space-y-0.5 text-[11px] text-[#6b6455]">
            {n.sources.map((s) => {
              const href = webUrl(s.url);
              const label = `${s.title}${s.publisher ? ` · ${s.publisher}` : ""}${s.lang === "en" ? " · 영어" : ""}${s.published ? ` · ${s.published}` : ""}`;
              return (
                <li key={s.url || s.title} className="truncate">
                  원문: {href ? <a href={href} target="_blank" rel="noopener noreferrer" className="underline">{label}</a> : label}
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ol>
  );
}
