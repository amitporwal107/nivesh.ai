-- 008_nidp_fred_macro.sql — Global macro indicators from FRED.
--
-- FRED (Federal Reserve Economic Data) is the authoritative public
-- source for US/global macro time series. Free API, no key required
-- for public series. We pull a curated set of cross-asset signals
-- the regime engine consumes:
--
--   DGS10        US 10-year Treasury yield (daily)
--   DGS2         US 2-year Treasury yield (daily)
--   DTWEXBGS     US dollar trade-weighted index (daily)
--   DCOILBRENTEU Brent crude spot (daily)
--   DCOILWTICO   WTI crude spot (daily)
--   VIXCLS       CBOE VIX (daily)
--   GOLDAMGBD228NLBM  Gold London PM fix (daily)
--   FEDFUNDS     Federal Funds rate (monthly)
--
-- Long-form: one row per (series_id, as_of_date, source).

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.fred_macro (
    as_of_date      DATE NOT NULL,
    series_id       TEXT NOT NULL,                   -- DGS10, VIXCLS, etc.
    series_name     TEXT,                            -- human label
    value           NUMERIC(16,4),                   -- nullable; FRED uses '.' for missing
    units           TEXT,                            -- 'Percent', 'Index', 'USD per Barrel', etc.
    frequency       TEXT,                            -- 'Daily', 'Weekly', 'Monthly'
    source          TEXT NOT NULL DEFAULT 'FRED',
    source_run_id   UUID NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (as_of_date, series_id, source)
);

CREATE INDEX IF NOT EXISTS idx_fred_macro_series_date
    ON nidp.fred_macro(series_id, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_fred_macro_date
    ON nidp.fred_macro(as_of_date DESC);

-- TimescaleDB hypertable for the time series
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.fred_macro', 'as_of_date',
            chunk_time_interval => INTERVAL '6 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;

INSERT INTO nidp.schema_migrations(filename) VALUES ('008_nidp_fred_macro.sql')
    ON CONFLICT (filename) DO NOTHING;
