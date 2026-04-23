-- 008_equity_scoring.sql — Stock Master + Primitives + V3 Scores for direct equities.
-- Mirrors the MF scoring schema so admin APIs can treat stocks as first-class.

CREATE TABLE IF NOT EXISTS stock_master (
    nse_symbol          TEXT PRIMARY KEY,
    isin                TEXT,
    company_name        TEXT NOT NULL,
    sector              TEXT,
    industry            TEXT,
    market_cap_cr       NUMERIC(14, 2),
    cap_bucket          TEXT,                    -- large | mid | small | unknown
    face_value          NUMERIC(10, 2),
    listing_date        DATE,
    is_nifty_100        BOOLEAN DEFAULT FALSE,
    groww_slug          TEXT,
    last_scraped_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_master_cap_bucket ON stock_master(cap_bucket);
CREATE INDEX IF NOT EXISTS idx_stock_master_sector     ON stock_master(sector);
CREATE INDEX IF NOT EXISTS idx_stock_master_nifty100   ON stock_master(is_nifty_100) WHERE is_nifty_100;

-- Per-stock primitives: all raw signals the scoring engine consumes. One
-- row per refresh-date so we can diff over time if needed.
CREATE TABLE IF NOT EXISTS stock_primitives (
    nse_symbol          TEXT NOT NULL,
    as_of_date          DATE NOT NULL,

    -- Fundamentals (Quality + Health inputs)
    pe_ratio            NUMERIC(10, 2),
    pb_ratio            NUMERIC(10, 2),
    roe_pct             NUMERIC(6, 2),
    roce_pct            NUMERIC(6, 2),
    debt_to_equity      NUMERIC(6, 2),
    promoter_holding_pct NUMERIC(5, 2),
    eps                 NUMERIC(10, 2),
    eps_growth_3y_cagr_pct NUMERIC(6, 2),       -- Quality: growth signal
    revenue_growth_3y_cagr_pct NUMERIC(6, 2),   -- Health: momentum signal
    profit_margin_pct   NUMERIC(6, 2),
    profit_margin_trend_pct NUMERIC(6, 2),      -- YoY delta (positive = improving)
    debt_trend_pct      NUMERIC(6, 2),          -- YoY delta (negative = healthier)
    earnings_consistency_score NUMERIC(5, 2),   -- 0-100 heuristic
    earnings_surprise_pct NUMERIC(6, 2),        -- latest qtr actual vs estimate
    dividend_yield_pct  NUMERIC(5, 2),

    -- Risk + valuation (Exit inputs)
    pe_historical_median NUMERIC(10, 2),
    pe_overvaluation_pct NUMERIC(6, 2),          -- current_pe / hist_median - 1
    earnings_decline_flag BOOLEAN DEFAULT FALSE,
    debt_spike_flag     BOOLEAN DEFAULT FALSE,
    liquidity_score     NUMERIC(5, 2),           -- 0-100 (high = better)

    -- Performance
    return_1y_pct       NUMERIC(7, 2),
    return_3y_cagr_pct  NUMERIC(7, 2),
    return_5y_cagr_pct  NUMERIC(7, 2),
    volatility_1y_pct   NUMERIC(6, 2),           -- annualised
    beta                NUMERIC(6, 3),
    max_drawdown_pct    NUMERIC(6, 2),

    -- Momentum (Add input)
    momentum_score      NUMERIC(5, 2),           -- 0-100 (proxy for technical trend)

    PRIMARY KEY (nse_symbol, as_of_date),
    FOREIGN KEY (nse_symbol) REFERENCES stock_master(nse_symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stock_primitives_date ON stock_primitives(as_of_date DESC);

-- V3 composite scores per stock (Quality / Health / Exit / Add).
CREATE TABLE IF NOT EXISTS stock_scores (
    nse_symbol          TEXT PRIMARY KEY,
    as_of_date          DATE NOT NULL,
    quality_score       NUMERIC(5, 2),
    health_score        NUMERIC(5, 2),
    exit_score          NUMERIC(5, 2),
    add_score           NUMERIC(5, 2),
    quality_components  JSONB,                   -- per-sub-factor breakdown
    health_components   JSONB,
    exit_components     JSONB,
    add_components      JSONB,
    recommendation      TEXT,                    -- BUY | HOLD | TRIM | EXIT | REVIEW
    recommendation_reason TEXT,
    low_confidence      BOOLEAN DEFAULT FALSE,
    engine_version      TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (nse_symbol) REFERENCES stock_master(nse_symbol) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_stock_scores_quality  ON stock_scores(quality_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_stock_scores_exit     ON stock_scores(exit_score DESC NULLS LAST);
