/**
 * Hook for the public Research Watchlist page (/watchlist).
 * Thin react-query wrapper over researchWatchlistService.list(listDate) —
 * `listDate` (YYYY-MM-DD) selects an earlier list, undefined the newest.
 *
 * Polls every 30s to match the backend's live-quote cache TTL (30s during
 * NSE market hours — see research_watchlist_live.py) so the page tracks a
 * live watchlist, not a static daily snapshot. Paused when the tab isn't
 * focused so a backgrounded tab doesn't keep polling for nothing.
 */
import { useQuery } from "@tanstack/react-query";
import { researchWatchlistService } from "@/services";
import { ApiError } from "@/services/api/errors";

export function useResearchWatchlist(listDate?: string) {
  return useQuery({
    queryKey: ["research-watchlist", listDate ?? "latest"],
    queryFn: () => researchWatchlistService.list(listDate),
    // No list was published for that date — asking again will not change that.
    retry: (count, err) => !(err instanceof ApiError && err.status === 404) && count < 2,
    // Keep the list on screen while another date loads, so the picker does not blink out.
    placeholderData: (prev) => prev,
    staleTime: 20 * 1000,
    refetchInterval: 30 * 1000,
    refetchIntervalInBackground: false,
  });
}
