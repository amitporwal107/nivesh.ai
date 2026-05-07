-- 021_stock_features_daily.sql — Per-stock daily technical features.
--
-- One row per (symbol, as_of_date). Materialised by the
-- feature_snapshotter ingester; reads ~90 trailing bars from
-- nidp.prices_eod and writes a flat row per symbol/date that the
-- Strategy Builder compiler can SQL-filter against directly. Without
-- this snapshot, every screen step would recompute 90 bars per symbol
-- per query — fine for one positional pick, fatal for a 500-symbol
-- screen that the user iterates on.
--
-- Append-only by (symbol, as_of_date, source). Refreshed daily after
-- prices_eod for that date is READY (gated by validation findings).

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.stock_features_daily (
    symbol              TEXT NOT NULL,
    as_of_date          DATE NOT NULL,

    -- Reference price (for compiler convenience — joins not required)
    close               NUMERIC(14,4),

    -- Trend
    sma20               NUMERIC(14,4),
    sma50               NUMERIC(14,4),
    sma100              NUMERIC(14,4),
    sma200              NUMERIC(14,4),
    sma50_slope         NUMERIC(10,6),                  -- per-day Δ% over last 20 bars
    dist_200dma_pct     NUMERIC(10,4),                  -- (close − sma200) / sma200 × 100
    dist_52w_high_pct   NUMERIC(10,4),                  -- (close − 52w_high) / 52w_high × 100 (≤ 0)
    dist_52w_low_pct    NUMERIC(10,4),

    -- Momentum
    rsi14               NUMERIC(7,4),
    macd                NUMERIC(14,6),
    macd_signal         NUMERIC(14,6),
    macd_hist           NUMERIC(14,6),
    return_5d_pct       NUMERIC(10,4),
    return_20d_pct      NUMERIC(10,4),
    return_60d_pct      NUMERIC(10,4),

    -- Volatility / structure
    atr14               NUMERIC(14,4),
    atr_pct             NUMERIC(10,4),                  -- atr14 / close × 100
    bb_width            NUMERIC(10,6),                  -- (upper − lower) / middle (Keltner-style)
    bb_pos              NUMERIC(10,6),                  -- (close − lower) / (upper − lower)

    -- Volume / flow
    avg_volume_20       BIGINT,
    vol_z20             NUMERIC(10,4),                  -- (today_vol − avg20) / std20
    deliv_pct_avg_20    NUMERIC(7,4),
    deliv_trend10       NUMERIC(10,4),                  -- linear regression slope of deliv_pct over 10 bars

    -- Swings / levels
    swing_high_20       NUMERIC(14,4),
    swing_low_20        NUMERIC(14,4),
    pivot_breakout_flag BOOLEAN,                        -- close > swing_high_20 today, not previous

    -- Pre-breakout / accumulation (matches accumulation_detector output)
    accumulation_score  NUMERIC(7,4),                   -- 0..1
    accumulation_signals TEXT[],                        -- ['vol_divergence','delivery_spike',…]

    -- Provenance
    source              TEXT NOT NULL DEFAULT 'NIDP_FEATURE_SNAPSHOTTER',
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, as_of_date, source)
);

CREATE INDEX IF NOT EXISTS idx_stock_features_date
    ON nidp.stock_features_daily(as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_features_symbol_date
    ON nidp.stock_features_daily(symbol, as_of_date DESC);

-- TimescaleDB hypertable conversion — guarded by extension presence.
-- 1-month chunks; older chunks compressible after 90 days.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.stock_features_daily', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('021_stock_features_daily.sql')
    ON CONFLICT (filename) DO NOTHING;
