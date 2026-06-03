-- Migration 076: Bank-specific quality scoring tables
-- ─────────────────────────────────────────────────────────────────────────────
-- Rationale: Generic stock scorer is misleading for banks — it treats D/E as
-- a liability (banks are naturally leveraged) and promoter holding as a
-- quality signal (private banks have 0% promoter). NPA is the single most
-- critical metric for bank quality and is not in the generic scorer at all.
--
-- This migration creates two tables:
--   1. nidp.bank_metrics_daily   — computed intermediates (NPA, NIM proxy, etc.)
--   2. nidp.bank_quality_scores_daily — final pillar scores + composite
-- ─────────────────────────────────────────────────────────────────────────────

-- ── 1. Bank metrics (intermediates) ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.bank_metrics_daily (
    symbol                  TEXT        NOT NULL,
    as_of_date              DATE        NOT NULL,
    -- Asset Quality (from raw_data JSONB time series, where available)
    gnpa_pct                NUMERIC(8,4),   -- Gross NPA % (latest quarter)
    nnpa_pct                NUMERIC(8,4),   -- Net NPA % (latest quarter)
    pcr_implied_pct         NUMERIC(8,4),   -- (1 - NNPA/GNPA) × 100
    gnpa_trend              TEXT,           -- 'improving' | 'stable' | 'worsening'
    gnpa_4q_ago             NUMERIC(8,4),   -- GNPA 4 quarters ago (for trend)
    -- Profitability (computed from raw_data time series)
    nii_cr                  NUMERIC(18,4),  -- Net Interest Income (latest Q, cr)
    nii_retention_pct       NUMERIC(8,4),   -- NII / gross_interest_earned × 100
    pat_margin_pct          NUMERIC(8,4),   -- PAT / total_income × 100 (captures efficiency + credit quality)
    roe_pct                 NUMERIC(8,4),   -- Annualised ROE from latest quarter
    pat_yoy_growth_pct      NUMERIC(10,4),  -- PAT YoY (latest Q vs same Q last year)
    -- Liability Franchise
    fee_income_mix_pct      NUMERIC(8,4),   -- other_income / total_income × 100
    revenue_yoy_growth_pct  NUMERIC(10,4),  -- Interest earned YoY growth
    -- Earnings Quality
    earnings_consistency    NUMERIC(8,4),   -- 0–100; based on PAT variance (8Q)
    -- Data completeness
    has_npa_data            BOOLEAN         NOT NULL DEFAULT FALSE,
    coverage_pct            NUMERIC(5,2),
    computed_at             TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_bank_metrics_date
    ON nidp.bank_metrics_daily (as_of_date DESC);

-- ── 2. Bank quality scores (pillar + composite) ──────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.bank_quality_scores_daily (
    symbol                      TEXT        NOT NULL,
    as_of_date                  DATE        NOT NULL,
    -- Pillar scores (0–100)
    asset_quality_score         NUMERIC(6,2),   -- 30% weight (null if no NPA data)
    profitability_score         NUMERIC(6,2),   -- 25% weight
    liability_franchise_score   NUMERIC(6,2),   -- 20% weight
    earnings_quality_score      NUMERIC(6,2),   -- 15% weight
    growth_score                NUMERIC(6,2),   -- 10% weight
    -- Composite
    bank_quality_score          NUMERIC(6,2),
    -- Coverage
    has_npa_data                BOOLEAN         NOT NULL DEFAULT FALSE,
    coverage_pct                NUMERIC(5,2),   -- % of expected metrics present
    engine_version              TEXT            NOT NULL DEFAULT 'v1',
    computed_at                 TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_bank_quality_date
    ON nidp.bank_quality_scores_daily (as_of_date DESC);

COMMENT ON TABLE nidp.bank_metrics_daily IS
    'Intermediate bank-specific metrics extracted from nse_financials_quarterly.raw_data';
COMMENT ON TABLE nidp.bank_quality_scores_daily IS
    'Bank-specific 5-pillar quality scores; asset_quality_score is null where GNPA is unavailable';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('076_bank_quality_scores.sql')
ON CONFLICT (filename) DO NOTHING;
