-- 191: long daily price history for research — TrueData's adjusted bars from 2010, stitched to our basis.
--
-- Why a table of its own: nidp.prices_eod_adjusted starts on 2024-04-01 and many readers scan it without a date floor
-- (screeners, features, backtests). Rows added there would silently change their outputs. This table is read only by
-- research code that asks for it, through the view below (Research Copilot category 20: correlation and sensitivity of a
-- stock to crude, the rupee proxy, G-Sec indices and VIX).
--
-- What a row is: TrueData's daily bar (adjusted by TrueData for splits, bonuses AND demergers) multiplied by the symbol's
-- stitch_factor = our adj_close / TrueData's close on the symbol's first days in prices_eod_adjusted. Our adjuster does
-- not adjust for demergers (ITC on 2024-04-01: ours 426.70, TrueData 402.55), so without the factor the level would jump
-- where history meets our series. Returns inside the history are TrueData's (scale-invariant); the level is ours.
-- Volume is TrueData's adjusted volume, not rescaled (the factor is a price-only difference).
-- Written by nidp.services.truedata_history (one transaction per batch of symbols, run id in source_run_id). A symbol
-- whose factor is not stable over >= 3 overlap days, whose seam is longer than a few days, or whose TrueData basis
-- changed since the raw fetch is NOT loaded; its status is recorded in prices_eod_history_stitch.
--
-- Rollback of a load:  python -m nidp.services.truedata_history --rollback <RUN_ID>
-- Rollback of this migration (nothing else reads these objects):
--   DROP VIEW nidp.v_prices_eod_long_research; DROP TABLE nidp.prices_eod_history_stitch;
--   DROP TABLE nidp.prices_eod_history; DELETE FROM nidp.schema_migrations WHERE filename = '191_truedata_price_history.sql';
--
-- A plain table (no hypertable): reads are per-symbol date ranges served by the primary key.
-- Re-runnable.

CREATE TABLE IF NOT EXISTS nidp.prices_eod_history (
    symbol          TEXT          NOT NULL,
    as_of_date      DATE          NOT NULL,
    adj_open        NUMERIC(14,6),
    adj_high        NUMERIC(14,6),
    adj_low         NUMERIC(14,6),
    adj_close       NUMERIC(14,6) NOT NULL,
    volume          BIGINT,
    stitch_factor   NUMERIC(14,8) NOT NULL,
    source          TEXT          NOT NULL DEFAULT 'truedata',
    source_run_id   UUID          NOT NULL,
    ingested_at     TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, as_of_date, source),
    CONSTRAINT prices_eod_history_close_positive CHECK (adj_close > 0),
    CONSTRAINT prices_eod_history_factor_positive CHECK (stitch_factor > 0)
);

COMMENT ON TABLE nidp.prices_eod_history IS
    'RESEARCH ONLY. TrueData adjusted daily bars before each symbol''s first prices_eod_adjusted date, x stitch_factor '
    '(our adj_close / TrueData close on the overlap days). Not read by screeners, features or backtests. Migration 191.';

-- One row per symbol per load run: what happened and the numbers behind it. A symbol that was flagged (not loaded) is
-- only here, with its status and reason.
CREATE TABLE IF NOT EXISTS nidp.prices_eod_history_stitch (
    source_run_id     UUID        NOT NULL,
    symbol            TEXT        NOT NULL,
    source            TEXT        NOT NULL DEFAULT 'truedata',
    status            TEXT        NOT NULL,      -- LOADED | SKIPPED_EXISTING | NO_HISTORY | NO_WAREHOUSE | SEAM_GAP
                                                 -- | NO_OVERLAP | UNSTABLE | FACTOR_OUT_OF_RANGE | BASIS_CHANGED
                                                 -- | NO_BASIS_CHECK | FETCH_FAILED
    reason            TEXT,
    stitch_factor     NUMERIC(14,8),
    overlap_days      INT,
    overlap_from      DATE,
    overlap_to        DATE,
    max_dev_pct       NUMERIC(12,6),             -- worst overlap ratio vs the factor, percent
    history_from      DATE,
    history_to        DATE,                      -- last history bar loaded (the seam's left side)
    warehouse_from    DATE,                      -- first prices_eod_adjusted date (the seam's right side)
    rows_loaded       INT         NOT NULL DEFAULT 0,
    duplicate_dates   INT         NOT NULL DEFAULT 0,
    conflicting_dates INT         NOT NULL DEFAULT 0,   -- dates dropped: their duplicate rows disagreed
    seam_move_pct     NUMERIC(12,6),             -- our first adj_close vs the last stitched close, percent
    td_seam_move_pct  NUMERIC(12,6),             -- TrueData's own move over the same days, percent
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_run_id, symbol, source)
);

CREATE INDEX IF NOT EXISTS idx_prices_eod_history_stitch_symbol
    ON nidp.prices_eod_history_stitch (symbol, created_at DESC);

-- History only where we have no price of our own, then our adjusted series. RESEARCH ONLY: the two parts come from
-- different sources (basis_source says which); the level is continuous at the seam by construction (stitch_factor),
-- and TrueData's history also carries TrueData's demerger adjustments before the seam, which ours does not after it.
CREATE OR REPLACE VIEW nidp.v_prices_eod_long_research AS
SELECT h.symbol, h.as_of_date, h.adj_open, h.adj_high, h.adj_low, h.adj_close, h.volume,
       h.stitch_factor, 'truedata_history'::text AS basis_source
  FROM nidp.prices_eod_history h
  -- grouped once per symbol (a WHERE symbol = ... on the view is pushed into this aggregate), not once per row
  LEFT JOIN (SELECT a.symbol, min(a.as_of_date) AS first_date
               FROM nidp.prices_eod_adjusted a
              WHERE a.source = 'NIDP_PRICE_ADJUSTER'
              GROUP BY a.symbol) f ON f.symbol = h.symbol
 WHERE h.source = 'truedata'
   AND h.as_of_date < COALESCE(f.first_date, 'infinity'::date)
UNION ALL
SELECT a.symbol, a.as_of_date, a.adj_open, a.adj_high, a.adj_low, a.adj_close, a.adj_volume AS volume,
       NULL::numeric AS stitch_factor, 'NIDP_PRICE_ADJUSTER'::text AS basis_source
  FROM nidp.prices_eod_adjusted a
 WHERE a.source = 'NIDP_PRICE_ADJUSTER';

COMMENT ON VIEW nidp.v_prices_eod_long_research IS
    'RESEARCH ONLY: TrueData history (prices_eod_history, stitched to our basis) before each symbol''s first '
    'prices_eod_adjusted date, then prices_eod_adjusted. basis_source tells the two apart. Migration 191.';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('191_truedata_price_history.sql')
ON CONFLICT (filename) DO NOTHING;
