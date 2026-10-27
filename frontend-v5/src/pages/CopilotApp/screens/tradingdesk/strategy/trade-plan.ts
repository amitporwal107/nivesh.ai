/**
 * The canonical TradePlan (Phase 2.1) as the desk reads it — backend services/strategy_plan/trade_plan.py, schema
 * "trade-plan-v1". Every surface (Top 10, the AI watchlist, the F&O boards, the Strategy Builder) shows the plan's levels
 * and records a paper trade at exactly those levels with `plan_ref`; the route refuses a body whose levels are not the
 * plan's (409 plan_levels_mismatch) and a plan that is not tradeable (409 plan_not_eligible).
 *
 * The exact bodies are pinned in e2e/fixtures/contract-trade-plan-paper.json, which the Playwright specs compare against
 * and backend/tests/test_trade_plan_contract.py sends through the real route. Nothing here places an order.
 */
import { z } from "zod";

const Num = z.number().nullable().optional().catch(null);
const Str = z.string().nullable().optional().catch(null);

export const PlanTargetSchema = z.object({ name: z.string(), price: Num, r_multiple: Num, rule: Str, primary: z.boolean().optional().catch(false) }).passthrough();
export const TradePlanSchema = z.object({
  plan_id: z.string(),
  rules_version: z.string().catch(""),
  version: Num,
  strategy: z.object({ segment: Str, family: Str, label: Str, direction: Str, candidate_id: Str }).passthrough(),
  instrument: z.object({ symbol: Str, segment: Str, lot_size: Num, expiry: Str }).passthrough(),
  entry: z.object({ price: Num, order_type: Str, desk_entry_rule: Str, order_text: Str, valid_for_sessions: Num, reference_close: Num }).passthrough(),
  stop: z.object({ price: Num, method: Str, atr_multiple: Num, distance_atr: Num, swing_ref: Num, measured_from: Num, rationale: Str, premium_stop: Num }).passthrough(),
  r_per_unit: Num,
  targets: z.array(PlanTargetSchema).catch([]),
  size: z.object({ status: Str, quantity: Num, lots: Num, risk_rs: Num, risk_pct_of_equity: Num }).passthrough().nullable().optional().catch(null),
  costs: z.object({ model: Str }).passthrough().nullable().optional().catch(null),
  eligibility: z.object({
    eligible: z.boolean().catch(false), paper_eligible: z.boolean().catch(false), state: z.string().catch("NO_SETUP"),
    reasons: z.array(z.object({ code: Str, message: Str }).passthrough()).catch([]),
  }).passthrough(),
  lifecycle: z.object({ status: Str, state: Str }).passthrough().nullable().optional().catch(null),
  data_as_of: z.record(z.string(), z.string().nullable()).nullable().optional().catch(null),
  stored: z.boolean().nullable().optional().catch(null),
}).passthrough();
export type TradePlan = z.infer<typeof TradePlanSchema>;
export const TradePlanOrNull = TradePlanSchema.nullable().optional().catch(null);

export interface PlanRef { plan_id: string; candidate_id?: string; rules_version?: string }

export function planRefOf(tp: TradePlan): PlanRef {
  return {
    plan_id: tp.plan_id,
    ...(tp.strategy.candidate_id ? { candidate_id: tp.strategy.candidate_id } : {}),
    ...(tp.rules_version ? { rules_version: tp.rules_version } : {}),
  };
}

export type PlanTarget = z.infer<typeof PlanTargetSchema>;

export function primaryTarget(tp: TradePlan): PlanTarget | null {
  return tp.targets.find((t) => t.primary) ?? null;
}

const ORDER_SHORT: Record<string, string> = {
  at_close: "at the close", stop_trigger: "break above", limit_pullback: "pull back to", at_premium: "at the premiums",
};

/** "1.5×ATR below 1413.21" · "swing low 1291" · "underlying" — the stop's METHOD, never a guessed label. */
export function stopMethodText(stop: TradePlan["stop"]): string {
  if (stop.method === "atr" && stop.atr_multiple != null) return `${stop.atr_multiple}×ATR${stop.measured_from != null ? ` below ${stop.measured_from}` : ""}`;
  if (stop.method === "structural") return stop.swing_ref != null ? `under the swing low ${stop.swing_ref}` : "structural";
  if (stop.method === "underlying") return "underlying invalidation";
  if (stop.method === "premium") return stop.premium_stop != null ? `premium stop ${stop.premium_stop}` : "premium stop";
  if (stop.method === "expected_move") return "edge of the expected move";
  return "method not identified";
}

const fmt = (n: number | null | undefined) => (n == null ? "—" : `₹${n.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`);

/** One line from the plan: entry (order type) · stop (method) · targets in R. */
export function planLine(tp: TradePlan): string {
  const entry = tp.entry.price != null ? `Entry ${fmt(tp.entry.price)} (${ORDER_SHORT[tp.entry.order_type ?? ""] ?? tp.entry.order_type})` : `Entry ${ORDER_SHORT.at_premium}`;
  const stop = `Stop ${fmt(tp.stop.price)} (${stopMethodText(tp.stop)})`;
  const targets = tp.targets.filter((t) => t.price != null).map((t) => `${fmt(t.price)}${t.r_multiple != null ? ` (${t.r_multiple}R)` : ""}`).join(" · ");
  return [entry, stop, targets ? `Targets ${targets}` : "No target"].join(" · ");
}

/** Why the plan cannot be paper traded, or null when it can. */
export function planBlocker(tp: TradePlan): string | null {
  if (tp.stored === false) return "The plan could not be stored, so a trade cannot cite it. Reload the board.";
  if (tp.eligibility.paper_eligible) return null;
  const why = tp.eligibility.reasons.map((r) => r.message || r.code).filter(Boolean).slice(0, 2).join(" ");
  const state = tp.eligibility.state.replace(/_/g, " ").toLowerCase();
  return `This plan is ${state}${why ? `: ${why}` : "."}`;
}

/** The plan's time exit (exit_plan.time.max_sessions: the setup's maximum horizon in sessions), when it has one. */
export function planMaxHold(tp: TradePlan): number | null {
  const t = (tp.exit_plan as { time?: { max_sessions?: unknown } } | undefined)?.time?.max_sessions;
  return typeof t === "number" && Number.isInteger(t) && t >= 1 ? t : null;
}
