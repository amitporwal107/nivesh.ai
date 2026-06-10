/**
 * One-line typed summary shown above a widget answer.
 *
 * The full narrative is suppressed when a widget is shown (it just repeats the
 * card), but a single typed headline restores the "being written" feel. The
 * headline is the FIRST SENTENCE of the narrative — which the copilot tends to
 * write as a punchy summary (e.g. "More than you need — it's a consolidation
 * issue, not a bad-funds issue."). It types out as the narrative streams in.
 */
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/** First sentence (to . ! ? or newline), trimmed, capped so it stays one line. */
export function firstSentence(text: string): string {
  const t = (text ?? "").trim();
  if (!t) return "";
  const m = t.match(/^[\s\S]*?[.!?](\s|$)/);
  const s = (m ? m[0] : t.split("\n")[0]).trim();
  return s.length > 160 ? s.slice(0, 159).trimEnd() + "…" : s;
}

const CPS = 42; // characters per second — brisk but readable

export function TypedHeadline(
  { source, typing = true, className }: { source: string; typing?: boolean; className?: string },
) {
  const headline = firstSentence(source);
  const [shown, setShown] = useState(typing ? 0 : headline.length);
  const headlineRef = useRef(headline);
  headlineRef.current = headline;
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (!typing || !headline) return;
    if (startRef.current == null) startRef.current = performance.now();
    let raf = requestAnimationFrame(function tick(now: number) {
      const h = headlineRef.current;
      const elapsed = now - (startRef.current ?? now);
      const target = Math.min(h.length, Math.floor((elapsed / 1000) * CPS));
      setShown(target);
      if (target < h.length) raf = requestAnimationFrame(tick);
    });
    return () => cancelAnimationFrame(raf);
  }, [typing, headline]);

  if (!headline) return null;
  const done = !typing || shown >= headline.length;
  return (
    <p className={cn("text-ink", className)}>
      {headline.slice(0, typing ? shown : headline.length)}
      {!done && <span className="inline-block w-[2px] h-[1.05em] -mb-[0.12em] ml-0.5 bg-accent align-baseline animate-pulse" />}
    </p>
  );
}
