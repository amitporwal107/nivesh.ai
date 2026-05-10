-- ─────────────────────────────────────────────────────────────────
-- Migration 044 — NIDP 90-Day Historical Replay & Backtesting Engine
-- ─────────────────────────────────────────────────────────────────
-- Adds an `audit` schema to track replay invocations + per-date
-- outcomes, and a versioned scoring policy registry so the engine can
-- compare {Q = 0.40A+0.30C+0.15P+0.10F+0.05U} against
-- {Q = 0.30A+0.25C+0.20L+0.15F+0.10K} (and any future policy) without
-- rerunning ingesters.

CREATE SCHEMA IF NOT EXISTS audit;

-- ── policy_versions ─────────────────────────────────────────────────
-- Stored scoring policy: weights, certification thresholds, publish
-- gate cutoffs. Replay engine reads the active row by `version`.
CREATE TABLE IF NOT EXISTS audit.policy_versions (
    version         TEXT PRIMARY KEY,
    description     TEXT,
    -- Weights for Q (must sum to ~1.0; engine validates)
    w_accuracy      NUMERIC(4,3) NOT NULL,
    w_consistency   NUMERIC(4,3) NOT NULL,
    w_completeness  NUMERIC(4,3) NOT NULL,
    w_freshness     NUMERIC(4,3) NOT NULL,
    w_confidence    NUMERIC(4,3) NOT NULL,        -- = K-weight (if K replaces auditability) OR auditability
    -- Certification thresholds (overall_score Q)
    cert_gold       NUMERIC(5,2) NOT NULL DEFAULT 99.0,
    cert_silver     NUMERIC(5,2) NOT NULL DEFAULT 95.0,
    cert_review     NUMERIC(5,2) NOT NULL DEFAULT 90.0,
    -- Publish gate
    publish_min     NUMERIC(5,2) NOT NULL DEFAULT 95.0,
    review_min      NUMERIC(5,2) NOT NULL DEFAULT 90.0,
    confidence_min  NUMERIC(5,2) NOT NULL DEFAULT 90.0,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed two default policies — legacy (existing weights) and v1 (PRD).
INSERT INTO audit.policy_versions
    (version, description,
     w_accuracy, w_consistency, w_completeness, w_freshness, w_confidence,
     cert_gold, cert_silver, cert_review,
     publish_min, review_min, confidence_min)
VALUES
    ('legacy', 'Pre-replay weights: Q = 0.40A + 0.30C + 0.15P + 0.10F + 0.05U',
     0.40, 0.30, 0.15, 0.10, 0.05,
     99.5, 95.0, 90.0,
     95.0, 90.0, 90.0),
    ('v1', 'PRD-spec weights: Q = 0.30A + 0.25C + 0.20L + 0.15F + 0.10K',
     0.30, 0.25, 0.20, 0.15, 0.10,
     99.0, 95.0, 90.0,
     95.0, 90.0, 90.0)
ON CONFLICT (version) DO NOTHING;


-- ── replay_runs ─────────────────────────────────────────────────────
-- One row per `python -m nidp.quality.replay ...` invocation.
CREATE TABLE IF NOT EXISTS audit.replay_runs (
    replay_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL DEFAULT 'RUNNING',
    -- Replay window
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    domains         TEXT[] NOT NULL,
    policy_version  TEXT NOT NULL REFERENCES audit.policy_versions(version),
    -- Knobs
    parallel        INTEGER NOT NULL DEFAULT 1,
    inject_failures BOOLEAN NOT NULL DEFAULT FALSE,
    reset_data      BOOLEAN NOT NULL DEFAULT FALSE,
    -- Counters (filled at end)
    dates_total     INTEGER NOT NULL DEFAULT 0,
    dates_processed INTEGER NOT NULL DEFAULT 0,
    dates_failed    INTEGER NOT NULL DEFAULT 0,
    -- Free-form extras
    config_json     JSONB,
    error           TEXT,
    initiated_by    TEXT,
    CHECK (status IN ('RUNNING','SUCCESS','FAILED','CANCELLED'))
);

CREATE INDEX IF NOT EXISTS idx_replay_runs_started
    ON audit.replay_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_replay_runs_status
    ON audit.replay_runs(status, started_at DESC);


-- ── replay_dates ────────────────────────────────────────────────────
-- Per (replay, target_date, domain) outcome — what the gate decided
-- under that policy on that date, what score was computed, etc.
CREATE TABLE IF NOT EXISTS audit.replay_dates (
    replay_id       UUID NOT NULL REFERENCES audit.replay_runs(replay_id) ON DELETE CASCADE,
    target_date     DATE NOT NULL,
    domain          TEXT NOT NULL,
    -- Result
    overall_score   NUMERIC(6,3),
    confidence_score NUMERIC(6,3),
    accuracy        NUMERIC(6,3),
    consistency     NUMERIC(6,3),
    completeness    NUMERIC(6,3),
    freshness       NUMERIC(6,3),
    auditability    NUMERIC(6,3),
    certification   TEXT,
    publish_decision TEXT,
    gate_outcome    TEXT,             -- PASS | REVIEW | FAIL
    block_findings  INTEGER NOT NULL DEFAULT 0,
    rules_run       INTEGER NOT NULL DEFAULT 0,
    rules_failed    INTEGER NOT NULL DEFAULT 0,
    duration_ms     INTEGER,
    error           TEXT,
    finished_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (replay_id, target_date, domain)
);

CREATE INDEX IF NOT EXISTS idx_replay_dates_target
    ON audit.replay_dates(target_date DESC, domain);
CREATE INDEX IF NOT EXISTS idx_replay_dates_outcome
    ON audit.replay_dates(gate_outcome, target_date DESC);


-- ── replay_statistics ───────────────────────────────────────────────
-- Aggregate roll-up populated at end of replay (one row per run).
-- Used to power the dashboard's "calibration" view.
CREATE TABLE IF NOT EXISTS audit.replay_statistics (
    replay_id           UUID PRIMARY KEY REFERENCES audit.replay_runs(replay_id) ON DELETE CASCADE,
    total_evaluations   INTEGER NOT NULL DEFAULT 0,
    pass_count          INTEGER NOT NULL DEFAULT 0,
    review_count        INTEGER NOT NULL DEFAULT 0,
    fail_count          INTEGER NOT NULL DEFAULT 0,
    avg_overall_score   NUMERIC(6,3),
    p50_overall_score   NUMERIC(6,3),
    p10_overall_score   NUMERIC(6,3),
    cert_gold           INTEGER NOT NULL DEFAULT 0,
    cert_silver         INTEGER NOT NULL DEFAULT 0,
    cert_review         INTEGER NOT NULL DEFAULT 0,
    cert_rejected       INTEGER NOT NULL DEFAULT 0,
    publish_auto        INTEGER NOT NULL DEFAULT 0,
    publish_review      INTEGER NOT NULL DEFAULT 0,
    publish_reject      INTEGER NOT NULL DEFAULT 0,
    quarantine_count    INTEGER NOT NULL DEFAULT 0,
    exception_count     INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms     INTEGER,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── replay_failures (synthetic injection log) ───────────────────────
-- Records each synthetic defect injected for a replay. Useful for
-- ground-truth validation: did the gate correctly catch the injected
-- failure?
CREATE TABLE IF NOT EXISTS audit.replay_failures (
    failure_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    replay_id       UUID NOT NULL REFERENCES audit.replay_runs(replay_id) ON DELETE CASCADE,
    target_date     DATE NOT NULL,
    domain          TEXT NOT NULL,
    failure_type    TEXT NOT NULL,    -- schema_drift | duplicate_keys | null_injection | delayed_arrival | cross_source_mismatch
    target_table    TEXT,
    rows_affected   INTEGER NOT NULL DEFAULT 0,
    detected        BOOLEAN,          -- did the gate catch it?
    detected_by     TEXT,             -- e.g. expectation rule name
    payload_json    JSONB,
    injected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_replay_failures_run
    ON audit.replay_failures(replay_id, target_date);


-- ── Idempotent registration ─────────────────────────────────────────
INSERT INTO nidp.schema_migrations(filename) VALUES ('044_nidp_replay_engine.sql')
    ON CONFLICT (filename) DO NOTHING;
