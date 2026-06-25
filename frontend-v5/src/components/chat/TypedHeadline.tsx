/**
 * Types a widget's hero summary line out character-by-character the first time
 * it appears, so a widget answer reads as "being written" right at the top —
 * where the user looks first — without a separate (redundant) headline. The
 * hero is the widget's first section, so it lands early in the staggered build.
 */
import { useEffect, useRef, useState } from "react";

const CPS = 42; // characters per second — brisk but readable

// Texts that have already typed once — so re-mounts (streaming→persisted swap,
// scrolling history back into view) render instantly instead of re-typing.
const _typedOnce = new Set<string>();

export function TypedText({ text, className }: { text: string; className?: string }) {
  const done0 = !text || _typedOnce.has(text);
  const [shown, setShown] = useState(done0 ? text.length : 0);
  const ref = useRef(text);
  ref.current = text;
  useEffect(() => {
    if (done0) return;
    const start = performance.now();
    let raf = requestAnimationFrame(function tick(now: number) {
      const t = ref.current;
      const target = Math.min(t.length, Math.floor(((now - start) / 1000) * CPS));
      setShown(target);
      if (target < t.length) raf = requestAnimationFrame(tick);
      else _typedOnce.add(t);
    });
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!text) return null;
  const isDone = done0 || shown >= text.length;
  return (
    <span className={className}>
      {text.slice(0, isDone ? text.length : shown)}
      {!isDone && <span className="inline-block w-[2px] h-[1.05em] -mb-[0.12em] ml-0.5 bg-accent align-baseline animate-pulse" />}
    </span>
  );
}
