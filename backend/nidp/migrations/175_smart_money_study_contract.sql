-- 175: NIDP-SM-VALIDATION-001 — the preregistered study contract.
--
-- WHY THESE TABLES EXIST
-- The protocol's whole purpose is to stop a horizon, hurdle or universe being chosen AFTER the
-- results are seen. That only works if the configuration is frozen and hashed BEFORE the
-- confirmatory run, and if every prediction and outcome is stored rather than recomputed. These
-- tables are that record. The config row is immutable by trigger, not by convention.
--
-- REUSED, NOT DUPLICATED
-- nidp.smart_money_scores_daily (migrations 166/173) already carries the score, the point_in_time
-- flag, confidence, coverage and provenance, so the protocol's "smart_money_scores_daily" record
-- is that table. Nothing here re-implements it.
--
-- WHAT IS DELIBERATELY NOT HERE
-- No promotion decision is seeded. Gates B and C are explicitly unproven, and writing an
-- optimistic default would defeat the point of a gate.
--
-- Idempotent: safe to re-run.

-- ── The frozen contract ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.smart_money_study_config (
    study_id            TEXT        PRIMARY KEY,
    protocol_version    TEXT        NOT NULL,
    prereg_sha256       TEXT        NOT NULL,   -- hash of the canonical config JSON below
    primary_horizon     INTEGER     NOT NULL,   -- trading sessions
    secondary_horizons  INTEGER[]   NOT NULL,
    primary_benchmark   TEXT        NOT NULL,
    secondary_benchmark TEXT        NOT NULL,
    hurdle_pp           NUMERIC(6,3) NOT NULL,  -- incremental NET return hurdle, percentage points
    cost_model_version  TEXT        NOT NULL,
    config              JSONB       NOT NULL,   -- universe rule, cost schedule, test plan
    frozen_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    frozen_by           TEXT        NOT NULL
);

COMMENT ON TABLE nidp.smart_money_study_config IS
  'Preregistered, immutable study contract. A changed rule requires a NEW study_id and a fresh '
  'holdout, never an UPDATE — enforced by trigger, because the protocol is worthless if the '
  'thresholds can move after results are inspected.';

-- Immutability. The protocol says a post-hoc change must become a new versioned study; this makes
-- that the only mechanical option.
CREATE OR REPLACE FUNCTION nidp.smart_money_study_config_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
      'nidp.smart_money_study_config is append-only (study %). Register a new study_id with a new '
      'protocol_version instead of altering a frozen contract.', OLD.study_id;
END $$;

DROP TRIGGER IF EXISTS trg_smart_money_study_config_immutable ON nidp.smart_money_study_config;
CREATE TRIGGER trg_smart_money_study_config_immutable
    BEFORE UPDATE OR DELETE ON nidp.smart_money_study_config
    FOR EACH ROW EXECUTE FUNCTION nidp.smart_money_study_config_immutable();

-- ── Study runs ─────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.smart_money_study_runs (
    run_id          UUID        PRIMARY KEY,
    study_id        TEXT        NOT NULL REFERENCES nidp.smart_money_study_config(study_id),
    code_commit     TEXT        NOT NULL,       -- git SHA the run executed from
    config_sha256   TEXT        NOT NULL,       -- must equal the study's prereg hash
    data_cutoff     DATE        NOT NULL,
    -- 'exploratory' = Stage A diagnostics on overlapping cohorts, explicitly underpowered.
    -- 'confirmatory' = the frozen out-of-sample evaluation. Only the latter can support promotion.
    stage           TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    status          TEXT        NOT NULL DEFAULT 'RUNNING',
    notes           TEXT,
    CONSTRAINT sm_run_stage_chk  CHECK (stage IN ('exploratory', 'confirmatory')),
    CONSTRAINT sm_run_status_chk CHECK (status IN ('RUNNING', 'OK', 'FAILED', 'ABANDONED'))
);

-- ── Paired predictions: baseline vs tilt, per scoring date ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.smart_money_shadow_predictions (
    study_id        TEXT        NOT NULL,
    run_id          UUID        NOT NULL REFERENCES nidp.smart_money_study_runs(run_id),
    scoring_date    DATE        NOT NULL,
    symbol          TEXT        NOT NULL,
    baseline_score  NUMERIC(8,3),
    baseline_rank   INTEGER,
    smart_money_score NUMERIC(8,3),
    tilt            NUMERIC(8,3),               -- the bounded adjustment actually applied
    tilted_score    NUMERIC(8,3),
    tilted_rank     INTEGER,
    data_confidence TEXT,
    evidence_class  TEXT,
    single_amc_signal BOOLEAN,
    eligible        BOOLEAN     NOT NULL,       -- passed the point-in-time universe rule
    ineligible_reason TEXT,                     -- recorded, never silently dropped (§2.5.7)
    PRIMARY KEY (run_id, scoring_date, symbol)
);

COMMENT ON COLUMN nidp.smart_money_shadow_predictions.ineligible_reason IS
  'Why a symbol was excluded from the cohort. The protocol requires every exclusion to be '
  'accounted for, so excluded rows are STORED with a reason rather than filtered out.';

-- ── Outcomes, which must not be readable before they mature ────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.smart_money_study_outcomes (
    study_id        TEXT        NOT NULL,
    run_id          UUID        NOT NULL REFERENCES nidp.smart_money_study_runs(run_id),
    scoring_date    DATE        NOT NULL,
    symbol          TEXT        NOT NULL,
    horizon_sessions INTEGER    NOT NULL,
    entry_date      DATE,                       -- next session after the signal (§2.3 convention)
    entry_price     NUMERIC(18,4),
    exit_date       DATE,
    exit_price      NUMERIC(18,4),
    gross_return_pct NUMERIC(12,6),
    cost_pct        NUMERIC(12,6),              -- round-trip, from the frozen cost schedule
    net_return_pct  NUMERIC(12,6),
    benchmark_return_pct NUMERIC(12,6),         -- Nifty 500 over the same window
    sector_return_pct    NUMERIC(12,6),
    -- 'pending' until the horizon completes. The protocol forbids using an immature outcome.
    maturity        TEXT        NOT NULL DEFAULT 'pending',
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, scoring_date, symbol, horizon_sessions),
    CONSTRAINT sm_outcome_maturity_chk CHECK (maturity IN ('pending', 'mature')),
    -- A matured row must actually have both ends of the window.
    CONSTRAINT sm_outcome_mature_complete_chk CHECK (
        maturity <> 'mature' OR (exit_price IS NOT NULL AND entry_price IS NOT NULL))
);

-- ── Gate decisions ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.smart_money_promotion_decisions (
    id              BIGSERIAL   PRIMARY KEY,
    study_id        TEXT        NOT NULL,
    gate            TEXT        NOT NULL,       -- A | B | C | D
    decision        TEXT        NOT NULL,       -- pass | fail | pending
    evidence_ref    TEXT,                       -- report path, run_id, query
    rationale       TEXT,
    approver        TEXT        NOT NULL,
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    rollback_conditions TEXT,
    CONSTRAINT sm_gate_chk     CHECK (gate IN ('A', 'B', 'C', 'D')),
    CONSTRAINT sm_decision_chk CHECK (decision IN ('pass', 'fail', 'pending'))
);

CREATE INDEX IF NOT EXISTS idx_sm_outcomes_mature
    ON nidp.smart_money_study_outcomes (study_id, horizon_sessions, maturity);
CREATE INDEX IF NOT EXISTS idx_sm_pred_date
    ON nidp.smart_money_shadow_predictions (study_id, scoring_date);
