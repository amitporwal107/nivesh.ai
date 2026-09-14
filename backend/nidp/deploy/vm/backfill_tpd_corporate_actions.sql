-- Insert the CSV built by backfill_tpd_corporate_actions.py into nidp.tpd_corporate_actions_history (mig 148).
--
-- Model-only table; the shared corporate_actions table must not change (price_adjuster reads it). Runs inside
-- the postgres container with the CSV at /tmp/tpd_ca_history.csv:
--
--   docker exec -i nidp-postgres-staging psql -U nidp_staging -d nidp_staging -v run_id=<uuid> -v apply=0 \
--     < backfill_tpd_corporate_actions.sql
--
-- apply=0 rolls back (dry run); apply=1 commits.
\set ON_ERROR_STOP on
\pset format unaligned
\pset fieldsep ' | '
\pset footer off
BEGIN;

SELECT to_regclass('nidp.tpd_corporate_actions_history') IS NULL AS table_missing \gset
\if :table_missing
  DO $$ BEGIN RAISE EXCEPTION 'nidp.tpd_corporate_actions_history does not exist - apply migration 148 first'; END $$;
\endif

CREATE TEMP TABLE shared_before ON COMMIT DROP AS
SELECT count(*) AS n, max(ingested_at) AS last_ingest FROM nidp.corporate_actions;

CREATE TEMP TABLE bf_ca (LIKE nidp.tpd_corporate_actions_history INCLUDING DEFAULTS) ON COMMIT DROP;
ALTER TABLE bf_ca ALTER COLUMN source_run_id SET DEFAULT :'run_id'::uuid;
\copy bf_ca (symbol, series, action_type, action_subtype, purpose, ratio, face_value_pre, face_value_post, dividend_amount, record_date, ex_date, bc_start_date, bc_end_date, announcement_date, source) FROM '/tmp/tpd_ca_history.csv' CSV HEADER

SELECT count(*) > 0 AS bad_source FROM bf_ca WHERE source <> 'NSE_CA_ARCHIVE' \gset
\if :bad_source
  DO $$ BEGIN RAISE EXCEPTION 'GUARD FAILED: unexpected source label'; END $$;
\endif

WITH ins AS (
  INSERT INTO nidp.tpd_corporate_actions_history
  SELECT * FROM bf_ca
  ON CONFLICT DO NOTHING
  RETURNING action_type)
SELECT 'inserted' AS step, action_type, count(*) AS rows FROM ins GROUP BY action_type ORDER BY rows DESC;

SELECT (SELECT n FROM shared_before) <> (SELECT count(*) FROM nidp.corporate_actions)
    OR (SELECT last_ingest FROM shared_before) IS DISTINCT FROM (SELECT max(ingested_at) FROM nidp.corporate_actions)
       AS shared_changed \gset
\if :shared_changed
  DO $$ BEGIN RAISE EXCEPTION 'GUARD FAILED: shared corporate_actions changed during the load'; END $$;
\endif
SELECT 'shared corporate_actions unchanged' AS step, n FROM shared_before;

\if :apply
  COMMIT;
  \echo 'COMMITTED'
\else
  ROLLBACK;
  \echo 'DRY RUN — rolled back'
\endif
