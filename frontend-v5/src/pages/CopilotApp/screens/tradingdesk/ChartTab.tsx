/**
 * Smart trading desk — 03 Chart analysis, with the 05 AI Risk desk beside it
 * (design-spec §5), and the phone's M4 composition (§11).
 *
 *   daily candles, indicators   GET /api/research/chart-live/{symbol}/ohlcv?start=   (useDailyBars; flag `charting`;
 *                               end of day, split and bonus adjusted: nidp.prices_eod_adjusted)
 *   setup, levels, why          GET /api/positional/watchlist + /picks                (useDeskScanner, end of day);
 *                               next resistance / support: the watchlist row's resistance_level / support_level
 *   catalyst (events on record) GET /api/move-odds/latest?head=p_up5_1d (useDeskOdds) and
 *                               GET /api/move-odds/stocks/{symbol} (useStockOdds; its events list)
 *   risk desk                   RiskDesk.tsx (its own header lists its reads and the two writes)
 *
 * EMA 20 / 50, RSI 14, ATR 14, RVOL and a 20-day VWAP are worked out here from
 * the daily bars (indicators.ts). The VWAP is a 20-day volume-weighted average
 * of daily prices, not the intraday VWAP. The stock shown is the desk's
 * `?sym=`, else the scanner's first setup.
 *
 * Shown as "—" with the reason, because no route publishes them: the setup's
 * back-tested hit rate and average move ("Historical performance"). The
 * design's "Pattern confidence" is the scanner's own grade (HIGH / MEDIUM / LOW),
 * labelled "Scanner confidence".
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { StockIcon } from "../../components/EntityIcon";
import { EmptyBlock, ErrorBlock, LoadingBlock, NotConnected, Pill, TONE_COLOR, fmtNum, fmtPct, humaniseTag, signTone, type Tone } from "../../components/ui";
import { useCopilotShell } from "../../lib/shell-context";
import { fmtDay, fmtPrice, fmtSigned } from "../trading/parts";
import { CandleChart, CandleLegend, PLAIN_CHART_WORDS, TRADER_CHART_WORDS } from "./CandleChart";
import { scanDateLabel, setupLabel, useDailyBars, useStockOdds, type DailyBars } from "./chart-data";
import { useDesk } from "./context";
import { useDeskOdds, useDeskScanner, type DeskSetup } from "./desk-data";
import { ema, rsiZone, snapshot, vwapRolling, type DailyBar, type IndicatorSnapshot } from "./indicators";
import { CardHead, RISK_STATUS, RiskDesk, Segmented, TradeScenarioCard } from "./RiskDesk";

type Timeframe = "1M" | "3M" | "6M";
const SESSIONS: Record<Timeframe, number> = { "1M": 22, "3M": 63, "6M": 126 };
const TIMEFRAMES = (Object.keys(SESSIONS) as Timeframe[]).map((t) => ({ value: t, label: t, id: t, title: `${SESSIONS[t]} daily candles` }));

/** Below this width the chart card and the risk desk stack instead of sitting 7 : 5 side by side. */
const SIDE_BY_SIDE_MIN = 640;
/** Below this width of the chart card the five indicator tiles wrap 3 + 2. */
const FIVE_TILES_MIN = 520;

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

// ── chart body (the candles, or why there are none) ──────────────────────

function ChartBody({ symbol, state, retry, setup, tf, ov, compact }: {
  symbol: string;
  state: { isPending: boolean; isError: boolean; error: unknown; data: DailyBars | undefined };
  retry: () => void;
  setup: DeskSetup | null;
  tf: Timeframe;
  ov: Overlays;
  compact?: boolean;
}) {
  const { persona } = useDesk();
  const words = persona === "investor" ? PLAIN_CHART_WORDS : TRADER_CHART_WORDS;
  const bars = state.data?.kind === "ok" ? state.data.bars : null;
  const hasLevels = !!setup && (setup.entry != null || setup.stop != null || setup.target != null);
  const lines = useMemo(() => {
    if (!bars) return null;
    const closes = bars.map((b) => b.close);
    return { ema20: ema(closes, 20), ema50: ema(closes, 50), vwap20: vwapRolling(bars, 20) };
  }, [bars]);

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
  if (state.data?.kind === "none" || !bars || !lines) {
    return (
      <div data-testid="desk-chart-noprices">
        <EmptyBlock title={`No daily prices on record for ${symbol}`} body="The data platform has no adjusted end-of-day bars for this symbol. Pick a stock from the AI scanner." />
      </div>
    );
  }
  const n = Math.min(SESSIONS[tf], bars.length);
  const from = bars.length - n;
  const slice = <T,>(xs: T[]) => xs.slice(from);
  const ok = state.data?.kind === "ok" ? state.data : null;
  const levelsOn = ov.levels && hasLevels;
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 10 }}>
      <CandleChart
        bars={slice(bars)}
        name={symbol}
        compact={compact}
        words={words}
        overlays={{
          ema20: ov.ema ? slice(lines.ema20) : undefined,
          ema50: ov.ema ? slice(lines.ema50) : undefined,
          vwap20: ov.vwap ? slice(lines.vwap20) : undefined,
          levels: levelsOn && setup ? { target: setup.target, entry: setup.entry, stop: setup.stop } : null,
        }}
      />
      <CandleLegend ema={ov.ema} vwap={ov.vwap} levels={levelsOn} words={words} span={tf} />
      <span data-testid="desk-chart-source" className="cp-mono-note" style={{ lineHeight: 1.6, fontSize: 9.5 }}>
        NSE daily bars, split and bonus adjusted{ok?.provider ? ` (${ok.provider})` : ""} · end of day · last session {fmtDay(bars[bars.length - 1].day)}
        {n < SESSIONS[tf] ? ` · only ${n} sessions on record, all shown` : ""}
        {ok?.partial ? " · the data platform dropped some incomplete sessions from this series" : ""}
        {" "}· indicators worked out here from these bars; VWAP 20D is a 20-day volume-weighted average of daily prices, not the intraday VWAP
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
  const m = priceMove(bars, setup);
  return (
    <div data-testid="desk-chart-header" className="flex flex-wrap items-start justify-between" style={{ gap: "10px 16px", padding: "16px 18px 4px" }}>
      <div className="flex min-w-0 flex-col" style={{ gap: 6 }}>
        <span className="flex min-w-0 items-center" style={{ gap: 8, fontSize: 13, color: "var(--cp-ink-3)" }}>
          <StockIcon symbol={symbol} name={company} size={20} />
          <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            <span data-testid="desk-chart-symbol" style={{ color: "var(--cp-ink-2)", fontWeight: 500 }}>{symbol}</span>
            {company ? ` · ${company}` : ""}
          </span>
        </span>
        <span className="flex flex-wrap items-baseline" style={{ gap: "4px 10px" }}>
          <span data-testid="desk-chart-close" style={{ fontFamily: "var(--display)", fontSize: 34, lineHeight: 1, letterSpacing: "-0.02em" }}>{fmtPrice(m.close)}</span>
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

// ── indicator tiles ──────────────────────────────────────────────────────

function where(close: number | null, v: number | null, plain: boolean): { text: string; tone: Tone } {
  if (close == null || v == null) return { text: "—", tone: "ink" };
  if (close > v) return { text: plain ? "Price above it" : "Price above", tone: "mint" };
  if (close < v) return { text: plain ? "Price below it" : "Price below", tone: "danger" };
  return { text: "Price at", tone: "ink" };
}

const RSI_PLAIN: Record<string, string> = { Overbought: "Stretched", Healthy: "Strong", Neutral: "Neutral" };

function IndicatorTiles({ snap, five }: { snap: IndicatorSnapshot; five: boolean }) {
  const { persona } = useDesk();
  const plain = persona === "investor";
  const zone = rsiZone(snap.rsi14);
  const expansion = snap.rvol20 != null && snap.rvol20 >= 1.5;
  const e = where(snap.close, snap.ema20, plain);
  const v = where(snap.close, snap.vwap20, plain);
  const tiles: Array<{ id: string; k: string; v: string; s: string; tone: Tone; title: string }> = [
    { id: "ema20", k: plain ? "Trend" : "EMA 20", v: fmtPrice(snap.ema20), s: e.text, tone: e.tone, title: "20-day exponential moving average of the close, seeded with the simple average of the first 20 closes" },
    {
      id: "rsi", k: plain ? "Momentum" : "RSI 14", v: fmtNum(snap.rsi14, 1), s: zone ? (plain ? RSI_PLAIN[zone] : zone) : "—",
      tone: zone === "Overbought" ? "amber" : zone === "Healthy" ? "mint" : "ink", title: "Wilder’s RSI over 14 sessions",
    },
    { id: "atr", k: plain ? "Daily swing" : "ATR 14", v: fmtPrice(snap.atr14), s: snap.atrPct != null ? `${fmtPct(snap.atrPct, { digits: 2 })} of price` : "—", tone: "ink", title: "Wilder’s average true range over 14 sessions" },
    { id: "vwap", k: plain ? "Month’s avg" : "VWAP 20D", v: fmtPrice(snap.vwap20), s: v.text, tone: v.tone, title: "20-day volume-weighted average of daily prices ((high + low + close) ÷ 3) — not the intraday VWAP" },
    {
      id: "rvol", k: plain ? "Activity" : "RVOL", v: snap.rvol20 != null ? `${fmtNum(snap.rvol20, 2)}×` : "—",
      s: snap.rvol20 == null ? "—" : expansion ? (plain ? "Busier than usual" : "Volume expansion") : (plain ? "Usual activity" : "No volume expansion"),
      tone: expansion ? "mint" : "ink", title: "The last session’s volume ÷ the average of the 20 sessions before it",
    },
  ];
  const cols = five ? 5 : 3;
  return (
    <div data-testid="desk-indicators" data-cols={cols} className="grid" style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`, borderTop: "1px solid var(--cp-line)" }}>
      {tiles.map((t, i) => (
        <div
          key={t.id}
          title={t.title}
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

function whyRows(setup: DeskSetup, snap: IndicatorSnapshot | null, cat: ReturnType<typeof useCatalyst>, plain: boolean): WhyRow[] {
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

function WhyItRanks({ setup, snap }: { setup: DeskSetup; snap: IndicatorSnapshot | null }) {
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

// ── historical performance ───────────────────────────────────────────────

function historyTiles(setup: DeskSetup | null, plain: boolean) {
  const rr = setup?.riskReward ?? null;
  return [
    { id: "hit", k: plain ? "Worked before" : "Hit rate", v: "—", s: "No back-tested record for this setup is published" },
    { id: "move", k: plain ? "Typical rise" : "Average move", v: "—", s: "Not published for this setup" },
    { id: "rr", k: plain ? "Reward for risk" : "Reward : risk", v: rr != null ? `${fmtNum(rr, 1)} : 1` : "—", s: rr != null ? "From the scanner’s levels" : "Needs a target and a stop" },
    {
      id: "conf", k: plain ? "Scanner’s confidence" : "Scanner confidence", v: setup?.confidence ? humaniseTag(setup.confidence.toLowerCase()) : "—",
      s: setup?.confidence ? "The scanner’s own grade" : "No grade for this stock",
    },
  ];
}

function HistoryTiles({ setup, count, phone }: { setup: DeskSetup | null; count: 3 | 4; phone?: boolean }) {
  const { persona } = useDesk();
  const tiles = historyTiles(setup, persona === "investor").slice(0, count);
  return (
    <div data-testid="desk-history" className="grid" style={{ gridTemplateColumns: `repeat(${count}, minmax(0, 1fr))`, background: phone ? undefined : "var(--bg-0)", borderTop: phone ? undefined : "1px solid var(--cp-line)", borderRadius: phone ? undefined : "0 0 14px 14px" }}>
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
          ? `The scanner didn’t load, so there is no trigger, stop or target for ${symbol}. The chart and indicators are still worked out from its daily bars.`
          : `${symbol} did not pass the end-of-day scanner’s rules${date ? ` on the ${date} scan` : ""}, so it has no trigger, stop or target. The chart and indicators are still worked out from its daily bars.`}
      </span>
    </div>
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
  const stockQ = useStockOdds(symbol);
  const [tf, setTf] = useState<Timeframe>("3M");
  const [ov, setOv] = useState<Overlays>({ ema: true, vwap: true, levels: true });
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const [card, setCard] = useState<HTMLElement | null>(null);
  const boxW = useBoxWidth(box);
  const cardW = useBoxWidth(card);
  const bars = barsQ.data?.kind === "ok" ? barsQ.data.bars : null;
  const snap = useMemo(() => (bars ? snapshot(bars) : null), [bars]);
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
  const body = <ChartBody symbol={symbol} state={barsQ} retry={() => barsQ.refetch()} setup={setup} tf={tf} ov={ov} compact={mobile} />;

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
        <section data-testid="desk-chart-card" className="cp-card flex min-w-0 flex-col" style={{ padding: 12 }}>{body}</section>

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
      </div>
    );
  }

  // ── desk (design-spec §5): 7fr chart card, 5fr risk desk ──
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
      <section ref={setCard} data-testid="desk-chart-card" className="cp-card flex min-w-0 flex-col">
        <CardHead num="03" title="AI Chart intelligence" padding="9px 12px 9px 18px" testId="desk-chart-title">
          <ChartControls tf={tf} setTf={setTf} ov={ov} setOv={setOv} hasLevels={hasLevels} />
        </CardHead>
        <HeadRow symbol={symbol} setup={setup} bars={bars} company={company} />
        <div style={{ padding: "8px 18px 14px" }}>{body}</div>
        {snap && <IndicatorTiles snap={snap} five={five} />}
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
      </section>
      <RiskDesk symbol={symbol} setup={setup} bars={bars} />
    </div>
  );
}
