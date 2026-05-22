-- 001_init_schema.sql — bootstrap the portfolio_ingestion schema.
--
-- Mirrors PRD §6.2 exactly, with two additions to defend the core invariant:
--   • partial unique index  one_active_snapshot_per_pan
--   • UNIQUE(pan_hash, checksum) on ingestion_jobs (idempotency)
--
-- PAN is stored hashed (SHA-256 hex) for lookups; encrypted PAN payload
-- (pan_enc BYTEA) lands in 002_pgcrypto_pan.sql.

CREATE EXTENSION IF NOT EXISTS pgcrypto;        -- gen_random_uuid()

CREATE SCHEMA IF NOT EXISTS portfolio_ingestion;
SET search_path TO portfolio_ingestion;

-- ── users ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id   TEXT        NOT NULL UNIQUE,    -- maps to host app's user_id
    pan_hash      VARCHAR(64) NOT NULL UNIQUE,    -- SHA-256 hex of PAN
    pan_enc       BYTEA,                          -- filled in 002_pgcrypto_pan.sql
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── ingestion_jobs ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID        NOT NULL REFERENCES users(id),
    pan_hash         VARCHAR(64) NOT NULL,
    source_type      TEXT        NOT NULL,           -- ECAS_CDSL|ECAS_NSDL|MF_CAMS|MF_KFIN
    method           TEXT        NOT NULL,           -- upload|inbox|generator|cdsl_fetch
    checksum         VARCHAR(64),                    -- SHA-256 of PDF; null for cdsl_fetch
    pdf_gcs_key      TEXT,
    pdf_status       TEXT,                           -- pending|downloaded|unavailable
    raw_data_ref     TEXT,                           -- MongoDB ObjectId reference
    status           TEXT        NOT NULL,           -- received|parsing|activated|failed
    failure_reason   TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at     TIMESTAMPTZ,
    CONSTRAINT ingestion_jobs_pan_checksum_uniq UNIQUE (pan_hash, checksum)
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON ingestion_jobs (status);
CREATE INDEX IF NOT EXISTS idx_jobs_user   ON ingestion_jobs (user_id, created_at DESC);

-- ── snapshots ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pan_hash          VARCHAR(64) NOT NULL,
    source_type       TEXT        NOT NULL,
    statement_from    DATE        NOT NULL,
    statement_to      DATE        NOT NULL,
    generated_at      TIMESTAMPTZ NOT NULL,
    ingestion_job_id  UUID        REFERENCES ingestion_jobs(id),
    is_active         BOOLEAN     NOT NULL DEFAULT false,
    total_value       NUMERIC(18,2),
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    deactivated_at    TIMESTAMPTZ
);

-- Core invariant: at most one active snapshot per PAN.
CREATE UNIQUE INDEX IF NOT EXISTS one_active_snapshot_per_pan
    ON snapshots (pan_hash)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_snapshots_pan_time
    ON snapshots (pan_hash, statement_to DESC);

-- ── holdings ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS holdings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pan_hash      VARCHAR(64) NOT NULL,
    snapshot_id   UUID        NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    asset_class   TEXT        NOT NULL,
    isin          VARCHAR(12),
    amfi_code     VARCHAR(10),
    folio         TEXT,
    scheme_code   TEXT,
    amc           TEXT,
    name          TEXT        NOT NULL,
    quantity      NUMERIC(20,4) NOT NULL,
    value         NUMERIC(18,2) NOT NULL,
    source_trace  JSONB         NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_holdings_pan      ON holdings (pan_hash);
CREATE INDEX IF NOT EXISTS idx_holdings_isin     ON holdings (isin)
    WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_holdings_mf_folio ON holdings (pan_hash, amc, folio, scheme_code);
