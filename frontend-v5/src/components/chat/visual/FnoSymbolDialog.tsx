/**
 * The F&O detail of one stock, opened from a build-up row or point in a visual answer (owner, 31 Oct 2026: "an option to show
 * the OI chain and the futures build-up for the stocks, may be a popup, and the user can open the chart analysis under the trade
 * desk to create a paper trade if required").
 *
 *   Option chain · OI   the desk's own chain (useOptionChain → FnoGate → OiRangeBar + ChainOiTable): the same figures as the
 *                       Options lab, read-only here (no leg buttons)
 *   Futures build-up    each listed future: close, day change, open interest and its change, the contract's own build-up label
 *   Open in Chart Analysis ›   Trade Desk › Chart Analysis for the symbol, where a strategy can be built and recorded as a paper trade
 *
 * Everything is the latest end-of-day F&O file (or the previous session's): the routes refuse older data, and the dialog says
 * which day it is. Opens only inside the app shell (it needs the desk's routes and its Chart Analysis to go to).
 */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { EmptyBlock, LoadingBlock } from "@/pages/CopilotApp/components/ui";
import { useOptionalCopilotShell } from "@/pages/CopilotApp/lib/shell-context";
import { ChainOiTable, FnoGate, OiRangeBar, UnderlineTabs } from "@/pages/CopilotApp/screens/tradingdesk/fno-parts";
import { useFnoFutures, useOptionChain } from "@/pages/CopilotApp/screens/trading/fno";
import { QueryProblem, fmtDay, fmtPrice, fmtQty, fmtSigned } from "@/pages/CopilotApp/screens/trading/parts";

type Tab = "chain" | "futures";
export interface FnoDetailContext { symbol: string; label?: string | null; sub?: string | null }

export const chartAnalysisView = (symbol: string) => `trader/desk?tab=trade&view=chart&sym=${encodeURIComponent(symbol)}`;

function Futures({ symbol }: { symbol: string }) {
  const q = useFnoFutures(symbol);
  if (q.isPending) return <div data-testid="va-fno-futures-loading"><LoadingBlock label={`Loading the ${symbol} futures`} rows={3} /></div>;
  if (q.isError) return <div data-testid="va-fno-futures-error"><QueryProblem what={`The ${symbol} futures`} error={q.error} onRetry={() => void q.refetch()} /></div>;
  const r = q.data;
  if (!r || r.kind === "none") return <div data-testid="va-fno-futures-none"><EmptyBlock title={`No futures for ${symbol}`} body={r ? `The server said: “${r.message}”.` : "Nothing came back."} /></div>;
  const f = r.data;
  return (
    <div data-testid="va-fno-futures" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <span style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>
        Futures of {fmtDay(f.as_of)}{f.spot != null ? ` · spot ${fmtPrice(f.spot)}` : ""}. Build-up = the contract's price change and open-interest change together.
      </span>
      <div className="cp-scroll overflow-x-auto">
        <table className="cp-num" style={{ width: "100%", minWidth: 560, borderCollapse: "collapse", fontSize: 12.5 }}>
          <thead>
            <tr style={{ color: "var(--cp-ink-3)" }}>
              {["Expiry", "Close", "Day change", "Open interest", "OI change", "Build-up"].map((h, i) => (
                <th key={h} scope="col" style={{ fontWeight: 400, padding: "4px 6px", textAlign: i === 0 || i === 5 ? "left" : "right", whiteSpace: "nowrap" }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {f.futures.map((c) => (
              <tr key={c.expiry} data-testid="va-fno-future" data-expiry={c.expiry} style={{ borderTop: "1px solid var(--cp-line)" }}>
                <td style={{ padding: "5px 6px", fontFamily: "var(--sans)" }}>{fmtDay(c.expiry)}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{c.close != null ? fmtPrice(c.close) : "—"}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{c.change_pct != null ? `${fmtSigned(c.change_pct)}%` : "—"}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{c.oi != null ? fmtQty(c.oi) : "—"}</td>
                <td style={{ padding: "5px 6px", textAlign: "right" }}>{c.change_in_oi != null ? fmtSigned(c.change_in_oi, 0) : "—"}</td>
                <td data-testid="va-fno-future-buildup" style={{ padding: "5px 6px", fontFamily: "var(--sans)", textTransform: "capitalize" }}>{c.oi_buildup ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function FnoSymbolDialog({ detail, onClose }: { detail: FnoDetailContext; onClose: () => void }) {
  const shell = useOptionalCopilotShell();
  const { symbol } = detail;
  const [tab, setTab] = useState<Tab>("chain");
  const chain = useOptionChain(symbol, null).state;
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    panel.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); opener?.focus?.(); };
  }, [onClose]);

  if (!shell) return null;
  const open = () => { onClose(); shell.go(chartAnalysisView(symbol)); };
  return createPortal(
    <div data-testid="va-fno-dialog-scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
      style={{ position: "fixed", inset: 0, zIndex: 80, background: "rgba(3,5,10,0.66)", display: "flex", alignItems: shell.mobile ? "flex-end" : "center", justifyContent: "center", padding: shell.mobile ? 0 : 24 }}>
      <div ref={panel} role="dialog" aria-modal="true" aria-label={`${symbol} futures and options detail`} tabIndex={-1} data-testid="va-fno-dialog" data-symbol={symbol}
        className="flex min-w-0 flex-col"
        style={{ width: "100%", maxWidth: 960, maxHeight: shell.mobile ? "92dvh" : "86dvh", overflow: "auto", gap: 12, padding: 16, outline: "none",
          background: "var(--bg-1)", border: "1px solid var(--cp-line)", borderRadius: shell.mobile ? "14px 14px 0 0" : 14 }}>
        <div className="flex flex-wrap items-center justify-between" style={{ gap: 8 }}>
          <span className="flex min-w-0 flex-col" style={{ gap: 2 }}>
            <strong data-testid="va-fno-dialog-title" style={{ fontSize: 17 }}>{symbol} · futures and options</strong>
            {(detail.label || detail.sub) && (
              <span data-testid="va-fno-dialog-context" style={{ fontSize: 12, color: "var(--cp-ink-3)" }}>In this answer: {[detail.label, detail.sub].filter(Boolean).join(" · ")}</span>
            )}
          </span>
          <span className="inline-flex flex-wrap items-center" style={{ gap: 8 }}>
            <button type="button" data-testid="va-fno-open-chart" className="cp-btn" onClick={open} style={{ padding: "5px 12px", fontSize: 12.5 }}>Open in Chart Analysis ›</button>
            <button type="button" data-testid="va-fno-close" className="cp-btn" data-variant="ghost" onClick={onClose} aria-label="Close" style={{ padding: "5px 12px", fontSize: 12.5 }}>Close</button>
          </span>
        </div>
        <UnderlineTabs<Tab> label={`${symbol} detail`} idPrefix="va-fno-tab" value={tab} onChange={setTab}
          tabs={[{ key: "chain", label: "Option chain · OI" }, { key: "futures", label: "Futures build-up" }]} />
        {tab === "chain"
          ? (
            <FnoGate symbol={symbol} state={chain} testId="va-fno-chain">
              {(c) => (
                <div data-testid="va-fno-chain" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
                  <OiRangeBar s={c.summary} testId="va-fno-range" />
                  <ChainOiTable chain={c} />
                </div>
              )}
            </FnoGate>
          )
          : <Futures symbol={symbol} />}
        <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>
          End-of-day F&O data, read only; nothing here places an order. To build a strategy on {symbol} and record it as a paper trade, open Chart Analysis.
        </span>
      </div>
    </div>,
    document.body,
  );
}
