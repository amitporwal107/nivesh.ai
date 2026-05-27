/**
 * use-goals — wired to goals service.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { goalsService } from "@/services";

export function useGoals() {
  return useQuery({
    queryKey: ["goals", "list"],
    queryFn: () => goalsService.list(),
  });
}

export function useGoalsSnapshot() {
  return useQuery({
    queryKey: ["goals", "snapshot"],
    queryFn: () => goalsService.getSnapshot(),
  });
}

export function useGoalSimulate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (goalId: string) => goalsService.simulate(goalId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); },
  });
}

export function useGoalWhatIf() {
  return useMutation({
    mutationFn: (args: { goalId: string; body: { monthly_sip_rs?: number; horizon_years?: number; current_corpus_rs?: number } }) =>
      goalsService.whatIf(args.goalId, args.body),
  });
}
