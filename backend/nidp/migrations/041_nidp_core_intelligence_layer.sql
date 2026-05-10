-- 041_nidp_core_intelligence_layer.sql
-- Core intelligence layer foundation for NIDP.
--
-- Creates canonical schemas + highest-value tables to transform the
-- platform from raw data repository into financial intelligence engine.

SET search_path TO public;

-- ── Schemas ───────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS dq;
CREATE SCHEMA IF NOT EXISTS features;
CREATE SCHEMA IF NOT EXISTS graph;
CREATE SCHEMA IF NOT EXISTS events;
CREATE SCHEMA IF NOT EXISTS analytics;


-- ── 1) Security Master (single source of truth) ─────────────────────
CREATE TABLE IF NOT EXISTS ref.security_master (
    security_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type        TEXT NOT NULL,  -- EQUITY | MF_SCHEME | INDEX | MACRO_SERIES | OTHER
    asset_class        TEXT NOT NULL,  -- EQUITY | MUTUAL_FUND | INDEX | DEBT | COMMODITY | CURRENCY | MACRO

    symbol             TEXT,
    isin               TEXT,
    nse_symbol         TEXT,
    bse_code           TEXT,
    amfi_scheme_code   TEXT,

    security_name      TEXT NOT NULL,
    sector             TEXT,
    industry           TEXT,

    is_active          BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from         DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to           DATE,

    source_system      TEXT NOT NULL DEFAULT 'nidp',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (entity_type IN ('EQUITY','MF_SCHEME','INDEX','MACRO_SERIES','OTHER')),
    CHECK (asset_class IN ('EQUITY','MUTUAL_FUND','INDEX','DEBT','COMMODITY','CURRENCY','MACRO'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_security_master_symbol
    ON ref.security_master (entity_type, symbol)
    WHERE symbol IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_security_master_isin
    ON ref.security_master (isin)
    WHERE isin IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_security_master_nse
    ON ref.security_master (nse_symbol)
    WHERE nse_symbol IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_security_master_bse
    ON ref.security_master (bse_code)
    WHERE bse_code IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_security_master_amfi
    ON ref.security_master (amfi_scheme_code)
    WHERE amfi_scheme_code IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_security_master_sector_industry
    ON ref.security_master (sector, industry);


-- ── 2) Data Quality Intelligence ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS dq.validation_runs (
    run_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_ts               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    pipeline_name        TEXT NOT NULL,
    dataset_name         TEXT NOT NULL,
    target_date          DATE,
    status               TEXT NOT NULL, -- PASS | FAIL | PARTIAL | ERROR
    checks_total         INTEGER NOT NULL DEFAULT 0,
    checks_passed        INTEGER NOT NULL DEFAULT 0,
    checks_failed        INTEGER NOT NULL DEFAULT 0,
    schema_hash          TEXT,
    execution_ms         INTEGER,
    notes                TEXT,
    CHECK (status IN ('PASS','FAIL','PARTIAL','ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_dq_validation_runs_dataset
    ON dq.validation_runs (dataset_name, target_date DESC, run_ts DESC);

CREATE TABLE IF NOT EXISTS dq.failed_rows (
    failed_row_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id                UUID REFERENCES dq.validation_runs(run_id) ON DELETE CASCADE,
    dataset_name          TEXT NOT NULL,
    source_record_ref     TEXT,
    rule_name             TEXT NOT NULL,
    severity              TEXT NOT NULL DEFAULT 'ERROR', -- INFO | WARN | ERROR | CRITICAL
    column_name           TEXT,
    observed_value        TEXT,
    expected_constraint   TEXT,
    error_message         TEXT,
    failed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (severity IN ('INFO','WARN','ERROR','CRITICAL'))
);

CREATE INDEX IF NOT EXISTS idx_dq_failed_rows_run
    ON dq.failed_rows (run_id, failed_at DESC);

CREATE TABLE IF NOT EXISTS dq.quality_scores (
    score_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    target_date           DATE NOT NULL,
    dataset_name          TEXT NOT NULL,
    freshness_score       NUMERIC(6,3) NOT NULL,
    accuracy_score        NUMERIC(6,3) NOT NULL,
    consistency_score     NUMERIC(6,3) NOT NULL,
    completeness_score    NUMERIC(6,3) NOT NULL,
    overall_score         NUMERIC(6,3) NOT NULL,
    quality_tier          TEXT NOT NULL, -- PLATINUM | GOLD | SILVER | REVIEW
    computed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (target_date, dataset_name, computed_at),
    CHECK (quality_tier IN ('PLATINUM','GOLD','SILVER','REVIEW'))
);

CREATE INDEX IF NOT EXISTS idx_dq_quality_scores_latest
    ON dq.quality_scores (dataset_name, target_date DESC, computed_at DESC);


-- ── 3) Feature Store ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS features.stock_features_daily (
    feature_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id             UUID NOT NULL REFERENCES ref.security_master(security_id),
    as_of_date              DATE NOT NULL,

    close_price             NUMERIC(18,6),
    ret_1d                  NUMERIC(10,6),
    ret_5d                  NUMERIC(10,6),
    ret_20d                 NUMERIC(10,6),
    volatility_20d          NUMERIC(10,6),
    gap_pct                 NUMERIC(10,6),
    atr_14                  NUMERIC(10,6),

    rsi_14                  NUMERIC(10,6),
    macd                    NUMERIC(10,6),
    macd_signal             NUMERIC(10,6),
    sma_20                  NUMERIC(18,6),
    sma_50                  NUMERIC(18,6),
    ema_20                  NUMERIC(18,6),

    beta_90d                NUMERIC(10,6),
    sharpe_90d              NUMERIC(10,6),
    rel_strength_90d        NUMERIC(10,6),

    source_run_id           UUID,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (security_id, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_features_date
    ON features.stock_features_daily (as_of_date DESC);


-- ── 4) Correlation Engine ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph.correlations (
    correlation_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    as_of_date              DATE NOT NULL,
    window_days             INTEGER NOT NULL DEFAULT 90,
    left_security_id        UUID NOT NULL REFERENCES ref.security_master(security_id),
    right_security_id       UUID NOT NULL REFERENCES ref.security_master(security_id),
    relationship_type       TEXT NOT NULL, -- STOCK_STOCK | STOCK_INDEX | STOCK_MACRO | FUND_STOCK
    correlation_value       NUMERIC(10,6) NOT NULL,
    abs_correlation         NUMERIC(10,6) GENERATED ALWAYS AS (abs(correlation_value)) STORED,
    method                  TEXT NOT NULL DEFAULT 'pearson',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (left_security_id <> right_security_id),
    CHECK (relationship_type IN ('STOCK_STOCK','STOCK_INDEX','STOCK_MACRO','FUND_STOCK'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_graph_correlations_key
    ON graph.correlations(as_of_date, window_days, left_security_id, right_security_id, relationship_type, method);

CREATE INDEX IF NOT EXISTS idx_graph_correlations_threshold
    ON graph.correlations (as_of_date DESC, abs_correlation DESC);


-- ── 5) Ownership Graph ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS graph.entity_links (
    link_id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    as_of_date                DATE,
    left_security_id          UUID REFERENCES ref.security_master(security_id),
    right_security_id         UUID REFERENCES ref.security_master(security_id),
    relationship_type         TEXT NOT NULL, -- FUND_HOLDS_STOCK | STOCK_IN_INDEX | STOCK_IN_SECTOR | PROMOTER_OWNS_COMPANY
    weight_pct                NUMERIC(10,6),
    metadata_json             JSONB,
    source_system             TEXT NOT NULL DEFAULT 'nidp',
    valid_from                DATE NOT NULL DEFAULT CURRENT_DATE,
    valid_to                  DATE,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (relationship_type IN ('FUND_HOLDS_STOCK','STOCK_IN_INDEX','STOCK_IN_SECTOR','PROMOTER_OWNS_COMPANY')),
    CHECK ((left_security_id IS NOT NULL) OR (right_security_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_entity_links_left
    ON graph.entity_links (left_security_id, relationship_type, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_entity_links_right
    ON graph.entity_links (right_security_id, relationship_type, as_of_date DESC);


-- ── 6) Event Intelligence (normalized events) ────────────────────────
CREATE TABLE IF NOT EXISTS events.normalized_events (
    event_id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    security_id               UUID REFERENCES ref.security_master(security_id),
    event_date                DATE NOT NULL,
    event_ts                  TIMESTAMPTZ,
    event_type                TEXT NOT NULL, -- DIVIDEND | SPLIT | BONUS | EARNINGS | MGMT_CHANGE | ANNOUNCEMENT
    event_subtype             TEXT,
    title                     TEXT,
    summary                   TEXT,
    payload_json              JSONB,
    impact_score              NUMERIC(6,3),
    source_system             TEXT NOT NULL,
    source_ref                TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (event_type IN ('DIVIDEND','SPLIT','BONUS','EARNINGS','MGMT_CHANGE','ANNOUNCEMENT'))
);

CREATE INDEX IF NOT EXISTS idx_events_by_security_date
    ON events.normalized_events (security_id, event_date DESC);
CREATE INDEX IF NOT EXISTS idx_events_by_type_date
    ON events.normalized_events (event_type, event_date DESC);


-- ── 7) Daily market summary ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics.market_snapshot (
    snapshot_id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    as_of_date                DATE NOT NULL UNIQUE,
    breadth_advances          INTEGER,
    breadth_declines          INTEGER,
    fii_net_cr                NUMERIC(18,4),
    dii_net_cr                NUMERIC(18,4),
    vix_close                 NUMERIC(18,6),
    nifty50_close             NUMERIC(18,6),
    banknifty_close           NUMERIC(18,6),
    top_sector                TEXT,
    weakest_sector            TEXT,
    market_regime             TEXT, -- RISK_ON | NEUTRAL | RISK_OFF
    summary_json              JSONB,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (market_regime IN ('RISK_ON','NEUTRAL','RISK_OFF'))
);


-- ── 8) Search layer bootstrapping view (FTS-ready) ──────────────────
CREATE OR REPLACE VIEW events.v_search_documents AS
SELECT
    e.event_id::text AS doc_id,
    COALESCE(sm.security_name, sm.symbol, sm.nse_symbol, 'unknown') AS entity_name,
    e.event_type,
    e.event_date,
    setweight(to_tsvector('simple', coalesce(e.title, '')), 'A') ||
    setweight(to_tsvector('simple', coalesce(e.summary, '')), 'B') ||
    setweight(to_tsvector('simple', coalesce(e.event_subtype, '')), 'C') AS document_tsv
FROM events.normalized_events e
LEFT JOIN ref.security_master sm ON sm.security_id = e.security_id;


INSERT INTO nidp.schema_migrations(filename)
VALUES ('041_nidp_core_intelligence_layer.sql')
ON CONFLICT (filename) DO NOTHING;
