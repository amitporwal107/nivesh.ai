/**
 * Strategy Builder — one P&L-versus-underlying-price chart for cash, futures and options (PRD §16.6 B, C, D).
 * Inline SVG, no chart library (house style: CandleChart.tsx).
 *
 * It draws what the payoff calculation returned and recomputes nothing: the expiry payoff
 * (`expiry`, exact at expiry) or the pre-expiry estimate (`pre_expiry`, a model's estimate with
 * its assumptions), net of costs or gross, with each leg's gross line faintly behind when asked.
 * X is the underlying price in INR, Y the position's P&L in INR with a zero line; the area above
 * zero is the profit zone (solid tint), the area below the loss zone (hatched tint), and both are
 * named in words inside the plot. Breakevens, the reference (last close) price, any caller markers
 * (entry, stop, targets) and the response's scenario points are marked and also listed as text under
 * the chart, so nothing is carried by colour or by a label that might not fit.
 *
 * Pointing at the chart (or touching it), or focusing it and pressing the left / right arrow keys
 * (Shift for ten steps, Home / End), prints the price, gross and net P&L and, on the pre-expiry
 * estimate, the Greeks in the line above it; nothing is on hover only.
 *
 * Unbounded ends are labelled with an arrow and words ("Profit unbounded"); max profit and max
 * loss print "Unlimited" when the response's flag says so and "—" when the figure is null.
 */
import { useId, useMemo, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";
import type { PayoffExpiry, PayoffPreExpiry } from "./strategy-contract";
import { DASH, greek, niceTicks, px, rs, rsTick } from "./strategy-format";

const PROFIT = "var(--mint)";
const LOSS = "var(--cp-danger)";
const LINE = "var(--cp-ink)";
const ESTIMATE = "var(--cp-indigo)";
const LEG_STYLES: Array<{ color: string; dash: string }> = [
  { color: "var(--amber)", dash: "5 3" },
  { color: "var(--cp-indigo)", dash: "2 3" },
  { color: "var(--rose)", dash: "7 3 2 3" },
  { color: "var(--cp-ink-3)", dash: "1 3" },
  { color: "var(--mint)", dash: "9 3" },
  { color: "var(--cp-ink-2)", dash: "4 2 1 2" },
];

export type PayoffMode = "expiry" | "pre";
export type PayoffBasis = "net" | "gross";

/** A vertical line the caller wants on the chart: the entry, the stop or invalidation, a target, or any other level. */
export interface PayoffMarker {
  kind: "entry" | "stop" | "target" | "other";
  price: number;
  /** Short, e.g. "Entry" (the price is added). */
  label: string;
}

const MARKER_COLOR: Record<PayoffMarker["kind"], string> = {
  entry: "var(--cp-ink-2)", stop: LOSS, target: PROFIT, other: "var(--cp-ink-3)",
};

export interface PayoffChartProps {
  expiry: PayoffExpiry | null | undefined;
  preExpiry: PayoffPreExpiry | null | undefined;
  /** The underlying's last close. */
  referencePrice: number;
  markers?: PayoffMarker[];
  defaultMode?: PayoffMode;
  defaultBasis?: PayoffBasis;
  defaultShowLegs?: boolean;
  /** The phone chart (330 wide viewBox). */
  compact?: boolean;
  /** Draw dimmed: a newer answer is loading. */
  stale?: boolean;
  /** Wording: investor uses plain labels. */
  persona?: "trader" | "investor";
}

interface Series { grid: number[]; gross: number[]; net: number[] }

function nearestIndex(grid: number[], price: number): number {
  let best = 0;
  let gap = Infinity;
  grid.forEach((g, i) => { const d = Math.abs(g - price); if (d < gap) { gap = d; best = i; } });
  return best;
}

export function PayoffChart({
  expiry, preExpiry, referencePrice, markers = [],
  defaultMode = "expiry", defaultBasis = "net", defaultShowLegs = false, compact = false, stale = false, persona = "trader",
}: PayoffChartProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const investor = persona === "investor";
  const [modeWanted, setMode] = useState<PayoffMode>(defaultMode);
  const [basis, setBasis] = useState<PayoffBasis>(defaultBasis);
  const [showLegs, setShowLegs] = useState(defaultShowLegs);
  const [active, setActive] = useState<number | null>(null);

  // The estimate is usable only when it carries a grid: a requested estimate that could not price a leg has none.
  const preSeries: Series | null = preExpiry && preExpiry.grid && preExpiry.gross && preExpiry.net ? { grid: preExpiry.grid, gross: preExpiry.gross, net: preExpiry.net } : null;
  const mode: PayoffMode = modeWanted === "pre" && preSeries ? "pre" : "expiry";
  const series: Series | null = mode === "pre" && preSeries ? preSeries : expiry ?? null;
  const legsAvailable = mode === "expiry" && !!expiry && expiry.per_leg.length > 1;
  const legsOn = showLegs && legsAvailable;

  const W = compact ? 330 : 540;
  const H = compact ? 220 : 270;
  const left = compact ? 48 : 52;
  const right = 10;
  const bottom = 24;
  const font = compact ? 9.5 : 9;

  const model = useMemo(() => {
    if (!series || series.grid.length < 2) return null;
    const ys = basis === "net" ? series.net : series.gross;
    if (ys.length !== series.grid.length) return null;
    const legYs = legsOn && expiry ? expiry.per_leg.map((l) => l.gross.filter((v): v is number => v != null)) : [];
    const all = [...ys, ...legYs.flat(), 0];
    const lo = Math.min(...all);
    const hi = Math.max(...all);
    const pad = (hi - lo || 1) * 0.1;
    return { ys, lo: lo - (lo < 0 ? pad : 0), hi: hi + (hi > 0 ? pad : 0), x0: series.grid[0], x1: series.grid[series.grid.length - 1] };
  }, [series, basis, legsOn, expiry]);

  if (!series || !model) {
    return (
      <div data-testid="payoff-chart-empty" role="note" style={{ padding: 12, fontSize: 12.5, color: "var(--cp-ink-3)" }}>
        There is no payoff to draw: the calculation returned no price grid.
      </div>
    );
  }

  const { ys, lo, hi, x0, x1 } = model;
  const n = series.grid.length;

  // Marker labels stack in rows above the plot so none overlap.
  const lines: Array<{ key: string; price: number; label: string; color: string; dash: string }> = [
    { key: "ref", price: referencePrice, label: `${investor ? "Now" : "Last"} ${px(referencePrice)}`, color: "var(--cp-ink)", dash: "2 2" },
    ...markers.map((m, i) => ({ key: `m${i}`, price: m.price, label: `${m.label} ${px(m.price)}`, color: MARKER_COLOR[m.kind], dash: "4 3" })),
  ];
  const inRange = (p: number) => p >= x0 && p <= x1;
  const drawn = lines.filter((l) => inRange(l.price)).sort((a, b) => a.price - b.price);
  const rowEnds: number[] = [];
  const plotW = W - left - right;
  const xOf = (p: number) => left + ((p - x0) / (x1 - x0 || 1)) * plotW;
  const placed = drawn.map((l) => {
    const w = l.label.length * (font * 0.6) + 6;
    const start = Math.min(Math.max(xOf(l.price) - w / 2, left), W - right - w);
    let row = rowEnds.findIndex((e) => start > e + 3);
    if (row < 0) { row = rowEnds.length; rowEnds.push(0); }
    rowEnds[row] = start + w;
    return { ...l, row, start, w };
  });
  const rows = Math.max(1, rowEnds.length);
  const top = 6 + rows * 11;
  const plotH = H - top - bottom;
  const yOf = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * plotH;
  const zeroY = yOf(0);

  const pathOf = (grid: number[], vals: Array<number | null>) => {
    let d = "";
    let pen = false;
    vals.forEach((v, i) => {
      if (v == null || !Number.isFinite(v)) { pen = false; return; }
      d += `${pen ? "L" : "M"} ${xOf(grid[i]).toFixed(1)} ${yOf(v).toFixed(1)} `;
      pen = true;
    });
    return d.trim();
  };
  const line = pathOf(series.grid, ys);
  const area = `${line} L ${xOf(x1).toFixed(1)} ${zeroY.toFixed(1)} L ${xOf(x0).toFixed(1)} ${zeroY.toFixed(1)} Z`;

  const yTicks = niceTicks(lo, hi, compact ? 4 : 5);
  const xTicks = niceTicks(x0, x1, compact ? 6 : 7);
  const xDigits = x1 - x0 < 20 ? 1 : 0;
  const hasProfit = Math.max(...ys) > 0;
  const hasLoss = Math.min(...ys) < 0;

  // Unbounded ends (expiry payoff only; the flags are facts about expiry).
  const upRight = ys[n - 1] > ys[n - 2];
  const upLeft = ys[0] > ys[1];
  const dnRight = ys[n - 1] < ys[n - 2];
  const dnLeft = ys[0] < ys[1];
  const ends: Array<{ side: "left" | "right"; profit: boolean }> = [];
  if (mode === "expiry" && expiry) {
    if (expiry.profit_unbounded) {
      if (upRight) ends.push({ side: "right", profit: true });
      if (upLeft) ends.push({ side: "left", profit: true });
    }
    if (expiry.loss_unbounded) {
      if (dnRight) ends.push({ side: "right", profit: false });
      if (dnLeft) ends.push({ side: "left", profit: false });
    }
  }

  const idx = active ?? nearestIndex(series.grid, referencePrice);
  const px_ = series.grid[idx];
  const onMove = (e: PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    if (box.width <= 0) return;
    const at = ((e.clientX - box.left) / box.width) * W;
    const price = x0 + ((at - left) / plotW) * (x1 - x0);
    setActive(nearestIndex(series.grid, price));
  };
  const onKey = (e: KeyboardEvent<SVGSVGElement>) => {
    const step = e.shiftKey ? 10 : 1;
    let next: number | null = null;
    if (e.key === "ArrowLeft") next = idx - step;
    else if (e.key === "ArrowRight") next = idx + step;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = n - 1;
    if (next == null) return;
    e.preventDefault();
    setActive(Math.min(n - 1, Math.max(0, next)));
  };

  const g = preExpiry?.greeks ?? null;

  const maxProfit = expiry ? (expiry.profit_unbounded ? "Unlimited" : expiry.max_profit == null ? DASH : rs(expiry.max_profit, { signed: true })) : DASH;
  const maxLoss = expiry ? (expiry.loss_unbounded ? "Unlimited" : expiry.max_loss == null ? DASH : rs(expiry.max_loss)) : DASH;
  const breakevens = expiry?.breakevens ?? [];
  const scenarios = expiry?.scenarios ?? [];

  const ariaLabel = [
    `${mode === "expiry" ? "Payoff at expiry" : `Pre-expiry estimate for ${preExpiry?.date ?? "the chosen date"}`}, ${basis === "net" ? "net of costs" : "before costs"}:`,
    `${n} points for an underlying price from ${rs(x0)} to ${rs(x1)}.`,
    `Profit ranges to ${rs(Math.max(...ys), { signed: true })} and loss to ${rs(Math.min(...ys))} on this range.`,
    mode === "expiry" ? `Maximum profit (gross) ${maxProfit}. Maximum loss (gross) ${maxLoss}.` : "This is an estimate from a pricing model, not a guarantee.",
    breakevens.length ? `Breakeven (gross) at ${breakevens.map((b) => rs(b)).join(" and ")}.` : "No breakeven on this range.",
    `Reference price ${rs(referencePrice)}.`,
    "Use the left and right arrow keys to read a price.",
  ].join(" ");

  const toggleBtn = (on: boolean, disabled = false): CSSProperties => ({
    padding: "5px 11px", borderRadius: 999, fontSize: 11.5, cursor: disabled ? "not-allowed" : "pointer", whiteSpace: "nowrap", fontFamily: "var(--sans)",
    border: `1px solid ${on ? "var(--mint-line)" : "var(--line-2)"}`, background: on ? "var(--mint-soft)" : "transparent",
    color: disabled ? "var(--cp-ink-4)" : on ? "var(--mint)" : "var(--cp-ink-2)", opacity: disabled ? 0.6 : 1,
  });

  const unavailable = preExpiry?.unavailable ?? [];

  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 8, opacity: stale ? 0.55 : 1, transition: "opacity .15s" }} data-testid="payoff-chart" data-mode={mode} data-basis={basis} data-stale={stale}>
      <div className="flex flex-wrap items-center" style={{ gap: 6 }}>
        <div role="group" aria-label="Payoff view" className="flex flex-wrap" style={{ gap: 6 }}>
          <button type="button" data-testid="payoff-mode-expiry" aria-pressed={mode === "expiry"} onClick={() => setMode("expiry")} style={toggleBtn(mode === "expiry")}>
            {investor ? "At expiry" : "Expiry payoff"}
          </button>
          <button
            type="button" data-testid="payoff-mode-pre" aria-pressed={mode === "pre"} disabled={!preSeries}
            title={preSeries ? undefined : "No pre-expiry estimate in this answer"}
            onClick={() => setMode("pre")} style={toggleBtn(mode === "pre", !preSeries)}
          >
            {investor ? "Before expiry (estimate)" : "Pre-expiry estimate"}
          </button>
        </div>
        <div role="group" aria-label="P&L basis" className="flex" style={{ gap: 6 }}>
          <button type="button" data-testid="payoff-basis-net" aria-pressed={basis === "net"} onClick={() => setBasis("net")} style={toggleBtn(basis === "net")}>{investor ? "After costs" : "Net"}</button>
          <button type="button" data-testid="payoff-basis-gross" aria-pressed={basis === "gross"} onClick={() => setBasis("gross")} style={toggleBtn(basis === "gross")}>{investor ? "Before costs" : "Gross"}</button>
        </div>
        <button
          type="button" data-testid="payoff-legs-toggle" aria-pressed={legsOn} disabled={!legsAvailable}
          title={legsAvailable ? undefined : mode === "pre" ? "Leg lines are drawn on the expiry payoff only" : "A single leg has no separate lines"}
          onClick={() => setShowLegs((v) => !v)} style={toggleBtn(legsOn, !legsAvailable)}
        >
          {investor ? "Show each leg" : "Per-leg lines"}
        </button>
      </div>

      {!preSeries && (
        <p data-testid="payoff-pre-reasons" className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          Pre-expiry estimate unavailable.{unavailable.length === 0 && (preExpiry ? " The calculation gave no estimate and no reason." : " None was requested: set an evaluation date in the what-if controls.")}
        </p>
      )}
      {unavailable.length > 0 && (
        <ul data-testid="payoff-pre-unavailable" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 11.5, lineHeight: 1.5, color: "var(--amber)" }}>
          {unavailable.map((u) => <li key={u.leg}>Leg {u.leg + 1} has no estimate: {u.reason}</li>)}
        </ul>
      )}

      <span data-testid="payoff-readout" aria-live="polite" className="cp-num" style={{ fontSize: compact ? 10 : 10.5, color: "var(--cp-ink-2)", lineHeight: 1.6 }}>
        {investor ? "Stock at" : "Underlying"} {rs(px_)}
        {" · "}{investor ? "Before costs" : "Gross"} <span data-testid="payoff-readout-gross">{rs(series.gross[idx], { signed: true })}</span>
        {" · "}{investor ? "After costs" : "Net"} <span data-testid="payoff-readout-net">{rs(series.net[idx], { signed: true })}</span>
        {mode === "pre" && g && (
          <span data-testid="payoff-readout-greeks">
            {" · "}Greeks at {rs(referencePrice)}: Δ {greek(g.delta)} · Γ {greek(g.gamma)} · Θ {greek(g.theta)}/day · Vega {greek(g.vega)} · ρ {greek(g.rho)}
          </span>
        )}
        {mode === "pre" && !g && <span data-testid="payoff-readout-greeks">{" · "}Greeks: — (no time value left on the evaluation date, or a leg is unpriced)</span>}
      </span>

      <svg
        data-testid="payoff-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        tabIndex={0}
        aria-label={ariaLabel}
        style={{ display: "block", width: "100%", height: "auto", touchAction: "pan-y", overflow: "visible" }}
        onPointerMove={onMove}
        onPointerDown={onMove}
        onPointerLeave={() => setActive(null)}
        onKeyDown={onKey}
        onBlur={() => setActive(null)}
      >
        <defs>
          <pattern id={`hatch${uid}`} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1={0} y1={0} x2={0} y2={6} style={{ stroke: LOSS }} strokeWidth={1.4} strokeOpacity={0.35} />
          </pattern>
          <clipPath id={`up${uid}`}><rect x={left} y={top} width={plotW} height={Math.max(0, zeroY - top)} /></clipPath>
          <clipPath id={`dn${uid}`}><rect x={left} y={zeroY} width={plotW} height={Math.max(0, top + plotH - zeroY)} /></clipPath>
        </defs>

        {yTicks.map((v) => (
          <g key={`y${v}`}>
            <line x1={left} y1={yOf(v)} x2={W - right} y2={yOf(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={0.6} />
            <text x={left - 4} y={yOf(v) + 3} textAnchor="end" className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>{rsTick(v)}</text>
          </g>
        ))}
        {xTicks.map((v) => (
          <text key={`x${v}`} x={xOf(v)} y={H - 8} textAnchor={xOf(v) > W - right - 14 ? "end" : "middle"} className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>{px(v, xDigits)}</text>
        ))}

        {/* profit zone (tint) and loss zone (hatched tint) */}
        <path data-testid="payoff-profit-area" d={area} clipPath={`url(#up${uid})`} style={{ fill: PROFIT }} fillOpacity={0.16} />
        <path data-testid="payoff-loss-area" d={area} clipPath={`url(#dn${uid})`} style={{ fill: `url(#hatch${uid})` }} />
        <path d={area} clipPath={`url(#dn${uid})`} style={{ fill: LOSS }} fillOpacity={0.1} />
        {hasProfit && <text data-testid="payoff-zone-profit" x={left + 5} y={top + 11} className="cp-num" style={{ fontSize: font, fill: PROFIT, letterSpacing: "0.1em" }}>PROFIT</text>}
        {hasLoss && <text data-testid="payoff-zone-loss" x={left + 5} y={top + plotH - 5} className="cp-num" style={{ fontSize: font, fill: LOSS, letterSpacing: "0.1em" }}>LOSS</text>}

        {/* zero line */}
        <line data-testid="payoff-zero" x1={left} y1={zeroY} x2={W - right} y2={zeroY} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} />

        {/* max profit / max loss (expiry facts) */}
        {mode === "expiry" && basis === "gross" && expiry && !expiry.profit_unbounded && expiry.max_profit != null && expiry.max_profit > 0 && expiry.max_profit <= hi && (
          <line data-testid="payoff-maxprofit-line" x1={left} y1={yOf(expiry.max_profit)} x2={W - right} y2={yOf(expiry.max_profit)} style={{ stroke: PROFIT }} strokeWidth={0.8} strokeDasharray="1 3" />
        )}
        {mode === "expiry" && basis === "gross" && expiry && !expiry.loss_unbounded && expiry.max_loss != null && expiry.max_loss < 0 && expiry.max_loss >= lo && (
          <line data-testid="payoff-maxloss-line" x1={left} y1={yOf(expiry.max_loss)} x2={W - right} y2={yOf(expiry.max_loss)} style={{ stroke: LOSS }} strokeWidth={0.8} strokeDasharray="1 3" />
        )}

        {/* per-leg gross lines, faint, each with its own dash */}
        {legsOn && expiry && expiry.per_leg.map((l, i) => {
          const st = LEG_STYLES[i % LEG_STYLES.length];
          return <path key={l.index} data-testid={`payoff-leg-line-${l.index}`} d={pathOf(expiry.grid, l.gross)} fill="none" style={{ stroke: st.color }} strokeWidth={1.1} strokeDasharray={st.dash} opacity={0.7} />;
        })}

        {/* the payoff */}
        <path data-testid="payoff-line" d={line} fill="none" style={{ stroke: mode === "pre" ? ESTIMATE : LINE }} strokeWidth={2} strokeDasharray={mode === "pre" ? "6 3" : undefined} strokeLinejoin="round" />

        {/* reference and caller markers */}
        {placed.map((l) => (
          <g key={l.key} data-testid={`payoff-marker-${l.key}`} data-price={l.price}>
            <line x1={xOf(l.price)} y1={top} x2={xOf(l.price)} y2={top + plotH} style={{ stroke: l.color }} strokeWidth={1} strokeDasharray={l.dash} />
            <text x={l.start + l.w / 2} y={top - 4 - l.row * 11} textAnchor="middle" className="cp-num" style={{ fontSize: font, fill: l.color }}>{l.label}</text>
          </g>
        ))}

        {/* breakevens: a ring on the zero line, value beside it */}
        {mode === "expiry" && breakevens.filter(inRange).map((b, i) => (
          <g key={`be${b}`} data-testid="payoff-breakeven" data-price={b}>
            <circle cx={xOf(b)} cy={zeroY} r={3.6} style={{ fill: "var(--bg-1)", stroke: LINE }} strokeWidth={1.6} />
            <text x={xOf(b)} y={zeroY + (i % 2 === 0 ? 14 : -8)} textAnchor="middle" className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink)" }}>BE {px(b, xDigits)}</text>
          </g>
        ))}

        {/* scenario points from the response */}
        {mode === "expiry" && scenarios.filter((s) => inRange(s.underlying_price)).map((s) => {
          const v = basis === "net" ? s.net : s.gross;
          if (v == null) return null;
          return (
            <g key={s.name} data-testid="payoff-scenario-point" data-name={s.name}>
              <path d={`M ${xOf(s.underlying_price)} ${yOf(v) - 4.5} L ${xOf(s.underlying_price) + 4.5} ${yOf(v)} L ${xOf(s.underlying_price)} ${yOf(v) + 4.5} L ${xOf(s.underlying_price) - 4.5} ${yOf(v)} Z`} style={{ fill: "var(--amber)", stroke: "var(--bg-1)" }} strokeWidth={1} />
            </g>
          );
        })}

        {/* unbounded ends */}
        {ends.map((e) => {
          const y = yOf(e.side === "right" ? ys[n - 1] : ys[0]);
          const x = e.side === "right" ? W - right : left;
          const dir = e.profit ? -1 : 1;
          const ty = Math.min(top + plotH - 4, Math.max(top + 10, y + dir * 12));
          const color = e.profit ? PROFIT : LOSS;
          const arrow = e.profit ? (e.side === "right" ? "↗" : "↖") : (e.side === "right" ? "↘" : "↙");
          return (
            <g key={`${e.side}${e.profit}`} data-testid={e.profit ? "payoff-unbounded-profit" : "payoff-unbounded-loss"}>
              <circle cx={x} cy={y} r={2.6} style={{ fill: color }} />
              <text x={e.side === "right" ? x - 2 : x + 2} y={ty} textAnchor={e.side === "right" ? "end" : "start"} className="cp-num" style={{ fontSize: font, fill: color }}>
                {e.profit ? "Profit unbounded" : "Loss unbounded"} {arrow}
              </text>
            </g>
          );
        })}

        {/* cursor */}
        {active != null && (
          <g data-testid="payoff-cursor">
            <line x1={xOf(px_)} y1={top} x2={xOf(px_)} y2={top + plotH} style={{ stroke: "var(--line-3)" }} strokeWidth={1} />
            <circle cx={xOf(px_)} cy={yOf(ys[idx])} r={3.4} style={{ fill: LINE, stroke: "var(--bg-1)" }} strokeWidth={1.2} />
          </g>
        )}
      </svg>

      <div data-testid="payoff-legend" className="flex flex-wrap items-center" style={{ gap: "6px 14px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
        <LegendKey color={mode === "pre" ? ESTIMATE : LINE} dash={mode === "pre" ? "6 3" : undefined}>
          {mode === "pre" ? "Estimate (model)" : "Payoff at expiry"} · {basis === "net" ? "after costs" : "before costs"}
        </LegendKey>
        <span className="inline-flex items-center" style={{ gap: 6 }}><span aria-hidden style={{ width: 10, height: 10, background: "color-mix(in srgb, var(--mint) 25%, transparent)", border: "1px solid var(--mint)" }} />Profit zone</span>
        <span className="inline-flex items-center" style={{ gap: 6 }}><svg width={10} height={10} aria-hidden><rect width={10} height={10} style={{ fill: `color-mix(in srgb, ${LOSS} 22%, transparent)`, stroke: LOSS }} /><path d="M0 10 L10 0" style={{ stroke: LOSS }} strokeWidth={1} /></svg>Loss zone</span>
        {legsOn && expiry && expiry.per_leg.map((l, i) => (
          <LegendKey key={l.index} color={LEG_STYLES[i % LEG_STYLES.length].color} dash={LEG_STYLES[i % LEG_STYLES.length].dash}>{l.label}</LegendKey>
        ))}
      </div>

      <dl data-testid="payoff-facts" className="m-0 grid" style={{ gridTemplateColumns: "repeat(auto-fit,minmax(110px,1fr))", gap: "6px 12px", fontSize: 11.5 }}>
        <Fact k="Max profit (gross)" id="maxprofit" v={maxProfit} note={expiry?.profit_unbounded ? "no upper limit" : undefined} />
        <Fact k="Max loss (gross)" id="maxloss" v={maxLoss} note={expiry?.loss_unbounded ? "no lower limit" : undefined} />
        <Fact k={investor ? "Break-even (gross)" : "Breakeven (gross)"} id="breakeven" v={breakevens.length ? breakevens.map((b) => rs(b)).join(" · ") : DASH} />
        <Fact k={investor ? "Stock now" : "Reference"} id="reference" v={rs(referencePrice)} note="last close" />
      </dl>
      {(markers.length > 0 || scenarios.length > 0) && (
        <ul data-testid="payoff-levels" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 11.5, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
          {markers.map((m, i) => (
            <li key={`m${i}`} data-testid="payoff-level">{m.label} {rs(m.price)}{inRange(m.price) ? "" : " (outside the plotted range)"}</li>
          ))}
          {scenarios.map((s) => (
            <li key={s.name} data-testid="payoff-scenario-row">Scenario {s.name}: underlying {rs(s.underlying_price)} → gross {rs(s.gross, { signed: true })}, net {rs(s.net, { signed: true })}</li>
          ))}
        </ul>
      )}
      {mode === "pre" && preExpiry && <PreNote pre={preExpiry} />}
    </div>
  );
}

function Fact({ k, id, v, note }: { k: string; id: string; v: string; note?: string }) {
  return (
    <div className="flex min-w-0 flex-col" style={{ gap: 2 }}>
      <dt className="cp-eyebrow" style={{ margin: 0 }}>{k}</dt>
      <dd data-testid={`payoff-fact-${id}`} className="cp-num m-0" style={{ fontSize: 13, color: "var(--cp-ink)", overflowWrap: "anywhere" }}>
        {v}{note && <span style={{ color: "var(--cp-ink-3)", fontSize: 10.5 }}> · {note}</span>}
      </dd>
    </div>
  );
}

function LegendKey({ color, dash, children }: { color: string; dash?: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center" style={{ gap: 6 }}>
      <svg width={16} height={6} aria-hidden><line x1={0} y1={3} x2={16} y2={3} style={{ stroke: color }} strokeWidth={2} strokeDasharray={dash} /></svg>
      {children}
    </span>
  );
}

/** The model and its assumptions, from the answer: rate and its source, forward basis, IV shift, as-of date, each option leg's days and volatility. */
function PreNote({ pre }: { pre: PayoffPreExpiry }) {
  const a = pre.assumptions as Record<string, unknown>;
  const text = (v: unknown) => (v == null || v === "" ? DASH : String(v));
  const legs = Array.isArray(a.legs) ? (a.legs as Array<Record<string, unknown>>) : [];
  return (
    <p data-testid="payoff-pre-note" className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
      Estimate for {pre.date} from {pre.model}, not a guarantee. Rate {text(a.rate_pct)}% ({text(a.rate_source)}); forward basis: {text(a.forward_basis)}; volatility shift {text(a.iv_shift_pct)} points; prices as of {text(a.as_of)}.
      {legs.map((l) => ` Leg ${Number(l.leg) + 1}: ${text(l.time_to_expiry_days)} days to expiry, IV ${l.iv_pct == null ? DASH : `${l.iv_pct}%`} (${text(l.iv_source)}).`).join("")}
    </p>
  );
}
