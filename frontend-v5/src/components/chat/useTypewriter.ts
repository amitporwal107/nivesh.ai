/**
 * Paced reveal for streaming copilot answers.
 *
 * Tokens accumulate into `buffer`; the visible `content` follows it. The reveal
 * is paced to ARRIVAL, not to a clock: the visible text never lags the buffer
 * by more than ~CATCH_UP_MS, and it never types slower than MIN_CPS. A fast
 * backend therefore reads as fast, while a slow one still types smoothly
 * instead of flushing in bursts. A `skip` flag on the stream state (set by any
 * click or keypress on the thread) shows everything that has arrived at once.
 *
 * History: the reveal used to be stretched over a fixed 10 s window regardless
 * of arrival speed, so a 1 s answer felt like a 10 s one and the composer stayed
 * locked for the whole window. See the design review (C1).
 */
import { useEffect, useRef } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

/** Floor typing speed (characters per second) when tokens trickle in. */
export const MIN_CPS = 140;
/** The visible text never lags what has arrived by more than about this. */
export const CATCH_UP_MS = 450;
/** Hard cap on the time added after the stream resolves. */
export const MAX_HOLD_MS = 1200;
/** Lets the staggered widget build-in (index.css `.sd-stagger`) finish. */
export const WIDGET_HOLD_MS = 1100;

type Revealable = { buffer: string; content: string; skip?: boolean };

export function useTypewriterReveal<T extends Revealable | null>(
  streaming: T,
  setStreaming: Dispatch<SetStateAction<T>>,
  firstTokenRef: MutableRefObject<number | null>,
): void {
  // When the visible text last advanced. Pacing is measured from HERE (wall
  // clock per reveal cycle), so a slow re-render between two advances yields a
  // bigger step instead of starving the reveal below MIN_CPS.
  const lastTickRef = useRef<number | null>(null);
  useEffect(() => {
    if (!streaming) { lastTickRef.current = null; return; }
    const buffer = streaming.buffer ?? "";
    const content = streaming.content ?? "";
    if (content.length >= buffer.length) { lastTickRef.current = null; return; } // caught up — wait for more tokens
    if (firstTokenRef.current == null && buffer.length > 0) {
      firstTokenRef.current = performance.now();
    }
    if (streaming.skip) {
      setStreaming((s) => (s ? { ...s, content: buffer } : s));
      return;
    }
    if (lastTickRef.current == null) lastTickRef.current = performance.now();
    const id = requestAnimationFrame(() => {
      const now = performance.now();
      // Seconds since the last advance (clamped so a background tab catching up
      // doesn't dump everything at once).
      const dt = Math.min(0.25, Math.max(0.008, (now - (lastTickRef.current ?? now)) / 1000));
      const remaining = buffer.length - content.length;
      const rate = Math.max(MIN_CPS, remaining / (CATCH_UP_MS / 1000));
      const next = Math.min(buffer.length, content.length + Math.max(1, Math.ceil(rate * dt)));
      lastTickRef.current = now;
      setStreaming((s) => (s ? { ...s, content: buffer.slice(0, next) } : s));
    });
    return () => cancelAnimationFrame(id);
  }, [streaming, setStreaming, firstTokenRef]);
}

/**
 * How long to keep the streaming bubble open after the SSE stream resolves:
 * enough to finish typing what is still hidden (capped at MAX_HOLD_MS) and,
 * for widget answers, to let the build-in animation play. 0 when nothing is
 * pending.
 */
export function remainingRevealMs(remainingChars: number, hasWidget = false): number {
  const text = remainingChars > 0
    ? Math.min(MAX_HOLD_MS, Math.ceil((remainingChars / MIN_CPS) * 1000) + 100)
    : 0;
  return Math.max(text, hasWidget ? WIDGET_HOLD_MS : 0);
}

/** Wait up to `ms`, resolving early as soon as `cancelled()` is true (skip / stop). */
export function holdFor(ms: number, cancelled: () => boolean): Promise<void> {
  return new Promise((resolve) => {
    const end = performance.now() + ms;
    const tick = () => {
      if (cancelled() || performance.now() >= end) resolve();
      else setTimeout(tick, 40);
    };
    tick();
  });
}
