/** Employees with a character in the office (Sprint 2B: every person-like agent). */
export const ROSTER = [
  { agentId: "market_analyst", role: "Market Analyst" },
  { agentId: "news_analyst", role: "News Analyst" },
  { agentId: "fundamentals_analyst", role: "Fundamentals Analyst" },
  { agentId: "sentiment_analyst", role: "Sentiment Analyst" },
  { agentId: "bull_researcher", role: "Bull Researcher" },
  { agentId: "bear_researcher", role: "Bear Researcher" },
  { agentId: "research_manager", role: "Research Manager" },
  { agentId: "trader", role: "Trader" },
  { agentId: "risk_aggressive", role: "Aggressive Risk Analyst" },
  { agentId: "risk_conservative", role: "Conservative Risk Analyst" },
  { agentId: "risk_neutral", role: "Neutral Risk Analyst" },
  { agentId: "portfolio_manager", role: "Portfolio Manager" },
];

/**
 * Agents shown as office equipment instead of a person (map spot `station:<agent_id>`).
 * Their status still comes only from their own events.
 */
export const STATION_AGENTS = ["data_collector", "memory_log"];
