import type { CharacterStatus } from "./stateMachine";

/** Korean display names. Display only: agent ids and events stay unchanged. */
export const AGENT_NAME_KO: Record<string, { full: string; short: string }> = {
  data_collector: { full: "데이터 수집", short: "수집" },
  memory_log: { full: "기록 보관", short: "기록" },
  market_analyst: { full: "시장 분석가", short: "시장" },
  news_analyst: { full: "뉴스 분석가", short: "뉴스" },
  fundamentals_analyst: { full: "재무 분석가", short: "재무" },
  sentiment_analyst: { full: "심리 분석가", short: "심리" },
  bull_researcher: { full: "강세 연구원", short: "강세" },
  bear_researcher: { full: "약세 연구원", short: "약세" },
  research_manager: { full: "리서치 매니저", short: "리서치" },
  trader: { full: "트레이더", short: "트레이더" },
  risk_aggressive: { full: "공격형 리스크 분석가", short: "공격형" },
  risk_conservative: { full: "보수형 리스크 분석가", short: "보수형" },
  risk_neutral: { full: "중립형 리스크 분석가", short: "중립형" },
  portfolio_manager: { full: "포트폴리오 매니저", short: "PM" },
};

export function agentName(agentId: string | null | undefined, fallback = ""): string {
  if (!agentId) return fallback;
  return AGENT_NAME_KO[agentId]?.full ?? (fallback || agentId);
}

export function agentShortName(agentId: string, fallback = ""): string {
  return AGENT_NAME_KO[agentId]?.short ?? (fallback || agentId);
}

export const STATUS_KO: Record<CharacterStatus, string> = {
  idle: "대기", working: "작업 중", talking: "발언 중", done: "완료", failed: "실패",
};

export const ZONE_KO: Record<string, string> = {
  analyst_office: "분석실", research_room: "리서치 회의실",
  trading_desk: "트레이딩 데스크", risk_executive: "리스크·임원실",
};

export const PHASE_KO: Record<string, string> = {
  IDLE: "대기", QUEUED: "대기열", RUNNING: "진행 중", COMPLETED: "완료", FAILED: "실패",
  INSUFFICIENT_DATA: "데이터 부족",
};

/** Data-provider codes the AI tends to quote (e.g. Yahoo "005930.KS") → names people use. */
const TICKER_NAMES: Record<string, string> = {
  "005930.KS": "삼성전자(005930)",
  "005930": "삼성전자(005930)",
};

/** Display only: replace provider ticker codes with company names. Stored text is unchanged. */
export function humanizeTickers(text: string): string {
  return text
    // A bare code, not already inside "(...)" and not part of a longer number.
    .replace(/(?<![\d(])005930(?:\.KS)?(?!\d)/g, (m) => TICKER_NAMES[m] ?? m)
    // Collapse doubled names the model sometimes writes around the code.
    .replace(/삼성전자\s*\(?\s*삼성전자\(005930\)\)?/g, "삼성전자(005930)")
    .replace(/삼성전자\(005930\)\s*\(삼성전자\)/g, "삼성전자(005930)");
}
