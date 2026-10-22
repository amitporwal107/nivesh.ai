/**
 * Options payoff at expiry — exact arithmetic on legs the user enters. No
 * prices, volatility or dates are assumed here.
 *
 *   P&L(S) = Σ over legs  (buy ? +1 : −1) × lots × lotSize × (intrinsic(S) − premium)
 *   intrinsic = max(S − strike, 0) for a call, max(strike − S, 0) for a put
 *
 * The payoff is piecewise linear with kinks only at the strikes, so the best
 * and worst outcomes sit at S = 0, at a strike, or run away along the tail
 * above the highest strike. That makes max profit, max loss and breakevens
 * closed-form; nothing is sampled.
 */
export type Side = "buy" | "sell";
export type OptionType = "CE" | "PE";

export interface Leg {
  side: Side;
  type: OptionType;
  strike: number;
  /** Premium per unit of the underlying. */
  premium: number;
  lots: number;
}

export interface Payoff {
  /** Rupees. Positive = net credit received, negative = net debit paid. */
  netPremium: number;
  /** Best P&L at expiry, in rupees. null = unlimited. */
  maxProfit: number | null;
  /** Worst loss at expiry as a positive number of rupees (0 when no outcome loses). null = unlimited. */
  maxLoss: number | null;
  /** Underlying prices at expiry where P&L crosses zero, ascending. */
  breakevens: number[];
  /** The exact curve over `domain`: the two ends and every strike between them. */
  points: Array<{ s: number; pnl: number }>;
  domain: [number, number];
}

const EPS = 1e-6;
const zero = (x: number) => Math.abs(x) < EPS;
const dir = (l: Leg) => (l.side === "buy" ? 1 : -1);

export function pnlAt(legs: Leg[], lotSize: number, s: number): number {
  return legs.reduce((a, l) => a + dir(l) * l.lots * lotSize * (Math.max(l.type === "CE" ? s - l.strike : l.strike - s, 0) - l.premium), 0);
}

export function analysePayoff(legs: Leg[], lotSize: number): Payoff {
  const strikes = [...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b);
  const top = strikes[strikes.length - 1];
  // Above the highest strike only calls still move: rupees gained per point.
  const tailSlope = legs.reduce((a, l) => a + (l.type === "CE" ? dir(l) * l.lots * lotSize : 0), 0);

  const knots = [0, ...strikes];
  const vals = knots.map((s) => pnlAt(legs, lotSize, s));
  const best = Math.max(...vals);
  const worst = Math.min(...vals);

  const breakevens: number[] = [];
  const add = (x: number) => {
    const r = Math.round(x * 100) / 100;
    if (!breakevens.some((b) => Math.abs(b - r) < 0.005)) breakevens.push(r);
  };
  for (let i = 0; i < knots.length - 1; i++) {
    const a = vals[i];
    const b = vals[i + 1];
    if (zero(a) && zero(b)) continue; // flat at zero is a range, not a crossing
    if (zero(a)) add(knots[i]);
    else if (!zero(b) && a * b < 0) add(knots[i] + ((knots[i + 1] - knots[i]) * -a) / (b - a));
  }
  const last = vals[vals.length - 1];
  if (zero(last)) {
    if (!zero(tailSlope)) add(top);
  } else if (!zero(tailSlope) && -last / tailSlope > 0) {
    add(top - last / tailSlope);
  }
  breakevens.sort((a, b) => a - b);

  const marks = [...strikes, ...breakevens];
  const lo0 = Math.min(...marks);
  const hi0 = Math.max(...marks);
  const pad = hi0 > lo0 ? (hi0 - lo0) * 0.6 : hi0 * 0.1;
  const domain: [number, number] = [Math.max(0, lo0 - pad), hi0 + pad];
  const xs = [domain[0], ...strikes.filter((k) => k > domain[0] && k < domain[1]), domain[1]];

  return {
    netPremium: legs.reduce((a, l) => a - dir(l) * l.premium * l.lots * lotSize, 0),
    maxProfit: tailSlope > EPS ? null : best,
    maxLoss: tailSlope < -EPS ? null : Math.max(0, -worst),
    breakevens,
    points: xs.map((s) => ({ s, pnl: pnlAt(legs, lotSize, s) })),
    domain,
  };
}

// ── ready-made structures ────────────────────────────────────────────────

export type MarketView = "Bullish" | "Bearish" | "Neutral" | "Volatile";
export const MARKET_VIEWS: MarketView[] = ["Bullish", "Bearish", "Neutral", "Volatile"];

export interface LegTemplate {
  side: Side;
  type: OptionType;
  lots: number;
  /** Strike steps away from the money. Only the order matters; no strike is implied. */
  offset: number;
}

export interface Structure {
  name: string;
  legs: LegTemplate[];
}

const leg = (side: Side, type: OptionType, offset: number, lots = 1): LegTemplate => ({ side, type, lots, offset });

export const STRUCTURES: Record<MarketView, Structure[]> = {
  Bullish: [
    { name: "Buy call", legs: [leg("buy", "CE", 0)] },
    { name: "Sell put", legs: [leg("sell", "PE", 0)] },
    { name: "Bull call spread", legs: [leg("buy", "CE", 0), leg("sell", "CE", 4)] },
    { name: "Bull put spread", legs: [leg("sell", "PE", 0), leg("buy", "PE", -3)] },
    { name: "Call ratio back spread", legs: [leg("sell", "CE", 0), leg("buy", "CE", 3, 2)] },
    { name: "Call butterfly", legs: [leg("buy", "CE", 0), leg("sell", "CE", 2, 2), leg("buy", "CE", 4)] },
  ],
  Bearish: [
    { name: "Buy put", legs: [leg("buy", "PE", 0)] },
    { name: "Sell call", legs: [leg("sell", "CE", 0)] },
    { name: "Bear put spread", legs: [leg("buy", "PE", 0), leg("sell", "PE", -4)] },
    { name: "Bear call spread", legs: [leg("sell", "CE", 0), leg("buy", "CE", 3)] },
  ],
  Neutral: [
    { name: "Short straddle", legs: [leg("sell", "CE", 0), leg("sell", "PE", 0)] },
    { name: "Short strangle", legs: [leg("sell", "CE", 3), leg("sell", "PE", -3)] },
    { name: "Iron condor", legs: [leg("sell", "CE", 3), leg("buy", "CE", 5), leg("sell", "PE", -3), leg("buy", "PE", -5)] },
    { name: "Iron butterfly", legs: [leg("sell", "CE", 0), leg("sell", "PE", 0), leg("buy", "CE", 3), leg("buy", "PE", -3)] },
  ],
  Volatile: [
    { name: "Long straddle", legs: [leg("buy", "CE", 0), leg("buy", "PE", 0)] },
    { name: "Long strangle", legs: [leg("buy", "CE", 3), leg("buy", "PE", -3)] },
  ],
};

/** Where a leg's strike sits relative to the others — shown as the strike input's hint. */
export function strikeHint(structure: Structure, t: LegTemplate): string {
  if (t.offset === 0) return "At the money";
  const same = [...new Set(structure.legs.map((l) => l.offset).filter((o) => Math.sign(o) === Math.sign(t.offset)))].sort((a, b) => Math.abs(a) - Math.abs(b));
  const further = same.indexOf(t.offset) > 0;
  if (t.offset > 0) return further ? "Higher still" : "Higher strike";
  return further ? "Lower still" : "Lower strike";
}

/**
 * Schematic shape of a structure for its picker tile (a 64 × 32 polyline).
 * Drawn from the leg layout alone with no premium, so it shows the shape of
 * the payoff and nothing about its size or where it crosses zero.
 */
export function shapePoints(structure: Structure): string {
  const legs: Leg[] = structure.legs.map((t) => ({ side: t.side, type: t.type, lots: t.lots, strike: 10 + t.offset, premium: 0 }));
  const xs = [3, ...[...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b), 17];
  const ys = xs.map((x) => pnlAt(legs, 1, x));
  const lo = Math.min(...ys);
  const span = Math.max(...ys) - lo || 1;
  return xs.map((x, i) => `${(((x - 3) / 14) * 64).toFixed(1)},${(30 - ((ys[i] - lo) / span) * 28).toFixed(1)}`).join(" ");
}
