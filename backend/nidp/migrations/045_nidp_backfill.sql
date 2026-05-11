-- ─────────────────────────────────────────────────────────────────
-- Migration 045 — Backfill Orchestrator audit tables
-- ─────────────────────────────────────────────────────────────────
-- Tracks long-running historical backfill runs that walk NSE archives
-- across N trading days × M ingesters. One row per invocation + one
-- row per (date, ingester) job.

-- ── backfill_runs ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit.backfill_runs (
    backfill_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'RUNNING',
    -- Window
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    ingesters       TEXT[] NOT NULL,
    -- Knobs
    wipe_first      BOOLEAN NOT NULL DEFAULT TRUE,
    politeness_ms   INTEGER NOT NULL DEFAULT 4000,
    parallel        INTEGER NOT NULL DEFAULT 1,
    auto_replay     BOOLEAN NOT NULL DEFAULT FALSE,
    -- Counters
    jobs_total      INTEGER NOT NULL DEFAULT 0,
    jobs_done       INTEGER NOT NULL DEFAULT 0,
    jobs_failed     INTEGER NOT NULL DEFAULT 0,
    rows_loaded     BIGINT  NOT NULL DEFAULT 0,
    -- Outcome metadata
    replay_id       UUID,                                  -- set when auto_replay completes
    error           TEXT,
    initiated_by    TEXT,
    config_json     JSONB,
    CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED','CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_backfill_runs_started
    ON audit.backfill_runs(started_at DESC);


-- ── backfill_jobs ───────────────────────────────────────────────────
-- Per (backfill_id, target_date, ingester) — one row per NSE archive
-- request the orchestrator makes.
CREATE TABLE IF NOT EXISTS audit.backfill_jobs (
    backfill_id     UUID NOT NULL REFERENCES audit.backfill_runs(backfill_id) ON DELETE CASCADE,
    target_date     DATE NOT NULL,
    ingester        TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',         -- PENDING|RUNNING|DONE|FAILED|SKIPPED
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    rows_loaded     INTEGER,
    duration_ms     INTEGER,
    attempt         INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    log_tail        TEXT,                                    -- last few lines of stdout/stderr on failure
    PRIMARY KEY (backfill_id, target_date, ingester),
    CHECK (status IN ('PENDING','RUNNING','DONE','FAILED','SKIPPED'))
);

CREATE INDEX IF NOT EXISTS idx_backfill_jobs_status
    ON audit.backfill_jobs(backfill_id, status);


-- ── Idempotent registration ─────────────────────────────────────────
INSERT INTO nidp.schema_migrations(filename) VALUES ('045_nidp_backfill.sql')
    ON CONFLICT (filename) DO NOTHING;
