/**
 * Model figures for the strategy builder's legs. Both use the loaded chain's
 * Black-76 estimates (trading/fno.ts; backend/services/option_pricing.py), so
 * both are model estimates from end-of-day prices, not market quotes.
 *
 * Net Greeks
 *   Σ over legs  (buy ? +1 : −1) × lots × lotSize × the Greek of the contract
 *   at the leg's strike and side. A contract's Greek is the route's figure per
 *   unit at its own end-of-day implied volatility; it does not follow a premium
 *   the user types. If any leg's contract has none, there is no net figure.
 *
 * Chance of profit
 *   The risk-neutral probability that the legs' P&L at expiry is above zero,
 *   with the underlying at expiry lognormal around the chain's forward F at one
 *   volatility σ (the chain's ATM implied volatility), T = days to expiry ÷ 365:
 *
 *     S = F × exp(−σ²T/2 + σ√T × Z),  Z standard normal
 *     P(S ≤ x) = N( [ln(x/F) + σ²T/2] / (σ√T) )
 *
 *   P&L at expiry is a straight line between strikes (trading/payoff.ts), so
 *   the prices where it is above zero are a few ranges with exact ends, and the
 *   chance is the sum of P(S ≤ high) − P(S ≤ low) over them. It is a model
 *   probability: one volatility for every strike (no skew), and risk-neutral,
 *   which is how options are priced and not how often trades have worked.
 */
import { sideAt, type FnoChain } from "./fno";
import { pnlAt, type Leg } from "./payoff";

const EPS = 1e-6;
const DAYS_PER_YEAR = 365;

/**
 * N(x), the standard normal distribution function. Abramowitz & Stegun
 * 26.2.17: absolute error below 7.5e-8, far inside a chance shown to 0.1%.
 */
export function normCdf(x: number): number {
  const a = Math.abs(x);
  const t = 1 / (1 + 0.2316419 * a);
  const poly = t * (0.31938153 + t * (-0.356563782 + t * (1.781477937 + t * (-1.821255978 + t * 1.330274429))));
  const upper = 1 - (Math.exp((-a * a) / 2) / Math.sqrt(2 * Math.PI)) * poly;
  return x >= 0 ? upper : 1 - upper;
}

/** The underlying prices at expiry where the legs make money, as [low, high] ranges; high is Infinity for an open top. */
export function profitRanges(legs: Leg[], lotSize: number): Array<[number, number]> {
  const strikes = [...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b);
  const knots = [0, ...strikes];
  const vals = knots.map((s) => pnlAt(legs, lotSize, s));
  const out: Array<[number, number]> = [];
  // Between two strikes the P&L is a straight line: all of it, one end of it, or none of it is above zero.
  for (let i = 0; i < knots.length - 1; i++) {
    const [a, b, va, vb] = [knots[i], knots[i + 1], vals[i], vals[i + 1]];
    const cross = a + ((b - a) * -va) / (vb - va);
    if (va > EPS && vb > EPS) out.push([a, b]);
    else if (va > EPS) out.push([a, cross]);
    else if (vb > EPS) out.push([cross, b]);
  }
  // Above the highest strike only calls still move: rupees gained per point.
  const top = knots[knots.length - 1];
  const last = vals[vals.length - 1];
  const slope = legs.reduce((sum, l) => sum + (l.type === "CE" ? (l.side === "buy" ? 1 : -1) * l.lots * lotSize : 0), 0);
  if (last > EPS) out.push([top, slope < -EPS ? top - last / slope : Infinity]);
  else if (slope > EPS) out.push([top - last / slope, Infinity]);
  return out;
}

/**
 * Chance of profit as a fraction (0–1), or null when the chain gives no
 * forward, no ATM implied volatility or no time to expiry to work it from.
 */
export function chanceOfProfit(legs: Leg[], lotSize: number, forward: number | null | undefined, atmIvPct: number | null | undefined, days: number | null | undefined): number | null {
  if (!legs.length || forward == null || atmIvPct == null || days == null) return null;
  if (!(forward > 0) || !(atmIvPct > 0) || !(days > 0)) return null;
  const spread = (atmIvPct / 100) * Math.sqrt(days / DAYS_PER_YEAR);
  const below = (x: number) => (x <= 0 ? 0 : x === Infinity ? 1 : normCdf((Math.log(x / forward) + (spread * spread) / 2) / spread));
  const p = profitRanges(legs, lotSize).reduce((sum, [lo, hi]) => sum + below(hi) - below(lo), 0);
  return Math.min(1, Math.max(0, p));
}

export interface NetGreeks {
  /** Rupees gained per one-point rise in the forward. */
  delta: number;
  /** Change in `delta` per one-point rise in the forward. */
  gamma: number;
  /** Rupees gained over one calendar day, forward and volatility unchanged. */
  theta: number;
  /** Rupees gained per one-point rise in implied volatility. */
  vega: number;
}

/** The legs' Greeks added up, or the legs whose contract has no model estimate in the chain. */
export function netGreeks(chain: FnoChain, legs: Leg[], lotSize: number): { net: NetGreeks; missing: [] } | { net: null; missing: Leg[] } {
  const net: NetGreeks = { delta: 0, gamma: 0, theta: 0, vega: 0 };
  const missing: Leg[] = [];
  for (const l of legs) {
    const c = sideAt(chain, l.type, l.strike);
    if (c?.delta == null || c.gamma == null || c.theta == null || c.vega == null) {
      missing.push(l);
      continue;
    }
    const size = (l.side === "buy" ? 1 : -1) * l.lots * lotSize;
    net.delta += size * c.delta;
    net.gamma += size * c.gamma;
    net.theta += size * c.theta;
    net.vega += size * c.vega;
  }
  return missing.length ? { net: null, missing } : { net, missing: [] };
}
