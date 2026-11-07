/**
 * Approval queue — TanStack queries and the decision mutation. Every key starts with "desk" so that one
 * invalidateQueries({ queryKey: ["desk"] }) after a decision refreshes the queue, the shell's badge and the detail.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { deskGet, deskPost } from "../../api";
import type { ApprovalRow, RiskAssessmentRow, TradePlanDetail, TradePlanRow } from "../../types";
import type { PlanVersionRow, PortfolioResponse, SignalLite } from "./model";

export const planQuery = (tradeId: string, version: number) => ({
  queryKey: ["desk", "plan", tradeId, version] as const,
  queryFn: () => deskGet<TradePlanDetail>(`/trade-plans/${encodeURIComponent(tradeId)}`, { version }),
});

/** Recent approval rows (desk + simulations); the screen keeps the decided desk ones. */
export function useRecentApprovals() {
  return useQuery({
    queryKey: ["desk", "approvals", "recent"],
    queryFn: () => deskGet<ApprovalRow[]>("/approvals", { limit: 100 }),
    refetchInterval: 30_000,
  });
}

/** Plan heads of the desk (instrument / strategy of decided rows). */
export function usePlanHeads(enabled: boolean) {
  return useQuery({ queryKey: ["desk", "trade-plans", "heads"], queryFn: () => deskGet<TradePlanRow[]>("/trade-plans", { limit: 200 }), enabled });
}

export function useApproval(id: string | null) {
  return useQuery({ queryKey: ["desk", "approval", id], queryFn: () => deskGet<ApprovalRow>(`/approvals/${encodeURIComponent(id!)}`), enabled: !!id });
}

export function usePlan(tradeId: string | undefined, version: number | undefined) {
  return useQuery({ ...planQuery(tradeId ?? "", version ?? 0), enabled: !!tradeId && !!version });
}

export function usePlanVersions(tradeId: string | undefined) {
  return useQuery({
    queryKey: ["desk", "plan-versions", tradeId],
    queryFn: () => deskGet<PlanVersionRow[]>(`/trade-plans/${encodeURIComponent(tradeId!)}/versions`),
    enabled: !!tradeId,
  });
}

export function useAssessment(id: string | null | undefined) {
  return useQuery({
    queryKey: ["desk", "risk", id],
    queryFn: () => deskGet<RiskAssessmentRow>(`/risk/assessments/${encodeURIComponent(id!)}`),
    enabled: !!id,
  });
}

export function usePortfolio(accountId: string | null | undefined) {
  return useQuery({
    queryKey: ["desk", "portfolio", accountId],
    queryFn: () => deskGet<PortfolioResponse>(`/risk/portfolio/${encodeURIComponent(accountId!)}`),
    enabled: !!accountId,
  });
}

export function useSignal(id: string | null | undefined) {
  return useQuery({
    queryKey: ["desk", "signal", id],
    queryFn: () => deskGet<SignalLite>(`/signals/${encodeURIComponent(id!)}`),
    enabled: !!id,
  });
}

export type Decision = "APPROVE" | "REJECT" | "REQUEST_REVISION";

/**
 * POST /approvals/{id}/decision with {decision, reason, plan_hash}. plan_hash is the hash of the plan version the
 * request binds (GET /trade-plans/{id}?version=<plan_version>); the API refuses the decision if it no longer matches.
 */
export function useDecide(approvalId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { decision: Decision; reason: string; plan_hash: string }) =>
      deskPost<ApprovalRow>(`/approvals/${encodeURIComponent(approvalId!)}/decision`, { decision: v.decision, reason: v.reason, plan_hash: v.plan_hash }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}
