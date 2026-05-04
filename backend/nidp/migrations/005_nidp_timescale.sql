-- 005_nidp_timescale.sql — Convert time-series tables into TimescaleDB
-- hypertables. Idempotent + degrades gracefully if the timescaledb
-- extension is not installed (validation/dev environments without
-- Timescale still work; we lose chunk pruning + compression but the
-- schema is unchanged).
--
-- Tables converted (per the production-stack decision):
--   prices_eod        — partition on as_of_date
--   delivery_data     — partition on as_of_date
--   index_eod         — partition on as_of_date
--   fii_dii_flows     — partition on as_of_date
--   bulk_deals        — partition on as_of_date
--   block_deals       — partition on as_of_date
--   rbi_yields        — partition on as_of_date
--
-- Not converted (low cardinality / event-driven, no benefit):
--   index_constituents (effective-dated, low row count)
--   corporate_actions  (event-driven, indexed by ex_date)
--   nse_holidays       (annual)
--   daily_snapshot     (one row/day; index is enough)
--   job_log, raw_archive_files, source_registry  (operational tables)
--
-- Chunk interval: 1 month for price-level data is the Timescale default
-- recommendation for ~10M rows/chunk class. Adjust later via
-- set_chunk_time_interval() if profile shows otherwise.

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        -- prices_eod
        PERFORM create_hypertable(
            'nidp.prices_eod', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- delivery_data
        PERFORM create_hypertable(
            'nidp.delivery_data', 'as_of_date',
            chunk_time_interval => INTERVAL '1 month',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- index_eod
        PERFORM create_hypertable(
            'nidp.index_eod', 'as_of_date',
            chunk_time_interval => INTERVAL '3 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- fii_dii_flows
        PERFORM create_hypertable(
            'nidp.fii_dii_flows', 'as_of_date',
            chunk_time_interval => INTERVAL '3 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- bulk_deals
        PERFORM create_hypertable(
            'nidp.bulk_deals', 'as_of_date',
            chunk_time_interval => INTERVAL '3 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- block_deals
        PERFORM create_hypertable(
            'nidp.block_deals', 'as_of_date',
            chunk_time_interval => INTERVAL '3 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
        -- rbi_yields
        PERFORM create_hypertable(
            'nidp.rbi_yields', 'as_of_date',
            chunk_time_interval => INTERVAL '6 months',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );

        RAISE NOTICE 'TimescaleDB hypertables created/verified.';
    ELSE
        RAISE NOTICE 'timescaledb extension not installed — skipping hypertable creation. Plain PG tables remain functional.';
    END IF;
END $$;

INSERT INTO nidp.schema_migrations(filename) VALUES ('005_nidp_timescale.sql')
    ON CONFLICT (filename) DO NOTHING;
