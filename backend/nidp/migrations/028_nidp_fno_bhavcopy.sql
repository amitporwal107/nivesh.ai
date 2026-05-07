-- 028_nidp_fno_bhavcopy.sql — NSE F&O EOD bhavcopy.
--
-- Source:   NSE archives — BhavCopy_NSE_FO_*.csv.zip (post-Jul-2024)
-- Cadence:  Daily, ~18:00 IST
-- Output:   nidp.fno_bhavcopy
--
-- One row per (trading_day, instrument_type, ticker, expiry, strike,
-- option_type). Covers index futures, stock futures, index options,
-- stock options.
--
-- Rationale: this is the FREE part of options-chain intelligence. PCR,
-- max pain, OI buildup, IV proxies — all derivable from EOD F&O bhav.
-- Real-time tick is a separate (vendor-gated) story; this lands the
-- T+1 / EOD signals at zero cost.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.fno_bhavcopy (
    as_of_date          DATE NOT NULL,                  -- trading day (TradDt)
    biz_date            DATE,                           -- BizDt — usually same as TradDt
    instrument_type     TEXT NOT NULL,                  -- 'FUTIDX' | 'FUTSTK' | 'OPTIDX' | 'OPTSTK'
    ticker_symbol       TEXT NOT NULL,                  -- TckrSymb — underlying
    isin                TEXT,
    series              TEXT,                           -- SctySrs (typically NULL for indices)
    expiry_date         DATE NOT NULL,                  -- XpryDt
    actual_expiry_date  DATE,                           -- FininstrmActlXpryDt (rolls when expiry shifts)
    strike_price        NUMERIC(14,4),                  -- StrkPric (NULL for futures)
    option_type         TEXT,                           -- 'CE' | 'PE' | NULL for futures

    -- Quotes
    open_price          NUMERIC(14,4),
    high_price          NUMERIC(14,4),
    low_price           NUMERIC(14,4),
    close_price         NUMERIC(14,4),
    last_price          NUMERIC(14,4),
    prev_close_price    NUMERIC(14,4),
    settle_price        NUMERIC(14,4),
    underlying_price    NUMERIC(14,4),

    -- Open interest + volume
    open_interest       BIGINT,
    change_in_oi        BIGINT,
    traded_volume       BIGINT,
    traded_value        NUMERIC(20,4),                  -- ₹ (raw, NOT crores — bhavcopy reports rupees)
    num_trades          BIGINT,
    new_board_lot_qty   INTEGER,

    -- Provenance
    source              TEXT NOT NULL,                  -- 'NSE_FO_BHAV'
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (as_of_date, instrument_type, ticker_symbol, expiry_date,
                 strike_price, option_type, source)
);

CREATE INDEX IF NOT EXISTS idx_fno_date
    ON nidp.fno_bhavcopy(as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_fno_ticker_date
    ON nidp.fno_bhavcopy(ticker_symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_fno_expiry
    ON nidp.fno_bhavcopy(expiry_date);
CREATE INDEX IF NOT EXISTS idx_fno_options
    ON nidp.fno_bhavcopy(ticker_symbol, expiry_date, option_type, strike_price)
    WHERE option_type IS NOT NULL;


-- ── v_options_chain_latest ──────────────────────────────────────────
-- For each (ticker, expiry), the most-recent EOD options chain
-- (CE+PE per strike). Consumers that want today's PCR, max-pain,
-- IV-skew read from this view rather than re-aggregating daily.
CREATE OR REPLACE VIEW nidp.v_options_chain_latest AS
WITH latest_date AS (
    SELECT MAX(as_of_date) AS d FROM nidp.fno_bhavcopy
)
SELECT
    f.as_of_date,
    f.ticker_symbol,
    f.expiry_date,
    f.strike_price,
    MAX(CASE WHEN f.option_type = 'CE' THEN f.close_price END)        AS ce_close,
    MAX(CASE WHEN f.option_type = 'CE' THEN f.open_interest END)      AS ce_oi,
    MAX(CASE WHEN f.option_type = 'CE' THEN f.change_in_oi END)       AS ce_chg_oi,
    MAX(CASE WHEN f.option_type = 'CE' THEN f.traded_volume END)      AS ce_vol,
    MAX(CASE WHEN f.option_type = 'PE' THEN f.close_price END)        AS pe_close,
    MAX(CASE WHEN f.option_type = 'PE' THEN f.open_interest END)      AS pe_oi,
    MAX(CASE WHEN f.option_type = 'PE' THEN f.change_in_oi END)       AS pe_chg_oi,
    MAX(CASE WHEN f.option_type = 'PE' THEN f.traded_volume END)      AS pe_vol,
    MAX(f.underlying_price)                                            AS underlying_price
  FROM nidp.fno_bhavcopy f
  JOIN latest_date d ON f.as_of_date = d.d
 WHERE f.option_type IN ('CE','PE')
 GROUP BY f.as_of_date, f.ticker_symbol, f.expiry_date, f.strike_price;


DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.fno_bhavcopy', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('028_nidp_fno_bhavcopy.sql')
    ON CONFLICT (filename) DO NOTHING;
