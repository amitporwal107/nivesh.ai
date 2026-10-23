/**
 * Price levels the scanner is watching — the product's other watchlist.
 *
 *   GET /api/positional/watchlist   four groups of chart setups, each stock with
 *                                   its close, the level to cross and a stop
 *
 * Read through the Trader desk's own hook (useWatchLevels), so the two screens
 * show the same rows. These are end-of-day levels to look at, not alerts:
 * nothing is sent when a level is crossed.
 */
import { useState } from "react";
import { StockName } from "../../components/EntityIcon";
import { Btn, DataTable, EmptyBlock, Footnote, LoadingBlock, Section, fmtPct, type Column } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useLiveOverlays } from "../../lib/useLiveQuotes";
import { dayLabel, fmtPrice } from "../markets/format";
import { LoadError } from "../markets/parts";
import { useWatchLevels, type WatchBucket, type WatchRow } from "../trading/queries";

const SETUP_LABEL: Record<WatchBucket, string> = {
  breakout_confirmed: "Breakout confirmed",
  pre_breakout: "Near breakout",
  true_accumulation: "Accumulation",
  trend_continuation: "Trend pullback",
};
const PREVIEW = 6;
const TITLE = "Price levels the scanner is watching";

export function SetupsToWatch() {
  const { ask, go } = useCopilotShell();
  const q = useWatchLevels();
  const [all, setAll] = useState(false);
  // Kite's live price against each level while the feed is LIVE (a column that is not there otherwise).
  const live = useLiveOverlays((q.data?.rows ?? []).map((r) => r.symbol), q.data?.asOf ?? null);

  if (q.isPending) return <Section title={TITLE}><LoadingBlock label="Loading the levels to watch" rows={2} /></Section>;
  if (q.isError) {
    return (
      <Section title={TITLE}>
        <div data-testid="watchlist-levels-error"><LoadError title="The levels to watch didn’t load" error={q.error} onRetry={() => q.refetch()} /></div>
      </Section>
    );
  }

  const { rows, asOf } = q.data;
  if (rows.length === 0) {
    return (
      <Section title={TITLE}>
        <div data-testid="watchlist-levels-empty">
          <EmptyBlock
            title="No price levels to watch right now"
            body={asOf
              ? `No stock fitted the scanner’s four chart setups on ${dayLabel(asOf, { year: true })}.`
              : "The scanner has no technical data to read yet, so it has no levels to show."}
          />
        </div>
      </Section>
    );
  }

  const columns: Column<WatchRow>[] = [
    { key: "stock", header: "Stock", width: "minmax(0,1.6fr)", render: (r) => <StockName symbol={r.symbol} sub={r.sector ?? undefined} size={24} testId="watchlist-level" /> },
    { key: "close", header: "Close", align: "right", num: true, render: (r) => fmtPrice(r.close) },
    ...(live.live
      ? [{
          key: "live", header: "Live · Kite", align: "right" as const, num: true,
          render: (r: WatchRow) => {
            const lq = live.get(r.symbol);
            if (!lq) return <span data-testid="watchlist-level-live" style={{ color: "var(--cp-ink-3)" }}>—</span>;
            return (
              <span data-testid="watchlist-level-live" title={lq.changePct != null ? `${lq.changePct > 0 ? "+" : ""}${lq.changePct.toFixed(2)}% on the day` : undefined} style={{ color: lq.changePct == null || lq.changePct === 0 ? undefined : lq.changePct > 0 ? "var(--mint)" : "var(--cp-danger)" }}>
                {fmtPrice(lq.ltp)}
              </span>
            );
          },
        }]
      : []),
    { key: "trigger", header: "Level to cross", align: "right", num: true, render: (r) => fmtPrice(r.trigger) },
    { key: "stop", header: "Stop · 1.5× ATR", align: "right", num: true, render: (r) => fmtPrice(r.stop) },
    { key: "atr", header: "Daily range", align: "right", num: true, render: (r) => fmtPct(r.atrPct, { digits: 2 }) },
    { key: "setup", header: "Setup", width: "minmax(0,1.2fr)", render: (r) => <span title={r.why ?? undefined}>{SETUP_LABEL[r.bucket]}</span> },
  ];

  return (
    <Section title={<span data-testid="watchlist-levels-count">{TITLE} · {rows.length}</span>} note={asOf ? `End of day · ${dayLabel(asOf, { year: true })}` : "End of day"} flush>
      <div data-testid="watchlist-levels">
        <DataTable
          columns={columns}
          rows={all ? rows : rows.slice(0, PREVIEW)}
          rowKey={(r) => `${r.bucket}:${r.symbol}`}
          minWidth={720}
          onRowClick={(r) => ask(`Show the ${r.symbol} chart with support and resistance${r.why ? `. Scanner note: ${r.why}` : ""}`)}
        />
      </div>
      <div className="flex flex-wrap items-center justify-between" style={{ gap: "8px 12px", padding: "10px 16px" }}>
        <div style={{ flex: "1 1 320px", minWidth: 0 }}>
          <Footnote>End-of-day levels from the scanner, not alerts and not a recommendation. Nothing is sent when a level is crossed.</Footnote>
        </div>
        <span className="flex flex-wrap items-center" style={{ gap: 8 }}>
          {rows.length > PREVIEW && (
            <Btn variant="ghost" data-testid="watchlist-levels-toggle" onClick={() => setAll((v) => !v)}>{all ? "Show fewer" : `Show all ${rows.length}`}</Btn>
          )}
          <Btn variant="ghost" onClick={() => go("trader")}>Open the Trader desk ›</Btn>
        </span>
      </div>
    </Section>
  );
}
