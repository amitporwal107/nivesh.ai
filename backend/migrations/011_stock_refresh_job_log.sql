-- Phase 3: Audit log for Nifty 100 stock refresh job.
-- Mirrors nav_analytics_job_log shape so the admin /data-pipeline/logs
-- endpoint can return a unified schema.

CREATE TABLE IF NOT EXISTS stock_refresh_job_log (
    id              BIGSERIAL PRIMARY KEY,
    job_name        TEXT NOT NULL,      -- 'nifty100_refresh' | 'stock_refresh_manual'
    status          TEXT NOT NULL,      -- 'ok' | 'partial' | 'failed'
    stocks_total    INTEGER,
    stocks_succeeded INTEGER,
    stocks_failed   INTEGER,
    duration_ms     INTEGER,
    error_msg       TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_refresh_log_started
    ON stock_refresh_job_log(job_name, started_at DESC);
