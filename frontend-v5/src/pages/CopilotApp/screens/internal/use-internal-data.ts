/**
 * Read-only queries for the internal (admin) screens. Each one reads an
 * endpoint that already exists in the backend but has no shared frontend hook.
 *
 *   GET /api/admin/nidp/feeds/live   feed status + rollup   (backend/routes/admin_nidp.py)
 *   GET /api/admin/stats             user / portfolio counts (backend/routes/admin.py)
 *   GET /api/compliance/audit        the caller's own trail  (backend/routes/compliance.py)
 *   GET /api/copilot/agents          routing agents          (backend/routes/copilot_agents.py)
 *
 * Responses are checked against the fields the screens read, so a changed
 * contract shows up as an error block instead of a broken page.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ApiError } from "@/services/api/errors";
import { useImpersonationStore } from "@/stores/impersonation.store";

/** Checks a response; a mismatch becomes one short line naming the fields at fault. */
function parse<T>(schema: z.ZodType<T, z.ZodTypeDef, unknown>, data: unknown, name: string): T {
  const parsed = schema.safeParse(data);
  if (parsed.success) return parsed.data;
  const fields = parsed.error.issues
    .slice(0, 3)
    .map((i) => `${i.path.join(".") || "response"} (${i.message.toLowerCase()})`)
    .join(", ");
  throw ApiError.contractDrift(`${name}: ${fields}`);
}

/**
 * A changed contract or a refusal will not improve on a second try, so those
 * fail at once and the screen shows its error state instead of a skeleton.
 * Anything transient gets the app's usual single retry.
 */
function retryTransient(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && !["network", "timeout", "server", "rate_limit", "unknown"].includes(error.kind)) return false;
  return failureCount < 1;
}

// ── GET /api/admin/nidp/feeds/live ───────────────────────────────────────

const FeedDayC = z.object({
  date: z.string(),
  /** OK | PARTIAL | FAILED | SKIPPED, or null when nothing ran that day. */
  status: z.string().nullable().optional(),
  run_count: z.number().nullable().optional(),
}).passthrough();

const LiveFeedC = z.object({
  ingester: z.string(),
  /** Reliability class of the source in the NIDP source registry (A–E, or "derived"). */
  source_class: z.string().nullable().optional(),
  expected_freq: z.string().nullable().optional(),
  schedule_cron: z.string().nullable().optional(),
  last_run_status: z.string().nullable().optional(),
  consecutive_failures: z.number().nullable().optional(),
  last_run_at: z.string().nullable().optional(),
  last_success_at: z.string().nullable().optional(),
  last_failure_at: z.string().nullable().optional(),
  last_rows_inserted: z.number().nullable().optional(),
  last_error_message: z.string().nullable().optional(),
  last_7_days: z.array(FeedDayC).nullable().optional(),
  /** running | never_run | failing | stale | healthy */
  freshness_state: z.string(),
  hours_since_success: z.number().nullable().optional(),
}).passthrough();
export type LiveFeed = z.infer<typeof LiveFeedC>;

const FeedsLiveC = z.object({
  generated_at: z.string().nullable().optional(),
  last_trading_day: z.string().nullable().optional(),
  summary: z.object({
    total: z.number(),
    healthy: z.number(),
    failing: z.number(),
    stale: z.number(),
    never_run: z.number(),
    running: z.number().optional(),
  }).passthrough(),
  feeds: z.array(LiveFeedC),
  /** Set when the NIDP Query API could not be read; `feeds` is then empty. */
  db_error: z.string().nullable().optional(),
}).passthrough();
export type FeedsLive = z.infer<typeof FeedsLiveC>;

/** Status of every NIDP ingester, worst first. Refreshes every 30 seconds. */
export function useFeedsLive() {
  return useQuery<FeedsLive>({
    queryKey: ["copilot-app", "ops", "feeds-live"],
    retry: retryTransient,
    staleTime: 15_000,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/nidp/feeds/live", timeoutMs: 30_000, signal });
      return parse(FeedsLiveC, res.data, "ops.feedsLive");
    },
  });
}

// ── GET /api/admin/stats ─────────────────────────────────────────────────

const AdminStatsC = z.object({
  whitelist: z.object({
    total: z.number(),
    active: z.number(),
    pending: z.number(),
    blocked: z.number(),
    /** Percent units: active ÷ total × 100. */
    conversion_rate: z.number(),
  }).passthrough(),
  usage: z.object({
    total_users: z.number(),
    total_portfolios: z.number(),
    total_holdings: z.number(),
  }).passthrough(),
}).passthrough();
export type AdminStats = z.infer<typeof AdminStatsC>;

/** All-time counts of users, portfolios, holdings and the invite list. */
export function useAdminStats() {
  return useQuery<AdminStats>({
    queryKey: ["copilot-app", "ops", "admin-stats"],
    retry: retryTransient,
    staleTime: 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/stats", signal });
      return parse(AdminStatsC, res.data, "ops.adminStats");
    },
  });
}

// ── GET /api/compliance/audit ────────────────────────────────────────────

const AuditRowC = z.object({
  audit_id: z.string().nullable().optional(),
  action: z.string(),
  /** Target id (holding, plan, broker …) when the action has one. */
  resource: z.string().nullable().optional(),
  /** success | denied | error */
  outcome: z.string().nullable().optional(),
  /** UTC ISO timestamp. */
  ts: z.string().nullable().optional(),
}).passthrough();
export type AuditRow = z.infer<typeof AuditRowC>;

const AuditTrailC = z.object({
  rows: z.array(AuditRowC),
  count: z.number().optional(),
}).passthrough();

/**
 * The signed-in account's own audit trail, newest first. The backend scopes
 * this to the effective user, so the cache is keyed by the client being viewed.
 */
export function useMyAuditTrail(limit = 100) {
  const activeProfileId = useImpersonationStore((s) => s.profileId);
  return useQuery<AuditRow[]>({
    queryKey: ["copilot-app", "ops", "audit", activeProfileId ?? "self", limit],
    retry: retryTransient,
    staleTime: 30_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/compliance/audit", query: { limit }, signal });
      return parse(AuditTrailC, res.data, "ops.auditTrail").rows;
    },
  });
}

// ── GET /api/copilot/agents ──────────────────────────────────────────────

const AgentC = z.object({
  id: z.string(),
  label: z.string(),
  one_liner: z.string().nullable().optional(),
  /** Regex patterns the intent router matches a question against. */
  triggers: z.array(z.string()).nullable().optional(),
  default_suggestions: z.array(z.string()).nullable().optional(),
}).passthrough();
export type CopilotAgent = z.infer<typeof AgentC>;

const AgentsC = z.object({ agents: z.array(AgentC) }).passthrough();

/** The specialist agents the Copilot's intent router picks between. */
export function useCopilotAgents() {
  return useQuery<CopilotAgent[]>({
    queryKey: ["copilot-app", "ops", "agents"],
    retry: retryTransient,
    staleTime: 5 * 60_000,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/copilot/agents", signal });
      return parse(AgentsC, res.data, "ops.agents").agents;
    },
  });
}
