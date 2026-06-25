/**
 * use-portfolio — React Query hooks wired to the services factory.
 *
 * Mock vs real is decided by env flag; hooks don't know which is in use.
 */
import { useQuery } from "@tanstack/react-query";
import { portfolioService } from "@/services";

export function usePortfolioSummary() {
  return useQuery({
    queryKey: ["portfolio", "summary"],
    queryFn: () => portfolioService.getSummary(),
  });
}

export function usePortfolioNavHistory(range: "1m" | "3m" | "6m" | "1y" | "all" = "1y") {
  return useQuery({
    queryKey: ["portfolio", "navHistory", range],
    queryFn: () => portfolioService.getNavHistory(range),
  });
}

export function useHoldings(portfolioId?: string, assetType?: string) {
  return useQuery({
    queryKey: ["portfolio", "holdings", portfolioId ?? "all", assetType ?? "all"],
    queryFn: () => portfolioService.listHoldings(portfolioId, assetType),
  });
}

/** Enriched holdings (V3 scores, badges, weight/XIRR/benchmark) + totals + allocation.
 *  This is the shape HoldingsTable and the Portfolio page actually render. */
export function useHoldingsEnriched() {
  return useQuery({
    queryKey: ["portfolio", "enriched"],
    queryFn: () => portfolioService.listHoldingsEnriched(),
  });
}

/** Detected SIPs from the CAS statement (authoritative source for the SIPs tab). */
export function usePortfolioSips() {
  return useQuery({
    queryKey: ["portfolio", "sips"],
    queryFn: () => portfolioService.listSips(),
  });
}

/** AMC / sector / company look-through for the Allocation tab. */
export function usePortfolioConcentration() {
  return useQuery({
    queryKey: ["portfolio", "concentration"],
    queryFn: () => portfolioService.getConcentration(),
  });
}
