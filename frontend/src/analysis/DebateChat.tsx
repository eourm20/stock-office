"use client";

import { useEffect, useState } from "react";
import Markdown from "../app/Markdown";
import { bubbleText, shortSpeech } from "../office/explain";
import { agentName, humanizeTickers } from "../office/names";
import { characterFor, type Registry } from "../office/registry";
import type { DebateLine } from "./model";

const STANCE_KO: Record<string, string> = {
  bull: "강세", bear: "약세", aggressive: "공격형", conservative: "보수형", neutral: "중립형",
};
const BUBBLE: Record<string, string> = {
  bull: "bg-emerald-900/60 border-emerald-600", bear: "bg-rose-900/50 border-rose-600",
  aggressive: "bg-orange-900/50 border-orange-500", conservative: "bg-blue-900/50 border-blue-500",
  neutral: "bg-slate-800 border-slate-500",
};
const NAME: Record<string, string> = {
  bull: "text-emerald-300", bear: "text-rose-300", aggressive: "text-orange-300",
  conservative: "text-blue-300", neutral: "text-slate-300",
};

const hhmm = (iso: string) => new Date(iso).toLocaleTimeString("ko-KR", {
  timeZone: "Asia/Seoul", hour: "2-digit", minute: "2-digit" });
const stripSpeaker = (t: string) => t.replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "");

/** Face of the agent's character: first frame of its sprite sheet (appearance only). */
function Avatar({ agentId, registry }: { agentId: string; registry: Registry | null }) {
  if (!registry) return <div className="h-10 w-10 shrink-0 rounded-full bg-[var(--line)]" />;
  const entry = characterFor(registry, agentId);
  const sheet = entry.asset.kind === "sprite_sheet";
  return (
    <div aria-hidden="true" className="h-10 w-10 shrink-0 overflow-hidden rounded-full border border-[var(--line)] bg-[#1d2944]"
         style={{
           backgroundImage: `url(/characters/${entry.asset.image})`,
           // Sheets are 4 frames of 64 px per row; show frame 0 (idle, facing down) at 40 px.
           backgroundSize: sheet ? "160px auto" : "cover",
           backgroundPosition: sheet ? "0 -2px" : "center",
           imageRendering: "pixelated",
         }} />
  );
}

function Message({ line, gist, right, registry }: {
  line: DebateLine; gist: string | undefined; right: boolean; registry: Registry | null;
}) {
  const [open, setOpen] = useState(false);
  const full = humanizeTickers(stripSpeaker(line.text));
  const short = gist ?? shortSpeech(bubbleText(line.text), 90);
  return (
    <li className={`flex items-end gap-2 ${right ? "flex-row-reverse" : ""}`}>
      <Avatar agentId={line.agentId} registry={registry} />
      <div className={`flex max-w-[85%] flex-col ${right ? "items-end" : "items-start"}`}>
        <div className={`mb-0.5 text-xs ${NAME[line.stance] ?? ""}`}>
          {agentName(line.agentId)} <span className="text-[var(--muted)]">· {STANCE_KO[line.stance] ?? line.stance}</span>
        </div>
        <div className={`flex items-end gap-1.5 ${right ? "flex-row-reverse" : ""}`}>
          <button onClick={() => setOpen(!open)} aria-expanded={open}
                  className={`rounded-2xl border px-3 py-2 text-left text-sm leading-relaxed ${BUBBLE[line.stance] ?? "bg-[var(--panel)] border-[var(--line)]"} ${right ? "rounded-br-sm" : "rounded-bl-sm"}`}>
            {open ? <Markdown text={full} /> : <span>{humanizeTickers(short)}</span>}
            <span className="mt-1 block text-[11px] text-[var(--muted)]">{open ? "접기 ▲" : "전체 발언 보기 ▼"}</span>
          </button>
          <time className="shrink-0 text-[10px] text-[var(--muted)]">{hhmm(line.at)}</time>
        </div>
      </div>
    </li>
  );
}

function Room({ title, subtitle, lines, gists, rightStances, registry }: {
  title: string; subtitle: string; lines: DebateLine[]; gists: Record<string, string>;
  rightStances: Set<string>; registry: Registry | null;
}) {
  let lastTurn = 0;
  return (
    <section className="rounded-xl border border-[var(--line)] bg-[#0f1729]">
      <header className="border-b border-[var(--line)] px-3 py-2">
        <h3 className="font-semibold">{title}</h3>
        <p className="text-xs text-[var(--muted)]">{subtitle}</p>
      </header>
      {lines.length === 0 ? <p className="p-3 text-sm text-[var(--muted)]">발언 없음</p> : (
        <ol className="space-y-3 p-3">
          {lines.flatMap((l) => {
            const items = [];
            if (l.turn !== lastTurn) {
              lastTurn = l.turn;
              items.push(
                <li key={`round-${l.seq}`} className="flex items-center gap-2 text-[11px] text-[var(--muted)]" aria-hidden="true">
                  <span className="h-px flex-1 bg-[var(--line)]" />{l.turn}라운드<span className="h-px flex-1 bg-[var(--line)]" />
                </li>);
            }
            items.push(<Message key={l.seq} line={l} gist={gists[String(l.seq)]}
                                right={rightStances.has(l.stance)} registry={registry} />);
            return items;
          })}
        </ol>
      )}
    </section>
  );
}

/**
 * The stored debate as a messenger chat. Every bubble is a real debate.message event; the short
 * text is the briefing's gist (AI summary) or the first sentence, and a tap shows the full speech.
 */
export default function DebateChat({ lines, gists, fullTranscripts }: {
  lines: DebateLine[]; gists: Record<string, string>; fullTranscripts: Record<string, string>;
}) {
  const [registry, setRegistry] = useState<Registry | null>(null);
  useEffect(() => {
    fetch("/characters/registry.json").then((r) => r.json() as Promise<Registry>)
      .then(setRegistry).catch(() => setRegistry(null));
  }, []);
  const invest = lines.filter((l) => l.debate === "investment");
  const risk = lines.filter((l) => l.debate !== "investment");
  return (
    <div className="space-y-4">
      <p className="text-xs text-[var(--muted)]">말풍선은 실제 발언입니다. 짧은 문장은 {Object.keys(gists).length ? "AI가 요약한 요지" : "발언의 첫 문장"}이고, 누르면 전체 발언이 펼쳐집니다.</p>
      <div className="grid gap-4 lg:grid-cols-2">
        <Room title="💬 투자 토론방" subtitle="강세 연구원 vs 약세 연구원 · 살까, 팔까" lines={invest}
              gists={gists} rightStances={new Set(["bear"])} registry={registry} />
        <Room title="💬 리스크 토론방" subtitle="공격형 · 보수형 · 중립형 리스크 분석가" lines={risk}
              gists={gists} rightStances={new Set(["conservative"])} registry={registry} />
      </div>
      {(fullTranscripts.investment_debate || fullTranscripts.risk_debate) && (
        <details className="text-sm">
          <summary className="cursor-pointer text-[var(--muted)]">잘리지 않은 전체 토론 기록 (원문)</summary>
          <div className="mt-2 space-y-3">
            {fullTranscripts.investment_debate && <Markdown text={humanizeTickers(fullTranscripts.investment_debate)} />}
            {fullTranscripts.risk_debate && <Markdown text={humanizeTickers(fullTranscripts.risk_debate)} />}
          </div>
        </details>
      )}
    </div>
  );
}
