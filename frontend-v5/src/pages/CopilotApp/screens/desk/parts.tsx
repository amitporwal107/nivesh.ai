/**
 * Trader desk and Paper trades — small shared pieces.
 */
import type { ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";

/**
 * A table cell that names a stock: the company icon, then the label.
 *
 * `testId` marks the label alone, not the icon, so the marked element's text is
 * exactly what the row says ("RELIANCE", "RELIANCE · 12 units") and a test can
 * match it whole. Use StockName (components/EntityIcon) where the name is the
 * company name with the symbol under it.
 */
export function SymbolCell({ symbol, name, sub, testId, title, size = 24, children }: {
  symbol: string;
  /** Company name, read out when the icon is an image. */
  name?: string | null;
  /** A quieter second line. */
  sub?: ReactNode;
  testId?: string;
  title?: string;
  size?: number;
  /** The label; the symbol when omitted. */
  children?: ReactNode;
}) {
  return (
    <span className="flex items-center" title={title} style={{ gap: 10, minWidth: 0 }}>
      <StockIcon symbol={symbol} name={name} size={size} />
      <span className="flex flex-col" style={{ gap: 1, minWidth: 0 }}>
        <span
          data-testid={testId}
          className="inline-flex items-center"
          style={{ gap: 8, minWidth: 0, color: "var(--cp-ink)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
        >
          {children ?? symbol}
        </span>
        {sub != null && sub !== "" && (
          <span style={{ fontSize: 12, color: "var(--cp-ink-3)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{sub}</span>
        )}
      </span>
    </span>
  );
}
