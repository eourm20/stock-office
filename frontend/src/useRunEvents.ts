import { useEffect, useReducer } from "react";
import { applyEvent, initialRunView, type RunView } from "./runState";
import type { EventType, RunEvent } from "./types";

type Action = { kind: "event"; ev: RunEvent } | { kind: "reset" };

function reducer(view: RunView, action: Action): RunView {
  return action.kind === "reset" ? initialRunView : applyEvent(view, action.ev);
}

const EVENT_TYPES: EventType[] = ["run.created", "run.started", "agent.started",
  "agent.completed", "agent.failed", "debate.message", "decision.created",
  "run.completed", "run.failed"];

/** EventSource resends Last-Event-ID on reconnect; the reducer drops duplicates by seq. */
export function useRunEvents(runId: string | null): RunView {
  const [view, dispatch] = useReducer(reducer, initialRunView);
  useEffect(() => {
    dispatch({ kind: "reset" });
    if (!runId) return;
    const source = new EventSource(`/api/v1/analysis-runs/${runId}/events`);
    const onEvent = (msg: MessageEvent<string>) => {
      const ev = JSON.parse(msg.data) as RunEvent;
      dispatch({ kind: "event", ev });
      if (ev.type === "run.completed" || ev.type === "run.failed") source.close();
    };
    for (const t of EVENT_TYPES) source.addEventListener(t, onEvent as EventListener);
    return () => source.close();
  }, [runId]);
  return view;
}
