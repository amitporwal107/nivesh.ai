/**
 * Read-only queries over the app's own admin and status endpoints, for the
 * four operations pages. Each endpoint exists in the backend already; none had
 * a shared frontend hook (the admin console reads some of them inline).
 *
 * Counted against the 10-a-minute admin budget (/api/admin/*):
 *   GET /api/admin/ai/circuit            insight writer on/off      (backend/routes/intelligence.py)
 *   GET /api/admin/prompts               prompt registry            (backend/routes/admin_rules.py)
 *   GET /api/admin/feature-flags         feature switches           (backend/routes/admin.py)
 *   GET /api/admin/users                 user directory             (backend/routes/admin_users.py)
 *   GET /api/admin/mf/audit-log          fund-data refresh log      (backend/routes/mf_data.py)
 *   GET /api/admin/ocr-correction/stats  statement-reading fixes    (backend/routes/admin.py)
 *
 * Not counted against it:
 *   GET /api/copilot/models/picker       answer models              (backend/routes/copilot_agents.py)
 *   GET /api/work/stats                  reported issues            (backend/routes/work.py, via workAdapter)
 *   GET /api/data-health/summary         nightly job status         (backend/routes/data_health.py)
 *   GET /api/move-odds/diagnostics       entry-setup research       (backend/routes/move_odds.py)
 *   GET /api/positional/backtest/calibration  score calibration     (backend/routes/positional.py)
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { workAdapter } from "@/services/adapters/work.adapter";
import type { WorkStats } from "@/services/contracts/work.contract";
import { ADMIN_STALE_MS, parse, retryTransient } from "./use-internal-data";

const KEY = ["copilot-app", "ops", "platform"] as const;

// ── GET /api/copilot/models/picker ───────────────────────────────────────

const AnswerModelC = z.object({
  id: z.string(),
  /** openai | anthropic | gemini */
  provider: z.string().nullable().optional(),
  label: z.string(),
  is_default: z.boolean().nullable().optional(),
  /** The model name sent to the provider. */
  underlying: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
});
export type AnswerModel = z.infer<typeof AnswerModelC>;

/** The language models the chat's model picker offers. */
export function useAnswerModels() {
  return useQuery<AnswerModel[]>({
    queryKey: [...KEY, "answer-models"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/copilot/models/picker", signal });
      return parse(z.object({ models: z.array(AnswerModelC) }), res.data, "ops.answerModels").models;
    },
  });
}

// ── GET /api/admin/ai/circuit ────────────────────────────────────────────

const AiCircuitC = z.object({
  /** True while model calls for written insights are switched off. */
  open: z.boolean(),
  seconds_remaining: z.number().nullable().optional(),
});
export type AiCircuit = z.infer<typeof AiCircuitC>;

/**
 * The switch in front of the model that writes portfolio insights
 * (backend/services/ai_insights.py). While it is open the insights come from
 * the rule-based fallback. The state is held per server process.
 */
export function useAiCircuit() {
  return useQuery<AiCircuit>({
    queryKey: [...KEY, "ai-circuit"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/ai/circuit", signal });
      return parse(AiCircuitC, res.data, "ops.aiCircuit");
    },
  });
}

// ── GET /api/admin/prompts ───────────────────────────────────────────────

// The payload also carries each prompt's full text (`default`, `current`).
// It is not read here: this page lists the prompts, the admin console edits them.
const PromptC = z.object({
  name: z.string(),
  description: z.string().nullable().optional(),
  /** The backend function or route that sends this prompt. */
  used_in: z.string().nullable().optional(),
  /** True when an admin has replaced the built-in text. */
  overridden: z.boolean().nullable().optional(),
  /** Characters in the text in use. */
  length: z.number().nullable().optional(),
});
export type PromptEntry = z.infer<typeof PromptC>;

/** The system prompts the backend sends to a model, with where each is used. */
export function usePromptRegistry() {
  return useQuery<PromptEntry[]>({
    queryKey: [...KEY, "prompts"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/prompts", signal });
      return parse(z.object({ prompts: z.array(PromptC) }), res.data, "ops.prompts").prompts;
    },
  });
}

// ── GET /api/admin/feature-flags ─────────────────────────────────────────

const FlagC = z.object({
  key: z.string(),
  display_name: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  /** off | allowlist | everyone */
  mode: z.string(),
  /** Email addresses the feature is on for when the mode is "allowlist". */
  allowlist: z.array(z.string()).nullable().optional(),
});
export type FeatureFlag = z.infer<typeof FlagC>;

const FlagsC = z.object({
  flags: z.array(FlagC),
  updated_at: z.string().nullable().optional(),
  updated_by: z.string().nullable().optional(),
});
export type FeatureFlags = z.infer<typeof FlagsC>;

/** Which gated features are on, and for whom. */
export function useFeatureFlags() {
  return useQuery<FeatureFlags>({
    queryKey: [...KEY, "feature-flags"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/feature-flags", signal });
      return parse(FlagsC, res.data, "ops.featureFlags");
    },
  });
}

// ── GET /api/admin/users ─────────────────────────────────────────────────

const AdminUserC = z.object({
  user_id: z.string(),
  email: z.string().nullable().optional(),
  name: z.string().nullable().optional(),
  is_admin: z.boolean().nullable().optional(),
  created_at: z.string().nullable().optional(),
  holdings_count: z.number().nullable().optional(),
  /** When the account's newest session was created; null if it never signed in. */
  last_login_at: z.string().nullable().optional(),
  /** True while that newest session has not expired. */
  session_active: z.boolean().nullable().optional(),
});
export type AdminUser = z.infer<typeof AdminUserC>;

const AdminUsersC = z.object({ users: z.array(AdminUserC), total: z.number().nullable().optional() });

/** The backend returns at most this many accounts, newest first. */
export const ADMIN_USERS_CAP = 500;

/**
 * Every account with its newest sign-in. One session per account — not a
 * sign-in history. Pass `enabled: false` to read only what is already cached.
 */
export function useAdminUsers(enabled = true) {
  return useQuery<AdminUser[]>({
    queryKey: [...KEY, "users"],
    enabled,
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      // The route counts holdings and plans per account, so it slows with the user base.
      const res = await http({ path: "/api/admin/users", timeoutMs: 30_000, signal });
      return parse(AdminUsersC, res.data, "ops.adminUsers").users;
    },
  });
}

// ── GET /api/admin/mf/audit-log ──────────────────────────────────────────

const FundRefreshC = z.object({
  id: z.string(),
  instrument_name: z.string().nullable().optional(),
  /** ok | partial | failed | skipped */
  status: z.string().nullable().optional(),
  holdings_count: z.number().nullable().optional(),
  validation_issues: z.string().nullable().optional(),
  /** fresh | cache | stale-cache */
  source: z.string().nullable().optional(),
  duration_ms: z.number().nullable().optional(),
  /** UTC, written without a zone suffix (Postgres `timestamp`). */
  created_at: z.string().nullable().optional(),
});
export type FundRefresh = z.infer<typeof FundRefreshC>;

/** Each time a fund's holdings were fetched from the source site, newest first. */
export function useFundRefreshLog(limit = 100) {
  return useQuery<FundRefresh[]>({
    queryKey: [...KEY, "fund-refresh-log", limit],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/mf/audit-log", query: { limit }, signal });
      return parse(z.object({ audit: z.array(FundRefreshC) }), res.data, "ops.fundRefreshLog").audit;
    },
  });
}

// ── GET /api/admin/ocr-correction/stats ──────────────────────────────────

const OcrStatsC = z.object({
  total_corrections: z.number(),
  auto_applied: z.number().nullable().optional(),
  isin_corrections: z.number().nullable().optional(),
  name_corrections: z.number().nullable().optional(),
  patterns_learned: z.number().nullable().optional(),
});
export type OcrStats = z.infer<typeof OcrStatsC>;

/** Corrections made to holdings read from uploaded statements, all time. */
export function useOcrStats() {
  return useQuery<OcrStats>({
    queryKey: [...KEY, "ocr-stats"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/ocr-correction/stats", signal });
      return parse(OcrStatsC, res.data, "ops.ocrStats");
    },
  });
}

// ── GET /api/work/stats ──────────────────────────────────────────────────

export type { WorkStats };

/**
 * Issues in the internal tracker, counted by status (open, in_progress,
 * in_review, testing_qa, resolved, wont_fix) and priority (P1–P3). Same client
 * and cache entry as the Work page.
 */
export function useWorkStats() {
  return useQuery<WorkStats>({
    queryKey: ["work-stats"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: () => workAdapter.stats(),
  });
}

// ── GET /api/data-health/summary ─────────────────────────────────────────

const DataHealthC = z.object({
  /** ok | warn | error */
  status: z.string(),
  issues: z.array(z.object({
    job: z.string().nullable().optional(),
    label: z.string().nullable().optional(),
    /** warn | error */
    severity: z.string().nullable().optional(),
    message: z.string().nullable().optional(),
  })),
  checked_at: z.string().nullable().optional(),
});
export type DataHealth = z.infer<typeof DataHealthC>;

/** Status of the app's own nightly jobs (prices, fund scores, rating cover, file scanner). */
export function useDataHealth() {
  return useQuery<DataHealth>({
    queryKey: [...KEY, "data-health"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/data-health/summary", timeoutMs: 20_000, signal });
      return parse(DataHealthC, res.data, "ops.dataHealth");
    },
  });
}

// ── GET /api/move-odds/diagnostics ───────────────────────────────────────

const SetupTradeC = z.object({
  /** Profit target of the simulated trade: "5%" or "10%". */
  trade: z.string(),
  trades: z.number(),
  /** Average result per trade after costs, as a fraction (−0.0065 = −0.65%). */
  mean_net: z.number().nullable().optional(),
  baseline_mean_net: z.number().nullable().optional(),
  /** passed | failed */
  validation: z.string().nullable().optional(),
});

const SetupC = z.object({
  id: z.string(),
  name: z.string(),
  status: z.string().nullable().optional(),
  status_label: z.string().nullable().optional(),
  trades: z.array(SetupTradeC),
});
export type EntrySetup = z.infer<typeof SetupC>;

const SetupResearchC = z.object({
  data: z.object({
    /** The day the owner took the decision the study supports. */
    decided: z.string().nullable().optional(),
    study: z.object({
      first_signal_day: z.string().nullable().optional(),
      last_signal_day: z.string().nullable().optional(),
      universe: z.string().nullable().optional(),
      /** Round-trip cost charged to each simulated trade, as a fraction. */
      cost_round_trip: z.number().nullable().optional(),
      rule: z.string().nullable().optional(),
      baseline: z.string().nullable().optional(),
      tested: z.number(),
      validated: z.number(),
    }),
    setups: z.array(SetupC),
  }),
});
export type SetupResearch = z.infer<typeof SetupResearchC>["data"];

/**
 * The entry-setup study behind the Move odds page: how many tested setups
 * beat the baseline after costs. A stored research result, not a live
 * measurement. Needs the Move odds feature (403 otherwise).
 */
export function useEntrySetupResearch() {
  return useQuery<SetupResearch>({
    queryKey: [...KEY, "entry-setup-research"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/move-odds/diagnostics", signal });
      return parse(SetupResearchC, res.data, "ops.entrySetupResearch").data;
    },
  });
}

// ── GET /api/positional/backtest/calibration ─────────────────────────────

const CalibrationBucketC = z.object({
  /** Which score the band is on. */
  metric: z.string().nullable().optional(),
  bucket_lo: z.number().nullable().optional(),
  bucket_hi: z.number().nullable().optional(),
  horizon_days: z.number().nullable().optional(),
  sample_count: z.number().nullable().optional(),
  moves_count: z.number().nullable().optional(),
  /** Share of the samples in this score band that went on to move, 0–1. */
  probability: z.number().nullable().optional(),
});
export type CalibrationBucket = z.infer<typeof CalibrationBucketC>;

const CalibrationC = z.object({
  buckets: z.array(CalibrationBucketC),
  /** Set instead of rows when the table could not be read. */
  _reason: z.string().nullable().optional(),
});
export type Calibration = z.infer<typeof CalibrationC>;

/** The positional engine's calibration table: score band → how often the move followed. */
export function usePositionalCalibration() {
  return useQuery<Calibration>({
    queryKey: [...KEY, "positional-calibration"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/positional/backtest/calibration", signal });
      return parse(CalibrationC, res.data, "ops.positionalCalibration");
    },
  });
}
