-- 098_v3_mf_primitives_materialized.sql
--
-- Materialize nidp.v_v3_mf_primitives for fast reads.
--
-- WHY: the plain view ranks the full analytics.fund_category_rank table
-- (~627k rows) on every call, and the scheme_code/ISIN filter does NOT push
-- down through the rank CTEs. A 3-scheme lookup measured ~102,000 ms on
-- staging, so the DaaS /mf/performance/v3-primitives/bulk endpoint hit its
-- query timeout → 500, and Copilot/dashboard requests blocked 10–15s before
-- falling back. Materializing turns the same lookup into a <1ms index scan
-- (measured 0.477 ms on staging).
--
-- REFRESH: nightly, AFTER the MF analytics pipeline updates the underlying
-- tables — wired into services/mf_analytics_engine/service.py run(). REFRESH
-- re-runs the ~110s view query (fine off-peak). Non-concurrent (the view grain
-- has a few dupes on ISIN, so there is no clean unique key for CONCURRENTLY);
-- the brief read-lock during the nightly refresh is acceptable.
--
-- ⚠️ FUTURE MIGRATIONS: v_v3_mf_primitives is now a MATERIALIZED VIEW, not a
-- plain view. Migrations up to 097 rebuilt it with `CREATE OR REPLACE VIEW`,
-- which will now FAIL. To change its columns:
--     DROP MATERIALIZED VIEW nidp.v_v3_mf_primitives;
--     CREATE MATERIALIZED VIEW nidp.v_v3_mf_primitives AS <new select>;
--     CREATE INDEX ... ; -- recreate the indexes below ; then REFRESH.
--
-- SAFE: no DB objects depend on it (checked via pg_depend); only
-- mf_performance.py + v3_scores_engine read it, both as plain SELECTs.
-- Idempotent: re-running skips if already materialized.

SET search_path TO nidp, analytics, public;

DO $$
DECLARE v_def text;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'v_v3_mf_primitives' AND relkind = 'm') THEN
        RAISE NOTICE '098: v_v3_mf_primitives already materialized — skipping conversion';
    ELSIF EXISTS (SELECT 1 FROM pg_class WHERE relname = 'v_v3_mf_primitives' AND relkind = 'v') THEN
        -- capture the CURRENT plain-view definition (post all prior migrations)
        SELECT pg_get_viewdef('nidp.v_v3_mf_primitives'::regclass) INTO v_def;
        EXECUTE 'DROP VIEW nidp.v_v3_mf_primitives';
        EXECUTE 'CREATE MATERIALIZED VIEW nidp.v_v3_mf_primitives AS ' || v_def;
        RAISE NOTICE '098: converted v_v3_mf_primitives to a materialized view';
    ELSE
        RAISE EXCEPTION '098: nidp.v_v3_mf_primitives not found';
    END IF;
END $$;

-- Lookup indexes (the two query keys: scheme_code and isin).
CREATE INDEX IF NOT EXISTS ix_v3mf_scheme_code ON nidp.v_v3_mf_primitives (scheme_code);
CREATE INDEX IF NOT EXISTS ix_v3mf_isin        ON nidp.v_v3_mf_primitives (isin);
-- (CREATE MATERIALIZED VIEW above already populates it; the nightly REFRESH is
--  wired into mf_analytics_engine.run().)
