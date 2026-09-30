/**
 * The swing chart for one paper trade: the daily sessions the trade actually lived through, with the
 * three PRE-REGISTERED legs drawn across them -- entry, stop and the two targets.
 *
 * It reads `trade.observations`, which the API already returns and the page already prints as a table.
 * Nothing new is fetched: the candles were always in the browser, only unrendered. The bars are the
 * engine's own corporate-action-adjusted record (each row carries its `adjustment_factor`), so they
 * cannot disagree with the returns printed beside them -- which a second price source would eventually
 * do, and silently.
 *
 * Why daily and not intraday: the position runs up to six sessions, so the single-session five-minute
 * chart (PaperIntradayChart) cannot show the thing a reader wants -- whether price reached the target
 * before it reached the stop. The two charts answer different questions and both are kept.
 *
 * The levels are a frozen experiment, not advice, and the chart is deliberately mute about what should
 * have been done. On this engine's own 402-session record the rules returned -0.19% per trade after
 * costs and FAILED their pre-registered test; drawing them more prettily does not change that.
 *
 * Accessibility: a <canvas> is opaque to assistive technology, so every level is also rendered as text
 * beside it. That list is the chart's real content -- the canvas is the decoration.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart, CandlestickSeries, createSeriesMarkers, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type Time, type SeriesMarker,
} from "lightweight-charts";
import { BandsPrimitive, type ReferenceBand } from "./charts/bandLayer";
import { LevelTagsPrimitive, type LevelTag } from "./charts/levelTagLayer";
import { resolveTheme, withAlpha } from "./charts/theme";
import { price, day } from "./paperMath";
import { fetchPreEntryBars, type PreEntryBar } from "@/services/adapters/paperTrades.adapter";

const HEIGHT = 260;

export interface PaperTradeChartTrade {
  symbol: string;
  prediction_date?: string | null;
  entry_price: number | null;
  stop_loss_price: number | null;
  target_1_price: number | null;
  target_2_price: number | null;
  stop_method?: string | null;
  observations: Array<{
    session_date: string;
    open_price: number | null;
    high_price: number | null;
    low_price: number | null;
    close_price: number | null;
    stop_hit: boolean | null;
    target_hit: boolean | null;
  }>;
}

type LegKey = "entry" | "stop" | "t1" | "t2";
interface Leg { key: LegKey; label: string; value: number; tone: "ink" | "danger" | "mint" }

export default function PaperTradeChart({ t }: { t: PaperTradeChartTrade }) {
  const host = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);

  // A session is only plottable when all four prices are present. A bar with a hole in it is dropped
  // rather than patched: a candle invented from three prices would be indistinguishable from a real one.
  const bars = useMemo(
    () =>
      t.observations
        .filter((o) => o.open_price != null && o.high_price != null && o.low_price != null && o.close_price != null)
        .map((o) => ({
          time: o.session_date as Time,
          open: o.open_price as number, high: o.high_price as number,
          low: o.low_price as number, close: o.close_price as number,
        })),
    [t.observations],
  );

  // A trade that has not entered has no observations. Rather than show an empty panel at the one
  // moment a reader most wants to see where the levels sit against recent price, fall back to the
  // sessions BEFORE the prediction date. Fetched only in that case -- an entered trade already has
  // its own bars and must never be drawn from a second price source.
  const [preEntry, setPreEntry] = useState<PreEntryBar[] | null>(null);
  const needsContext = bars.length === 0 && !!t.prediction_date;
  useEffect(() => {
    if (!needsContext) { setPreEntry(null); return; }
    let live = true;
    fetchPreEntryBars(t.symbol, t.prediction_date as string, 5)
      .then((b) => { if (live) setPreEntry(b); })
      .catch(() => { if (live) setPreEntry([]); });
    return () => { live = false; };
  }, [needsContext, t.symbol, t.prediction_date]);

  const legs = useMemo<Leg[]>(() => {
    const raw: Array<[LegKey, string, number | null, Leg["tone"]]> = [
      ["entry", "entry", t.entry_price, "ink"],
      ["stop", "stop", t.stop_loss_price, "danger"],
      ["t1", "target 1", t.target_1_price, "mint"],
      ["t2", "target 2", t.target_2_price, "mint"],
    ];
    // A level the engine never set is left out entirely. Substituting a default would draw a line the
    // experiment never had, which is the one thing a frozen-rules chart must not do.
    return raw.flatMap(([key, label, value, tone]) =>
      value != null && Number.isFinite(value) ? [{ key, label, value, tone }] : []);
  }, [t.entry_price, t.stop_loss_price, t.target_1_price, t.target_2_price]);

  const marks = useMemo(
    () => t.observations.filter((o) => o.stop_hit || o.target_hit).length,
    [t.observations],
  );

  const riskPct = useMemo(() => {
    if (t.entry_price == null || t.stop_loss_price == null || t.entry_price <= 0) return null;
    return (t.entry_price - t.stop_loss_price) / t.entry_price;
  }, [t.entry_price, t.stop_loss_price]);

  // What actually gets plotted: the trade's own sessions when it has them, otherwise the
  // pre-entry context. Never both -- mixing the engine's record with a second source in one
  // series would make it impossible to tell which candles the engine is accountable for.
  const isContext = bars.length === 0 && (preEntry?.length ?? 0) > 0;
  const plotted = useMemo(
    () => (bars.length ? bars : (preEntry ?? []).map((b) => ({ time: b.date as Time, open: b.o, high: b.h, low: b.l, close: b.c }))),
    [bars, preEntry],
  );

  useEffect(() => {
    const el = host.current;
    if (!el || plotted.length === 0) return;
    const theme = resolveTheme(el);

    const chart = createChart(el, {
      height: HEIGHT,
      layout: { background: { color: theme.bg1 }, textColor: theme.ink3, attributionLogo: false },
      grid: { vertLines: { color: withAlpha(theme.line, 0.5) }, horzLines: { color: withAlpha(theme.line, 0.5) } },
      rightPriceScale: { borderColor: theme.line },
      timeScale: { borderColor: theme.line, fixLeftEdge: true, fixRightEdge: true },
      crosshair: { mode: CrosshairMode.Normal },
      handleScroll: false,   // six bars: there is nothing to scroll to, and panning them away only loses them
      handleScale: false,
    });
    chartRef.current = chart;

    const series = chart.addSeries(CandlestickSeries, {
      upColor: theme.mint, downColor: theme.danger,
      wickUpColor: theme.mint, wickDownColor: theme.danger,
      borderVisible: false,
      priceLineVisible: false,
    });
    series.setData(plotted);

    const by = (k: LegKey) => legs.find((l) => l.key === k)?.value ?? null;
    const entry = by("entry"), stop = by("stop"), t2 = by("t2");

    // Two shaded zones so the asymmetry between them is visible rather than arithmetic: what is risked
    // below entry, what is sought above it. On the live rules these are 8% down against 10% up.
    if (entry != null && stop != null) {
      const risk = new BandsPrimitive();
      try {
        series.attachPrimitive(risk);
        risk.set([{ value: stop, label: "stop" }] as ReferenceBand[], { from: stop, to: entry },
                 withAlpha(theme.danger, 0.85), withAlpha(theme.danger, 0.10));
      } catch { /* a series the library refused has nothing to band */ }
    }
    if (entry != null && t2 != null) {
      const reward = new BandsPrimitive();
      const bands = legs.filter((l) => l.tone === "mint").map((l) => ({ value: l.value, label: l.label }));
      try {
        series.attachPrimitive(reward);
        reward.set(bands as ReferenceBand[], { from: entry, to: t2 },
                   withAlpha(theme.mint, 0.85), withAlpha(theme.mint, 0.08));
      } catch { /* as above */ }
    }

    if (entry != null) {
      series.createPriceLine({ price: entry, color: theme.ink3, lineWidth: 1,
                               lineStyle: LineStyle.Solid, axisLabelVisible: true, title: "entry" });
    }

    const last = plotted.at(-1)?.close ?? null;
    const tags = new LevelTagsPrimitive();
    try {
      series.attachPrimitive(tags);
      // entry is excluded: it already carries a price line with its own axis label, and a tag at the
      // same price stacks a third label on top of that one.
      tags.set(legs.filter((l) => l.key !== "entry").map<LevelTag>((l) => ({
        price: l.value,
        side: l.key === "stop" ? "S" : l.key === "entry" ? "S/R" : "R",
        pct: last != null && last > 0 ? ((l.value - last) / last) * 100 : null,
        colour: l.tone === "danger" ? theme.danger : l.tone === "mint" ? theme.mint : theme.ink3,
        broken: false,
        dim: false,
      })));
    } catch { /* tags are an enhancement; the text list below is the real record */ }

    // Mark the sessions where price actually reached a level, which is the question the table answers
    // only by making the reader compare four columns per row.
    const markers: SeriesMarker<Time>[] = (isContext ? [] : t.observations).flatMap((o) => {
      if (!o.stop_hit && !o.target_hit) return [];
      const stopped = Boolean(o.stop_hit);
      return [{
        time: o.session_date as Time,
        position: stopped ? "belowBar" : "aboveBar",
        color: stopped ? theme.danger : theme.mint,
        shape: stopped ? "arrowDown" : "arrowUp",
        text: stopped ? "stop" : "target",
      } as SeriesMarker<Time>];
    });
    if (markers.length) {
      try { createSeriesMarkers(series, markers); } catch { /* markers are decoration too */ }
    }

    chart.timeScale().fitContent();

    const ro = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    ro.observe(el);
    chart.applyOptions({ width: el.clientWidth });

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; };
  }, [plotted, isContext, legs, t.observations]);

  if (plotted.length === 0) {
    // Still loading the context, or there is genuinely no prior history (a freshly listed symbol).
    return (
      <div className="pt-note" data-testid="pt-swing-empty">
        {preEntry === null && needsContext
          ? `Loading the sessions up to ${day(t.prediction_date)}\u2026`
          : "No sessions recorded for this trade yet, and no prior history to show. The levels below were still fixed when the trade was registered."}
      </div>
    );
  }

  const label = isContext
    ? `${t.symbol}: the ${plotted.length} daily sessions up to ${day(t.prediction_date)}, shown as context. ` +
      `This trade has not entered, so none of these candles are part of its record. ` +
      `Levels fixed at registration: ${legs.map((l) => `${l.label} ${price(l.value)}`).join(", ")}.`
    : `${t.symbol}: ${plotted.length} daily sessions with the pre-registered entry, stop and target levels drawn. ` +
      legs.map((l) => `${l.label} ${price(l.value)}`).join(", ") + ".";

  return (
    <figure className="pt-swing" style={{ margin: 0 }}>
      {isContext && (
        <p className="pt-note pt-swing-context" data-testid="pt-swing-context">
          Not entered yet — these are the {plotted.length} sessions up to {day(t.prediction_date)}, shown so the
          levels can be read against recent price. None of them is part of this trade&rsquo;s record.
        </p>
      )}
      <div
        ref={host}
        className={`pt-swing-canvas${isContext ? " context" : ""}`}
        data-testid="pt-swing-chart"
        data-context={isContext ? "1" : "0"}
        data-bars={plotted.length}
        data-marks={isContext ? 0 : marks}
        role="img"
        aria-label={label}
      />
      <figcaption className="pt-swing-legend">
        <ul className="pt-swing-levels">
          {legs.map((l) => (
            <li key={l.key} data-testid={`pt-swing-level-${l.key}`} className={`pt-swing-leg ${l.tone}`}>
              <span className="pt-swing-leg-l">{l.label}</span>
              <span className="pt-mono">{price(l.value)}</span>
            </li>
          ))}
        </ul>
        {riskPct != null && (
          <p className="pt-note" data-testid="pt-swing-risk">
            Risked to the stop: {(riskPct * 100).toFixed(1)}%
            {t.stop_method === "CAP_8PCT" ? " — the 8% cap, not ATR or support, set this stop." : ""}
          </p>
        )}
      </figcaption>
    </figure>
  );
}
