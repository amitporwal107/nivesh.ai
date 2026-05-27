/**
 * use-insights — now backed by the canonical endpoints:
 *
 *   useHealthAnalysis()    → /api/insights/analysis  · portfolio Health Score 0-100
 *   useV3Portfolio()       → /api/insights/v3-portfolio  · per-fund V3 (0-100/fund)
 *   useInsightsList()      → /api/insights  · cached insights list + counts
 *   useGenerateInsights()  → POST /api/insights/generate  · force refresh
 *
 * Earlier draft mixed health-score and v3-portfolio — they are distinct
 * resources in the real backend and shouldn't share a hook.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { insightsService } from "@/services";
export function useHealthAnalysis() {
    return useQuery({
        queryKey: ["insights", "analysis"],
        queryFn: () => insightsService.analysis(),
    });
}
/** Back-compat alias — existing screens calling `useV3Portfolio` keep working. */
export const useV3Portfolio = useHealthAnalysis;
export function useV3FundScores(refreshStocks = false) {
    return useQuery({
        queryKey: ["insights", "v3-portfolio", refreshStocks],
        queryFn: () => insightsService.v3Portfolio(refreshStocks),
    });
}
export function useInsightsList() {
    return useQuery({
        queryKey: ["insights", "list"],
        queryFn: () => insightsService.list(),
    });
}
export function useGenerateInsights() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => insightsService.regenerate(),
        onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
    });
}
