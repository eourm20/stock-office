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
  debate: Record<string, string>;
  model: string;
  generated_at: string | null;
  demo: boolean;
  error: string | null;
}

export const getBriefing = (id: string) =>
  getJson<{ available: boolean; briefing: Briefing | null }>(`/api/v1/analysis-runs/${id}/briefing`);
