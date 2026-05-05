-- 019_positional_backtest_v2.sql
-- Calibration v2 — fixes the inverted-hit-rate bug from v1 by adding
-- two outcome metrics that are properly aligned with the
-- accumulation-detector's design intent:
--
--   broke_high_Nd          — did the stock close above its 20d high
--                            (resistance at scan_date) within N bars?
--                            This is the actual "breakout fired" event,
--                            independent of the 5%-move threshold.
--
--   move_threshold_pct     — the scale-aware move threshold used for
--                            this label, computed as max(5, atr_pct × 3).
--                            High-vol stocks need bigger moves to count;
--                            low-vol stocks are evaluated against a
--                            looser bar.
--
--   moved_scaled_Nd        — fwd_max_return ≥ move_threshold_pct?
--                            Replaces the old fixed-5% moved_Nd, which
--                            was anti-predictive on tight-range stocks.
--
-- The old `moved_Nd` columns are kept (no DROP) so existing rows
-- aren't lost; the calibrate() job now writes the new metrics.

ALTER TABLE positional_backtest_labels
    ADD COLUMN IF NOT EXISTS broke_high_5d        BOOLEAN,
    ADD COLUMN IF NOT EXISTS broke_high_10d       BOOLEAN,
    ADD COLUMN IF NOT EXISTS broke_high_20d       BOOLEAN,
    ADD COLUMN IF NOT EXISTS move_threshold_pct   NUMERIC(5, 2),
    ADD COLUMN IF NOT EXISTS moved_scaled_5d      BOOLEAN,
    ADD COLUMN IF NOT EXISTS moved_scaled_10d     BOOLEAN,
    ADD COLUMN IF NOT EXISTS moved_scaled_20d     BOOLEAN,
    ADD COLUMN IF NOT EXISTS resistance_at_scan   NUMERIC(14, 4);

CREATE INDEX IF NOT EXISTS idx_pbl_broke_high
    ON positional_backtest_labels (broke_high_10d) WHERE broke_high_10d IS NOT NULL;


-- Calibration table now keys on (metric, bucket, horizon) so we can
-- store hit rates for each outcome metric independently. The PRIMARY
-- KEY is dropped + re-added; existing rows tagged metric='moved_5pct'
-- (the v1 metric) so they're not lost.
ALTER TABLE accumulation_calibration
    ADD COLUMN IF NOT EXISTS metric TEXT;

UPDATE accumulation_calibration
   SET metric = 'moved_5pct'
   WHERE metric IS NULL;

ALTER TABLE accumulation_calibration
    ALTER COLUMN metric SET NOT NULL;

-- Drop old PK + add new composite PK (metric, lo, hi, horizon)
ALTER TABLE accumulation_calibration
    DROP CONSTRAINT IF EXISTS accumulation_calibration_pkey;

ALTER TABLE accumulation_calibration
    ADD PRIMARY KEY (metric, bucket_lo, bucket_hi, horizon_days);
