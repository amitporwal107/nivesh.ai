/**
 * Paced reveal for streaming copilot answers.
 *
 * The LLM tokens often arrive in ~1s, which makes the whole answer flush in
 * instantly. That doesn't read as "being generated." This hook decouples the
 * DISPLAY speed from the arrival speed: tokens accumulate into `buffer`, and the
 * visible `content` is advanced toward `buffer` over a fixed ~10s window so the
 * text types out smoothly regardless of how fast the network/model delivered it.
 *
 * The reveal is rate-paced to a deadline: each frame it shows
 * `remaining * frameBudget / timeLeft` more characters, so it always lands right
 * at the window edge — slowing down when little text is left, catching up if a
 * burst of tokens arrives late. When the time window elapses it dumps whatever
 * remains so nothing is ever stuck hidden.
 */
import { useEffect } from "react";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

export const TYPE_WINDOW_MS = 10000;

type Revealable = { buffer: string; content: string };

export function useTypewriterReveal<T extends Revealable | null>(
  streaming: T,
  setStreaming: Dispatch<SetStateAction<T>>,
  firstTokenRef: MutableRefObject<number | null>,
  windowMs: number = TYPE_WINDOW_MS,
): void {
  useEffect(() => {
    if (!streaming) return;
    const buffer = streaming.buffer ?? "";
    const content = streaming.content ?? "";
    if (content.length >= buffer.length) return; // caught up — wait for more tokens
    if (firstTokenRef.current == null && buffer.length > 0) {
      firstTokenRef.current = performance.now();
    }
    const FRAME_MS = 32; // ~2 frames; smooth without thrashing React
    const id = requestAnimationFrame((now) => {
      const start = firstTokenRef.current ?? now;
      const timeLeft = Math.max(0, windowMs - (now - start));
      const remaining = buffer.length - content.length;
      const step = timeLeft <= FRAME_MS
        ? remaining // window elapsed → reveal the rest
        : Math.max(1, Math.ceil((remaining * FRAME_MS) / timeLeft));
      const next = Math.min(buffer.length, content.length + step);
      setStreaming((s) => (s ? { ...s, content: buffer.slice(0, next) } : s));
    });
    return () => cancelAnimationFrame(id);
  }, [streaming, setStreaming, firstTokenRef, windowMs]);
}

/**
 * How long to keep the streaming bubble open after the SSE stream resolves, so
 * the paced reveal can finish its ~10s window instead of being cut short the
 * moment the last token lands. Returns the ms to wait (0 if no tokens arrived).
 */
export function remainingRevealMs(
  firstTokenAt: number | null,
  windowMs: number = TYPE_WINDOW_MS,
): number {
  if (firstTokenAt == null) return 0; // widget-only / error — nothing to type out
  return Math.max(0, windowMs - (performance.now() - firstTokenAt) + 250);
}
