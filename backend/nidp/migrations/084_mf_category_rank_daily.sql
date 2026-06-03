-- 084_mf_category_rank_daily.sql
--
-- New persistence table for the corrected MF category ranking engine.
--
-- Replaces the structurally incorrect composite_rank column in
-- analytics.fund_category_rank (which averaged per-metric PERCENT_RANK values,
-- discarding magnitude).  The new engine: normalises each metric to a
-- percentile within the category, computes a weighted composite with
-- re-normalised denominator for missing data, then ranks the composite once.
--
-- Correctness rules implemented (per docs/prd/MF_COMPOSITE_SCORING.prd):
--   - Never average per-metric ranks  (§7.1 — root cause of the defect)
--   - Invert lower-is-better metrics  (§7.2)
--   - Dedupe Direct-Growth canonical  (§7.3)
--   - Re-normalise denominator for null metrics, never zero-fill (§7.4)
--   - Normalise within the correct peer set, point-in-time  (§7.5)
--   - Flag tiny categories N < 8 as low_confidence  (§7.6)
--
-- Key design choices:
--   - metric_contributions is JSONB so the metric set is configurable without
--     schema changes (each entry: {value, pct, weight, contribution}).
--   - Upsert on (scheme_code, rank_date) — safe to re-run.
--   - analytics.fund_category_rank is NOT altered; its composite_rank column
--     is deprecated (do not read) but kept to avoid breaking existing jobs.
--
-- Idempotent.  Safe to re-run.

SET search_path TO nidp, public;


CREATE TABLE IF NOT EXISTS nidp.mf_category_rank_daily (
    scheme_code             TEXT        NOT NULL,
    rank_date               DATE        NOT NULL,

    sebi_category           TEXT        NOT NULL,
    -- Full AMFI/SEBI category string from mf_scheme_master.scheme_category
    -- (e.g. "Equity Scheme - Large Cap Fund").  Peer-set key.

    composite               NUMERIC(6,2),
    -- Weighted normalised composite score 0–100.
    -- NULL when status = insufficient_history | insufficient_coverage.

    category_rank           INTEGER,
    -- Competition rank within sebi_category; 1 = best performer.
    -- NULL when status ∈ {insufficient_history, insufficient_coverage}.
    -- Assigned for status = ranked | low_confidence.

    category_pct            NUMERIC(6,2),
    -- (N − category_rank) / (N − 1) × 100; best fund = 100.
    -- NULL when not rankable.

    category_size           INTEGER     NOT NULL DEFAULT 0,
    -- Count of rankable funds in the peer set for this rank_date.
    -- Excludes insufficient_history and insufficient_coverage funds.

    metric_contributions    JSONB       NOT NULL DEFAULT '{}',
    -- Per-metric audit trail:
    --   {metric_name: {value, pct, weight, contribution}}
    -- Satisfies auditability requirement: weighted sum == composite ±0.01.

    status                  TEXT        NOT NULL,
    -- One of: ranked | insufficient_history | insufficient_coverage | low_confidence
    -- 'ranked'                 — normal; category_rank and composite assigned
    -- 'low_confidence'         — ranked but N < min_peers (8); rank noisy
    -- 'insufficient_history'   — < min_history NAV bars; excluded from peer set
    -- 'insufficient_coverage'  — W_i < W_min; too many null metrics

    last_ranked_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Timestamp of the ranking run that produced this row.

    data_as_of              DATE        NOT NULL,
    -- Latest NAV date actually used (≤ rank_date).
    -- Staleness = rank_date − data_as_of.

    PRIMARY KEY (scheme_code, rank_date)
);

COMMENT ON TABLE nidp.mf_category_rank_daily IS
'Corrected MF peer rankings produced by services.mf_category_ranking. '
'One row per (scheme_code, rank_date). Supersedes analytics.fund_category_rank.'
'composite_rank column. Served via nidp.v_v3_mf_primitives (migration 085).';

COMMENT ON COLUMN nidp.mf_category_rank_daily.metric_contributions IS
'Per-metric audit trail: {metric: {value, pct, weight, contribution}}. '
'Invariant: weighted_sum(pct * weight / W_i) == composite ±0.01.';

COMMENT ON COLUMN nidp.mf_category_rank_daily.category_pct IS
'(N − rank) / (N − 1) × 100.  Best fund = 100.  '
'Feeds percentile_rank in V3 scoring contract and rec-engine persona thresholds.';


-- ── Indexes ─────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_mf_cat_rank_category_date
    ON nidp.mf_category_rank_daily (sebi_category, rank_date DESC, category_rank ASC NULLS LAST);
-- Leaderboard queries: "top N in Large Cap as of date D"

CREATE INDEX IF NOT EXISTS idx_mf_cat_rank_scheme_date
    ON nidp.mf_category_rank_daily (scheme_code, rank_date DESC);
-- Per-fund rank history

CREATE INDEX IF NOT EXISTS idx_mf_cat_rank_date_status
    ON nidp.mf_category_rank_daily (rank_date DESC, status);
-- Run monitoring / coverage dashboards


-- ── Optional run-metrics table ──────────────────────────────────────────
-- Stores per-category statistics for each ranking run (observability).
-- If this table is not needed, the service falls back to structured logging.

CREATE TABLE IF NOT EXISTS nidp.mf_ranking_run_metrics (
    run_id                  TEXT        NOT NULL,
    sebi_category           TEXT        NOT NULL,
    rank_date               DATE        NOT NULL,
    ranked_count            INTEGER     NOT NULL DEFAULT 0,
    insufficient_history_count  INTEGER NOT NULL DEFAULT 0,
    insufficient_coverage_count INTEGER NOT NULL DEFAULT 0,
    low_confidence_count    INTEGER     NOT NULL DEFAULT 0,
    total_input_count       INTEGER     NOT NULL DEFAULT 0,
    dedupe_collapse_count   INTEGER     NOT NULL DEFAULT 0,
    null_counts_per_metric  JSONB       NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (run_id, sebi_category)
);

COMMENT ON TABLE nidp.mf_ranking_run_metrics IS
'Per-category run statistics emitted by services.mf_category_ranking. '
'AC-12 observability requirement.';

CREATE INDEX IF NOT EXISTS idx_mf_ranking_run_date
    ON nidp.mf_ranking_run_metrics (rank_date DESC, run_id);


-- ── Audit ────────────────────────────────────────────────────────────────
INSERT INTO nidp.schema_migrations (filename)
VALUES ('084_mf_category_rank_daily.sql')
ON CONFLICT (filename) DO NOTHING;
