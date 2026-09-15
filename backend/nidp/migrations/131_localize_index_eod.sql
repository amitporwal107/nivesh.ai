-- Promote nidp.index_eod_local to the canonical name so index_close can write.
--
-- The problem
-- -----------
-- nidp.index_eod is a pass-through VIEW over an FDW FOREIGN TABLE into the prod
-- database (search_path is `prod_data, nidp, public`, so the unqualified
-- `FROM index_eod` in the view body binds to prod_data.index_eod). A foreign
-- table has no unique constraint, so every ingester upsert died with
--
--     InvalidColumnReferenceError: there is no unique or exclusion constraint
--     matching the ON CONFLICT specification
--
-- index_close had failed that way 253 consecutive times and had never once
-- succeeded. The FDW was not even serving current data: prod's own ingestion
-- stopped, so the view ends 2026-07-20 and consumers read a frozen snapshot.
--
-- Why merge rather than create
-- ---------------------------
-- nidp.index_eod_local already exists as a real table — staging's own pre-FDW
-- ingestion, orphaned when the canonical name was switched to the view. It is
-- structurally identical (column name and type compared position by position)
-- and already owns the intended primary key and indexes under the canonical
-- names. The prod history has already been merged into it, so it is now a
-- strict superset of the view:
--
--     index_eod_local (before)   4,556 rows  2026-04-10 .. 2026-05-27
--     index_eod (FDW view)      12,350 rows  2026-02-06 .. 2026-07-20
--     index_eod_local (merged)  13,530 rows  2026-02-06 .. 2026-07-20, 161 indices
--
-- Nothing depends on nidp.index_eod, so the swap is a two-statement rename.
--
-- Hazards a rollback-only dry run surfaced
-- ----------------------------------------
-- 1. index_eod_pkey ALREADY EXISTS — it belongs to index_eod_local. Creating a
--    fresh table with that constraint name fails outright. Hence merge-and-
--    rename rather than create-and-swap.
-- 2. Pulling rows through postgres_fdw at its default fetch_size of 100 rows
--    per round trip is pathologically slow and holds ACCESS EXCLUSIVE on the
--    view meanwhile, blocking every reader. The merge above was therefore done
--    by reading prod directly (0.18s for 12,350 rows) rather than through the
--    FDW, and this file no longer copies anything.
--
-- mf_nav_daily is deliberately NOT handled here — see 132 (deferred).
--
-- The runner executes each migration file in one transaction, so there is no
-- BEGIN/COMMIT here; a failure rolls the swap back and leaves the view intact.

-- Idempotent: only swap if index_eod is still the FDW view.
DO $mig$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'nidp' AND c.relname = 'index_eod' AND c.relkind = 'v')
    THEN
        -- Keep the FDW view rather than dropping it: it stays available as an
        -- explicit accessor for prod's copy, and a rename is reversible.
        EXECUTE 'ALTER VIEW nidp.index_eod RENAME TO index_eod_fdw';
        EXECUTE 'ALTER TABLE nidp.index_eod_local RENAME TO index_eod';
        EXECUTE 'GRANT SELECT ON nidp.index_eod, nidp.index_eod_fdw TO nidp_ro';
    END IF;
END
$mig$;

-- The planner's statistics describe the pre-merge table; refresh them or a
-- "latest close per index" lookup plans against a row count three times too small.
ANALYZE nidp.index_eod;
