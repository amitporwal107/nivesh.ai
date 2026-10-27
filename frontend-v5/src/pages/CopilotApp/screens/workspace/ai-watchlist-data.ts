/**
 * AI scanner watchlist — the route as a hook, and the links into the trading desk.
 *
 *   GET /api/desk/ai-watchlist[?date=YYYY-MM-DD]   one stored day: Top 10 cash + Top 10 F&O ideas as the routes answered
 *                                                  them that day, the dateline (`available_dates`), and per entry the
 *                                                  earlier list days and `days_on_list` (backend/routes/ai_watchlist.py)
 *
 * A stored day never changes, so a day's answer is kept for the session; the newest day is asked again every 10 minutes
 * (a new day appears after the 20:15 IST job). The F&O entries are the regime-fit board's ideas, so their shape is that
 * board's contract (strategy/top-contract.ts). Nothing here recomputes a figure.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { TradePlanOrNull } from "../tradingdesk/strategy/trade-plan";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { paramsFromPlanInputs } from "../tradingdesk/strategy/ideas-data";
import { OptionIdeaSchema } from "../tradingdesk/strategy/top-contract";

export const AI_WATCHLIST_PATH = "/api/desk/ai-watchlist";

const num = z.number().nullable().catch(null);
const str = z.string().nullable().catch(null);
const strs = z.array(z.string()).catch([]);

const Listing = { earlier_list_dates: strs, days_on_list: z.number().catch(1) };

export const CashEntrySchema = z.object({
  rank: z.number(),
  symbol: z.string(),
  name: str,
  sector: str,
  direction: str,
  fno_eligible: z.boolean().nullable().catch(null),
  source: str,
  scanner: z.object({
    bucket: str, status: str, score: num, close: num, close_date: str, entry: num, stop: num, target: num,
    risk_reward: num, horizon_days: num, atr_pct: num, liquidity_cr: num, reason: str, reasons: strs,
  }).partial().catch({}),
  plan_status: str,
  status_reasons: strs,
  preferred: z.object({
    id: z.string(), segment: str, label: z.string(), status: str, legs_text: str, max_loss: num, capital_at_risk: num,
    max_profit: num, reward_risk_net: num,
  }).partial({ segment: true, status: true, legs_text: true, max_loss: true, capital_at_risk: true, max_profit: true, reward_risk_net: true })
    .nullable().catch(null),
  sized_shares: num,
  plan_inputs: z.record(z.unknown()).catch({}),
  /** Phase 2.1: the TradePlan the job stored with the row (absent on days stored before plans). */
  trade_plan_id: z.string().nullable().optional().catch(null),
  trade_plan: TradePlanOrNull,
  ...Listing,
});

export const FnoEntrySchema = OptionIdeaSchema.extend({
  kind: z.enum(["index", "stock"]).catch("stock"),
  rank: z.number(),
  /** The levels engine's answer stored with the day's list (services/ai_watchlist_build.levels_for); absent on a day
   *  stored before the job kept them. `result` is parsed by tradingdesk/IdeaLevels.tsx readStoredLevels. */
  strategy_levels: z.object({ as_of: str, computed_at: str, result: z.unknown(), error: str }).partial().nullable().catch(null),
  ...Listing,
});

export const DaySchema = z.object({
  list_date: z.string().nullable(),
  built_at: str.optional(),
  available_dates: z.array(z.object({ list_date: z.string(), cash: z.number().catch(0), fno: z.number().catch(0) })).catch([]),
  cash: z.array(CashEntrySchema),
  fno: z.array(FnoEntrySchema),
  notes: z.object({
    cash_ranking: str, cash_caveats: strs, fno_ranking: str, fno_gaps: strs, fno_staleness: str, fno_chain_as_of: str, fno_rules_version: str,
    fno_skipped: z.array(z.object({ underlying: str }).passthrough()).catch([]),
    regime: z.object({ available: z.boolean().nullable().catch(null), label: str, as_of: str, trend: str, india_vix: num }).partial().nullable().catch(null),
  }).partial().catch({}),
  rules: z.object({ cash: str, fno: str }).partial().catch({}),
  empty_reason: str.optional(),
});

export type AiWatchDay = z.infer<typeof DaySchema>;
export type CashEntry = z.infer<typeof CashEntrySchema>;
export type FnoEntry = z.infer<typeof FnoEntrySchema>;

export function useAiWatchlist(date: string | null) {
  return useQuery<AiWatchDay>({
    queryKey: ["copilot", "ai-watchlist", date ?? "newest"],
    staleTime: date ? Infinity : 10 * 60_000,
    refetchInterval: date ? false : 10 * 60_000,
    refetchOnWindowFocus: false,
    placeholderData: keepPreviousData,
    retry: (n, e) => !(e instanceof ApiError && (e.status === 404 || e.status === 401)) && n < 1,
    queryFn: async ({ signal }) => {
      const res = await http({ path: AI_WATCHLIST_PATH, query: date ? { date } : undefined, signal });
      const r = DaySchema.safeParse(res.data);
      if (!r.success) throw ApiError.contractDrift(`ai-watchlist: ${r.error.issues[0]?.message ?? "unexpected shape"}`, r.error);
      return r.data;
    },
  });
}

// ── links into the trading desk (/app/trader/desk; its URL state: TradingDesk.tsx, FnoTab.tsx) ──

const desk = (q: Record<string, string>) => `trader/desk?${new URLSearchParams(q).toString()}`;

export const deskChart = (sym: string) => desk({ tab: "chart", sym });
export const deskTrades = () => desk({ tab: "portfolio" });
export const deskChain = (sym: string) => desk({ tab: "fno", lab: "chain", lab_sym: sym });
export const deskBuildup = (sym: string, index: boolean) => desk(index ? { tab: "fno", lab: "indices", lab_sym: sym } : { tab: "fno", lab_sym: sym });
export const deskLab = (sym: string, index: boolean) => desk({ tab: "fno", lab: index ? "indices" : "candidates", lab_sym: sym, lab_focus: sym });

/** The Strategy Builder with the idea's plan, as the ideas board opens it (IdeasBoard openPlan). */
export function deskPlan(e: CashEntry, listDate: string): string {
  const q: Record<string, string> = { tab: "more", view: "strategy", mode: "stock", build: "1" };
  for (const [k, v] of Object.entries({ sym: e.symbol, direction: e.direction ?? "", ...paramsFromPlanInputs(e.plan_inputs) })) if (v) q[k] = v;
  q.src_kind = "ideas";
  if (e.scanner.bucket) q.src_bucket = e.scanner.bucket;
  q.src_date = e.scanner.close_date ?? listDate;
  if (e.preferred?.id) q.cand = e.preferred.id;
  return desk(q);
}
