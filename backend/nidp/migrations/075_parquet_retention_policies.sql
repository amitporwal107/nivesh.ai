-- Migration 075: TimescaleDB retention policies for WARM-tier tables
--
-- PURPOSE
--   Once Parquet export (parquet_exporter service) is running reliably
--   and DuckDB is available for historical queries, these retention policies
--   allow TimescaleDB to drop old chunks and reclaim disk space.
--
-- PREREQUISITE
--   1. parquet_exporter cron has been running for ≥ 7 days without errors
--   2. DuckDB analytics endpoint is live and tested
--   3. Confirm Parquet files exist in MinIO for the dates you are about to drop:
--        SELECT count(*) FROM nidp.raw_archive_files WHERE file_path LIKE 'minio://%parquet%';
--
-- ACTIVATION
--   Remove the /* and */ comment markers below and run this migration.
--   Dry-run first with:
--     SELECT show_chunks('nidp.stock_features_daily', older_than => INTERVAL '180 days');
--     SELECT show_chunks('nidp.prices_eod',           older_than => INTERVAL '365 days');
--
-- SAFETY
--   Retention is one-way — dropped chunks cannot be recovered from TimescaleDB.
--   The Parquet files on MinIO are the only copy for dropped date ranges.
--   Keep raw_archive_files rows (they point to MinIO objects) so replay still works.

-- No-op: retention policies are deliberately inactive until parquet
-- export is confirmed live. This statement exists only so asyncpg's
-- conn.execute() gets a valid SQL result.
SELECT 1;

-- ============================================================
-- UNCOMMENT BELOW ONLY AFTER PARQUET EXPORT IS CONFIRMED LIVE
-- ============================================================

/*

-- stock_features_daily: keep 180 days hot (6 months of features for scoring)
-- Historical features are in Parquet on MinIO
SELECT add_retention_policy(
    'nidp.stock_features_daily',
    INTERVAL '180 days',
    if_not_exists => true
);

-- prices_eod: keep 365 days hot (1 year for TA calculations)
-- Older history is in Parquet on MinIO
SELECT add_retention_policy(
    'nidp.prices_eod',
    INTERVAL '365 days',
    if_not_exists => true
);

-- prices_eod_adjusted: same window as prices_eod
SELECT add_retention_policy(
    'nidp.prices_eod_adjusted',
    INTERVAL '365 days',
    if_not_exists => true
);

-- nse_financials_quarterly: keep 5 years hot (20 quarters for trend analysis)
SELECT add_retention_policy(
    'nidp.nse_financials_quarterly',
    INTERVAL '5 years',
    if_not_exists => true
);

*/

-- Verify policies after activation:
-- SELECT * FROM timescaledb_information.jobs WHERE proc_name = 'policy_retention';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('075_parquet_retention_policies.sql')
ON CONFLICT (filename) DO NOTHING;
