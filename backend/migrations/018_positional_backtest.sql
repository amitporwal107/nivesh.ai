-- 018_positional_backtest.sql
-- Backtest + calibration support for the pre-breakout accumulation
-- detector. Two tables:
--
--   positional_backtest_labels — every (symbol, scan_date) pair we
--   replayed gets one row with the accumulation score we *would have*
--   computed that day, plus the realised forward returns at three
--   horizons. This is the labeled training set for calibration.
--
--   accumulation_calibration — bucketed hit-rate stats produced by
--   sweeping `positional_backtest_labels`. Maps an accumulation_score
--   to a probability_of_move based on what actually happened
--   historically. Refreshed nightly.

CREATE TABLE IF NOT EXISTS positional_backtest_labels (
    nse_symbol          TEXT NOT NULL,
    scan_date           DATE NOT NULL,

    -- Inputs as they would have been seen on scan_date (T+0)
    accumulation_score  NUMERIC(5, 4),
    signals             TEXT[],                 -- list of fired signal names
    final_score         NUMERIC(5, 4),          -- engine score on that day
    stage               TEXT,
    close_price         NUMERIC(14, 4),

    -- Forward outcomes: max return + drawdown over 5/10/20 trading days
    -- after scan_date. NULL if not yet evaluable (horizon hasn't elapsed).
    fwd_max_return_5d   NUMERIC(7, 2),
    fwd_max_return_10d  NUMERIC(7, 2),
    fwd_max_return_20d  NUMERIC(7, 2),
    fwd_max_drawdown_5d NUMERIC(7, 2),
    fwd_max_drawdown_10d NUMERIC(7, 2),
    fwd_max_drawdown_20d NUMERIC(7, 2),

    -- Did the move happen? Binary label per horizon.
    -- "moved" defined as fwd_max_return >= 5% within the horizon.
    moved_5d            BOOLEAN,
    moved_10d           BOOLEAN,
    moved_20d           BOOLEAN,

    engine_version      TEXT,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (nse_symbol, scan_date)
);

CREATE INDEX IF NOT EXISTS idx_pbl_score
    ON positional_backtest_labels (accumulation_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_pbl_moved
    ON positional_backtest_labels (moved_10d) WHERE moved_10d IS NOT NULL;


-- ── Calibration table — bucketed hit rates ──────────────────────────────
-- Populated by macro-level sweep over positional_backtest_labels. Each
-- row is one accumulation_score bucket (e.g. 0.55-0.60), one horizon,
-- and the empirical probability that "moved" was true.
CREATE TABLE IF NOT EXISTS accumulation_calibration (
    bucket_lo           NUMERIC(4, 2) NOT NULL,    -- e.g. 0.55
    bucket_hi           NUMERIC(4, 2) NOT NULL,    -- e.g. 0.60
    horizon_days        INTEGER NOT NULL,          -- 5 | 10 | 20
    sample_count        INTEGER NOT NULL,
    moves_count         INTEGER NOT NULL,
    probability         NUMERIC(5, 4),             -- moves / sample
    avg_fwd_return      NUMERIC(7, 2),
    avg_fwd_drawdown    NUMERIC(7, 2),
    refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (bucket_lo, bucket_hi, horizon_days)
);
