-- 111_validation_runs_asset_and_dq_rollup.sql
-- Fix the "ingester collapse": multiple DQ suites map to one feed ingester (e.g.
-- v3_stock_scores + v3_mf_scores both -> v3_scores_engine), so a DISTINCT ON (ingester)
-- surfacing picks one suite's verdict and drops the other.
--
-- 1. Track the asset (table) per validation run, so suites that share an ingester are
--    distinguishable.
-- 2. nidp.v_feed_dq — per-ingester rollup: the WORST status across the latest run per
--    asset, plus summed findings. Env-agnostic (reads only validation_runs), so it
--    applies cleanly to prod and staging.
-- Re-runnable.

ALTER TABLE nidp.validation_runs ADD COLUMN IF NOT EXISTS asset text;

CREATE OR REPLACE VIEW nidp.v_feed_dq AS
WITH latest_per_asset AS (
    SELECT DISTINCT ON (ingester, asset)
        ingester, asset, status, rules_failed, findings_count, started_at
    FROM nidp.validation_runs
    WHERE asset IS NOT NULL
    ORDER BY ingester, asset, started_at DESC
)
SELECT
    ingester,
    CASE max(CASE status WHEN 'ERROR'  THEN 4 WHEN 'FAILED'  THEN 3
                         WHEN 'PARTIAL' THEN 2 WHEN 'PASSED' THEN 1 ELSE 0 END)
        WHEN 4 THEN 'ERROR' WHEN 3 THEN 'FAILED' WHEN 2 THEN 'PARTIAL'
        WHEN 1 THEN 'PASSED' ELSE 'NONE' END  AS dq_status,   -- worst wins
    count(*)            AS dq_assets,
    sum(rules_failed)   AS dq_rules_failed,
    sum(findings_count) AS dq_findings,
    max(started_at)     AS dq_checked_at
FROM latest_per_asset
GROUP BY ingester;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('111_validation_runs_asset_and_dq_rollup.sql')
ON CONFLICT (filename) DO NOTHING;
