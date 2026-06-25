/**
 * use-markets — Market Pulse data hooks.
 *
 * The Market tab (home) refetches every 60s so it tracks the live tape during
 * market hours (the backend itself caches 30s open / 5min closed). The FII/DII
 * and corporate-action feeds are EOD, so they use longer stale times.
 */
import { useQuery } from "@tanstack/react-query";
import { marketsService } from "@/services";
import type { CapSegment, CorpActionsQuery, ArticlesQuery } from "@/services/adapters/markets.adapter";

export function useMarketsHome() {
  return useQuery({
    queryKey: ["markets", "home"],
    queryFn: () => marketsService.getHome(),
    refetchInterval: 60_000,
    staleTime: 30_000,
  });
}

/** Explore lists (52w high/low, most active). Fetched only when opened. */
export function useMarketsExplore(enabled: boolean) {
  return useQuery({
    queryKey: ["markets", "explore"],
    queryFn: () => marketsService.getExplore(),
    enabled,
    staleTime: 5 * 60_000,
  });
}

/** Top gainers / losers for one market-cap segment (large | mid | small). */
export function useMarketsMovers(cap: CapSegment) {
  return useQuery({
    queryKey: ["markets", "movers", cap],
    queryFn: () => marketsService.getMovers(cap),
    staleTime: 60_000,
  });
}

/** FII/DII cash-segment flows — daily series + monthly aggregates. */
export function useMarketsFiiDii(days = 90) {
  return useQuery({
    queryKey: ["markets", "fii-dii", days],
    queryFn: () => marketsService.getFiiDii(days),
    staleTime: 5 * 60_000,
  });
}

/** Corporate-action calendar, filterable by date range / type / search. */
export function useCorporateActions(params: CorpActionsQuery) {
  return useQuery({
    queryKey: ["markets", "corp-actions", params],
    queryFn: () => marketsService.getCorporateActions(params),
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

/** Stock-market news & analysis — classified filings, filterable. */
export function useArticles(params: ArticlesQuery) {
  return useQuery({
    queryKey: ["markets", "articles", params],
    queryFn: () => marketsService.getArticles(params),
    staleTime: 5 * 60_000,
    placeholderData: (prev) => prev,
  });
}

/** Daily Iris Update — the persisted grounded brief (today, or a past date). */
export function useDailyBrief(date?: string) {
  return useQuery({
    queryKey: ["markets", "daily-brief", date ?? "today"],
    queryFn: () => marketsService.getDailyBrief(date),
    staleTime: 5 * 60_000,
  });
}

/** Past briefs for the archive selector. */
export function useBriefHistory(limit = 30) {
  return useQuery({
    queryKey: ["markets", "brief-history", limit],
    queryFn: () => marketsService.getBriefHistory(limit),
    staleTime: 5 * 60_000,
  });
}
