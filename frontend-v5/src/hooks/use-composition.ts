/**
 * useComposition — fetches portfolio composition breakdown from
 * GET /api/portfolio/composition?dimension=&metric=&period=
 */
import { useQuery } from "@tanstack/react-query";
import { http } from "@/services/api/http";

export type CompositionDimension = "asset_class" | "sector" | "fund" | "group";
export type CompositionMetric    = "weight" | "invested" | "current";

export interface CompositionSegment {
  name:            string;
  weight_pct:      number;
  current_value:   number;
  invested:        number | null;
  pnl_pct:         number | null;
  metric_value:    number;
  breach:          boolean;
  breach_threshold:number;
}

export interface CompositionData {
  dimension:             CompositionDimension;
  metric:                CompositionMetric;
  period:                string | null;
  segments:              CompositionSegment[];
  totals:                { current_value: number; invested: number | null };
  concentration_breaches:Array<{ segment: string; weight_pct: number; threshold: number }>;
  threshold:             number;
}

export function useComposition(
  dimension: CompositionDimension,
  metric: CompositionMetric = "weight",
  period = "1Y",
) {
  return useQuery<CompositionData>({
    queryKey: ["composition", dimension, metric, period],
    queryFn: async () => {
      const res = await http({ path: "/api/portfolio/composition", query: { dimension, metric, period } });
      return res.data as CompositionData;
    },
    staleTime: 5 * 60 * 1000,
  });
}
