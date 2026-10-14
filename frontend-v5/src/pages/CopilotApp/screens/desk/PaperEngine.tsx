import PaperTradesScreen from "@/pages/Research/PaperTradesScreen";
// The original screen's styles are scoped under .research-screen; research.css
// defines the colour aliases (--c-ink…, --c-line) those styles use.
import "@/pages/Research/research.css";

/**
 * The paper-trade engine's full record — the original v5 Research → Paper
 * screen, mounted as it is: today's frozen portfolio with its universe and
 * sizing what-ifs, one trade's path over six sessions with its lifecycle log
 * and chart, and the whole evaluation (every exit mode, the benchmarks, the
 * calibration buckets, cost sensitivity).
 *
 * Same adapter as the summary (services/adapters/paperTrades.adapter.ts), plus
 *   GET /api/paper-trades/trades/{id}                 one trade with its lifecycle log
 *   GET /api/research/chart-live/{symbol}/ohlcv       bars before entry, for the trade chart
 *
 * Loaded lazily from Paper.tsx, so the chart code is fetched only when this
 * view is opened.
 */
export default function PaperEngine() {
  return (
    <div data-testid="paper-engine" className="research-screen" style={{ margin: "0 -12px", minWidth: 0 }}>
      <PaperTradesScreen />
    </div>
  );
}
