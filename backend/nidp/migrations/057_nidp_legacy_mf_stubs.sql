-- 057_nidp_legacy_mf_stubs.sql
--
-- Creates empty stub tables for mutual_fund_metadata and
-- mutual_fund_performance_ratios so migration 050's view
-- (nidp.v_v3_mf_primitives) can be applied without the Nivesh-side
-- legacy data being imported into NIDP.
--
-- These tables exist purely to satisfy 050/051's mf_legacy CTE
-- references. The CTE provides LEFT-JOIN fallback values; with the
-- table empty, the view's COALESCE just falls through to whichever
-- NIDP-native source has the data. The V3 engine already handles
-- NULL primitives via _norm_*() returning None (graceful degradation).
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.

SET search_path TO public;

CREATE TABLE IF NOT EXISTS public.mutual_fund_metadata (
    instrument_id              UUID PRIMARY KEY,
    -- Debt-side primitives
    ytm                        NUMERIC,
    modified_duration          NUMERIC,
    investment_style           TEXT,
    moneycontrol_imid          TEXT,
    morningstar_rating         INT,
    -- Identity / age
    manager_tenure_years       NUMERIC,
    category                   TEXT,
    sub_category               TEXT,
    aum_cr                     NUMERIC,
    -- Expense ratio variants
    expense_ratio_direct       NUMERIC,
    expense_ratio_regular      NUMERIC,
    expense_ratio              NUMERIC,
    -- Category averages
    category_avg_1y            NUMERIC,
    category_avg_3y            NUMERIC,
    category_avg_5y            NUMERIC,
    -- Risk / concentration
    max_drawdown_pct           NUMERIC,
    top10_concentration_pct    NUMERIC,
    expense_trend_delta        NUMERIC,
    -- Fields 051 will eventually replace with computed NIDP values
    turnover_ratio             NUMERIC,
    consistency_score          NUMERIC,
    downside_capture_pct       NUMERIC,
    aum_trend_score            NUMERIC,
    credit_quality_score       NUMERIC,
    duration_risk_score        NUMERIC
);

CREATE TABLE IF NOT EXISTS public.mutual_fund_performance_ratios (
    instrument_id              UUID NOT NULL,
    ratios_date                DATE NOT NULL,
    ret_1y                     NUMERIC,
    ret_3y                     NUMERIC,
    ret_5y                     NUMERIC,
    sharpe                     NUMERIC,
    sortino                    NUMERIC,
    PRIMARY KEY (instrument_id, ratios_date)
);

-- instrument_master stub — referenced as `FROM instrument_master im`
-- in 050. Minimal column set needed by the view: instrument_id (join
-- spine), symbol (join key to mf_scheme_master.scheme_code), and
-- instrument_type (WHERE filter on 'MUTUAL_FUND'). Real data is
-- expected to live on the Nivesh-app side; this is just a stub so
-- the view DDL compiles.
CREATE TABLE IF NOT EXISTS public.instrument_master (
    instrument_id              UUID PRIMARY KEY,
    symbol                     TEXT,
    instrument_type            TEXT,
    name                       TEXT,
    isin                       TEXT
);
CREATE INDEX IF NOT EXISTS ix_im_symbol_type
    ON public.instrument_master (instrument_type, symbol);

-- Audit row so it's clear this was a stub install, not real data.
DO $$
BEGIN
    INSERT INTO nidp.job_log (job_name, status, message, started_at, finished_at)
    SELECT
        'migration_057_legacy_mf_stubs',
        'success',
        'Created empty stub tables for mutual_fund_metadata + mutual_fund_performance_ratios so 050''s view applies cleanly.',
        NOW(), NOW()
    WHERE EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema='nidp' AND table_name='job_log'
    );
END $$;
