/**
 * Daily candlestick chart for the Top movers view: price panel, volume strip and one row per event lane, all
 * drawn on ONE x-scale. Bars are spaced by INDEX, not by calendar date, so a weekend never opens a gap that
 * the lanes would then disagree with: an event whose bar_index is k is centred on exactly the x of bars[k].
 * `barX` below is the single function every layer calls; there is deliberately no second x computation.
 *
 * Plain SVG, no charting library. Up/down candles differ by fill (up = hollow body, down = solid body) as well
 * as colour, and each carries a <title>, so the direction survives colour-blindness and print. Colours come
 * from --mv-* custom properties (the stylesheet owns the palette); the literals are only fallbacks.
 */
import { useMemo, useState } from "react";

export type ChartBar = { t: string; o: number|null; h: number|null; l: number|null; c: number|null; v: number };
export type ChartEvent = {
  id: string; date: string; title: string; sub?: string|null; lane: string; glyph: string;
  type_label: string; kind: string; kind_note?: string|null; bar_index: number|null;
  flags: Array<{label: string; tone: string}>;
  metrics: { re: number|null; gap: number|null; vol_pre: number|null; vol_post: number|null; flip: boolean } | null;
};
type Props = {
  bars: ChartBar[];
  market: Array<number|null>;
  marketName: string;
  marketAvailable: boolean;
  events: ChartEvent[];
  lanes: Array<{ key: string; label: string }>;
  sessionIndex: number;
  modelMarker?: { state: string; label: string } | null;
  selectedEventId: string|null;
  onSelectEvent: (id: string|null) => void;
};
type Hover = { kind: "bar"; i: number } | { kind: "evt"; id: string; x: number; y: number } | null;

const W = 720, PAD_L = 100, PAD_R = 10, PRICE_T = 10, PRICE_H = 190, VOL_T = 206, VOL_H = 38;
const LANE_T = 252, LANE_H = 26, TIP_W = 210;
const UP = "var(--mv-up, #2f9e6e)", DOWN = "var(--mv-down, #d1495b)", INK = "var(--mv-ink, #5b6472)";
const MKT = "var(--mv-market, #4c6ef5)", RULE = "var(--mv-rule, #e1a21b)", BG = "var(--mv-bg, #ffffff)";
const GRID = "var(--mv-grid, rgba(128,128,128,0.25))";

const pct = (v: number|null|undefined, d = 2) => (v == null ? "n/a" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`);
const mult = (v: number|null|undefined) => (v == null ? "n/a" : `${v.toFixed(2)}x`);
const px = (v: number|null|undefined) => (v == null ? "n/a" : v.toFixed(2));
const fin = (v: number|null): v is number => v != null && Number.isFinite(v);

export function MoversChart(props: Props) {
  const { bars, market, marketName, marketAvailable, events, lanes, sessionIndex, modelMarker,
          selectedEventId, onSelectEvent } = props;
  const [hover, setHover] = useState<Hover>(null);
  const n = bars.length;
  const plotW = W - PAD_L - PAD_R;
  // The ONE x-scale: centre of slot i. Candles, overlay, volume, session rule and event markers all use it.
  const barX = (i: number) => PAD_L + ((i + 0.5) / Math.max(1, n)) * plotW;
  const slot = plotW / Math.max(1, n);

  const geom = useMemo(() => {
    const highs = bars.map((b) => b.h).filter(fin), lows = bars.map((b) => b.l).filter(fin);
    if (!highs.length || !lows.length) return null;
    const hi = Math.max(...highs), lo = Math.min(...lows), span = hi - lo || 1;
    const y = (v: number) => PRICE_T + PRICE_H - ((v - lo) / span) * PRICE_H;
    const maxV = Math.max(1, ...bars.map((b) => b.v || 0));
    // Market overlay: indexed to its own first non-null value, mapped onto the price range. Null runs break the path.
    let d = "";
    const base = market.find(fin);
    const anchor = bars.map((b) => b.c).find(fin) ?? (hi + lo) / 2; // index 100 sits at the first close
    if (marketAvailable && base) {
      let pen = false;
      market.slice(0, n).forEach((m, i) => {
        if (!fin(m)) { pen = false; return; }
        const v = anchor * (m / base);
        d += `${pen ? "L" : "M"}${barX(i).toFixed(1)} ${y(Math.min(hi, Math.max(lo, v))).toFixed(1)} `;
        pen = true;
      });
    }
    return { hi, lo, y, maxV, d };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bars, market, marketAvailable]);

  if (!n || !geom) {
    return <div className="mv-chart-empty" data-testid="mv-chart" role="img" aria-label="No price history">No price history for this stock.</div>;
  }
  const { y, maxV, d: mktPath } = geom;

  const laneKeys = new Set(lanes.map((l) => l.key));
  const placed = events.filter((e) => e.bar_index != null && e.bar_index >= 0 && e.bar_index < n && laneKeys.has(e.lane));
  const overflow = events.filter((e) => !placed.includes(e));
  const whyOff = (e: ChartEvent) =>
    e.bar_index == null ? "no matching trading day in this window"
      : e.bar_index < 0 || e.bar_index >= n ? "outside the plotted price window"
      : `lane "${e.lane}" is not shown`;
  const H = LANE_T + lanes.length * LANE_H + 18;
  const first = bars[0].t, last = bars[n - 1].t;
  const label = `Daily candles ${first} to ${last}, ${n} sessions, ${events.length} event${events.length === 1 ? "" : "s"}`;

  const pick = (id: string) => onSelectEvent(selectedEventId === id ? null : id);
  const evById = (id: string) => events.find((e) => e.id === id);

  const tipLines = (): { x: number; y: number; lines: string[] } | null => {
    if (!hover) return null;
    if (hover.kind === "bar") {
      const b = bars[hover.i], prev = hover.i > 0 ? bars[hover.i - 1].c : null;
      const chg = fin(b.c) && fin(prev) && prev !== 0 ? b.c / prev - 1 : null;
      return { x: barX(hover.i), y: PRICE_T + 4, lines: [
        b.t, `O ${px(b.o)}  H ${px(b.h)}`, `L ${px(b.l)}  C ${px(b.c)}`,
        `Volume ${b.v.toLocaleString("en-IN")}`, `${pct(chg)} vs previous close`] };
    }
    const e = evById(hover.id);
    if (!e) return null;
    const m = e.metrics;
    const lines = [e.kind, e.title, ...(e.kind_note ? [e.kind_note] : []),
      ...(e.flags.length ? [e.flags.map((f) => f.label).join(" / ")] : []),
      ...(m ? [`Reaction ${pct(m.re)}  Gap ${pct(m.gap)}`,
               `Volume before ${mult(m.vol_pre)}  after ${mult(m.vol_post)}`,
               `Reversed direction: ${m.flip ? "yes" : "no"}`] : [])];
    return { x: hover.x, y: hover.y, lines: lines.map((l) => (l.length > 38 ? `${l.slice(0, 37)}…` : l)) };
  };
  const tip = tipLines();

  return (
    <div className="mv-chart" data-testid="mv-chart" role="img" aria-label={label}>
      <svg className="mv-chart-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="xMidYMid meet"
           width="100%" style={{ display: "block", maxWidth: "100%", height: "auto" }}
           onMouseLeave={() => setHover(null)}>
        {[0, 0.5, 1].map((f) => {
          const v = geom.lo + (geom.hi - geom.lo) * f;
          return (
            <g key={f}>
              <line x1={PAD_L} x2={W - PAD_R} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth="0.6" />
              <text x={PAD_L - 6} y={y(v) + 3} fontSize="9" textAnchor="end" fill={INK} fontFamily="var(--mono, monospace)">{px(v)}</text>
            </g>
          );
        })}
        {bars.map((b, i) => {
          const x = barX(i), bw = Math.max(1.5, slot * 0.62);
          const volH = ((b.v || 0) / maxV) * VOL_H;
          const dirn = fin(b.o) && fin(b.c) ? (b.c >= b.o ? "up" : "down") : "n/a";
          const col = dirn === "down" ? DOWN : UP;
          return (
            <g key={`${b.t}-${i}`} data-testid={`mv-candle-${i}`} data-dir={dirn} aria-label={`${b.t} ${dirn} candle`}
               onMouseEnter={() => setHover({ kind: "bar", i })}>
              <title>{`${b.t}: ${dirn === "up" ? "up (close at or above open)" : dirn === "down" ? "down (close below open)" : "no price"}`}</title>
              <rect x={x - slot / 2} y={PRICE_T} width={slot} height={PRICE_H} fill="transparent" />
              {fin(b.h) && fin(b.l) && <line x1={x} x2={x} y1={y(b.h)} y2={y(b.l)} stroke={col} strokeWidth="1" />}
              {fin(b.o) && fin(b.c) && (
                <rect x={x - bw / 2} y={Math.min(y(b.o), y(b.c))} width={bw}
                      height={Math.max(1, Math.abs(y(b.c) - y(b.o)))}
                      fill={dirn === "up" ? BG : col} stroke={col} strokeWidth="1" />
              )}
              <rect x={x - Math.max(1, slot * 0.3)} y={VOL_T + VOL_H - volH} width={Math.max(1, slot * 0.6)}
                    height={volH} fill={col} opacity="0.55" />
            </g>
          );
        })}
        {marketAvailable && mktPath && (
          <g>
            <path data-testid="mv-overlay-market" d={mktPath} fill="none" stroke={MKT} strokeWidth="2"
                  strokeLinejoin="round" pointerEvents="none"><title>{marketName}</title></path>
            <text x={W - PAD_R} y={PRICE_T + 9} fontSize="9" textAnchor="end" fill={MKT}>{marketName} (rescaled)</text>
          </g>
        )}
        <text x={PAD_L - 6} y={VOL_T + 12} fontSize="9" textAnchor="end" fill={INK}>Volume</text>
        {sessionIndex >= 0 && sessionIndex < n && (
          <rect data-testid="mv-session-marker" x={barX(sessionIndex) - 0.75} width="1.5" y={PRICE_T}
                height={LANE_T + lanes.length * LANE_H - PRICE_T} fill={RULE} opacity="0.85"
                pointerEvents="none"><title>Move session</title></rect>
        )}
        {lanes.map((ln, li) => {
          const top = LANE_T + li * LANE_H, cy = top + LANE_H / 2;
          return (
            <g key={ln.key} data-testid={`mv-lane-${ln.key}`}>
              <line x1={PAD_L} x2={W - PAD_R} y1={top + LANE_H} y2={top + LANE_H} stroke={GRID} strokeWidth="0.5" />
              <text x={PAD_L - 6} y={cy + 3} fontSize="9" textAnchor="end" fill={INK}>{ln.label}</text>
              {ln.key === "mdl" && modelMarker && sessionIndex >= 0 && sessionIndex < n && (
                <g data-testid="mv-model-marker" data-state={modelMarker.state}>
                  <title>{modelMarker.label}</title>
                  <circle cx={barX(sessionIndex)} cy={cy} r="6" fill={BG} stroke={RULE} strokeWidth="1.5" />
                  <text x={barX(sessionIndex) + 10} y={cy + 3} fontSize="9" fill={INK}>{modelMarker.label}</text>
                </g>
              )}
              {placed.filter((e) => e.lane === ln.key).map((e) => {
                const ex = barX(e.bar_index as number);
                return (
                  <foreignObject key={e.id} x={ex - 11} y={cy - 11} width="22" height="22" style={{ overflow: "visible" }}>
                    <button type="button" data-testid={`mv-evt-${e.id}`} className="mv-evt"
                            aria-label={`${e.type_label}: ${e.title}`}
                            aria-pressed={selectedEventId === e.id ? true : undefined}
                            onClick={() => pick(e.id)}
                            onMouseEnter={() => setHover({ kind: "evt", id: e.id, x: ex, y: cy - 6 })}
                            onFocus={() => setHover({ kind: "evt", id: e.id, x: ex, y: cy - 6 })}
                            onBlur={() => setHover(null)}
                            style={{ width: 22, height: 22, padding: 0, lineHeight: "20px", fontSize: 11, textAlign: "center",
                                     cursor: "pointer", borderRadius: 11, color: INK, background: BG,
                                     border: `${selectedEventId === e.id ? 2 : 1}px solid ${selectedEventId === e.id ? RULE : INK}` }}>
                      {e.glyph}
                    </button>
                  </foreignObject>
                );
              })}
            </g>
          );
        })}
        <text x={PAD_L} y={H - 4} fontSize="9" fill={INK}>{first}</text>
        <text x={W - PAD_R} y={H - 4} fontSize="9" textAnchor="end" fill={INK}>{last}</text>
        {tip && (() => {
          const h = tip.lines.length * 13 + 10;
          const tx = tip.x + 12 + TIP_W > W - 2 ? tip.x - 12 - TIP_W : tip.x + 12;
          const ty = Math.min(Math.max(2, tip.y - h / 2), H - h - 2);
          return (
            <g data-testid="mv-tooltip" pointerEvents="none">
              <rect x={Math.max(2, tx)} y={ty} width={TIP_W} height={h} rx="4" fill={BG} stroke={INK} strokeWidth="0.8" />
              {tip.lines.map((l, k) => (
                <text key={k} x={Math.max(2, tx) + 8} y={ty + 15 + k * 13} fontSize="10" fill={INK}
                      fontWeight={k === 0 ? 700 : 400}>{l}</text>
              ))}
            </g>
          );
        })()}
      </svg>
      {events.length > 0 && (
        <div className="mv-evt-overflow">
          <p className="mv-note">
            Every event in this window ({events.length}){overflow.length > 0 ? `, ${overflow.length} of them not on the timeline` : ""}:
          </p>
          <ul data-testid="mv-evt-list">
            {events.map((e) => {
              const off = overflow.some((x) => x.id === e.id);
              return (
                <li key={e.id}>
                  {e.date} · {e.type_label}: {e.title}
                  {off ? ` — not plotted: ${whyOff(e)}` : ""}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

export default MoversChart;
