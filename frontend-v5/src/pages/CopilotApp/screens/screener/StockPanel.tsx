/**
 * A stock opened from a screen's results: the Research page's own stock view (price chart, key figures,
 * scores, shareholding, corporate actions, filings), in a slide-over so the matches stay where they were.
 * It renders Research's StockResearch, so the chart is the same component with the same data routes.
 */
import { useEffect, useRef } from "react";
import type { StockHit } from "@/hooks/use-instrument-search";
import { useCopilotShell } from "../../lib/shell-context";
import { StockResearch } from "../markets/ResearchInstrument";

export function StockPanel({ stock, onClose }: { stock: StockHit; onClose: () => void }) {
  const { mobile } = useCopilotShell();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    // Focus goes into the panel, and back to the row that opened it when it closes.
    const opener = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      opener?.focus?.();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- opened once per mount; the parent keys it by symbol
  }, []);

  return (
    <div data-testid="screener-stock-panel-root" style={{ position: "fixed", inset: 0, zIndex: 60 }}>
      <div
        data-testid="screener-stock-backdrop"
        onClick={onClose}
        style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.5)" }}
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`${stock.name} research`}
        data-testid="screener-stock-panel"
        style={{
          position: "absolute", top: 0, bottom: 0, right: 0, width: mobile ? "100%" : "min(680px, 92vw)",
          background: "var(--bg-1)", borderLeft: mobile ? undefined : "1px solid var(--line-2)",
          display: "flex", flexDirection: "column", minWidth: 0,
        }}
      >
        <div className="flex items-center justify-between" style={{ padding: "12px 16px", borderBottom: "1px solid var(--cp-line)", gap: 12 }}>
          <span className="cp-eyebrow">Stock · opened from the screen</span>
          <button ref={closeRef} type="button" data-variant="ghost" className="cp-btn" onClick={onClose} data-testid="screener-stock-close" aria-label="Close the stock view">Close ✕</button>
        </div>
        <div className="flex min-w-0 flex-col" style={{ gap: 16, padding: 16, overflowY: "auto", flex: 1 }}>
          <StockResearch stock={stock} onClear={onClose} />
        </div>
      </aside>
    </div>
  );
}
