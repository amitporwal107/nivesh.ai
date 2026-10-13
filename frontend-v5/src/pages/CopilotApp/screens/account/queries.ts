/**
 * Account screens (Get started, Broker connections, Settings) — typed reads and
 * writes for backend endpoints that had no hook in this app, plus the "finish
 * onboarding" call the existing Onboarding page makes inline.
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
  brokerFetched: [ROOT, "broker-fetched"] as const,
  gmailHistory: [ROOT, "gmail-history"] as const,
  audit: [ROOT, "audit"] as const,
  dataExport: [ROOT, "data-export"] as const,
  consents: [ROOT, "consents"] as const,
  notifications: [ROOT, "notifications"] as const,
};

// ── validation ───────────────────────────────────────────────────────────

export const optStr = z.string().nullish().transform((v) => v ?? null);
export const optNum = z.number().nullish().transform((v) => v ?? null);
const optFlag = z.boolean().nullish().transform((v) => v === true);

function drift(source: string, error: z.ZodError): ApiError {
  const where = error.issues.slice(0, 3).map((i) => `${i.path.join(".") || "response"}: ${i.message}`).join("; ");
  return ApiError.contractDrift(`${source} (${where})`);
}

export function parse<S extends z.ZodTypeAny>(schema: S, value: unknown, source: string): z.infer<S> {
  const r = schema.safeParse(value);
  if (!r.success) throw drift(source, r.error);
  return r.data as z.infer<S>;
}

/** A malformed 200 will be malformed again; only other failures get one more try. */
export function retryUnlessDrift(failureCount: number, error: Error): boolean {
  return !(error instanceof ApiError && error.kind === "contract_drift") && failureCount < 1;
}

/**
 * Result of a write whose failure the screen reports itself.
 *
 * The app shows a toast for every REJECTED mutation, quoting the server's own
 * wording to whoever is signed in (App.tsx → toastFromError). The writes on
 * these screens resolve with an Outcome instead, so a failure is said once, in
 * plain words, where the action was taken.
 */
export type Outcome<T, E = unknown> = { ok: true; value: T } | { ok: false; error: E };

export async function settle<T>(run: () => Promise<T>): Promise<Outcome<T>> {
  try {
    return { ok: true, value: await run() };
  } catch (error) {
    return { ok: false, error };
  }
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
  /** Stored holdings from any source: a broker account, a broker file, a statement. */
  holdings_count: z.number(),
  /** Connected broker accounts, in any state. */
  broker_accounts: z.number(),
  /** Of those, the ones whose status is "active". */
  broker_accounts_live: z.number(),
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

// ── POST /api/portfolio/upload (.xlsx / .xls / .csv) ─────────────────────
// backend/routes/upload.py :: upload_portfolio →
//   { message, count, holdings, broker, broker_name, format }
// backend/helpers/statement_exports.py reads the file; helpers/parsing.py ::
// save_holdings and helpers/holdings_reconcile.py store it:
//   - a broker's own holdings export is recognised by its columns. Its rows
//     REPLACE the rows of that broker's earlier export, and a holding already
//     read from a connected account at the same broker is left out;
//   - any other sheet with a name and a quantity column ("generic"), or a
//     table whose broker cannot be named ("unidentified"), is ADDED to what is
//     on file with no broker on its rows.
// Rows are saved in the same call: there is no preview. A file with no
// holdings table is a 400 whose message names the columns looked for.
//
// Posted here and not through casUploadService.uploadFile, which keeps only
// message, count and holdings. One request per press: apiFetch does not
// re-send (the shared http() client would, after a 5xx, and the rows would be
// saved twice), and the mutation resolves with an Outcome so the form words
// the failure itself.

/**
 * Brokers whose own holdings export the server recognises, by slug
 * (statement_exports.py :: _BROKERS — keep in step with it).
 */
export const EXPORT_BROKERS: Record<string, string> = {
  zerodha: "Zerodha",
  groww: "Groww",
  upstox: "Upstox",
  angel: "Angel One",
  icicidirect: "ICICI Direct",
  hdfcsec: "HDFC Securities",
  kotak: "Kotak Securities",
  dhan: "Dhan",
  fivepaisa: "5paisa",
  mfcentral: "MF Central",
};

const HoldingsUploadRes = z.object({
  /** Holdings saved from the file. */
  count: z.number(),
  /** Slug of the broker whose export this is; null for a generic or unidentified file. */
  broker: optStr,
  broker_name: optStr,
  /** A broker slug, "generic" or "unidentified"; null when the file was empty. */
  format: optStr,
});
export type HoldingsUpload = z.infer<typeof HoldingsUploadRes>;

export function useHoldingsFileUpload() {
  return useMutation<Outcome<HoldingsUpload>, never, File>({
    mutationFn: (file) => settle(async () => {
      const form = new FormData();
      form.append("file", file);
      let res: Response;
      try {
        res = await apiFetch("/api/portfolio/upload", { method: "POST", body: form });
      } catch (cause) {
        throw ApiError.network(cause);
      }
      const body: unknown = await res.json().catch(() => undefined);
      if (!res.ok) throw ApiError.fromResponse(res, body);
      return parse(HoldingsUploadRes, body, "portfolio.upload");
    }),
  });
}

// ── GET /api/compliance/consents ─────────────────────────────────────────
// backend/routes/compliance.py :: list_consents — the consent purposes and the
// latest recorded choice for each (services/consents.py).

const ConsentC = z.object({
  purpose: z.string().min(1),
  title: z.string().min(1),
  required: z.boolean(),
  /** "granted" | "withdrawn" | "pending" (no choice recorded) */
  status: z.string(),
  granted_at: optStr,
  withdrawn_at: optStr,
});
export type Consent = z.infer<typeof ConsentC>;

const ConsentsRes = z.object({ consents: z.array(ConsentC) });

export function useConsents() {
  return useQuery<Consent[]>({
    queryKey: accountKeys.consents,
    staleTime: 5 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/compliance/consents", signal });
      return parse(ConsentsRes, res.data, "compliance.consents").consents;
    },
  });
}

// ── GET / PATCH /api/user/preferences ────────────────────────────────────
// backend/routes/user.py :: get_user_preferences / update_user_preferences →
// { notifications: { push, email } }. The two flags are stored on the profile;
// no sender in the backend reads them yet.

const NotificationPrefsRes = z.object({
  notifications: z.object({ push: z.boolean(), email: z.boolean() }),
});
export type NotificationPrefs = z.infer<typeof NotificationPrefsRes>["notifications"];

export function useNotificationPrefs() {
  return useQuery<NotificationPrefs>({
    queryKey: accountKeys.notifications,
    staleTime: 5 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/user/preferences", signal });
      return parse(NotificationPrefsRes, res.data, "user.preferences").notifications;
    },
  });
}

export function useSaveNotificationPrefs() {
  const qc = useQueryClient();
  return useMutation<Outcome<NotificationPrefs>, never, Partial<NotificationPrefs>>({
    mutationFn: (change) => settle(async () => {
      const res = await http({ method: "PATCH", path: "/api/user/preferences", body: { notifications: change }, noRetry: true });
      return parse(NotificationPrefsRes, res.data, "user.preferences").notifications;
    }),
    onSuccess: (saved) => { if (saved.ok) qc.setQueryData(accountKeys.notifications, saved.value); },
  });
}

// ── GET /api/goals/snapshot ──────────────────────────────────────────────
// backend/routes/goals.py :: get_snapshot → { snapshot: {…} | null }
//
// Read here and not through useGoalsSnapshot: that hook parses the wrapper as
// if it were the snapshot, so its age / income / expenses are always undefined.
// The key sits under the shared ["goals", "snapshot"] prefix, so
// useSnapshotUpsert (which invalidates that prefix) refreshes this read.
//
// PUT replaces the whole row and resets any field left out to its default, so
// a save must send every field back: `snapshotBody` merges an edit into what
// the server last returned.

const SnapshotC = z.object({
  age: optNum,
  dependents: optNum,
  monthly_income_rs: optNum,
  monthly_expenses_rs: optNum,
  marital_status: optStr,
  income_growth_pct: optNum,
  inflation_pct: optNum,
  current_corpus_rs: optNum,
  total_liabilities_rs: optNum,
  risk_profile: optStr,
  behavior_score: optNum,
  updated_at: optStr,
});
export type FinancialSnapshot = z.infer<typeof SnapshotC>;

const SnapshotRes = z.object({ snapshot: SnapshotC.nullable() });

/** `null` = the server holds no snapshot for this user. */
export function useFinancialSnapshot() {
  return useQuery<FinancialSnapshot | null>({
    queryKey: ["goals", "snapshot", ROOT],
    staleTime: 5 * 60_000,
    retry: retryUnlessDrift,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/goals/snapshot", signal });
      return parse(SnapshotRes, res.data, "goals.snapshot").snapshot;
    },
  });
}

export interface SnapshotEdit {
  age: number | null;
  dependents: number;
  monthly_income_rs: number | null;
  monthly_expenses_rs: number | null;
}

/**
 * Body of PUT /api/goals/snapshot (backend/routes/goals.py :: FinancialSnapshot).
 * A type alias, not an interface: the shared upsert hook takes an object with an
 * index signature, which an interface is not assignable to.
 */
export type SnapshotBody = {
  age?: number;
  dependents: number;
  monthly_income_rs?: number;
  monthly_expenses_rs?: number;
  marital_status?: string;
  income_growth_pct?: number;
  inflation_pct?: number;
  current_corpus_rs?: number;
  total_liabilities_rs?: number;
  risk_profile?: string;
  behavior_score?: number;
};

/**
 * The full body for a save: the edit over everything already stored. A field
 * that is left out takes the server's default, which is what "not given" means.
 */
export function snapshotBody(current: FinancialSnapshot | null, edit: SnapshotEdit): SnapshotBody {
  const given = <T,>(v: T | null | undefined): T | undefined => v ?? undefined;
  return {
    dependents: edit.dependents,
    age: given(edit.age),
    monthly_income_rs: given(edit.monthly_income_rs),
    monthly_expenses_rs: given(edit.monthly_expenses_rs),
    marital_status: given(current?.marital_status),
    income_growth_pct: given(current?.income_growth_pct),
    inflation_pct: given(current?.inflation_pct),
    current_corpus_rs: given(current?.current_corpus_rs),
    total_liabilities_rs: given(current?.total_liabilities_rs),
    risk_profile: given(current?.risk_profile),
    behavior_score: given(current?.behavior_score),
  };
}

// ── DELETE /api/chat/clear ───────────────────────────────────────────────
// backend/routes/chat.py :: clear_chat — with no session id, deletes every
// conversation and message of the signed-in user.

export function useClearConversations() {
  const qc = useQueryClient();
  return useMutation<Outcome<void>, never, void>({
    mutationFn: () => settle(async () => {
      await http({ method: "DELETE", path: "/api/chat/clear", noRetry: true });
    }),
    onSuccess: (done) => { if (done.ok) void qc.invalidateQueries({ queryKey: ["chat"] }); },
  });
}

/** Refresh everything a newly imported statement changes. */
export function useAfterImport() {
  const qc = useQueryClient();
  return useCallback(() => {
    const keys: ReadonlyArray<readonly string[]> = [
      accountKeys.onboardingState,
      accountKeys.gmailHistory,
      accountKeys.brokerFetched,
      ["gmail", "status"],
      ["onboarding", "state"],
      ["portfolio"],
      ["plans"],
    ];
    for (const queryKey of keys) void qc.invalidateQueries({ queryKey });
  }, [qc]);
}
