/**
 * Daily candlesticks with traded volume in a strip underneath, and optional
 * overlays: 20-, 50- and 200-day EMA, a 20-day volume-weighted average price,
 * the scanner's levels (target, entry, stop) as dashed lines, and a marker
 * under each session with an exchange filing. Inline SVG, no chart library
 * (house style: screens/research/PriceChart.tsx). This is the desk's preview;
 * the full chart with drawing tools is the Research chart workspace.
 *
 * Design (design-spec §5 / §11 M4): viewBox 540 × 272 on the desk (price 230,
 * volume 36) and 330 × 194 on a phone, with a right-hand gutter that carries
 * the level labels — or the price axis when the levels are hidden — and the
 * last-price tag.
 *
 * The data comes from the caller (ChartTab: GET /api/research/chart-live/
 * {symbol}/ohlcv, end of day). Pointing at the chart, or focusing it and
 * pressing ← / →, prints one session's open, high, low, close and volume in
 * the line above it; nothing is available on hover only.
 */
import { useState, type KeyboardEvent, type PointerEvent } from "react";
import { fmtShares } from "../research/PriceChart";
import { fmtDay, fmtPrice } from "../trading/parts";
import type { DailyBar, Series } from "./indicators";

const UP = "var(--mint)";
const DOWN = "var(--cp-danger)";
const EMA20 = "var(--cp-indigo)";
const EMA50 = "var(--amber)";
const EMA200 = "var(--cp-ink-3)";
const EVENT = "var(--cp-indigo)";
const VWAP = "var(--rose)";
const ENTRY = "var(--cp-ink-2)";
const VOLUME = "var(--ink-5)";

export interface ChartLevels {
  target: number | null;
  entry: number | null;
  stop: number | null;
}

export interface ChartOverlays {
  /** Aligned to `bars`. */
  ema20?: Series;
  ema50?: Series;
  ema200?: Series;
  vwap20?: Series;
  levels?: ChartLevels | null;
}

/** Exchange filings on a session of the chart (one marker per session, however many filings it had). */
export interface ChartEvent {
  day: string;
  count: number;
  /** What the marker's tooltip and screen-reader text say. */
  title: string;
}

/** A signal marker: a pill at the top of the price pane with a dotted line down to its bar (or, `below`, a tag under the
 *  candles). `at` is a bar's `day` (its ISO time on an intraday chart); a marker whose bar is not drawn is skipped. */
export interface ChartMarker {
  at: string;
  label: string;
  /** A CSS colour (a var(--…) token). */
  color: string;
  title: string;
  /** The toggle it belongs to (data-group), e.g. pattern / confirmation / volume / fno. */
  group: string;
}

/** Extra horizontal levels (T1, T2, …): a dashed line, its value in the gutter and its name at the left. */
export interface ChartLine { key: string; label: string; value: number; color: string }

/** One signed value of a pane, drawn from the pane's zero line in its own colour (null: a gap). */
export interface PaneBar { value: number | null; color: string }

/** A pane under the volume strip on the same time axis and cursor (Live chart: futures OI, options). Bars in `bars` are
 *  series side by side in each slot, each aligned to the chart's bars; `line` has its own scale, its last value in the
 *  gutter. `empty` is drawn instead when there is nothing to draw, saying why. */
export interface ChartPane {
  key: string;
  title: string;
  bars?: PaneBar[][];
  line?: { values: Array<number | null>; color: string; format: (v: number) => string } | null;
  empty?: string | null;
  /** Text for the second readout line at bar i, or null. */
  readout?: (i: number) => string | null;
}

/** A market event under a bar: a lettered chip at the foot of the price pane (R results, F filing, C corporate action …). */
export interface ChartGlyph { key: string; at: string; glyph: string; color: string; title: string; group: string; kind: string }

/** The live chart's extras (Trade Desk › Chart Analysis › Live chart, the owner's design of 28 Oct). All optional. */
export interface ChartExtras {
  /** Panes under the volume strip (stacked, same time axis). */
  panes?: ChartPane[];
  /** Event chips at the foot of the price pane. */
  glyphs?: ChartGlyph[];
  /** The entry range, shaded; drawn only when low < high. */
  band?: { low: number; high: number; label: string } | null;
  lines?: ChartLine[];
  markers?: ChartMarker[];
  below?: ChartMarker[];
  /** An open circle on the last close. */
  lastDot?: boolean;
  /** A note at the right edge of the plot, e.g. "VALID UNTIL 29 OCT 15:30". */
  rightNote?: string | null;
  /** Names on the level lines (STOP, ENTRY, T1 …) at the left of the plot. */
  lineNames?: boolean;
}

/** What the legend and the level lines are called (trader or plain wording, design-spec §10). */
export interface ChartWords {
  ema20: string;
  ema50: string;
  ema200: string;
  vwap: string;
  target: string;
  entry: string;
  stop: string;
}

export const TRADER_CHART_WORDS: ChartWords = { ema20: "EMA 20", ema50: "EMA 50", ema200: "EMA 200", vwap: "VWAP 20D", target: "Target", entry: "Entry", stop: "Stop" };
export const PLAIN_CHART_WORDS: ChartWords = { ema20: "20-day avg", ema50: "50-day avg", ema200: "200-day avg", vwap: "Month’s avg", target: "Target", entry: "Buy above", stop: "Exit" };

/** Round tick values covering [min, max], about `count` of them. */
function niceTicks(min: number, max: number, count: number): number[] {
  const span = max - min || Math.abs(max) || 1;
  const rough = span / Math.max(1, count - 1);
  const mag = 10 ** Math.floor(Math.log10(rough));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= rough) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + step * 1e-6; v += step) out.push(Number(v.toFixed(6)));
  return out;
}

/** A price short enough for the 50-unit gutter: 2 decimals under 1,000, 1 under 10,000, none above. */
function gutterPrice(v: number): string {
  const d = v >= 10_000 ? 0 : v >= 1_000 ? 1 : 2;
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(v);
}

/** A line through the non-null points of a series (a gap where the series has none). */
function seriesPath(series: Series, x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let pen = false;
  series.forEach((v, i) => {
    if (v == null || !Number.isFinite(v)) { pen = false; return; }
    d += `${pen ? "L" : "M"} ${x(i).toFixed(1)} ${y(v).toFixed(1)} `;
    pen = true;
  });
  return d.trim();
}

/** Labels at their wanted height, pushed apart so none overlap, kept inside [top, bottom]. */
function spread<T extends { y: number; h: number }>(items: T[], top: number, bottom: number): T[] {
  const out = [...items].sort((a, b) => a.y - b.y).map((it) => ({ ...it }));
  for (let i = 0; i < out.length; i++) {
    const min = i === 0 ? top + out[i].h / 2 : out[i - 1].y + (out[i - 1].h + out[i].h) / 2 + 1;
    out[i].y = Math.max(out[i].y, min);
  }
  for (let i = out.length - 1; i >= 0; i--) {
    const max = i === out.length - 1 ? bottom - out[i].h / 2 : out[i + 1].y - (out[i + 1].h + out[i].h) / 2 - 1;
    out[i].y = Math.min(out[i].y, max);
  }
  return out;
}

/** Pill width in viewBox units for a label (monospace 8.5). */
const pillW = (label: string) => label.length * 5.3 + 10;

export function CandleChart({ bars, name, overlays, events = [], compact = false, words = TRADER_CHART_WORDS, intraday = false, extras }: {
  bars: DailyBar[];
  name: string;
  overlays: ChartOverlays;
  /** Sessions with an exchange filing; days outside the bars are ignored. */
  events?: ChartEvent[];
  /** The phone chart (330 × 194). */
  compact?: boolean;
  words?: ChartWords;
  /** Bars are intraday: `day` is an ISO time with the IST offset and the labels show the time, not just the date. */
  intraday?: boolean;
  extras?: ChartExtras;
}) {
  const label = (d: string) => (intraday ? `${fmtDay(d.slice(0, 10))} ${d.slice(11, 16)}` : fmtDay(d));
  const [active, setActive] = useState<number | null>(null);
  const n = bars.length;

  const W = compact ? 330 : 540;
  const markers = extras?.markers ?? [];
  const below = extras?.below ?? [];
  const pillH = 12;
  const head = markers.length ? 2 * (pillH + 3) + 4 : 0;          // two rows of pills above the candles
  const priceH = (compact ? 160 : 230) + head;
  const gap = 6;
  const volH = compact ? 28 : 36;
  const belowH = below.length ? 16 : 0;
  const gutter = compact ? 46 : 50;
  const panes = extras?.panes ?? [];
  const glyphs = extras?.glyphs ?? [];
  const paneH = compact ? 48 : 62;
  const panesTop = priceH + gap + volH + belowH + (panes.length ? 8 : 0);
  const H = priceH + gap + volH + belowH + (panes.length ? 8 + panes.length * (paneH + 6) : 0);
  const plotW = W - gutter;
  const volTop = priceH + gap;
  const font = compact ? 8.5 : 9;

  const levels = overlays.levels ?? null;
  const levelList: Array<{ key: string; label: string; value: number; color: string }> = [];
  if (levels?.target != null) levelList.push({ key: "target", label: words.target, value: levels.target, color: UP });
  if (levels?.entry != null) levelList.push({ key: "entry", label: words.entry, value: levels.entry, color: ENTRY });
  if (levels?.stop != null) levelList.push({ key: "stop", label: words.stop, value: levels.stop, color: DOWN });
  for (const l of extras?.lines ?? []) if (Number.isFinite(l.value)) levelList.push(l);
  const band = extras?.band && extras.band.low < extras.band.high ? extras.band : null;

  const lineValues = [overlays.ema20, overlays.ema50, overlays.ema200, overlays.vwap20].flatMap((s) => (s ?? []).filter((v): v is number => v != null && Number.isFinite(v)));
  const bandValues = band ? [band.low, band.high] : [];
  const lo = Math.min(...bars.map((b) => b.low), ...lineValues, ...levelList.map((l) => l.value), ...bandValues);
  const hi = Math.max(...bars.map((b) => b.high), ...lineValues, ...levelList.map((l) => l.value), ...bandValues);
  const room = (hi - lo || hi || 1) * 0.06;
  const min = lo - room;
  const range = hi + room - min;
  const plotH = priceH - head;
  const maxVol = Math.max(...bars.map((b) => b.volume), 1);

  const slot = plotW / Math.max(n, 1);
  const x = (i: number) => (i + 0.5) * slot;
  const y = (v: number) => head + plotH - ((v - min) / range) * plotH;
  const bodyW = Math.max(1, slot * 0.62);
  const ticks = niceTicks(lo, hi, compact ? 4 : 5);

  const last = bars[n - 1];
  const tagH = compact ? 14 : 16;
  const tagW = gutter - 1;
  // The gutter: the last-price tag, then the level labels (or the price axis when no level is drawn), kept apart.
  const gutterItems = spread(
    [
      { key: "last", y: y(last.close), h: tagH, text: gutterPrice(last.close), color: UP },
      ...levelList.map((l) => ({ key: l.key, y: y(l.value), h: 11, text: gutterPrice(l.value), color: l.color })),
    ],
    head,
    priceH,
  );
  const tagAt = gutterItems.find((g) => g.key === "last")?.y ?? y(last.close);
  const axis = levelList.length ? [] : ticks.filter((v) => Math.abs(y(v) - tagAt) > tagH / 2 + 6 && y(v) > head + 5 && y(v) < priceH - 3);

  // Pills: placed left to right, each in the first of two rows where it does not overlap the previous pill of that row.
  const dayIndex = new Map(bars.map((b, i) => [b.day, i] as const));
  const rowEnd = [-Infinity, -Infinity];
  const placed = markers
    .map((m) => ({ m, i: dayIndex.get(m.at) }))
    .filter((p): p is { m: ChartMarker; i: number } => p.i != null)
    .sort((a, b) => a.i - b.i)
    .map(({ m, i }) => {
      const w = pillW(m.label);
      const cx = Math.min(Math.max(x(i), w / 2), plotW - w / 2);
      const row = cx - w / 2 > rowEnd[0] + 2 ? 0 : cx - w / 2 > rowEnd[1] + 2 ? 1 : 0;
      rowEnd[row] = cx + w / 2;
      return { m, i, w, cx, top: 2 + row * (pillH + 3) };
    });
  const belowTop = volTop + volH + 3;

  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0 || n === 0) return;
    const at = ((e.clientX - box.left) / box.width) * W;
    setActive(Math.min(n - 1, Math.max(0, Math.floor(at / slot))));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    const from = active ?? n - 1;
    setActive(Math.min(n - 1, Math.max(0, from + (e.key === "ArrowLeft" ? -1 : 1))));
  };

  const shown = bars[active ?? n - 1];
  const shownEvent = events.find((e) => e.day === shown.day) ?? null;
  const highest = Math.max(...bars.map((b) => b.high));
  const lowest = Math.min(...bars.map((b) => b.low));
  const gutterText = { fontFamily: "var(--mono)", fontSize: font } as const;

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 6 }} data-testid="desk-chart">
      <span data-testid="desk-chart-readout" aria-live="polite" className="cp-num" style={{ fontSize: compact ? 10 : 10.5, color: "var(--cp-ink-3)", lineHeight: 1.5 }}>
        {label(shown.day)} · O {fmtPrice(shown.open)} · H {fmtPrice(shown.high)} · L {fmtPrice(shown.low)} · C {fmtPrice(shown.close)} · Vol {fmtShares(shown.volume)}
        {shownEvent ? ` · ${shownEvent.count} ${shownEvent.count === 1 ? "filing" : "filings"}` : ""}
      </span>
      {(panes.length > 0 || glyphs.length > 0) && (() => {
        const idx = active ?? n - 1;
        const parts = [
          ...panes.map((p) => p.readout?.(idx) ?? null),
          ...glyphs.filter((g) => g.at === bars[idx].day).map((g) => `${g.glyph} ${g.title}`),
        ].filter((t): t is string => !!t);
        return parts.length ? (
          <span data-testid="desk-chart-readout-panes" aria-live="polite" className="cp-num" style={{ fontSize: compact ? 10 : 10.5, color: "var(--cp-ink-3)", lineHeight: 1.5, marginTop: -4 }}>
            {parts.join(" · ")}
          </span>
        ) : null;
      })()}
      <svg
        data-testid="desk-chart-svg"
        data-compact={compact}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        tabIndex={0}
        aria-label={`${name}: ${n} ${intraday ? "intraday" : "daily"} candles from ${label(bars[0].day)} to ${label(last.day)}. Last close ${fmtPrice(last.close)}; highest ${fmtPrice(highest)}, lowest ${fmtPrice(lowest)}. Use the left and right arrow keys to read a session.`}
        style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y", overflow: "visible" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        {/* grid */}
        {ticks.filter((v) => y(v) >= head).map((v) => (
          <line key={v} x1={0} y1={y(v)} x2={plotW} y2={y(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={0.6} />
        ))}

        {/* the entry range */}
        {band && (
          <g data-testid="desk-band" data-low={band.low} data-high={band.high}>
            <title>{`${band.label} ${fmtPrice(band.low)}–${fmtPrice(band.high)}`}</title>
            <rect x={0} y={y(band.high)} width={plotW} height={Math.max(1, y(band.low) - y(band.high))} style={{ fill: "color-mix(in srgb, var(--cp-indigo) 14%, transparent)" }} />
          </g>
        )}

        {/* volume */}
        {bars.map((b, i) => {
          const h = Math.max(b.volume > 0 ? 1 : 0, (b.volume / maxVol) * volH);
          return <rect key={`v-${b.day}`} x={x(i) - bodyW / 2} y={volTop + volH - h} width={bodyW} height={h} style={{ fill: i === active ? "var(--cp-ink-3)" : VOLUME }} />;
        })}

        {/* candles */}
        {bars.map((b, i) => {
          const color = b.close >= b.open ? UP : DOWN;
          const top = y(Math.max(b.open, b.close));
          const h = Math.max(1, Math.abs(y(b.open) - y(b.close)));
          return (
            <g key={b.day} data-testid="desk-candle" data-day={b.day} opacity={active != null && i !== active ? 0.75 : 1}>
              <line x1={x(i)} y1={y(b.high)} x2={x(i)} y2={y(b.low)} style={{ stroke: color }} strokeWidth={1} />
              <rect x={x(i) - bodyW / 2} y={top} width={bodyW} height={h} style={{ fill: color }} />
            </g>
          );
        })}

        {/* overlays */}
        {overlays.vwap20 && <path data-testid="desk-line-vwap" d={seriesPath(overlays.vwap20, x, y)} fill="none" style={{ stroke: VWAP }} strokeWidth={1.3} strokeDasharray="4 3" />}
        {overlays.ema200 && <path data-testid="desk-line-ema200" d={seriesPath(overlays.ema200, x, y)} fill="none" style={{ stroke: EMA200 }} strokeWidth={1.2} strokeDasharray="1 2" />}
        {overlays.ema50 && <path data-testid="desk-line-ema50" d={seriesPath(overlays.ema50, x, y)} fill="none" style={{ stroke: EMA50 }} strokeWidth={1.3} />}
        {overlays.ema20 && <path data-testid="desk-line-ema20" d={seriesPath(overlays.ema20, x, y)} fill="none" style={{ stroke: EMA20 }} strokeWidth={1.3} />}

        {/* levels: dashed lines, the value in the gutter */}
        {levelList.map((l) => {
          const at = gutterItems.find((g) => g.key === l.key)?.y ?? y(l.value);
          return (
            <g key={l.key} data-testid={`desk-level-${l.key}`} data-value={l.value}>
              <title>{`${l.label} ${fmtPrice(l.value)}`}</title>
              <line x1={0} y1={y(l.value)} x2={plotW} y2={y(l.value)} style={{ stroke: l.color }} strokeWidth={1} strokeDasharray="4 4" />
              <text x={plotW + 4} y={at + 3} style={{ ...gutterText, fill: l.color }}>{gutterPrice(l.value)}</text>
              {extras?.lineNames && <text data-testid={`desk-level-name-${l.key}`} x={3} y={y(l.value) - 3} style={{ ...gutterText, fontSize: font - 0.5, letterSpacing: "0.08em", fill: l.color }}>{l.label.toUpperCase()}</text>}
            </g>
          );
        })}

        {/* price axis, when no level is drawn */}
        {axis.map((v) => (
          <text key={`a-${v}`} data-testid="desk-axis-label" x={plotW + 4} y={y(v) + 3} style={{ ...gutterText, fill: "var(--cp-ink-3)" }}>{gutterPrice(v)}</text>
        ))}

        {/* last-price tag */}
        <g data-testid="desk-last-tag" data-value={last.close}>
          <rect x={plotW + 1} y={tagAt - tagH / 2} width={tagW} height={tagH} rx={3} style={{ fill: UP }} />
          <text x={plotW + 1 + tagW / 2} y={tagAt + 3.2} textAnchor="middle" style={{ ...gutterText, fill: "var(--bg-0)", fontWeight: 600 }}>
            {gutterPrice(last.close)}
          </text>
        </g>

        {/* the last price: an open circle */}
        {extras?.lastDot && <circle data-testid="desk-last-dot" cx={x(n - 1)} cy={y(last.close)} r={3.6} style={{ fill: "var(--bg-1)", stroke: UP }} strokeWidth={1.6} />}

        {/* the validity note at the right edge */}
        {extras?.rightNote && (
          <text data-testid="desk-right-note" x={plotW - 4} y={head + 11} textAnchor="end" style={{ ...gutterText, fontSize: font - 0.5, letterSpacing: "0.08em", fill: "var(--cp-ink-3)" }}>{extras.rightNote}</text>
        )}

        {/* signal markers: pills with a dotted drop-line to the bar */}
        {placed.map(({ m, i, w, cx, top }) => (
          <g key={`m-${m.group}-${m.label}-${m.at}`} data-testid="desk-signal-marker" data-group={m.group} data-label={m.label} data-at={m.at}>
            <title>{m.title}</title>
            <line x1={x(i)} y1={top + pillH} x2={x(i)} y2={y(bars[i].high) - 2} style={{ stroke: m.color }} strokeWidth={0.9} strokeDasharray="1.5 2" />
            <rect x={cx - w / 2} y={top} width={w} height={pillH} rx={6} style={{ fill: "var(--bg-1)", stroke: m.color }} strokeWidth={1} />
            <text x={cx} y={top + 8.6} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 7.6, letterSpacing: "0.06em", fill: m.color }}>{m.label}</text>
          </g>
        ))}

        {/* F&O markers under the volume strip */}
        {below.map((m) => {
          const i = dayIndex.get(m.at);
          if (i == null) return null;
          const w = pillW(m.label);
          const cx = Math.min(Math.max(x(i), w / 2), plotW - w / 2);
          return (
            <g key={`b-${m.label}-${m.at}`} data-testid="desk-fno-marker" data-group={m.group} data-label={m.label} data-at={m.at}>
              <title>{m.title}</title>
              <rect x={cx - w / 2} y={belowTop} width={w} height={pillH} rx={3} style={{ fill: `color-mix(in srgb, ${m.color} 16%, transparent)`, stroke: m.color }} strokeWidth={0.8} />
              <text x={cx} y={belowTop + 8.6} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 7.4, letterSpacing: "0.05em", fill: m.color }}>{m.label}</text>
            </g>
          );
        })}

        {/* filings: a small diamond at the foot of the price pane, under the session */}
        {events.map((ev) => {
          const i = bars.findIndex((b) => b.day === ev.day);
          if (i < 0) return null;
          const cx = x(i);
          const cy = priceH - 5;
          return (
            <g key={`e-${ev.day}`} data-testid="desk-event-marker" data-day={ev.day} data-count={ev.count}>
              <title>{ev.title}</title>
              <path d={`M ${cx} ${cy - 4} L ${cx + 4} ${cy} L ${cx} ${cy + 4} L ${cx - 4} ${cy} Z`} style={{ fill: EVENT, stroke: "var(--bg-1)" }} strokeWidth={1} />
            </g>
          );
        })}

        {/* market events: lettered chips stacked up from the foot of the price pane */}
        {(() => {
          const stack = new Map<number, number>();
          return glyphs.map((g) => {
            const i = dayIndex.get(g.at);
            if (i == null) return null;
            const k = stack.get(i) ?? 0;
            stack.set(i, k + 1);
            const cx = x(i);
            const cy = priceH - 7 - k * 11;
            return (
              <g key={`g-${g.key}`} data-testid="desk-event-glyph" data-kind={g.kind} data-group={g.group} data-at={g.at}>
                <title>{g.title}</title>
                <rect x={cx - 5} y={cy - 5} width={10} height={10} rx={2.5} style={{ fill: "var(--bg-1)", stroke: g.color }} strokeWidth={1} />
                <text x={cx} y={cy + 2.6} textAnchor="middle" style={{ fontFamily: "var(--mono)", fontSize: 7, fontWeight: 600, fill: g.color }}>{g.glyph}</text>
              </g>
            );
          });
        })()}

        {/* panes under the volume strip: same slots, own scales */}
        {panes.map((p, k) => {
          const top = panesTop + k * (paneH + 6);
          const bandTop = top + 12;
          const bandBot = top + paneH - 2;
          const series = p.bars ?? [];
          const vals = series.flatMap((sr) => sr.map((b) => b.value).filter((v): v is number => v != null && Number.isFinite(v)));
          const hasNeg = vals.some((v) => v < 0);
          const maxAbs = Math.max(...vals.map((v) => Math.abs(v)), 0) || 1;
          const zero = hasNeg ? (bandTop + bandBot) / 2 : bandBot;
          const half = hasNeg ? (bandBot - bandTop) / 2 : bandBot - bandTop;
          const subW = series.length ? bodyW / series.length : bodyW;
          const lv = (p.line?.values ?? []).filter((v): v is number => v != null && Number.isFinite(v));
          const lmin = lv.length ? Math.min(...lv) : 0;
          const lmax = lv.length ? Math.max(...lv) : 1;
          const ly = (v: number) => bandBot - ((v - lmin) / ((lmax - lmin) || Math.abs(lmax) || 1)) * (bandBot - bandTop) * 0.92 - (bandBot - bandTop) * 0.04;
          const lastLine = p.line ? [...p.line.values].reverse().find((v): v is number => v != null && Number.isFinite(v)) ?? null : null;
          const drawn = !p.empty && (vals.length > 0 || lv.length > 0);
          return (
            <g key={`pane-${p.key}`} data-testid={`desk-pane-${p.key}`} data-empty={drawn ? "false" : "true"}>
              <line x1={0} y1={top} x2={plotW} y2={top} style={{ stroke: "var(--line-2)" }} strokeWidth={0.6} />
              <text x={2} y={top + 9} style={{ fontFamily: "var(--mono)", fontSize: 7.4, letterSpacing: "0.1em", fill: "var(--cp-ink-3)" }}>{p.title.toUpperCase()}</text>
              {!drawn ? (
                <text data-testid={`desk-pane-${p.key}-empty`} x={2} y={top + paneH / 2 + 6} style={{ fontSize: 8.5, fill: "var(--cp-ink-3)" }}>{p.empty ?? "No data for these bars."}</text>
              ) : (
                <>
                  {hasNeg && <line x1={0} y1={zero} x2={plotW} y2={zero} style={{ stroke: "var(--line-3)" }} strokeWidth={0.6} />}
                  {series.map((sr, si) => sr.map((b, i) => {
                    if (b.value == null || !Number.isFinite(b.value) || i >= n) return null;
                    const h = Math.max(0.8, (Math.abs(b.value) / maxAbs) * half);
                    const bx = x(i) - bodyW / 2 + si * subW;
                    return <rect key={`pb-${p.key}-${si}-${i}`} data-testid={`desk-pane-${p.key}-bar`} data-series={si} data-i={i} data-value={b.value}
                      x={bx} y={b.value >= 0 ? zero - h : zero} width={Math.max(0.8, subW - 0.4)} height={h} style={{ fill: b.color }} opacity={active != null && i !== active ? 0.7 : 1} />;
                  }))}
                  {p.line && lv.length > 0 && (
                    <>
                      <path data-testid={`desk-pane-${p.key}-line`} d={seriesPath(p.line.values.slice(0, n), x, ly)} fill="none" style={{ stroke: p.line.color }} strokeWidth={1.3} />
                      {lastLine != null && <text x={plotW + 4} y={ly(lastLine) + 3} style={{ ...gutterText, fontSize: font - 0.5, fill: p.line.color }}>{p.line.format(lastLine)}</text>}
                    </>
                  )}
                </>
              )}
            </g>
          );
        })}

        {/* cursor */}
        {active != null && <line x1={x(active)} y1={0} x2={x(active)} y2={H} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />}
      </svg>
    </div>
  );
}

/** One legend key: a short line (solid, or dashed) in the series' colour. */
function LegendKey({ color, dash, children }: { color: string; dash?: string; children: string }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 6 }}>
      <svg width={14} height={6} aria-hidden>
        <line x1={0} y1={3} x2={14} y2={3} style={{ stroke: color }} strokeWidth={2} strokeDasharray={dash} />
      </svg>
      {children}
    </span>
  );
}

const SPAN_WORDS: Record<string, string> = { "1M": "1 month", "3M": "3 months", "6M": "6 months" };

/** The legend under the chart (only the overlays that are drawn), with the span on the right: "DAILY · 3 MONTHS". */
export function CandleLegend({ ema, ema200 = false, vwap, levels, events = 0, words = TRADER_CHART_WORDS, span }: {
  ema: boolean; ema200?: boolean; vwap: boolean; levels: boolean; events?: number; words?: ChartWords; span: string;
}) {
  return (
    <div
      data-testid="desk-chart-legend"
      className="flex flex-wrap items-center"
      style={{ gap: "6px 14px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}
    >
      {ema && <LegendKey color={EMA20}>{words.ema20}</LegendKey>}
      {ema && <LegendKey color={EMA50}>{words.ema50}</LegendKey>}
      {ema200 && <LegendKey color={EMA200} dash="1 2">{words.ema200}</LegendKey>}
      {vwap && <LegendKey color={VWAP} dash="4 2">{words.vwap}</LegendKey>}
      {levels && <LegendKey color={UP} dash="3 3">{words.target}</LegendKey>}
      {levels && <LegendKey color={ENTRY} dash="3 3">{words.entry}</LegendKey>}
      {levels && <LegendKey color={DOWN} dash="3 3">{words.stop}</LegendKey>}
      {events > 0 && (
        <span data-testid="desk-chart-legend-events" className="inline-flex items-center" style={{ gap: 6 }}>
          <svg width={10} height={10} aria-hidden><path d="M 5 1 L 9 5 L 5 9 L 1 5 Z" style={{ fill: EVENT }} /></svg>
          Filing
        </span>
      )}
      <span data-testid="desk-chart-span" style={{ marginLeft: "auto", color: "var(--cp-ink-4)" }}>Daily · {SPAN_WORDS[span] ?? span}</span>
    </div>
  );
}
