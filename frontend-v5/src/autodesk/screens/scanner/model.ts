/**
 * Data and view model of the Opportunity scanner (design: docs/autodesk/design/prototype/TDScanner.dc.html).
 *
 * Sources (backend/autodesk/routers/api.py):
 *   GET /desk/workflows?account_id&kind=SESSION_CYCLE   the account's cycles; the newest is the session on screen. Its
 *                                                       outcome.scan = {universe, universe_size, scanned, signals,
 *                                                       suppressed, scan_task_id, data_as_of, rule_version};
 *                                                       outcome.proposals = {candidates, proposed, results[], held_back?}
 *   GET /desk/workflows/{id}                            polled while a cycle runs
 *   GET /signals?account_id&session_date&limit          the session's desk signals, best score first
 *   GET /trade-plans?account_id                         plan per signal (signal_id)
 *   GET /approvals                                      latest approval per plan (desk rows only)
 *   GET /policies/{id}?version=                         the policy pinned in the cycle (min_signal_score)
 *   POST /desk/workflows {kind: "SESSION_CYCLE", account_id}   start a cycle (202 → the workflow)
 */
import { useMutation, useQuery } from "@tanstack/react-query";
import { deskGet, deskPost } from "../../api";
import { DASH, humanize, num } from "../../format";
import { screenById } from "../../nav";
import type { ApprovalRow, PolicyDetail, ScoreDimension, SignalRow, TradePlanRow, WorkflowRow } from "../../types";
import { shortId } from "./fmt";

export const OPEN_WF = new Set(["CREATED", "RUNNING"]);

export interface ScanSummary {
  universe?: string;
  universe_size?: number;
  scanned?: number;
  signals?: number;
  suppressed?: number;
  scan_task_id?: string;
  data_as_of?: string;
  rule_version?: string;
}

export interface ProposalsSummary {
  candidates?: number;
  proposed?: number;
  results?: { workflow_id: string; instrument: string; state: string; result: string | null }[];
  held_back?: string;
}

export interface CycleOutcome {
  premarket?: { status?: string; allowed_segments?: string[]; reason?: string; [k: string]: unknown };
  scan?: ScanSummary;
  proposals?: ProposalsSummary;
  result?: string;
  error?: string;
}

export const outcomeOf = (w: WorkflowRow | null | undefined): CycleOutcome => (w?.outcome ?? {}) as CycleOutcome;

// ── queries ─────────────────────────────────────────────────────────────────────────────────────────────────────────

/** The account's desk session cycles, newest first. */
export function useCycles(accountId: string | null) {
  return useQuery({
    queryKey: ["desk", "workflows", accountId ?? "", "SESSION_CYCLE"],
    queryFn: async () => {
      const rows = await deskGet<WorkflowRow[]>("/desk/workflows", { account_id: accountId, kind: "SESSION_CYCLE", limit: 500 });
      return rows.filter((w) => !w.simulation_id).sort((a, b) => (b.created_at > a.created_at ? 1 : b.created_at < a.created_at ? -1 : 0));
    },
    enabled: !!accountId,
    refetchInterval: 30_000,
  });
}

export function useSessionSignals(accountId: string | null, session: string | null) {
  return useQuery({
    queryKey: ["desk", "signals", accountId ?? "", session ?? ""],
    queryFn: () => deskGet<SignalRow[]>("/signals", { account_id: accountId, session_date: session, limit: 2000 }),
    enabled: !!accountId && !!session,
  });
}

export function useAccountPlans(accountId: string | null) {
  return useQuery({
    queryKey: ["desk", "plans", accountId ?? ""],
    queryFn: () => deskGet<TradePlanRow[]>("/trade-plans", { account_id: accountId, limit: 500 }),
    enabled: !!accountId,
  });
}

/** All desk approval rows, newest first (simulation rows left out). */
export function useDeskApprovals() {
  return useQuery({
    queryKey: ["desk", "approvals", "all"],
    queryFn: async () => (await deskGet<ApprovalRow[]>("/approvals", { limit: 500 })).filter((a) => !a.simulation_id),
  });
}

export function usePolicyVersion(policyId: string | null, version: number | null) {
  return useQuery({
    queryKey: ["desk", "policy", policyId ?? "", version ?? 0],
    queryFn: () => deskGet<PolicyDetail>(`/policies/${encodeURIComponent(policyId ?? "")}`, { version }),
    enabled: !!policyId,
    staleTime: 10 * 60_000,
  });
}

/** POST /desk/workflows — the body is exactly WorkflowIn's required fields for a session cycle (extra fields are refused). */
export function useRunCycle() {
  return useMutation({
    mutationFn: (accountId: string) => deskPost<WorkflowRow>("/desk/workflows", { kind: "SESSION_CYCLE", account_id: accountId }),
  });
}

// ── view model ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** The eight scored dimensions of ait-rules-v1 (agents/ai_trader.py WEIGHTS), labelled as the design names them. */
export const DIM_LABEL: Record<string, string> = {
  trend: "Trend confirmation",
  momentum: "Momentum",
  volume_delivery: "Volume and delivery",
  relative_strength: "Relative strength",
  structure: "Market structure",
  derivatives: "Derivatives confirmation",
  regime: "Market regime",
  liquidity: "Liquidity",
};
const DIM_ORDER = Object.keys(DIM_LABEL);

const n1 = (v: unknown): string => {
  const n = num(v);
  if (n == null) return DASH;
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
};

export interface DimView { key: string; k: string; v: string; w: string; available: boolean; detail: string }

export function dims(sig: SignalRow): DimView[] {
  const rows = [...(sig.body?.score_breakdown ?? [])] as ScoreDimension[];
  rows.sort((a, b) => {
    const ia = DIM_ORDER.indexOf(a.dimension), ib = DIM_ORDER.indexOf(b.dimension);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib);
  });
  return rows.map((d) => {
    const w = num(d.weight), p = num(d.points);
    const ok = d.available !== false;
    return {
      key: d.dimension,
      k: DIM_LABEL[d.dimension] ?? humanize(d.dimension),
      v: ok ? `${n1(d.points)}/${n1(d.weight)}` : `—/${n1(d.weight)}`,
      w: ok && w && p != null ? `${Math.max(0, Math.min(100, (p / w) * 100)).toFixed(0)}%` : "0%",
      available: ok,
      detail: d.detail ?? "",
    };
  });
}

/** The OI / volume confirmation the design puts in its own column: the agent's derivatives detail, else its volume detail. */
export function confirmation(sig: SignalRow): string {
  const b = sig.body?.score_breakdown ?? [];
  const d = b.find((x) => x.dimension === "derivatives");
  if (d && d.available !== false && d.detail) return d.detail;
  const v = b.find((x) => x.dimension === "volume_delivery");
  if (v && v.available !== false && v.detail) return v.detail;
  return DASH;
}

export const scoreColor = (s: number): string => (s >= 70 ? "var(--mint)" : s >= 55 ? "var(--amber)" : "var(--ink-4)");

export const DIR_TONE: Record<string, [string, string, string]> = {
  BULLISH: ["var(--mint)", "var(--mint-line)", "var(--mint-soft)"],
  BEARISH: ["var(--danger)", "var(--danger-line)", "var(--danger-soft)"],
  NEUTRAL: ["var(--ink-2)", "var(--line-2)", "transparent"],
};

export type StatusTone = "mint" | "amber" | "danger" | "indigo" | "ink";
export const STATUS_TONE: Record<StatusTone, [string, string]> = {
  mint: ["var(--mint)", "var(--mint-line)"],
  amber: ["var(--amber)", "var(--amber-line)"],
  danger: ["var(--danger)", "var(--danger-line)"],
  indigo: ["var(--indigo)", "var(--indigo-line)"],
  ink: ["var(--ink-2)", "var(--line-2)"],
};

export interface RowAction { t: string; to: string; workbench: boolean }
export interface RowStatus { label: string; tone: StatusTone; act: RowAction | null; title?: string }

export interface StatusCtx {
  now: number;
  minScore: number | null;
  heldBack: boolean;
  /** proposal results of the session cycle, by instrument (one proposal per instrument per cycle) */
  results: Map<string, { result: string | null; state: string }>;
  plansReady: boolean;
}

const approvalPath = (id: string) => `${screenById("approvals").path}/${encodeURIComponent(id)}`;
const workbench = (t: string): RowAction => ({ t, to: screenById("workbench").path, workbench: true });

/** Where a signal stands: its plan's status and the plan's latest approval (Phase 1 ends at approval). */
export function statusOf(sig: SignalRow, plan: TradePlanRow | undefined, appr: ApprovalRow | undefined, c: StatusCtx): RowStatus {
  if (!c.plansReady) return { label: "Status unavailable", tone: "ink", act: null };
  if (plan) {
    const a = appr ? shortId(appr.approval_id) : null;
    const t = shortId(plan.trade_id);
    const open = appr ? { t: "Open approval", to: approvalPath(appr.approval_id), workbench: false } : null;
    switch (plan.status) {
      case "AWAITING_APPROVAL":
        return appr?.status === "NEEDS_HUMAN_APPROVAL"
          ? { label: `In approval · ${a}`, tone: "amber", act: open, title: appr.approval_id }
          : { label: `Awaiting approval · ${t}`, tone: "amber", act: open, title: plan.trade_id };
      case "APPROVED":
        return { label: `Approved · ${a ?? t}`, tone: "mint", act: open, title: appr?.approval_id ?? plan.trade_id };
      case "NEEDS_REVISION":
        return { label: `Revision · ${a ?? t}`, tone: "amber", act: workbench("Revise in workbench"), title: appr?.approval_id ?? plan.trade_id };
      case "DRAFT":
      case "RISK_REVIEW":
        return { label: `Risk review · ${t}`, tone: "indigo", act: workbench("Open in workbench"), title: plan.trade_id };
      case "REJECTED":
        return { label: `Rejected · ${a ?? t}`, tone: "danger", act: null, title: appr?.approval_id ?? plan.trade_id };
      case "RESEARCH_ONLY":
        return { label: `Research only · ${t}`, tone: "ink", act: null, title: plan.trade_id };
      case "EXPIRED":
        return { label: `Expired · ${t}`, tone: "ink", act: null, title: plan.trade_id };
      default:
        return { label: `${humanize(plan.status)} · ${t}`, tone: "ink", act: null, title: plan.trade_id };
    }
  }
  const score = num(sig.signal_score) ?? 0;
  const expired = !!sig.expires_at && new Date(sig.expires_at).getTime() < c.now;
  switch (sig.status) {
    case "CONSUMED": {
      const r = c.results.get(sig.instrument);
      if (r?.state === "FAILED" || r?.result === "FAILED") return { label: "Proposal failed", tone: "danger", act: null };
      if (r?.result) return { label: `No plan · ${r.result}`, tone: "ink", act: null };
      return { label: "Taken · no plan", tone: "ink", act: null };
    }
    case "SUPPRESSED":
      return { label: "Suppressed", tone: "ink", act: null };
    case "EXPIRED":
      return { label: "Expired unused", tone: "ink", act: null };
    default:
      if (expired) return { label: "Expired unused", tone: "ink", act: null };
      if (c.heldBack && c.minScore != null && score >= c.minScore) return { label: "Held back · entries stopped", tone: "danger", act: null };
      return { label: "Watch only", tone: "ink", act: null };
  }
}

/** Stored signal count from the scan task's result_ref ("scan://WF-…?signals=172"). */
export function storedFromRef(ref: string | null | undefined): number | null {
  const m = typeof ref === "string" ? /[?&]signals=(\d+)/.exec(ref) : null;
  return m ? Number(m[1]) : null;
}

/** "autodesk-ait-v1/ait-rules-v1" → "autodesk-ait-v1 · ait-rules-v1". */
export const versionLabel = (v: string | null | undefined): string | null => (v ? v.split("/").join(" · ") : null);
