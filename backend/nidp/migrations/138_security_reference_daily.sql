-- 138_security_reference_daily.sql
--
-- Three NSE reference lists that decide whether a 10% day is even possible, none
-- of which NIDP stored: a stock in a 5% price band cannot move 10%, F&O stocks
-- have no fixed band, and ETFs trade in the EQ series but are not companies (350
-- of them sat inside the "next 500 by turnover" universe).
--
-- One row per symbol per day, so a past day keeps that day's band — bands are
-- revised weekly by surveillance, and today's band copied onto history would be
-- look-ahead.
--
--   price_band_pct  2 / 5 / 10 / 20 from content/equities/sec_list.csv;
--                   NULL when NSE lists 'No Band'
--   fno_eligible    symbol in content/fo/fo_mktlots.csv (index rows excluded)
--   is_etf          symbol in content/equities/eq_etfseclist.csv
--
-- Re-runnable.

CREATE TABLE IF NOT EXISTS nidp.security_reference_daily (
    as_of_date      DATE         NOT NULL,
    symbol          TEXT         NOT NULL,
    series          TEXT,
    price_band_pct  NUMERIC(5,2),
    band_raw        TEXT,
    fno_eligible    BOOLEAN      NOT NULL DEFAULT FALSE,
    is_etf          BOOLEAN      NOT NULL DEFAULT FALSE,
    source_run_id   UUID,
    ingested_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, symbol)
);

CREATE INDEX IF NOT EXISTS idx_security_reference_daily_symbol
    ON nidp.security_reference_daily (symbol, as_of_date DESC);

COMMENT ON TABLE nidp.security_reference_daily IS
  'Daily point-in-time NSE reference flags: price band (sec_list.csv), F&O eligibility (fo_mktlots.csv), ETF (eq_etfseclist.csv)';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('138_security_reference_daily.sql')
ON CONFLICT (filename) DO NOTHING;
