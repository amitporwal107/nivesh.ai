/**
 * Strategy Builder — the underlying potential-movement graph (PRD §16.6 A).
 *
 * Observed history is the desk's own candle chart (CandleChart, reused as is) with the trigger,
 * invalidation and first target as its dashed levels. Under it a second pane draws the scenario
 * estimates: only from the numeric inputs passed in (a level or a low-high range per scenario, a
 * horizon in sessions, the forecast origin and the rule or model version). Each scenario is a straight
 * wedge from the last observed close to its range at the horizon; nothing smoother is drawn and no
 * path in between is implied, and the legend and the caption say so. The scenario pane is hatched and
 * labelled "estimate" so it cannot be read as price history. With no scenario inputs there is no pane,
 * only the history, the levels and a note saying so.
 *
 * Nothing is fetched or computed here beyond placing the passed numbers on a scale.
 */
import { useId } from "react";
import { CandleChart, CandleLegend, PLAIN_CHART_WORDS, TRADER_CHART_WORDS } from "../CandleChart";
import type { DailyBar } from "../indicators";
import { fmtDay } from "../../trading/parts";
import { niceTicks, px, rs } from "./strategy-format";

export interface FanZone {
  label: string;
  /** A level (high omitted) or a zone from `low` to `high`. */
  low: number;
  high?: number | null;
}

export interface FanBand {
  /** "conservative", "base" or "optimistic". */
  name: string;
  /** A level (give the same number twice) or a range at the horizon. */
  low: number | null;
  high: number | null;
}

export interface FanScenario {
  /** When the scenarios were made: an ISO date or timestamp. */
  origin: string;
  /** Sessions from the origin to where the ranges apply. */
  horizonSessions: number;
  /** The rule or model that produced them, e.g. "scanner v2". */
  version: string;
  bands: FanBand[];
}

export interface ScenarioFanProps {
  /** Daily candles, oldest first (the Chart tab's bars). */
  bars: DailyBar[];
  name: string;
  trigger?: number | null;
  invalidation?: number | null;
  targets?: FanZone[];
  scenario?: FanScenario | null;
  compact?: boolean;
  persona?: "trader" | "investor";
}

const BAND_STYLE: Record<string, { color: string; dash: string }> = {
  conservative: { color: "var(--amber)", dash: "5 3" },
  base: { color: "var(--cp-indigo)", dash: "" },
  optimistic: { color: "var(--mint)", dash: "2 3" },
};
const OTHER_STYLE = { color: "var(--cp-ink-3)", dash: "1 3" };

export function ScenarioFan({ bars, name, trigger = null, invalidation = null, targets = [], scenario = null, compact = false, persona = "trader" }: ScenarioFanProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const investor = persona === "investor";
  const words = investor ? PLAIN_CHART_WORDS : TRADER_CHART_WORDS;
  if (bars.length === 0) {
    return <div data-testid="fan-empty" role="note" style={{ fontSize: 12.5, color: "var(--cp-ink-3)" }}>No daily candles were supplied, so there is no history to draw.</div>;
  }
  const last = bars[bars.length - 1];
  const bands = (scenario?.bands ?? []).filter((b) => b.low != null && b.high != null) as Array<FanBand & { low: number; high: number }>;
  const dropped = (scenario?.bands ?? []).filter((b) => b.low == null || b.high == null);
  const drawFan = !!scenario && bands.length > 0 && scenario.horizonSessions > 0;
  const originDay = scenario ? scenario.origin.slice(0, 10) : null;
  const mismatch = originDay != null && /^\d{4}-\d{2}-\d{2}$/.test(originDay) && originDay !== last.day;

  const levelsList = [
    trigger != null ? { label: words.entry, value: trigger } : null,
    invalidation != null ? { label: investor ? "Exit if below" : "Invalidation", value: invalidation } : null,
  ].filter((x): x is { label: string; value: number } => x != null);

  // Scenario pane
  const W = compact ? 330 : 540;
  const H = compact ? 150 : 190;
  const left = compact ? 44 : 52;
  const right = compact ? 82 : 110;
  const top = 8;
  const bottom = 22;
  const plotW = W - left - right;
  const plotH = H - top - bottom;
  const font = compact ? 8.5 : 9;
  const vals = [last.close, ...(trigger != null ? [trigger] : []), ...(invalidation != null ? [invalidation] : []),
    ...targets.flatMap((t) => [t.low, t.high ?? t.low]), ...bands.flatMap((b) => [b.low, b.high])];
  const lo0 = Math.min(...vals);
  const hi0 = Math.max(...vals);
  const pad = (hi0 - lo0 || hi0 * 0.02 || 1) * 0.12;
  const lo = lo0 - pad;
  const hi = hi0 + pad;
  const yOf = (v: number) => top + (1 - (v - lo) / (hi - lo)) * plotH;
  const x0 = left;
  const x1 = left + plotW;
  const ticks = niceTicks(lo0, hi0, 4);
  const dg = hi0 - lo0 < 20 ? 1 : 0;

  // Right-hand labels, pushed apart.
  const labels = bands.map((b) => ({ b, y: yOf((b.low + b.high) / 2) })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) labels[i].y = Math.max(labels[i].y, labels[i - 1].y + 22);
  const over = labels.length ? labels[labels.length - 1].y - (top + plotH) : 0;
  if (over > 0) labels.forEach((l) => { l.y -= over; });

  const bandText = (b: FanBand & { low: number; high: number }) => (b.low === b.high ? `${b.name} ${rs(b.low)}` : `${b.name} ${rs(b.low)} to ${rs(b.high)}`);

  return (
    <div data-testid="scenario-fan" className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <CandleChart
        bars={bars}
        name={name}
        compact={compact}
        words={words}
        overlays={{ levels: { entry: trigger, stop: invalidation, target: targets[0]?.low ?? null } }}
      />
      <CandleLegend ema={false} vwap={false} levels={trigger != null || invalidation != null || targets.length > 0} words={words} span={`${bars.length} sessions`} />

      {(levelsList.length > 0 || targets.length > 0) && (
        <ul data-testid="fan-levels" className="m-0 flex flex-col" style={{ gap: 2, paddingLeft: 16, fontSize: 11.5, color: "var(--cp-ink-2)", lineHeight: 1.5 }}>
          {levelsList.map((l) => <li key={l.label}>{l.label} {rs(l.value)}</li>)}
          {targets.map((t) => <li key={t.label}>{t.label} {t.high != null && t.high !== t.low ? `${rs(t.low)} to ${rs(t.high)}` : rs(t.low)}</li>)}
        </ul>
      )}

      {drawFan && scenario ? (
        <>
          <svg
            data-testid="fan-svg"
            viewBox={`0 0 ${W} ${H}`}
            role="img"
            style={{ display: "block", width: "100%", height: "auto", overflow: "visible" }}
            aria-label={`Scenario estimates, not observed prices. From the last close ${rs(last.close)} on ${fmtDay(last.day)}, straight ranges to ${scenario.horizonSessions} sessions ahead: ${bands.map(bandText).join("; ")}. Made ${scenario.origin} by ${scenario.version}.`}
          >
            <defs>
              <pattern id={`est${uid}`} width={6} height={6} patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1={0} y1={0} x2={0} y2={6} style={{ stroke: "var(--cp-ink-3)" }} strokeWidth={1} strokeOpacity={0.28} />
              </pattern>
            </defs>
            <rect x={x0} y={top} width={plotW} height={plotH} style={{ fill: `url(#est${uid})` }} />
            {ticks.map((v) => (
              <g key={v}>
                <line x1={x0} y1={yOf(v)} x2={x1} y2={yOf(v)} style={{ stroke: "var(--line-2)" }} strokeWidth={0.6} />
                <text x={x0 - 4} y={yOf(v) + 3} textAnchor="end" className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>{px(v, dg)}</text>
              </g>
            ))}
            {targets.map((t) => (
              <g key={t.label} data-testid="fan-target">
                <rect x={x0} y={yOf(t.high ?? t.low)} width={plotW} height={Math.max(1.5, Math.abs(yOf(t.low) - yOf(t.high ?? t.low)))} style={{ fill: "var(--mint)" }} fillOpacity={0.14} />
                <line x1={x0} y1={yOf(t.low)} x2={x1} y2={yOf(t.low)} style={{ stroke: "var(--mint)" }} strokeWidth={0.9} strokeDasharray="4 3" />
              </g>
            ))}
            {trigger != null && <line data-testid="fan-trigger" x1={x0} y1={yOf(trigger)} x2={x1} y2={yOf(trigger)} style={{ stroke: "var(--cp-ink-2)" }} strokeWidth={1} strokeDasharray="4 3" />}
            {invalidation != null && <line data-testid="fan-invalidation" x1={x0} y1={yOf(invalidation)} x2={x1} y2={yOf(invalidation)} style={{ stroke: "var(--cp-danger)" }} strokeWidth={1} strokeDasharray="4 3" />}
            {bands.map((b) => {
              const st = BAND_STYLE[b.name] ?? OTHER_STYLE;
              const pts = `${x0},${yOf(last.close)} ${x1},${yOf(b.high)} ${x1},${yOf(b.low)}`;
              return (
                <g key={b.name} data-testid="fan-band" data-name={b.name} data-low={b.low} data-high={b.high}>
                  <polygon points={pts} style={{ fill: st.color, stroke: st.color }} fillOpacity={0.14} strokeWidth={1.2} strokeDasharray={st.dash || undefined} />
                </g>
              );
            })}
            <circle cx={x0} cy={yOf(last.close)} r={3.4} style={{ fill: "var(--cp-ink)" }} />
            {labels.map(({ b, y }) => {
              const st = BAND_STYLE[b.name] ?? OTHER_STYLE;
              return (
                <g key={b.name}>
                  <text x={x1 + 5} y={y} className="cp-num" style={{ fontSize: font, fill: st.color }}>{b.name}</text>
                  <text x={x1 + 5} y={y + 10} className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>{b.low === b.high ? px(b.low, dg) : `${px(b.low, dg)} to ${px(b.high, dg)}`}</text>
                </g>
              );
            })}
            <text x={x0} y={H - 7} className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>Last close</text>
            <text x={x1} y={H - 7} textAnchor="end" className="cp-num" style={{ fontSize: font, fill: "var(--cp-ink-3)" }}>+{scenario.horizonSessions} sessions</text>
          </svg>
          <div data-testid="fan-legend" className="flex flex-wrap items-center" style={{ gap: "6px 14px", fontFamily: "var(--mono)", fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
            <span>Hatched pane: scenario estimate, not observed price</span>
            <span>Straight ranges from the last close, no path between</span>
          </div>
          <p data-testid="fan-caption" className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
            Scenario estimates, not observed prices and not guarantees. Made {scenario.origin.length > 10 ? scenario.origin : fmtDay(scenario.origin)} from the last close {rs(last.close)} ({fmtDay(last.day)}); horizon {scenario.horizonSessions} sessions; {scenario.version}.
            Each range is a straight line from the close to the level or range given for the horizon; the desk draws nothing smoother and implies no path in between.
            {mismatch ? ` The scenarios were made on ${fmtDay(originDay)}, not on the last candle's day.` : ""}
            {dropped.length > 0 ? ` Not drawn, no numbers given: ${dropped.map((d) => d.name).join(", ")}.` : ""}
          </p>
        </>
      ) : (
        <p data-testid="fan-none" role="note" className="m-0" style={{ fontSize: 11.5, lineHeight: 1.5, color: "var(--cp-ink-3)" }}>
          No scenario inputs were supplied (levels or ranges and a horizon), so only the observed history and the levels above are shown. Nothing is projected.
        </p>
      )}
    </div>
  );
}
