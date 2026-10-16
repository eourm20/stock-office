/**
 * Plain-Korean explanations of what is on screen. Deterministic templates over the office
 * state — no model calls — so they never invent anything the events do not say.
 */
import { agentName, humanizeTickers } from "./names";
import type { OfficeState } from "./stateMachine";

/** Pipeline order: when several agents are busy, the latest stage describes "now". */
const STAGES: { agents: string[]; text: string }[] = [
  { agents: ["data_collector"], text: "시세·공시 데이터를 모으고 있어요." },
  { agents: ["market_analyst", "news_analyst", "fundamentals_analyst", "sentiment_analyst",
             "memory_log"],
    text: "분석가들이 차트·뉴스·재무제표를 조사하고 있어요." },
  { agents: ["bull_researcher", "bear_researcher"],
    text: "강세 연구원과 약세 연구원이 '살까, 팔까'를 두고 토론하고 있어요." },
  { agents: ["research_manager"], text: "리서치 매니저가 토론 내용을 정리해 투자 계획을 세우고 있어요." },
  { agents: ["trader"], text: "트레이더가 구체적인 거래안을 만들고 있어요." },
  { agents: ["risk_aggressive", "risk_conservative", "risk_neutral"],
    text: "리스크 팀(공격형·보수형·중립형)이 이 거래가 위험하지 않은지 따지고 있어요." },
  { agents: ["portfolio_manager"], text: "포트폴리오 매니저가 최종 결정을 내리고 있어요." },
];

export const ACTION_KO: Record<string, { label: string; plain: string }> = {
  BUY: { label: "매수", plain: "사는 쪽이 낫다는 의견이에요." },
  SELL: { label: "매도", plain: "파는(줄이는) 쪽이 낫다는 의견이에요." },
  HOLD: { label: "보유", plain: "지금은 사지도 팔지도 말고 지켜보자는 의견이에요." },
  REVIEW: { label: "판단 보류", plain: "근거가 부족하거나 결론을 읽을 수 없어서 사람이 확인해야 해요." },
};

export const RATING_KO: Record<string, string> = {
  Buy: "매수 — 적극적으로 사기",
  Overweight: "비중 확대 — 조금 더 사기",
  Hold: "유지 — 지금 비중 그대로",
  Underweight: "비중 축소 — 조금 줄이기",
  Sell: "매도 — 팔기",
  REVIEW: "판단 보류",
};

export const FLAG_KO: Record<string, string> = {
  COVERAGE_GAP: "일부 데이터를 구하지 못했어요 (예: 뉴스·예측시장 접속 실패).",
  ENGINE_DATA_NOT_SNAPSHOTTED: "AI가 스스로 찾아본 자료는 근거 목록에 따로 저장되지 않았어요.",
  DEMO_NOT_ANALYSIS: "연습용 가짜 데이터예요. 실제 분석이 아니에요.",
  INSUFFICIENT_DATA: "데이터가 부족해서 분석을 멈췄어요.",
  NO_GROUNDED_EVIDENCE: "판단을 뒷받침할 데이터가 없어요.",
  UNPARSEABLE_OR_REVIEW_RATING: "AI의 결론(등급)을 읽을 수 없었어요.",
};

/** One friendly sentence for "what is happening now". */
export function narrate(state: OfficeState): string {
  switch (state.phase) {
    case "IDLE":
      return "위쪽에서 저장된 실행을 고르거나 '새 분석 시작'을 눌러 보세요.";
    case "QUEUED":
      return "분석 요청이 접수됐어요. 곧 회의가 시작돼요.";
    case "FAILED":
      return "분석이 중간에 멈췄어요. 오른쪽 활동 기록에서 이유를 확인하세요.";
    case "COMPLETED": {
      const d = state.decision;
      if (!d) return "분석이 끝났어요.";
      const a = ACTION_KO[d.action] ?? { label: d.action, plain: "" };
      return `회의 끝! AI 위원회의 의견은 '${a.label}'예요. 실제 주문은 하지 않았어요.`;
    }
    case "RUNNING": {
      const busy = new Set<string>();
      for (const c of Object.values(state.characters)) {
        if (c.status === "working" || c.status === "talking") busy.add(c.agentId);
      }
      for (const [id, o] of Object.entries(state.offstage)) {
        if (o.status === "working" || o.status === "talking") busy.add(id);
      }
      for (let i = STAGES.length - 1; i >= 0; i--) {
        if (STAGES[i]!.agents.some((a) => busy.has(a))) return STAGES[i]!.text;
      }
      return "다음 담당자에게 자료를 넘기고 있어요.";
    }
  }
}

/** Speech-bubble form of a debate line: no speaker prefix or markdown markup. */
export function bubbleText(text: string): string {
  return humanizeTickers(text)
    .replace(/^\s*[A-Za-z ]+(Analyst|Researcher):\s*/, "")
    .replace(/[#*_`>]+/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

/** Short speech for a bubble: the first sentence, capped. The full text stays in the panel. */
export function shortSpeech(text: string, max = 70): string {
  const clean = text.replace(/\s+/g, " ").trim();
  const m = clean.match(/^(.+?[.!?。]|.+?(다|요|죠|니다)\.)(\s|$)/);
  const first = (m?.[1] ?? clean).trim();
  return first.length > max ? `${first.slice(0, max - 1)}…` : first;
}

export function decisionLines(d: NonNullable<OfficeState["decision"]>): string[] {
  const lines = [ACTION_KO[d.action]?.plain ?? ""];
  if (d.rating) lines.push(`AI 등급: ${RATING_KO[d.rating] ?? d.rating}`);
  lines.push("AI 위원회의 1회 의견일 뿐, 검증된 투자 신호가 아니에요.");
  return lines.filter(Boolean);
}

export function who(agentId: string): string {
  return agentName(agentId);
}
