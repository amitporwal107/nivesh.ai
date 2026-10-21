/**
 * Smart trading desk — 03 Chart analysis, with the 05 AI Risk desk beside it
 * (design-spec §5), the phone's M4 composition (§11), and the opportunity
 * detail every stock opens (PRD §5.7: ten sections, summaries first, details on demand).
 *
 *   daily candles               GET /api/research/chart-live/{symbol}/ohlcv?start=   (useDailyBars; flag `charting`;
 *                               end of day, split and bonus adjusted: nidp.prices_eod_adjusted)
 *   indicators, overlay lines   GET /api/research/chart/live/{symbol}/indicators     (useLiveIndicators; the
 *                               stock_features_daily engine, calculator.py, on the same bars; lookbacks in the
 *                               response; Nifty 50 relative strength; price band from security_reference_daily)
 *   patterns, states, criteria  GET /api/research/chart/live/{symbol}/patterns       (useLivePatterns; research.charting)
 *   setup, levels, why          GET /api/positional/watchlist + /picks                (useDeskScanner, end of day)
 *   model, calibration          GET /api/move-odds/latest?head=p_up5_1d (useDeskOdds), GET /api/move-odds/stocks/{symbol}
 *   historical record           GET /api/positional/backtest/calibration?symbol=&horizon_days=10 (useSetupRecord)
 *   fundamentals, ownership     POST /api/copilot/widgets/company_financials           (useCompanyNumbers — a read:
 *                               nse_financials_quarterly, shareholding_pattern, stock_features_daily)
 *   filings, event markers      GET /api/filings/feed?symbol=&days=30&sort=latest     (useFilingsFeed)
 *   watchlist                   GET /api/watchlists, POST /api/watchlists/{id}/symbols (AddToList — the user's own list)
 *   full chart                  a link to Research → Charts with ?symbol=&entry=&stop=&t1= (drawing tools, layouts)
 *   risk desk                   RiskDesk.tsx (its own header lists its reads and writes)
 *
 * Shown as "—" with the reason, because nothing serves them: intraday intervals (no intraday bars), the F&O ban
 * and ASM / GSM lists (not ingested), market-regime and event criteria for a pattern (the engine has none), and
 * every validation figure the historical record does not hold (average and median return, costs, benchmark,
 * out-of-sample). The design's "Pattern confidence" is the scanner's own grade, labelled "Scanner confidence".
 */
import { Flash } from "../../components/LiveBits";
import { closeLabel, useLiveOverlay, flashOf } from "../../lib/useLiveQuotes";
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import {
  EmptyBlock, ErrorBlock, LoadingBlock, NotConnected, Pill, TONE_COLOR, fmtNum, fmtPct, humaniseTag, signTone, type Tone,
} from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { useCompanyNumbers, useFilingsFeed, type CompanyFeatures, type HoldingRow } from "../markets/hooks";
import { fmtDay, fmtPrice, fmtSigned } from "../trading/parts";
import { AddToList } from "../workspace/PersonalLists";
import { CandleChart, CandleLegend, PLAIN_CHART_WORDS, TRADER_CHART_WORDS, type ChartEvent } from "./CandleChart";
import {
  INTERVALS, INTRADAY_REASON, RECORD_HORIZON, STATE_LABEL, alignSeries, fullChartHref, scanDateLabel, setupLabel, useDailyBars, useIntradayAvailability, useIntradayBars,
  deskLevels, useDeskLevels, useLiveIndicators, useLivePatterns, useSetupRecord, useStockOdds,
  type DailyBars, type IndicatorValues, type LiveIndicators, type LivePattern, type LivePatterns, type LiveRead, type RecordRow, type SetupRecord,
} from "./chart-data";
import { useDesk } from "./context";
import { suggestionsFor, useDidYouMean } from "./symbol-lookup-data";
import { LIQUID_MIN_CR, PROBABILITY_WITHHELD, modelEvidence, probabilityGate, useDeskOdds, useDeskScanner, type DeskSetup } from "./desk-data";
import { largestGap, rsiZone, type DailyBar } from "./indicators";
import { CardHead, RISK_STATUS, RiskDesk, Segmented, TradeScenarioCard } from "./RiskDesk";
import { TrustLine } from "./trust";

type Timeframe = "1M" | "3M" | "6M";
const SESSIONS: Record<Timeframe, number> = { "1M": 22, "3M": 63, "6M": 126 };
const TIMEFRAMES = (Object.keys(SESSIONS) as Timeframe[]).map((t) => ({ value: t, label: t, id: t, title: `${SESSIONS[t]} daily candles` }));

/** Below this width the chart card and the risk desk stack instead of sitting 7 : 5 side by side. */
const SIDE_BY_SIDE_MIN = 640;
/** Below this width of the chart card the five indicator tiles wrap 3 + 2. */
const FIVE_TILES_MIN = 520;
/** Filings the event markers and section 5 read: the route's own ceiling is 30 days. */
const FILING_DAYS = 30;
/** Promoter pledge at or above this share of the promoter holding is listed as contradictory evidence. */
const PLEDGE_FLAG_PCT = 5;

interface Overlays { ema: boolean; vwap: boolean; levels: boolean }

/** Width of an observed box, or null until it is measured. */
function useBoxWidth(box: HTMLElement | null): number | null {
  const [w, setW] = useState<number | null>(null);
  useEffect(() => {
    if (!box || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const v = entries[0]?.contentRect.width;
      if (v) setW(v);
    });
    ro.observe(box);
    return () => ro.disconnect();
  }, [box]);
  return w;
}

const okData = <T,>(q: { data?: LiveRead<T> }): T | null => (q.data?.kind === "ok" ? q.data.data : null);

// ── controls ─────────────────────────────────────────────────────────────

/** Overlay chip (design-spec §1 filter chip, mono 9.5px). */
function OverlayChip({ on, onClick, disabled, title, testId, children }: { on: boolean; onClick: () => void; disabled?: boolean; title?: string; testId: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      disabled={disabled}
      title={title}
      data-testid={testId}
      onClick={onClick}
      style={{
        padding: "5px 11px", borderRadius: 999, fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase",
        cursor: disabled ? "not-allowed" : "pointer", opacity: disabled ? 0.45 : 1,
        border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`,
        color: on ? "var(--mint)" : "var(--cp-ink-2)",
        background: on ? "var(--mint-soft)" : "transparent",
      }}
    >
      {children}
    </button>
  );
}

/** Under the "no daily prices" state: stocks the symbol may have meant (the symbol lookup), each switching the chart. */
function DidYouMean({ symbol }: { symbol: string }) {
  const { setSymbol, persona } = useDesk();
  const q = useDidYouMean(symbol, true);
  if (q.isPending) return <span data-testid="desk-chart-dym-loading" className="cp-mono-note">Looking for a stock like {symbol}…</span>;
  if (q.isError) return null;                    // the lookup failed: the explanation above stands alone
  const sugg = suggestionsFor(q.data, symbol);
  if (sugg.length === 0) {
    return (
      <p data-testid="desk-chart-dym-none" role="status" className="m-0" style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>
        {q.data.results.length === 0 ? `No NSE stock matches ${symbol}. ` : ""}{persona === "investor" ? "Check the spelling, or search by company name." : "Check the ticker, or search by company name or ISIN in the box above."}
      </p>
    );
  }
  return (
    <div data-testid="desk-chart-dym" role="group" aria-label="Did you mean" className="flex flex-wrap items-center" style={{ gap: 8 }}>
      <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>Did you mean</span>
      {sugg.map((r) => (
        <button key={r.symbol} type="button" className="cp-chip" data-testid={`desk-chart-dym-${r.symbol}`} onClick={() => setSymbol(r.symbol)} style={{ minHeight: 40, display: "inline-flex", alignItems: "center", gap: 8 }}>
          <StockIcon symbol={r.symbol} name={r.name} size={20} />
          <span className="cp-num">{r.symbol}</span>{r.name ? <span style={{ color: "var(--cp-ink-3)" }}>({r.name})</span> : null}
        </button>
      ))}
      <span style={{ fontSize: 13, color: "var(--cp-ink-2)" }}>?</span>
    </div>
  );
}

function ChartControls({ tf, setTf, ov, setOv, hasLevels, small }: {
  tf: Timeframe; setTf: (t: Timeframe) => void; ov: Overlays; setOv: (o: Overlays) => void; hasLevels: boolean; small?: boolean;
}) {
  const chips = (
    <div role="group" aria-label="Overlays" className="flex flex-wrap" style={{ gap: 4 }}>
      <OverlayChip on={ov.ema} onClick={() => setOv({ ...ov, ema: !ov.ema })} testId="desk-chart-ov-ema" title="20- and 50-day EMA">EMA</OverlayChip>
      <OverlayChip on={ov.vwap} onClick={() => setOv({ ...ov, vwap: !ov.vwap })} testId="desk-chart-ov-vwap" title="20-day VWAP of daily prices">VWAP</OverlayChip>
      <OverlayChip
        on={ov.levels && hasLevels}
        disabled={!hasLevels}
        title={hasLevels ? "The scanner’s target, entry and stop" : "No scanner levels for this stock"}
        onClick={() => setOv({ ...ov, levels: !ov.levels })}
        testId="desk-chart-ov-levels"
      >
        Levels
      </OverlayChip>
    </div>
  );
  const seg = <Segmented label="Timeframe" value={tf} options={TIMEFRAMES} onChange={setTf} idPrefix="desk-chart-tf" small />;
  // The desk header puts the overlay chips first; the phone puts the timeframe first (design-spec §5, §11 M4).
  return small ? <>{seg}{chips}</> : <>{chips}{seg}</>;
}

/** Interval, the full chart and the watchlist (PRD §7.2): one row under the chart. */
function ChartToolbar({ symbol, company, setup, iv, setIv, enabledIntervals }: { symbol: string; company: string | null; setup: DeskSetup | null; iv: string; setIv: (v: string) => void; enabledIntervals: string[] }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const lv = useDeskLevels(symbol, setup);
  const href = fullChartHref(symbol, lv);
  return (
    <div data-testid="desk-chart-toolbar" className="flex flex-wrap items-center" style={{ gap: "8px 12px" }}>
      <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>{plain ? "Each candle" : "Interval"}</span>
      <Segmented
        label="Interval"
        value={iv}
        idPrefix="desk-chart-iv"
        small
        options={INTERVALS.map((o) => {
          const off = o.value !== "1D" && !enabledIntervals.includes(o.value);
          return { value: o.value, label: o.label, id: o.id, disabled: off, title: off ? INTRADAY_REASON : o.value === "1D" ? "One candle per trading day" : `Kite ${o.label} candles, raw prices, the live price in the latest candle` };
        })}
        onChange={(v) => setIv(String(v))}
      />
      <span id="desk-chart-iv-why" data-testid="desk-chart-iv-why" className="sr-only">{INTRADAY_REASON}</span>
      <a
        data-testid="desk-chart-full"
        href={href}
        aria-describedby="desk-chart-full-why"
        style={{ fontSize: 12, color: "var(--mint)", textDecoration: "none", marginLeft: "auto", whiteSpace: "nowrap" }}
      >
        {plain ? "Open the full chart ↗" : "Open full chart ↗"}
      </a>
      <span id="desk-chart-full-why" className="sr-only">
        Opens Research → Charts with {symbol}{setup?.entry != null ? " and the scanner’s levels" : ""}: drawing tools, saved layouts and pattern overlays.
      </span>
      <span data-testid="desk-chart-watch" className="flex min-w-0 items-center"><AddToList symbol={symbol} name={company ?? symbol} /></span>
    </div>
  );
}

// ── chart body (the candles, or why there are none) ──────────────────────

function eventMarkers(rows: Array<{ date?: string | null; docLabel?: string | null; category?: string | null }>): ChartEvent[] {
  const byDay = new Map<string, string[]>();
  for (const r of rows) {
    const day = (r.date ?? "").slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
    const what = [r.docLabel, r.category ? humaniseTag(r.category) : null].filter(Boolean).join(" · ") || "Exchange filing";
    byDay.set(day, [...(byDay.get(day) ?? []), what]);
  }
  return [...byDay.entries()].map(([day, items]) => ({
    day, count: items.length, title: `${fmtDay(day)}: ${items.length} ${items.length === 1 ? "filing" : "filings"} — ${items.join("; ")}`,
  }));
}

function ChartBody({ symbol, state, retry, setup, tf, ov, compact, live, events }: {
  symbol: string;
  state: { isPending: boolean; isError: boolean; error: unknown; data: DailyBars | undefined };
  retry: () => void;
  setup: DeskSetup | null;
  tf: Timeframe;
  ov: Overlays;
  compact?: boolean;
  live: LiveIndicators | null;
  events: ChartEvent[];
}) {
  const { persona } = useDesk();
  const words = persona === "investor" ? PLAIN_CHART_WORDS : TRADER_CHART_WORDS;
  const bars = state.data?.kind === "ok" ? state.data.bars : null;
  const hasLevels = !!setup && (setup.entry != null || setup.stop != null || setup.target != null);
  const n = bars ? Math.min(SESSIONS[tf], bars.length) : 0;
  const shown = useMemo(() => (bars ? bars.slice(bars.length - n) : null), [bars, n]);
  const lines = useMemo(() => {
    if (!shown || !live) return null;
    const s = live.series;
    return {
      ema20: alignSeries(s.days, s.ema20, shown),
      ema50: alignSeries(s.days, s.ema50, shown),
      ema200: alignSeries(s.days, s.ema200, shown),
      vwap20: alignSeries(s.days, s.vwap20, shown),
    };
  }, [shown, live]);

  if (state.isPending) return <LoadingBlock label={`Loading ${symbol} daily bars`} rows={5} />;
  if (state.isError) return <div data-testid="desk-chart-error"><ErrorBlock title={`${symbol} prices didn’t load`} error={state.error} onRetry={retry} /></div>;
  if (state.data?.kind === "locked") {
    return (
      <NotConnected
        testId="desk-chart-locked"
        title="Charting is not enabled for this account"
        body="Daily candles and the indicators worked out from them need the charting feature. The scanner levels and the risk desk still show."
        needs={["The `charting` feature allowlist for this account (GET /api/research/chart-live/{symbol}/ohlcv answers 403 without it)."]}
      />
    );
  }
  if (state.data?.kind === "none" || !bars || !shown) {
    return (
      <div data-testid="desk-chart-noprices" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
        <EmptyBlock title={`No daily prices on record for ${symbol}`} body="The data platform has no adjusted end-of-day bars for this symbol. Pick a stock from the AI scanner." />
        <DidYouMean symbol={symbol} />
      </div>
    );
  }
  const ok = state.data?.kind === "ok" ? state.data : null;
  const levelsOn = ov.levels && hasLevels;
  const inView = events.filter((e) => e.day >= shown[0].day && e.day <= shown[shown.length - 1].day);
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <CandleChart
        bars={shown}
        name={symbol}
        compact={compact}
        words={words}
        events={inView}
        overlays={{
          ema20: ov.ema && lines ? lines.ema20 : undefined,
          ema50: ov.ema && lines ? lines.ema50 : undefined,
          ema200: ov.ema && lines ? lines.ema200 : undefined,
          vwap20: ov.vwap && lines ? lines.vwap20 : undefined,
          levels: levelsOn && setup ? { target: setup.target, entry: setup.entry, stop: setup.stop } : null,
        }}
      />
      <CandleLegend ema={ov.ema && !!lines} ema200={ov.ema && !!lines && lines.ema200.some((v) => v != null)} vwap={ov.vwap && !!lines} levels={levelsOn} events={inView.length} words={words} span={tf} />
      <span data-testid="desk-chart-source" className="cp-mono-note" style={{ lineHeight: 1.6, fontSize: 9.5 }}>
        NSE daily bars, split and bonus adjusted{ok?.provider ? ` (${ok.provider})` : ""} · end of day · last session {fmtDay(bars[bars.length - 1].day)}
        {n < SESSIONS[tf] ? ` · only ${n} sessions on record, all shown` : ""}
        {ok?.partial ? " · the data platform dropped some incomplete sessions from this series" : ""}
        {live?.adjustment_break
          ? ` · the price series jumps ${fmtPrice(live.adjustment_break.prev_close)} to ${fmtPrice(live.adjustment_break.close)} on ${fmtDay(live.adjustment_break.date)}, a split or bonus the data platform has not adjusted: indicators use only the ${live.sessions} sessions from that day`
          : ""}
        {live?.series_notes?.ema200 && ov.ema ? ` · no EMA 200 line: ${live.series_notes.ema200}` : ""}
        {live
          ? " · lines and indicators from the server’s feature engine on these bars; VWAP 20D is a 20-day volume-weighted average of daily prices, not the intraday VWAP"
          : " · no indicator lines: the indicator route did not answer"}
        {inView.length ? ` · ◆ ${inView.length} ${inView.length === 1 ? "session" : "sessions"} with an exchange filing in the last ${FILING_DAYS} days` : ""}
      </span>
    </div>
  );
}

/** Intraday candles (Kite, platform session). Shown only for an interval the availability route lists; never fabricates a bar. */
function IntradayBody({ symbol, interval, setup, ov, compact }: { symbol: string; interval: string; setup: DeskSetup | null; ov: Overlays; compact?: boolean }) {
  const { persona } = useDesk();
  const words = persona === "investor" ? PLAIN_CHART_WORDS : TRADER_CHART_WORDS;
  const q = useIntradayBars(symbol, interval, true, 30_000);
  if (q.isPending) return <LoadingBlock label={`Loading ${symbol} ${interval} candles`} rows={5} />;
  if (q.isError) return <div data-testid="desk-chart-error"><ErrorBlock title={`${symbol} ${interval} candles didn’t load`} error={q.error} onRetry={() => q.refetch()} /></div>;
  const d = q.data;
  if (!d.bars.length) {
    return (
      <div data-testid="desk-chart-intraday-empty">
        <EmptyBlock title={`No ${interval} candles for ${symbol}`} body={d.availability === "token_missing" || d.availability === "token_expired" ? "The platform Kite session is not connected, so there are no intraday candles. Daily bars still work." : d.availability === "symbol_not_found" ? "Kite does not list this symbol." : "Kite returned no intraday candles for the recent sessions."} />
      </div>
    );
  }
  const hasLevels = !!setup && (setup.entry != null || setup.stop != null || setup.target != null);
  const levelsOn = ov.levels && hasLevels;
  return (
    <div data-testid="desk-chart-intraday" data-interval={interval} className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <CandleChart
        bars={d.bars}
        name={`${symbol} ${interval}`}
        compact={compact}
        words={words}
        intraday
        overlays={{ levels: levelsOn && setup ? { target: setup.target, entry: setup.entry, stop: setup.stop } : null }}
      />
      <span data-testid="desk-chart-source" className="cp-mono-note" style={{ lineHeight: 1.6, fontSize: 9.5 }}>
        {d.source} · {interval} candles · raw prices, not split or bonus adjusted · {d.sessions.length} {d.sessions.length === 1 ? "session" : "sessions"} · as of {d.asOf.slice(11, 16)} UTC
        {d.liveMerged ? " · the live price is in the latest candle" : ""} · no indicator lines on intraday candles
      </span>
    </div>
  );
}

// ── head row ─────────────────────────────────────────────────────────────

function priceMove(bars: DailyBar[] | null, setup: DeskSetup | null) {
  const last = bars?.length ? bars[bars.length - 1] : null;
  const prev = bars && bars.length > 1 ? bars[bars.length - 2] : null;
  const close = last?.close ?? setup?.close ?? null;
  const change = last && prev ? last.close - prev.close : null;
  const changePct = last && prev && prev.close > 0 ? ((last.close - prev.close) / prev.close) * 100 : null;
  const asOf = last ? `${fmtDay(last.day)} close · end of day` : setup?.close != null ? "Scanner close · end of day" : "";
  return { close, change, changePct, asOf };
}

function patternPills(setup: DeskSetup | null, plain: boolean): ReactNode {
  if (!setup) return <Pill>Not on today’s scanner</Pill>;
  const vol = setup.signals.volume_spike_3v20 ?? null;
  return (
    <>
      <Pill tone="mint">{setupLabel(setup, plain)}</Pill>
      {vol != null && <Pill tone={vol >= 1.5 ? "mint" : "ink"} title="Last 3 sessions’ volume ÷ the 20-day average (scanner)">{plain ? "Activity" : "Volume"} {fmtNum(vol, 1)}×</Pill>}
      {setup.stage && <Pill tone="indigo">Stage · {humaniseTag(setup.stage.toLowerCase())}</Pill>}
    </>
  );
}

function HeadRow({ symbol, setup, bars, company }: { symbol: string; setup: DeskSetup | null; bars: DailyBar[] | null; company: string | null }) {
  const { persona } = useDesk();
  const eod = priceMove(bars, setup);
  const lastDay = bars?.length ? bars[bars.length - 1].day.slice(0, 10) : null;
  const live = useLiveOverlay(symbol, lastDay);                    // Kite: the live price, or today's close after the session until the end-of-day bar lands
  const m = live
    ? { close: live.ltp, change: live.change, changePct: live.changePct, asOf: live.kind === "close" ? closeLabel(live) : `Live · Kite${live.ts ? ` · ${live.ts.slice(11, 19)} IST` : ""}` }
    : eod;
  return (
    <div data-testid="desk-chart-header" data-live={live ? live.kind : undefined} className="flex flex-wrap items-start justify-between" style={{ gap: "10px 16px", padding: "16px 18px 4px" }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="flex min-w-0 items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-3)" }}>
          <StockIcon symbol={symbol} name={company} size={20} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <span data-testid="desk-chart-symbol" style={{ color: "var(--cp-ink-2)", fontWeight: 500 }}>{symbol}</span>
            {company ? ` · ${company}` : ""}
          </span>
        </span>
        <span className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
          <span data-testid="desk-chart-close" style={{ fontFamily: "var(--display)", fontSize: 34, lineHeight: 1, letterSpacing: "-0.02em" }}><Flash value={flashOf(live)}>{fmtPrice(m.close)}</Flash></span>
          <span data-testid="desk-chart-change" className="cp-num" style={{ fontSize: 12, color: TONE_COLOR[signTone(m.change)] }}>
            {m.change != null ? `${fmtSigned(m.change)} (${fmtPct(m.changePct, { signed: true, digits: 2 })})` : "—"}
          </span>
          {m.asOf && <span className="cp-mono-note" style={{ fontSize: 9 }}>{m.asOf}</span>}
        </span>
      </div>
      <div data-testid="desk-chart-pills" className="flex flex-wrap justify-end" style={{ gap: 6 }}>{patternPills(setup, persona === "investor")}</div>
    </div>
  );
}

// ── indicator tiles and the indicator drawer ─────────────────────────────

function where(close: number | null, v: number | null, plain: boolean): { text: string; tone: Tone } {
  if (close == null || v == null) return { text: "—", tone: "ink" };
  if (close > v) return { text: plain ? "Price above it" : "Price above", tone: "mint" };
  if (close < v) return { text: plain ? "Price below it" : "Price below", tone: "danger" };
  return { text: "Price at", tone: "ink" };
}

const RSI_PLAIN: Record<string, string> = { Overbought: "Stretched", Healthy: "Strong", Neutral: "Neutral" };

interface Tile { id: string; k: string; v: string; s: string; tone: Tone; title: string }

function tileOf(id: string, v: IndicatorValues, defs: Map<string, string>, plain: boolean): Tile | null {
  const zone = rsiZone(v.rsi14);
  const t = (k: string, val: string, s: string, tone: Tone = "ink"): Tile => ({ id, k, v: val, s, tone, title: defs.get(id) ?? "" });
  switch (id) {
    case "ema20": { const e = where(v.close, v.ema20, plain); return t(plain ? "Trend" : "EMA 20", fmtPrice(v.ema20), e.text, e.tone); }
    case "rsi": return { ...t(plain ? "Momentum" : "RSI 14", fmtNum(v.rsi14, 1), zone ? (plain ? RSI_PLAIN[zone] : zone) : "—", zone === "Overbought" ? "amber" : zone === "Healthy" ? "mint" : "ink"), title: defs.get("rsi14") ?? "" };
    case "atr": return { ...t(plain ? "Daily swing" : "ATR 14", fmtPrice(v.atr14), v.atr_pct != null ? `${fmtPct(v.atr_pct, { digits: 2 })} of price` : "—"), title: defs.get("atr14") ?? "" };
    case "vwap": { const e = where(v.close, v.vwap20, plain); return { ...t(plain ? "Month’s avg" : "VWAP 20D", fmtPrice(v.vwap20), e.text, e.tone), title: defs.get("vwap20") ?? "" }; }
    case "rvol": {
      const exp = v.rvol20 != null && v.rvol20 >= 1.5;
      return {
        ...t(plain ? "Activity" : "RVOL", v.rvol20 != null ? `${fmtNum(v.rvol20, 2)}×` : "—",
          v.rvol20 == null ? "—" : exp ? (plain ? "Busier than usual" : "Volume expansion") : (plain ? "Usual activity" : "No volume expansion"), exp ? "mint" : "ink"),
        title: defs.get("rvol20") ?? "",
      };
    }
    case "ema50": { const e = where(v.close, v.ema50, plain); return t(plain ? "50-day avg" : "EMA 50", fmtPrice(v.ema50), e.text, e.tone); }
    case "ema200": { const e = where(v.close, v.ema200, plain); return t(plain ? "200-day avg" : "EMA 200", fmtPrice(v.ema200), v.ema200 == null ? "Needs 200 sessions" : e.text, e.tone); }
    case "macd": return t("MACD 12 / 26 / 9", fmtNum(v.macd_hist, 2), v.macd != null && v.macd_signal != null ? `MACD ${fmtNum(v.macd, 2)} · signal ${fmtNum(v.macd_signal, 2)}` : "Needs 35 sessions", signTone(v.macd_hist));
    case "roc20": return t(plain ? "Change · 20 days" : "ROC 20", fmtPct(v.roc20, { signed: true, digits: 1 }), "vs the close 20 sessions ago", signTone(v.roc20));
    case "rs63": return t(plain ? "vs Nifty 50" : "RS vs Nifty 50", v.rs63 ? `${v.rs63.excess_pct > 0 ? "+" : v.rs63.excess_pct < 0 ? "−" : ""}${fmtNum(Math.abs(v.rs63.excess_pct), 1)} pts` : "—",
      v.rs63 ? `Stock ${fmtPct(v.rs63.stock_return_pct, { signed: true, digits: 1 })} · index ${fmtPct(v.rs63.benchmark_return_pct, { signed: true, digits: 1 })}` : "Needs Nifty 50 closes", v.rs63 ? signTone(v.rs63.excess_pct) : "ink");
    case "avg_volume20": return t(plain ? "Usual volume" : "Volume MA 20", v.avg_volume20 != null ? fmtNum(v.avg_volume20) : "—", "shares a day, before the last session");
    case "sr20": return t(plain ? "Recent range" : "Support / resistance", v.support20 != null && v.resistance20 != null ? `${fmtPrice(v.support20)} – ${fmtPrice(v.resistance20)}` : "—", "20-session low – high");
    default: return null;
  }
}

/** The design's five tiles (design-spec §5). */
const DEFAULT_TILES = ["ema20", "rsi", "atr", "vwap", "rvol"];
/** PRD §7.3's other indicators: in the drawer, off by default (§16.2 — never every indicator at once). */
const EXTRA_TILES: Array<{ id: string; defKey: string; label: string }> = [
  { id: "ema50", defKey: "ema50", label: "EMA 50" },
  { id: "ema200", defKey: "ema200", label: "EMA 200" },
  { id: "macd", defKey: "macd", label: "MACD" },
  { id: "roc20", defKey: "roc20", label: "Rate of change" },
  { id: "rs63", defKey: "rs63", label: "Relative strength vs Nifty 50" },
  { id: "avg_volume20", defKey: "avg_volume20", label: "Volume MA" },
  { id: "sr20", defKey: "resistance20", label: "Support / resistance" },
];

function IndicatorTiles({ live, five, extra }: { live: LiveIndicators; five: boolean; extra: string[] }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const defs = new Map(live.definitions.map((d) => [d.key, `${d.label} · ${d.lookback}: ${d.formula}`]));
  const tiles = [...DEFAULT_TILES, ...extra].map((id) => tileOf(id, live.values, defs, plain)).filter((x): x is Tile => !!x);
  const cols = five ? 5 : 3;
  return (
    <div data-testid="desk-indicators" data-cols={cols} className="grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, borderTop: "1px solid var(--cp-line)" }}>
      {tiles.map((t, i) => (
        <div
          key={t.id}
          title={t.title}
          data-testid={`desk-ind-tile-${t.id}`}
          className="flex min-w-0 flex-col"
          style={{
            gap: 4, padding: "12px 14px",
            borderRight: (i + 1) % cols !== 0 && i !== tiles.length - 1 ? "1px solid var(--cp-line)" : undefined,
            borderTop: i >= cols ? "1px solid var(--cp-line)" : undefined,
          }}
        >
          <span className="cp-eyebrow" style={{ fontSize: 9.5, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{t.k}</span>
          <span data-testid={`desk-ind-${t.id}`} style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.1, letterSpacing: "-0.02em", fontVariantNumeric: "tabular-nums" }}>{t.v}</span>
          <span data-testid={`desk-ind-${t.id}-sub`} style={{ fontSize: 11.5, color: t.tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[t.tone] }}>{t.s}</span>
        </div>
      ))}
    </div>
  );
}

/** Disclosure button (PRD §1.4.6 progressive disclosure): aria-expanded, and the panel it controls. */
function DisclosureButton({ open, onClick, controls, testId, children }: { open: boolean; onClick: () => void; controls: string; testId: string; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-expanded={open}
      aria-controls={controls}
      data-testid={testId}
      onClick={onClick}
      style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)", textAlign: "left" }}
    >
      {children} {open ? "▴" : "▾"}
    </button>
  );
}

function IndicatorDrawer({ live, extra, setExtra }: { live: LiveIndicators; extra: string[]; setExtra: (x: string[]) => void }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const defs = new Map(live.definitions.map((d) => [d.key, d]));
  const toggle = (id: string) => setExtra(extra.includes(id) ? extra.filter((x) => x !== id) : [...extra, id]);
  return (
    <div data-testid="desk-ind-drawer" className="flex flex-col" style={{ gap: 10, padding: "10px 18px 12px", borderTop: "1px solid var(--cp-line)" }}>
      <DisclosureButton open={open} onClick={() => setOpen(!open)} controls={panel} testId="desk-ind-drawer-toggle">
        More indicators and how each is worked out
      </DisclosureButton>
      {open && (
        <div id={panel} className="flex flex-col" style={{ gap: 10 }}>
          <div role="group" aria-label="Show an indicator as a tile" className="flex flex-wrap" style={{ gap: 6 }}>
            {EXTRA_TILES.map((x) => (
              <OverlayChip key={x.id} on={extra.includes(x.id)} onClick={() => toggle(x.id)} testId={`desk-ind-toggle-${x.id}`} title={defs.get(x.defKey)?.formula}>
                {x.label}
              </OverlayChip>
            ))}
          </div>
          <ul data-testid="desk-ind-defs" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none", gap: 6 }}>
            {live.definitions.map((d) => (
              <li key={d.key} data-testid={`desk-ind-def-${d.key}`} style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
                <span style={{ color: "var(--cp-ink)", fontWeight: 500 }}>{d.label}</span>
                <span className="cp-mono-note" style={{ fontSize: 9.5 }}> · lookback {d.lookback}</span>
                <span style={{ color: "var(--cp-ink-3)" }}> — {d.formula}</span>
              </li>
            ))}
          </ul>
          <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>
            {live.method ?? "Server feature engine"} · {live.sessions} sessions to {fmtDay(live.as_of)} · end of day
          </span>
        </div>
      )}
    </div>
  );
}

// ── setup check ──────────────────────────────────────────────────────────

interface CheckLine { key: string; label: string; value: string; tone: Tone }

/** The setup's structure, most telling first; the design shows seven rows. */
function setupLines(s: DeskSetup, plain: boolean): CheckLine[] {
  const sig = s.signals;
  const out: CheckLine[] = [];
  const add = (key: string, trader: string, simple: string, value: string, tone: Tone = "ink") => out.push({ key, label: plain ? simple : trader, value, tone });
  // The watchlist's own levels around the close; each says how far the scan-day close is from it.
  const fromClose = (level: number) => (s.close != null && s.close > 0 ? ` · ${fmtPct(((level - s.close) / s.close) * 100, { signed: true, digits: 1 })}` : "");
  if (s.trigger != null) {
    const d = sig.dist_breakout_pct;
    add("trigger", "Breakout level", "Price to beat", `${fmtPrice(s.trigger)}${d != null ? ` · ${fmtPct(d, { signed: true, digits: 1 })}` : ""}`, d != null && d >= 0 ? "mint" : "ink");
  }
  if (sig.volume_spike_3v20 != null) add("volume", "Volume vs 20-day avg", "Activity vs usual", `${fmtNum(sig.volume_spike_3v20, 1)}×`, sig.volume_spike_3v20 >= 1.5 ? "mint" : "ink");
  if (s.rsi14 != null) add("rsi", "RSI 14", "Momentum score", fmtNum(s.rsi14, 1), s.rsi14 >= 70 ? "amber" : s.rsi14 >= 55 ? "mint" : "ink");
  if (sig.dist_ema20_pct != null) add("ema20", "Distance to EMA 20", "Gap to 20-day avg", fmtPct(sig.dist_ema20_pct, { signed: true, digits: 1 }), sig.dist_ema20_pct >= 0 && sig.dist_ema20_pct <= 4 ? "mint" : "ink");
  if (s.resistance != null) add("resistance", "Next resistance", "Next ceiling", `${fmtPrice(s.resistance)}${fromClose(s.resistance)}`);
  if (s.support != null) add("support", "Next support", "Next floor", `${fmtPrice(s.support)}${fromClose(s.support)}`);
  if (sig.higher_lows_count != null) add("higher-lows", "Higher lows · 20 sessions", "Rising dips · 20 days", fmtNum(sig.higher_lows_count), sig.higher_lows_count >= 1 ? "mint" : "ink");
  if (sig.range_pct_15d != null) add("range", "15-day range", "Sideways range · 15 days", fmtPct(sig.range_pct_15d, { digits: 1 }), sig.range_pct_15d < 8 ? "mint" : "ink");
  if (s.atrPct != null) add("atr", "ATR 14 · % of close", "Daily swing", fmtPct(s.atrPct, { digits: 2 }));
  if (sig.volume_slope_10d_pct != null) add("vol-slope", "Volume trend · 10 sessions", "Activity trend · 10 days", `${fmtPct(sig.volume_slope_10d_pct, { signed: true, digits: 1 })} a day`);
  if (sig.delivery_trend_pct != null) add("delivery", "Delivery trend · 10 sessions", "Shares kept · 10 days", fmtPct(sig.delivery_trend_pct, { signed: true, digits: 0 }));
  if (s.daysMin != null || s.daysMax != null) add("window", "Holding window", "Holding time", `${s.daysMin != null ? fmtNum(s.daysMin) : "—"}–${s.daysMax != null ? fmtNum(s.daysMax) : "—"} days`);
  return out.slice(0, 7);
}

function SetupRows({ setup }: { setup: DeskSetup }) {
  const { persona } = useDesk();
  const lines = setupLines(setup, persona === "investor");
  if (!lines.length) return <span style={{ fontSize: 13, color: "var(--cp-ink-3)" }}>The scanner sent no structure figures for this setup.</span>;
  return (
    <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
      {lines.map((l, i) => (
        <li key={l.key} data-testid={`desk-check-${l.key}`} className="flex items-center" style={{ gap: 10, padding: "7px 0", borderTop: i ? "1px solid var(--cp-line)" : undefined, fontSize: 12.5 }}>
          <span aria-hidden style={{ flex: "none", width: 6, height: 6, borderRadius: 999, background: l.tone === "ink" ? "var(--cp-ink-4)" : TONE_COLOR[l.tone] }} />
          <span style={{ flex: "1 1 auto", minWidth: 0, color: "var(--cp-ink-2)" }}>{l.label}</span>
          <span className="cp-num" style={{ flex: "none", fontSize: 11.5, color: "var(--cp-ink)", textAlign: "right" }}>{l.value}</span>
        </li>
      ))}
    </ul>
  );
}

function SetupCheck({ setup, date }: { setup: DeskSetup; date: string | null }) {
  const { persona } = useDesk();
  return (
    <div data-testid="desk-setup-check" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
        <span className="cp-eyebrow">{persona === "investor" ? "What the chart shows" : "Setup check"}</span>
        <span className="cp-mono-note" style={{ fontSize: 9 }}>Scanner · {date ?? "end of day"}</span>
      </div>
      <SetupRows setup={setup} />
    </div>
  );
}

// ── why it ranks ─────────────────────────────────────────────────────────

interface WhyRow { key: "trend" | "momentum" | "catalyst" | "risk"; label: string; tone: Tone; text: ReactNode }

/** The latest event the model has on record for the stock, from GET /api/move-odds/stocks/{symbol}. */
function useCatalyst(symbol: string) {
  const odds = useDeskOdds("p_up5_1d");
  const stock = useStockOdds(symbol);
  const fromLatest = odds.data?.kind === "final" ? odds.data.bySymbol.get(symbol.toUpperCase())?.events ?? null : null;
  const data = stock.data?.kind === "ok" ? stock.data.data : null;
  const events = fromLatest ?? (data ? data.events.length : null);
  const latest = data?.events.length ? [...data.events].sort((a, b) => b.event_time.localeCompare(a.event_time))[0] : null;
  const unavailable = odds.data?.kind === "no_access" || stock.data?.kind === "locked";
  return { events, latest, unavailable };
}

/** The indicator figures the why rows read, from the server; null when the route did not answer. */
interface Snap { close: number | null; ema20: number | null; ema50: number | null; rsi14: number | null; atrPct: number | null }

const snapOf = (v: IndicatorValues | null): Snap | null => (v ? { close: v.close, ema20: v.ema20, ema50: v.ema50, rsi14: v.rsi14, atrPct: v.atr_pct } : null);

function whyRows(setup: DeskSetup, snap: Snap | null, cat: ReturnType<typeof useCatalyst>, plain: boolean): WhyRow[] {
  const close = snap?.close ?? setup.close;
  const e20 = snap?.ema20 ?? setup.ema20;
  const e50 = snap?.ema50 ?? null;
  const rows: WhyRow[] = [];

  // Trend: the close against the 20-day EMA, and the 20-day against the 50-day.
  if (close != null && e20 != null) {
    const above = close > e20;
    const stacked = e50 != null ? e20 > e50 : null;
    rows.push({
      key: "trend", label: "Trend", tone: above && stacked !== false ? "mint" : !above && stacked === false ? "danger" : "amber",
      text: plain
        ? <>The price ({fmtPrice(close)}) is {above ? "above" : "below"} its 20-day average ({fmtPrice(e20)}){e50 != null ? <>, which is {stacked ? "above" : "below"} the 50-day average ({fmtPrice(e50)})</> : null}.</>
        : <>Close {fmtPrice(close)} is {above ? "above" : "below"} the 20-day EMA {fmtPrice(e20)}{e50 != null ? <>; EMA 20 is {stacked ? "above" : "below"} EMA 50 {fmtPrice(e50)}</> : null}.</>,
    });
  } else {
    rows.push({ key: "trend", label: "Trend", tone: "ink", text: "— No moving averages for this stock." });
  }

  // Momentum: RSI and the volume the scanner measured.
  const rsi = snap?.rsi14 ?? setup.rsi14;
  const vol = setup.signals.volume_spike_3v20 ?? null;
  const zone = rsiZone(rsi);
  rows.push({
    key: "momentum", label: plain ? "Strength" : "Momentum", tone: zone === "Healthy" ? "mint" : zone === "Overbought" ? "amber" : "ink",
    text: rsi == null && vol == null ? "— No RSI or volume figure." : plain
      ? <>{rsi != null ? <>Momentum score {fmtNum(rsi, 1)} ({(zone && RSI_PLAIN[zone])?.toLowerCase()})</> : null}{rsi != null && vol != null ? "; " : null}{vol != null ? <>trading {fmtNum(vol, 1)}× the usual amount over 3 days</> : null}.</>
      : <>{rsi != null ? <>RSI 14 at {fmtNum(rsi, 1)} ({zone?.toLowerCase()})</> : null}{rsi != null && vol != null ? "; " : null}{vol != null ? <>volume {fmtNum(vol, 1)}× the 20-day average over 3 sessions</> : null}.</>,
  });

  // Catalyst: filings and news the move-odds model has on record for the stock.
  rows.push({
    key: "catalyst", label: plain ? "News" : "Catalyst", tone: "indigo",
    text: cat.unavailable ? "— Events on record are not enabled for this account."
      : cat.events == null ? "— The move-odds model has no run for this stock, so no events are on record here."
        : cat.events === 0 ? (plain ? "No company news or filings on record." : "No filing or news event on record in the model’s run.")
          : <>{fmtNum(cat.events)} {cat.events === 1 ? "event" : "events"} on record{cat.latest?.title ? <>; latest: {cat.latest.title} ({cat.latest.source_label}, {fmtDay(cat.latest.event_time.slice(0, 10))})</> : null}.</>,
  });

  // Risk: how far the stop is, against a day's typical swing.
  const entry = setup.entry;
  const stop = setup.stop;
  const atrPct = snap?.atrPct ?? setup.atrPct;
  if (entry != null && stop != null && entry > stop) {
    const dist = ((entry - stop) / entry) * 100;
    rows.push({
      key: "risk", label: plain ? "Watch" : "Risk", tone: "danger",
      text: plain
        ? <>Exit if it falls to {fmtPrice(stop)}, {fmtPct(dist, { digits: 1 })} below the buy level{atrPct != null ? <>; it typically moves {fmtPct(atrPct, { digits: 1 })} a day</> : null}.</>
        : <>Stop {fmtPrice(stop)} is {fmtPct(dist, { digits: 1 })} below the entry{atrPct != null ? <>, about {fmtNum(dist / atrPct, 1)} × ATR ({fmtPct(atrPct, { digits: 1 })})</> : null}.</>,
    });
  } else {
    rows.push({ key: "risk", label: plain ? "Watch" : "Risk", tone: "ink", text: "— No entry with a stop below it on this setup." });
  }
  return rows;
}

function WhyItRanks({ setup, snap }: { setup: DeskSetup; snap: Snap | null }) {
  const { askDesk, persona } = useDesk();
  const plain = persona === "investor";
  const cat = useCatalyst(setup.symbol);
  const summary = [setup.why, ...setup.reasons].filter((x): x is string => !!x);
  return (
    <div data-testid="desk-why" className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <div className="flex flex-wrap items-baseline justify-between" style={{ gap: "4px 10px" }}>
        <span className="cp-eyebrow">{plain ? "Why it shows up" : "Why it ranks"}</span>
        <button
          type="button"
          data-testid="desk-why-ask"
          onClick={() => askDesk(`Explain the ${setup.symbol} setup and what would invalidate it`)}
          style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}
        >
          Ask Copilot ›
        </button>
      </div>
      <p data-testid="desk-why-summary" className="m-0" style={{ fontSize: 13, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        {summary.length ? summary.join(" · ") : "The scanner stored no reason text for this setup."}{" "}
        <span className="cp-mono-note" style={{ fontSize: 9 }}>Score {setup.score != null ? fmtNum(setup.score, 0) : "—"} · rules-based</span>
      </p>
      <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
        {whyRows(setup, snap, cat, plain).map((r, i) => (
          <li key={r.key} data-testid={`desk-why-${r.key}`} className="flex items-start" style={{ gap: 10, padding: "7px 0", borderTop: i ? "1px solid var(--cp-line)" : undefined }}>
            <span className="cp-eyebrow" style={{ flex: "none", width: 72, fontSize: 9.5, paddingTop: 2, color: r.tone === "ink" ? "var(--cp-ink-3)" : TONE_COLOR[r.tone] }}>{r.label}</span>
            <span style={{ flex: "1 1 auto", minWidth: 0, fontSize: 12.5, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>{r.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── historical performance (the design's four tiles) ─────────────────────

/** The record row the tiles quote: the breakout outcome, in the stock's score bucket, at the desk's horizon. */
function headlineRow(rec: SetupRecord | undefined): RecordRow | null {
  return rec?.buckets.find((r) => r.matched && r.metric === "broke_high" && r.horizon_days === RECORD_HORIZON) ?? null;
}

function recordGap(rec: SetupRecord | undefined, isError: boolean): string {
  if (isError) return "The historical record didn’t load";
  if (!rec) return "Loading the historical record";
  if (!rec.buckets.length) return "No historical record is on file yet";
  if (!rec.symbol_score) return "No accumulation score for this stock, so no bucket to quote";
  return "No record for this stock’s score bucket";
}

function historyTiles(setup: DeskSetup | null, rec: SetupRecord | undefined, recError: boolean, plain: boolean) {
  const rr = setup?.riskReward ?? null;
  const row = headlineRow(rec);
  const gap = recordGap(rec, recError);
  return [
    {
      id: "hit", k: plain ? "Worked before" : "Hit rate",
      v: row?.probability != null ? `${fmtPct(row.probability * 100, { digits: 0 })} · n ${fmtNum(row.sample_count)}` : "—",
      s: row ? `Broke its 20-session high within ${RECORD_HORIZON} sessions (intraday touch)` : gap,
    },
    {
      id: "move", k: plain ? "Typical rise" : "Average move",
      v: row?.avg_fwd_return != null ? fmtPct(row.avg_fwd_return, { signed: true, digits: 1 }) : "—",
      s: row ? `Mean best move within ${RECORD_HORIZON} sessions (MFE) — not an average return` : gap,
    },
    { id: "rr", k: plain ? "Reward for risk" : "Reward : risk", v: rr != null ? `${fmtNum(rr, 1)} : 1` : "—", s: rr != null ? "From the scanner’s levels" : "Needs a target and a stop" },
    {
      id: "conf", k: plain ? "Scanner’s confidence" : "Scanner confidence", v: setup?.confidence ? humaniseTag(setup.confidence.toLowerCase()) : "—",
      s: setup?.confidence ? "The scanner’s own grade" : "No grade for this stock",
    },
  ];
}

function HistoryTiles({ setup, count, phone }: { setup: DeskSetup | null; count: 3 | 4; phone?: boolean }) {
  const { persona } = useDesk();
  const recQ = useSetupRecord(setup?.symbol ?? null);
  const tiles = historyTiles(setup, recQ.data, recQ.isError, persona === "investor").slice(0, count);
  return (
    <div data-testid="desk-history" className="grid" style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))`, background: phone ? undefined : "var(--bg-0)", borderTop: phone ? undefined : "1px solid var(--cp-line)" }}>
      {tiles.map((t, i) => (
        <div key={t.id} className="flex min-w-0 flex-col" style={{ gap: 4, padding: phone ? "4px 8px" : "12px 14px", borderRight: i < tiles.length - 1 ? "1px solid var(--cp-line)" : undefined }}>
          <span className="cp-eyebrow" style={{ fontSize: phone ? 8.5 : 9.5, lineHeight: 1.35 }}>{t.k}</span>
          <span data-testid={`desk-hist-${t.id}`} style={{ fontFamily: "var(--display)", fontSize: phone ? 22 : 24, lineHeight: 1.05, color: t.v === "—" ? "var(--cp-ink-3)" : "var(--cp-ink)" }}>{t.v}</span>
          <span data-testid={`desk-hist-${t.id}-note`} style={{ fontSize: phone ? 10.5 : 11, lineHeight: 1.4, color: "var(--cp-ink-3)" }}>{t.s}</span>
        </div>
      ))}
    </div>
  );
}

function NotOnScanner({ symbol, scanError, date }: { symbol: string; scanError: boolean; date: string | null }) {
  return (
    <div data-testid="desk-not-on-scanner" className="flex flex-col" style={{ gap: 4 }}>
      <span style={{ fontFamily: "var(--display)", fontSize: 20, lineHeight: 1.2 }}>Not on today’s scanner — no levels</span>
      <span style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
        {scanError
          ? `The scanner didn’t load, so there is no trigger, stop or target for ${symbol}. The chart and indicators still show from its daily bars.`
          : `${symbol} did not pass the end-of-day scanner’s rules${date ? ` on the ${date} scan` : ""}, so it has no trigger, stop or target. The chart and indicators still show from its daily bars.`}
      </span>
    </div>
  );
}

// ── the opportunity detail (PRD §5.7) ────────────────────────────────────

const dash = <span style={{ color: "var(--cp-ink-3)" }}>—</span>;

/** One "label · value" line; `why` explains a dash. */
function KV({ k, v, why, testId }: { k: ReactNode; v: ReactNode; why?: ReactNode; testId?: string }) {
  return (
    <div data-testid={testId} className="flex flex-wrap items-baseline" style={{ gap: "2px 12px", padding: "6px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
      <span style={{ flex: "1 1 160px", minWidth: 0, color: "var(--cp-ink-2)" }}>{k}</span>
      <span className="cp-num" style={{ flex: "0 1 auto", color: "var(--cp-ink)", textAlign: "right", overflowWrap: "anywhere" }}>{v}</span>
      {why && <span style={{ flexBasis: "100%", fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{why}</span>}
    </div>
  );
}

const STATUS_MARK: Record<string, { mark: string; word: string; tone: Tone | "na" }> = {
  pass: { mark: "✓", word: "Passed", tone: "mint" },
  fail: { mark: "✕", word: "Failed", tone: "danger" },
  pending: { mark: "…", word: "Pending", tone: "amber" },
  na: { mark: "–", word: "Not judged", tone: "na" },
};

function PatternCard({ p, plain }: { p: LivePattern; plain: boolean }) {
  const st = p.state ? STATE_LABEL[p.state] : null;
  return (
    <li data-testid={`desk-pattern-${p.pattern_id}`} data-state={p.state ?? "none"} className="flex flex-col" style={{ gap: 8, padding: "10px 12px", borderRadius: 10, border: "1px solid var(--cp-line)", background: "var(--bg-0)" }}>
      <div className="flex flex-wrap items-center" style={{ gap: "6px 10px" }}>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{p.label}</span>
        {p.direction && p.direction !== "NEUTRAL" && <span className="cp-mono-note" style={{ fontSize: 9.5 }}>{humaniseTag(p.direction.toLowerCase())}</span>}
        <span data-testid="desk-pattern-state" style={{ marginLeft: "auto" }}>
          {st ? <Pill tone={st.tone}>{plain ? st.plain : st.trader}</Pill> : <Pill>— no state</Pill>}
        </span>
      </div>
      <span style={{ fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        {p.state_reason}{p.detected_on ? ` Detected ${fmtDay(p.detected_on)}.` : ""}{p.lifecycle_status ? ` Engine status ${p.lifecycle_status}.` : ""}
      </span>
      <ul data-testid="desk-pattern-criteria" className="m-0 grid" style={{ padding: 0, listStyle: "none", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 210px), 1fr))", gap: "2px 14px" }}>
        {p.criteria.map((c) => {
          const m = STATUS_MARK[c.status];
          return (
            <li key={c.key} data-testid={`desk-crit-${c.key}`} data-status={c.status} className="flex items-start" style={{ gap: 8, fontSize: 12, lineHeight: 1.45, padding: "3px 0" }}>
              <span aria-hidden style={{ flex: "none", width: 14, textAlign: "center", fontFamily: "var(--mono)", color: m.tone === "na" ? "var(--cp-ink-4)" : TONE_COLOR[m.tone] }}>{m.mark}</span>
              <span style={{ minWidth: 0, color: "var(--cp-ink-2)" }}>
                <span className="sr-only">{m.word}: </span>
                {c.label}
                {c.observed ? <span className="cp-mono-note" style={{ fontSize: 9.5 }}> · {c.observed}</span> : null}
                {c.reason ? <span style={{ display: "block", color: "var(--cp-ink-3)", fontSize: 11 }}>{c.reason}</span> : null}
              </span>
            </li>
          );
        })}
      </ul>
      {p.rules.length > 0 && (
        <details>
          <summary style={{ fontSize: 11.5, color: "var(--cp-ink-3)", cursor: "pointer" }}>The engine’s rules ({p.rules.length})</summary>
          <ul className="m-0 flex flex-col" style={{ padding: "6px 0 0", listStyle: "none", gap: 2 }}>
            {p.rules.map((r, i) => (
              <li key={`${r.rule_id}-${i}`} className="cp-mono-note" style={{ fontSize: 9.5, lineHeight: 1.6 }}>
                {r.rule_id} · {r.result} · observed {typeof r.observed === "number" ? fmtNum(r.observed, 2) : String(r.observed ?? "—")}
                {r.threshold != null ? ` · threshold ${typeof r.threshold === "number" ? fmtNum(r.threshold, 2) : String(r.threshold)}` : ""}
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function PatternsBlock({ q, plain }: { q: ReturnType<typeof useLivePatterns>; plain: boolean }) {
  if (q.isPending) return <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading the pattern engine…</span>;
  if (q.isError) return <ErrorBlock title="Patterns didn’t load" error={q.error} onRetry={() => q.refetch()} />;
  const d = q.data;
  if (d.kind === "locked") return <KV testId="desk-patterns-none" k="Patterns" v={dash} why="Pattern detection needs the charting feature, which this account does not have." />;
  if (d.kind === "none") return <KV testId="desk-patterns-none" k="Patterns" v={dash} why="No daily bars on record, so nothing to detect patterns on." />;
  if (d.kind === "unavailable") {
    return (
      <KV
        testId="desk-patterns-unavailable"
        k={plain ? "Chart shapes" : "Pattern states"}
        v={dash}
        why={`The pattern engine is not running on this server (${d.reason}): its research package is not deployed beside the backend, so no state is shown rather than a guess.`}
      />
    );
  }
  const p: LivePatterns = d.data;
  const off = p.families.filter((f) => !f.enabled);
  return (
    <div data-testid="desk-patterns" className="flex flex-col" style={{ gap: 8 }}>
      {p.patterns.length ? (
        <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none", gap: 8 }}>
          {p.patterns.map((x) => <PatternCard key={x.pattern_id} p={x} plain={plain} />)}
        </ul>
      ) : (
        <span data-testid="desk-patterns-empty" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>
          The engine found no support / resistance, rectangle or higher-high pattern at the last bar ({fmtDay(p.as_of)}).
        </span>
      )}
      {p.total > p.patterns.length && <span className="cp-mono-note">Showing {p.patterns.length} of {p.total}, confirmed first.</span>}
      <span data-testid="desk-patterns-off" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
        Not detected yet — no validated detector: {off.map((f) => f.label).join(", ")}.
      </span>
      <TrustLine
        testId="desk-patterns-trust"
        source="research.charting pattern engine"
        mode="eod"
        asOf={fmtDay(p.as_of)}
        maker="rules"
        method={`engine ${p.engine.engine_version} · config ${p.engine.config_hash.slice(0, 8)}${p.engine.registry_version ? ` · registry ${p.engine.registry_version}` : ""}`}
      />
    </div>
  );
}

interface Contra { key: string; text: string; source: string }

/** Contradictory evidence (§5.7 9): each point names the figure it rests on. Rules restated in the section's footnote. */
function contradictions(args: {
  setup: DeskSetup | null; live: IndicatorValues | null; patterns: LivePatterns | null; bars: DailyBar[] | null;
  pUp: number | null; pDown: number | null; liquidCr: number | null; patQ: number | null; pledge: number | null; plain: boolean;
}): { found: Contra[]; unchecked: string[] } {
  const { setup, live, patterns, bars, pUp, pDown, liquidCr, patQ, pledge, plain } = args;
  const found: Contra[] = [];
  const unchecked: string[] = [];
  if (live) {
    if (live.ema200 != null && live.close < live.ema200) {
      found.push({ key: "below-ema200", text: plain ? `The price (${fmtPrice(live.close)}) is under its 200-day average (${fmtPrice(live.ema200)}): the long trend is down.` : `Close ${fmtPrice(live.close)} is below EMA 200 ${fmtPrice(live.ema200)}: the long-term trend is against a long setup.`, source: "Indicators" });
    } else if (live.ema200 == null) unchecked.push("Long-term trend (needs 200 sessions for EMA 200)");
    if (live.rsi14 != null && live.rsi14 >= 70) found.push({ key: "overbought", text: `RSI 14 at ${fmtNum(live.rsi14, 1)}: stretched; moves after an overbought reading often retrace.`, source: "Indicators" });
    if (live.rs63) {
      if (live.rs63.excess_pct < 0) found.push({ key: "weak-rs", text: `${fmtNum(Math.abs(live.rs63.excess_pct), 1)} points behind Nifty 50 over 63 sessions.`, source: "Indicators" });
    } else unchecked.push("Relative strength (Nifty 50 closes did not load)");
    if (live.rvol20 != null && setup?.status === "confirmed" && live.rvol20 < 1) found.push({ key: "thin-volume", text: `Last session’s volume ${fmtNum(live.rvol20, 2)}× its average: the breakout is not being followed by volume.`, source: "Indicators" });
  } else unchecked.push("Trend, momentum and relative strength (indicators did not load)");
  if (patterns) {
    for (const p of patterns.patterns) {
      if (p.state === "invalidated" || p.state === "expired") found.push({ key: `pat-${p.pattern_id}`, text: `${p.label} ${p.state === "invalidated" ? "did not hold" : "expired"}${p.detected_on ? ` (${fmtDay(p.detected_on)})` : ""}: ${p.state_reason ?? ""}`.trim(), source: "Pattern engine" });
      else if (p.state === "awaiting_confirmation" || p.state === "confirmed") {
        const failed = p.criteria.filter((c) => c.status === "fail").map((c) => c.label.toLowerCase());
        if (failed.length) found.push({ key: `crit-${p.pattern_id}`, text: `${p.label}: ${failed.join(", ")} ${failed.length === 1 ? "fails" : "fail"} its check.`, source: "Pattern engine" });
      }
    }
  } else unchecked.push("Pattern failures (the pattern engine did not answer)");
  if (pUp != null && pDown != null) {
    if (pDown >= pUp) found.push({ key: "odds-down", text: "The move-odds model puts a 5% fall next session at least as high as a 5% rise (the estimates are not calibrated, so no probability is shown).", source: "Move-odds model" });
  } else unchecked.push("Down-move odds (no published estimate for this stock)");
  if (liquidCr != null) {
    if (liquidCr < LIQUID_MIN_CR) found.push({ key: "illiquid", text: `Trades ₹${fmtNum(liquidCr, 1)} Cr a day, under the desk’s ₹${LIQUID_MIN_CR} Cr liquidity gate.`, source: "Traded value" });
  } else unchecked.push("Liquidity (no 20-session traded value)");
  if (bars && setup?.entry != null && setup.stop != null && setup.entry > setup.stop) {
    const gap = largestGap(bars.slice(-64));
    const stopDist = ((setup.entry - setup.stop) / setup.entry) * 100;
    if (gap && Math.abs(gap.pct) >= stopDist) found.push({ key: "gap", text: `A ${fmtPct(Math.abs(gap.pct), { digits: 1 })} opening gap on ${fmtDay(gap.day)} is larger than the ${fmtPct(stopDist, { digits: 1 })} stop distance: a stop may fill well below its price.`, source: "Daily bars" });
    const last = bars[bars.length - 1].close;
    if (setup.target != null && last >= setup.target) found.push({ key: "past-target", text: `The last close ${fmtPrice(last)} is already at or above the target ${fmtPrice(setup.target)}.`, source: "Daily bars" });
    if (last <= setup.stop) found.push({ key: "past-stop", text: `The last close ${fmtPrice(last)} is at or below the stop ${fmtPrice(setup.stop)}.`, source: "Daily bars" });
  }
  if (patQ != null) {
    if (patQ < 0) found.push({ key: "profit-fall", text: `Latest quarter’s profit fell ${fmtPct(Math.abs(patQ), { digits: 1 })} from a year ago.`, source: "Reported results" });
  } else unchecked.push("Results trend (no quarterly results on record)");
  if (pledge != null && pledge >= PLEDGE_FLAG_PCT) found.push({ key: "pledge", text: `${fmtPct(pledge, { digits: 1 })} of shares pledged by the promoter.`, source: "Shareholding" });
  return { found, unchecked };
}

type SectionKey = "definition" | "model" | "technical" | "fundamentals" | "events" | "liquidity" | "levels" | "validation" | "contra" | "freshness";

const SECTION_TITLES: Record<SectionKey, { trader: string; plain: string }> = {
  definition: { trader: "Prediction definition and horizon", plain: "What is being estimated, and for how long" },
  model: { trader: "Model score and calibration", plain: "The score, and how reliable it has been" },
  technical: { trader: "Technical evidence", plain: "What the chart shows" },
  fundamentals: { trader: "Fundamental and ownership context", plain: "The business and who owns it" },
  events: { trader: "Corporate events and news", plain: "Company news and filings" },
  liquidity: { trader: "Liquidity and tradability", plain: "Is it easy to buy and sell?" },
  levels: { trader: "Hypothetical entry, stop and target", plain: "Possible buy, exit and target prices" },
  validation: { trader: "Historical validation", plain: "How similar setups did before" },
  contra: { trader: "Contradictory evidence", plain: "What argues against it" },
  freshness: { trader: "Data freshness and missing inputs", plain: "How fresh the data is, and what is missing" },
};
const SECTION_ORDER: SectionKey[] = ["definition", "model", "technical", "fundamentals", "events", "liquidity", "levels", "validation", "contra", "freshness"];

function DetailSection({ n, k, summary, open, onToggle, children }: { n: number; k: SectionKey; summary: ReactNode; open: boolean; onToggle: () => void; children: ReactNode }) {
  const { persona } = useDesk();
  const panel = useId();
  const t = SECTION_TITLES[k];
  return (
    <li data-testid={`desk-detail-${k}`} style={{ borderTop: n > 1 ? "1px solid var(--cp-line)" : undefined }}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panel}
        data-testid={`desk-detail-${k}-toggle`}
        onClick={onToggle}
        className="flex w-full items-start"
        style={{ gap: 12, padding: "12px 18px", border: 0, background: "none", cursor: "pointer", textAlign: "left", color: "inherit", fontFamily: "var(--sans)" }}
      >
        <span className="cp-num" style={{ flex: "none", width: 20, fontSize: 11, color: "var(--mint)", paddingTop: 1 }}>{String(n).padStart(2, "0")}</span>
        <span className="flex min-w-0 flex-col" style={{ flex: "1 1 auto", gap: 3 }}>
          <span style={{ fontSize: 13, fontWeight: 500, color: "var(--cp-ink)" }}>{persona === "investor" ? t.plain : t.trader}</span>
          <span data-testid={`desk-detail-${k}-summary`} style={{ fontSize: 12, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{summary}</span>
        </span>
        <span aria-hidden style={{ flex: "none", color: "var(--cp-ink-3)", fontSize: 12 }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && <div id={panel} data-testid={`desk-detail-${k}-body`} className="flex min-w-0 flex-col" style={{ gap: 6, padding: "0 18px 14px 50px" }}>{children}</div>}
    </li>
  );
}

function OpportunityDetail({ symbol, setup, bars, barsQ, liveQ, company, date, phone }: {
  symbol: string; setup: DeskSetup | null; bars: DailyBar[] | null; barsQ: ReturnType<typeof useDailyBars>;
  liveQ: ReturnType<typeof useLiveIndicators>; company: string | null; date: string | null; phone?: boolean;
}) {
  const { persona, openStrategy } = useDesk();
  const scanQ = useDeskScanner();
  const scanIso = setup ? (setup.inPicks ? scanQ.data?.signalDate : scanQ.data?.watchAsOf) ?? null : null;
  const plain = persona === "investor";
  const [open, setOpen] = useState<Set<SectionKey>>(() => new Set());
  const toggle = (k: SectionKey) => setOpen((s) => {
    const next = new Set(s);
    if (next.has(k)) next.delete(k); else next.add(k);
    return next;
  });
  const allOpen = open.size === SECTION_ORDER.length;

  const oddsQ = useDeskOdds("p_up5_1d");
  const stockQ = useStockOdds(symbol);
  const patQ = useLivePatterns(symbol);
  const recQ = useSetupRecord(symbol);
  const finQ = useCompanyNumbers(symbol);
  const filQ = useFilingsFeed({ symbol, days: FILING_DAYS, sort: "latest", limit: 20 });

  const live = okData(liveQ);
  const v = live?.values ?? null;
  const patterns = okData(patQ);
  const odds = oddsQ.data;
  const stock = stockQ.data?.kind === "ok" ? stockQ.data.data : null;
  const sym = symbol.toUpperCase();
  const fromLatest = odds?.kind === "final" ? odds.bySymbol.get(sym) ?? null : null;
  const pUp = fromLatest?.p ?? stock?.estimates.p_up5_1d ?? null;
  const pDown = stock?.estimates.p_down5_1d ?? null;
  const run = odds?.kind === "final" ? odds.data.run : stock?.run ?? null;
  const record = odds?.kind === "final" ? odds.data.record : null;
  const oddsWhy = odds?.kind === "no_access" || stockQ.data?.kind === "locked" ? "Move probabilities are not enabled for this account."
    : odds?.kind === "withheld" ? `Withheld: ${odds.reason}.`
      : stockQ.data?.kind === "withheld" ? `Withheld: ${stockQ.data.reason}.`
        : odds?.kind === "not_published" ? `The model has not published for ${fmtDay(odds.expectedSession)} yet (preview only).`
          : oddsQ.isPending ? "Loading the move-odds model." : oddsQ.isError ? "The move-odds model didn’t load." : `No estimate for ${sym} in the published run.`;
  // The one probability gate (desk-data.ts): the estimates are not marked calibrated, so no probability prints here.
  const gate = probabilityGate(odds, plain, stockQ.data?.kind === "ok");
  const evidence = modelEvidence(run, record, plain);
  const fin = finQ.data ?? null;
  const quarter = fin?.quarters[0] ?? null;
  const holdings = fin ? [...fin.holdings].sort((a, b) => (b.period_end ?? "").localeCompare(a.period_end ?? "")) : [];
  // The newest quarter that has any ownership figure: a quarter with only a pledge figure must not
  // hide the previous quarter's holdings (the pledge row is still shown through `newest`).
  const hasShares = (h: HoldingRow) => h.promoter_pct != null || h.fii_pct != null || h.dii_pct != null || h.mf_pct != null;
  const newest = holdings[0] ?? null;
  const ownIdx = holdings.findIndex(hasShares);
  const own = ownIdx >= 0 ? holdings[ownIdx] : newest;
  const ownPrev = ownIdx >= 0 ? holdings[ownIdx + 1] ?? null : holdings[1] ?? null;
  const filings = filQ.data?.rows ?? [];
  const tr = live?.tradability ?? null;
  // One traded-value figure on the page: the scanner's (the risk desk's gate reads it too), else the daily bars'.
  const liquidCr = setup?.avgTradedCr ?? v?.avg_traded_value_cr20 ?? null;
  const liquidSource = setup?.avgTradedCr != null ? "the scanner’s 20-session figure (stock_ohlcv)" : "the adjusted daily bars (prices_eod_adjusted)";
  const rec = recQ.data;
  const matched = rec?.buckets.filter((r) => r.matched) ?? [];
  const contra = contradictions({ setup, live: v, patterns, bars, pUp, pDown, liquidCr, patQ: quarter?.pat_yoy_pct ?? null, pledge: own?.promoter_pledged_pct ?? null, plain });
  const pct1 = (p: number | null | undefined) => (p == null ? "—" : fmtPct(p * 100, { digits: 1 }));
  const lv = deskLevels(setup, live);
  const href = fullChartHref(symbol, lv);

  // ── 1 · definition ──
  const s1 = (
    <>
      <KV testId="desk-def-setup" k={plain ? "What the scanner found" : "Scanner setup (rules, not a prediction)"} v={setup ? setupLabel(setup, plain) : dash}
        why={setup ? (setup.why ?? "The scanner stored no rule text for this setup.") : "Not on today’s scanner, so there is no rules-based setup."} />
      <KV testId="desk-def-window" k={plain ? "Holding time" : "Holding window"} v={setup && (setup.daysMin != null || setup.daysMax != null) ? `${setup.daysMin ?? "—"}–${setup.daysMax ?? "—"} days` : dash}
        why={setup && (setup.daysMin != null || setup.daysMax != null) ? "The pick’s own window." : "Only the scanner’s picks carry a holding window."} />
      <KV testId="desk-def-odds" k={plain ? "Chance of +5% next day" : "P(+5% next session)"} v={run ? `for ${fmtDay(run.target_session)}` : dash}
        why="The move-odds model’s estimate that the next session’s high reaches the last close plus 5%. One session only — never a multi-day horizon." />
      <KV testId="desk-def-record" k={plain ? "Past-record outcome" : "Historical outcome"} v={`within ${RECORD_HORIZON} sessions`}
        why="Did the stock break its 20-session high within 10 sessions after a scan with a similar score? An intraday touch, not a close and not a trade." />
      <KV testId="desk-def-patterns" k={plain ? "Chart shapes" : "Pattern states"} v="at the last bar" why="Candidate, awaiting confirmation, confirmed, invalidated or expired, from the pattern engine’s lifecycle (section 3)." />
    </>
  );

  // ── 2 · model ──
  const s2 = (
    <>
      <KV testId="desk-model-score" k={plain ? "Scanner score" : "Scanner score (rules-based, not a probability)"} v={setup?.score != null ? `${fmtNum(setup.score, 0)} / 100` : dash}
        why={setup?.score == null ? "Not on today’s scanner." : setup.confidence ? `Scanner grade ${humaniseTag(setup.confidence.toLowerCase())}.` : undefined} />
      <KV testId="desk-model-p" k={plain ? "Chance of +5% next day" : "P(+5% next session) · model estimate"} v={pUp != null ? PROBABILITY_WITHHELD : dash} why={pUp != null ? `${gate.reason}${evidence ? ` Evidence, not a probability: ${evidence}.` : ""}` : oddsWhy} />
      <KV testId="desk-model-pdown" k={plain ? "Chance of −5% next day" : "P(−5% next session) · model estimate"} v={pDown != null ? PROBABILITY_WITHHELD : dash}
        why={pDown != null ? gate.reason : stockQ.data?.kind === "ok" ? "Not in the stock’s estimates." : oddsWhy} />
      <KV testId="desk-model-version" k="Model version" v={run ? `Move-odds ${run.model}` : dash}
        why={run ? `Refit ${run.refit ?? "—"} · trained to ${run.train_end ? fmtDay(run.train_end) : "—"} · data as of ${fmtDay(run.data_as_of)} · for ${fmtDay(run.target_session)} · build ${run.git_sha}` : oddsWhy} />
      <KV testId="desk-model-eval" k="Evaluation period" v={record ? record.window_label : dash}
        why={record ? `Out of sample: top-10 hit rate ${pct1(record.top10_hit_rate)} over ${fmtNum(record.sessions)} sessions vs a base rate of ${pct1(record.base_rate)}. The model’s record, not this stock’s.` : "No out-of-sample record is published with this run."} />
      <div data-testid="desk-model-bands" className="flex flex-col" style={{ gap: 4, paddingTop: 6, borderTop: "1px solid var(--cp-line)" }}>
        <span className="cp-eyebrow" style={{ fontSize: 9.5 }}>Calibration · predicted band → what happened</span>
        {record?.bands.length ? (
          <ul className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
            {record.bands.map((b) => (
              <li key={`${b.band_lo}-${b.band_hi}`} data-testid="desk-model-band" className="cp-num flex justify-between" style={{ fontSize: 11.5, padding: "2px 0", color: "var(--cp-ink-2)" }}>
                <span>{fmtPct(b.band_lo * 100, { digits: 0 })}–{fmtPct(b.band_hi * 100, { digits: 0 })} predicted</span>
                <span>{b.realised != null ? `${fmtPct(b.realised * 100, { digits: 1 })} realised` : "— realised"} · n {fmtNum(b.rows)}</span>
              </li>
            ))}
          </ul>
        ) : (
          <span style={{ fontSize: 11.5, color: "var(--cp-ink-3)" }}>— {record ? "The run publishes no calibration bands." : oddsWhy}</span>
        )}
      </div>
    </>
  );

  // ── 3 · technical ──
  const s3 = (
    <>
      {liveQ.isPending ? <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading indicators…</span>
        : liveQ.isError ? <ErrorBlock title="Indicators didn’t load" error={liveQ.error} onRetry={() => liveQ.refetch()} />
          : v ? (
            <>
              <KV testId="desk-tech-trend" k={plain ? "Price vs 20 / 50 / 200-day averages" : "Close vs EMA 20 / 50 / 200"} v={`${fmtPrice(v.close)} · ${fmtPrice(v.ema20)} / ${fmtPrice(v.ema50)} / ${fmtPrice(v.ema200)}`} />
              <KV testId="desk-tech-momentum" k="RSI 14 · MACD histogram · ROC 20" v={`${fmtNum(v.rsi14, 1)} · ${fmtNum(v.macd_hist, 2)} · ${fmtPct(v.roc20, { signed: true, digits: 1 })}`} />
              <KV testId="desk-tech-rs" k="Relative strength vs Nifty 50 · 63 sessions" v={v.rs63 ? `${v.rs63.excess_pct > 0 ? "+" : v.rs63.excess_pct < 0 ? "−" : ""}${fmtNum(Math.abs(v.rs63.excess_pct), 1)} pts` : dash}
                why={v.rs63 ? undefined : live?.benchmark.reason ?? "No benchmark figure."} />
              <KV testId="desk-tech-volume" k="Relative volume · ATR %" v={`${v.rvol20 != null ? `${fmtNum(v.rvol20, 2)}×` : "—"} · ${fmtPct(v.atr_pct, { digits: 2 })}`} />
            </>
          ) : <KV k="Indicators" v={dash} why="The indicator route did not answer for this stock (charting not enabled, or no bars)." />}
      <span className="cp-eyebrow" style={{ fontSize: 9.5, paddingTop: 8 }}>{plain ? "Chart shapes and what confirms them" : "Patterns · state and evidence"}</span>
      <PatternsBlock q={patQ} plain={plain} />
    </>
  );

  // ── 4 · fundamentals ──
  const featureGap = (f: CompanyFeatures, what: string) =>
    `${what}: not filled on the ${fmtDay(f.as_of_date ?? null)} feature row (stock_features_daily). ${f.fundamentals_source ? `Figures there come from ${f.fundamentals_source}, as of ${fmtDay(f.fundamentals_as_of ?? null)}, and this one is missing.` : "No source figure was loaded for that date, and the filings give none."}`;
  const ownershipWhy = (o: HoldingRow | null, latest: HoldingRow | null) => {
    if (!o) return "No shareholding pattern on record.";
    const pledge = latest?.promoter_pledged_pct ?? o.promoter_pledged_pct;
    const pledgeNote = pledge != null ? ` Pledged ${fmtPct(pledge, { digits: 1 })}${latest && latest !== o ? ` (${latest.period ?? fmtDay(latest.period_end ?? null)})` : ""}.` : "";
    if (!hasShares(o)) return `Only a pledge figure is loaded for ${o.period ?? fmtDay(o.period_end ?? null)}; the exchange’s shareholding filing for that quarter is not in the warehouse.${pledgeNote}`;
    if (o.promoter_pct == null) return `The ${o.period ?? fmtDay(o.period_end ?? null)} filing gives no promoter holding.${pledgeNote}`;
    return pledgeNote.trim() || undefined;
  };
  const ownDelta = (a: number | null | undefined, b: number | null | undefined) => (a != null && b != null ? ` (${fmtPct(a - b, { signed: true, digits: 1 })} vs ${ownPrev?.period ?? "previous"})` : "");
  const s4 = finQ.isPending ? <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading results and shareholding…</span>
    : finQ.isError ? <ErrorBlock title="Results and shareholding didn’t load" error={finQ.error} onRetry={() => finQ.refetch()} />
      : (
        <>
          <KV testId="desk-fund-valuation" k="P/E · P/B" v={`${fmtNum(fin?.features?.pe_ttm ?? null, 1)} · ${fmtNum(fin?.features?.pb ?? null, 1)}`}
            why={!fin?.features ? "No feature row for this stock (stock_features_daily)." : fin.features.pe_ttm != null && fin.features.pb != null ? undefined : `${featureGap(fin.features, "P/E and P/B")}`} />
          <KV testId="desk-fund-quality" k="ROE · debt to equity" v={`${fmtPct(fin?.features?.roe_pct ?? null, { digits: 1 })} · ${fmtNum(fin?.features?.debt_to_equity ?? null, 2)}`}
            why={fin?.features && (fin.features.roe_pct == null || fin.features.debt_to_equity == null) ? featureGap(fin.features, "ROE and debt to equity") : undefined} />
          <KV testId="desk-fund-mcap" k="Market cap" v={fin?.features?.market_cap_cr != null ? `₹${fmtNum(fin.features.market_cap_cr, 0)} Cr` : dash}
            why={fin?.features?.market_cap_cr == null ? (fin?.features ? featureGap(fin.features, "Market cap") : "No feature row for this stock (stock_features_daily).") : undefined} />
          <KV testId="desk-fund-quarter" k={quarter ? `Latest quarter · ${quarter.quarter ?? fmtDay(quarter.period_end ?? null)}` : "Latest quarter"}
            v={quarter ? `Revenue ₹${fmtNum(quarter.revenue_cr ?? null, 0)} Cr · profit ₹${fmtNum(quarter.pat_cr ?? null, 0)} Cr` : dash}
            why={quarter ? `Year on year: revenue ${fmtPct(quarter.revenue_yoy_pct ?? null, { signed: true, digits: 1 })}, profit ${fmtPct(quarter.pat_yoy_pct ?? null, { signed: true, digits: 1 })}.` : "No quarterly results on record (nse_financials_quarterly)."} />
          <KV testId="desk-fund-promoter" k={own ? `Promoter · ${own.period ?? fmtDay(own.period_end ?? null)}` : "Promoter"} v={own ? `${fmtPct(own.promoter_pct ?? null, { digits: 1 })}${ownDelta(own.promoter_pct, ownPrev?.promoter_pct)}` : dash}
            why={ownershipWhy(own, newest)} />
          <KV testId="desk-fund-institutions" k="FII · DII · mutual funds" v={own ? `${fmtPct(own.fii_pct ?? null, { digits: 1 })} · ${fmtPct(own.dii_pct ?? null, { digits: 1 })} · ${fmtPct(own.mf_pct ?? null, { digits: 1 })}` : dash}
            why={own && hasShares(own) && own.mf_pct == null ? "Mutual funds: the filing’s mutual-fund line is not loaded for this quarter." : undefined} />
          <TrustLine testId="desk-fund-trust" source="NSE quarterly results · shareholding pattern · stock_features_daily" maker="reported" mode="historical" />
        </>
      );

  // ── 5 · events ──
  const s5 = filQ.isPending ? <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading filings…</span>
    : filQ.isError ? <ErrorBlock title="Filings didn’t load" error={filQ.error} onRetry={() => filQ.refetch()} />
      : (
        <>
          {filings.length ? (
            <ul data-testid="desk-events" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
              {filings.slice(0, 8).map((f) => {
                const exchange = typeof f.exchange === "string" ? f.exchange : null;
                return (
                  <li key={f.id} data-testid="desk-event" className="flex flex-col" style={{ gap: 3, padding: "7px 0", borderTop: "1px solid var(--cp-line)" }}>
                    <span className="flex flex-wrap items-baseline" style={{ gap: "2px 10px", fontSize: 12.5 }}>
                      <span className="cp-num" style={{ fontSize: 11, color: "var(--cp-ink-3)" }}>{fmtDay((f.date ?? "").slice(0, 10) || null)}</span>
                      <span style={{ color: "var(--cp-ink)" }}>{f.docLabel ?? "Filing"}</span>
                      {f.category && <span className="cp-mono-note" style={{ fontSize: 9.5 }}>{humaniseTag(f.category)}</span>}
                      {f.url && <a href={f.url} target="_blank" rel="noopener noreferrer" style={{ marginLeft: "auto", fontSize: 11.5, color: "var(--mint)" }}>{`Exchange filing${exchange ? ` (${exchange})` : ""} ↗`}</a>}
                    </span>
                    {f.one && (
                      <span style={{ fontSize: 11.5, lineHeight: 1.45, color: "var(--cp-ink-2)" }}>
                        <Pill tone="amber">AI read · not verified</Pill> {f.one}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <KV testId="desk-events-none" k={`Filings · last ${FILING_DAYS} days`} v="None" why={`No exchange filing for ${sym} in the last ${FILING_DAYS} days.`} />
          )}
        </>
      );

  // ── 6 · liquidity ──
  const band = tr ? (tr.band_raw && /no band/i.test(tr.band_raw) ? "No price band" : tr.price_band_pct != null ? `±${fmtNum(tr.price_band_pct, 0)}%` : tr.band_raw ?? "—") : null;
  const s6 = (
    <>
      <KV testId="desk-liq-traded" k={plain ? `Money traded a day · gate ₹${LIQUID_MIN_CR} Cr` : `Traded value · 20 sessions · gate ₹${LIQUID_MIN_CR} Cr`}
        v={liquidCr != null ? <>₹{fmtNum(liquidCr, 1)} Cr <Pill tone={liquidCr >= LIQUID_MIN_CR ? "mint" : "danger"}>{liquidCr >= LIQUID_MIN_CR ? "Passes" : "Below the gate"}</Pill></> : dash}
        why={liquidCr == null ? "Needs 20 sessions of close and volume." : `Mean of close × volume over the last 20 sessions, from ${liquidSource}. The desk’s gate (setup_rules LIQUIDITY).`} />
      <KV testId="desk-liq-band" k="Price band" v={band ?? dash} why={tr ? `${tr.band_raw && /no band/i.test(tr.band_raw) ? "F&O stocks trade without a daily price band. " : ""}Exchange reference data · ${tr.as_of_date ? fmtDay(tr.as_of_date) : "date —"}.` : liveQ.data?.kind === "ok" ? live?.tradability_reason ?? "No reference row." : "The reference read did not answer."} />
      <KV testId="desk-liq-fno" k="F&O eligible" v={tr?.fno_eligible == null ? dash : tr.fno_eligible ? "Yes" : "No"} />
      <KV testId="desk-liq-etf" k="ETF" v={tr?.is_etf == null ? dash : tr.is_etf ? "Yes" : "No"} />
      <KV testId="desk-liq-ban" k="F&O ban list" v={dash} why="Not ingested: no F&O ban list is on record, so a ban cannot be checked." />
      <KV testId="desk-liq-asm" k="ASM / GSM surveillance" v={dash} why="Not ingested: no surveillance list is on record." />
    </>
  );

  // ── 7 · levels ──
  const s7 = (
    <>
      <KV testId="desk-lvl-source" k="Source" v={lv.source === "scanner" ? "AI scanner pick" : lv.source === "rule" ? `Rule ${lv.rule?.name} v${lv.rule?.version}` : dash}
        why={lv.source === "scanner" ? "The scanner has levels for this stock, so they are shown instead of the rule’s." : lv.source === "rule" ? lv.rule?.label : lv.reason ?? undefined} />
      <KV testId="desk-lvl-entry" k={plain ? "Buy above" : "Entry"} v={fmtPrice(lv.entry)} why={lv.entry == null ? lv.reason ?? "No entry." : lv.source === "rule" ? "The last close." : undefined} />
      <KV testId="desk-lvl-stop" k={plain ? "Exit if wrong" : "Stop"} v={fmtPrice(lv.stop)}
        why={lv.stop == null ? lv.reason ?? "No stop." : lv.source === "rule" ? (lv.rule?.stopBasis === "support20" ? "The 20-session low, closer than the ATR stop." : `${fmtNum(lv.rule?.constants.atr_multiple ?? 0, 1)} × ATR(${lv.rule?.constants.atr_period ?? 14}) below the entry.`) : undefined} />
      <KV testId="desk-lvl-target" k="Target" v={fmtPrice(lv.target)}
        why={lv.target == null ? (lv.source === "scanner" ? "Only the scanner’s picks carry a target." : lv.reason ?? "No target.") : lv.source === "rule" ? `Entry plus ${fmtNum(lv.rule?.constants.reward_multiple ?? 0, 1)} × the risk.` : undefined} />
      <KV testId="desk-lvl-rr" k={plain ? "Reward for risk" : "Reward : risk"} v={lv.riskReward != null ? `${fmtNum(lv.riskReward, 1)} : 1` : dash} />
      <span style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)", paddingTop: 4 }}>
        {lv.source === "rule" ? `${lv.rule?.label}. ` : lv.source === "scanner" ? "Hypothetical levels from the scanner. " : ""}
        Size them in the {phone ? "trade scenario below" : "risk desk"}; nothing is sent to a broker.{" "}
        <a data-testid="desk-lvl-full" href={href} style={{ color: "var(--mint)" }}>Open full chart with these levels ↗</a>
      </span>
      <button type="button" data-testid="desk-lvl-strategy" onClick={() => openStrategy(symbol, { kind: "chart", bucket: setup?.bucket ?? null, date: scanIso })}
        style={{ alignSelf: "flex-start", padding: 0, border: 0, background: "none", cursor: "pointer", fontSize: 12.5, color: "var(--mint)", fontFamily: "var(--sans)" }}>
        Build a strategy for {symbol} ›
      </button>
    </>
  );

  // ── 8 · validation ──
  const nm = rec?.not_measured ?? {};
  const s8 = recQ.isPending ? <span style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>Loading the historical record…</span>
    : recQ.isError ? <ErrorBlock title="The historical record didn’t load" error={recQ.error} onRetry={() => recQ.refetch()} />
      : (
        <>
          <KV testId="desk-val-score" k="This stock’s accumulation score" v={rec?.symbol_score ? fmtNum(rec.symbol_score.accumulation_score, 2) : dash}
            why={rec?.symbol_score ? `As of ${fmtDay(rec.symbol_score.as_of_date)}; the record below is for scans in the same score bucket.` : rec?.symbol_reason ?? rec?.empty_reason ?? rec?._reason ?? "No score on record."} />
          {matched.length ? (
            <ul data-testid="desk-val-rows" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
              {matched.map((r) => {
                const def = rec?.metrics?.[r.metric];
                return (
                  <li key={`${r.metric}-${r.horizon_days}`} data-testid={`desk-val-${r.metric}`} className="flex flex-col" style={{ gap: 3, padding: "7px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5 }}>
                    <span style={{ color: "var(--cp-ink)" }}>{def?.label ?? r.metric} <span className="cp-mono-note" style={{ fontSize: 9.5 }}>· {def?.outcome_type === "touch" ? "intraday touch" : def?.outcome_type ?? "outcome"} · within {r.horizon_days} sessions</span></span>
                    <span className="cp-num" style={{ fontSize: 11.5, color: "var(--cp-ink-2)" }}>
                      Occurrences <span data-testid={`desk-val-${r.metric}-n`}>{fmtNum(r.sample_count)}</span>
                      {" · "}hit rate <span data-testid={`desk-val-${r.metric}-hit`}>{pct1(r.probability)}</span>
                      {" "}(95% <span data-testid={`desk-val-${r.metric}-ci`}>{r.ci95_lo != null && r.ci95_hi != null ? `${pct1(r.ci95_lo)}–${pct1(r.ci95_hi)}` : "—"}</span>)
                      {" · "}mean best move <span data-testid={`desk-val-${r.metric}-mfe`}>{fmtPct(r.avg_fwd_return, { signed: true, digits: 1 })}</span>
                      {" · "}mean worst move <span data-testid={`desk-val-${r.metric}-mae`}>{fmtPct(r.avg_fwd_drawdown, { signed: true, digits: 1 })}</span>
                    </span>
                    {def?.rule && <span style={{ fontSize: 11, lineHeight: 1.45, color: "var(--cp-ink-3)" }}>{def.rule}</span>}
                  </li>
                );
              })}
            </ul>
          ) : (
            <KV testId="desk-val-none" k="Occurrences · hit rate · MFE · MAE" v={dash} why={rec?.empty_reason ?? rec?.symbol_reason ?? rec?._reason ?? "No record row for this stock’s score bucket."} />
          )}
          <KV testId="desk-val-slot-holding" k="Holding period" v={`${RECORD_HORIZON} sessions`} why="Every row checks the sessions after the scan day; no exit rule is simulated." />
          <KV testId="desk-val-slot-average" k="Average return" v={dash} why={nm.median_return ? "Not stored: the record keeps each scan’s best and worst move (MFE / MAE), not a realised exit return." : "Not in the record."} />
          <KV testId="desk-val-slot-median" k="Median return" v={dash} why={nm.median_return ?? "Not in the record."} />
          <KV testId="desk-val-slot-costs" k="Transaction costs" v={dash} why={nm.costs ?? "Not in the record."} />
          <KV testId="desk-val-slot-benchmark" k="Benchmark comparison" v={dash} why={nm.benchmark ?? "Not in the record."} />
          <KV testId="desk-val-slot-oos" k="Out-of-sample" v={dash} why={nm.out_of_sample ?? "Not in the record."} />
          <KV testId="desk-val-slot-sample" k="Sample period" v={rec?.sample ? `${fmtDay(rec.sample.first_scan_date ?? null)} – ${fmtDay(rec.sample.last_scan_date ?? null)}` : dash}
            why={rec?.sample ? `${fmtNum(rec.sample.labelled_rows)} labelled scans${rec.sample.engine_versions.length ? ` · engine ${rec.sample.engine_versions.join(", ")}` : ""}.` : rec?.sample_reason ?? "No labelled period on record."} />
          <span style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            The accumulation detector’s record, bucketed by accumulation score — scans like this one, not this setup’s own trades.
          </span>
        </>
      );

  // ── 9 · contradictory evidence ──
  const s9 = (
    <>
      {contra.found.length ? (
        <ul data-testid="desk-contra" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
          {contra.found.map((c) => (
            <li key={c.key} data-testid={`desk-contra-${c.key}`} className="flex items-start" style={{ gap: 8, padding: "6px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12.5, lineHeight: 1.5 }}>
              <span aria-hidden style={{ flex: "none", color: "var(--cp-danger)", fontFamily: "var(--mono)" }}>!</span>
              <span style={{ minWidth: 0, color: "var(--cp-ink-2)" }}>{c.text} <span className="cp-mono-note" style={{ fontSize: 9.5 }}>· {c.source}</span></span>
            </li>
          ))}
        </ul>
      ) : (
        <KV testId="desk-contra-none" k="Points against" v="None found" why="None of the checks below found evidence against the setup. That is not evidence for it." />
      )}
      {contra.unchecked.length > 0 && (
        <span data-testid="desk-contra-unchecked" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Could not check: {contra.unchecked.join("; ")}.</span>
      )}
      <span className="cp-mono-note" style={{ lineHeight: 1.6 }}>
        Checks: close under EMA 200 · RSI ≥ 70 · behind Nifty 50 · weak volume after a breakout · failed or expired patterns and failed criteria · model odds of a fall ≥ a rise · under ₹{LIQUID_MIN_CR} Cr a day · a gap larger than the stop distance · price past the target or stop · profit down year on year · promoter pledge ≥ {PLEDGE_FLAG_PCT}%.
      </span>
    </>
  );

  // ── 10 · freshness ──
  const fresh: Array<{ key: string; source: string; asOf: string | null; why?: string }> = [
    { key: "bars", source: "Daily bars · nidp.prices_eod_adjusted", asOf: bars?.length ? fmtDay(bars[bars.length - 1].day) : null, why: barsQ.data?.kind === "locked" ? "Charting is not enabled for this account." : barsQ.isError ? "Did not load." : bars ? undefined : "No bars on record." },
    { key: "indicators", source: "Indicators · stock_features_daily engine", asOf: live ? fmtDay(live.as_of) : null, why: live ? undefined : liveQ.isError ? "Did not load." : "Not available for this stock." },
    { key: "patterns", source: "Patterns · research.charting", asOf: patterns ? fmtDay(patterns.as_of) : null, why: patterns ? undefined : patQ.data?.kind === "unavailable" ? "The pattern engine is not deployed on this server." : patQ.isError ? "Did not load." : "Not available for this stock." },
    { key: "scanner", source: "Scanner · positional engine", asOf: date, why: setup ? undefined : "Not on today’s scanner." },
    { key: "odds", source: "Move-odds model", asOf: run ? fmtDay(run.data_as_of) : null, why: run ? undefined : oddsWhy },
    { key: "results", source: "Quarterly results", asOf: quarter ? quarter.quarter ?? fmtDay(quarter.period_end ?? null) : null, why: quarter ? undefined : "None on record." },
    { key: "shareholding", source: "Shareholding pattern", asOf: own ? own.period ?? fmtDay(own.period_end ?? null) : null, why: own ? undefined : "None on record." },
    { key: "filings", source: "Exchange filings", asOf: filings.length ? fmtDay((filings[0].date ?? "").slice(0, 10) || null) : null, why: filings.length ? undefined : filQ.isError ? "Did not load." : `None in the last ${FILING_DAYS} days.` },
    { key: "reference", source: "Price band · security_reference_daily", asOf: tr?.as_of_date ? fmtDay(tr.as_of_date) : null, why: tr ? undefined : live?.tradability_reason ?? "Not read." },
    { key: "record", source: "Historical record · accumulation backtest", asOf: rec?.sample?.last_scan_date ? fmtDay(rec.sample.last_scan_date) : null, why: rec?.sample ? undefined : rec?.sample_reason ?? rec?.empty_reason ?? "Not on record." },
  ];
  const missing = [
    ...fresh.filter((f) => !f.asOf).map((f) => f.source.split(" · ")[0]),
    "Intraday bars", "F&O ban list", "ASM / GSM lists", "Market-regime and event context for patterns",
  ];
  const s10 = (
    <>
      <ul data-testid="desk-fresh" className="m-0 flex flex-col" style={{ padding: 0, listStyle: "none" }}>
        {fresh.map((f) => (
          <li key={f.key} data-testid={`desk-fresh-${f.key}`} data-missing={!f.asOf} className="flex flex-wrap items-baseline" style={{ gap: "2px 12px", padding: "5px 0", borderTop: "1px solid var(--cp-line)", fontSize: 12 }}>
            <span style={{ flex: "1 1 180px", minWidth: 0, color: "var(--cp-ink-2)" }}>{f.source}</span>
            <span className="cp-num" style={{ color: f.asOf ? "var(--cp-ink)" : "var(--cp-ink-3)" }}>{f.asOf ?? "—"}</span>
            {f.why && <span style={{ flexBasis: "100%", fontSize: 11, color: "var(--cp-ink-3)" }}>{f.why}</span>}
          </li>
        ))}
      </ul>
      <span data-testid="desk-fresh-missing" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>Missing inputs: {missing.join(", ")}.</span>
      <span className="cp-mono-note">Everything here is end of day or older; nothing on this page is live.</span>
    </>
  );

  const summaries: Record<SectionKey, ReactNode> = {
    definition: setup ? `${setupLabel(setup, plain)} · scanner rules · ${run ? `P(+5%) for ${fmtDay(run.target_session)}` : "next-session odds —"}` : "Not on today’s scanner · next-session odds and patterns only",
    model: `Score ${setup?.score != null ? fmtNum(setup.score, 0) : "—"} (rules) · P(+5% next session) ${pUp != null ? PROBABILITY_WITHHELD.toLowerCase() : "—"}${record ? ` · ${record.window_label}` : ""}`,
    technical: v
      ? `${v.ema20 != null ? (v.close > v.ema20 ? "Above" : "Below") : "—"} EMA 20 · RSI ${fmtNum(v.rsi14, 0)} · ${patterns ? `${patterns.patterns.filter((p) => p.state === "confirmed").length} confirmed, ${patterns.patterns.filter((p) => p.state === "awaiting_confirmation").length} awaiting` : "patterns —"}`
      : "Indicators —",
    fundamentals: fin ? `P/E ${fmtNum(fin.features?.pe_ttm ?? null, 1)} · ROE ${fmtPct(fin.features?.roe_pct ?? null, { digits: 0 })} · promoter ${fmtPct(own?.promoter_pct ?? null, { digits: 0 })}` : finQ.isPending ? "Loading…" : "—",
    events: filQ.isPending ? "Loading…" : filings.length ? `${filings.length} ${filings.length === 1 ? "filing" : "filings"} in ${FILING_DAYS} days · latest ${fmtDay((filings[0].date ?? "").slice(0, 10) || null)}` : `No filings in ${FILING_DAYS} days`,
    liquidity: `${liquidCr != null ? `₹${fmtNum(liquidCr, 1)} Cr a day` : "Traded value —"} · ${band ?? "price band —"} · F&O ban list —`,
    levels: lv.entry != null ? `${lv.source === "rule" ? "Rule-based · " : ""}Entry ${fmtPrice(lv.entry)} · stop ${fmtPrice(lv.stop)} · target ${fmtPrice(lv.target)}` : "No levels",
    validation: headlineRow(rec) ? `Hit rate ${pct1(headlineRow(rec)?.probability ?? null)} · n ${fmtNum(headlineRow(rec)?.sample_count ?? null)} (touch, ${RECORD_HORIZON} sessions)` : "— No record for this stock’s bucket",
    contra: contra.found.length ? `${contra.found.length} ${contra.found.length === 1 ? "point" : "points"} against` : "None found among the checks",
    freshness: `${fresh.filter((f) => f.asOf).length} of ${fresh.length} sources on record · ${missing.length} missing inputs`,
  };
  const bodies: Record<SectionKey, ReactNode> = { definition: s1, model: s2, technical: s3, fundamentals: s4, events: s5, liquidity: s6, levels: s7, validation: s8, contra: s9, freshness: s10 };

  return (
    <section data-testid="desk-detail" className="cp-card flex min-w-0 flex-col">
      {phone ? (
        <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "12px 14px", borderBottom: "1px solid var(--cp-line)" }}>
          <span data-testid="desk-detail-title" className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}>{plain ? "Everything about this idea" : "Opportunity detail"}</span>
        </div>
      ) : (
        <CardHead num="03" title={plain ? "Everything about this idea" : "Opportunity detail"} testId="desk-detail-title">
          <span className="cp-mono-note" style={{ fontSize: 9.5 }}>{company ? `${sym} · ${company}` : sym}</span>
        </CardHead>
      )}
      <div className="flex flex-wrap items-center" style={{ gap: 8, padding: "10px 18px 0" }}>
        <span style={{ fontSize: 12, color: "var(--cp-ink-3)", flex: "1 1 200px" }}>{plain ? "Short answers first; open a section for the detail." : "Ten sections, summaries first; open one for its evidence."}</span>
        <button
          type="button"
          data-testid="desk-detail-all"
          aria-pressed={allOpen}
          onClick={() => setOpen(allOpen ? new Set() : new Set(SECTION_ORDER))}
          style={{ padding: 0, border: 0, background: "none", color: "var(--mint)", fontSize: 12, cursor: "pointer", fontFamily: "var(--sans)" }}
        >
          {allOpen ? "Close all" : "Open all"}
        </button>
      </div>
      <ol className="m-0 flex flex-col" style={{ padding: "6px 0 0", listStyle: "none" }}>
        {SECTION_ORDER.map((k, i) => (
          <DetailSection key={k} n={i + 1} k={k} summary={summaries[k]} open={open.has(k)} onToggle={() => toggle(k)}>{bodies[k]}</DetailSection>
        ))}
      </ol>
      <div style={{ padding: "10px 18px 14px", borderTop: "1px solid var(--cp-line)" }}>
        <TrustLine
          testId="desk-detail-trust"
          source="Positional scanner · move-odds model · data platform"
          mode="eod"
          asOf={date}
          maker="rules"
          method="Each section names its own source; missing figures show — with the reason"
        />
      </div>
    </section>
  );
}

// ── the tab ──────────────────────────────────────────────────────────────

export default function ChartTab() {
  const { mobile } = useCopilotShell();
  const { symbol: chosen, openTab, persona } = useDesk();
  const plain = persona === "investor";
  const scan = useDeskScanner();
  const odds = useDeskOdds("p_up5_1d");
  const setups = scan.data?.setups ?? [];
  const symbol = chosen ?? setups[0]?.symbol ?? null;
  const setup = symbol ? setups.find((s) => s.symbol === symbol) ?? null : null;
  const barsQ = useDailyBars(symbol);
  const availQ = useIntradayAvailability();
  const [iv, setIvRaw] = useState<string>("1D");
  const enabledIntervals = availQ.data?.available ? availQ.data.intervals.map((i) => i.toLowerCase()) : [];
  const ivNow = iv === "1D" || enabledIntervals.includes(iv) ? iv : "1D";       // an interval that stopped being available falls back to daily
  const setIv = (v: string) => setIvRaw(v);
  const stockQ = useStockOdds(symbol);
  const liveQ = useLiveIndicators(symbol);
  const filQ = useFilingsFeed({ symbol: symbol ?? "", days: FILING_DAYS, sort: "latest", limit: 20 }, !!symbol);
  const [tf, setTf] = useState<Timeframe>("3M");
  const [ov, setOv] = useState<Overlays>({ ema: true, vwap: true, levels: true });
  const [extra, setExtra] = useState<string[]>([]);
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [card, setCard] = useState<HTMLElement | null>(null);
  const boxW = useBoxWidth(box);
  const cardW = useBoxWidth(card);
  const bars = barsQ.data?.kind === "ok" ? barsQ.data.bars : null;
  const live = okData(liveQ);
  const snap = snapOf(live?.values ?? null);
  const events = useMemo(() => eventMarkers(filQ.data?.rows ?? []), [filQ.data]);
  const date = scan.data ? scanDateLabel(scan.data.watchAsOf, scan.data.signalDate) : null;

  if (!symbol) {
    if (scan.isPending) return <LoadingBlock label="Loading the scanner" rows={4} />;
    return (
      <div data-testid="desk-chart-tab" className="flex flex-col" style={{ gap: 16 }}>
        <div data-testid="desk-chart-nosymbol">
          <EmptyBlock
            title="Pick a stock to chart"
            body={scan.isError ? "The scanner didn’t load, so there is no first setup to show." : "The scanner has no setups on its latest scan, so there is no stock to open yet."}
            action={<button type="button" className="cp-chip" onClick={() => openTab("scanner")}>Open the AI scanner ›</button>}
          />
        </div>
      </div>
    );
  }

  const row = odds.data?.kind === "final" ? odds.data.data.rows.find((r) => r.symbol.toUpperCase() === symbol) ?? null : null;
  const stock = stockQ.data?.kind === "ok" ? stockQ.data.data : null;
  const company = row?.company_name ?? stock?.company_name ?? null;
  const hasLevels = !!setup && (setup.entry != null || setup.stop != null || setup.target != null);
  const body = ivNow === "1D"
    ? <ChartBody symbol={symbol} state={barsQ} retry={() => barsQ.refetch()} setup={setup} tf={tf} ov={ov} compact={mobile} live={live} events={events} />
    : <IntradayBody symbol={symbol} interval={ivNow} setup={setup} ov={ov} compact={mobile} />;
  const trust = (
    <TrustLine
      testId="desk-chart-trust"
      source="NSE daily bars (nidp.prices_eod_adjusted)"
      mode="eod"
      asOf={bars?.length ? fmtDay(bars[bars.length - 1].day) : null}
      maker="rules"
      method={live ? "Indicators: stock_features_daily engine (calculator.py) · scanner setups: rules" : "Scanner setups: rules"}
      status={barsQ.isError || liveQ.isError ? "failed" : null}
    />
  );

  // ── phone (design-spec §11 M4) ──
  if (mobile) {
    const m = priceMove(bars, setup);
    return (
      <div data-testid="desk-chart-tab" data-layout="phone" data-symbol={symbol} className="flex min-w-0 flex-col" style={{ gap: 12 }}>
        <div data-testid="desk-chart-header" className="flex items-start justify-between" style={{ gap: 10 }}>
          <div className="flex min-w-0 items-center" style={{ gap: 10 }}>
            <StockIcon symbol={symbol} name={company} size={32} />
            <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
              <span data-testid="desk-chart-symbol" style={{ fontFamily: "var(--display)", fontSize: 26, lineHeight: 1 }}>{symbol}</span>
              <span className="cp-num" style={{ fontSize: 12, color: "var(--cp-ink-3)", whiteSpace: "nowrap" }}>
                NSE · <span data-testid="desk-chart-close" style={{ color: "var(--cp-ink-2)" }}>{fmtPrice(m.close)}</span>{" "}
                <span data-testid="desk-chart-change" style={{ color: TONE_COLOR[signTone(m.change)] }}>{fmtPct(m.changePct, { signed: true, digits: 2 })}</span>
              </span>
            </div>
          </div>
          {setup && <span data-testid="desk-chart-status" data-status={setup.status} style={{ flex: "none" }}><Pill tone={RISK_STATUS[setup.status].tone}>{RISK_STATUS[setup.status].label}</Pill></span>}
        </div>
        <div className="flex flex-wrap items-center" style={{ gap: 8 }}>
          <ChartControls tf={tf} setTf={setTf} ov={ov} setOv={setOv} hasLevels={hasLevels} small />
        </div>
        <section data-testid="desk-chart-card" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 12 }}>
          {body}
          <ChartToolbar symbol={symbol} company={company} setup={setup} iv={ivNow} setIv={setIv} enabledIntervals={enabledIntervals} />
          {trust}
        </section>

        <section data-testid="desk-analysis" className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: 14 }}>
          <span className="cp-eyebrow" style={{ color: "var(--cp-ink-2)" }}><span style={{ color: "var(--mint)" }}>03</span> · AI chart analysis</span>
          <div data-testid="desk-chart-pills" className="flex flex-wrap" style={{ gap: 6 }}>
            {setup ? (
              <>
                <Pill tone="mint">{setupLabel(setup, plain)}</Pill>
                {setup.confidence && <Pill tone="indigo">{plain ? "Scanner’s confidence" : "Scanner confidence"} · {humaniseTag(setup.confidence.toLowerCase())}</Pill>}
              </>
            ) : <Pill>Not on today’s scanner</Pill>}
          </div>
          {setup ? (
            <>
              <p data-testid="desk-why-summary" className="m-0" style={{ fontSize: 12.5, lineHeight: 1.55, color: "var(--cp-ink-2)" }}>
                {[setup.why, ...setup.reasons].filter(Boolean).join(" · ") || "The scanner stored no reason text for this setup."}
              </p>
              <div data-testid="desk-setup-check"><SetupRows setup={setup} /></div>
            </>
          ) : (
            <NotOnScanner symbol={symbol} scanError={scan.isError} date={date} />
          )}
        </section>

        <section className="cp-card flex min-w-0 flex-col" style={{ gap: 10, padding: "12px 6px" }}>
          <span className="cp-eyebrow" style={{ padding: "0 8px" }}>Historical performance · similar setups</span>
          <HistoryTiles setup={setup} count={3} phone />
        </section>

        <TradeScenarioCard symbol={symbol} setup={setup} />

        <OpportunityDetail symbol={symbol} setup={setup} bars={bars} barsQ={barsQ} liveQ={liveQ} company={company} date={date} phone />
      </div>
    );
  }

  // ── desk (design-spec §5): 7fr chart card + the opportunity detail, 5fr risk desk ──
  const sideBySide = boxW == null || boxW >= SIDE_BY_SIDE_MIN;
  const five = cardW == null || cardW >= FIVE_TILES_MIN;
  return (
    <div
      ref={setBox}
      data-testid="desk-chart-tab"
      data-layout={sideBySide ? "desk" : "stacked"}
      data-symbol={symbol}
      className="grid min-w-0"
      style={{ gridTemplateColumns: sideBySide ? "minmax(0,7fr) minmax(0,5fr)" : "minmax(0,1fr)", gap: 16, alignItems: "start" }}
    >
      <div className="flex min-w-0 flex-col" style={{ gap: 16 }}>
        <section ref={setCard} data-testid="desk-chart-card" className="cp-card flex min-w-0 flex-col">
          <CardHead num="03" title="AI Chart intelligence" padding="9px 12px 9px 18px" testId="desk-chart-title">
            <ChartControls tf={tf} setTf={setTf} ov={ov} setOv={setOv} hasLevels={hasLevels} />
          </CardHead>
          <HeadRow symbol={symbol} setup={setup} bars={bars} company={company} />
          <div className="flex flex-col" style={{ gap: 10, padding: "8px 18px 14px" }}>
            {body}
            <ChartToolbar symbol={symbol} company={company} setup={setup} iv={ivNow} setIv={setIv} enabledIntervals={enabledIntervals} />
          </div>
          {live ? (
            <>
              <IndicatorTiles live={live} five={five} extra={extra} />
              <IndicatorDrawer live={live} extra={extra} setExtra={setExtra} />
            </>
          ) : liveQ.isError ? (
            <div style={{ padding: "0 18px 12px" }}><ErrorBlock title="Indicators didn’t load" error={liveQ.error} onRetry={() => liveQ.refetch()} /></div>
          ) : liveQ.isPending ? null : liveQ.data?.kind === "unavailable" ? (
            <span data-testid="desk-indicators-none" style={{ padding: "0 18px 12px", fontSize: 12, color: "var(--cp-ink-3)" }}>— Indicators are not available here: {liveQ.data.reason}.</span>
          ) : null}
          <div
            className="grid"
            style={{ gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 240px), 1fr))", gap: 20, padding: "16px 18px", borderTop: "1px solid var(--cp-line)" }}
          >
            {setup ? (
              <>
                <SetupCheck setup={setup} date={date} />
                <WhyItRanks setup={setup} snap={snap} />
              </>
            ) : (
              <NotOnScanner symbol={symbol} scanError={scan.isError} date={date} />
            )}
          </div>
          <HistoryTiles setup={setup} count={4} />
          <div style={{ padding: "10px 18px 12px", borderTop: "1px solid var(--cp-line)", background: "var(--bg-0)", borderRadius: "0 0 14px 14px" }}>{trust}</div>
        </section>
        <OpportunityDetail symbol={symbol} setup={setup} bars={bars} barsQ={barsQ} liveQ={liveQ} company={company} date={date} />
      </div>
      <RiskDesk symbol={symbol} setup={setup} bars={bars} />
    </div>
  );
}
