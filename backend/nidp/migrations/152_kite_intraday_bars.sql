-- 152: intraday OHLCV bars from Kite Connect.
--
-- Unblocks the gap-down sleeve's G2-G5 entry variants and the intraday exit matrix, which
-- daily bhavcopy cannot resolve. NIDP held no intraday table before this (verified: no
-- CREATE TABLE matched intraday/minute/tick; analytics.market_snapshot is one row per day).
--
-- source_version stamps every row so a later vendor switch does not contaminate a training
-- set: a model can select the source it trusts instead of silently mixing feeds.

CREATE TABLE IF NOT EXISTS nidp.intraday_bars (
    instrument_token  BIGINT       NOT NULL,
    symbol            TEXT         NOT NULL,
    exchange          TEXT         NOT NULL DEFAULT 'NSE',
    bar_ts            TIMESTAMPTZ  NOT NULL,           -- candle OPEN time, IST offset preserved
    interval          TEXT         NOT NULL,           -- minute | 5minute | 15minute | 60minute | day
    open_price        NUMERIC(18,4) NOT NULL,
    high_price        NUMERIC(18,4) NOT NULL,
    low_price         NUMERIC(18,4) NOT NULL,
    close_price       NUMERIC(18,4) NOT NULL,
    volume            BIGINT,
    source            TEXT         NOT NULL DEFAULT 'KITE',
    source_version    TEXT         NOT NULL,           -- e.g. kite-connect-v3
    ingested_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    PRIMARY KEY (instrument_token, interval, bar_ts),
    CHECK (high_price >= low_price),
    CHECK (open_price > 0 AND close_price > 0)
);

CREATE INDEX IF NOT EXISTS idx_intraday_bars_symbol_ts
    ON nidp.intraday_bars (symbol, interval, bar_ts DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_bars_date
    ON nidp.intraday_bars (interval, (bar_ts AT TIME ZONE 'Asia/Kolkata')::date);

-- Auditable ingestion record: which symbol/day/interval was attempted, and what happened.
-- Absence of a bar row is then distinguishable from "never fetched" vs "fetched, no trades".
CREATE TABLE IF NOT EXISTS nidp.intraday_ingest_log (
    id             BIGSERIAL PRIMARY KEY,
    symbol         TEXT        NOT NULL,
    interval       TEXT        NOT NULL,
    window_start   DATE        NOT NULL,
    window_end     DATE        NOT NULL,
    status         TEXT        NOT NULL,               -- OK | EMPTY | ERROR
    rows_written   INTEGER     NOT NULL DEFAULT 0,
    error_text     TEXT,
    source_version TEXT        NOT NULL,
    run_id         TEXT        NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('OK','EMPTY','ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_intraday_ingest_log_run ON nidp.intraday_ingest_log (run_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intraday_ingest_log_window
    ON nidp.intraday_ingest_log (symbol, interval, window_start, window_end, run_id);
