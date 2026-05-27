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
import { dashboardsService } from "@/services";
export function useDashboard(domain, params) {
    return useQuery({
        queryKey: ["dashboards", domain, params ?? {}],
        queryFn: () => dashboardsService.fetch(domain, params),
    });
}
