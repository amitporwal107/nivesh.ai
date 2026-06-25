/**
 * Copilot answer renderer.
 *
 * Wraps Streamdown — a renderer purpose-built for streaming markdown (memoized
 * blocks, forgiving of unterminated tokens, GFM tables, code highlighting). The
 * wrapper keeps every call site as `<Markdown caret>{content}</Markdown>` and
 * lets base typography (ink color + size) inherit from the host className.
 *
 * Streamdown (+ shiki) is ~150 kB gzip, so it's LAZY-loaded: it lives in its own
 * chunk and only downloads when the copilot is used, keeping it out of the
 * initial bundle on every other page. Call `prefetchStreamdown()` when the user
 * enters/opens the chat to warm the chunk so there's no fallback flash. Until it
 * loads, the fallback renders the text raw (whitespace-preserved).
 */
import { lazy, Suspense } from "react";
import { cn } from "@/lib/utils";

const StreamdownLazy = lazy(async () => {
  const m = await import("streamdown");
  return { default: m.Streamdown };
});

let _prefetch: Promise<unknown> | null = null;
/** Warm the Streamdown chunk ahead of first render (idempotent). */
export function prefetchStreamdown(): Promise<unknown> {
  if (!_prefetch) _prefetch = import("streamdown");
  return _prefetch;
}

export function Markdown(
  { children, className, caret }: { children: string; className?: string; caret?: boolean },
) {
  return (
    <Suspense fallback={<div className={cn("whitespace-pre-wrap", className)}>{children}</div>}>
      <StreamdownLazy
        parseIncompleteMarkdown
        caret={caret ? "block" : undefined}
        className={cn(
          "min-w-0 break-words",
          "[&_p]:my-1.5 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
          "[&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5 [&_:is(h1,h2,h3)]:mt-3 [&_:is(h1,h2,h3):first-child]:mt-0",
          className,
        )}
      >
        {children}
      </StreamdownLazy>
    </Suspense>
  );
}
