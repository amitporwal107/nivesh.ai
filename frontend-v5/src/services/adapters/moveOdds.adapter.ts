/**
 * Move odds adapter — the Research page's Ten-Percent Days screen (backend/routes/move_odds.py → DaaS).
 *
 *   GET /api/move-odds/latest?head=…     → published estimates for the session they apply to
 *   GET /api/move-odds/stocks/{symbol}   → one stock: four estimates, inputs on record, events on record
 *
 * Every state is explicit so the screen can never show numbers it should not:
 *   final         → rows (sorted by estimate, no rank)
 *   not_published → no rows; the session they will be for
 *   withheld      → no rows; the run was refused on incomplete data
 *   no_access     → 403: the account is not on the move_odds allowlist
 *   error         → anything else (retry offered; no cached numbers)
 */
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { z } from "zod";

export const MOVE_HEADS = ["p_up5_1d", "p_down5_1d", "p_up10_1d", "p_down10_1d"] as const;
export type MoveHead = (typeof MOVE_HEADS)[number];

const RunC = z.object({
  model: z.string(),
  refit: z.string().nullable().optional(),
  status: z.string(),
  data_as_of: z.string(),
  target_session: z.string(),
  frozen_at: z.string(),
  git_sha: z.string(),
  universe_size: z.number(),
  scored: z.number(),
  input_count: z.number().nullable().optional(),
  train_rows: z.number().nullable().optional(),
  train_end: z.string().nullable().optional(),
  counts_toward_verdict: z.boolean(),
  skipped_holidays: z.array(z.string()).default([]),
});
export type MoveRun = z.infer<typeof RunC>;

const RowC = z.object({
  symbol: z.string(),
  company_name: z.string().nullable(),
  sector: z.string().nullable(),
  p: z.number(),
  p_opposite: z.number().nullable(),
  events_on_record: z.number(),
});
export type MoveRow = z.infer<typeof RowC>;

const BandC = z.object({ band_lo: z.number(), band_hi: z.number(), rows: z.number(), realised: z.number().nullable() });
export type MoveBand = z.infer<typeof BandC>;

const FinalC = z.object({
  status: z.literal("final"),
  head: z.enum(MOVE_HEADS),
  expected_session: z.string(),
  base_rate: z.number(),
  run: RunC,
  rows: z.array(RowC),
  record: z.object({
    window_label: z.string(), sessions: z.number(), base_rate: z.number(), top10_hit_rate: z.number(), bands: z.array(BandC),
  }).nullable(),
  live_record: z.object({
    sessions: z.number(),
    top10_hits: z.number().nullable(),
    touched: z.number().nullable(),
    graded_rows: z.number().nullable(),
    last_target: z.string().nullable(),
    last_top10_hits: z.number().nullable(),
    last_touched: z.number().nullable(),
    last_graded_rows: z.number().nullable(),
  }),
  limits: z.object({ not_used: z.array(z.string()) }),
});
export type MoveFinal = z.infer<typeof FinalC>;

const PendingC = z.object({
  status: z.literal("not_published"),
  head: z.enum(MOVE_HEADS),
  expected_session: z.string(),
  last_published_for: z.string().nullable(),
  rows: z.array(z.unknown()).length(0),
});
export type MovePending = z.infer<typeof PendingC>;

const InputC = z.object({ v: z.number().nullable(), date: z.string().nullable() });
const EventC = z.object({
  ord: z.number(),
  event_time: z.string(),
  source_label: z.string(),
  is_media: z.boolean(),
  event_type: z.string(),
  event_subtype: z.string(),
  direction: z.string(),
  title: z.string().nullable(),
  url: z.string().nullable(),
  method: z.string(),
});
const StockC = z.object({
  symbol: z.string(),
  company_name: z.string().nullable(),
  sector: z.string().nullable(),
  results_filed: z.boolean(),
  run: RunC,
  estimates: z.record(z.number()),
  inputs: z.record(InputC),
  events: z.array(EventC),
});
export type MoveStock = z.infer<typeof StockC>;
export type MoveEvent = z.infer<typeof EventC>;

export type MoveLatestResult =
  | { kind: "final"; data: MoveFinal }
  | { kind: "not_published"; data: MovePending }
  | { kind: "withheld"; reason: string }
  | { kind: "no_access" }
  | { kind: "error"; message: string };

export type MoveStockResult =
  | { kind: "ok"; data: MoveStock }
  | { kind: "no_access" }
  | { kind: "withheld"; reason: string }
  | { kind: "error"; message: string };

function fromError(e: unknown): { kind: "no_access" } | { kind: "withheld"; reason: string } | { kind: "error"; message: string } {
  if (e instanceof ApiError) {
    if (e.status === 403) return { kind: "no_access" };
    if (e.status === 503 && (e.detail ?? "").startsWith("withheld")) {
      return { kind: "withheld", reason: (e.detail ?? "").replace(/^withheld:\s*/, "") || "not stated" };
    }
    return { kind: "error", message: e.status ? `HTTP ${e.status}` : e.message };
  }
  return { kind: "error", message: e instanceof Error ? e.message : "unexpected response" };
}

export const moveOddsService = {
  async latest(head: MoveHead): Promise<MoveLatestResult> {
    try {
      const res = await http<unknown>({ path: "/api/move-odds/latest", query: { head }, noRetry: true });
      const env = z.object({ data: z.union([FinalC, PendingC]) }).safeParse(res.data);
      if (!env.success) return { kind: "error", message: "unexpected response shape" };
      return env.data.data.status === "final"
        ? { kind: "final", data: env.data.data as MoveFinal }
        : { kind: "not_published", data: env.data.data as MovePending };
    } catch (e) {
      return fromError(e);
    }
  },

  async stock(symbol: string): Promise<MoveStockResult> {
    try {
      const res = await http<unknown>({ path: `/api/move-odds/stocks/${encodeURIComponent(symbol)}`, noRetry: true });
      const env = z.object({ data: StockC }).safeParse(res.data);
      return env.success ? { kind: "ok", data: env.data.data } : { kind: "error", message: "unexpected response shape" };
    } catch (e) {
      return fromError(e);
    }
  },
};
