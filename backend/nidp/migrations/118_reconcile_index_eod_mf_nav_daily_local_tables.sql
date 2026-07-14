-- 118_reconcile_index_eod_mf_nav_daily_local_tables.sql
--
-- Restore nidp.index_eod, nidp.mf_nav_daily and nidp.mf_scheme_master as REAL
-- LOCAL TABLES.
--
-- WHY
-- ---
-- On prod these three names had drifted to VIEWS over postgres_fdw foreign tables
-- (search_path = prod_data,nidp,public; the views read `FROM index_eod` /
-- `FROM mf_nav_daily`, which resolve to prod_data.* foreign tables backed by a
-- remote nidp DB). The ingesters write with:
--     INSERT INTO nidp.index_eod    ... ON CONFLICT (as_of_date, index_name, source)
--     INSERT INTO nidp.mf_nav_daily ... ON CONFLICT (scheme_code, nav_date, source)
-- You cannot upsert through a view over a foreign table, so every run raised
--     InvalidColumnReferenceError: there is no unique or exclusion constraint
--     matching the ON CONFLICT specification
-- and both feeds NEVER wrote a row (index_close: 57 consecutive failures;
-- amfi_nav: 21). This restores the canonical tables (migrations 002 / 034) whose
-- PRIMARY KEY is exactly the writers' ON CONFLICT target, and migrates the
-- currently-federated rows in so historical reads survive the cutover.
--
-- This SEVERS the FDW read-federation for these two names (by design — see the
-- PR discussion). Readers use the nidp.* qualified names, which now resolve to
-- the local tables. The prod_data.* / prod_nidp.* foreign tables are left intact
-- (harmless) and can be dropped in a follow-up once reads are confirmed.
--
-- SAFETY
-- ------
-- * Idempotent / re-runnable: each block acts ONLY when the object is currently a
--   VIEW. If it is already a table (e.g. on staging, or on a second run), the
--   block is a no-op.
-- * Snapshot-then-swap: the federated rows are copied into a TEMP table BEFORE the
--   view is dropped, so a failure (e.g. FDW unreachable) aborts with the view
--   still in place — no data window is lost.
-- * ON CONFLICT DO NOTHING on the reseed tolerates any duplicate the ingester may
--   have written between snapshot and swap.
--
-- ROLLBACK (manual): DROP the tables and recreate the two views, e.g.
--     DROP TABLE nidp.index_eod;
--     CREATE VIEW nidp.index_eod AS SELECT <cols> FROM index_eod;   -- prod_data foreign table
--   (same for mf_nav_daily). Only do this to revert to the federated read layer.

DO $mig$
DECLARE
    _kind "char";
    _n    bigint;
BEGIN
    ---------------------------------------------------------------- index_eod --
    SELECT c.relkind INTO _kind
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'nidp' AND c.relname = 'index_eod';

    IF _kind = 'v' THEN
        CREATE TEMP TABLE _idx_seed ON COMMIT DROP AS
            SELECT as_of_date, index_name, open_price, high_price, low_price,
                   close_price, pe_ratio, pb_ratio, div_yield, pts_change,
                   pct_change, volume, turnover, source, source_run_id, ingested_at
              FROM nidp.index_eod;

        DROP VIEW nidp.index_eod;

        CREATE TABLE nidp.index_eod (
            as_of_date      DATE NOT NULL,
            index_name      TEXT NOT NULL,
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
            source          TEXT NOT NULL,
            source_run_id   UUID NOT NULL,
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (as_of_date, index_name, source)   -- == writer ON CONFLICT
        );

        INSERT INTO nidp.index_eod
            (as_of_date, index_name, open_price, high_price, low_price,
             close_price, pe_ratio, pb_ratio, div_yield, pts_change,
             pct_change, volume, turnover, source, source_run_id, ingested_at)
        SELECT as_of_date, index_name, open_price, high_price, low_price,
               close_price, pe_ratio, pb_ratio, div_yield, pts_change,
               pct_change, volume, turnover, source, source_run_id, ingested_at
          FROM _idx_seed
        ON CONFLICT (as_of_date, index_name, source) DO NOTHING;

        CREATE INDEX IF NOT EXISTS idx_index_eod_name_date
            ON nidp.index_eod (index_name, as_of_date DESC);

        SELECT count(*) INTO _n FROM nidp.index_eod;
        RAISE NOTICE '118: nidp.index_eod restored as TABLE, % rows migrated', _n;
    ELSE
        RAISE NOTICE '118: nidp.index_eod relkind=% (not a view) — skipped', COALESCE(_kind::text, 'MISSING');
    END IF;

    ------------------------------------------------------------- mf_nav_daily --
    SELECT c.relkind INTO _kind
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'nidp' AND c.relname = 'mf_nav_daily';

    IF _kind = 'v' THEN
        CREATE TEMP TABLE _nav_seed ON COMMIT DROP AS
            SELECT scheme_code, nav_date, nav, repurchase_nav, sale_nav,
                   source, source_run_id, ingested_at
              FROM nidp.mf_nav_daily;

        DROP VIEW nidp.mf_nav_daily;

        CREATE TABLE nidp.mf_nav_daily (
            scheme_code     TEXT NOT NULL,
            nav_date        DATE NOT NULL,
            nav             NUMERIC(14,4) NOT NULL,
            repurchase_nav  NUMERIC(14,4),
            sale_nav        NUMERIC(14,4),
            source          TEXT NOT NULL,
            source_run_id   UUID NOT NULL,
            ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (scheme_code, nav_date, source)    -- == writer ON CONFLICT
        );

        INSERT INTO nidp.mf_nav_daily
            (scheme_code, nav_date, nav, repurchase_nav, sale_nav,
             source, source_run_id, ingested_at)
        SELECT scheme_code, nav_date, nav, repurchase_nav, sale_nav,
               source, source_run_id, ingested_at
          FROM _nav_seed
        ON CONFLICT (scheme_code, nav_date, source) DO NOTHING;

        CREATE INDEX IF NOT EXISTS idx_mf_nav_daily_scheme_date
            ON nidp.mf_nav_daily (scheme_code, nav_date DESC);
        CREATE INDEX IF NOT EXISTS idx_mf_nav_daily_date
            ON nidp.mf_nav_daily (nav_date DESC, scheme_code);

        SELECT count(*) INTO _n FROM nidp.mf_nav_daily;
        RAISE NOTICE '118: nidp.mf_nav_daily restored as TABLE, % rows migrated', _n;
    ELSE
        RAISE NOTICE '118: nidp.mf_nav_daily relkind=% (not a view) — skipped', COALESCE(_kind::text, 'MISSING');
    END IF;

    --------------------------------------------------------- mf_scheme_master --
    -- amfi_nav also upserts nidp.mf_scheme_master ON CONFLICT (scheme_code), and
    -- on prod this too had drifted to a view (relkind confirmed 'v'), so amfi_nav
    -- fails on the scheme upsert before it ever reaches mf_nav_daily. Restore it
    -- per migration 034 (all 15 columns confirmed identical on prod).
    SELECT c.relkind INTO _kind
      FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'nidp' AND c.relname = 'mf_scheme_master';

    IF _kind = 'v' THEN
        CREATE TEMP TABLE _sm_seed ON COMMIT DROP AS
            SELECT scheme_code, scheme_name, amc_id, amc_name_raw, isin_growth,
                   isin_idcw, scheme_type, scheme_category, benchmark_id,
                   launch_date, status, latest_nav, latest_nav_date,
                   first_seen_at, updated_at
              FROM nidp.mf_scheme_master;

        DROP VIEW nidp.mf_scheme_master;

        CREATE TABLE nidp.mf_scheme_master (
            scheme_code        TEXT PRIMARY KEY,          -- == writer ON CONFLICT
            scheme_name        TEXT NOT NULL,
            amc_id             TEXT,
            amc_name_raw       TEXT,
            isin_growth        TEXT,
            isin_idcw          TEXT,
            scheme_type        TEXT,
            scheme_category    TEXT,
            benchmark_id       TEXT,
            launch_date        DATE,
            status             TEXT NOT NULL DEFAULT 'active',
            latest_nav         NUMERIC(14,4),
            latest_nav_date    DATE,
            first_seen_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        INSERT INTO nidp.mf_scheme_master
            (scheme_code, scheme_name, amc_id, amc_name_raw, isin_growth,
             isin_idcw, scheme_type, scheme_category, benchmark_id,
             launch_date, status, latest_nav, latest_nav_date,
             first_seen_at, updated_at)
        SELECT scheme_code, scheme_name, amc_id, amc_name_raw, isin_growth,
               isin_idcw, scheme_type, scheme_category, benchmark_id,
               launch_date, COALESCE(status,'active'), latest_nav, latest_nav_date,
               COALESCE(first_seen_at, NOW()), COALESCE(updated_at, NOW())
          FROM _sm_seed
        ON CONFLICT (scheme_code) DO NOTHING;

        -- FK + CHECK added NOT VALID: enforced for new ingester upserts, but not
        -- retro-validated, so any legacy orphan amc_id / off-enum status doesn't
        -- block the cutover. mf_amc_master is a real table on prod (relkind 'r').
        ALTER TABLE nidp.mf_scheme_master
            ADD CONSTRAINT mf_scheme_master_amc_id_fkey
            FOREIGN KEY (amc_id) REFERENCES nidp.mf_amc_master(amc_id) NOT VALID;
        ALTER TABLE nidp.mf_scheme_master
            ADD CONSTRAINT mf_scheme_master_status_check
            CHECK (status IN ('active','closed','merged','suspended')) NOT VALID;

        CREATE INDEX IF NOT EXISTS idx_mf_scheme_master_amc
            ON nidp.mf_scheme_master (amc_id);

        SELECT count(*) INTO _n FROM nidp.mf_scheme_master;
        RAISE NOTICE '118: nidp.mf_scheme_master restored as TABLE, % rows migrated', _n;
    ELSE
        RAISE NOTICE '118: nidp.mf_scheme_master relkind=% (not a view) — skipped', COALESCE(_kind::text, 'MISSING');
    END IF;
END
$mig$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('118_reconcile_index_eod_mf_nav_daily_local_tables.sql')
ON CONFLICT (filename) DO NOTHING;
