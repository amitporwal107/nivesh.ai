/**
 * POST /api/screeners/run — run a rule list on the day's stock data and get the
 * matching stocks back in the `stock_screener` widget contract the chat uses.
 * Contract: backend/routes/screeners.py (run_screener). Read-only.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";

export type ScreenBucket = "" | "large" | "mid" | "small";

export interface ScreenRunRequest {
  /** Same shape a saved screen stores: `value` is the number as typed. */
  conditions: { key: string; op: "over" | "under"; value: string }[];
  bucket?: ScreenBucket;
  sector?: string;
  /** Matching stocks sent back (1–500, default 200). */
  limit?: number;
  /** Add the mutual-fund columns (disclosed holdings, Nifty 500 only) to the rows. */
  include_funds?: boolean;
}

/** How many of the day's stocks carry a value for one metric. */
const CoverageC = z.object({
  filled: z.number().int().nonnegative(),
  total: z.number().int().nonnegative(),
});
export type ScreenCoverage = z.infer<typeof CoverageC>;

/** The parts of the widget contract this screen reads; the rest goes to ChatWidget untouched. */
const WidgetC = z.object({
  columns: z.array(z.object({ key: z.string(), label: z.string() }).passthrough()),
  universe: z.array(z.record(z.unknown())),
  filters: z.record(z.number()),
}).passthrough();

export const ScreenRunC = z.object({
  /** False when the stock data source did not answer; nothing below is a result then. */
  ok: z.boolean(),
  as_of_date: z.string().nullable(),
  widget: WidgetC,
  /** Keyed by widget row key (the rule metrics and the table columns), plus `bucket` when a size was asked for. */
  coverage: z.record(CoverageC),
  /** Stocks that pass every rule, across the whole day; `widget.universe` holds at most `limit` of them. */
  matched: z.number().int().nonnegative().nullable(),
  /** False when the day had more stocks than one read returns. */
  universe_complete: z.boolean(),
}).refine(
  // An answered run says how many stocks matched, and the rows agree with that
  // number: never more rows than matches, and rows whenever something matched.
  (r) => !r.ok || (r.matched !== null && r.widget.universe.length <= r.matched && (r.matched === 0 || r.widget.universe.length > 0)),
  { path: ["matched"], message: "the match count and the rows sent do not agree" },
);
export type ScreenRun = z.infer<typeof ScreenRunC>;

/**
 * One run of a screen. It is a read (a POST only because the rules travel in the
 * body), so it is a query: a failure shows in the results section and does not
 * raise the app's "a change failed" toast. `runId` changes on every press of
 * Run, so each press asks again; nothing is asked while `request` is null.
 */
export function useScreenRun(request: ScreenRunRequest | null, runId: number) {
  return useQuery({
    queryKey: ["screener-run", runId, request],
    enabled: request !== null,
    queryFn: async ({ signal }): Promise<ScreenRun> => {
      // The server waits up to 20 s for the data platform before answering ok:false,
      // so give it longer than the default 15 s.
      const res = await http({ method: "POST", path: "/api/screeners/run", body: request, timeoutMs: 30_000, noRetry: true, signal });
      return ScreenRunC.parse(res.data);
    },
    // One attempt (the results section has its own Retry), and the answer stays
    // what that run returned until the next run.
    retry: false,
    staleTime: Infinity,
  });
}
