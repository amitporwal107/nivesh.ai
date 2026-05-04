-- 002_nidp_market_data.sql — Market data tables (PRD §10).
--
-- Covers P0 rows 1.3, 1.4, 1.5, 1.6 from the locked source list:
--   prices_eod          — NSE bhavcopy (per-stock OHLCV)
--   delivery_data       — NSE sec_bhavdata_full (delivery %)
--   index_eod           — NSE ind_close_all (index OHLCV + ratios)
--   index_constituents  — NSE per-index constituent list (effective-dated)
--
-- Append-only by (as_of_date, symbol/index, source). PK includes
-- `source` so multiple feeds (NSE primary, BSE/yfinance backup) can
-- coexist; reconciliation is a downstream concern.

SET search_path TO nidp, public;

-- ── prices_eod ──────────────────────────────────────────────────────
-- One row per (date, symbol, series, source).
-- Field names mirror NSE bhavcopy headers (post-Jul-2024 format) so
-- the parser is a near-1:1 copy.
CREATE TABLE IF NOT EXISTS nidp.prices_eod (
    as_of_date      DATE NOT NULL,                   -- TradDt from bhavcopy
    symbol          TEXT NOT NULL,                   -- TckrSymb
    series          TEXT NOT NULL,                   -- SctySrs (EQ | BE | BZ | …)
    isin            TEXT,                            -- ISIN
    prev_close      NUMERIC(14,4),                   -- PrvsClsgPric
    open_price      NUMERIC(14,4),                   -- OpnPric
    high_price      NUMERIC(14,4),                   -- HghPric
    low_price       NUMERIC(14,4),                   -- LwPric
    close_price     NUMERIC(14,4),                   -- ClsgPric
    last_price      NUMERIC(14,4),                   -- LastPric
    avg_price       NUMERIC(14,4),                   -- VWAP / AvgPric
    volume          BIGINT,                          -- TtlTradgVol
    turnover        NUMERIC(20,4),                   -- TtlTrfVal (rupees)
    trades          BIGINT,                          -- TtlNbOfTxsExctd
    deliv_qty       BIGINT,                          -- nullable; populated when delivery merged
    deliv_pct       NUMERIC(7,4),                    -- nullable; populated when delivery merged
    source          TEXT NOT NULL,                   -- 'NSE_BHAVCOPY' | 'BSE_BHAVCOPY'
    source_run_id   UUID NOT NULL,                   -- → nidp.job_log.run_id
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, symbol, series, source)
);

CREATE INDEX IF NOT EXISTS idx_prices_eod_symbol_date
    ON nidp.prices_eod(symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_prices_eod_date
    ON nidp.prices_eod(as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_prices_eod_isin_date
    ON nidp.prices_eod(isin, as_of_date DESC) WHERE isin IS NOT NULL;


-- ── delivery_data ───────────────────────────────────────────────────
-- Stored separately from prices_eod because:
--   (a) it lands T+1 (next morning), not T+0
--   (b) it's a different source file (sec_bhavdata_full)
-- The two are merged into prices_eod.deliv_qty/pct by a join job once
-- both are present for a given date.
CREATE TABLE IF NOT EXISTS nidp.delivery_data (
    as_of_date      DATE NOT NULL,
    symbol          TEXT NOT NULL,
    series          TEXT NOT NULL,
    traded_qty      BIGINT,                          -- TTL_TRD_QNTY (cross-check vs prices_eod.volume)
    deliverable_qty BIGINT,                          -- DELIV_QTY
    deliverable_pct NUMERIC(7,4),                    -- DELIV_PER
    source          TEXT NOT NULL,                   -- 'NSE_SEC_BHAVDATA'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, symbol, series, source)
);

CREATE INDEX IF NOT EXISTS idx_delivery_symbol_date
    ON nidp.delivery_data(symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_delivery_date
    ON nidp.delivery_data(as_of_date DESC);


-- ── index_eod ───────────────────────────────────────────────────────
-- NSE ind_close_all gives daily OHLC + PE/PB/Div Yield per index.
CREATE TABLE IF NOT EXISTS nidp.index_eod (
    as_of_date      DATE NOT NULL,
    index_name      TEXT NOT NULL,                   -- 'Nifty 50' | 'Nifty Bank' | 'Nifty IT' | …
    open_price      NUMERIC(14,4),
    high_price      NUMERIC(14,4),
    low_price       NUMERIC(14,4),
    close_price     NUMERIC(14,4),
    pe_ratio        NUMERIC(10,4),
    pb_ratio        NUMERIC(10,4),
    div_yield       NUMERIC(10,4),
    pts_change      NUMERIC(14,4),
    pct_change      NUMERIC(10,4),
    volume          BIGINT,
    turnover        NUMERIC(20,4),
    source          TEXT NOT NULL,                   -- 'NSE_IND_CLOSE'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, index_name, source)
);

CREATE INDEX IF NOT EXISTS idx_index_eod_name_date
    ON nidp.index_eod(index_name, as_of_date DESC);


-- ── index_constituents ──────────────────────────────────────────────
-- Effective-dated constituent membership. `as_of_date` is the date
-- this membership row is *valid from*. New rebalance writes a new
-- as_of_date with the new full constituent list — old rows remain so
-- historical universe queries are deterministic.
CREATE TABLE IF NOT EXISTS nidp.index_constituents (
    as_of_date      DATE NOT NULL,
    index_name      TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    isin            TEXT,
    company_name    TEXT,
    industry        TEXT,
    weight_pct      NUMERIC(7,4),                    -- nullable; not all NSE files publish weights
    source          TEXT NOT NULL,                   -- 'NSE_INDEX_LIST'
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, index_name, symbol, source)
);

CREATE INDEX IF NOT EXISTS idx_constituents_index_date
    ON nidp.index_constituents(index_name, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_constituents_symbol
    ON nidp.index_constituents(symbol);


INSERT INTO nidp.schema_migrations(filename) VALUES ('002_nidp_market_data.sql')
    ON CONFLICT (filename) DO NOTHING;
