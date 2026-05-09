-- 040_nidp_consistency_quality.sql — Cross-source consistency checks + data quality scores.
--
-- Extends the existing per-ingester validation framework (006_nidp_validation.sql)
-- with cross-ingester, temporal, and API-layer consistency checks.
--
-- Tables:
--   consistency_runs      — one row per (target_date, domain) cross-source check run
--   consistency_findings  — per-field findings from those checks
--   quality_scores        — time-series weighted quality score per (date, domain)
--
-- Views:
--   v_data_certification  — current certification tier per (date, domain)
--   v_publish_gate        — actionable publish/hold/reject decision per date

SET search_path TO nidp, public;


-- ── consistency_runs ────────────────────────────────────────────────
-- One row per execution of run_consistency_checks(target_date, domain).
-- Domain values: 'mf' | 'equity' | 'all'
CREATE TABLE IF NOT EXISTS nidp.consistency_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date     DATE NOT NULL,
    domain          TEXT NOT NULL,
    status          TEXT NOT NULL,          -- PASSED | FAILED | PARTIAL | ERROR
    rules_run       INTEGER NOT NULL DEFAULT 0,
    rules_failed    INTEGER NOT NULL DEFAULT 0,
    findings_count  INTEGER NOT NULL DEFAULT 0,
    has_block       BOOLEAN NOT NULL DEFAULT FALSE,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    notes           TEXT,
    CHECK (status IN ('PASSED','FAILED','PARTIAL','ERROR')),
    CHECK (domain  IN ('mf','equity','all'))
);

CREATE INDEX IF NOT EXISTS idx_cruns_date_domain
    ON nidp.consistency_runs(target_date DESC, domain);
CREATE INDEX IF NOT EXISTS idx_cruns_status
    ON nidp.consistency_runs(status) WHERE status IN ('FAILED','PARTIAL','ERROR');


-- ── consistency_findings ────────────────────────────────────────────
-- One row per failed consistency assertion. Richer than validation_findings:
-- captures which two sources disagree (source_a/b, value_a/b) and the
-- computed deviation so dashboards can sort by severity of drift.
CREATE TABLE IF NOT EXISTS nidp.consistency_findings (
    finding_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id          UUID NOT NULL REFERENCES nidp.consistency_runs(run_id),
    target_date     DATE NOT NULL,
    domain          TEXT NOT NULL,
    -- Which of the 5 dimensions flagged this
    dimension       TEXT NOT NULL,          -- CROSS_SOURCE | INTERNAL | TEMPORAL | API | POINT_IN_TIME
    rule_name       TEXT NOT NULL,
    severity        TEXT NOT NULL,          -- INFO | WARN | ERROR | CRITICAL
    failure_class   TEXT NOT NULL,          -- RETRY | FIX | BLOCK | INFO
    -- What entity and field
    entity_type     TEXT,                   -- 'scheme' | 'symbol' | 'portfolio' | 'index'
    entity_id       TEXT,                   -- scheme_code, NSE symbol, etc.
    field_name      TEXT,                   -- 'nav' | 'ter_pct' | 'promoter_pct' | etc.
    -- Source comparison (populated for CROSS_SOURCE / API dimensions)
    source_a        TEXT,                   -- e.g. 'amfi_nav'
    value_a         TEXT,
    source_b        TEXT,                   -- e.g. 'scheme_master'
    value_b         TEXT,
    deviation_pct   NUMERIC(10,4),          -- abs((a-b)/b)*100; NULL for non-numeric
    -- Human-readable summary
    message         TEXT NOT NULL,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (dimension     IN ('CROSS_SOURCE','INTERNAL','TEMPORAL','API','POINT_IN_TIME')),
    CHECK (severity      IN ('INFO','WARN','ERROR','CRITICAL')),
    CHECK (failure_class IN ('RETRY','FIX','BLOCK','INFO'))
);

CREATE INDEX IF NOT EXISTS idx_cfindings_date_domain
    ON nidp.consistency_findings(target_date DESC, domain);
CREATE INDEX IF NOT EXISTS idx_cfindings_rule
    ON nidp.consistency_findings(rule_name, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_cfindings_block
    ON nidp.consistency_findings(target_date)
    WHERE failure_class = 'BLOCK';
CREATE INDEX IF NOT EXISTS idx_cfindings_entity
    ON nidp.consistency_findings(entity_type, entity_id, target_date DESC)
    WHERE entity_id IS NOT NULL;


-- ── quality_scores ──────────────────────────────────────────────────
-- Time-series of data quality scores per (target_date, domain).
-- overall_score is the weighted formula:
--   Q = 0.40·A + 0.30·C + 0.15·P + 0.10·F + 0.05·U
-- confidence_score:
--   K = 0.40·source_reliability + 0.30·validation_pass_rate + 0.20·freshness + 0.10·cross_source_agreement
CREATE TABLE IF NOT EXISTS nidp.quality_scores (
    score_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date           DATE NOT NULL,
    domain                TEXT NOT NULL,
    -- Five dimensions (0–100 each)
    accuracy              NUMERIC(6,3) NOT NULL,
    consistency           NUMERIC(6,3) NOT NULL,
    completeness          NUMERIC(6,3) NOT NULL,
    freshness             NUMERIC(6,3) NOT NULL,
    auditability          NUMERIC(6,3) NOT NULL,
    -- Weighted overall (stored, not generated, for compatibility with older PG)
    overall_score         NUMERIC(6,3) NOT NULL,
    -- Confidence sub-components
    source_reliability    NUMERIC(6,3),
    validation_pass_rate  NUMERIC(6,3),
    cross_source_agreement NUMERIC(6,3),
    confidence_score      NUMERIC(6,3),
    -- Derived certification tier
    certification         TEXT NOT NULL,      -- PLATINUM | GOLD | SILVER | REVIEW
    -- Actionable publish gate
    publish_decision      TEXT NOT NULL,      -- AUTO_PUBLISH | HOLD | MANUAL_REVIEW | REJECT
    -- Provenance
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes                 TEXT,
    CHECK (domain           IN ('mf','equity','all')),
    CHECK (certification    IN ('PLATINUM','GOLD','SILVER','REVIEW')),
    CHECK (publish_decision IN ('AUTO_PUBLISH','HOLD','MANUAL_REVIEW','REJECT'))
);

CREATE INDEX IF NOT EXISTS idx_qscores_date_domain
    ON nidp.quality_scores(target_date DESC, domain);
CREATE INDEX IF NOT EXISTS idx_qscores_certification
    ON nidp.quality_scores(certification, target_date DESC);


-- ── v_data_certification ────────────────────────────────────────────
-- Most-recent quality score per (target_date, domain); used by snapshot
-- engine gate and the /quality API.
CREATE OR REPLACE VIEW nidp.v_data_certification AS
SELECT DISTINCT ON (target_date, domain)
    target_date,
    domain,
    score_id,
    overall_score,
    accuracy,
    consistency,
    completeness,
    freshness,
    auditability,
    confidence_score,
    certification,
    publish_decision,
    computed_at
FROM nidp.quality_scores
ORDER BY target_date DESC, domain, computed_at DESC;


-- ── v_publish_gate ──────────────────────────────────────────────────
-- Convenience view joining latest quality scores with any BLOCK findings
-- so the snapshot engine has a single query for go/no-go decisions.
CREATE OR REPLACE VIEW nidp.v_publish_gate AS
SELECT
    c.target_date,
    c.domain,
    c.overall_score,
    c.certification,
    c.publish_decision,
    c.confidence_score,
    COALESCE(b.block_count, 0) AS consistency_blocks,
    CASE
        WHEN COALESCE(b.block_count, 0) > 0 THEN 'REJECT'
        ELSE c.publish_decision
    END AS gate_decision
FROM nidp.v_data_certification c
LEFT JOIN (
    SELECT target_date, domain, count(*) AS block_count
      FROM nidp.consistency_findings
     WHERE failure_class = 'BLOCK'
     GROUP BY target_date, domain
) b ON b.target_date = c.target_date AND b.domain = c.domain;


-- ── certified_dates ─────────────────────────────────────────────────
-- Written by CertificationPublisher.publish() after a PASS gate decision.
-- The DaaS API checks this table before serving data; uncertified dates
-- are excluded from API responses.
CREATE TABLE IF NOT EXISTS nidp.certified_dates (
    cert_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date   DATE NOT NULL,
    domain        TEXT NOT NULL,
    overall_score NUMERIC(6,3),
    certification TEXT,
    certified_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (target_date, domain),
    CHECK (domain IN ('mf','equity','all')),
    CHECK (certification IN ('PLATINUM','GOLD','SILVER','REVIEW'))
);

CREATE INDEX IF NOT EXISTS idx_certified_dates_date
    ON nidp.certified_dates(target_date DESC);


-- ── exception_queue ─────────────────────────────────────────────────
-- Populated by QualityGate when outcome = REVIEW.  Ops team resolves
-- entries manually and sets resolved = TRUE to unblock publishing.
CREATE TABLE IF NOT EXISTS nidp.exception_queue (
    queue_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date      DATE NOT NULL,
    domain           TEXT NOT NULL,
    outcome          TEXT NOT NULL DEFAULT 'REVIEW',
    quality_score    NUMERIC(6,3),
    confidence_score NUMERIC(6,3),
    block_findings   INTEGER NOT NULL DEFAULT 0,
    reason           TEXT NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved         BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_at      TIMESTAMPTZ,
    resolved_by      TEXT,
    resolution_note  TEXT,
    UNIQUE (target_date, domain)
);

CREATE INDEX IF NOT EXISTS idx_excqueue_unresolved
    ON nidp.exception_queue(target_date DESC)
    WHERE resolved = FALSE;


-- ── quarantine_log ──────────────────────────────────────────────────
-- Populated by QualityGate when outcome = FAIL.  Records every condemned
-- run for audit; does not block future runs for the same date.
CREATE TABLE IF NOT EXISTS nidp.quarantine_log (
    quarantine_id    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date      DATE NOT NULL,
    domain           TEXT NOT NULL,
    quality_score    NUMERIC(6,3),
    confidence_score NUMERIC(6,3),
    block_findings   INTEGER NOT NULL DEFAULT 0,
    reason           TEXT NOT NULL,
    quarantined_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (target_date, domain)
);

CREATE INDEX IF NOT EXISTS idx_quarantine_date
    ON nidp.quarantine_log(quarantined_at DESC);


INSERT INTO nidp.schema_migrations(filename) VALUES ('040_nidp_consistency_quality.sql')
    ON CONFLICT (filename) DO NOTHING;
