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
        mutationFn: (goalId) => goalsService.simulate(goalId),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ["goals"] }); },
    });
}
export function useGoalWhatIf() {
    return useMutation({
        mutationFn: (args) => goalsService.whatIf(args.goalId, args.body),
    });
}
