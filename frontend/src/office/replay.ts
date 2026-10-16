import type { RunEvent } from "../types";

export type Speed = 1 | 4 | "instant";

/** Reading time after a debate line. Real logs record the line and the speaker's completion at
 * the same instant, so without a dwell the speech bubble would vanish before anyone can read it.
 * The dwell only delays *when* the next stored event is shown; state is never altered. */
export const DEBATE_DWELL_MS = 4500;
const DECISION_DWELL_MS = 2500;
/** Live mode: if the UI falls this far behind, apply the backlog at once (no walking). */
export const LIVE_CATCH_UP_BACKLOG = 8;

/**
 * Playback delay before `next`, from the real gap between events. Real runs have multi-second
 * gaps (LLM calls), so gaps are compressed and clamped; the order is never changed.
 */
export function playbackDelayMs(prev: RunEvent | null, next: RunEvent, speed: Speed): number {
  if (speed === "instant" || !prev) return 0;
  const gap = Date.parse(next.occurred_at) - Date.parse(prev.occurred_at);
  let base = Number.isFinite(gap) ? Math.min(Math.max(gap / 10, 250), 2500) : 600;
  if (prev.type === "decision.created") base = Math.max(base, DECISION_DWELL_MS);
  let delay = base / speed;
  // Reading time shrinks more slowly than motion when sped up (4.5 s at 1×, 2.25 s at 4×).
  if (prev.type === "debate.message") delay = Math.max(delay, DEBATE_DWELL_MS / Math.sqrt(speed));
  return Math.round(delay);
}

/**
 * Feeds events to the office in order with presentation timing. In live mode events are pushed
 * as they arrive; a large backlog is applied immediately (`onEvent(ev, false)`) to catch up.
 */
export class ReplayPlayer {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private index = 0;
  private closed: boolean;
  private readonly events: RunEvent[];

  constructor(
    events: RunEvent[],
    private readonly onEvent: (ev: RunEvent, animate: boolean) => void,
    private speed: Speed = 1,
    private readonly onEnd: () => void = () => {},
    live = false,
  ) {
    this.events = [...events];
    this.closed = !live;
  }

  play(): void {
    if (this.timer !== null) return;
    if (this.speed === "instant") {
      this.flush();
      return;
    }
    this.scheduleNext();
  }

  pause(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }

  setSpeed(speed: Speed): void {
    this.speed = speed;
    if (this.timer !== null) {
      this.pause();
      this.play();
    }
  }

  /** Live mode: append an event received from the stream. */
  push(ev: RunEvent): void {
    this.events.push(ev);
    if (this.events.length - this.index > LIVE_CATCH_UP_BACKLOG) {
      this.pause();
      this.flush(false);
      return;
    }
    if (this.timer === null) this.scheduleNext();
  }

  /** Live mode: no more events will arrive. */
  close(): void {
    this.closed = true;
    if (this.timer === null) this.scheduleNext();
  }

  get done(): boolean {
    return this.closed && this.index >= this.events.length;
  }

  private flush(callEnd = true): void {
    while (this.index < this.events.length) this.onEvent(this.events[this.index++]!, false);
    if (callEnd && this.closed) this.onEnd();
  }

  private scheduleNext(): void {
    if (this.index >= this.events.length) {
      this.timer = null;
      if (this.closed) this.onEnd();
      return;
    }
    const prev = this.index > 0 ? this.events[this.index - 1]! : null;
    const delay = playbackDelayMs(prev, this.events[this.index]!, this.speed);
    this.timer = setTimeout(() => {
      this.onEvent(this.events[this.index++]!, true);
      this.scheduleNext();
    }, delay);
  }
}
