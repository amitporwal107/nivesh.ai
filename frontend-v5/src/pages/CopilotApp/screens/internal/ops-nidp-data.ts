/**
 * Read-only queries over the data platform's admin endpoints — the same ones
 * the NIDP console's tabs read (src/components/nidp/*), which keep their
 * queries inside each panel and so have no hook to share.
 *
 *   GET /api/admin/nidp/jobs/{ingester}/runs   run history of one feed     (backend/routes/admin_nidp.py)
 *   GET /api/admin/nidp/catalog                tables, row counts, validation runs
 *   GET /api/admin/nidp/quality/consistency    cross-source checks and their findings
 *   GET /api/admin/nidp/quality/summary        quality scores and the publish gate
 *   GET /api/admin/nidp/pipeline/stages        filings → search pipeline   (backend/routes/admin_nidp_pipeline.py)
 *
 * All of these count against the 10-a-minute admin budget, so each is read
 * once and kept for five minutes; none is polled.
 */
import { useQuery } from "@tanstack/react-query";
import { z } from "zod";
import { http } from "@/services/api/http";
import { ADMIN_STALE_MS, parse, retryTransient } from "./use-internal-data";

const KEY = ["copilot-app", "ops", "nidp"] as const;

// ── GET /api/admin/nidp/jobs/{ingester}/runs ─────────────────────────────

const FeedRunC = z.object({
  run_id: z.string().nullable().optional(),
  /** The market day the run loaded data for. */
  target_date: z.string().nullable().optional(),
  /** OK | PARTIAL | FAILED | RUNNING | SKIPPED */
  status: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  duration_ms: z.number().nullable().optional(),
  rows_fetched: z.number().nullable().optional(),
  rows_inserted: z.number().nullable().optional(),
  rows_skipped: z.number().nullable().optional(),
  error_class: z.string().nullable().optional(),
  error_message: z.string().nullable().optional(),
});
export type FeedRun = z.infer<typeof FeedRunC>;

const FeedRunsC = z.object({
  ingester: z.string().nullable().optional(),
  runs: z.array(FeedRunC),
  /** Set when the NIDP query service could not be read; `runs` is then empty. */
  error: z.string().nullable().optional(),
});
export type FeedRuns = z.infer<typeof FeedRunsC>;

/** The last runs of one feed, newest first. Read only while its row is open. */
export function useFeedRuns(ingester: string | null, limit = 10) {
  return useQuery<FeedRuns>({
    queryKey: [...KEY, "runs", ingester, limit],
    enabled: !!ingester,
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: `/api/admin/nidp/jobs/${encodeURIComponent(ingester ?? "")}/runs`, query: { limit }, timeoutMs: 30_000, signal });
      return parse(FeedRunsC, res.data, "ops.feedRuns");
    },
  });
}

// ── GET /api/admin/nidp/catalog ──────────────────────────────────────────

const CatalogTableC = z.object({
  table: z.string(),
  domain: z.string().nullable().optional(),
  /** Column the date range is measured on; null for tables without one. */
  date_col: z.string().nullable().optional(),
  rows: z.number().nullable().optional(),
  first_at: z.string().nullable().optional(),
  last_at: z.string().nullable().optional(),
  description: z.object({
    source: z.string().nullable().optional(),
    stores: z.string().nullable().optional(),
    use: z.string().nullable().optional(),
  }).nullable().optional(),
  /** Set when this table could not be counted. */
  error: z.string().nullable().optional(),
});
export type CatalogTable = z.infer<typeof CatalogTableC>;

const CatalogDomainC = z.object({
  domain: z.string(),
  tables: z.number().nullable().optional(),
  rows: z.number().nullable().optional(),
  earliest: z.string().nullable().optional(),
  latest: z.string().nullable().optional(),
});
export type CatalogDomain = z.infer<typeof CatalogDomainC>;

const ValidationRunC = z.object({
  ingester: z.string(),
  target_date: z.string().nullable().optional(),
  /** PASSED | PARTIAL | FAILED */
  status: z.string().nullable().optional(),
  rules_run: z.number().nullable().optional(),
  rules_failed: z.number().nullable().optional(),
  findings_count: z.number().nullable().optional(),
  started_at: z.string().nullable().optional(),
});
export type ValidationRun = z.infer<typeof ValidationRunC>;

// `feeds` is in the payload too; the screens read feed status from
// /feeds/live, so it is left out here.
const CatalogC = z.object({
  as_of: z.string().nullable().optional(),
  totals: z.object({ tables: z.number().nullable().optional(), feeds: z.number().nullable().optional() }).nullable().optional(),
  by_domain: z.array(CatalogDomainC),
  tables: z.array(CatalogTableC),
  /** The 50 most recent validation runs across all feeds, newest first. */
  validation: z.array(ValidationRunC),
});
export type NidpCatalog = z.infer<typeof CatalogC>;

/** Warehouse tables with row counts and date coverage, plus recent validation runs. */
export function useNidpCatalog(enabled = true) {
  return useQuery<NidpCatalog>({
    queryKey: [...KEY, "catalog"],
    enabled,
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      // Counts every table, so it is slow on a cold start — same allowance as the console.
      const res = await http({ path: "/api/admin/nidp/catalog", timeoutMs: 60_000, signal });
      return parse(CatalogC, res.data, "ops.catalog");
    },
  });
}

// ── GET /api/admin/nidp/quality/consistency ──────────────────────────────

const ConsistencyRunC = z.object({
  target_date: z.string().nullable().optional(),
  /** equity | mf */
  domain: z.string(),
  /** PASSED | PARTIAL | FAILED */
  status: z.string().nullable().optional(),
  rules_run: z.number().nullable().optional(),
  rules_failed: z.number().nullable().optional(),
  findings_count: z.number().nullable().optional(),
  /** True when a finding is severe enough to stop publishing. */
  has_block: z.boolean().nullable().optional(),
  started_at: z.string().nullable().optional(),
});
export type ConsistencyRun = z.infer<typeof ConsistencyRunC>;

const FindingC = z.object({
  target_date: z.string().nullable().optional(),
  domain: z.string().nullable().optional(),
  dimension: z.string().nullable().optional(),
  rule_name: z.string(),
  /** WARN | ERROR | BLOCK */
  severity: z.string().nullable().optional(),
  failure_class: z.string().nullable().optional(),
  /** "symbol" for a listed stock, "scheme"/"isin" for a fund, … */
  entity_type: z.string().nullable().optional(),
  entity_id: z.string().nullable().optional(),
  field_name: z.string().nullable().optional(),
  source_a: z.string().nullable().optional(),
  value_a: z.string().nullable().optional(),
  source_b: z.string().nullable().optional(),
  value_b: z.string().nullable().optional(),
  deviation_pct: z.number().nullable().optional(),
  message: z.string().nullable().optional(),
  detected_at: z.string().nullable().optional(),
});
export type Finding = z.infer<typeof FindingC>;

const ConsistencyC = z.object({
  runs: z.array(ConsistencyRunC),
  findings: z.array(FindingC),
  /** Per-part read errors from the NIDP query service; null when the part was read. */
  errors: z.object({ runs: z.string().nullable().optional(), findings: z.string().nullable().optional() }).nullable().optional(),
});
export type Consistency = z.infer<typeof ConsistencyC>;

/** Cross-source consistency runs (up to 30) and their findings (up to 200), newest first. */
export function useConsistency(enabled = true) {
  return useQuery<Consistency>({
    queryKey: [...KEY, "consistency"],
    enabled,
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/nidp/quality/consistency", timeoutMs: 20_000, signal });
      return parse(ConsistencyC, res.data, "ops.consistency");
    },
  });
}

// ── GET /api/admin/nidp/quality/summary ──────────────────────────────────

const QualityScoreC = z.object({
  target_date: z.string(),
  domain: z.string(),
  /** All scores are 0–100. */
  overall_score: z.number().nullable().optional(),
  accuracy: z.number().nullable().optional(),
  consistency: z.number().nullable().optional(),
  completeness: z.number().nullable().optional(),
  freshness: z.number().nullable().optional(),
  auditability: z.number().nullable().optional(),
  confidence: z.number().nullable().optional(),
  /** GOLD | SILVER | REVIEW | … */
  certification: z.string().nullable().optional(),
  /** AUTO_PUBLISH | REVIEW | REJECT */
  publish_decision: z.string().nullable().optional(),
  computed_at: z.string().nullable().optional(),
});
export type QualityScore = z.infer<typeof QualityScoreC>;

const QualitySummaryC = z.object({
  /** Up to 90 scored days per domain, newest first. */
  quality: z.array(QualityScoreC),
  /** Days held for a person to review and not yet resolved. */
  exceptions: z.array(z.object({
    target_date: z.string().nullable().optional(),
    domain: z.string().nullable().optional(),
    reason: z.string().nullable().optional(),
  })).nullable().optional(),
  errors: z.object({ quality: z.string().nullable().optional(), exceptions: z.string().nullable().optional() }).nullable().optional(),
});
export type QualitySummary = z.infer<typeof QualitySummaryC>;

/** Data-quality scores per domain and day, with the publish decision. */
export function useQualitySummary() {
  return useQuery<QualitySummary>({
    queryKey: [...KEY, "quality-summary"],
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/nidp/quality/summary", timeoutMs: 20_000, signal });
      return parse(QualitySummaryC, res.data, "ops.qualitySummary");
    },
  });
}

// ── GET /api/admin/nidp/pipeline/stages ──────────────────────────────────

const StageC = z.object({
  id: z.string(),
  label: z.string(),
  order: z.number().nullable().optional(),
  table: z.string().nullable().optional(),
  total: z.number().nullable().optional(),
  done: z.number().nullable().optional(),
  pending: z.number().nullable().optional(),
  problem: z.number().nullable().optional(),
  latest_at: z.string().nullable().optional(),
  age_hours: z.number().nullable().optional(),
  trading_days_behind: z.number().nullable().optional(),
  /** stale | never | lagging | backlog | healthy */
  state: z.string(),
  note: z.string().nullable().optional(),
});
export type PipelineStage = z.infer<typeof StageC>;

const StagesC = z.object({
  generated_at: z.string().nullable().optional(),
  stages: z.array(StageC),
  summary: z.object({
    total: z.number(),
    healthy: z.number(),
    backlog: z.number().optional(),
    lagging: z.number().optional(),
    stale: z.number().optional(),
    never: z.number().optional(),
  }),
  /** Set when the NIDP query service could not be read; `stages` is then empty. */
  db_error: z.string().nullable().optional(),
});
export type PipelineStages = z.infer<typeof StagesC>;

/** The six stages that turn exchange filings into searchable text, in pipeline order. */
export function usePipelineStages(enabled = true) {
  return useQuery<PipelineStages>({
    queryKey: [...KEY, "pipeline-stages"],
    enabled,
    retry: retryTransient,
    staleTime: ADMIN_STALE_MS,
    queryFn: async ({ signal }) => {
      const res = await http({ path: "/api/admin/nidp/pipeline/stages", timeoutMs: 30_000, signal });
      return parse(StagesC, res.data, "ops.pipelineStages");
    },
  });
}
