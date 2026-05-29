/**
 * use-analytics — all methods via the adapter factory (real or mock).
 */
import { useQuery } from "@tanstack/react-query";
import { analyticsService } from "@/services";

export function useConcentration() {
  return useQuery({
    queryKey: ["analytics", "concentration"],
    queryFn: () => analyticsService.concentration(),
  });
}

export function useCorrelation() {
  return useQuery({
    queryKey: ["analytics", "correlation"],
    queryFn: () => analyticsService.correlation(),
  });
}

export function useOverlap() {
  return useQuery({
    queryKey: ["analytics", "overlap"],
    queryFn: () => analyticsService.overlap(),
  });
}

export function useRisk() {
  return useQuery({
    queryKey: ["analytics", "risk"],
    queryFn: () => analyticsService.risk(),
  });
}

export function useConcentrationAnalysis() {
  return useQuery({
    queryKey: ["analytics", "concentration-analysis"],
    queryFn: () => import("@/services/api/http").then(({ http }) =>
      Promise.all([
        http({ path: "/api/portfolio/exposure/concentration" }),
        http({ path: "/api/portfolio/exposure/fund-overlap/matrix" }).catch(() => ({ data: null })),
      ]).then(([conc, overlap]) => ({ concentration: conc.data, overlap: (overlap as { data: unknown }).data }))
    ),
    staleTime: 5 * 60 * 1000,
  });
}
