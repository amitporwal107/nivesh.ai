/**
 * Queries and writes of the Policies & permissions screen (screen 12):
 *   GET  /policies                         — the tenant's policies (the API creates the default on first use)
 *   GET  /policies/{id}[?version=n]        — a policy version (body = PolicyBody)
 *   POST /accounts/{id}/mode               — {mode, reason}: operating mode change, audited
 *   POST /policies/{id}/versions           — {changes, reason}: a new policy version (403 when a non-admin loosens)
 * Query keys start with "desk" so the shell's invalidate after a write refreshes them too.
 */
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { deskGet, deskPost } from "../../api";
import type { Account, IsoTime, OperatingMode, PolicyDetail } from "../../types";

export interface PolicyRow {
  policy_id: string;
  tenant_id?: string;
  name: string;
  scope_type: "TENANT" | "ACCOUNT" | "STRATEGY" | "SEGMENT" | string;
  scope_ref: string | null;
  current_version: number;
  created_at: IsoTime;
  updated_at?: IsoTime;
}

/** History shown per policy: the newest versions. */
export const HISTORY_DEPTH = 8;

export function usePolicies() {
  return useQuery({ queryKey: ["desk", "policies"], queryFn: () => deskGet<PolicyRow[]>("/policies") });
}

/** The current version of each listed policy. */
export function usePolicyDetails(rows: PolicyRow[]) {
  return useQueries({
    queries: rows.map((p) => ({
      queryKey: ["desk", "policies", p.policy_id, "current", p.current_version],
      queryFn: () => deskGet<PolicyDetail>(`/policies/${encodeURIComponent(p.policy_id)}`),
    })),
  });
}

/** Older versions (current − 1 … current − HISTORY_DEPTH + 1) of each policy. Versions never change once written. */
export function usePolicyHistory(rows: PolicyRow[]) {
  const wanted = rows.flatMap((p) => {
    const out: { policy_id: string; version: number }[] = [];
    for (let v = p.current_version - 1; v >= 1 && v > p.current_version - HISTORY_DEPTH; v--) out.push({ policy_id: p.policy_id, version: v });
    return out;
  });
  const qs = useQueries({
    queries: wanted.map((w) => ({
      queryKey: ["desk", "policies", w.policy_id, "version", w.version],
      queryFn: () => deskGet<PolicyDetail>(`/policies/${encodeURIComponent(w.policy_id)}`, { version: w.version }),
      staleTime: Infinity,
    })),
  });
  return wanted.map((w, i) => ({ ...w, q: qs[i] }));
}

export function useSetMode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { accountId: string; mode: OperatingMode; reason: string }) =>
      deskPost<Account>(`/accounts/${encodeURIComponent(v.accountId)}/mode`, { mode: v.mode, reason: v.reason }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["desk"] }),
  });
}

export function useNewPolicyVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { policyId: string; changes: Record<string, unknown>; reason: string }) =>
      deskPost<{ policy_id: string; version: number; body: Record<string, unknown> }>(
        `/policies/${encodeURIComponent(v.policyId)}/versions`, { changes: v.changes, reason: v.reason }),
    // Not awaited: the save is finished once the API accepts it. Waiting for the refresh let the new version empty the
    // version-keyed policy query first, which unmounted the dialog and dropped its close callback (AD-UI-74b).
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["desk"] }); },
  });
}

export const MODE_OPTIONS: { mode: OperatingMode | "AUTONOMOUS_LIVE"; label: string }[] = [
  { mode: "RESEARCH", label: "Research" },
  { mode: "ASSISTED", label: "Assisted" },
  { mode: "AUTONOMOUS_PAPER", label: "Autonomous paper" },
  { mode: "AUTONOMOUS_LIVE", label: "Autonomous live" },
];

/** What each mode lets the desk do — from the Middle Office rules (backend/autodesk/agents/middle_office.py). */
export const MODE_NOTE: Record<OperatingMode, string> = {
  RESEARCH: "Research: agents publish signals, draft plans and risk reports; nothing is approved.",
  ASSISTED: "Assisted: every plan that passes the risk check comes to you for approval.",
  AUTONOMOUS_PAPER: "Autonomous paper: the Middle Office approves plans inside the policy's autonomy rules and sends the rest to you. Paper only.",
};
