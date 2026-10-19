"use client";

import { useState } from "react";
import { startRun } from "../lib/api";
import { INSTRUMENT_KO } from "../office/auto";

/** "＋ 회의 소집": the CEO calls a committee meeting now (paid runs ask for confirmation). */
export default function ConveneButton({ onStarted }: { onStarted?: (runId: string) => void }) {
  const [open, setOpen] = useState(false);
  const [instrument, setInstrument] = useState("US:NASDAQ:NVDA");
  const [engine, setEngine] = useState<"demo" | "tradingagents">("tradingagents");
  const [busy, setBusy] = useState(false);
  const start = async () => {
    if (engine === "tradingagents" && !window.confirm(
      `${INSTRUMENT_KO[instrument] ?? instrument} 회의를 소집할까요?\n실제 분석은 OpenAI 비용이 발생합니다 (약 $0.05, 3~4분).`)) return;
    setBusy(true);
    try {
      const id = await startRun(instrument, engine);
      setOpen(false);
      onStarted?.(id);
    } catch (e) {
      window.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open}
              className="whitespace-nowrap rounded-lg border border-[var(--mint)] px-2 py-1 text-xs text-[var(--mint)]">＋ 회의 소집</button>
      {open && (
        <div className="absolute right-0 top-9 z-50 w-64 space-y-2 rounded-lg border border-[var(--line)] bg-[#0f1729] p-3 shadow-xl">
          <label className="block text-xs text-[var(--muted)]">종목
            <select className="mt-1 w-full rounded bg-[var(--panel)] px-2 py-1.5 text-sm text-[var(--ink)]" value={instrument}
                    onChange={(e) => setInstrument(e.target.value)}>
              {Object.entries(INSTRUMENT_KO).map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          <label className="block text-xs text-[var(--muted)]">종류
            <select className="mt-1 w-full rounded bg-[var(--panel)] px-2 py-1.5 text-sm text-[var(--ink)]" value={engine}
                    onChange={(e) => setEngine(e.target.value as "demo" | "tradingagents")}>
              <option value="tradingagents">실제 회의 (유료)</option>
              <option value="demo">연습 회의 DEMO (무료)</option>
            </select>
          </label>
          <button disabled={busy} onClick={() => void start()}
                  className="w-full rounded bg-[var(--mint)] py-1.5 text-sm font-semibold text-black disabled:opacity-50">
            {busy ? "소집 중…" : "회의 시작"}
          </button>
        </div>
      )}
    </div>
  );
}
