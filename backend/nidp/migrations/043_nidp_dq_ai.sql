-- 043_nidp_dq_ai.sql
-- AI-assisted data quality additions (additive, no breaking changes).
--
--   1. dq.smell_diagnostics       — output of the smell analyzer
--   2. dq.expectations_active     — dynamic registry of active rules
--   3. dq.expectation_proposals   — AI-proposed rules pending human review
--
-- The legacy hand-written suites in nidp/shared/expectations.py keep
-- working unchanged. Once we seed them into expectations_active and
-- the runner is taught to read from this table, hand-edits move to
-- the DB. For now the table exists in parallel.

SET search_path TO public;

-- ── 1) Smell diagnostics ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dq.smell_diagnostics (
    diagnostic_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID,                                    -- soft FK to dq.validation_runs (nullable: ad-hoc analysis allowed)
    dataset_name         TEXT NOT NULL,
    target_date          DATE,
    smell                TEXT NOT NULL,                           -- 1-line headline
    root_causes_json     JSONB NOT NULL,                          -- array[ {hypothesis, confidence(0..1)} ]
    suggested_fixes_json JSONB NOT NULL,                          -- array[ {action, kind, expression?} ]
    affected_subset_json JSONB,                                   -- {affected_rows, sample_keys, ...}
    sample_failed_rows   JSONB,                                   -- the 10-50 rows shown to the LLM
    blocking_for_intelligence BOOLEAN,
    estimated_impact     TEXT,
    llm_model            TEXT NOT NULL,
    llm_prompt_tokens    INTEGER,
    llm_completion_tokens INTEGER,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dq_smell_dataset
    ON dq.smell_diagnostics (dataset_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dq_smell_run
    ON dq.smell_diagnostics (run_id);


-- ── 2) Active expectation registry ──────────────────────────────────
-- Each row is one validation rule. Runner reads active=TRUE rules at
-- start-of-day and evaluates them.
CREATE TABLE IF NOT EXISTS dq.expectations_active (
    rule_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_name      TEXT NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT,
    expression        TEXT NOT NULL,                              -- SQL fragment evaluated against the dataset
    severity          TEXT NOT NULL CHECK (severity IN ('INFO','WARN','ERROR','CRITICAL')),
    source            TEXT NOT NULL CHECK (source IN ('hand','ai_proposed','promoted')),
    active            BOOLEAN NOT NULL DEFAULT TRUE,
    rationale         TEXT,
    business_impact   TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    promoted_by       TEXT,
    promoted_at       TIMESTAMPTZ,
    UNIQUE (dataset_name, name)
);

CREATE INDEX IF NOT EXISTS idx_dq_exp_active_dataset
    ON dq.expectations_active (dataset_name, active);


-- ── 3) AI proposals awaiting human review ──────────────────────────
CREATE TABLE IF NOT EXISTS dq.expectation_proposals (
    proposal_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_name       TEXT NOT NULL,
    proposed_rule_json JSONB NOT NULL,                            -- {name,description,expression,severity,rationale,business_impact}
    status             TEXT NOT NULL DEFAULT 'proposed'
                       CHECK (status IN ('proposed','accepted','rejected','superseded')),
    review_notes       TEXT,
    reviewed_by        TEXT,
    reviewed_at        TIMESTAMPTZ,
    promoted_rule_id   UUID,                                      -- soft FK to dq.expectations_active.rule_id when accepted
    llm_model          TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dq_proposals_dataset_status
    ON dq.expectation_proposals (dataset_name, status, created_at DESC);


INSERT INTO nidp.schema_migrations(filename)
VALUES ('043_nidp_dq_ai.sql')
ON CONFLICT (filename) DO NOTHING;
