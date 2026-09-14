-- One-off insert of CSVs built by backfill_sec_bhavdata_archive.py into nidp.prices_eod / nidp.delivery_data.
--
-- Additive only: every staged row must be strictly older than the cut-offs, inserts use ON CONFLICT DO
-- NOTHING, and the transaction aborts if any pre-existing row's fingerprint changed. Runs inside the
-- postgres container with the CSVs copied to /tmp/bf_prices_eod.csv and /tmp/bf_delivery_data.csv.
--
--   docker exec -i nidp-postgres-staging psql -U nidp_staging -d nidp_staging \
--     -v prices_before=2025-01-01 -v delivery_before=2025-02-01 -v run_id=<uuid> -v apply=0 \
--     < backfill_sec_bhavdata_archive.sql
--
-- apply=0 rolls back (dry run); apply=1 commits.
\set ON_ERROR_STOP on
\pset format unaligned
\pset fieldsep ' | '
\pset footer off
BEGIN;

CREATE TEMP TABLE bf_prices (LIKE nidp.prices_eod INCLUDING DEFAULTS) ON COMMIT DROP;
CREATE TEMP TABLE bf_delivery (LIKE nidp.delivery_data INCLUDING DEFAULTS) ON COMMIT DROP;
-- LIKE copies NOT NULL on source_run_id; the CSVs don't carry it, so default it to this run.
ALTER TABLE bf_prices ALTER COLUMN source_run_id SET DEFAULT :'run_id'::uuid, ALTER COLUMN ingested_at SET DEFAULT now();
ALTER TABLE bf_delivery ALTER COLUMN source_run_id SET DEFAULT :'run_id'::uuid, ALTER COLUMN ingested_at SET DEFAULT now();
\copy bf_prices (as_of_date, symbol, series, isin, prev_close, open_price, high_price, low_price, close_price, last_price, avg_price, volume, turnover, trades, deliv_qty, deliv_pct, source) FROM '/tmp/bf_prices_eod.csv' CSV HEADER
\copy bf_delivery (as_of_date, symbol, series, traded_qty, deliverable_qty, deliverable_pct, source) FROM '/tmp/bf_delivery_data.csv' CSV HEADER

SELECT 'staged' AS step, (SELECT count(*) FROM bf_prices) AS prices_rows, (SELECT count(*) FROM bf_delivery) AS delivery_rows;

-- Guard 1: nothing staged at or after the cut-offs, and only the archive's own source label.
SELECT (SELECT count(*) FROM bf_prices WHERE as_of_date >= :'prices_before'::date OR source <> 'NSE_SEC_BHAVDATA')
     + (SELECT count(*) FROM bf_delivery WHERE as_of_date >= :'delivery_before'::date OR source <> 'NSE_SEC_BHAVDATA')
       > 0 AS guard_failed \gset
\if :guard_failed
  \echo 'GUARD FAILED: staged rows at/after cut-off or with an unexpected source'
  ROLLBACK;
  \quit 3
\endif

-- Fingerprint every pre-existing row before inserting.
CREATE TEMP TABLE fp_before ON COMMIT DROP AS
SELECT 'prices_eod' AS t, count(*) AS n,
       sum(hashtextextended(as_of_date::text||symbol||series||source||coalesce(close_price::text,'')||coalesce(volume::text,'')||coalesce(deliv_pct::text,'')||coalesce(ingested_at::text,''),0)::numeric) AS fp
  FROM nidp.prices_eod
UNION ALL
SELECT 'delivery_data', count(*),
       sum(hashtextextended(as_of_date::text||symbol||series||source||coalesce(deliverable_qty::text,'')||coalesce(deliverable_pct::text,'')||coalesce(ingested_at::text,''),0)::numeric)
  FROM nidp.delivery_data;

WITH ins AS (
  INSERT INTO nidp.prices_eod (as_of_date, symbol, series, isin, prev_close, open_price, high_price, low_price,
         close_price, last_price, avg_price, volume, turnover, trades, deliv_qty, deliv_pct, source, source_run_id, ingested_at)
  SELECT as_of_date, symbol, series, isin, prev_close, open_price, high_price, low_price,
         close_price, last_price, avg_price, volume, turnover, trades, deliv_qty, deliv_pct, source, source_run_id, ingested_at
    FROM bf_prices
  ON CONFLICT DO NOTHING
  RETURNING 1)
SELECT 'inserted prices_eod' AS step, count(*) AS rows FROM ins;

WITH ins AS (
  INSERT INTO nidp.delivery_data (as_of_date, symbol, series, traded_qty, deliverable_qty, deliverable_pct, source, source_run_id, ingested_at)
  SELECT as_of_date, symbol, series, traded_qty, deliverable_qty, deliverable_pct, source, source_run_id, ingested_at
    FROM bf_delivery
  ON CONFLICT DO NOTHING
  RETURNING 1)
SELECT 'inserted delivery_data' AS step, count(*) AS rows FROM ins;

-- Guard 2: the pre-existing rows are byte-for-byte what they were.
SELECT count(*) > 0 AS existing_changed FROM (
  SELECT 'prices_eod' AS t, count(*) AS n,
         sum(hashtextextended(as_of_date::text||symbol||series||source||coalesce(close_price::text,'')||coalesce(volume::text,'')||coalesce(deliv_pct::text,'')||coalesce(ingested_at::text,''),0)::numeric) AS fp
    FROM nidp.prices_eod WHERE source_run_id IS DISTINCT FROM :'run_id'::uuid
  UNION ALL
  SELECT 'delivery_data', count(*),
         sum(hashtextextended(as_of_date::text||symbol||series||source||coalesce(deliverable_qty::text,'')||coalesce(deliverable_pct::text,'')||coalesce(ingested_at::text,''),0)::numeric)
    FROM nidp.delivery_data WHERE source_run_id IS DISTINCT FROM :'run_id'::uuid
  EXCEPT SELECT t, n, fp FROM fp_before
) d \gset
\if :existing_changed
  \echo 'GUARD FAILED: a pre-existing row changed'
  ROLLBACK;
  \quit 4
\endif
SELECT 'existing rows unchanged' AS step, t, n FROM fp_before ORDER BY t;

SELECT 'result' AS step, source, count(*) AS rows, min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) AS sessions
  FROM nidp.prices_eod WHERE source_run_id = :'run_id'::uuid GROUP BY source;
SELECT 'result delivery' AS step, source, count(*) AS rows, min(as_of_date), max(as_of_date), count(DISTINCT as_of_date) AS sessions
  FROM nidp.delivery_data WHERE source_run_id = :'run_id'::uuid GROUP BY source;

\if :apply
  COMMIT;
  \echo 'COMMITTED'
\else
  ROLLBACK;
  \echo 'DRY RUN — rolled back'
\endif
