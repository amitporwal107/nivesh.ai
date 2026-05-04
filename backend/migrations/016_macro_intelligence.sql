-- 016_macro_intelligence.sql
--
-- Macro Intelligence Layer (Nivesh Positional Engine PR-1).
--
-- Four tables that together produce the daily macro context the engine
-- uses to bias stock selection + position sizing:
--   * macro_daily         — raw daily prints (crude / USDINR / 10Y / Nifty)
--   * macro_features      — derived signals (trend / momentum / breakout)
--   * macro_state         — regime classification (inflation / liquidity / risk)
--   * sector_macro_scores — per-sector daily macro tilt for the scoring layer
--
-- Population path:
--   macro_ingester (yfinance) → macro_daily
--   macro_engine.compute_features() → macro_features
--   macro_engine.classify_regime() → macro_state
--   macro_engine.compute_sector_scores() → sector_macro_scores  (PR-2)
--
-- All columns are nullable except the date PK so a single failed source
-- doesn't block the row insert. Source + confidence cols let the API
-- response carry data lineage straight through to the UI.

CREATE TABLE IF NOT EXISTS macro_daily (
    date              DATE PRIMARY KEY,
    crude_price       NUMERIC(12, 4),
    usd_inr           NUMERIC(12, 4),
    bond_10y          NUMERIC(8, 4),
    nifty             NUMERIC(14, 4),
    source_crude      VARCHAR(32),
    source_usd        VARCHAR(32),
    source_bond       VARCHAR(32),
    source_nifty      VARCHAR(32),
    confidence_crude  NUMERIC(4, 2),
    confidence_usd    NUMERIC(4, 2),
    confidence_bond   NUMERIC(4, 2),
    confidence_nifty  NUMERIC(4, 2),
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_daily_date_desc ON macro_daily(date DESC);


CREATE TABLE IF NOT EXISTS macro_features (
    date                DATE PRIMARY KEY,
    -- Crude
    crude_20dma         NUMERIC(12, 4),
    crude_50dma         NUMERIC(12, 4),
    crude_trend         BOOLEAN,
    crude_momentum_5d   NUMERIC(8, 4),
    crude_breakout      BOOLEAN,
    -- USDINR
    usd_20dma           NUMERIC(12, 4),
    usd_trend           BOOLEAN,
    usd_momentum_5d     NUMERIC(8, 4),
    -- 10Y yield
    yield_50dma         NUMERIC(8, 4),
    yield_trend         BOOLEAN,
    yield_momentum_5d   NUMERIC(8, 4),
    -- Market
    nifty_50dma         NUMERIC(14, 4),
    market_regime       VARCHAR(16),  -- BULL | NEUTRAL | BEAR
    created_at          TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_features_date_desc ON macro_features(date DESC);


CREATE TABLE IF NOT EXISTS macro_state (
    date              DATE PRIMARY KEY,
    inflation         VARCHAR(16),    -- RISING | STABLE
    liquidity         VARCHAR(16),    -- TIGHT | EASY
    risk              VARCHAR(16),    -- HIGH | MEDIUM | LOW
    macro_multiplier  NUMERIC(4, 2),  -- 0.80 | 1.00 | 1.10
    insight           TEXT,           -- 1-line human-readable summary for Copilot
    created_at        TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_macro_state_date_desc ON macro_state(date DESC);


-- Per-sector macro tilt — populated in PR-2 by the scoring integration.
-- Schema landed here so PR-2 doesn't need its own migration.
CREATE TABLE IF NOT EXISTS sector_macro_scores (
    date         DATE        NOT NULL,
    sector       VARCHAR(64) NOT NULL,
    macro_score  NUMERIC(8, 4),    -- typically -10 .. +10
    rationale    TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (date, sector)
);
CREATE INDEX IF NOT EXISTS idx_sector_macro_scores_date_desc
    ON sector_macro_scores(date DESC);
