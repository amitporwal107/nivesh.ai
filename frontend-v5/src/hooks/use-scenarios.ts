/**
 * use-scenarios — what-if simulator + rebalancing.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { scenariosService, type ScenarioSimulateBody } from "@/services";

export function useScenarioSuggestions() {
  return useQuery({
    queryKey: ["scenarios", "suggest"],
    queryFn: () => scenariosService.suggest(),
  });
}

export function useScenarioSimulate() {
  return useMutation({
    mutationFn: (body: ScenarioSimulateBody) => scenariosService.simulate(body),
  });
}

export function useScenarioRebalancePlan() {
  return useMutation({
    mutationFn: (body: ScenarioSimulateBody) => scenariosService.rebalancePlan(body),
  });
}

export function useApplyScenario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (args: { scenario_id: string; actions: unknown[]; payload: unknown }) =>
      scenariosService.apply(args),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["plans"] });
      qc.invalidateQueries({ queryKey: ["scenarios"] });
    },
  });
}

export function useSavedScenarios() {
  return useQuery({
    queryKey: ["scenarios", "saved"],
    queryFn: () => scenariosService.listSaved(),
  });
}

export function usePendingPlans() {
  return useQuery({
    queryKey: ["scenarios", "pending"],
    queryFn: () => scenariosService.listPending(),
  });
}
