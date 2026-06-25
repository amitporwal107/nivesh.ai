/**
 * use-dashboards — v4 unified envelope per screen.
 *
 * Six domains, one shape. Pass the lens/period via `params` — backend ignores
 * unknowns so over-passing is safe.
 *
 *   useDashboard("concentration", { lens: "sector" })
 *   useDashboard("performance",   { period: "3y" })
 */
import { useQuery } from "@tanstack/react-query";
import { dashboardsService, type DashboardDomain } from "@/services";

export function useDashboard(
  domain: DashboardDomain,
  params?: Record<string, string | number>,
) {
  return useQuery({
    queryKey: ["dashboards", domain, params ?? {}],
    queryFn: () => dashboardsService.fetch(domain, params),
    staleTime: 24 * 60 * 60 * 1000, // 24 h — backend Redis cache is the source of truth
    gcTime: 24 * 60 * 60 * 1000,
  });
}
