-- 021_v5_performance_dashboard.sql
-- Adds three schema elements required by the v5 Portfolio & Performance Dashboard:
--
--   1. mutual_fund_metadata.asset_class  — broad asset class label (Equity/Debt/Hybrid/etc.)
--      Derived from fund category; populated by the scrape/enrich pipeline.
--
--   2. mutual_fund_metadata.amfi_matched — TRUE when this fund has been matched to an AMFI
--      NAV record. Drives the "AMFI-unmatched" marker in the Holdings table (AC-16, AC-19).
--
--   3. portfolio_performance_cache       — server-side cache keyed by (user_id, period).
--      Pre-computed XIRR, attribution waterfall, monthly returns, and top contributors so
--      the Performance page renders in <2.5 s on 100+ holding portfolios (REQ 14).
--
-- Forward-only. All statements are IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

-- ─────────────────────────────────────────────
-- 1. mutual_fund_metadata — asset_class column
-- ─────────────────────────────────────────────
ALTER TABLE mutual_fund_metadata
    ADD COLUMN IF NOT EXISTS asset_class TEXT;

-- Index for Composition Explorer dimension queries and Holdings table filters.
CREATE INDEX IF NOT EXISTS idx_mfm_asset_class
    ON mutual_fund_metadata (asset_class)
    WHERE asset_class IS NOT NULL;

COMMENT ON COLUMN mutual_fund_metadata.asset_class IS
    'Broad asset class: Equity, Debt, Hybrid, Gold, International, Liquid. '
    'Derived from category by the scrape/enrich pipeline; NULL until first enrichment.';

-- ─────────────────────────────────────────────
-- 2. mutual_fund_metadata — amfi_matched column
-- ─────────────────────────────────────────────
ALTER TABLE mutual_fund_metadata
    ADD COLUMN IF NOT EXISTS amfi_matched BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN mutual_fund_metadata.amfi_matched IS
    'TRUE when this fund has an active match in mutual_fund_nav_history (AMFI sourced). '
    'FALSE means benchmark/attribution fields are unavailable for this fund (AC-19).';

-- Back-fill: mark any fund that already has NAV rows as matched.
-- Safe to run multiple times (only updates rows where the default FALSE was set but
-- NAV history already exists — i.e. pre-migration enriched funds).
UPDATE mutual_fund_metadata mfm
   SET amfi_matched = TRUE
 WHERE amfi_matched = FALSE
   AND EXISTS (
       SELECT 1 FROM mutual_fund_nav_history nav
        WHERE nav.instrument_id = mfm.instrument_id
        LIMIT 1
   );

-- ─────────────────────────────────────────────
-- 3. portfolio_performance_cache
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio_performance_cache (
    user_id         TEXT        NOT NULL,
    period          TEXT        NOT NULL,   -- '1M','3M','6M','1Y','3Y','inception'

    -- KPI strip
    portfolio_xirr  NUMERIC(8,4),           -- annualised, e.g. 14.72 = 14.72%
    benchmark_xirr  NUMERIC(8,4),           -- same period, category peer average
    alpha           NUMERIC(8,4),           -- portfolio_xirr − benchmark_xirr
    sharpe          NUMERIC(8,4),           -- annualised Sharpe ratio
    hit_rate        NUMERIC(6,4),           -- fraction of months beating benchmark (0–1)

    -- Attribution waterfall steps (ordered array of {label, value, type})
    waterfall       JSONB,

    -- Monthly returns strip [{month, portfolio, benchmark}]
    monthly_returns JSONB,

    -- Top contributors [{name, return_pct, alpha_contribution}]
    top_contributors JSONB,

    -- Verdict
    verdict_headline TEXT,
    status_pill     TEXT,                   -- 'HEALTHY','FAIR','POOR'

    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (user_id, period)
);

COMMENT ON TABLE portfolio_performance_cache IS
    'Server-computed performance analytics keyed by (user_id, period). '
    'Populated by portfolio_performance_engine; invalidated on resync or new CAS upload. '
    'Required for <2.5 s render target on 100+ holding portfolios (REQ 14).';

CREATE INDEX IF NOT EXISTS idx_ppc_computed_at
    ON portfolio_performance_cache (computed_at DESC);

COMMENT ON COLUMN portfolio_performance_cache.period IS
    'One of: 1M, 3M, 6M, 1Y, 3Y, inception';
COMMENT ON COLUMN portfolio_performance_cache.waterfall IS
    'Array of {label: str, value: float (pp), type: "start"|"end"|"pos"|"neg"}';
COMMENT ON COLUMN portfolio_performance_cache.monthly_returns IS
    'Array of {month: str, portfolio: float, benchmark: float}';
COMMENT ON COLUMN portfolio_performance_cache.top_contributors IS
    'Array of {name: str, return_pct: float, alpha_contribution: float}';
