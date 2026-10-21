/**
 * Best picks from the user's Chartink scans - the hook.
 *
 *   useChartinkPicks()   GET /api/desk/chartink/picks?limit=5   stale after 5 minutes, never polled; runs only for a connected dashboard
 *
 * The route reads the stored hits and the plan sources (a few seconds: it builds one plan per candidate) and writes nothing. One query serves the
 * Chartink settings, the Overview card (which shows the first 3) and the Strategy Builder's ideas board, so they always agree. A failure is shown with
 * a Retry button; nothing here ranks, scores or edits a pick.
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { PicksSchema, type ChartinkPicks } from "./picks-contract";
import { useChartinkSource } from "./chartink-data";

export const CHARTINK_PICKS_PATH = "/api/desk/chartink/picks";
export const PICKS_LIMIT = 5;

export function useChartinkPicks() {
  const source = useChartinkSource();
  return useQuery<ChartinkPicks>({
    queryKey: ["copilot", "desk", "chartink", "picks", PICKS_LIMIT],
    // Only once a dashboard is known to be connected: without one the route has only "no source" to say.
    enabled: source.data != null,
    staleTime: 5 * 60_000,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `${CHARTINK_PICKS_PATH}?limit=${PICKS_LIMIT}`, signal, noRetry: true });
      const r = PicksSchema.safeParse(res.data);
      if (!r.success) throw new ApiError("contract_drift", "The Chartink best picks were not in the expected form.", { cause: r.error });
      return r.data;
    },
  });
}
