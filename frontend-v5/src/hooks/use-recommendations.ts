/**
 * use-recommendations — wired to plans service.
 *
 * The backend's Plan.actions array IS the recommendations list. The mapper
 * inside `plansService.getRecommendations` translates plan actions into
 * Keep/Reduce/Add cards.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { plansService } from "@/services";
export function useRecommendations() {
  return useQuery({
    queryKey: ["recommendations"],
    queryFn: () => plansService.getRecommendations(),
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
