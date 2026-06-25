/**
 * use-mfd — Per-client workspace + v4 client-360 actions.
 *
 * Mutations invalidate the relevant query keys on success so the UI stays in
 * sync without an explicit refetch.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { mfdService } from "@/services";
import { usePolling } from "@/lib/polling";
import { useImpersonationStore } from "@/stores/impersonation.store";
import type { CallOutcome, ReviewPackSection, ReviewPackStatus, SipNudgeTemplate } from "@/services/adapters/mfd.adapter";

export function useMfdProfiles() {
  return useQuery({
    queryKey: ["mfd", "profiles"],
    queryFn: () => mfdService.listProfiles(),
  });
}

/**
 * Open a client = start per-request impersonation. There is NO backend
 * round-trip: the active client is carried on every request as the
 * X-Active-Profile header, sourced from the impersonation store (see http.ts).
 * We set the store FIRST so the subsequent invalidation refetches every query
 * in the client's context. The backend validates ownership per request.
 */
export function useActivateProfile() {
  const qc = useQueryClient();
  const setImpersonating = useImpersonationStore((s) => s.setImpersonating);
  return useMutation({
    mutationFn: async (args: { profileId: string; name: string }) => {
      setImpersonating(args.profileId, args.name);
      return { ok: true };
    },
    onSuccess: () => {
      // impersonation changes nearly every query result; clear server-state cache
      qc.invalidateQueries();
    },
  });
}

export function useDeactivateProfile() {
  const qc = useQueryClient();
  const clear = useImpersonationStore((s) => s.clear);
  return useMutation({
    mutationFn: async () => { clear(); return { ok: true }; },
    onSuccess: () => { qc.invalidateQueries(); },
  });
}

export function useNeedsAttention(profileId: string) {
  return useQuery({
    queryKey: ["mfd", profileId, "needs-attention"],
    queryFn: () => mfdService.needsAttention(profileId),
    enabled: !!profileId,
  });
}

export function useLogCall(profileId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { notes: string; outcome: CallOutcome; next_followup_date?: string }) =>
      mfdService.callLog(profileId, body),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mfd", profileId] }); },
  });
}

export function useSipNudge(profileId: string) {
  return useMutation({
    mutationFn: (body: { fund_name: string; proposed_amount?: number; template?: SipNudgeTemplate }) =>
      mfdService.sipNudge(profileId, body),
  });
}

/**
 * useReviewPack — fire-and-poll until COMPLETED or FAILED.
 *
 * Usage:
 *   const { generate, status, downloadUrl } = useReviewPack(profileId);
 *   generate({ sections: ["portfolio","goals","risk","performance"] });
 */
export function useReviewPack(profileId: string) {
  const qc = useQueryClient();
  const taskKey = ["mfd", profileId, "reviewPack", "task"] as const;

  const generate = useMutation({
    mutationFn: (body: { sections: ReviewPackSection[] }) =>
      mfdService.reviewPackGenerate(profileId, body),
    onSuccess: (data) => qc.setQueryData(taskKey, data),
  });

  const taskId = (qc.getQueryData(taskKey) as { task_id?: string } | undefined)?.task_id;

  const polling = usePolling<{ task_id: string; status: ReviewPackStatus; download_url?: string }>({
    queryKey: ["mfd", profileId, "reviewPack", "poll", taskId ?? ""],
    queryFn: () => mfdService.reviewPackPoll(profileId, taskId!),
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
