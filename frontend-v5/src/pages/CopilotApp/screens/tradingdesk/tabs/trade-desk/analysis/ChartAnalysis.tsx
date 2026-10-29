/**
 * Trade Desk › Chart Analysis › Live chart (?tab=trade&view=chart&sub=live&sym=[&tp=]) — the owner's new chart interface of
 * 29 Oct ("Nivesh Chart"), built as drawn with real data (test_reports/chart_analysis_v2_TESTCASES.md).
 *
 *   left card   SYMBOL [state] NSE · CASH · DAILY|15M · SIGNAL … · LAST · + PAPER TRADE
 *               stats: PCR · FUT OI Δ · MAX PAIN · ATM IV · IV PCTILE · EXP. MOVE
 *               SIGNALS ON CHART: Build-up · OI walls · Max pain · Pattern · Confirmation · RVOL · Events
 *               readout · the chart (AnalysisChart.tsx: price, futures OI, OI Δ, build-up, strike ladder)
 *               OPTION CHAIN (OptionChain.tsx) · EXPIRY pills · LADDER modes · the summary lines
 *               RECOMMENDED STRATEGIES (RecoStrategies.tsx) · footer
 *   right       the PAPER TRADE basket (BasketPanel.tsx), beside the card from TWO_COLUMN_MIN px, else below it
 *   below       the strategy panel (StrategyPanel.tsx): legs + Greeks, margin, payoff, scenario table
 *
 *   GET /api/desk/live-chart/{sym}               candles, EMA 20, RVOL, markers, levels, signal, LAST (Kite close until EOD)
 *   GET /api/fno/{sym}/futures/oi-buildup        futures OI per bar (intraday bars / daily_bars), build-up windows
 *   GET /api/fno/{sym}/chain[/consolidated]      PCR, max pain, walls, ATM IV, expected move, the ladder and the chain
 *   GET /api/fno/{sym}/iv-history                IV percentile (null with the reason until 252 recorded sessions)
 *   GET /api/desk/chart-events/{sym}             market events (the Events chip; the owner asked for them on 29 Oct)
 *   GET /api/desk/paper-trades                   the state badge (an open paper trade on this symbol)
 *
 * Every figure is a route's; a figure the data does not give is "—" with why. Paper only; nothing is sent to a broker.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { ApiError } from "@/services/api/errors";
import { ErrorBlock, LoadingBlock, TONE_COLOR, fmtNum } from "../../../../../components/ui";
import { useCopilotShell } from "../../../../../lib/shell-context";
import { useLiveMeta, useLiveOverlay } from "../../../../../lib/useLiveQuotes";
import { fmtDay } from "../../../../trading/parts";
import { useDesk } from "../../../context";
import { useDeskScanner } from "../../../desk-data";
import { usePaperTrades, type PaperTrade } from "../../../desk-trading";
import { BUILDUP_META } from "../../../fno-buildup";
import type { DailyBar } from "../../../indicators";
import { useTop10Stocks } from "../../../top10-data";
import { useAiWatchlist } from "../../../../workspace/ai-watchlist-data";
import { useChartEvents, useIvHistory, useLiveChart, useOiBuildup, type LiveChart, type OiSeries, type OiWindow } from "../live-chart-data";
import { AnalysisChart, fmtLakh, type BuildupTag, type ChartLevel, type ChartMark, type EventChip, type LadderMode, type TradeLine } from "./AnalysisChart";
import { BasketPanel } from "./BasketPanel";
import { BasketProvider, useBasket } from "./basket";
import { SLOT_NAME, SLOTS, useAnalysisChain, type AnalysisChain, type Slot } from "./chain-data";
import { OptionChain } from "./OptionChain";
import { RecoStrategies } from "./RecoStrategies";
import { StrategyPanel } from "./StrategyPanel";

const mono = { fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.12em", textTransform: "uppercase" as const };
const quiet = { fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-3)" } as const;
/** The chart card and the basket sit side by side from this width; below it they stack. */
export const TWO_COLUMN_MIN = 1000;
const DAILY_SESSIONS = 60;      // the live chart route draws 60 daily bars in its daily fallback

const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v);
const priceTxt = (v: number | null | undefined) => (fin(v) ? v.toLocaleString("en-IN", { minimumFractionDigits: v >= 1000 ? 1 : 2, maximumFractionDigits: v >= 1000 ? 1 : 2 }) : "—");
const signedTxt = (v: number | null | undefined, dp = 2) => (fin(v) ? `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp })}` : "—");
const pctOf = (chg: number | null | undefined, now: number | null | undefined) => (fin(chg) && fin(now) && now - chg !== 0 ? (chg / (now - chg)) * 100 : null);
const pctTxt = (v: number | null) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(2)}%`);
const istTime = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(t) ? new Date(t).toLocaleTimeString("en-GB", { timeZone: "Asia/Kolkata", hour12: false }) : null;
};
const dayMonth = (iso: string) => new Date(`${iso.slice(0, 10)}T12:00:00+05:30`).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" }).toUpperCase();
const expiryTxt = (iso: string | null) => (iso ? fmtDay(iso) : "—");

function useBoxWidth(box: HTMLElement | null): number | null {
  const [w, setW] = useState<number | null>(null);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((e) => { const v = e[0]?.contentRect.width; if (v) setW(v); });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box]);
  return w;
}

// ── the page ─────────────────────────────────────────────────────────────

export default function ChartAnalysis() {
  const desk = useDesk();
  const [params] = useSearchParams();
  const scan = useDeskScanner();
  const symbol = (desk.symbol ?? scan.data?.setups[0]?.symbol ?? null)?.toUpperCase() ?? null;
  if (!symbol) {
    if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={4} />;
    return <p data-testid="ca-nosymbol" className="m-0" style={quiet}>Pick a stock with the symbol search above to open its chart.</p>;
  }
  const tpRaw = params.get("tp");
  const tp = tpRaw && /^[A-Za-z0-9_:-]{1,80}$/.test(tpRaw) ? tpRaw : null;
  return (
    <BasketProvider symbol={symbol}>
      <Analysis key={symbol} symbol={symbol} tp={tp} />
    </BasketProvider>
  );
}

const TOGGLES = [
  { key: "build", label: "Build-up" }, { key: "walls", label: "OI walls" }, { key: "pain", label: "Max pain" },
  { key: "pattern", label: "Pattern" }, { key: "conf", label: "Confirmation" }, { key: "rvol", label: "RVOL" }, { key: "events", label: "Events" },
] as const;
type ToggleKey = (typeof TOGGLES)[number]["key"];

const TAG: Record<string, BuildupTag["tag"]> = { long_buildup: "LB", short_buildup: "SB", short_covering: "SC", long_unwinding: "LU" };
const SOFT: Record<string, string> = { mint: "var(--mint-soft)", danger: "var(--danger-soft)", indigo: "var(--indigo-soft)", amber: "var(--amber-soft)", ink: "transparent" };
const GLYPH: Record<string, [string, string]> = {
  results: ["R", "var(--mint)"], board: ["B", "var(--cp-indigo)"], filing: ["F", "var(--cp-ink-2)"], dividend: ["C", "var(--amber)"], split: ["C", "var(--amber)"],
  bonus: ["C", "var(--amber)"], buyback: ["C", "var(--amber)"], rights: ["C", "var(--amber)"], agm: ["C", "var(--amber)"], demerger: ["C", "var(--amber)"],
  macro: ["M", "var(--cp-danger)"], fno_expiry: ["X", "var(--cp-ink-3)"], fii_dii: ["$", "var(--cp-indigo)"],
};

/** The paper trade on this symbol that is still open (pending entry or a position), if any. */
function openTradeOf(trades: PaperTrade[] | undefined, symbol: string, planId: string | null): PaperTrade | null {
  const mine = (trades ?? []).filter((t) => t.status === "open" && t.symbol.toUpperCase() === symbol.toUpperCase());
  return mine.find((t) => planId && t.tradePlanId === planId) ?? mine[0] ?? null;
}
const filled = (t: PaperTrade | null) => !!t && (t.entryStatus === "reached" || t.entryStatus === "assumed");

/** The bar a window ends on: its last bar inside [start, end) (intraday); the bar of its day (daily). */
function barOfWindow(bars: DailyBar[], w: OiWindow, daily: boolean): number {
  if (daily) return bars.findIndex((b) => b.day.slice(0, 10) === (w.end || w.day).slice(0, 10));
  let at = -1;
  bars.forEach((b, i) => { if (b.day >= w.start && b.day < w.end) at = i; });
  return at;
}

function directionOf(d: LiveChart | null, w: OiWindow | null): { dir: "bullish" | "bearish" | "neutral"; why: string } {
  const lv = d?.levels.direction?.toLowerCase() ?? null;
  const sig = d?.signal ? `the ${d.signal.kind ?? "scanner"} signal of ${dayMonth(d.signal.signal_date)}` : d?.levels.source === "plan" ? "the trade plan" : null;
  if (lv && sig) {
    if (lv === "long" || lv === "bullish") return { dir: "bullish", why: `from ${sig}` };
    if (lv === "short" || lv === "bearish") return { dir: "bearish", why: `from ${sig}` };
    if (lv === "neutral") return { dir: "neutral", why: `from ${sig}` };
  }
  if (w?.label && w.label !== "neutral") {
    const meta = BUILDUP_META[w.label];
    return { dir: w.label === "long_buildup" || w.label === "short_covering" ? "bullish" : "bearish", why: `from the futures' ${meta.label.toLowerCase()}` };
  }
  return { dir: "neutral", why: "no signal and no clear futures build-up" };
}

function Analysis({ symbol, tp }: { symbol: string; tp: string | null }) {
  const { mobile } = useCopilotShell();
  const basket = useBasket();
  // This symbol's plan: ?tp=, else the stored AI watchlist day, else the ideas board only when already cached (never fetched here: ~16 s).
  const watch = useAiWatchlist(null);
  const board = useTop10Stocks(false);
  const row = !tp ? watch.data?.cash.find((e) => e.symbol.toUpperCase() === symbol) ?? null : null;
  const idea = !tp ? board.data?.ideas.find((i) => i.symbol?.toUpperCase() === symbol) ?? null : null;
  const planId = tp ?? row?.trade_plan_id ?? row?.trade_plan?.plan_id ?? (idea as { trade_plan?: { plan_id?: string } | null } | null)?.trade_plan?.plan_id ?? null;
  const meta = useLiveMeta();
  const open = meta.session === "open";
  const q = useLiveChart(symbol, planId, open);
  const d = q.data ?? null;
  const daily = d?.timeframe.interval === "1d";
  const oiQ = useOiBuildup(symbol, open, daily ? DAILY_SESSIONS : 0);
  const iv = useIvHistory(symbol);
  const ev = useChartEvents(symbol);
  const paper = usePaperTrades();
  const quote = useLiveOverlay(symbol);
  const [slot, setSlot] = useState<Slot>("current");
  const [mode, setMode] = useState<LadderMode>("oi");
  const [on, setOn] = useState<Record<ToggleKey, boolean>>({ build: true, walls: true, pain: true, pattern: true, conf: true, rvol: true, events: true });
  const [sel, setSel] = useState<number | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const width = useBoxWidth(box);
  const wide = (width ?? 1200) >= TWO_COLUMN_MIN;
  const ch = useAnalysisChain(symbol, slot);
  const chain: AnalysisChain | null = ch.view.status === "ok" ? ch.view.chain : null;
  const selected = sel ?? chain?.atm ?? null;

  const bars: DailyBar[] = useMemo(() => (d?.bars ?? []).map(([day, o, h, l, c, v]) => ({ day, open: o, high: h, low: l, close: c, volume: v })), [d]);
  const oi = oiQ.data?.kind === "ok" ? oiQ.data.data : null;
  const series: OiSeries | null = oi ? (slot === "consolidated" ? oi.consolidated : oi.contracts.find((c) => c.slot === slot) ?? null) : null;
  const trade = openTradeOf(paper.data?.trades, symbol, planId);

  // futures OI and its change on the chart's bars
  const fut = useMemo(() => {
    if (!series || !bars.length) return null;
    const oiArr: Array<number | null> = bars.map(() => null);
    const chg: Array<number | null> = bars.map(() => null);
    if (daily) {
      const byDay = new Map(series.daily_bars.map((b) => [b[0].slice(0, 10), b]));
      bars.forEach((b, i) => { const r = byDay.get(b.day.slice(0, 10)); if (r) { oiArr[i] = r[3]; chg[i] = r[4]; } });
    } else {
      // Kite 15m futures candles [t, close, volume, oi], one baseline bar before the first shown (contract A)
      const ms = (t: string) => Date.parse(t);
      const at = new Map(series.bars.map((b, k) => [ms(b[0]), k]));
      bars.forEach((b, i) => {
        const k = at.get(ms(b.day));
        const v = k != null ? series.bars[k][3] : null;
        oiArr[i] = v;
        const prev = k != null && k > 0 ? series.bars[k - 1][3] : null;
        chg[i] = fin(v) && fin(prev) ? v - prev : null;     // the same contract's bar-on-bar change
      });
    }
    return oiArr.some(fin) ? { oi: oiArr, change: chg, label: SLOT_NAME[slot] } : null;
  }, [series, bars, daily, slot]);
  const windows = series ? (daily ? series.daily_windows : series.windows) : [];
  const lastWindow = [...windows].reverse().find((w) => w.label != null) ?? null;

  if (q.isPending) return <div ref={setBox}><LoadingBlock label={`Reading ${symbol}'s chart`} rows={8} /></div>;
  if (q.error instanceof ApiError && q.error.status === 404) {
    return <p data-testid="ca-noprices" role="note" className="m-0" style={{ fontSize: 13, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>No prices on record for {symbol}, so there is no chart. Search another stock above, or check the symbol on Market Desk › Stock Research.</p>;
  }
  if (q.isError || !d) return <div data-testid="ca-error"><ErrorBlock error={q.error} onRetry={() => q.refetch()} /></div>;

  const live = quote?.kind === "live";
  const lastPrice = live ? quote.ltp : d.last.price;
  const today = daily ? d.timeframe.today ?? null : null;
  const lastWhen = live ? `${istTime(quote.ts) ?? ""} IST` : daily ? fmtDay(d.last.at) : `${istTime(d.last.at) ?? ""} IST`;
  const lastSrc = live ? "KITE LIVE" : today?.source === "kite_close" ? "KITE CLOSE · PROVISIONAL" : today?.source === "kite_live" ? "KITE LIVE" : d.last.source === "eod" || daily ? "EXCHANGE EOD" : "KITE";
  const state = trade ? (filled(trade) ? "POSITION_OPEN" : "ENTRY_PENDING") : d.signal?.kind ?? "NO_SIGNAL";
  const stateColor = state === "READY" || state === "ENTRY_PENDING" ? "amber" : state === "CONFIRMED" || state === "POSITION_OPEN" ? "mint" : "ink";

  // ── marks on the chart ──
  const idxOf = (at: string) => {
    const k = bars.findIndex((b) => b.day === at);
    return k >= 0 ? k : bars.findIndex((b) => b.day.slice(0, 10) === at.slice(0, 10));
  };
  const marks: ChartMark[] = d.markers.flatMap((m): ChartMark[] => {
    const i = idxOf(m.at);
    if (i < 0) return [];
    if ((m.kind === "WATCH" || m.kind === "READY") && on.pattern) return [{ i, label: m.kind, color: m.kind === "READY" ? "var(--amber)" : "var(--cp-ink-2)", title: m.text ?? m.kind, row: 0 as const }];
    if (m.kind === "RVOL" && on.rvol) return [{ i, label: m.rvol != null ? `RVOL ${fmtNum(m.rvol, 1)}×` : "RVOL", color: "var(--cp-indigo)", title: m.text ?? "Relative volume", row: 1 as const }];
    return [];
  });
  const confirms = on.conf ? d.markers.filter((m) => m.kind === "CONFIRMED").map((m) => idxOf(m.at)).filter((i) => i >= 0) : [];
  const levels: ChartLevel[] = [];
  if (chain && on.walls) {
    if (chain.callWall) levels.push({ key: "call-wall", value: chain.callWall.strike, label: "CALL WALL", color: "var(--cp-danger)" });
    if (chain.putWall) levels.push({ key: "put-wall", value: chain.putWall.strike, label: "PUT WALL", color: "var(--mint)" });
  }
  if (chain && on.pain && fin(chain.maxPain)) levels.push({ key: "max-pain", value: chain.maxPain, label: "MAX PAIN", color: "var(--amber)" });
  const buildups: BuildupTag[] = on.build ? windows.flatMap((w) => {
    if (!w.label || w.label === "neutral") return [];
    const i1 = barOfWindow(bars, w, daily);
    if (i1 < 0) return [];
    const i0 = Math.max(0, i1 - (daily ? Math.max(1, w.bars) : Math.max(1, w.bars)) + 1);
    const meta = BUILDUP_META[w.label];
    return [{ i0, i1, tag: TAG[w.label], color: TONE_COLOR[meta.tone], soft: SOFT[meta.tone] ?? "transparent",
      title: `${meta.label} (${meta.rule}) ${w.start.slice(11, 16) || fmtDay(w.day)}–${w.end.slice(11, 16)}: price ${signedTxt(w.price_change)}, OI ${fmtLakh(w.oi_change, true)}` }];
  }) : [];
  const events: EventChip[] = on.events ? (ev.data?.events ?? []).flatMap((e) => {
    const i = bars.findIndex((b) => b.day.slice(0, 10) === e.date);
    if (i < 0) return [];
    const [glyph, color] = GLYPH[e.kind] ?? ["•", "var(--cp-ink-2)"];
    const r = e.reaction;
    const reaction = r ? ` · day ${pctTxt(r.day_change_pct ?? null)}, next day ${pctTxt(r.next_day_change_pct ?? null)}, volume ${r.volume_x_avg20 != null ? `${fmtNum(r.volume_x_avg20, 1)}×` : "—"} avg` : "";
    return [{ i, glyph, color, kind: e.kind, title: `${fmtDay(e.date)} ${e.title}${reaction}` }];
  }) : [];

  // ── the basket's lines: the underlying levels (STOP / TGT drag) and the cash entry ──
  const und = basket.legs.filter((l) => l.kind === "FUT" || l.kind === "CASH");
  const cashOnly = basket.legs.length > 0 && basket.legs.every((l) => l.kind === "CASH");
  const tradeLines: TradeLine[] = [];
  und.forEach((l) => {
    const entry = l.kind === "CASH" ? basket.levels.cashEntry ?? l.entry : l.entry;
    tradeLines.push({ key: `${l.kind}-entry`, value: entry, label: l.kind === "CASH" ? "C ENTRY" : "F ENTRY", color: "var(--cp-ink-2)", drag: l.kind === "CASH" && cashOnly ? "cashEntry" : null });
  });
  if (basket.legs.length) {
    if (fin(basket.levels.stop)) tradeLines.push({ key: "stop", value: basket.levels.stop, label: "STOP", color: "var(--cp-danger)", drag: "stop" });
    if (fin(basket.levels.target)) tradeLines.push({ key: "target", value: basket.levels.target, label: "TGT", color: "var(--mint)", drag: "target" });
  } else {
    // no basket yet: the plan's or the signal's own levels, not draggable
    if (fin(d.levels.entry)) tradeLines.push({ key: "sig-entry", value: d.levels.entry, label: "ENTRY", color: "var(--cp-ink-2)" });
    if (fin(d.levels.stop)) tradeLines.push({ key: "sig-stop", value: d.levels.stop, label: "STOP", color: "var(--cp-danger)" });
    const t1 = d.levels.targets[0]?.price;
    if (fin(t1)) tradeLines.push({ key: "sig-t1", value: t1, label: d.levels.targets[0]?.name ?? "T1", color: "var(--mint)" });
  }

  // ── readout ──
  const ai = active ?? bars.length - 1;
  const ab = bars[ai];
  const aOi = fut?.oi[ai] ?? null, aChg = fut?.change[ai] ?? null;
  const readout = ab ? `${daily ? fmtDay(ab.day) : `${fmtDay(ab.day)} ${ab.day.slice(11, 16)}`} · O ₹${priceTxt(ab.open)} · H ₹${priceTxt(ab.high)} · L ₹${priceTxt(ab.low)} · C ₹${priceTxt(ab.close)} · Vol ${fmtLakh(ab.volume)}` : "—";

  // ── stats ──
  const ivp = iv.data?.iv_percentile;
  const futLast = daily ? series?.daily_bars[series.daily_bars.length - 1] ?? null : null;
  const futChg = daily ? futLast?.[4] ?? null : lastWindow?.oi_change ?? null;
  const futChgPct = daily ? pctOf(futLast?.[4], futLast?.[3]) : lastWindow?.oi_change_pct ?? null;
  const futWhen = daily ? (futLast ? `session ${fmtDay(futLast[0])}` : "—") : lastWindow ? `${lastWindow.start.slice(11, 16)}–${lastWindow.end.slice(11, 16)} window` : "—";
  const notFno = ch.notFno;
  const noChain = notFno ? "not in F&O" : ch.view.status === "loading" ? "loading" : ch.view.status === "error" ? "chain did not load" : ch.view.status === "none" ? "no chain" : null;
  const stats: Array<{ k: string; v: string; n: string; c: string; small?: boolean }> = [
    { k: "PCR", v: chain?.pcr != null ? chain.pcr.toFixed(2) : "—", c: "var(--cp-ink)", n: noChain ?? "put OI ÷ call OI" },
    { k: "FUT OI Δ", v: futChg != null ? fmtLakh(futChg, true) : "—", c: futChg == null ? "var(--cp-ink)" : futChg >= 0 ? "var(--mint)" : "var(--cp-danger)", n: futChg != null ? `${pctTxt(futChgPct ?? null)} · ${futWhen}` : oiQ.data?.kind === "none" ? oiQ.data.message : oiQ.isPending ? "loading" : "no futures OI" },
    { k: "MAX PAIN", v: chain?.maxPain != null ? fmtNum(chain.maxPain, 0) : "—", c: "var(--amber)", n: chain?.maxPain != null && fin(lastPrice) ? `${signedTxt(chain.maxPain - lastPrice, 0)} vs last` : noChain ?? "—" },
    { k: "ATM IV", v: chain?.atmIv != null ? `${chain.atmIv.toFixed(1)}%` : "—", c: "var(--cp-ink)", n: chain?.atmIv != null ? `model, end of day ${dayMonth(chain.asOf)}` : slot === "consolidated" ? "pick an expiry" : noChain ?? "not available" },
    { k: "IV PCTILE", v: ivp != null ? `${Math.round(ivp)}` : "not recorded", c: ivp != null ? "var(--cp-ink)" : "var(--cp-ink-2)", small: ivp == null, n: ivp != null ? `of ${iv.data?.sessions ?? "—"} recorded sessions` : iv.data?.reason ?? (iv.isPending ? "loading" : "needs 252 recorded sessions") },
    { k: "EXP. MOVE", v: chain?.expectedMove != null ? `±${priceTxt(chain.expectedMove)}` : "—", c: "var(--cp-indigo)", n: chain?.expectedMovePct != null ? `${chain.expectedMovePct.toFixed(2)}% to expiry` : slot === "consolidated" ? "pick an expiry" : noChain ?? "not available" },
  ];

  // ── summary lines ──
  const sumWindow = lastWindow;
  const sumMeta = sumWindow?.label ? BUILDUP_META[sumWindow.label] : null;
  const expName = slot === "consolidated" ? "CONSOLIDATED" : `${SLOT_NAME[slot].toUpperCase()} · ${chain?.expiry ? fmtDay(chain.expiry).toUpperCase() : "—"}`;
  const selRow = chain && selected != null ? chain.rows.find((r) => r.strike === selected) ?? null : null;
  const dir = directionOf(d, lastWindow);
  const planLevels = { entry: d.levels.entry ?? null, stop: d.levels.stop ?? null, target: d.levels.targets[0]?.price ?? null, direction: d.levels.direction ?? null };

  const header = (
    <div className="flex flex-wrap items-center" style={{ gap: "10px 12px" }}>
      <span data-testid="ca-symbol" style={{ fontFamily: "var(--display)", fontSize: mobile ? 28 : 34, lineHeight: 1 }}>{symbol}</span>
      <span data-testid="ca-state" data-state={state} style={{ ...mono, fontSize: 11, color: stateColor === "ink" ? "var(--cp-ink-2)" : `var(--${stateColor})`, border: `1px solid ${stateColor === "ink" ? "var(--line-3)" : `var(--${stateColor}-line)`}`, background: stateColor === "ink" ? "transparent" : `var(--${stateColor}-soft)`, borderRadius: 6, padding: "4px 9px" }}>{state.replace("_", " ")}</span>
      <span data-testid="ca-meta" style={{ ...mono, fontSize: 11, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        NSE · CASH · {daily ? "DAILY" : d.timeframe.label}{d.signal ? ` · SIGNAL ${dayMonth(d.signal.signal_date)}${d.signal.revision ? ` R${d.signal.revision}` : ""}` : " · NO SCANNER SIGNAL"}
      </span>
      <div style={{ flex: 1 }} />
      <span data-testid="ca-last" data-source={live ? "kite_live" : today?.source ?? d.last.source ?? undefined} className="cp-num" style={{ ...mono, fontSize: 11, letterSpacing: "0.1em", color: "var(--cp-ink-3)" }}>
        LAST {priceTxt(lastPrice)} · {lastWhen} · {lastSrc}
      </span>
      <button type="button" data-testid="ca-paper-btn" onClick={() => basket.setOpen(true)} style={{ cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 12, fontWeight: 500, letterSpacing: "0.1em", color: "var(--bg-0)", background: "var(--mint)", border: 0, borderRadius: 8, padding: "9px 14px" }}>＋ PAPER TRADE</button>
    </div>
  );

  const card: ReactNode = (
    <section data-testid="ca-card" data-interval={d.timeframe.interval} className="flex min-w-0 flex-col" style={{ gap: 0, background: "var(--bg-1)", border: "1px solid var(--line-2)", borderRadius: 14, padding: mobile ? 16 : "22px 22px 18px", boxShadow: "var(--shadow-card)" }}>
      {header}
      {d.timeframe.reason && (
        <p data-testid="ca-kite-fallback" role="note" className="m-0" style={{ marginTop: 10, fontSize: 12.5, lineHeight: 1.5, color: "var(--amber)" }}>
          {d.timeframe.reason_text ?? "Kite login needed for 15m candles."} Showing daily candles{today ? `; ${fmtDay(today.day)} from ${today.source === "kite_close" ? "the Kite close (provisional until the exchange's end-of-day file)" : "the live Kite price (still forming)"}` : " (end of day)"}.
        </p>
      )}
      {/* stats */}
      <div data-testid="ca-stats" style={{ marginTop: 16, display: "grid", gridTemplateColumns: mobile ? "repeat(2, minmax(0, 1fr))" : "repeat(6, minmax(0, 1fr))", gap: 1, background: "var(--cp-line)", border: "1px solid var(--cp-line)", borderRadius: 10, overflow: "hidden" }}>
        {stats.map((s) => (
          <div key={s.k} data-testid={`ca-stat-${s.k.toLowerCase().replace(/[^a-z]+/g, "-").replace(/-$/, "")}`} style={{ background: "var(--bg-1)", padding: "10px 14px", minWidth: 0 }}>
            <div style={{ ...mono, fontSize: 10, color: "var(--cp-ink-3)" }}>{s.k}</div>
            <div className="cp-num" style={{ fontFamily: "var(--mono)", fontWeight: 500, fontSize: s.small ? 14 : 19, marginTop: 4, color: s.c, overflowWrap: "anywhere" }}>{s.v}</div>
            <div style={{ fontSize: 11, color: "var(--cp-ink-3)", marginTop: 2, lineHeight: 1.35 }}>{s.n}</div>
          </div>
        ))}
      </div>
      {/* toggles */}
      <div role="group" aria-label="Signals on chart" className="flex flex-wrap items-center" style={{ marginTop: 14, gap: 8 }}>
        <span style={{ ...mono, color: "var(--cp-ink-3)", marginRight: 4 }}>Signals on chart</span>
        {TOGGLES.map((t) => (
          <button key={t.key} type="button" data-testid={`ca-toggle-${t.key}`} aria-pressed={on[t.key]} onClick={() => setOn((x) => ({ ...x, [t.key]: !x[t.key] }))}
            style={{ cursor: "pointer", whiteSpace: "nowrap", fontSize: 12, fontWeight: 500, borderRadius: 999, padding: "5px 12px", border: `1px solid ${on[t.key] ? "var(--mint-line)" : "var(--line-3)"}`, background: on[t.key] ? "var(--mint-soft)" : "transparent", color: on[t.key] ? "var(--mint)" : "var(--cp-ink-2)" }}>
            {t.label}
          </button>
        ))}
      </div>
      {/* readout */}
      <div data-testid="ca-readout" aria-live="polite" className="cp-num" style={{ marginTop: 10, fontFamily: "var(--mono)", fontSize: 11, letterSpacing: "0.04em", color: "var(--cp-ink-3)", lineHeight: 1.5 }}>
        {readout} · <span style={{ color: "var(--cp-indigo)" }}>FUT OI {fmtLakh(aOi)}</span> · <span style={{ color: aChg == null ? undefined : aChg >= 0 ? "var(--mint)" : "var(--cp-danger)" }}>Δ {fmtLakh(aChg, true)} ({pctTxt(pctOf(aChg, aOi))})</span>
      </div>
      {/* the chart */}
      <div style={{ marginTop: 6 }}>
        {bars.length ? (
          <AnalysisChart bars={bars} intraday={!daily} ema={d.ema20} marks={marks} confirms={confirms} levels={levels} tradeLines={tradeLines} last={lastPrice}
            fut={fut} futEmpty={oiQ.isPending ? "Reading the futures OI…" : oiQ.data?.kind === "none" ? oiQ.data.message : oiQ.isError ? "The futures OI did not load." : daily ? "No daily futures OI for these sessions." : "No futures OI for these bars."}
            buildups={buildups} events={events} compact={mobile} active={active} onActive={setActive}
            ladder={chain ? { rows: chain.rows, mode, selected, atm: chain.atm, putWall: chain.putWall?.strike ?? null, callWall: chain.callWall?.strike ?? null, onSelect: setSel } : null}
            ladderEmpty={notFno ? `${symbol} is not in F&O` : ch.view.status === "none" ? ch.view.message : null}
            onPriceClick={cashOnly ? (p) => basket.setLevels({ cashEntry: p }) : undefined}
            onDrag={(key, p) => basket.setLevels(key === "stop" ? { stop: p } : key === "target" ? { target: p } : { cashEntry: p })} />
        ) : <span style={quiet}>No candles to draw.</span>}
      </div>
      <div style={{ marginTop: 6, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", color: "var(--cp-ink-4)", lineHeight: 1.6 }}>
        BUILD-UP BY {daily ? "4-SESSION" : "4-BAR"} WINDOW · LB LONG BUILD-UP · SB SHORT BUILD-UP · SC SHORT COVERING · LU LONG UNWINDING{basket.legs.length ? " · DRAG STOP OR TGT TO MOVE IT" : ""}{events.length ? " · R RESULTS · B BOARD · F FILING · C CORPORATE ACTION · M MACRO · X F&O EXPIRY · $ FII/DII DAY" : ""}
      </div>
      {oi && (oi.missing_note || (slot !== "consolidated" && oi.missing_slots.includes(slot))) && <span style={{ ...quiet, fontSize: 11, marginTop: 4 }}>{oi.missing_note}</span>}

      {/* option chain */}
      <div style={{ marginTop: 14 }}>
        {chain ? <OptionChain symbol={symbol} chain={chain} selected={selected} onSelect={setSel} compact={mobile} />
          : ch.view.status === "loading" ? <LoadingBlock label="Reading the option chain" rows={3} />
            : ch.view.status === "error" ? <div data-testid="ca-chain-error"><ErrorBlock error={ch.view.error} onRetry={ch.view.retry} /></div>
              : <p data-testid="ca-chain-none" className="m-0" style={quiet}>{notFno ? `${symbol} is not in the F&O segment, so there is no option chain. The paper basket takes a cash trade.` : ch.view.status === "none" ? ch.view.message : ""}</p>}
      </div>

      {/* expiry + ladder mode */}
      {!notFno && (
        <div className="flex flex-wrap items-center" style={{ marginTop: 12, gap: 8 }}>
          <span style={{ ...mono, color: "var(--cp-ink-3)", marginRight: 4 }}>Expiry</span>
          {SLOTS.map((s) => {
            const date = s === "consolidated" ? "all" : ch.expiries[s === "current" ? 0 : s === "next" ? 1 : 2]?.expiry ?? null;
            const act = s === slot;
            return (
              <button key={s} type="button" data-testid={`ca-expiry-${s}`} aria-pressed={act} disabled={s !== "consolidated" && !date && ch.expiries.length > 0} onClick={() => setSlot(s)}
                style={{ cursor: "pointer", whiteSpace: "nowrap", fontSize: 12, fontWeight: 500, borderRadius: 999, padding: "6px 13px", border: `1px solid ${act ? "var(--mint-line)" : "var(--line-3)"}`, background: act ? "var(--mint-soft)" : "transparent", color: act ? "var(--mint)" : "var(--cp-ink-2)" }}>
                {SLOT_NAME[s]}<span style={{ color: "var(--cp-ink-3)", fontWeight: 400 }}> · {date === "all" ? "all" : expiryTxt(date)}</span>
              </button>
            );
          })}
          <div style={{ flex: 1 }} />
          <span style={{ ...mono, color: "var(--cp-ink-3)" }}>Ladder</span>
          {(["oi", "oichg", "vol"] as LadderMode[]).map((m) => (
            <button key={m} type="button" data-testid={`ca-ladder-${m}`} aria-pressed={mode === m} onClick={() => setMode(m)}
              style={{ cursor: "pointer", whiteSpace: "nowrap", ...mono, fontSize: 11, fontWeight: 500, letterSpacing: "0.08em", borderRadius: 8, padding: "6px 10px", border: `1px solid ${mode === m ? "var(--indigo-line)" : "var(--line-3)"}`, background: mode === m ? "var(--indigo-soft)" : "transparent", color: mode === m ? "var(--cp-indigo)" : "var(--cp-ink-2)" }}>
              {m === "oi" ? "OI" : m === "oichg" ? "OI Δ" : "VOLUME"}
            </button>
          ))}
        </div>
      )}

      {/* summary lines */}
      <div data-testid="ca-summary" className="flex flex-col" style={{ marginTop: 14, gap: 8 }}>
        {sumWindow && sumMeta && (
          <Line testid="ca-sum-buildup" tone={sumMeta.tone} tag={sumMeta.label.toUpperCase()}>
            {SLOT_NAME[slot]}{series?.expiry ? ` (${fmtDay(series.expiry)})` : ""}: price {signedTxt(sumWindow.price_change)}, OI {fmtLakh(sumWindow.oi_change, true)}{sumWindow.oi_change_pct != null ? ` (${pctTxt(sumWindow.oi_change_pct)})` : ""} in {daily ? `the sessions to ${fmtDay(sumWindow.end || sumWindow.day)}` : `${sumWindow.start.slice(11, 16)}–${sumWindow.end.slice(11, 16)} ${fmtDay(sumWindow.day)}`}. {sumMeta.rule}.
          </Line>
        )}
        {chain?.callWall && <Line testid="ca-sum-call-wall" tone="danger" tag={`CALL WALL ${fmtNum(chain.callWall.strike, 0)}`}>Most call OI at or above spot ({fmtLakh(chain.callWall.oi)}). Resistance as positioning, not a level the price must respect.</Line>}
        {chain?.putWall && <Line testid="ca-sum-put-wall" tone="mint" tag={`PUT WALL ${fmtNum(chain.putWall.strike, 0)}`}>Most put OI at or below spot ({fmtLakh(chain.putWall.oi)}). Support as positioning.</Line>}
        {selRow && (
          <Line testid="ca-sum-strike" tone="amber" tag={`STRIKE ${fmtNum(selRow.strike, 0)}`}>
            Call OI {fmtLakh(selRow.call?.oi)} ({fmtLakh(selRow.call?.oiChange, true)}, {pctTxt(pctOf(selRow.call?.oiChange, selRow.call?.oi))}) · Put OI {fmtLakh(selRow.put?.oi)} ({fmtLakh(selRow.put?.oiChange, true)}, {pctTxt(pctOf(selRow.put?.oiChange, selRow.put?.oi))}) · PCR {fin(selRow.put?.oi) && fin(selRow.call?.oi) && selRow.call!.oi! > 0 ? (selRow.put!.oi! / selRow.call!.oi!).toFixed(2) : "—"}
          </Line>
        )}
      </div>

      {/* recommended strategies */}
      {!notFno && (
        <div style={{ marginTop: 18 }}>
          <RecoStrategies symbol={symbol} chain={chain && chain.tradable ? chain : null} direction={dir.dir} directionWhy={dir.why} compact={mobile} />
        </div>
      )}

      <div className="flex flex-wrap justify-between" style={{ marginTop: 12, gap: 8, fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.1em", color: "var(--cp-ink-4)" }}>
        <span data-testid="ca-footer">SNAPSHOT {istTime(new Date().toISOString())} IST{chain ? ` · CHAIN END OF DAY ${fmtDay(chain.asOf).toUpperCase()}` : ""} · {d.timeframe.source.toUpperCase()}</span>
        <span>EDUCATIONAL · PAPER ONLY</span>
      </div>
    </section>
  );

  const showBasket = basket.open || basket.legs.length > 0;
  return (
    <div ref={setBox} data-testid="ca-view" data-symbol={symbol} className="flex min-w-0 flex-col" style={{ gap: 16 }}>
      <div className="flex min-w-0" style={{ flexDirection: wide ? "row" : "column", gap: 16, alignItems: wide ? "flex-start" : "stretch" }}>
        <div className="min-w-0" style={{ flex: 1 }}>{card}</div>
        {showBasket && (
          <div className="min-w-0" style={{ width: wide ? 292 : "100%", flex: "none" }}>
            <BasketPanel symbol={symbol} chain={chain && chain.tradable ? chain : null} notFno={notFno} last={{ price: lastPrice, at: live ? quote.ts ?? d.last.at : d.last.at, source: live ? "Kite live price" : today?.source === "kite_close" ? `Kite close ${fmtDay(today.day)}, provisional` : `end of day ${fmtDay(d.last.at)}` }}
              planLevels={planLevels} planId={planId}
              onShowAnalysis={() => { const el = document.getElementById("ca-strategy-panel"); if (el) window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 16, behavior: "smooth" }); }}
              onClose={() => basket.setOpen(false)} compact={mobile} />
          </div>
        )}
      </div>
      {basket.legs.length > 0 && <StrategyPanel symbol={symbol} chain={chain && chain.tradable ? chain : null} refPrice={lastPrice} refAsOf={chain?.asOf ?? d.last.at.slice(0, 10)} compact={mobile} />}
    </div>
  );
}

function Line({ testid, tone, tag, children }: { testid: string; tone: string; tag: string; children: ReactNode }) {
  const c = tone === "danger" ? "var(--cp-danger)" : tone === "indigo" ? "var(--cp-indigo)" : tone === "ink" ? "var(--cp-ink-2)" : `var(--${tone})`;
  const soft = tone === "ink" ? "transparent" : `var(--${tone}-soft)`;
  const line = tone === "ink" ? "var(--line-3)" : `var(--${tone}-line)`;
  return (
    <div data-testid={testid} className="flex min-w-0 items-baseline" style={{ gap: 12, flexWrap: "wrap" }}>
      <span style={{ fontFamily: "var(--mono)", fontSize: 10, fontWeight: 500, letterSpacing: "0.12em", whiteSpace: "nowrap", color: c, border: `1px solid ${line}`, background: soft, borderRadius: 6, padding: "4px 8px" }}>{tag}</span>
      <span style={{ fontSize: 14, color: "var(--cp-ink-2)", minWidth: 0, flex: 1 }}>{children}</span>
    </div>
  );
}
