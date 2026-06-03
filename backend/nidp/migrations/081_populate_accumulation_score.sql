-- Migration 081: Populate accumulation_score in stock_features_daily
-- ─────────────────────────────────────────────────────────────────────────────
-- Problem: accumulation_score is 0% covered for all Nifty 500 stocks because
--   the existing feature_snapshotter (Python) path never ran inside the NIDP
--   SQL pipeline.  The V3 momentum_score uses accumulation_score × 100 at 25%
--   weight — without it, every stock gets a default 50 instead of a real signal.
--
-- Fix: Translate the four-signal detector from
--   services/positional_engine/accumulation_detector.py to a SQL function
--   that reads existing columns from stock_features_daily and writes back
--   accumulation_score (0.0–1.0) and accumulation_signals (text array).
--
-- Signals:
--   1. vol_divergence  — vol_z20 > 1.0 AND flat price (|slope| < 0.1)
--   2. delivery_spike  — deliv_trend10 > 15 AND flat price (slope ≤ 0.3)
--   3. bb_squeeze      — bb_width < 0.08 AND atr_pct < 2.5
--   4. sector_lag      — stock lagging Nifty 50 AND above SMA50
--
-- Composite: mean(fired_strengths) × confirm_factor{1→0.5, 2→0.85, 3→1.0, 4→1.05}
-- ─────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION nidp.populate_accumulation_score(p_target_date DATE)
RETURNS INTEGER AS $$
DECLARE
    v_rows INTEGER;
    v_bench_ret_20d NUMERIC;
BEGIN
    -- ── Benchmark 20-day return (Nifty 50) for sector_lag signal ─────
    SELECT ROUND(((cur.close_price / NULLIF(prev.close_price, 0) - 1) * 100)::NUMERIC, 2)
      INTO v_bench_ret_20d
      FROM (
          SELECT close_price FROM nidp.index_eod
           WHERE index_name = 'Nifty 50' AND as_of_date <= p_target_date
           ORDER BY as_of_date DESC LIMIT 1
      ) cur,
      (
          SELECT close_price FROM nidp.index_eod
           WHERE index_name = 'Nifty 50'
             AND as_of_date <= (p_target_date - 20)
           ORDER BY as_of_date DESC LIMIT 1
      ) prev;

    -- Default to 0 if bench return unavailable (disables sector_lag)
    v_bench_ret_20d := COALESCE(v_bench_ret_20d, 0);

    WITH signals AS (
        SELECT
            f.symbol,
            -- ── Signal 1: Volume divergence ──────────────────────────
            -- vol_z20 > 1.0 AND |sma50_slope| < 0.1
            CASE
                WHEN f.vol_z20 > 1.0 AND ABS(f.sma50_slope) < 0.1
                THEN LEAST(1.0, 0.4 + (f.vol_z20 - 1.0) * 0.3)
                ELSE 0.0
            END AS s1_strength,
            CASE
                WHEN f.vol_z20 > 1.0 AND ABS(f.sma50_slope) < 0.1
                 AND LEAST(1.0, 0.4 + (f.vol_z20 - 1.0) * 0.3) >= 0.30
                THEN TRUE ELSE FALSE
            END AS s1_fired,

            -- ── Signal 2: Delivery spike ─────────────────────────────
            -- deliv_trend10 > 15 AND sma50_slope <= 0.3
            CASE
                WHEN f.deliv_trend10 > 15.0 AND COALESCE(f.sma50_slope, 0) <= 0.3
                THEN LEAST(1.0, 0.4 + (f.deliv_trend10 - 15.0) / 35.0 * 0.6)
                ELSE 0.0
            END AS s2_strength,
            CASE
                WHEN f.deliv_trend10 > 15.0 AND COALESCE(f.sma50_slope, 0) <= 0.3
                 AND LEAST(1.0, 0.4 + (f.deliv_trend10 - 15.0) / 35.0 * 0.6) >= 0.30
                THEN TRUE ELSE FALSE
            END AS s2_fired,

            -- ── Signal 3: Bollinger / ATR compression ────────────────
            -- bb_width < 0.08 AND atr_pct < 2.5
            CASE
                WHEN f.bb_width < 0.08 AND f.atr_pct < 2.5
                THEN (
                    -- bb_strength: ramp bb_width from [0.03, 0.08] → [1.0, 0.0]
                    GREATEST(0.0, LEAST(1.0, 1.0 - (f.bb_width - 0.03) / 0.05))
                    -- atr_strength: ramp atr_pct from [1.0, 2.5] → [1.0, 0.0]
                  + GREATEST(0.0, LEAST(1.0, 1.0 - (f.atr_pct - 1.0) / 1.5))
                ) / 2.0
                ELSE 0.0
            END AS s3_strength,
            CASE
                WHEN f.bb_width < 0.08 AND f.atr_pct < 2.5
                 AND (
                    GREATEST(0.0, LEAST(1.0, 1.0 - (f.bb_width - 0.03) / 0.05))
                  + GREATEST(0.0, LEAST(1.0, 1.0 - (f.atr_pct - 1.0) / 1.5))
                 ) / 2.0 >= 0.30
                THEN TRUE ELSE FALSE
            END AS s3_fired,

            -- ── Signal 4: Sector lag ─────────────────────────────────
            -- bench_ret > 2% AND stock lagging AND stock above SMA50
            CASE
                WHEN v_bench_ret_20d > 2.0
                 AND f.return_20d_pct IS NOT NULL
                 AND f.close > f.sma50 AND f.sma50 > 0
                 AND f.return_20d_pct < (v_bench_ret_20d * 0.4)
                THEN LEAST(1.0, 0.4 + (v_bench_ret_20d - f.return_20d_pct) / 10.0 * 0.6)
                ELSE 0.0
            END AS s4_strength,
            CASE
                WHEN v_bench_ret_20d > 2.0
                 AND f.return_20d_pct IS NOT NULL
                 AND f.close > f.sma50 AND f.sma50 > 0
                 AND f.return_20d_pct < (v_bench_ret_20d * 0.4)
                 AND LEAST(1.0, 0.4 + (v_bench_ret_20d - f.return_20d_pct) / 10.0 * 0.6) >= 0.30
                THEN TRUE ELSE FALSE
            END AS s4_fired

        FROM nidp.stock_features_daily f
        WHERE f.as_of_date = p_target_date
          AND f.close IS NOT NULL
          AND f.vol_z20 IS NOT NULL
    ),
    composite AS (
        SELECT
            symbol,
            -- Count of fired signals
            (s1_fired::int + s2_fired::int + s3_fired::int + s4_fired::int) AS n_fired,
            -- Sum of fired strengths
            (CASE WHEN s1_fired THEN s1_strength ELSE 0 END
           + CASE WHEN s2_fired THEN s2_strength ELSE 0 END
           + CASE WHEN s3_fired THEN s3_strength ELSE 0 END
           + CASE WHEN s4_fired THEN s4_strength ELSE 0 END) AS sum_strength,
            -- Signal names array
            ARRAY_REMOVE(ARRAY[
                CASE WHEN s1_fired THEN 'vol_divergence' END,
                CASE WHEN s2_fired THEN 'delivery_spike' END,
                CASE WHEN s3_fired THEN 'bb_squeeze' END,
                CASE WHEN s4_fired THEN 'sector_lag' END
            ], NULL) AS signal_names
        FROM signals
    ),
    scored AS (
        SELECT
            symbol,
            CASE
                WHEN n_fired = 0 THEN 0.0
                ELSE LEAST(1.0, ROUND((
                    (sum_strength / n_fired)  -- mean strength
                    * CASE n_fired
                        WHEN 1 THEN 0.50
                        WHEN 2 THEN 0.85
                        WHEN 3 THEN 1.00
                        ELSE 1.05
                      END
                )::NUMERIC, 4))
            END AS score,
            signal_names
        FROM composite
    )
    UPDATE nidp.stock_features_daily f
       SET accumulation_score   = s.score,
           accumulation_signals = s.signal_names
      FROM scored s
     WHERE f.symbol     = s.symbol
       AND f.as_of_date = p_target_date;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION nidp.populate_accumulation_score(DATE) IS
    'Compute OBV-inspired accumulation score (0–1) from 4 signals: '
    'vol_divergence, delivery_spike, bb_squeeze, sector_lag. '
    'Run after populate_stock_price_features() and before populate_stock_features_v3().';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('081_populate_accumulation_score.sql')
ON CONFLICT (filename) DO NOTHING;
