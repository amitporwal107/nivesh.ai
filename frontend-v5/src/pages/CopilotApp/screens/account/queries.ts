/**
 * Account screens (Get started, Broker connections, Settings) — typed reads for
 * backend endpoints that had no hook in this app, plus the "finish onboarding"
 * call the existing Onboarding page makes inline.
 *
 * Every response is checked with zod before a screen sees it. A body that does
 * not have the documented shape (for example `{}`) fails the query, so the
 * screen shows an error with a retry instead of reading missing fields or
 * presenting "nothing there" as a fact. Each schema mirrors the backend
 * handler named above it; fields the screens do not read are left out.
 */
import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { z } from "zod";
import { useGmailStatus } from "@/hooks/use-gmail";
import { http } from "@/services/api/http";
import { apiFetch } from "@/services/api/authed-fetch";
import { ApiError } from "@/services/api/errors";
import type { User } from "@/types/user";

const ROOT = "copilot-account";

export const accountKeys = {
  onboardingState: [ROOT, "onboarding-state"] as const,
  brokerAccounts: [ROOT, "broker-accounts"] as const,
  brokerAdapters: [ROOT, "broker-adapters"] as const,
  gmailHistory: [ROOT, "gmail-history"] as const,
  audit: [ROOT, "audit"] as const,
  dataExport: [ROOT, "data-export"] as const,
};

// ── validation ───────────────────────────────────────────────────────────

const optStr = z.string().nullish().transform((v) => v ?? null);
const optNum = z.number().nullish().transform((v) => v ?? null);
const optFlag = z.boolean().nullish().transform((v) => v === true);

function drift(source: string, error: z.ZodError): ApiError {
  const where = error.issues.slice(0, 3).map((i) => `${i.path.join(".") || "response"}: ${i.message}`).join("; ");
  return ApiError.contractDrift(`${source} (${where})`);
}

function parse<S extends z.ZodTypeAny>(schema: S, value: unknown, source: string): z.infer<S> {
  const r = schema.safeParse(value);
  if (!r.success) throw drift(source, r.error);
  return r.data as z.infer<S>;
}

/** A malformed 200 will be malformed again; only other failures get one more try. */
function retryUnlessDrift(failureCount: number, error: Error): boolean {
  return !(error instanceof ApiError && error.kind === "contract_drift") && failureCount < 1;
}

/** What a screen renders from: still loading, failed (with a retry), or data that passed validation. */
export type Read<T> =
  | { state: "loading" }
  | { state: "error"; error: unknown; retry: () => void }
  | { state: "ready"; data: T };

export function toRead<T>(q: UseQueryResult<T>): Read<T> {
  if (q.isPending) return { state: "loading" };
  if (q.isError) return { state: "error", error: q.error, retry: () => { void q.refetch(); } };
  return { state: "ready", data: q.data };
}

// ── GET /api/onboarding/state ────────────────────────────────────────────
// backend/routes/onboarding_gmail.py :: onboarding_state

const OnboardingStateC = z.object({
  /** A PAN (the usual CAS password) is saved on the profile. */
  pan_on_file: z.boolean(),
  /** e.g. "Mar/2025"; null until a statement has been imported. */
  cas_statement_period: optStr,
  /** Rupees. */
  cas_portfolio_value_rs: optNum,
  /** As printed on the statement, e.g. "31-Mar-2025". */
  cas_statement_date: optStr,
});
export type OnboardingState = z.infer<typeof OnboardingStateC>;

/** True once any statement has been imported (period, date or value is set). */
export function hasStatement(s: OnboardingState): boolean {
  return !!(s.cas_statement_period || s.cas_statement_date || s.cas_portfolio_value_rs != null);
}

export function useOnboardingState() {
  return useQuery<OnboardingState>({
    queryKey: accountKeys.onboardingState,
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/onboarding/state", signal });
      return parse(OnboardingStateC, res.data, "onboarding.state");
    },
  });
}

// ── GET /api/broker/accounts ─────────────────────────────────────────────
// backend/routes/broker_connect.py :: list_accounts / _public_account

const BrokerAccountC = z.object({
  account_id: z.string(),
  broker: optStr,
  broker_display: optStr,
  label: optStr,
  /** "active" | "pending" | "error" */
  status: optStr,
  last_sync_at: optStr,
  last_sync_count: optNum,
  last_error: optStr,
  created_at: optStr,
});
export type BrokerAccount = z.infer<typeof BrokerAccountC>;

const BrokerAccountsRes = z.object({ accounts: z.array(BrokerAccountC) });

export function useBrokerAccounts() {
  return useQuery<BrokerAccount[]>({
    queryKey: accountKeys.brokerAccounts,
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/broker/accounts", signal });
      return parse(BrokerAccountsRes, res.data, "broker.accounts").accounts;
    },
  });
}

// ── GET /api/broker/native/supported ─────────────────────────────────────
// backend/routes/broker_native.py :: list_supported
// backend/services/brokers/registry.py :: list_supported

const BrokerAdapterC = z.object({
  slug: z.string(),
  name: z.string(),
  /** false = a placeholder on the server that raises on every call. */
  implemented: z.boolean(),
});
export type BrokerAdapter = z.infer<typeof BrokerAdapterC>;

const BrokerAdaptersRes = z.object({ brokers: z.array(BrokerAdapterC) });

export function useBrokerAdapters() {
  return useQuery<BrokerAdapter[]>({
    queryKey: accountKeys.brokerAdapters,
    staleTime: 10 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/broker/native/supported", signal });
      return parse(BrokerAdaptersRes, res.data, "broker.native.supported").brokers;
    },
  });
}

// ── GET /api/gmail/history ───────────────────────────────────────────────
// backend/routes/gmail.py :: gmail_import_history (rows of db.gmail_imports)

const GmailImportC = z.object({
  message_id: optStr,
  filename: optStr,
  /** Holdings imported from this file. */
  count: optNum,
  status: optStr,
  /** "onboarding_gmail" (started by the user) | "gmail_auto" (scheduled). */
  source: optStr,
  imported_at: optStr,
});
export type GmailImport = z.infer<typeof GmailImportC>;

const GmailHistoryRes = z.object({ imports: z.array(GmailImportC) });

export function useGmailImportHistory() {
  return useQuery<GmailImport[]>({
    queryKey: accountKeys.gmailHistory,
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/gmail/history", signal });
      return parse(GmailHistoryRes, res.data, "gmail.history").imports;
    },
  });
}

// ── GET /api/compliance/audit ────────────────────────────────────────────
// backend/routes/compliance.py :: my_audit_trail (rows of services/audit.py).
// Rows also carry ip / ua; the screens do not read them.

const AuditRowC = z.object({
  audit_id: z.string(),
  /** e.g. "broker_connect" | "broker_sync" | "broker_disconnect" | "login" … */
  action: z.string(),
  /** "success" | "denied" | "error" */
  outcome: z.string(),
  details: z.record(z.unknown()).nullish().transform((v) => v ?? null),
  ts: z.string(),
});
export type AuditRow = z.infer<typeof AuditRowC>;

const AuditRes = z.object({ rows: z.array(AuditRowC) });

export function useAuditTrail(limit = 100) {
  return useQuery<AuditRow[]>({
    queryKey: [...accountKeys.audit, limit],
    staleTime: 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/compliance/audit", query: { limit }, signal });
      return parse(AuditRes, res.data, "compliance.audit").rows;
    },
  });
}

// ── GET /api/compliance/export ───────────────────────────────────────────
// backend/routes/compliance.py :: data_export — the signed-in user's own data
// ({ user, holdings, action_plans, consents }). Fetched only when asked for
// (`refetch()`), and not kept in the cache afterwards.

const DataExportC = z.object({
  holdings: z.array(z.unknown()),
  action_plans: z.array(z.unknown()),
  consents: z.array(z.unknown()),
}).passthrough();
export type DataExport = z.infer<typeof DataExportC>;

export function useDataExport() {
  return useQuery<DataExport>({
    queryKey: accountKeys.dataExport,
    enabled: false,
    retry: false,
    gcTime: 0,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/compliance/export", noRetry: true, signal });
      return parse(DataExportC, res.data, "compliance.export");
    },
  });
}

// ── GET /api/gmail/status (existing hook: useGmailStatus) ────────────────
// backend/routes/gmail.py :: gmail_status. The shared hook returns the body
// as-is, so it is validated here before a screen reads it.

const GmailSourceC = z.object({
  connected: z.boolean(),
  connected_at: optStr,
  /** Scheduled import is switched on. */
  auto_import_enabled: optFlag,
  /** A PAN is saved with the Gmail token, so scheduled import can open the PDFs. */
  auto_import_ready: optFlag,
  last_auto_import_at: optStr,
  last_import: z.object({ filename: optStr, imported_at: optStr, count: optNum }).nullish().transform((v) => v ?? null),
});
export type GmailSourceStatus = z.infer<typeof GmailSourceC>;

export function useGmailSourceStatus(): Read<GmailSourceStatus> {
  const q = useGmailStatus();
  const retry = () => { void q.refetch(); };
  if (q.isPending) return { state: "loading" };
  if (q.isError) return { state: "error", error: q.error, retry };
  const r = GmailSourceC.safeParse(q.data);
  return r.success ? { state: "ready", data: r.data } : { state: "error", error: drift("gmail.status", r.error), retry };
}

// ── GET /api/user/risk-profile ───────────────────────────────────────────
// backend/routes/user.py :: get_risk_profile → { risk_profile: {…} | null }
//
// Read here and not through useRiskProfile (hooks/use-risk-profile): that hook
// answers `null` for a failed request as well, which a screen would then show
// as "no risk profile yet". The key sits under the shared
// ["user", "risk-profile"] prefix, so saving a profile (useSaveRiskProfile
// invalidates that prefix) refreshes this read too.
//
// Two backend flows write the profile, with different fields:
//   questionnaire (routes/user.py)            category "Moderate", score where
//                                             HIGHER = MORE CONSERVATIVE,
//                                             completed_at, answers {id: value}
//   chat (services/risk_profile_chat.py)      category "moderate", score where
//                                             HIGHER = MORE AGGRESSIVE,
//                                             computed_at, answers [records]
// Only the category and the date mean the same thing in both, so those are
// what the screens show.

const RiskProfileC = z.object({
  category: z.string().min(1),
  score: z.number().nullish(),
  completed_at: z.string().nullish(),
  computed_at: z.string().nullish(),
  answers: z.unknown(),
});

const RiskProfileRes = z.object({ risk_profile: RiskProfileC.nullable() });

const AnswerMapC = z.record(z.string());

export interface RiskProfileView {
  /** As stored: "Moderate", "moderate", "Moderately Aggressive" … */
  category: string;
  /** When it was assessed, if the profile says. */
  assessedAt: string | null;
  /** Questionnaire answers by question id; null when the profile has none in that form. */
  answers: Record<string, string> | null;
  /** Not shown (its direction depends on which flow wrote it); kept so the questionnaire can reopen pre-filled. */
  score: number | null;
}

/** `null` = the server says there is no risk profile. */
export function useRiskProfileRead() {
  return useQuery<RiskProfileView | null>({
    queryKey: ["user", "risk-profile", ROOT],
    staleTime: 10 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/user/risk-profile", signal });
      const p = parse(RiskProfileRes, res.data, "user.risk-profile").risk_profile;
      if (!p) return null;
      const answers = AnswerMapC.safeParse(p.answers);
      return {
        category: p.category,
        assessedAt: p.completed_at ?? p.computed_at ?? null,
        answers: answers.success ? answers.data : null,
        score: p.score ?? null,
      };
    },
  });
}

// ── POST /api/user/complete-onboarding ───────────────────────────────────
// backend/routes/user.py :: complete_onboarding → { status, onboarding_completed }

/**
 * Records that onboarding is finished, the way pages/Onboarding does: POST
 * /api/user/complete-onboarding, then set the cached `me` flag so the shell's
 * onboarding gate lets the user through at once.
 *
 * Resolves to whether the server recorded it. It never rejects and gives up
 * after a few seconds, so a failed or stalled request cannot hold anyone on
 * the onboarding screen. `me` is re-read from the server only when the write
 * succeeded: after a failed write the server would answer "not completed" and
 * send the user straight back.
 */
const COMPLETE_TIMEOUT_MS = 8_000;

export function useCompleteOnboarding() {
  const qc = useQueryClient();
  return useMutation<boolean, never, void>({
    mutationFn: async () => {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), COMPLETE_TIMEOUT_MS);
      const recorded = await apiFetch("/api/user/complete-onboarding", { method: "POST", signal: ctrl.signal })
        .then((r) => r.ok, () => false)
        .finally(() => clearTimeout(timer));
      qc.setQueryData<User>(["auth", "me"], (old) => (old ? { ...old, onboardingCompleted: true } : old));
      if (recorded) void qc.invalidateQueries({ queryKey: ["auth", "me"] });
      return recorded;
    },
  });
}

/** Refresh everything a newly imported statement changes. */
export function useAfterImport() {
  const qc = useQueryClient();
  return useCallback(() => {
    const keys: ReadonlyArray<readonly string[]> = [
      accountKeys.onboardingState,
      accountKeys.gmailHistory,
      ["gmail", "status"],
      ["onboarding", "state"],
      ["portfolio"],
      ["plans"],
    ];
    for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
  }, [qc]);
}
