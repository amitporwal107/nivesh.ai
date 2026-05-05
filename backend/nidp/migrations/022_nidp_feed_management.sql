-- 022_nidp_feed_management.sql — Per-feed archive + snapshot + status.
--
-- Closes three gaps in the feed-management story:
--
--   (a) Parsed archive: raw bytes are already archived in
--       nidp.raw_archive_files. We additionally archive the parsed +
--       validated *normalized* rows as gzipped JSONL on the storage
--       backend, indexed in nidp.parsed_archive_files. This means a
--       schema-migration / model-recompute can replay ANY past run
--       without re-parsing the raw file.
--
--   (b) Per-feed snapshot in DB: nidp.feed_snapshot stores one row per
--       (ingester, snapshot_date) with a JSONB payload of the parsed
--       rows + pointers to both archives. snapshot_date is the
--       business AS-OF date the parsed data represents (target_date
--       for dated feeds; run date for rolling APIs).
--
--   (c) Per-feed dashboard: nidp.source_registry is extended with
--       last_run_at, next_run_at, last_run_status, last_run_duration_ms
--       and success/failure/partial counters. The view
--       nidp.v_feed_status surfaces a single row per feed for ops.

SET search_path TO nidp, public;

-- ── (c) Per-feed dashboard fields on source_registry ────────────────
ALTER TABLE nidp.source_registry
    ADD COLUMN IF NOT EXISTS last_run_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_run_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_run_id           UUID,
    ADD COLUMN IF NOT EXISTS last_run_status       TEXT,
    ADD COLUMN IF NOT EXISTS last_run_duration_ms  INTEGER,
    ADD COLUMN IF NOT EXISTS success_count         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS failure_count         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS partial_count         INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS schedule_cron         TEXT;

-- Seed the registry with the 13 services we ship today. ON CONFLICT
-- preserves existing rows (this migration is idempotent).
INSERT INTO nidp.source_registry
    (source_name, ingester, source_url_pattern, source_class,
     confidence, is_primary, expected_freq, schedule_cron, notes)
VALUES
    -- NSE daily (post-market, 18:30 IST = 13:00 UTC)
    ('NSE_BHAVCOPY',           'bhavcopy',           'https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv',
        'A', 0.99, TRUE, 'daily',     '0 13 * * 1-5', 'NSE EQ bhavcopy CSV'),
    ('NSE_BULK_DEALS',         'bulk_deals',         'https://www.nseindia.com/api/historical/bulk-deals',
        'A', 0.99, TRUE, 'daily',     '15 13 * * 1-5', 'NSE bulk deals JSON API'),
    ('NSE_BLOCK_DEALS',        'block_deals',        'https://www.nseindia.com/api/historical/block-deals',
        'A', 0.99, TRUE, 'daily',     '20 13 * * 1-5', 'NSE block deals JSON API'),
    ('NSE_DELIVERY',           'delivery',           'https://archives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv',
        'A', 0.95, TRUE, 'daily',     '30 13 * * 1-5', 'NSE delivery % (lags by 1 day)'),
    ('NSE_INDEX_CLOSE',        'index_close',        'https://archives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv',
        'A', 0.99, TRUE, 'daily',     '5 13 * * 1-5',  'NSE index closes CSV'),
    ('NSE_INDEX_CONSTITUENTS', 'index_constituents', 'https://archives.nseindia.com/content/indices/ind_<index>list.csv',
        'A', 0.95, TRUE, 'monthly',   '0 5 1 * *',     'NSE index membership (monthly snap)'),
    ('NSE_FII_DII',            'fii_dii',            'https://www.nseindia.com/api/fiidiiTradeReact',
        'B', 0.90, TRUE, 'daily',     '45 13 * * 1-5', 'NSE FII/DII rolling JSON API'),
    ('NSE_CORP_ACTIONS',       'corporate_actions',  'https://www.nseindia.com/api/corporates-corporateActions?index=equities',
        'A', 0.95, TRUE, 'event',     '0 14 * * *',    'NSE corporate actions JSON'),
    ('NSE_CALENDAR',           'nse_calendar',       'https://www.nseindia.com/api/holiday-master?type=trading',
        'A', 0.99, TRUE, 'monthly',   '0 6 1 * *',     'NSE trading-holiday master'),
    -- RBI weekly
    ('RBI_YIELDS',             'rbi_yields',         'https://www.rbi.org.in/Scripts/WSSViewDetail.aspx',
        'B', 0.90, TRUE, 'daily',     '0 16 * * 1-5',  'RBI WSS yields (HTML)'),
    -- FRED daily
    ('FRED_MACRO',             'fred_macro',         'https://api.stlouisfed.org/fred/series/observations',
        'A', 0.99, TRUE, 'daily',     '0 17 * * *',    'FRED macro series API'),
    -- yfinance backfill (event-driven)
    ('YFINANCE_BACKFILL',      'yfinance_backfill',  'https://query1.finance.yahoo.com/v8/finance/chart/<symbol>',
        'C', 0.85, FALSE, 'event',    NULL,            'yfinance per-symbol history (backfill only)'),
    -- snapshot builder runs after all daily ingesters
    ('SNAPSHOT_BUILDER',       'snapshot_builder',   'internal://snapshot-builder',
        'A', 1.00, TRUE, 'daily',     '0 15 * * 1-5',  'Builds market_daily_snapshot + stock_daily_snapshot')
ON CONFLICT (source_name) DO NOTHING;


-- ── (a) Parsed archive — normalized rows on storage backend ─────────
CREATE TABLE IF NOT EXISTS nidp.parsed_archive_files (
    parsed_id        UUID PRIMARY KEY,
    ingester         TEXT NOT NULL,
    target_date      DATE,
    snapshot_date    DATE NOT NULL,                 -- business AS-OF the rows describe
    job_run_id       UUID NOT NULL,
    raw_archive_id   UUID,                          -- → nidp.raw_archive_files
    file_path        TEXT NOT NULL,                 -- storage URI (gzipped JSONL)
    file_bytes       INTEGER NOT NULL,
    file_sha256      TEXT NOT NULL,
    row_count        INTEGER NOT NULL,
    format           TEXT NOT NULL DEFAULT 'jsonl.gz',
    schema_name      TEXT,                          -- avro schema name in contracts/
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata         JSONB
);

CREATE INDEX IF NOT EXISTS idx_parsed_arc_ingester_snapdate
    ON nidp.parsed_archive_files(ingester, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_parsed_arc_runid
    ON nidp.parsed_archive_files(job_run_id);
CREATE UNIQUE INDEX IF NOT EXISTS uq_parsed_arc_run_sha
    ON nidp.parsed_archive_files(job_run_id, file_sha256);


-- ── (b) Per-feed snapshot in DB ─────────────────────────────────────
-- One row per (ingester, snapshot_date). Holds the *parsed* rows as
-- JSONB so a model-build can replay any past day without going to
-- object storage. Large feeds (e.g. bhavcopy with ~2k symbols) fit
-- comfortably in TOAST'd JSONB; per-feed rows are bounded by daily
-- universe size.
--
-- The companion `parsed_archive_files` row holds the same data as a
-- gzipped JSONL on object storage — DB row is for fast access,
-- archive is for cold storage / re-replay.
CREATE TABLE IF NOT EXISTS nidp.feed_snapshot (
    ingester          TEXT NOT NULL,
    snapshot_date     DATE NOT NULL,
    target_date       DATE,
    job_run_id        UUID NOT NULL,
    raw_archive_id    UUID,                        -- → nidp.raw_archive_files
    parsed_archive_id UUID,                        -- → nidp.parsed_archive_files
    row_count         INTEGER NOT NULL,
    rows_payload      JSONB NOT NULL,              -- the parsed rows themselves
    payload_sha256    TEXT NOT NULL,
    captured_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ingester, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_feed_snap_runid
    ON nidp.feed_snapshot(job_run_id);
CREATE INDEX IF NOT EXISTS idx_feed_snap_captured
    ON nidp.feed_snapshot(captured_at DESC);


-- ── Per-feed status view (the dashboard) ────────────────────────────
-- One row per feed. Joins source_registry's running counters with
-- the latest job_log row for at-a-glance "is this feed healthy?".
CREATE OR REPLACE VIEW nidp.v_feed_status AS
WITH last_run AS (
    SELECT DISTINCT ON (ingester)
        ingester,
        run_id           AS last_run_id,
        target_date      AS last_target_date,
        status           AS last_status,
        started_at       AS last_started_at,
        finished_at      AS last_finished_at,
        duration_ms      AS last_duration_ms,
        rows_fetched     AS last_rows_fetched,
        rows_inserted    AS last_rows_inserted,
        rows_skipped     AS last_rows_skipped,
        error_message    AS last_error_message,
        artifact_path    AS last_artifact_path
    FROM nidp.job_log
    ORDER BY ingester, started_at DESC
),
last_snapshot AS (
    SELECT DISTINCT ON (ingester)
        ingester,
        snapshot_date    AS last_snapshot_date,
        row_count        AS last_snapshot_rows,
        captured_at      AS last_snapshot_at
    FROM nidp.feed_snapshot
    ORDER BY ingester, snapshot_date DESC
)
SELECT
    s.source_name,
    s.ingester,
    s.source_class,
    s.confidence,
    s.expected_freq,
    s.schedule_cron,
    s.is_primary,
    s.last_success_at,
    s.last_failure_at,
    s.consecutive_failures,
    s.success_count,
    s.failure_count,
    s.partial_count,
    s.last_run_at,
    s.next_run_at,
    s.last_run_status,
    s.last_run_duration_ms,
    lr.last_run_id,
    lr.last_target_date,
    lr.last_started_at,
    lr.last_finished_at,
    lr.last_rows_fetched,
    lr.last_rows_inserted,
    lr.last_rows_skipped,
    lr.last_error_message,
    lr.last_artifact_path,
    ls.last_snapshot_date,
    ls.last_snapshot_rows,
    ls.last_snapshot_at
FROM nidp.source_registry s
LEFT JOIN last_run      lr USING (ingester)
LEFT JOIN last_snapshot ls USING (ingester);

COMMENT ON VIEW nidp.v_feed_status IS
    'Single-row-per-feed health view. Use for ops dashboards: '
    'last_run_*, next_run_at, success/failure_count, last_snapshot_*.';
