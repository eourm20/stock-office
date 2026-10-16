import type { InstrumentSummary } from "../office/auto";
import type { RunEvent } from "../types";

/** The browser talks to FastAPI directly (CORS) so SSE is never buffered by a proxy. */
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

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
