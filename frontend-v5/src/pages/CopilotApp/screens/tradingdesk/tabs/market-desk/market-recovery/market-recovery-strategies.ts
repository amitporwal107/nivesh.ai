/**
 * Market Desk › Market Recovery — one stock's strategies with downside protection (contract: docs/market_recovery/DESIGN.md §8;
 * backend routes/market_recovery.py).
 *
 *   GET /api/market-recovery/strategies/{symbol}   asked only when the stock's detail is open
 *
 * kind "options": the five strategies the owner listed (4 Nov) for one lot on the chosen expiry, priced at the end-of-day close
 * (else the settlement price): protective put, bull call spread, collar, bull put credit spread, put ratio backspread. Each
 * carries its legs, net premium, maximum profit (or unlimited) and loss, breakevens, reward : risk, scenarios at the plan's
 * levels, the Strategy Builder's checks and its payoff at expiry. All five are always sent; a failing one has status "fails"
 * (or "unavailable") and says why.
 * kind "index_hedge": the stock has no stock options, so one Nifty put lot sized by the stock's beta.
 *
 * Typed errors {detail: {code, message}}: 404 not_scored, 503 chain_unavailable, 503 data_unavailable — read with
 * recoveryProblem(), whose message is the server's own sentence. Every field is parsed defensively: a missing number is null
 * (shown as "—"), never 0. Nothing is computed here: every figure is the server's.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { num } from "../../../desk-data";
import { MR_PATH } from "./market-recovery-data";

export const strategiesPath = (symbol: string) => `${MR_PATH}/strategies/${encodeURIComponent(symbol)}`;

type Raw = Record<string, unknown>;
const rec = (v: unknown): Raw => (v && typeof v === "object" && !Array.isArray(v) ? (v as Raw) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string | null => (typeof v === "string" && v.trim() ? v.trim() : null);
const bool = (v: unknown): boolean | null => (typeof v === "boolean" ? v : null);
const strs = (v: unknown): string[] => arr(v).map(str).filter((s): s is string => s !== null);
const nums = (v: unknown): number[] => arr(v).map(num).filter((n): n is number => n !== null);

// ── types ────────────────────────────────────────────────────────────────────────────────────────────────────────────

export type StrategyStatus = "passes" | "fails" | "unavailable";

export interface Leg {
  action: string;                 // "Buy" | "Sell" (the owner's words for this page)
  instrument: string;             // "Shares" | "Call" | "Put"
  strike: number | null;
  lots: number | null;
  units: number | null;
  price: number | null;
  priceBasis: string | null;      // "close", or the settlement price ("settlement"; "settle" in the design's example)
  oi: number | null;
  volume: number | null;
  flags: string[];
}
export interface StrategyCheck { id: string; label: string; pass: boolean | null; detail: string | null }
export interface StrategyScenario { label: string; price: number | null; pnl: number | null; pnlUnhedged: number | null }
export interface Strategy {
  key: string;
  label: string;
  bestWhen: string | null;
  status: string;                 // StrategyStatus, or an unknown value kept as sent
  why: string | null;
  legs: Leg[];
  netPremium: number | null;      // whole position; debit < 0, credit > 0
  netPremiumPerShare: number | null;
  outlay: number | null;
  maxProfit: number | null;
  profitUnbounded: boolean;
  maxLoss: number | null;
  maxLossWithCosts: number | null;
  breakevens: number[];
  rewardRisk: number | null;
  costsRoundTrip: number | null;
  scenarios: StrategyScenario[];
  checks: StrategyCheck[];
  payoff: Array<[number, number]>;
}
export interface HedgeScenario { label: string; niftyMovePct: number | null; putPnl: number | null; stockLoss: number | null }
export interface IndexHedge {
  index: string | null;
  expiry: string | null;
  daysToExpiry: number | null;
  lotSize: number | null;
  spot: number | null;
  beta: number | null;
  putStrike: number | null;
  premium: number | null;
  priceBasis: string | null;
  oi: number | null;
  volume: number | null;
  costPerLot: number | null;
  hedgedValue: number | null;
  costPct: number | null;
  fallUsedPct: number | null;
  scenarios: HedgeScenario[];
  checks: StrategyCheck[];
  caveat: string | null;
  status: string | null;          // the backend's verdict ("passes" | "fails" | "unavailable"), when sent
  why: string | null;
  sizing: string | null;          // the backend's one-sentence sizing basis
}
export interface StrategyPlanLevels { entryLow: number | null; close: number | null; stopLoss: number | null; target1: number | null; target2: number | null }
export interface RecoveryStrategies {
  symbol: string | null;
  kind: string | null;            // "options" | "index_hedge"
  asOf: string | null;
  expiry: string | null;
  daysToExpiry: number | null;
  lotSize: number | null;
  spot: number | null;
  plan: StrategyPlanLevels | null;
  strategies: Strategy[];
  indexHedge: IndexHedge | null;
  notes: string[];
  sources: Array<{ what: string | null; source: string | null; asOf: string | null }>;
  warnings: string[];
}

// ── parsing ──────────────────────────────────────────────────────────────────────────────────────────────────────────

function parseChecks(v: unknown): StrategyCheck[] {
  return arr(v).flatMap((c) => {
    const o = rec(c);
    const id = str(o.id) ?? str(o.label), label = str(o.label) ?? str(o.id);
    return id && label ? [{ id, label, pass: bool(o.pass), detail: str(o.detail) }] : [];
  });
}

function parseLeg(v: unknown): Leg[] {
  const o = rec(v);
  const action = str(o.action), instrument = str(o.instrument);
  if (!action || !instrument) return [];
  return [{
    action, instrument, strike: num(o.strike), lots: num(o.lots), units: num(o.units), price: num(o.price),
    priceBasis: str(o.price_basis), oi: num(o.oi), volume: num(o.volume), flags: strs(o.flags),
  }];
}

function parseStrategy(v: unknown): Strategy[] {
  const o = rec(v);
  const key = str(o.key);
  if (!key) return [];
  const payoff = arr(o.payoff).flatMap((p): Array<[number, number]> => {
    const pair = arr(p);
    const x = num(pair[0]), y = num(pair[1]);
    return x != null && y != null ? [[x, y]] : [];
  }).sort((a, b) => a[0] - b[0]);
  return [{
    key, label: str(o.label) ?? key, bestWhen: str(o.best_when), status: str(o.status) ?? "unavailable", why: str(o.why),
    legs: arr(o.legs).flatMap(parseLeg),
    netPremium: num(o.net_premium), netPremiumPerShare: num(o.net_premium_per_share), outlay: num(o.outlay),
    maxProfit: num(o.max_profit), profitUnbounded: bool(o.profit_unbounded) ?? false,
    maxLoss: num(o.max_loss), maxLossWithCosts: num(o.max_loss_with_costs),
    breakevens: nums(o.breakevens), rewardRisk: num(o.reward_risk), costsRoundTrip: num(o.costs_round_trip),
    scenarios: arr(o.scenarios).flatMap((s) => {
      const q = rec(s);
      const label = str(q.label);
      return label ? [{ label, price: num(q.price), pnl: num(q.pnl), pnlUnhedged: num(q.pnl_unhedged) }] : [];
    }),
    checks: parseChecks(o.checks),
    payoff,
  }];
}

function parseIndexHedge(v: unknown): IndexHedge | null {
  const o = rec(v);
  if (!Object.keys(o).length) return null;
  return {
    index: str(o.index), expiry: str(o.expiry), daysToExpiry: num(o.days_to_expiry), lotSize: num(o.lot_size), spot: num(o.spot),
    beta: num(o.beta), putStrike: num(o.put_strike), premium: num(o.premium), priceBasis: str(o.price_basis), oi: num(o.oi),
    volume: num(o.volume), costPerLot: num(o.cost_per_lot), hedgedValue: num(o.hedged_value), costPct: num(o.cost_pct),
    fallUsedPct: num(o.fall_used_pct),
    scenarios: arr(o.scenarios).flatMap((s) => {
      const q = rec(s);
      const label = str(q.label);
      return label ? [{ label, niftyMovePct: num(q.nifty_move_pct), putPnl: num(q.put_pnl), stockLoss: num(q.stock_loss) }] : [];
    }),
    checks: parseChecks(o.checks),
    caveat: str(o.caveat),
    status: str(o.status),
    why: str(o.why),
    sizing: str(o.sizing),
  };
}

export function parseRecoveryStrategies(v: unknown): RecoveryStrategies {
  const d = rec(v);
  if (!Object.keys(d).length) throw new ApiError("contract_drift", "The strategies answer was not in the expected form.");
  const p = rec(d.plan);
  return {
    symbol: str(d.symbol), kind: str(d.kind), asOf: str(d.as_of), expiry: str(d.expiry), daysToExpiry: num(d.days_to_expiry),
    lotSize: num(d.lot_size), spot: num(d.spot),
    plan: Object.keys(p).length
      ? { entryLow: num(p.entry_low), close: num(p.close), stopLoss: num(p.stop_loss), target1: num(p.target_1), target2: num(p.target_2) }
      : null,
    strategies: arr(d.strategies).flatMap(parseStrategy),
    indexHedge: parseIndexHedge(d.index_hedge),
    notes: strs(d.notes),
    sources: arr(d.sources).flatMap((s) => {
      const o = rec(s);
      const what = str(o.what), source = str(o.source);
      return what || source ? [{ what, source, asOf: str(o.as_of) }] : [];
    }),
    warnings: strs(d.warnings),
  };
}

// ── hook ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

/** A 4xx or a contract drift is the server's settled answer: asking again changes nothing. */
const noRetry4xx = (count: number, e: unknown) =>
  !(e instanceof ApiError && (e.kind === "contract_drift" || (e.status != null && e.status >= 400 && e.status < 500))) && count < 1;

/** One stock's strategies; asked only while `enabled` (the stock's detail is open). End-of-day prices: no polling. */
export function useRecoveryStrategies(symbol: string, enabled = true) {
  return useQuery<RecoveryStrategies>({
    queryKey: ["copilot", "desk", "market-recovery", "strategies", symbol],
    enabled: enabled && !!symbol,
    queryFn: async ({ signal }) => {
      // Each answer reads the stock's option chain (and the Nifty chain for an index hedge) on the server.
      const res = await http({ path: strategiesPath(symbol), signal, timeoutMs: 60_000, noRetry: true });
      return parseRecoveryStrategies(res.data);
    },
    staleTime: 10 * 60_000,
    refetchOnWindowFocus: false,
    retry: noRetry4xx,
  });
}
