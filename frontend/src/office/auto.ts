/** Auto mode: what the office shows when nobody picked a run. Pure, so it is unit-tested. */

export interface InstrumentSummary {
  instrument_id: string;
  name: string;
  latest: { run_id: string; action: string; engine_rating: string | null; decided_at: string;
            risk_flags: string[] } | null;
  active_run_id: string | null;
  active_status: string | null;
}

export type AutoChoice = { runId: string; live: boolean; instrumentId: string } | null;

/** A meeting in progress wins (watch it live); otherwise the most recent real decision. */
export function chooseAutoRun(items: InstrumentSummary[]): AutoChoice {
  const active = items.find((i) => i.active_run_id);
  if (active) return { runId: active.active_run_id!, live: true, instrumentId: active.instrument_id };
  const decided = items.filter((i) => i.latest)
    .sort((a, b) => Date.parse(b.latest!.decided_at) - Date.parse(a.latest!.decided_at));
  const top = decided[0];
  return top ? { runId: top.latest!.run_id, live: false, instrumentId: top.instrument_id } : null;
}

/** "3분 전", "2시간 전", "어제" … for decision cards. */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000));
  if (s < 60) return "방금";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}시간 전`;
  const d = Math.round(h / 24);
  return d === 1 ? "어제" : `${d}일 전`;
}

export const INSTRUMENT_KO: Record<string, string> = {
  "US:NASDAQ:NVDA": "엔비디아 (NVDA)",
  "KR:KRX:005930": "삼성전자 (005930)",
};
