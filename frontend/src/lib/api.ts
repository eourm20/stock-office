import type { InstrumentSummary } from "../office/auto";
import type { RunEvent } from "../types";

/**
 * Where the browser reaches FastAPI.
 * - UI on port 3000 (dev server, SSH tunnel): FastAPI directly on port 8000 of the same host (CORS).
 * - Anything else (Tailscale `serve` over HTTPS, phone home-screen app): same origin; the proxy
 *   forwards `/api` to FastAPI.
 * `NEXT_PUBLIC_API_BASE` overrides both.
 */
export function resolveApiBase(loc: { protocol: string; hostname: string; port: string } | null,
                               override?: string): string {
  if (override) return override;
  if (!loc) return "http://localhost:8000";            // server-side render: never fetched
  return loc.port === "3000" ? `${loc.protocol}//${loc.hostname}:8000` : "";
}

export const API_BASE = resolveApiBase(
  typeof window === "undefined" ? null : window.location, process.env.NEXT_PUBLIC_API_BASE);

export interface RunSummary {
  id: string;
  instrument_id: string;
  engine: "demo" | "tradingagents";
  status: string;
  demo: boolean;
  requested_at: string;
  latency_ms: number | null;
}

export async function listRuns(): Promise<RunSummary[]> {
  const resp = await fetch(`${API_BASE}/api/v1/analysis-runs`);
  if (!resp.ok) throw new Error(`runs: HTTP ${resp.status}`);
  return (await resp.json()) as RunSummary[];
}

export async function getRun(runId: string): Promise<RunSummary> {
  const resp = await fetch(`${API_BASE}/api/v1/analysis-runs/${runId}`);
  if (!resp.ok) throw new Error(`run ${runId}: HTTP ${resp.status}`);
  return (await resp.json()) as RunSummary;
}

export async function getSummary(): Promise<InstrumentSummary[]> {
  const resp = await fetch(`${API_BASE}/api/v1/office/summary`);
  if (!resp.ok) throw new Error(`summary: HTTP ${resp.status}`);
  return ((await resp.json()) as { instruments: InstrumentSummary[] }).instruments;
}

/** Parse an SSE body into events (the stream of a finished run ends by itself). */
export function parseSse(body: string): RunEvent[] {
  const events: RunEvent[] = [];
  for (const block of body.split("\n\n")) {
    const data = block.split("\n").filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trimStart()).join("\n");
    if (data) events.push(JSON.parse(data) as RunEvent);
  }
  return events;
}

/** All stored events of a finished run, for replay. */
export async function fetchRunEvents(runId: string): Promise<RunEvent[]> {
  const resp = await fetch(`${API_BASE}/api/v1/analysis-runs/${runId}/events`);
  if (!resp.ok) throw new Error(`events: HTTP ${resp.status}`);
  return parseSse(await resp.text());
}

export async function startRun(instrumentId: string, engine: "demo" | "tradingagents"):
    Promise<string> {
  const resp = await fetch(`${API_BASE}/api/v1/analysis-runs`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ instrument_id: instrumentId, engine }),
  });
  if (!resp.ok) throw new Error(`${resp.status}: ${await resp.text()}`);
  return ((await resp.json()) as { run_id: string }).run_id;
}

// ---------------------------------------------------------------- analysis screen

export interface RunDetail extends RunSummary {
  as_of: string;
  engine_version: string | null;
  config_hash: string | null;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_message: string | null;
  snapshot_ids: string[];
  coverage_gaps: string[];
  token_usage: Record<string, { input_tokens?: number; output_tokens?: number; total_tokens?: number }> | null;
  trigger?: string | null;
  schedule_slot?: string | null;
}

export interface Decision {
  action: "BUY" | "SELL" | "HOLD" | "REVIEW";
  engine_rating: string | null;
  confidence: string | number | null;   // Decimal; model self-assessment, not a probability
  rationale: string;
  counterarguments: string[];
  risk_flags: string[];
  evidence_snapshot_ids: string[];
  model_version: string;
  created_at: string;
  demo: boolean;
  execution: string;
}

export interface Snapshot {
  id: string;
  source: string;
  kind: string;
  observed_at: string;
  available_at: string;
  ingested_at: string;
  currency: string | null;
  payload: Record<string, unknown>;
  source_url: string | null;
  demo: boolean;
}

async function getJson<T>(path: string): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`);
  if (!resp.ok) throw new Error(`${path}: HTTP ${resp.status}`);
  return (await resp.json()) as T;
}

export const getRunDetail = (id: string) => getJson<RunDetail>(`/api/v1/analysis-runs/${id}`);
export const getSnapshots = (id: string) => getJson<Snapshot[]>(`/api/v1/analysis-runs/${id}/snapshots`);
export const getReports = (id: string) =>
  getJson<{ available: boolean; reports: Record<string, string> }>(`/api/v1/analysis-runs/${id}/reports`);

/** The decision, or null while it does not exist (running, failed or blocked runs). */
export async function getDecision(id: string): Promise<Decision | null> {
  const resp = await fetch(`${API_BASE}/api/v1/analysis-runs/${id}/decision`);
  if (resp.status === 404) return null;
  if (!resp.ok) throw new Error(`decision: HTTP ${resp.status}`);
  return (await resp.json()) as Decision;
}

/** One-page AI summary of the stored reports (null when not generated). */
export interface Briefing {
  status: "OK" | "FAILED";
  headline: string;
  key_reasons: string[];
  risks: string[];
  watch_next: string[];
  agents: Record<string, string>;
  agent_points?: Record<string, string[]>;
  debate: Record<string, string>;
  model: string;
  generated_at: string | null;
  demo: boolean;
  error: string | null;
}

export const getBriefing = (id: string) =>
  getJson<{ available: boolean; briefing: Briefing | null }>(`/api/v1/analysis-runs/${id}/briefing`);

// ---------------------------------------------------------------- CEO inbox, records, office now

export interface PlanAllocation {
  qty: string;            // Decimal: whole shares (KRW) or fractional shares (USD)
  notional: string;
  notional_krw: string;
  max_loss_krw: string;
  binding: string;
  lines: [string, string][];
  blocked: string | null;
}

export interface ApprovalPlan {
  side?: "BUY" | "SELL";
  /** "kiwoom_mock": sized on the desk's Kiwoom mock account (POLICY_V3); amounts in account_currency. */
  venue?: "kiwoom_mock";
  account_currency?: "KRW" | "USD";
  currency: "KRW" | "USD";
  limit: string;
  stop: string;
  target: string;
  sources: Record<"limit" | "stop" | "target", "ai" | "policy">;
  ref_price: string;
  ref_at: string;
  atr: string | null;
  stop_distance: string;
  multiplier: string;
  multiplier_source: "ai" | "policy";
  rating: string | null;
  sizing_text: string | null;
  horizon: string | null;
  fx_krw_per_unit: string;
  fx_at: string | null;
  allocation: PlanAllocation;
  policy_version: string;
  account_basis: string;
  valid_until?: string;
}

/** SELL request: the whole paper position, sold at the next open. */
export interface SellPlan {
  side: "SELL";
  venue?: "kiwoom_mock";
  account_currency?: "KRW" | "USD";
  currency: "KRW" | "USD";
  qty: string;
  avg_price: string;
  cost_krw: string;
  last_price: string;
  last_fx: string;
  marked_session: string;
  value_krw: string;
  rating: string | null;
  policy_version: string;
  valid_until?: string;
  execution: string;
}

export type OrderRole = "entry" | "take_profit" | "stop" | "exit";
export type OrderStatus = "OPEN" | "FILLED" | "CANCELLED" | "EXPIRED" | "REJECTED";

export interface PaperFill {
  session: string; price: string; qty: string; gross: string; fee: string; tax: string; fx: string;
  amount_krw: string; realized_krw: string | null; rule: string; filled_at: string;
}

/** A simulated order in the paper book (nothing is sent anywhere). */
export interface PaperOrder {
  id: number;
  item_id: number | null;
  parent_id: number | null;
  instrument_id: string;
  name: string;
  market: "KR" | "US";
  currency: "KRW" | "USD";
  role: OrderRole;
  side: "BUY" | "SELL";
  qty: string;
  price: string | null;
  reserved_krw: string;
  status: OrderStatus;
  reason: string;
  detail: { stop?: string; target?: string; session?: string; nav_krw?: string };
  active_from: string;
  valid_until: string | null;
  created_at: string;
  closed_at: string | null;
  fill: PaperFill | null;
}

export interface Holding {
  instrument_id: string; name: string; currency: "KRW" | "USD"; qty: string; avg_price: string;
  last_price: string; last_fx: string; marked_session: string; value_krw: string; cost_krw: string;
  pnl_krw: string; pnl_pct: string; take_profit: string | null; stop: string | null;
}

export interface Portfolio {
  started_at: string | null;
  initial_krw: string;
  cash_krw: string;
  reserved_krw: string;
  nav_krw: string;
  return_pct: string;
  realized_krw: string;
  cash_weight_pct: string;
  holdings: Holding[];
  pending: PaperOrder[];
  last_settles: { market: "KR" | "US"; session: string; status: string; note: string; created_at: string }[];
  costs: { label: string; value: string }[];
  auto_approve: boolean;
  policy_version: string;
}

export interface CompanySettings {
  auto_approve: boolean;
  costs: { label: string; value: string }[];
  policy_version: string;
  initial_krw: string;
}

export type InboxStatus = "PENDING" | "APPROVED" | "REJECTED" | "DEFERRED" | "EXPIRED" | "INFO";

export interface InboxItem {
  id: number;
  kind: "approval" | "daily" | "adhoc" | "execution" | "closing" | "research";
  run_id: string | null;
  instrument_id: string | null;
  title: string;
  summary: string;
  payload: { action?: string; rating?: string | null; risk_flags?: string[]; demo?: boolean;
             name?: string; trigger?: string; note?: string; review_reasons?: string[];
             filed_late?: boolean; role?: OrderRole; status?: OrderStatus; realized_krw?: string;
             item_id?: number | null };
  status: InboxStatus;
  expires_at: string | null;
  read_at: string | null;
  created_at: string;
  decided_at: string | null;
  plan: ApprovalPlan | SellPlan | null;
  approvals: { action: string; comment: string; decided_at: string; auto?: boolean; opinion?: boolean }[];
  paper?: PaperOrder[];
  /** Orders on the Kiwoom mock account (국장/미장 desks). */
  mock_orders?: MockOrder[];
  auto_approved?: boolean;
  /** CEO's view on an auto-approved request (recorded only; the paper order follows the model). */
  ceo_opinion?: "approve" | "reject" | "defer" | null;
  opinion_open?: boolean;
}

export interface RecordRow {
  run_id: string;
  instrument_id: string;
  name: string;
  status: string;
  demo: boolean;
  trigger: string | null;
  requested_at: string;
  action: string | null;
  rating: string | null;
  headline: string | null;
  approval: InboxStatus | null;
  approval_auto?: boolean;
  paper?: OrderStatus | null;
  ceo_opinion?: "approve" | "reject" | "defer" | null;
}

export interface OfficeNow {
  now: string;
  active: { run_id: string; instrument_id: string; name: string; status: string; demo: boolean } | null;
  next: { instrument_id: string | null; name: string; market: "KR" | "US"; at: string; kind: "committee" | "settle" | string }[];
  budget: { month: string; budget_usd: string; spent_usd: string; reserved_usd: string;
            remaining_usd: string; paid_runs: number } | null;
  pending_approvals: number;
}

export const getInbox = () => getJson<InboxItem[]>("/api/v1/inbox");
export const getInboxItem = (id: number | string) => getJson<InboxItem>(`/api/v1/inbox/${id}`);
export const getRecords = () => getJson<RecordRow[]>("/api/v1/records");
export const getOfficeNow = () => getJson<OfficeNow>("/api/v1/office/now");
export const getPortfolio = () => getJson<Portfolio>("/api/v1/portfolio");
export const getPortfolioActivity = () => getJson<PaperOrder[]>("/api/v1/portfolio/activity");
export const getCompanySettings = () => getJson<CompanySettings>("/api/v1/company/settings");

/** One Kiwoom 모의투자 account, read-only (step K1). Amounts in the account currency. */
export interface MockAccount {
  market: "KR" | "US";
  currency: "KRW" | "USD";
  ok: boolean;
  error: string | null;
  cash: string | null;
  orderable: string | null;
  total_value: string | null;
  holdings: { code: string; name: string; qty: string | null; avg_price: string | null; price: string | null;
              value: string | null; pnl: string | null; pnl_pct: string | null }[];
  fills_today: number | null;
  checked_at: string;
  notes: string[];
}

export interface KiwoomMockStatus {
  server: string;
  mode: "MOCK";
  read_only: boolean;
  configured: { KR: boolean; US: boolean };
  accounts: { KR: MockAccount | null; US: MockAccount | null };
}

export type MockOrderStatus = "WAITING" | "SENDING" | "SENT" | "FILLED" | "CANCELLED" | "EXPIRED" | "REJECTED" | "REVIEW";

/** An order the desk placed (or will place) on the Kiwoom mock account. */
export interface MockOrder {
  id: number;
  item_id: number | null;
  parent_id: number | null;
  market: "KR" | "US";
  instrument_id: string;
  name: string;
  role: OrderRole;
  side: "BUY" | "SELL";
  qty: string | null;
  limit_price: string | null;
  stop: string | null;
  target: string | null;
  currency: "KRW" | "USD";
  status: MockOrderStatus;
  ext_order_no: string | null;
  filled_qty: string;
  fill_price: string | null;
  valid_until: string | null;
  reason: string;
  detail: { pnl?: string; closed?: boolean; trigger_price?: string; binding?: string };
  created_at: string;
  sent_at: string | null;
  closed_at: string | null;
}

export interface MockPerformance {
  start: string | null;
  history: { market: string; session: string; nav: string; cash: string; holdings_value: string; currency: string;
             benchmark: string | null; benchmark_close: string | null }[];
}

/** The research team's latest screening for one market. */
export interface ResearchRun {
  market: "KR" | "US";
  session: string;
  rules_version: string;
  universe: string;
  screened: number;
  liquid: number;
  candidates: { instrument_id: string; score: number; reasons: string[]; metrics: Record<string, number> }[];
  watchlist: string[];
  focus: { instrument_id: string; why: string }[];
  created_at: string;
  names: Record<string, string>;
}

export const getResearch = (market: "KR" | "US") => getJson<ResearchRun | null>(`/api/v1/research?market=${market}`);

export const getMockActivity = (market: "KR" | "US") => getJson<MockOrder[]>(`/api/v1/kiwoom-mock/activity?market=${market}`);
export const getMockPerformance = (market: "KR" | "US") => getJson<MockPerformance>(`/api/v1/kiwoom-mock/performance?market=${market}`);

export const getKiwoomMock = (refresh = false) =>
  getJson<KiwoomMockStatus>(`/api/v1/kiwoom-mock${refresh ? "?refresh=true" : ""}`);

/** Paper-trading switch: approve every request as it is filed. Local setting only. */
export async function setAutoApprove(enabled: boolean): Promise<boolean> {
  const resp = await fetch(`${API_BASE}/api/v1/company/auto-approve`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }),
  });
  if (!resp.ok) throw new Error(resp.statusText);
  return ((await resp.json()) as { auto_approve: boolean }).auto_approve;
}

export async function markRead(id: number): Promise<void> {
  await fetch(`${API_BASE}/api/v1/inbox/${id}/read`, { method: "POST" });
}

/** CEO decision; the request id makes a double tap harmless. Throws with the server message. */
export async function decideInbox(id: number, action: "approve" | "reject" | "defer",
                                  comment: string, clientRequestId: string): Promise<InboxItem> {
  const resp = await fetch(`${API_BASE}/api/v1/inbox/${id}/decision`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ action, comment, client_request_id: clientRequestId }),
  });
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({ detail: resp.statusText }))).detail);
  return (await resp.json()) as InboxItem;
}

export interface ToolResult { agent_id: string; turn: number; round: number; tool: string; content: string; captured_at: string }

/** What the analysts' tools returned in a meeting (stored since 2026-10-19). */
export const getToolResults = (id: string) =>
  getJson<{ available: boolean; results: ToolResult[] }>(`/api/v1/analysis-runs/${id}/tool-results`);
