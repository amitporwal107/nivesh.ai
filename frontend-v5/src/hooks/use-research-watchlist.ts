/**
 * Hook for the public Research Watchlist page (/watchlist).
 * Thin react-query wrapper over researchWatchlistService.list().
 */
import { useQuery } from "@tanstack/react-query";
import { researchWatchlistService } from "@/services";

export function useResearchWatchlist() {
  return useQuery({
    queryKey: ["research-watchlist"],
    queryFn: () => researchWatchlistService.list(),
    staleTime: 60 * 1000,
  });
}
