/**
 * Smart trading desk — the Scanner's two "Top 10 ideas" boards: the reads and the merge.
 *
 *   POST /api/desk/strategy/ideas  { limit: 10 }                                                    useTop10Stocks
 *   POST /api/desk/strategy/top    { limit: 10, classes: ["index_options", "stock_fno"], distinct: true }   useTop10Fno
 *
 * Both routes read sources and write nothing (sent_to_broker false). Each takes seconds — they read option chains
 * and the scanner — so an answer is kept for TOP10_STALE_MS under one fixed key: the lab's focus panel, a trip to
 * another tab and the way back all show the board already read instead of asking again. "Rank again" refetches.
 *
 * The F&O board is the route's two option classes merged by the route's own order (regime_fit._rank_key: fit
 * first, then reward : risk, a missing reward : risk last) and cut to ten. Both classes are scored by the same
 * rule against the same regime, so one order across them is the route's order, not a ranking made up here.
 * The wording is "ideas": nothing here is a recommendation (the user's decision of 2026-10-25).
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { IdeasSchema, type Idea, type IdeaStrategy, type IdeasBoard } from "./strategy/ideas-contract";
import { IDEAS_PATH, paramsFromPlanInputs } from "./strategy/ideas-data";
import { TOP_PATH, type TopRequest } from "./strategy/top-data";
import { TopSchema, type OptionIdea, type TopBoard } from "./strategy/top-contract";
import { readAccountSize } from "./decision/plan-view";
import { fmtNum } from "../../components/ui";

export const TOP10 = 10;
const TOP10_STALE_MS = 15 * 60_000;

export const TOP10_STOCKS_BODY = { limit: TOP10 } as const;
export const TOP10_FNO_BODY: TopRequest = { limit: TOP10, classes: ["index_options", "stock_fno"], distinct: true };

const STOCKS_KEY = ["copilot", "desk", "top10", "stocks"] as const;
const FNO_KEY = ["copilot", "desk", "top10", "fno"] as const;

const shared = { retry: false, staleTime: TOP10_STALE_MS, gcTime: 2 * TOP10_STALE_MS, refetchOnWindowFocus: false } as const;
/** The ideas and board routes build every idea's plan on the server (the scanner read, the strategy fit, the TradePlan); on
 *  staging that took 12–16 s on 27 Oct, over the app's 15 s default, so the Top AI candidates showed "the request took too
 *  long". These two calls wait up to 45 s. */
export const TOP10_TIMEOUT_MS = 45_000;

export function useTop10Stocks(enabled = true) {
  return useQuery<IdeasBoard>({
    queryKey: STOCKS_KEY,
    enabled,
    ...shared,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: IDEAS_PATH, body: TOP10_STOCKS_BODY, signal, noRetry: true, timeoutMs: TOP10_TIMEOUT_MS });
      const r = IdeasSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The stock ideas were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}

export function useTop10Fno(enabled = true) {
  return useQuery<TopBoard>({
    queryKey: FNO_KEY,
    enabled,
    ...shared,
    queryFn: async ({ signal }) => {
      const res = await http({ method: "POST", path: TOP_PATH, body: TOP10_FNO_BODY, signal, noRetry: true, timeoutMs: TOP10_TIMEOUT_MS });
      const r = TopSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The F&O ideas were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}

// ── F&O: one list across the two option classes ──────────────────────────

export type FnoKind = "index" | "stock";
export interface FnoRow { idea: OptionIdea; kind: FnoKind; rank: number }

/** regime_fit._rank_key, the route's order: fit first, then reward : risk, a missing reward : risk last. */
const routeOrder = (a: OptionIdea, b: OptionIdea) =>
  b.fit.score - a.fit.score || (b.reward_risk ?? 0) - (a.reward_risk ?? 0);

function allFno(board: TopBoard | undefined): Array<{ idea: OptionIdea; kind: FnoKind }> {
  return [
    ...(board?.classes.index_options?.ideas ?? []).map((idea) => ({ idea, kind: "index" as const })),
    ...(board?.classes.stock_fno?.ideas ?? []).map((idea) => ({ idea, kind: "stock" as const })),
  ];
}

/** Both option classes in the route's order, cut to `limit`, ranked 1..n. A tie keeps the index class first (stable sort). */
export function mergeFno(board: TopBoard | undefined, limit = TOP10): FnoRow[] {
  return allFno(board).sort((a, b) => routeOrder(a.idea, b.idea)).slice(0, limit).map((r, i) => ({ ...r, rank: i + 1 }));
}

/** The board's row for one underlying (searched over both classes, not only the ten shown), or null. */
export function fnoRowFor(board: TopBoard | undefined, symbol: string | null): FnoRow | null {
  if (!symbol) return null;
  const rows = allFno(board).sort((a, b) => routeOrder(a.idea, b.idea));
  const i = rows.findIndex((r) => r.idea.underlying.toUpperCase() === symbol.toUpperCase());
  return i < 0 ? null : { ...rows[i], rank: i + 1 };
}

/** Where the F&O board's names came from, and what it passed over, in one line each. */
export function fnoUniverseNotes(board: TopBoard | undefined): { skipped: string[]; unreadable: string[] } {
  const stock = board?.classes.stock_fno;
  const idx = board?.classes.index_options;
  const skipped = (stock?.universe?.skipped ?? []).map((s) => s.underlying).filter((s): s is string => !!s);
  const unreadable = [...(idx?.unavailable ?? []), ...(stock?.unavailable ?? [])]
    .map((u) => (u.underlying ? `${u.underlying}${u.reason ? ` (${u.reason})` : ""}` : u.reason ?? null))
    .filter((s): s is string => !!s);
  return { skipped, unreadable };
}

// ── stocks: the strategy that fits, and the plan behind it ───────────────

/** The route's preferred strategy for the idea, or null when it named none. */
export function preferredStrategy(idea: Idea): IdeaStrategy | null {
  return idea.preferred ? idea.strategies.find((s) => s.id === idea.preferred) ?? null : null;
}

/** The owner's minimum reward : risk for a directional trade (risk profile), when the route sends no minimum of its own. */
export const DEFAULT_MIN_REWARD_RISK = 1.5;

/** The strategy fields the minimum and the account size are read from (an ideas row, a Chartink candidate's strategy, a stored list's). */
export interface FitStrategy {
  segment?: string | null;
  status?: string | null;
  legs_text?: string | null;
  reward_risk_net?: number | null;
  reward_risk_gross?: number | null;
  min_reward_risk?: unknown;
  meets_min_reward_risk?: unknown;
  account_size?: unknown;
  sizing?: { status?: string | null; quantity?: number | null; lots?: number | null } | null;
}

/**
 * The minimum a viable strategy's SHOWN reward : risk (net, else gross) falls short of, or null when it does not. A
 * strategy under the minimum is "below your 1.5 minimum", never "viable" (audit 2026-10-28: a 0.19 : 1 strategy was
 * labelled VIABLE). The route's own verdict (`meets_min_reward_risk`, ideas.strategies_of) wins; without it the ratio
 * is compared here. Credit structures follow this rule until their own (net credit vs strike width, PR #382) is merged.
 */
export function belowMinimum(s: FitStrategy): number | null {
  if (s.status !== "candidate") return null;
  const min = typeof s.min_reward_risk === "number" ? s.min_reward_risk : DEFAULT_MIN_REWARD_RISK;
  if (s.meets_min_reward_risk === false) return min;
  if (s.meets_min_reward_risk === true) return null;
  const got = s.reward_risk_net ?? s.reward_risk_gross ?? null;
  return got != null && got < min ? min : null;
}

export const belowMinimumText = (min: number) => `below your ${fmtNum(min, 1)} minimum`;

/**
 * The size of the "strategy that fits", from the risk service's sizing of ITS trade plan for your account
 * (`account_size`, POST /ideas → plan_sizing.size_for), so it never reads differently from the card's "Size"
 * (audit 2026-10-28: "Size 34 shares" beside "Buy 700 shares…"). A structure the risk service could not size is shown
 * at the plan's own lot count and says so: "1 lot, not sized to your account".
 *   legs   the legs to show: the route's text, or for a sized cash strategy the account's share count
 *   size   the size clause;  sized  whether the account's size is shown;  why  the risk service's reason, when not sized
 */
export function fitSize(s: FitStrategy, symbol: string): { legs: string | null; size: string; sized: boolean; why: string | null } {
  const a = readAccountSize(s.account_size);
  const cash = s.segment === "cash";
  if (a?.status === "sized") {
    if (cash && a.quantity != null) return { legs: `Buy ${fmtNum(a.quantity)} shares ${symbol}`, size: `${fmtNum(a.quantity)} share${a.quantity === 1 ? "" : "s"}, sized to your account`, sized: true, why: null };
    if (!cash && a.lots != null) return { legs: s.legs_text ?? null, size: `${fmtNum(a.lots)} lot${a.lots === 1 ? "" : "s"}, sized to your account`, sized: true, why: null };
  }
  const own = s.sizing?.status === "complete" ? (cash ? s.sizing.quantity : s.sizing.lots) : null;
  const n = own != null && own >= 1 ? own : 1;
  const unit = cash ? (n === 1 ? "share" : "shares") : (n === 1 ? "lot" : "lots");
  const why = a == null ? "the risk service did not size it for your account"
    : a.status === "not_confirmed" ? `the risk service cuts it again at submission${a.confirmReasons[0]?.message ? `: ${a.confirmReasons[0].message}` : ""}`
      : a.blocking[0]?.message ?? a.reason ?? null;
  return { legs: s.legs_text ?? null, size: `${fmtNum(n)} ${unit}, not sized to your account`, sized: false, why };
}

/** The share count the plan sized for the cash strategy, when it sized one (the paper trade's starting quantity). */
export function sizedShares(idea: Idea): number | null {
  const cash = idea.strategies.find((s) => s.segment === "cash");
  const q = cash?.sizing?.quantity;
  return q != null && Number.isInteger(q) && q >= 1 ? q : null;
}

/** The Strategy Builder params for the idea's plan, as the ideas board writes them (IdeasBoard openPlan). */
export function planParamsFor(idea: Idea, scanDate: string | null): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries({ sym: idea.symbol, direction: idea.direction, ...paramsFromPlanInputs(idea.plan_inputs) })) if (v) out[k] = v;
  out.src_kind = "ideas";
  if (idea.scanner.bucket) out.src_bucket = idea.scanner.bucket;
  if (scanDate) out.src_date = scanDate;
  if (idea.preferred) out.cand = idea.preferred;
  return out;
}
