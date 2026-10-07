/**
 * Hook for the public Research Watchlist page (/watchlist).
 * Thin react-query wrapper over researchWatchlistService.list().
 *
 * Polls every 30s to match the backend's live-quote cache TTL (30s during
 * NSE market hours — see research_watchlist_live.py) so the page tracks a
 * live watchlist, not a static daily snapshot. Paused when the tab isn't
 * focused so a backgrounded tab doesn't keep polling for nothing.
 */
import { useQuery } from "@tanstack/react-query";
import { researchWatchlistService } from "@/services";

export function useResearchWatchlist() {
  return useQuery({
    queryKey: ["research-watchlist"],
    queryFn: () => researchWatchlistService.list(),
    staleTime: 20 * 1000,
    refetchInterval: 30 * 1000,
    refetchIntervalInBackground: false,
  });
}
