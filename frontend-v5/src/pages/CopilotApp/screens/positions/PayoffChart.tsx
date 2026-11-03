/**
 * A group's P&L against the underlying's price: at expiry (the payoff) and today (Black-76 at each leg's own
 * implied volatility), with the current price, the user's stop and target and the breakevens marked. The points come
 * from the server (`analytics.curve`: [[price, expiry P&L, today P&L], …]); nothing is worked out here. Gross figures.
 */
import { useId } from "react";
import { fmtINR, fmtNum } from "../../components/ui";

const W = 640;
const H = 220;
const PAD = { l: 64, r: 12, t: 12, b: 26 };

export interface PayoffChartProps {
  curve: Array<Array<number | null>>;
  spot: number | null;
  stop?: number | null;
  target?: number | null;
  breakevens?: Array<number | null>;
  testId?: string;
}

export function PayoffChart({ curve, spot, stop, target, breakevens = [], testId = "positions-payoff" }: PayoffChartProps) {
  const titleId = useId();
  const pts = curve.filter((p) => p[0] != null && p[1] != null) as Array<[number, number, number | null]>;
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p[0]);
  const ys = pts.flatMap((p) => [p[1], p[2]]).filter((v): v is number => v != null);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
  const sx = (x: number) => PAD.l + ((x - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r);
  const sy = (y: number) => PAD.t + (1 - (y - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b);
  const line = (i: 1 | 2) => {
    const seg = pts.filter((p) => p[i] != null);
    return seg.length > 1 ? seg.map((p, k) => `${k ? "L" : "M"}${sx(p[0]).toFixed(1)},${sy(p[i] as number).toFixed(1)}`).join(" ") : null;
  };
  const expiry = line(1);
  const today = line(2);
  const marker = (x: number | null | undefined, color: string, label: string, kind: string) =>
    x != null && x >= x0 && x <= x1 ? (
      <g key={`${kind}-${x}`} data-testid={`${testId}-${kind}`} data-value={x}>
        <line x1={sx(x)} x2={sx(x)} y1={PAD.t} y2={H - PAD.b} stroke={color} strokeDasharray="4 4" strokeWidth={1} />
        <text x={sx(x) + 4} y={PAD.t + 10} fontSize={10} fill={color} fontFamily="var(--mono)">{label}</text>
      </g>
    ) : null;
  return (
    <figure className="m-0 flex flex-col" style={{ gap: 6 }} data-testid={testId}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-labelledby={titleId} style={{ display: "block", height: "auto" }}>
        <title id={titleId}>P&L against the underlying price, at expiry and today</title>
        <line x1={PAD.l} x2={W - PAD.r} y1={sy(0)} y2={sy(0)} stroke="var(--cp-line)" strokeWidth={1} />
        {[y0, 0, y1].filter((v, i, a) => a.indexOf(v) === i).map((v) => (
          <text key={v} x={PAD.l - 6} y={sy(v) + 3} fontSize={10} textAnchor="end" fill="var(--cp-ink-3)" fontFamily="var(--mono)">
            {fmtINR(v, { compact: true, signed: v !== 0 })}
          </text>
        ))}
        {[x0, x1].map((v) => (
          <text key={v} x={sx(v)} y={H - 8} fontSize={10} textAnchor={v === x0 ? "start" : "end"} fill="var(--cp-ink-3)" fontFamily="var(--mono)">
            {fmtNum(v, 0)}
          </text>
        ))}
        {expiry && <path d={expiry} fill="none" stroke="var(--cp-ink-2)" strokeWidth={1.5} data-testid={`${testId}-expiry`} />}
        {today && <path d={today} fill="none" stroke="var(--mint)" strokeWidth={2} data-testid={`${testId}-today`} />}
        {marker(spot, "var(--cp-ink)", "Now", "spot")}
        {marker(stop, "var(--cp-danger)", "Stop", "stop")}
        {marker(target, "var(--mint)", "Target", "target")}
        {breakevens.map((b) => marker(b, "var(--amber)", "BE", "breakeven"))}
      </svg>
      <figcaption className="cp-mono-note">
        Grey: at expiry · Green: today{today ? "" : " (not available: an option leg has no implied volatility)"} · gross, before charges
      </figcaption>
    </figure>
  );
}
