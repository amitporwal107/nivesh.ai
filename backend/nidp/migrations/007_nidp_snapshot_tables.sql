-- 007_nidp_snapshot_tables.sql — The Snapshot Layer.
--
-- This is the AS-OF coherence substrate the PRD §9 calls for. Two
-- tables, both append-only by `as_of_date`:
--
--   market_daily_snapshot  — one row per date (market-wide facts)
--   stock_daily_snapshot   — one row per (symbol, date)
--
-- Build rule: a snapshot for date D is only constructed when
-- nidp.daily_snapshot.snapshot_status = READY for that date AND no
-- validation_findings with failure_class='BLOCK' exist for D.
--
-- Carry-forward semantics live in the snapshot_builder service. The
-- table itself records the *as-of dates* of each carried-forward
-- domain so consumers know exactly how stale each input is.

SET search_path TO nidp, public;


-- ── Market-level daily snapshot ────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.market_daily_snapshot (
    as_of_date              DATE PRIMARY KEY,

    -- Headline indices (joined from nidp.index_eod)
    nifty50_close           NUMERIC(14,4),
    nifty50_pct_change      NUMERIC(10,4),
    nifty500_close          NUMERIC(14,4),
    bank_nifty_close        NUMERIC(14,4),
    india_vix               NUMERIC(10,4),

    -- FII/DII (joined from nidp.fii_dii_flows)
    fii_cash_net_cr         NUMERIC(16,4),
    dii_cash_net_cr         NUMERIC(16,4),
    fii_fno_index_net_cr    NUMERIC(16,4),
    dii_fno_index_net_cr    NUMERIC(16,4),

    -- Rates (joined from nidp.rbi_yields)
    rbi_10y_yield           NUMERIC(8,4),
    rbi_91d_yield           NUMERIC(8,4),

    -- Market breadth (computed from prices_eod)
    advances_count          INTEGER,
    declines_count          INTEGER,
    unchanged_count         INTEGER,
    total_traded_value_cr   NUMERIC(16,4),
    total_traded_volume     BIGINT,

    -- Carry-forward bookkeeping (PRD §9 — never silently pretend
    -- data is current). For each input domain, record the actual
    -- as_of_date used.
    prices_as_of            DATE,
    fii_dii_as_of           DATE,
    yields_as_of            DATE,
    index_as_of             DATE,

    -- Build provenance
    build_run_id            UUID NOT NULL,           -- → nidp.job_log.run_id
    built_at                TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_market_snap_built
    ON nidp.market_daily_snapshot(built_at DESC);


-- ── Per-stock daily snapshot ───────────────────────────────────────
-- One row per (symbol, series, date). EQ-only by default; BE/BZ rows
-- are also written but flagged via series.
CREATE TABLE IF NOT EXISTS nidp.stock_daily_snapshot (
    symbol                  TEXT NOT NULL,
    as_of_date              DATE NOT NULL,
    series                  TEXT NOT NULL,
    isin                    TEXT,

    -- OHLCV (from nidp.prices_eod)
    open_price              NUMERIC(14,4),
    high_price              NUMERIC(14,4),
    low_price               NUMERIC(14,4),
    close_price             NUMERIC(14,4),
    prev_close              NUMERIC(14,4),
    volume                  BIGINT,
    turnover                NUMERIC(20,4),
    trades                  BIGINT,

    -- Returns (computed)
    return_1d_pct           NUMERIC(10,4),

    -- Delivery (from nidp.delivery_data — may be NULL on D when
    -- delivery hasn't landed yet)
    deliv_qty               BIGINT,
    deliv_pct               NUMERIC(7,4),

    -- Index membership (from nidp.index_constituents, latest as-of)
    in_nifty50              BOOLEAN NOT NULL DEFAULT FALSE,
    in_nifty100             BOOLEAN NOT NULL DEFAULT FALSE,
    in_nifty500             BOOLEAN NOT NULL DEFAULT FALSE,
    industry                TEXT,

    -- Deal activity (joined from nidp.bulk_deals + nidp.block_deals)
    bulk_deal_count         INTEGER NOT NULL DEFAULT 0,
    bulk_buy_qty            BIGINT  NOT NULL DEFAULT 0,
    bulk_sell_qty           BIGINT  NOT NULL DEFAULT 0,
    block_deal_count        INTEGER NOT NULL DEFAULT 0,
    block_buy_qty           BIGINT  NOT NULL DEFAULT 0,
    block_sell_qty          BIGINT  NOT NULL DEFAULT 0,

    -- Corporate actions (any with ex_date in next 7 trading days?)
    has_upcoming_ca         BOOLEAN NOT NULL DEFAULT FALSE,
    upcoming_ca_types       TEXT[],                   -- ['DIVIDEND','SPLIT'] etc.

    -- Carry-forward bookkeeping
    prices_as_of            DATE,                     -- typically = as_of_date
    delivery_as_of          DATE,                     -- may lag by 1 day
    constituents_as_of      DATE,
    -- (Quarterly fields like shareholding/financials are NULL for now;
    --  added when those ingesters land.)

    -- Build provenance
    build_run_id            UUID NOT NULL,
    built_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, as_of_date, series)
);

CREATE INDEX IF NOT EXISTS idx_stock_snap_date
    ON nidp.stock_daily_snapshot(as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_snap_symbol_date
    ON nidp.stock_daily_snapshot(symbol, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_snap_nifty500
    ON nidp.stock_daily_snapshot(as_of_date, symbol)
    WHERE in_nifty500;
CREATE INDEX IF NOT EXISTS idx_stock_snap_nifty50
    ON nidp.stock_daily_snapshot(as_of_date, symbol)
    WHERE in_nifty50;
CREATE INDEX IF NOT EXISTS idx_stock_snap_isin_date
    ON nidp.stock_daily_snapshot(isin, as_of_date DESC) WHERE isin IS NOT NULL;


-- ── Convenience views ──────────────────────────────────────────────
-- Nifty 500 rolling view — the universe most signals operate on.
CREATE OR REPLACE VIEW nidp.v_nifty500_daily AS
SELECT * FROM nidp.stock_daily_snapshot
 WHERE in_nifty500;

CREATE OR REPLACE VIEW nidp.v_nifty50_daily AS
SELECT * FROM nidp.stock_daily_snapshot
 WHERE in_nifty50;


-- TimescaleDB hypertable conversion — guarded by extension presence.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.stock_daily_snapshot', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        PERFORM create_hypertable(
            'nidp.market_daily_snapshot', 'as_of_date',
            chunk_time_interval => INTERVAL '6 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('007_nidp_snapshot_tables.sql')
    ON CONFLICT (filename) DO NOTHING;
