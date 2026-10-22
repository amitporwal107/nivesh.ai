/** Small pieces shared by the stock and fund research blocks. */
import type { ReactNode } from "react";
import { NotConnected } from "../../components/ui";

/**
 * Shown in place of a figure the data does not carry. A missing figure keeps
 * its tile or row and says so; it is never hidden and never shown as 0.
 */
export function NotAvailable() {
  return (
    <span data-na="true" style={{ fontFamily: "var(--sans)", fontSize: 13, letterSpacing: 0, color: "var(--cp-ink-3)" }}>
      Not available
    </span>
  );
}

/** `format(value)` for a real number, <NotAvailable /> otherwise. */
export function orNA(value: number | null | undefined, format: (n: number) => string): ReactNode {
  return value != null && Number.isFinite(value) ? format(value) : <NotAvailable />;
}

/** "a", "a and b", "a, b and c". */
export function inWords(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** A block whose endpoint is switched on per account, and is off for this one. */
export function Locked({ testId, title, body, needs }: { testId: string; title: string; body: string; needs: string[] }) {
  return <NotConnected testId={testId} title={title} body={body} needs={needs} />;
}
