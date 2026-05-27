/**
 * use-mfd — Per-client workspace + v4 client-360 actions.
 *
 * Mutations invalidate the relevant query keys on success so the UI stays in
 * sync without an explicit refetch.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mfdService } from "@/services";
import { usePolling } from "@/lib/polling";
export function useMfdProfiles() {
    return useQuery({
        queryKey: ["mfd", "profiles"],
        queryFn: () => mfdService.listProfiles(),
    });
}
export function useActivateProfile() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (profileId) => mfdService.activateProfile(profileId),
        onSuccess: () => {
            // impersonation changes nearly every query result; clear server-state cache
            qc.invalidateQueries();
        },
    });
}
export function useDeactivateProfile() {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: () => mfdService.deactivateProfile(),
        onSuccess: () => { qc.invalidateQueries(); },
    });
}
export function useNeedsAttention(profileId) {
    return useQuery({
        queryKey: ["mfd", profileId, "needs-attention"],
        queryFn: () => mfdService.needsAttention(profileId),
        enabled: !!profileId,
    });
}
export function useLogCall(profileId) {
    const qc = useQueryClient();
    return useMutation({
        mutationFn: (body) => mfdService.callLog(profileId, body),
        onSuccess: () => { qc.invalidateQueries({ queryKey: ["mfd", profileId] }); },
    });
}
export function useSipNudge(profileId) {
    return useMutation({
        mutationFn: (body) => mfdService.sipNudge(profileId, body),
    });
}
/**
 * useReviewPack — fire-and-poll until COMPLETED or FAILED.
 *
 * Usage:
 *   const { generate, status, downloadUrl } = useReviewPack(profileId);
 *   generate({ sections: ["portfolio","goals","risk","performance"] });
 */
export function useReviewPack(profileId) {
    const qc = useQueryClient();
    const taskKey = ["mfd", profileId, "reviewPack", "task"];
    const generate = useMutation({
        mutationFn: (body) => mfdService.reviewPackGenerate(profileId, body),
        onSuccess: (data) => qc.setQueryData(taskKey, data),
    });
    const taskId = qc.getQueryData(taskKey)?.task_id;
    const polling = usePolling({
        queryKey: ["mfd", profileId, "reviewPack", "poll", taskId ?? ""],
        queryFn: () => mfdService.reviewPackPoll(profileId, taskId),
        isTerminal: (d) => d.status === "COMPLETED" || d.status === "FAILED",
        intervalMs: 2_000,
        enabled: !!taskId,
    });
    return {
        generate: generate.mutate,
        isGenerating: generate.isPending,
        status: polling.data?.status,
        downloadUrl: polling.data?.download_url,
        error: generate.error ?? polling.error,
    };
}
