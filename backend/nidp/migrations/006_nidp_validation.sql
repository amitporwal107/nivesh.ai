-- 006_nidp_validation.sql — Data Quality / Validation tables.
--
-- Validation runs after every ingester persist (BaseIngester hook) and
-- emits zero or more findings. Findings are categorised by severity
-- (INFO|WARN|ERROR|CRITICAL) and class (RETRY|FIX|BLOCK), so the
-- snapshot engine can refuse to build for dates with BLOCK findings
-- without re-running validation.
--
-- Tables:
--   validation_runs      — one row per validator run (links to job_log)
--   validation_findings  — one row per failed assertion
--
-- Append-only: a re-run produces a new validation_runs row; old rows
-- are preserved for audit/explainability.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.validation_runs (
    validation_id   UUID PRIMARY KEY,
    job_run_id      UUID NOT NULL,                  -- → nidp.job_log.run_id
    ingester        TEXT NOT NULL,
    target_date     DATE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    status          TEXT NOT NULL,                   -- PASSED | FAILED | PARTIAL | ERROR
    rules_run       INTEGER NOT NULL DEFAULT 0,
    rules_failed    INTEGER NOT NULL DEFAULT 0,
    findings_count  INTEGER NOT NULL DEFAULT 0,
    notes           TEXT,
    CHECK (status IN ('PASSED','FAILED','PARTIAL','ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_validation_runs_ingester_date
    ON nidp.validation_runs(ingester, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_validation_runs_started
    ON nidp.validation_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_validation_runs_status
    ON nidp.validation_runs(status) WHERE status IN ('FAILED','PARTIAL','ERROR');


CREATE TABLE IF NOT EXISTS nidp.validation_findings (
    finding_id      UUID PRIMARY KEY,
    validation_id   UUID NOT NULL,                   -- → nidp.validation_runs.validation_id
    job_run_id      UUID NOT NULL,                   -- denormed for fast filter
    ingester        TEXT NOT NULL,
    target_date     DATE,
    rule_name       TEXT NOT NULL,                   -- e.g. 'bhavcopy.row_count_min'
    severity        TEXT NOT NULL,                   -- INFO | WARN | ERROR | CRITICAL
    failure_class   TEXT NOT NULL,                   -- RETRY | FIX | BLOCK | INFO
    message         TEXT NOT NULL,
    expected        TEXT,
    actual          TEXT,
    sample_rows     JSONB,                           -- up to 10 offending rows for triage
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (severity IN ('INFO','WARN','ERROR','CRITICAL')),
    CHECK (failure_class IN ('RETRY','FIX','BLOCK','INFO'))
);

CREATE INDEX IF NOT EXISTS idx_findings_ingester_date
    ON nidp.validation_findings(ingester, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_findings_blocking
    ON nidp.validation_findings(target_date)
    WHERE failure_class = 'BLOCK';
CREATE INDEX IF NOT EXISTS idx_findings_severity_date
    ON nidp.validation_findings(severity, target_date DESC);


-- Convenience view: most-recent validation status per (ingester, date).
CREATE OR REPLACE VIEW nidp.v_latest_validation AS
SELECT DISTINCT ON (ingester, target_date)
    ingester, target_date, validation_id, status,
    rules_run, rules_failed, findings_count, started_at
FROM nidp.validation_runs
ORDER BY ingester, target_date DESC, started_at DESC;


INSERT INTO nidp.schema_migrations(filename) VALUES ('006_nidp_validation.sql')
    ON CONFLICT (filename) DO NOTHING;
