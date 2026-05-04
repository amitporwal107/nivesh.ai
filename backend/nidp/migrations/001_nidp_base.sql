-- 001_nidp_base.sql — NIDP base schema, job log, raw archive, daily snapshot.
--
-- All NIDP tables live in the `nidp` Postgres schema. This isolates the
-- platform from the existing application schema during validation; we
-- can DROP SCHEMA nidp CASCADE to fully unwind without touching live
-- data.
--
-- Design rules (locked):
--   1. Append-only by `as_of_date`. Never overwrite a fact row in place.
--   2. Every fact row carries `source` + `source_run_id` so a bad source
--      run can be revoked or replayed.
--   3. PK includes `source` so multiple sources can coexist for the
--      same (date, symbol) — reconciliation lives downstream, not at
--      the storage layer.
--   4. `ingested_at` is wall-clock for the write; `as_of_date` is the
--      data's logical date. They are always different concepts.
--   5. Idempotent migrations — IF NOT EXISTS everywhere.

CREATE SCHEMA IF NOT EXISTS nidp;

SET search_path TO nidp, public;

-- ── Per-run job log ─────────────────────────────────────────────────
-- One row per ingester invocation. Records intent (target_date) and
-- outcome (rows_*, status, error). Powers the data-health dashboard
-- (PRD §15-16).
CREATE TABLE IF NOT EXISTS nidp.job_log (
    run_id          UUID PRIMARY KEY,
    ingester        TEXT NOT NULL,                  -- 'bhavcopy' | 'fii_dii' | …
    target_date     DATE,                            -- logical AS-OF date being ingested
    source_url      TEXT,
    status          TEXT NOT NULL,                   -- RUNNING | OK | FAILED | PARTIAL | SKIPPED
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INTEGER,
    rows_fetched    INTEGER,
    rows_inserted   INTEGER,
    rows_skipped    INTEGER,
    error_message   TEXT,
    error_class     TEXT,                            -- 'HTTP' | 'PARSE' | 'VALIDATE' | 'DB'
    artifact_path   TEXT,                            -- path under nidp.raw_archive_files for the source bytes
    metadata        JSONB,                           -- ingester-specific (file-format version, etc.)
    CHECK (status IN ('RUNNING','OK','FAILED','PARTIAL','SKIPPED'))
);

CREATE INDEX IF NOT EXISTS idx_nidp_job_log_ingester_date
    ON nidp.job_log(ingester, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_nidp_job_log_started
    ON nidp.job_log(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_nidp_job_log_status
    ON nidp.job_log(status) WHERE status IN ('FAILED','PARTIAL');


-- ── Raw archive metadata ────────────────────────────────────────────
-- We persist the *original* downloaded bytes (CSV/XLS/ZIP) to disk
-- under data/nidp_raw/ and index them here. This lets us replay
-- ingestion deterministically when parsers change without re-hitting
-- the source. Critical for long-term reproducibility (PRD §14
-- "Idempotent ingestion").
CREATE TABLE IF NOT EXISTS nidp.raw_archive_files (
    archive_id      UUID PRIMARY KEY,
    ingester        TEXT NOT NULL,
    target_date     DATE,
    source_url      TEXT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    file_path       TEXT NOT NULL,                   -- relative to NIDP_RAW_DIR
    file_bytes      INTEGER,
    file_sha256     TEXT,                            -- de-dup identical fetches
    content_type    TEXT,
    http_status     INTEGER,
    metadata        JSONB
);

CREATE INDEX IF NOT EXISTS idx_nidp_raw_ingester_date
    ON nidp.raw_archive_files(ingester, target_date DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_nidp_raw_sha
    ON nidp.raw_archive_files(ingester, file_sha256)
    WHERE file_sha256 IS NOT NULL;


-- ── Source registry ─────────────────────────────────────────────────
-- One row per logical (ingester, source-name) pair. Tracks source
-- reliability score over time so the validation layer can downgrade a
-- source automatically when it gets flaky.
CREATE TABLE IF NOT EXISTS nidp.source_registry (
    source_name     TEXT PRIMARY KEY,                -- 'NSE_BHAVCOPY' | 'NSE_FII_DII' | 'RBI_REF_RATE'
    ingester        TEXT NOT NULL,
    source_url_pattern TEXT NOT NULL,
    source_class    TEXT NOT NULL,                   -- A | B | C | D | E (see PRD reliability scale)
    confidence      NUMERIC(3,2) NOT NULL,           -- 0.00 - 1.00
    is_primary      BOOLEAN NOT NULL DEFAULT TRUE,
    expected_freq   TEXT NOT NULL,                   -- 'daily' | 'monthly' | 'quarterly' | 'event'
    last_success_at TIMESTAMPTZ,
    last_failure_at TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── Daily snapshot (PRD §9, §10) ────────────────────────────────────
-- The single AS-OF coherence record. One row per market trading day.
-- Records *which* domains successfully ingested for that date, so
-- downstream consumers can refuse to compute signals on partial days.
CREATE TABLE IF NOT EXISTS nidp.daily_snapshot (
    as_of_date          DATE PRIMARY KEY,
    snapshot_status     TEXT NOT NULL DEFAULT 'BUILDING',  -- BUILDING | READY | INCOMPLETE | FAILED
    -- Per-domain readiness flags
    prices_eod_ready    BOOLEAN NOT NULL DEFAULT FALSE,
    delivery_ready      BOOLEAN NOT NULL DEFAULT FALSE,
    index_eod_ready     BOOLEAN NOT NULL DEFAULT FALSE,
    fii_dii_ready       BOOLEAN NOT NULL DEFAULT FALSE,
    corp_actions_ready  BOOLEAN NOT NULL DEFAULT FALSE,
    bulk_deals_ready    BOOLEAN NOT NULL DEFAULT FALSE,
    block_deals_ready   BOOLEAN NOT NULL DEFAULT FALSE,
    rbi_yields_ready    BOOLEAN NOT NULL DEFAULT FALSE,
    -- Lag bookkeeping for quarterly/monthly carry-forward
    shareholding_as_of  DATE,                         -- most recent quarterly filing date
    fundamentals_as_of  DATE,                         -- most recent quarterly results date
    mf_holdings_as_of   DATE,                         -- most recent monthly disclosure date
    -- Build metadata
    built_at            TIMESTAMPTZ,
    rebuilt_at          TIMESTAMPTZ,
    build_run_ids       UUID[],                       -- references nidp.job_log.run_id
    notes               TEXT,
    CHECK (snapshot_status IN ('BUILDING','READY','INCOMPLETE','FAILED'))
);

CREATE INDEX IF NOT EXISTS idx_nidp_snapshot_status
    ON nidp.daily_snapshot(snapshot_status);


-- ── Migration tracking ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.schema_migrations (
    filename        TEXT PRIMARY KEY,
    applied_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sha256          TEXT
);

INSERT INTO nidp.schema_migrations(filename) VALUES ('001_nidp_base.sql')
    ON CONFLICT (filename) DO NOTHING;
