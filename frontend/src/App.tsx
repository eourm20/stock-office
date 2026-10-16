import { useState } from "react";
import { useRunEvents } from "./useRunEvents";

type Engine = "demo" | "tradingagents";

// Sprint 0 developer console only. The committee UI (React Flow, Motion) is Sprint 2.
export function App() {
  const [instrument, setInstrument] = useState("US:NASDAQ:NVDA");
  const [engine, setEngine] = useState<Engine>("demo");
  // `?run=<id>` follows an existing run (e.g. one started by the worker or CLI).
  const [runId, setRunId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("run"),
  );
  const [error, setError] = useState<string | null>(null);
  const view = useRunEvents(runId);

  async function start() {
    setError(null);
    const resp = await fetch("/api/v1/analysis-runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ instrument_id: instrument, engine }),
    });
    if (!resp.ok) {
      setError(`${resp.status}: ${await resp.text()}`);
      return;
    }
    const body = (await resp.json()) as { run_id: string };
    setRunId(body.run_id);
  }

  return (
    <main style={{ fontFamily: "system-ui", padding: 16, maxWidth: 960, margin: "auto" }}>
      <h1>Stock Office — Sprint 0 console</h1>
      <p>PAPER ONLY · decisions are proposals, never orders.</p>
      <label>
        Instrument{" "}
        <select value={instrument} onChange={(e) => setInstrument(e.target.value)}>
          <option>US:NASDAQ:NVDA</option>
          <option>KR:KRX:005930</option>
        </select>
      </label>{" "}
      <label>
        Engine{" "}
        <select value={engine} onChange={(e) => setEngine(e.target.value as Engine)}>
          <option value="demo">demo (synthetic)</option>
          <option value="tradingagents">tradingagents</option>
        </select>
      </label>{" "}
      <button onClick={start}>Convene committee</button>
      {error && <p role="alert">{error}</p>}
      {runId && (
        <section aria-live="polite">
          <h2>
            Run {runId} — {view.phase} {view.demo && <strong>[DEMO]</strong>}
          </h2>
          <ul>
            {Object.values(view.agents).map((a) => (
              <li key={a.agentId}>
                {a.role}: {a.status}
                {a.turns > 1 ? ` (turn ${a.turns})` : ""}
              </li>
            ))}
          </ul>
          <ol>
            {view.feed.map((ev) => (
              <li key={ev.seq}>
                #{ev.seq} {ev.occurred_at.slice(11, 19)} {ev.type} {ev.agent_id ?? ""}
                {typeof ev.payload.text === "string" && (
                  <blockquote style={{ margin: "4px 0 8px 16px", color: "#555" }}>
                    {ev.payload.text}
                  </blockquote>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}
    </main>
  );
}
