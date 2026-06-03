/**
 * use-intelligence — portfolio look-through, stock overlap, V3 fund scores.
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { intelligenceService } from "@/services";

export function useIntelligencePortfolio(narrate = true) {
  return useQuery({
    queryKey: ["intelligence", "portfolio", narrate],
    queryFn: () => intelligenceService.portfolio(narrate),
  });
}

export function useIntelligenceSimulate() {
  return useMutation({
    mutationFn: (removeIds: string[]) => intelligenceService.simulate(removeIds),
  });
}

export function useV3FundScore(instrumentId: string) {
  return useQuery({
    queryKey: ["intelligence", "v3-score", instrumentId],
    queryFn: () => intelligenceService.v3Score(instrumentId),
    enabled: !!instrumentId,
  });
}
