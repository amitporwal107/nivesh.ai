/**
 * Shared cross-component types for the W1 workspace (§38.3–§38.9) — kept in one place so Toolbar, BottomBar,
 * Sidebar, ChartCanvas and ChartsScreen agree on the same vocabulary instead of each re-declaring it.
 */

/** §38.7 / §38.11: the three display timeframes the chart API serves (`timeframe=1D|1W|1M`). */
export type Timeframe = "1D" | "1W" | "1M";

export const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M"];

export const TIMEFRAME_LABEL: Record<Timeframe, string> = { "1D": "Daily", "1W": "Weekly", "1M": "Monthly" };

/** §38.7 P0 set plus Heikin-Ashi, which §38.7 calls "P1, labelled synthetic" — it is a client-side display
 *  transform over the same served bars (contract.ts `heikinAshi`), never an indicator and never an input to the
 *  pattern layer. */
export type ChartType = "candles" | "hollow_candles" | "ohlc_bars" | "line" | "area" | "heikin_ashi";

export const CHART_TYPE_LABEL: Record<ChartType, string> = {
  candles: "Candles", hollow_candles: "Hollow candles", ohlc_bars: "OHLC bars",
  line: "Line", area: "Area", heikin_ashi: "Heikin-Ashi",
};

/** §38.7: "auto, log and percent modes, set per pane." */
export type ScaleMode = "auto" | "log" | "percent";

/** The 1A right panel's tabs (design-1a-reference.md item 8), in display order. Patterns is the default open tab
 *  (§38.3 item 6). Provenance is not a tab: it stays one click away behind the status pill (§38.2), and the
 *  drawings list is a permanent footer below the tabs, as in the design. */
export type SidebarTab = "levels" | "indicators" | "patterns";

export const SIDEBAR_TABS: SidebarTab[] = ["levels", "indicators", "patterns"];
