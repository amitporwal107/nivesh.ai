/**
 * The strategy builder's result: the payoff curve at expiry and the four
 * figures worked out from the legs the user typed (trading/payoff.ts).
 *
 * The curve is exact: the payoff is a straight line between strikes, so the
 * polyline through the ends of the range and every strike is the payoff itself.
 */
import { Tiles, fmtINR, fmtNum, type TileItem } from "../../components/ui";
import type { Payoff } from "./payoff";

/** An index level or strike: no decimals unless it has them ("22,150", "22,524.95"). */
export const fmtLevel = (n: number) => fmtNum(n, Number.isInteger(n) ? 0 : 2);

function PayoffChart({ payoff, spot, spotLabel }: { payoff: Payoff; spot: number | null; spotLabel: string }) {
  const [x0, x1] = payoff.domain;
  const ys = payoff.points.map((p) => p.pnl);
  const lo = Math.min(0, ...ys);
  const hi = Math.max(0, ...ys);
  const X = (s: number) => ((s - x0) / (x1 - x0 || 1)) * 600;
  const Y = (v: number) => 190 - ((v - lo) / (hi - lo || 1)) * 180;
  // The spot, drawn only when it falls inside the range the legs span.
  const mark = spot != null && spot > x0 && spot < x1 ? spot : null;
  return (
    <>
      <svg
        data-testid="optlab-payoff-chart"
        role="img"
        aria-label={`Payoff at expiry between ${fmtLevel(x0)} and ${fmtLevel(x1)}`}
        viewBox="0 0 600 200"
        preserveAspectRatio="none"
        style={{ width: "100%", height: 200, display: "block" }}
      >
        <line x1="0" y1={Y(0)} x2="600" y2={Y(0)} stroke="var(--line-3)" vectorEffect="non-scaling-stroke" />
        {mark != null && <line x1={X(mark)} y1="0" x2={X(mark)} y2="200" stroke="var(--cp-ink-4)" strokeDasharray="2 4" vectorEffect="non-scaling-stroke" />}
        <polyline
          points={payoff.points.map((p) => `${X(p.s).toFixed(1)},${Y(p.pnl).toFixed(1)}`).join(" ")}
          fill="none"
          stroke="var(--mint)"
          strokeWidth="2.2"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="cp-num flex justify-between" style={{ gap: 8, fontSize: 10, color: "var(--cp-ink-3)" }}>
        <span>{fmtLevel(x0)}</span>
        {mark != null && <span data-testid="optlab-chart-spot">{spotLabel} {fmtNum(mark, 2)}</span>}
        <span>{fmtLevel(x1)}</span>
      </div>
    </>
  );
}

export function PayoffResult({ payoff, lotSize, spot, spotLabel = "SPOT", underlying }: {
  payoff: Payoff;
  lotSize: number;
  /** The underlying's spot (the end-of-day chain's, else the markets feed's), or null when there is none. */
  spot: number | null;
  /** How the marked spot is captioned, e.g. "END-OF-DAY SPOT" when it comes from the chain. */
  spotLabel?: string;
  /** Name for the breakeven caption; null when the legs are for something without a quote. */
  underlying: string | null;
}) {
  const summary: TileItem[] = [
    { k: "Max profit", v: <span data-testid="optlab-max-profit">{payoff.maxProfit == null ? "Unlimited" : fmtINR(payoff.maxProfit)}</span>, s: "At expiry", tone: "mint" },
    { k: "Max loss", v: <span data-testid="optlab-max-loss">{payoff.maxLoss == null ? "Unlimited" : fmtINR(payoff.maxLoss)}</span>, s: "At expiry", tone: "danger" },
    { k: "Breakeven", v: <span data-testid="optlab-breakevens">{payoff.breakevens.length ? payoff.breakevens.map(fmtLevel).join(" · ") : "—"}</span>, s: `${underlying ?? "Underlying"} at expiry` },
    { k: payoff.netPremium >= 0 ? "Net credit" : "Net debit", v: <span data-testid="optlab-net-premium">{fmtINR(Math.abs(payoff.netPremium))}</span>, s: "Premium" },
  ];
  return (
    <>
      <div className="cp-card flex flex-col" style={{ gap: 8, padding: 16 }}>
        <div className="flex flex-wrap justify-between" style={{ gap: 8 }}>
          <span className="cp-eyebrow">Payoff · 1 lot = {fmtNum(lotSize)}</span>
          <span className="cp-num" style={{ fontSize: 10, color: "var(--mint)" }}>— AT EXPIRY</span>
        </div>
        <PayoffChart payoff={payoff} spot={spot} spotLabel={spotLabel} />
      </div>
      <Tiles items={summary} min={120} />
    </>
  );
}
