/**
 * use-markets — Markets home dashboard data.
 *
 * Refetches every 60s so the dashboard tracks the live tape during market
 * hours (the backend itself caches 30s open / 5min closed).
 */
import { useQuery } from "@tanstack/react-query";
import { marketsService } from "@/services";

export function useMarketsHome() {
  return useQuery({
    queryKey: ["markets", "home"],
    queryFn: () => marketsService.getHome(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}
