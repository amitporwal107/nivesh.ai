/**
 * Strategy Builder, "From AI opportunities" - the ideas route as a hook, and the request the inputs make.
 *
 *   useStrategyIdeas(run)   POST /api/desk/strategy/ideas   reads the scanner and the F&O data, writes nothing
 *
 * No retry (a failure is shown with a Retry button), and the previous board stays on screen while a new one loads.
 * Nothing places an order; `sent_to_broker` is false on the answer.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { IdeasSchema, type IdeasBoard } from "./ideas-contract";
import { readNumber, type FormState } from "./plan-form";
import type { FieldProblem } from "./plan-contract";

export const IDEAS_PATH = "/api/desk/strategy/ideas";

/** The body of POST /api/desk/strategy/ideas. A field left out is a default the route applies and names in `inputs.defaults_applied`. */
export interface IdeasRequest {
  limit: number;
  capital?: number;
  risk_budget_inr?: number;
  risk_pct?: number;
  max_allocation_pct?: number;
  min_reward_risk?: number;
  avoid_events?: boolean;
  allow_multi_leg?: boolean;
  include_combinations: boolean;
}

export const IDEAS_LIMIT = 8;

/** One run of the board: the body and a counter, so "Build ideas" runs again with the same body. */
export interface IdeasRun { body: IdeasRequest; runId: number }

export function useStrategyIdeas(run: IdeasRun | null) {
  return useQuery<IdeasBoard>({
    queryKey: ["copilot", "desk", "strategy-ideas", run?.runId ?? 0, run?.body ?? null],
    enabled: run != null,
    retry: false,
    staleTime: 0,
    gcTime: 60_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: IDEAS_PATH, body: run?.body, signal, noRetry: true });
      const r = IdeasSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The ideas were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}

const problem = (field: string, code: string, message: string): FieldProblem => ({ field, code, message });

function num(out: FieldProblem[], key: string, text: string, hi: number, label: string): number | undefined {
  if (!text.trim()) return undefined;
  const n = readNumber(text);
  if (n == null || n <= 0 || n > hi) { out.push(problem(key, `bad_${key}`, `${label} must be a number above 0 and at most ${hi}.`)); return undefined; }
  return n;
}

/** The ideas request for the inputs panel (same limits as the plan route), or the problems that stop it. */
export function ideasRequestFromForm(f: FormState, combos: boolean): { request: IdeasRequest | null; problems: FieldProblem[] } {
  const out: FieldProblem[] = [];
  const capital = num(out, "capital", f.capital, 1e12, "Capital");
  const risk = f.riskMode === "inr" ? num(out, "risk_budget_inr", f.risk, 1e12, "The risk budget") : num(out, "risk_pct", f.risk, 100, "The risk percentage");
  const alloc = num(out, "max_allocation_pct", f.maxAlloc, 100, "The maximum allocation");
  const minRr = num(out, "min_reward_risk", f.minRr, 100, "The minimum reward : risk");
  if (out.length) return { request: null, problems: out };
  return {
    problems: [],
    request: {
      limit: IDEAS_LIMIT,
      ...(capital != null ? { capital } : {}),
      ...(risk != null ? (f.riskMode === "inr" ? { risk_budget_inr: risk } : { risk_pct: risk }) : {}),
      ...(alloc != null ? { max_allocation_pct: alloc } : {}),
      ...(minRr != null ? { min_reward_risk: minRr } : {}),
      ...(f.avoidEvents != null ? { avoid_events: f.avoidEvents } : {}),
      ...(f.allowMultiLeg != null ? { allow_multi_leg: f.allowMultiLeg } : {}),
      include_combinations: combos,
    },
  };
}

/** The URL params that open one stock's full plan with an idea's inputs (read back by formFromParams). */
export function paramsFromPlanInputs(pi: Record<string, unknown>): Record<string, string> {
  const out: Record<string, string> = {};
  const put = (param: string, key: string) => { const v = pi[key]; if (v != null && (typeof v === "string" || typeof v === "number" || typeof v === "boolean")) out[param] = String(v); };
  put("sym", "underlying"); put("direction", "direction"); put("instrument", "instrument"); put("horizon", "horizon");
  put("horizon_days", "horizon_days"); put("capital", "capital"); put("risk_inr", "risk_budget_inr"); put("risk_pct", "risk_pct");
  put("max_alloc", "max_allocation_pct"); put("min_rr", "min_reward_risk"); put("avoid_events", "avoid_events"); put("multi_leg", "allow_multi_leg"); put("combos", "include_combinations"); put("expiry", "expiry");
  return out;
}
