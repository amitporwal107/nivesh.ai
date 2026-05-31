import { useQuery } from "@tanstack/react-query";
import { plansService } from "@/services";
import type { PlanC } from "@/services/contracts/plan.contract";

export function useActivePlan() {
  return useQuery<PlanC | null>({
    queryKey: ["plans", "active"],
    queryFn: () => plansService.getActive(),
    staleTime: 30_000,
  });
}

/** Returns gate flags from the active plan (undefined while loading). */
export function useGateFlags() {
  const q = useActivePlan();
  return {
    requiresPersona: q.data?.gate_flags?.requires_persona ?? false,
    requiresGoal: q.data?.gate_flags?.requires_goal ?? false,
    capacityToleranceDiverged: q.data?.gate_flags?.capacity_tolerance_diverged ?? false,
    isLoading: q.isPending,
  };
}
