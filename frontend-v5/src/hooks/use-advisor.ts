/**
 * use-advisor — Advisor Home book/AUM/underperformers/rebalance + v4 summary & SIP board.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { advisorService } from "@/services";

/**
 * useAdvisorBook — the client book + workspace from GET /api/mfd/profiles.
 * One fetch powers the ADVISORY-mode gate, the header stats, and the table.
 */
export function useAdvisorBook(includeSelf = true) {
  return useQuery({
    queryKey: ["advisor", "book", includeSelf],
    queryFn: () => advisorService.listProfiles(includeSelf),
  });
}

export function useCreateClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Parameters<typeof advisorService.createProfile>[0]) =>
      advisorService.createProfile(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["advisor"] });
      qc.invalidateQueries({ queryKey: ["mfd"] });
    },
  });
}

export function useDeleteClient() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (profileId: string) => advisorService.deleteProfile(profileId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["advisor"] });
      qc.invalidateQueries({ queryKey: ["mfd"] });
    },
  });
}

/** Flip the workspace INDIVIDUAL → ADVISORY (mirrors the v2 upgrade card). */
export function useUpgradeToAdvisory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      advisorService.workspaceUpdate({ mode: "ADVISORY", mfd_onboarding_completed: false }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["advisor"] }); },
  });
}

export function useAdvisorSummary() {
  return useQuery({
    queryKey: ["advisor", "summary"],
    queryFn: () => advisorService.summary(),
  });
}

export function useAdvisorToday(limit = 100) {
  return useQuery({
    queryKey: ["advisor", "today", limit],
    queryFn: () => advisorService.today(limit),
  });
}

export function useAdvisorAum(limit = 100) {
  return useQuery({
    queryKey: ["advisor", "aum", limit],
    queryFn: () => advisorService.aum(limit),
  });
}

export function useAdvisorUnderperformers(gapPct?: number, benchmark?: string) {
  return useQuery({
    queryKey: ["advisor", "underperformers", gapPct ?? 5, benchmark ?? "nifty_50"],
    queryFn: () => advisorService.underperformers(gapPct, benchmark),
  });
}

export function useAdvisorRebalance(gapPp?: number) {
  return useQuery({
    queryKey: ["advisor", "rebalance", gapPp ?? 10],
    queryFn: () => advisorService.rebalance(gapPp),
  });
}

export function useSipBoard(state?: string, cycle?: string) {
  return useQuery({
    queryKey: ["advisor", "sipBoard", state ?? "all", cycle ?? "current"],
    queryFn: () => advisorService.sipBoard(state, cycle),
  });
}

export function useSipBoardSummary() {
  return useQuery({
    queryKey: ["advisor", "sipBoard", "summary"],
    queryFn: () => advisorService.sipBoardSummary(),
  });
}
