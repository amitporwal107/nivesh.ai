-- 055_nidp_v3_stock_primitives_view.sql
--
-- Creates nidp.v_v3_stock_primitives — the bridge view that maps NIDP
-- column names to the exact primitive keys read by services/stock_scoring.py.
--
-- This view is the stock equivalent of nidp.v_v3_mf_primitives (migration 050).
-- Wire the nightly batch to read from here instead of groww_fundamentals.
--
-- Field naming conventions from stock_scoring.py:
--   roe_pct, debt_to_equity          → direct passthrough
--   promoter_pct                     → aliased as promoter_holding_pct
--   market_cap_bucket (LARGE_CAP)    → aliased as cap_bucket ('large')
--   pe_vs_sector_pct                 → aliased as pe_overvaluation_pct
--   All other new columns            → direct passthrough (names already match)
--
-- NULL columns (hard gaps, stay NULL until external data source added):
--   earnings_surprise_pct            — requires analyst consensus feed

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_v3_stock_primitives AS
SELECT
    f.symbol,
    f.as_of_date,

    -- ── Exact field names stock_scoring.py reads via primitives.get() ────

    -- Quality score inputs
    f.roe_pct,
    f.debt_to_equity,
    f.eps_growth_3y_cagr_pct,
    f.earnings_consistency_score,
    f.promoter_pct                                         AS promoter_holding_pct,
    CASE f.market_cap_bucket
        WHEN 'LARGE_CAP' THEN 'large'
        WHEN 'MID_CAP'   THEN 'mid'
        WHEN 'SMALL_CAP' THEN 'small'
        WHEN 'MICRO_CAP' THEN 'small'   -- micro treated as small for stability score
        ELSE NULL
    END                                                    AS cap_bucket,

    -- Health score inputs
    f.revenue_growth_3y_cagr_pct,
    f.profit_margin_trend_pct,
    f.debt_trend_pct,
    f.volatility_1y_pct,
    f.dividend_yield_pct,
    NULL::NUMERIC                                          AS earnings_surprise_pct,

    -- Exit score inputs
    f.pe_vs_sector_pct                                     AS pe_overvaluation_pct,
    f.earnings_decline_flag,
    f.debt_spike_flag,
    f.liquidity_score,

    -- Add score inputs
    f.momentum_score,

    -- ── Passthrough columns (additional context for the scoring pipeline) ─

    -- Fundamental levels
    f.pe_ttm,
    f.pb,
    f.roce_pct,
    f.interest_coverage,
    f.profit_margin_pct,
    f.ev_ebitda,
    f.pat_growth_yoy_pct,
    f.revenue_growth_yoy_pct,
    f.eps_growth_yoy_pct,

    -- Shareholding
    f.promoter_pct,
    f.fii_pct,
    f.dii_pct,
    f.mf_pct,
    f.promoter_pledged_pct,
    f.fii_pct_change_qoq,
    f.dii_pct_change_qoq,
    f.promoter_pct_change_qoq,

    -- Market / valuation
    f.market_cap_cr,
    f.market_cap_bucket,
    f.enterprise_value_cr,
    f.shares_outstanding,

    -- Price-history
    f.return_252d_pct,
    f.beta_1y,
    f.max_drawdown_1y_pct,

    -- Technicals (for copilot / trader view)
    f.rsi14,
    f.macd,
    f.macd_signal,
    f.macd_hist,
    f.accumulation_score,
    f.pivot_breakout_flag,

    -- Classification
    f.sector,
    f.industry

  FROM nidp.stock_features_daily f;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('055_nidp_v3_stock_primitives_view.sql')
ON CONFLICT (filename) DO NOTHING;
