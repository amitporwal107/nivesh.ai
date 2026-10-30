/**
 * Strategy Builder — the plan routes as hooks, and the pure builders that turn a plan into a paper-trade body
 * (PRD §16.5 lifecycle, §17.3 step 8). No order is placed from here: a plan, a saved plan and a paper trade are
 * records; `sent_to_broker` is false on every one.
 *
 *   useBuildPlan()      POST   /api/desk/strategy/plan       builds a plan; nothing is written
 *   useSavedPlans()     GET    /api/desk/strategy/plans      the signed-in user's saved plans
 *   useSavedPlan(id)    GET    /api/desk/strategy/plans/{id}
 *   useSavePlan()       POST   /api/desk/strategy/plans      { plan } - the plan object exactly as the build route returned it
 *   useDeletePlan()     DELETE /api/desk/strategy/plans/{id} only the saved copy
 *
 * A plan is saved from its RAW body: the route checks a fingerprint of its inputs and snapshots, so the screen
 * never re-serialises a parsed copy (zod would fill defaults). The parsed copy is for rendering only.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ZodError } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { maxHoldFor, type NewPaperTrade, type NewStrategyLeg, type NewStrategyPaperTrade, type StrategyDirection } from "../desk-trading";
import { planBlocker, planRefOf } from "./trade-plan";
import {
  DeleteAnswerSchema, PlanSchema, SavedListSchema, SavedPlanSchema,
  type Candidate, type FieldProblem, type SavedList, type StrategyPlan,
} from "./plan-contract";

export const PLAN_PATH = "/api/desk/strategy/plan";
export const PLANS_PATH = "/api/desk/strategy/plans";
const SAVED_KEY = ["copilot", "desk", "strategy-plans"] as const;

// ── the request ──────────────────────────────────────────────────────────

/** The body of POST /api/desk/strategy/plan. A field left out is a default the route applies and names in `inputs.defaults_applied`. */
export interface PlanRequest {
  underlying: string;
  direction: string;
  horizon?: string;
  instrument?: string;
  horizon_days?: number;
  capital?: number;
  risk_budget_inr?: number;
  risk_pct?: number;
  max_allocation_pct?: number;
  min_reward_risk?: number;
  avoid_events?: boolean;
  allow_multi_leg?: boolean;
  include_combinations?: boolean;
  expiry?: string;
}

export interface BuiltPlan { plan: StrategyPlan; raw: unknown }
export interface SavedOne extends BuiltPlan { id: string; savedAt: string }

function parsePlan(raw: unknown): StrategyPlan {
  const r = PlanSchema.safeParse(raw);
  if (!r.success) throw new ApiError("contract_drift", "The plan was not in the expected form.", { cause: r.error });
  return r.data;
}

export function useBuildPlan() {
  return useMutation({
    mutationFn: async (req: PlanRequest): Promise<BuiltPlan> => {
      const res = await http({ method: "POST", path: PLAN_PATH, body: req, noRetry: true });
      return { plan: parsePlan(res.data), raw: res.data };
    },
  });
}

// ── saved plans ──────────────────────────────────────────────────────────

export function useSavedPlans(enabled = true) {
  return useQuery<SavedList>({
    queryKey: SAVED_KEY,
    enabled,
    staleTime: 30_000,
    retry: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: PLANS_PATH, signal });
      const r = SavedListSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The saved plans were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}

async function readSaved(data: unknown): Promise<SavedOne> {
  const r = SavedPlanSchema.safeParse(data);
  if (!r.success) throw new ApiError("contract_drift", "The saved plan was not in the expected form.", { cause: r.error });
  const rawPlan = (data as { plan: unknown }).plan;
  return { id: r.data.id, savedAt: r.data.saved_at, plan: r.data.plan, raw: rawPlan };
}

export function useSavedPlan(id: string | null) {
  return useQuery<SavedOne>({
    queryKey: [...SAVED_KEY, id],
    enabled: !!id,
    staleTime: 5 * 60_000,
    retry: false,
    queryFn: async ({ signal }) => readSaved((await http({ path: `${PLANS_PATH}/${encodeURIComponent(id as string)}`, signal })).data),
  });
}

export function useSavePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (built: BuiltPlan): Promise<SavedOne> => {
      const res = await http({ method: "POST", path: PLANS_PATH, body: { plan: built.raw }, noRetry: true });
      return readSaved(res.data);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: SAVED_KEY }),
  });
}

export function useDeletePlan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string): Promise<{ id: string; note: string | null }> => {
      const res = await http({ method: "DELETE", path: `${PLANS_PATH}/${encodeURIComponent(id)}`, noRetry: true });
      const r = DeleteAnswerSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The delete answer was not in the expected form.", { cause: r.error });
      return { id: r.data.id, note: r.data.note };
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: SAVED_KEY }),
  });
}

// ── the failures, in words ───────────────────────────────────────────────

/** The route's `detail.problems` of a 422 (invalid_input), else an empty list. */
export function planProblems(e: unknown): FieldProblem[] {
  if (!(e instanceof ApiError) || e.status !== 422) return [];
  const detail = (e.body as { detail?: unknown } | undefined)?.detail;
  const list = detail && typeof detail === "object" ? (detail as { problems?: unknown }).problems : null;
  if (!Array.isArray(list)) return [];
  return list.flatMap((p) => {
    const o = p as { field?: unknown; code?: unknown; message?: unknown };
    return typeof o?.message === "string" ? [{ field: typeof o.field === "string" ? o.field : "", code: typeof o.code === "string" ? o.code : "", message: o.message }] : [];
  });
}

const SAVE_CODE_TEXT: Record<string, string> = {
  plan_not_found: "That saved plan is not on record (it was deleted, or it is not yours).",
};

/** A failed build, save, open or delete in plain words. */
export function planFailure(e: unknown, what: string): string {
  if (e instanceof ZodError) return `${what}: the answer was not in the expected form.`;
  if (e instanceof ApiError) {
    if (e.kind === "auth") return `${what}: you are signed out. Sign in again.`;
    if (e.kind === "forbidden") return `${what}: this account is not allowed to build strategy plans.`;
    if (e.kind === "network") return `${what}: the network request failed.`;
    if (e.kind === "timeout") return `${what}: the request took too long.`;
    if (e.kind === "contract_drift") return `${what}: the answer was not in the expected form, so nothing is shown.`;
    if (e.kind === "server") return `${what}: the server could not finish (${e.status ?? "error"}${e.detail ? `: ${e.detail}` : ""}).`;
    if (e.detail) return `${what}: ${SAVE_CODE_TEXT[e.detail] ?? e.detail}`;
    return `${what}: HTTP ${e.status ?? "error"}.`;
  }
  return `${what}: ${e instanceof Error && e.message ? e.message : "it failed."}`;
}

export const isForbiddenPlan = (e: unknown) => e instanceof ApiError && (e.kind === "forbidden" || e.status === 403);

// ── paper trade bodies ───────────────────────────────────────────────────

/** The route's controlled family list (backend/services/desk_strategy_trades.py FAMILIES). */
const PAPER_FAMILIES = new Set([
  "long_future", "short_future", "long_call", "long_put", "bull_call_spread", "bear_put_spread", "bull_put_spread", "bear_call_spread",
  "long_straddle", "long_strangle", "iron_condor", "iron_butterfly", "covered_call", "protective_put", "collar", "hedged_future", "custom",
]);

/** The plan's family as the paper store's: futures by side, option structures by name, anything else custom. */
export function paperFamily(c: Candidate): string {
  if (c.segment === "futures") return c.legs[0]?.side === "sell" ? "short_future" : "long_future";
  return PAPER_FAMILIES.has(c.family) ? c.family : "custom";
}

function paperDirection(plan: StrategyPlan): StrategyDirection {
  const d = plan.inputs.direction;
  return d === "bullish" || d === "bearish" ? d : "neutral";
}

const levelOf = (c: Candidate, name: string): number | null => c.targets.find((t) => t.name === name)?.price ?? null;

/** Why this candidate cannot be paper-traded, or null when it can. The route enforces the same rules again. */
export function paperBlocker(plan: StrategyPlan, c: Candidate): string | null {
  if (c.trade_plan) {
    const blocked = planBlocker(c.trade_plan);
    if (blocked) return blocked;
  }
  if (c.status !== "candidate") {
    const why = c.reasons[0]?.message;
    return `This candidate is "${c.status.replace("_", " ")}", not a plan${why ? `: ${why}` : "."}`;
  }
  if (!c.legs.length) return "This candidate has no legs.";
  if (c.options_selection?.stale) return "The option chain is delayed/historical, not a current actionable strike, so it cannot be paper traded.";
  if (c.sizing?.status !== "complete" || !c.sizing.quantity) {
    const miss = c.sizing?.missing.length ? ` Missing: ${c.sizing.missing.join(", ")}.` : "";
    return `Sizing is incomplete, so there is no quantity to record.${miss}`;
  }
  if (c.legs.some((l) => !(l.entry_price > 0) || !l.price_source)) return "A leg has no price or no price source, so its mark is missing.";
  const ex = c.payoff?.expiry;
  if (c.segment === "options" && (!c.payoff || !c.payoff.valid || !ex || ex.loss_unbounded || c.payoff.capital_at_risk == null)) {
    return "The risk of this structure is undefined, and only defined-risk option structures are recorded.";
  }
  if (c.segment === "cash") {
    const stop = c.invalidation?.technical?.price ?? null;
    const entry = c.legs[0].entry_price;
    if (c.legs[0].side !== "buy") return "Selling shares is not supported in a paper trade.";
    if (stop == null || !(stop < entry)) return "The plan has no stop below the entry, which a share paper trade needs.";
    return null;
  }
  const dir = paperDirection(plan);
  if (c.segment === "futures" && c.legs.some((l) => l.kind === "future" && l.side === "sell")) {
    // The route refuses it too (short_futures_not_supported, owner decision D2): said here before any request.
    return "Short futures are not recorded as paper trades yet: they need the shared risk service (margin and gap stress) first.";
  }
  const ref = plan.underlying.spot;
  if (ref == null) return "The plan has no reference price (the last close).";
  const stop = dir === "neutral" ? null : c.invalidation?.technical?.price ?? null;
  const target = dir === "neutral" ? null : levelOf(c, "base");
  if (dir === "bullish" && ((stop != null && stop >= ref) || (target != null && target <= ref))) return "The plan's stop or target is on the wrong side of the reference price for a bullish view.";
  if (dir === "bearish" && ((stop != null && stop <= ref) || (target != null && target >= ref))) return "The plan's stop or target is on the wrong side of the reference price for a bearish view.";
  return null;
}

const SOURCE_ORDER = ["indicators", "chain", "futures", "buildup", "scan_row", "scanner_bucket", "regime", "features", "events", "expiries"];

/** The signal block's source references from the plan's snapshots (at most 10; the failed ones are not evidence). */
export function signalRefs(plan: StrategyPlan): Array<{ kind: string; ref: string; as_of: string | null }> {
  const ok = plan.source_snapshots.filter((s) => s.ok);
  const rank = (k: string) => { const i = SOURCE_ORDER.indexOf(k); return i < 0 ? SOURCE_ORDER.length : i; };
  return [...ok].sort((a, b) => rank(a.key) - rank(b.key) || a.key.localeCompare(b.key)).slice(0, 10).map((s) => ({
    kind: s.key.slice(0, 40),
    ref: `${s.source ?? s.key}${s.content_hash ? ` #${s.content_hash}` : ""}`.slice(0, 120),
    as_of: s.as_of,
  }));
}

/** The immutable signal's evidence text (up to 1000 characters): the candidate, the view and the evidence that applied. */
export function evidenceSummary(plan: StrategyPlan, c: Candidate): string {
  const parts = [
    `${c.label} on ${plan.underlying.symbol}, ${plan.inputs.direction} view, ${plan.inputs.horizon} horizon. Plan ${plan.plan_id}, status ${plan.status}, price as of ${plan.data_as_of.price ?? "—"} (end of day).`,
    plan.thesis.supports.length ? `Supports: ${plan.thesis.supports.map((s) => `${s.group}.${s.key}`).join(", ")}.` : "No supporting evidence listed.",
    plan.thesis.conflicts.length ? `Conflicts: ${plan.thesis.conflicts.map((s) => `${s.group}.${s.key}`).join(", ")}.` : "No conflicting evidence listed.",
    `Validation: ${plan.validation.status}. Model estimate: ${plan.headline.model_estimate.status}.`,
  ];
  const text = parts.join(" ");
  return text.length <= 1000 ? text : `${text.slice(0, 997)}...`;
}

/** The body of a kind "strategy" paper trade for a futures or option candidate. Call only when `paperBlocker` is null and the plan is saved. */
export function strategyPaperBody(plan: StrategyPlan, c: Candidate, savedId: string): NewStrategyPaperTrade {
  const dir = paperDirection(plan);
  const legs: NewStrategyLeg[] = c.legs.map((l) => ({
    kind: l.kind, side: l.side, lots: l.quantity, lot_size: l.lot_size, entry_price: l.entry_price, expiry: l.expiry ?? null,
    strike: l.strike ?? null, option_type: l.option_type ?? null, price_source: l.price_source ?? "",
  }));
  return {
    kind: "strategy",
    underlying: plan.underlying.symbol,
    direction: dir,
    family: paperFamily(c),
    strategy_plan_id: savedId,
    reference_price: plan.underlying.spot as number,
    stop_underlying: dir === "neutral" ? null : c.invalidation?.technical?.price ?? null,
    target_underlying: dir === "neutral" ? null : levelOf(c, "base"),
    legs,
    signal: {
      signal_at: plan.generated_at,
      rule_version: plan.rules_version,
      source_refs: signalRefs(plan),
      evidence_summary: evidenceSummary(plan, c),
    },
    ...(plan.inputs.horizon_days ? { max_hold_sessions: plan.inputs.horizon_days } : {}),
    ...(c.trade_plan ? { plan_ref: planRefOf(c.trade_plan) } : {}),
  };
}

/** The body of a share paper trade for a cash candidate (the existing share paper-trade API). `quantity`: the risk
 *  service's size for the account (the decision card's), when it is known; else the candidate's own sizing. */
export function cashPaperBody(plan: StrategyPlan, c: Candidate, quantity?: number | null): NewPaperTrade {
  const leg = c.legs[0];
  const maxHold = maxHoldFor(plan.inputs.horizon_days);
  const target = levelOf(c, "base");
  return {
    symbol: plan.underlying.symbol,
    quantity: quantity ?? leg.quantity,
    entry_price: leg.entry_price,
    stop_price: c.invalidation?.technical?.price as number,
    target_price: target != null && target > leg.entry_price ? target : null,
    source: { kind: "strategy_plan", bucket: c.family.slice(0, 60), ...(plan.data_as_of.price ? { signal_date: plan.data_as_of.price } : {}) },
    signal_at: plan.generated_at,
    strategy_version: plan.rules_version,
    rationale: `${c.label}; plan ${plan.plan_id}`.slice(0, 500),
    // The plan's horizon is the time exit (the strategy trade body already sends it): closed at the close of that session held.
    ...(maxHold != null ? { max_hold_sessions: maxHold } : {}),
    // Phase 2.1: the trade cites the candidate's TradePlan; its entry rule is the plan's order type (a setup that waits
    // for its trigger is recorded as a conditional entry, never as filled at once).
    ...(c.trade_plan ? { plan_ref: planRefOf(c.trade_plan), entry_rule: (c.trade_plan.entry.desk_entry_rule ?? "at_once") as NewPaperTrade["entry_rule"] } : {}),
  };
}

/** The question the Copilot gets about a saved plan: its saved id, the plan id and a short summary. */
export function copilotQuestion(plan: StrategyPlan, savedId: string, c: Candidate | null): string {
  const pref = c ? `${c.label} (${c.status.replace("_", " ")})` : "no candidate";
  return `Explain my saved strategy plan ${savedId} (plan ${plan.plan_id}) for ${plan.underlying.symbol}: ${plan.inputs.direction} view, ${plan.inputs.horizon} horizon, status ${plan.status.replace("_", " ")}, looking at ${pref}. Quote its legs, levels and figures exactly; do not invent strikes, prices or P&L.`;
}
