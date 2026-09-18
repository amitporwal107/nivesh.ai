-- 150_technical_features_daily.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- v6 technical feature store (PRD "Ten-Percent Days v6" §13.1, Phase 2).
--
-- One row per (symbol, session, feature_version). The version is part of the key on purpose: when a definition
-- changes, the new version is written alongside the old rather than overwriting it, so a past backtest can still be
-- reproduced exactly against the features it actually saw (PRD criterion 14: model, feature and data versions recorded).
--
-- RESEARCH ONLY at this migration: nidp.services.tpd_model.technical_v6 and regime_v6 compute these values, nothing
-- serves them. No route, page or model reads this table. It is additive — it creates a new table and touches nothing
-- that exists.
--
-- Missing stays missing (PRD criterion 13): every feature column is nullable and a window that is not fully present is
-- written NULL, never 0 or a carried-forward value. bars_available and features_missing record how much history backed
-- the row and how many of the features could not be computed, so a thin row is visible as thin instead of looking
-- like a confident one.
--
-- data_cutoff_date is the last session that fed the calculation. It exists so a row can be audited for look-ahead:
-- it must never be later than session_date.
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;

CREATE TABLE IF NOT EXISTS nidp.technical_features_daily (
    symbol                          TEXT NOT NULL,
    session_date                    DATE NOT NULL,
    feature_version                 TEXT NOT NULL,

    -- trend
    ema20_slope_10d                 DOUBLE PRECISION,
    ema50_slope_20d                 DOUBLE PRECISION,
    trend_alignment_score           DOUBLE PRECISION,
    trend_efficiency_20d            DOUBLE PRECISION,
    higher_high_count_20d           DOUBLE PRECISION,
    higher_low_count_20d            DOUBLE PRECISION,

    -- momentum
    rsi_slope_3d                    DOUBLE PRECISION,
    momentum_acceleration           DOUBLE PRECISION,
    positive_return_day_ratio_10d   DOUBLE PRECISION,

    -- volatility
    volatility_percentile_60d       DOUBLE PRECISION,
    bollinger_width_percentile      DOUBLE PRECISION,
    range_expansion_ratio           DOUBLE PRECISION,
    true_range_zscore               DOUBLE PRECISION,

    -- volume and supply/demand
    up_volume_down_volume_ratio_10d DOUBLE PRECISION,
    obv_slope_10d                   DOUBLE PRECISION,
    cmf20                           DOUBLE PRECISION,
    mfi14                           DOUBLE PRECISION,
    delivery_zscore_20d             DOUBLE PRECISION,
    high_volume_positive_close_ratio DOUBLE PRECISION,

    -- price action and candle geometry
    close_location_value            DOUBLE PRECISION,
    body_pct_of_range               DOUBLE PRECISION,
    upper_wick_pct                  DOUBLE PRECISION,
    lower_wick_pct                  DOUBLE PRECISION,
    body_to_atr                     DOUBLE PRECISION,

    -- structure
    distance_to_resistance_atr      DOUBLE PRECISION,
    distance_to_support_atr         DOUBLE PRECISION,
    breakout_age_days               DOUBLE PRECISION,
    failed_breakout_count_60d       DOUBLE PRECISION,
    consolidation_days              DOUBLE PRECISION,

    -- relative strength: index-relative is per symbol, the ranks are cross-sectional for that session
    relative_return_5d              DOUBLE PRECISION,
    relative_return_20d             DOUBLE PRECISION,
    relative_strength_rank_universe DOUBLE PRECISION,
    relative_strength_rank_sector   DOUBLE PRECISION,
    sector_relative_strength        DOUBLE PRECISION,

    -- regime labels (regime_v6); market_* repeat per row so a row is self-contained for a backtest join
    market_regime                   TEXT,
    market_volatility               TEXT,
    technical_regime                TEXT,
    regime_version                  TEXT,

    -- data quality: how much history backed this row, and what could not be computed
    bars_available                  INTEGER,
    features_missing                INTEGER,
    data_cutoff_date                DATE,
    calculated_at                   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, session_date, feature_version),
    -- a feature row may never be computed from a session later than its own
    CONSTRAINT technical_features_no_lookahead CHECK (data_cutoff_date IS NULL OR data_cutoff_date <= session_date)
);

-- the backtest reads a whole session at a time (every symbol for one date), which is the opposite order to the key
CREATE INDEX IF NOT EXISTS idx_technical_features_session
    ON nidp.technical_features_daily (session_date, feature_version);

CREATE INDEX IF NOT EXISTS idx_technical_features_regime
    ON nidp.technical_features_daily (session_date, technical_regime)
    WHERE technical_regime IS NOT NULL;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('150_technical_features_daily.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
