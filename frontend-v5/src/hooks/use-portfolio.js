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
export function usePortfolioNavHistory(range = "1y") {
    return useQuery({
        queryKey: ["portfolio", "navHistory", range],
        queryFn: () => portfolioService.getNavHistory(range),
    });
}
export function useHoldings(portfolioId, assetType) {
    return useQuery({
        queryKey: ["portfolio", "holdings", portfolioId ?? "all", assetType ?? "all"],
        queryFn: () => portfolioService.listHoldings(portfolioId, assetType),
    });
}
