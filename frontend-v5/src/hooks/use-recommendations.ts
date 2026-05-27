/**
 * use-recommendations — wired to plans service.
 *
 * The backend's Plan.actions array IS the recommendations list. The mapper
 * inside `plansService.getRecommendations` translates plan actions into
 * Keep/Reduce/Add cards.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { plansService } from "@/services";
import type { RecAction } from "@/types/recommendation";

export function useRecommendations(action?: RecAction) {
  return useQuery({
    queryKey: ["recommendations", action ?? "all"],
    queryFn: async () => {
      const all = await plansService.getRecommendations();
      return action ? all.filter((r) => r.action === action) : all;
    },
  });
}

export function useApplyRecommendation(planId?: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (actionId: string) => {
      if (!planId) {
        // optimistic-only when no real plan ID yet (mock mode pre-API-wire)
        return { actionId };
      }
      await plansService.updateActionStatus(planId, actionId, "done");
      return { actionId };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["recommendations"] });
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["portfolio"] });
    },
  });
}
