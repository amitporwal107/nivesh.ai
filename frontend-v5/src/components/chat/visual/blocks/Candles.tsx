/**
 * `candles`: the desk's own CandleChart (screens/tradingdesk/CandleChart.tsx), unchanged. The contract's levels map to
 * its extra lines (a dashed line, the price in the gutter and the name at the left) and its band to the chart's shaded
 * band. The chart is drawn compact when its box is narrow, so the gutter text stays legible on a phone. Under it, the
 * same numbers as text: the history the candles cover, each level and the band.
 */
import { useState } from "react";
import { CandleChart } from "@/pages/CopilotApp/screens/tradingdesk/CandleChart";
import type { DailyBar, Series } from "@/pages/CopilotApp/screens/tradingdesk/indicators";
import { useBoxWidth } from "@/pages/CopilotApp/screens/tradingdesk/decision/PlanPayoff";
import type { CandlesBlock } from "../schema";
import { fmtDay, fmtPrice } from "../format";
import { quiet, type BlockProps } from "./common";

/** What each level kind is called and drawn in (house tokens). */
export const LEVEL_STYLE: Record<string, { name: string; color: string }> = {
  support: { name: "Support", color: "var(--mint)" },
  resistance: { name: "Resistance", color: "var(--cp-danger)" },
  entry: { name: "Entry", color: "var(--cp-ink-2)" },
  stop: { name: "Stop", color: "var(--cp-danger)" },
  target: { name: "Target", color: "var(--mint)" },
  wall_call: { name: "Call OI wall", color: "var(--rose)" },
  wall_put: { name: "Put OI wall", color: "var(--cp-indigo)" },
  max_pain: { name: "Max pain", color: "var(--amber)" },
};
const levelStyle = (kind: string) => LEVEL_STYLE[kind] ?? { name: kind.replace(/_/g, " "), color: "var(--cp-ink-3)" };

const EMA = [
  { key: "ema20", label: "EMA 20", color: "var(--cp-indigo)", dash: undefined },
  { key: "ema50", label: "EMA 50", color: "var(--amber)", dash: undefined },
  { key: "ema200", label: "EMA 200", color: "var(--cp-ink-3)", dash: "1 2" },
] as const;

export function CandlesView({ b }: BlockProps<CandlesBlock>) {
  const [box, setBox] = useState<HTMLDivElement | null>(null);
  const width = useBoxWidth(box);
  const n = b.bars.length;
  const bars: DailyBar[] = b.bars.map((x) => ({ day: x.d, open: x.o, high: x.h, low: x.l, close: x.c, volume: x.v ?? 0 }));
  const fit = (s?: Array<number | null>): Series | undefined => (s && s.length ? s.slice(0, n) : undefined);
  const overlays = { ema20: fit(b.overlays?.ema20), ema50: fit(b.overlays?.ema50), ema200: fit(b.overlays?.ema200) };
  const levels = (b.levels ?? []).map((l, i) => ({ ...l, key: `${l.kind}-${i}`, name: l.label || levelStyle(l.kind).name, color: levelStyle(l.kind).color }));
  const band = b.band && b.band.low < b.band.high ? b.band : null;
  const last = b.bars[n - 1];
  const drawnEma = EMA.filter((e) => overlays[e.key]?.some((v) => v != null));
  const compact = width != null && width < 480;
  return (
    <div data-testid="va-candles" data-symbol={b.symbol} className="flex min-w-0 flex-col" style={{ gap: 8 }}>
      <div ref={setBox} className="min-w-0">
        <CandleChart
          bars={bars}
          name={b.symbol}
          compact={compact}
          overlays={overlays}
          extras={{
            lines: levels.map((l) => ({ key: l.key, label: l.name, value: l.price, color: l.color })),
            band: band ? { low: band.low, high: band.high, label: band.label || "Band" } : null,
            lineNames: true,
          }}
        />
      </div>
      <div className="flex flex-wrap items-center" style={{ gap: "4px 14px", fontFamily: "var(--mono)", fontSize: 10, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--cp-ink-3)" }}>
        {drawnEma.map((e) => (
          <span key={e.key} data-testid={`va-candles-legend-${e.key}`} className="inline-flex items-center" style={{ gap: 6 }}>
            <svg width={14} height={6} aria-hidden><line x1={0} y1={3} x2={14} y2={3} style={{ stroke: e.color }} strokeWidth={2} strokeDasharray={e.dash} /></svg>
            {e.label}
          </span>
        ))}
        {band && (
          <span className="inline-flex items-center" style={{ gap: 6 }}>
            <span aria-hidden style={{ width: 14, height: 8, background: "color-mix(in srgb, var(--cp-indigo) 22%, transparent)", border: "1px solid color-mix(in srgb, var(--cp-indigo) 40%, transparent)" }} />
            Shaded band
          </span>
        )}
      </div>
      <span data-testid="va-candles-history" style={quiet}>
        History: {n} daily candles of {b.symbol}, {fmtDay(b.bars[0].d)} to {fmtDay(last.d)}; last close {fmtPrice(last.c)}.
      </span>
      {(levels.length > 0 || band) && (
        <ul data-testid="va-candles-levels" className="m-0 flex list-none flex-wrap p-0" style={{ gap: "4px 14px", fontSize: 12, lineHeight: 1.5, color: "var(--cp-ink-2)" }}>
          {levels.map((l) => (
            <li key={l.key} data-testid="va-level" data-kind={l.kind} data-price={l.price} className="inline-flex items-center" style={{ gap: 6 }}>
              <svg width={14} height={6} aria-hidden><line x1={0} y1={3} x2={14} y2={3} style={{ stroke: l.color }} strokeWidth={2} strokeDasharray="3 3" /></svg>
              <span>{l.name}</span> <span className="cp-num" data-testid="va-level-price">{fmtPrice(l.price)}</span>
            </li>
          ))}
          {band && (
            <li data-testid="va-band" data-low={band.low} data-high={band.high}>
              {band.label || "Band"}: <span className="cp-num" data-testid="va-band-range">{fmtPrice(band.low)} – {fmtPrice(band.high)}</span>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
