/**
 * Copilot answer renderer.
 *
 * Wraps Streamdown — a renderer purpose-built for streaming markdown: it parses
 * the text into memoized blocks and is forgiving of unterminated tokens, so an
 * in-flight `**bold` or half-written list reads cleanly while it streams and
 * snaps into place when the closing token arrives. It also brings GFM tables and
 * code highlighting for free if the copilot ever emits them.
 *
 * The wrapper keeps every call site as `<Markdown caret>{content}</Markdown>` and
 * lets base typography (ink color + size) inherit from the className the host
 * passes. `caret` turns on Streamdown's blinking block caret for the in-flight
 * (streaming) bubble so the text feels like live typing.
 */
import { Streamdown } from "streamdown";
import { cn } from "@/lib/utils";

export function Markdown(
  { children, className, caret }: { children: string; className?: string; caret?: boolean },
) {
  return (
    <Streamdown
      parseIncompleteMarkdown
      caret={caret ? "block" : undefined}
      className={cn(
        "min-w-0 break-words",
        // tighten the default block rhythm to match our chat bubbles
        "[&_p]:my-1.5 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0",
        "[&_ul]:my-1.5 [&_ol]:my-1.5 [&_li]:my-0.5 [&_:is(h1,h2,h3)]:mt-3 [&_:is(h1,h2,h3):first-child]:mt-0",
        className,
      )}
    >
      {children}
    </Streamdown>
  );
}
