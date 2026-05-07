-- 026_nidp_price_adjustments.sql — Adjusted EOD prices.
--
-- Source: derived from nidp.prices_eod ⋈ nidp.corporate_actions.
-- Cadence: rebuilt nightly after corp_actions ingest succeeds, OR
--          on-demand when a new SPLIT/BONUS lands inside the
--          rolling-list window.
--
-- Why this matters: every backtest, return calc, technical indicator
-- and 52-week-high lookup is silently wrong without a corp-action
-- adjustment. yfinance's Adj Close was our prior crutch — this table
-- gives us a first-class, audit-trail-bearing replacement sourced
-- directly from NSE CA filings.
--
-- Adjustment policy:
--   • SPLIT  factor = face_value_post / face_value_pre
--   • BONUS  factor = m / (n + m)   for ratio "n new : m held"
--   • DIVIDEND factor = (prev_close − amount) / prev_close
--                       (only applied to tret_close, not adj_close)
--   • RIGHTS deliberately NOT applied — needs subscription price &
--     theoretical-rights-issue math; documented for Phase 2.
--
-- For each row, cumulative_adj_factor is the product of all SPLIT and
-- BONUS factors whose ex_date is STRICTLY GREATER than as_of_date.
-- Prices ON the ex-date are post-adjustment per NSE convention, so
-- they receive the cumulative factor of all events AFTER them.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.prices_eod_adjusted (
    symbol                  TEXT NOT NULL,
    as_of_date              DATE NOT NULL,

    -- Raw (verbatim from prices_eod) — kept for sanity & comparison
    raw_open                NUMERIC(14,4),
    raw_high                NUMERIC(14,4),
    raw_low                 NUMERIC(14,4),
    raw_close               NUMERIC(14,4),
    raw_volume              BIGINT,

    -- Price-return adjusted (SPLIT + BONUS only) — what backtests use
    adj_open                NUMERIC(14,6),
    adj_high                NUMERIC(14,6),
    adj_low                 NUMERIC(14,6),
    adj_close               NUMERIC(14,6),
    adj_volume              BIGINT,

    -- Total-return adjusted (SPLIT + BONUS + DIVIDEND) — for total
    -- return / Sharpe / drawdown calcs
    tret_close              NUMERIC(14,6),

    -- Diagnostics
    cumulative_adj_factor   NUMERIC(14,8),                 -- product of split+bonus factors strictly after as_of_date
    cumulative_tret_factor  NUMERIC(14,8),
    last_event_ex_date      DATE,                           -- most recent ex_date strictly after as_of_date
    last_event_type         TEXT,                           -- 'SPLIT' | 'BONUS' | 'DIVIDEND'

    source                  TEXT NOT NULL DEFAULT 'NIDP_PRICE_ADJUSTER',
    source_run_id           UUID NOT NULL,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, as_of_date, source)
);

CREATE INDEX IF NOT EXISTS idx_pea_symbol_date
    ON nidp.prices_eod_adjusted(symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_pea_date
    ON nidp.prices_eod_adjusted(as_of_date DESC);


-- TimescaleDB hypertable — 1-month chunks, matching prices_eod
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.prices_eod_adjusted', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('026_nidp_price_adjustments.sql')
    ON CONFLICT (filename) DO NOTHING;
