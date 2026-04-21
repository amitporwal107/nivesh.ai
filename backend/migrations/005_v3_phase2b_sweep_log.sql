-- V3 Engine Phase 2b: Analytics sweep log + composite score cache columns.

-- Per-sweep audit table (mirrors amfi_nav_fetch_log shape)
CREATE TABLE IF NOT EXISTS nav_analytics_job_log (
    id               BIGSERIAL PRIMARY KEY,
    job_name         TEXT NOT NULL,  -- 'analytics_sweep' | 'v3_rescore' | 'nav_analytics_manual'
    status           TEXT NOT NULL,  -- 'ok' | 'partial' | 'failed'
    funds_total      INTEGER,
    funds_processed  INTEGER,
    funds_skipped    INTEGER,
    funds_failed     INTEGER,
    duration_ms      INTEGER,
    error_msg        TEXT,
    started_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_nav_analytics_log_started
    ON nav_analytics_job_log(job_name, started_at DESC);

-- Composite score cache columns on metadata (durable fallback for Redis)
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS quality_score       NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS health_score        NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS exit_score_baseline NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS add_score_baseline  NUMERIC(5,2);
ALTER TABLE mutual_fund_metadata ADD COLUMN IF NOT EXISTS v3_scored_at        TIMESTAMPTZ;
