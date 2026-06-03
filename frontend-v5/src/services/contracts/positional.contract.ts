/**
 * Pro Trader Module — Zod contracts for basket + simulate API.
 */
import { z } from "zod";

// ── Hedge ─────────────────────────────────────────────────────────────────
export const HedgeC = z.object({
  put_strike:  z.number(),
  expiry:      z.string(),
  put_close:   z.number(),
  lot_size:    z.number().int(),
  cost_rs:     z.number(),
  cost_pct:    z.number(),
  hedge_type:  z.enum(["ATM_PUT", "NIFTY_PE_PROXY"]),
}).nullable();

// ── Basket position ───────────────────────────────────────────────────────
export const BasketItemC = z.object({
  symbol:               z.string(),
  stage:                z.string().nullable().optional(),
  conviction_verdict:   z.string().nullable().optional(),
  readiness:            z.string().nullable().optional(),
  live_price:           z.number().nullable().optional(),
  entry_price:          z.number(),
  stoploss:             z.number(),
  target_price:         z.number(),
  risk_reward:          z.number(),
  horizon_days_min:     z.number().int().nullable().optional(),
  horizon_days_max:     z.number().int().nullable().optional(),
  reasons:              z.array(z.string()).optional(),
  qty:                  z.number().int(),
  allocated_rs:         z.number(),
  risk_rs:              z.number(),
  risk_pct:             z.number(),
  position_size_factor: z.number().optional(),
  hedge:                HedgeC.optional(),
  signal_date:          z.string().optional(),
  accumulation_score:   z.number().nullable().optional(),
}).passthrough();
export type BasketItem = z.infer<typeof BasketItemC>;

// ── Basket summary ────────────────────────────────────────────────────────
export const BasketSummaryC = z.object({
  capital_rs:               z.number(),
  total_deployed:           z.number(),
  cash_remaining:           z.number(),
  total_risk_rs:            z.number(),
  portfolio_max_loss_pct:   z.number(),
  hedge_total_cost_rs:      z.number(),
  hedge_cost_pct_of_capital: z.number(),
  positions:                z.number().int(),
}).passthrough();

// ── Deploy verdict ────────────────────────────────────────────────────────
export const DeployVerdictC = z.object({
  verdict: z.enum(["AGGRESSIVE", "NORMAL", "CAUTIOUS", "DEFENSIVE"]).or(z.string()),
  reason:  z.string().optional(),
}).passthrough();

// ── Basket response ───────────────────────────────────────────────────────
export const BasketResponseC = z.object({
  signal_date:    z.string().nullable(),
  deploy_verdict: DeployVerdictC.nullable(),
  basket:         z.array(BasketItemC),
  summary:        BasketSummaryC,
  message:        z.string().optional(),
}).passthrough();
export type BasketResponse = z.infer<typeof BasketResponseC>;

// ── Simulate ──────────────────────────────────────────────────────────────
const ScenarioC = z.object({
  expected_return_pct:   z.number(),
  expected_pnl_rs:       z.number(),
  max_drawdown_pct:      z.number(),
  max_loss_rs:           z.number(),
}).passthrough();

export const SimPositionC = z.object({
  symbol:                 z.string(),
  allocated_rs:           z.number(),
  probability_of_move:    z.number(),
  avg_fwd_return_pct:     z.number(),
  avg_fwd_drawdown_pct:   z.number(),
  scenarios: z.object({
    BASE: ScenarioC,
    BULL: ScenarioC,
    BEAR: ScenarioC,
  }),
}).passthrough();

const AggScenarioC = z.object({
  total_expected_pnl_rs:   z.number(),
  total_max_loss_rs:       z.number(),
  portfolio_return_pct:    z.number(),
  portfolio_drawdown_pct:  z.number(),
  win_count:               z.number().int(),
  loss_count:              z.number().int(),
}).passthrough();

export const SimulateResponseC = z.object({
  horizon_days:  z.number().int(),
  scenarios: z.object({
    BASE: AggScenarioC,
    BULL: AggScenarioC,
    BEAR: AggScenarioC,
  }),
  per_position: z.array(SimPositionC),
}).passthrough();
export type SimulateResponse = z.infer<typeof SimulateResponseC>;
