-- Migration 077: DQ Gates infrastructure
-- Creates the `dq` schema with all tables required by the Quality Gates PRD.
-- All existing nidp.validation_findings / consistency_findings / quality_scores
-- remain unchanged — this adds a thin verdict + SLO layer on top.

-- ── Schema ────────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS dq;

-- ── dq.feed_sla ───────────────────────────────────────────────────────────────
-- Per-feed SLO definitions.  Seed rows are inserted at the bottom.
CREATE TABLE IF NOT EXISTS dq.feed_sla (
    feed                    TEXT        NOT NULL,
    gate_id                 SMALLINT    NOT NULL,   -- 1–7
    -- Freshness: max seconds since last successful run before P1/P0 trigger
    freshness_warn_secs     INTEGER,                -- NULL = not checked
    freshness_error_secs    INTEGER,
    -- Completeness: expected row count band (NULL = not checked)
    row_count_min           INTEGER,
    row_count_max           INTEGER,
    row_count_trailing_days SMALLINT    DEFAULT 30, -- band computed from last N days
    -- Validity: max % of rows failing schema/sanity checks
    validity_warn_pct       NUMERIC(5,2) DEFAULT 5.00,
    validity_error_pct      NUMERIC(5,2) DEFAULT 25.00,
    -- Referential: max % of FK misses
    referential_warn_pct    NUMERIC(5,2) DEFAULT 0.10,
    referential_error_pct   NUMERIC(5,2) DEFAULT 1.00,
    -- Gate 3 specific: is this feed required for derivation engines to run?
    is_p0_for_derivation    BOOLEAN     NOT NULL DEFAULT FALSE,
    -- Meta
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (feed, gate_id)
);

-- ── dq.gate_verdicts ──────────────────────────────────────────────────────────
-- One row per gate invocation (one gate run can cover multiple feeds).
CREATE TABLE IF NOT EXISTS dq.gate_verdicts (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    gate_id         SMALLINT    NOT NULL,           -- 1–7
    feed            TEXT,                           -- NULL for multi-feed gates
    target_date     DATE        NOT NULL,
    job_run_id      UUID,                           -- FK to nidp.job_log (nullable for gate-only runs)
    verdict         TEXT        NOT NULL CHECK (verdict IN ('PASS','AMBER','FAIL')),
    severity        TEXT        NOT NULL CHECK (severity IN ('P0','P1','P2','OK')),
    details         JSONB       NOT NULL DEFAULT '{}',
    -- Prometheus labels cached here for replay/reporting
    labels          JSONB       NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dq_gate_verdicts_date_gate
    ON dq.gate_verdicts (target_date DESC, gate_id);
CREATE INDEX IF NOT EXISTS idx_dq_gate_verdicts_feed_date
    ON dq.gate_verdicts (feed, target_date DESC)
    WHERE feed IS NOT NULL;

-- ── dq.feed_signatures ────────────────────────────────────────────────────────
-- Daily statistical fingerprint per feed — used for drift detection in Gate 7.
CREATE TABLE IF NOT EXISTS dq.feed_signatures (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    feed            TEXT        NOT NULL,
    target_date     DATE        NOT NULL,
    row_count       BIGINT,
    null_rate_pct   NUMERIC(6,3),           -- avg across all columns
    min_value       NUMERIC,                -- domain-specific numeric min
    max_value       NUMERIC,                -- domain-specific numeric max
    cardinality     BIGINT,                 -- count(distinct primary_key)
    checksum        TEXT,                   -- xxhash of (symbol, date, close) sample
    extra           JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (feed, target_date)
);
CREATE INDEX IF NOT EXISTS idx_dq_feed_signatures_feed_date
    ON dq.feed_signatures (feed, target_date DESC);

-- ── dq.snapshot_status ────────────────────────────────────────────────────────
-- Per-date Gate 3 outcome: which feeds are ready, which are blocking.
CREATE TABLE IF NOT EXISTS dq.snapshot_status (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    target_date     DATE        NOT NULL UNIQUE,
    status          TEXT        NOT NULL CHECK (status IN ('PENDING','PASS','BLOCKED','PARTIAL')),
    -- feeds_ready / feeds_blocked are arrays of feed names
    feeds_ready     TEXT[]      NOT NULL DEFAULT '{}',
    feeds_blocked   TEXT[]      NOT NULL DEFAULT '{}',
    feeds_amber     TEXT[]      NOT NULL DEFAULT '{}',
    -- blocking reason for the first P0 failure (for dashboard display)
    block_reason    TEXT,
    gate_verdict_id UUID        REFERENCES dq.gate_verdicts(id),
    evaluated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── dq.dlq_findings ───────────────────────────────────────────────────────────
-- Messages quarantined at Gate 1 or 2, with replay capability.
CREATE TABLE IF NOT EXISTS dq.dlq_findings (
    id              UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    gate_id         SMALLINT    NOT NULL CHECK (gate_id IN (1, 2)),
    feed            TEXT        NOT NULL,
    target_date     DATE,
    job_run_id      UUID,
    -- Kafka / ingester context
    topic           TEXT,
    partition_key   TEXT,
    message_offset  BIGINT,
    -- Failure detail
    failure_reason  TEXT        NOT NULL,
    severity        TEXT        NOT NULL CHECK (severity IN ('P0','P1','P2')),
    raw_payload     JSONB,                  -- sanitised copy of the failed message
    -- Replay
    replay_status   TEXT        NOT NULL DEFAULT 'PENDING'
                        CHECK (replay_status IN ('PENDING','REPLAYED','DROPPED','INVESTIGATING')),
    replayed_at     TIMESTAMPTZ,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_dq_dlq_feed_date
    ON dq.dlq_findings (feed, target_date DESC);
CREATE INDEX IF NOT EXISTS idx_dq_dlq_replay_status
    ON dq.dlq_findings (replay_status)
    WHERE replay_status = 'PENDING';

-- ── Seed: feed_sla for P0 feeds (Gate 3) ────────────────────────────────────
-- These are the feeds whose absence blocks the derivation chain.
-- Row counts are conservative lower bounds — tune after 30 days of data.
INSERT INTO dq.feed_sla (feed, gate_id, freshness_warn_secs, freshness_error_secs,
    row_count_min, is_p0_for_derivation, notes)
VALUES
    ('bhavcopy',                      3, 7200,  14400, 1500, TRUE,  'NSE EOD bhavcopy — min 1500 tradeable instruments'),
    ('index_close',                   3, 7200,  14400,   50, TRUE,  'NSE index closes — min 50 indices'),
    ('fii_dii',                       3, 86400, 172800,   1, TRUE,  'FII/DII daily provisional — 1 row per day'),
    ('delivery',                      3, 90000, 180000, 200, TRUE,  'T+1 delivery data'),
    ('mf_nav_daily',                  3, 86400, 172800, 4500, TRUE, 'AMFI NAV — min 4500 active schemes'),
    ('mf_scheme_master',              3, NULL,  NULL,   4500, FALSE, 'Reference — warn only if missing'),
    ('prices_eod',                    3, 7200,  14400, 1500, TRUE,  'Adjusted prices — mirrors bhavcopy'),
    ('nse_financials_quarterly',      3, 604800,1209600, 500, FALSE, 'Quarterly — warn if > 14 days stale'),
    ('corporate_actions',             3, 86400, 172800,   0, FALSE, 'May be 0 on quiet days — just check freshness'),
    ('stock_features_daily',          3, 7200,  14400, 1500, TRUE,  'Feature engine output — depends on bhavcopy'),
    ('block_deals',                   3, NULL,  NULL,    0, FALSE, 'Optional — 0 rows valid'),
    ('bulk_deals',                    3, NULL,  NULL,    0, FALSE, 'Optional — 0 rows valid')
ON CONFLICT (feed, gate_id) DO NOTHING;

COMMENT ON TABLE dq.gate_verdicts    IS 'One row per gate invocation — the authoritative quality audit trail.';
COMMENT ON TABLE dq.feed_sla         IS 'Per-feed SLO definitions: freshness windows, row-count bands, P0 flags.';
COMMENT ON TABLE dq.feed_signatures  IS 'Daily statistical fingerprint per feed for drift detection.';
COMMENT ON TABLE dq.snapshot_status  IS 'Gate 3 outcome per date: which feeds are ready/blocked.';
COMMENT ON TABLE dq.dlq_findings     IS 'Messages quarantined at gate 1 or 2 with replay support.';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('077_dq_gates_schema.sql')
ON CONFLICT (filename) DO NOTHING;
