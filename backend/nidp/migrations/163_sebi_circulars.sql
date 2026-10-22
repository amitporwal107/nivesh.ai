-- 163_sebi_circulars.sql
-- SEBI circulars and master circulars, for the trading desk's Market intelligence tab.
--
-- Loaded by services/sebi_circulars from SEBI's own public pages:
--   source 'sebi_rss'      https://www.sebi.gov.in/sebirss.xml (the scheduled run). The feed holds
--                          about the latest 30 items of every kind; on 2026-10-14 all 30 were
--                          enforcement orders and recovery notices (12-13 Oct), none a circular.
--   source 'sebi_listing'  page 1 of the Legal > Circulars and Legal > Master Circulars listings
--                          (25 newest each; a one-off backfill, `--source listing`).
-- Only links under /legal/circulars/ and /legal/master-circulars/ are kept. The feed also carries
-- enforcement notices that name individuals with their PAN; those are dropped by the parser and
-- never reach this table.
--
--   url            the circular's page on sebi.gov.in (https://www.sebi.gov.in/legal/...); the key
--   kind           'circular' | 'master_circular', from the link path
--   issued_on      the date SEBI shows for the item (RSS pubDate / listing Date column); NULL when
--                  the source gives none
--   department     NULL: neither the feed nor the listing rows say which department issued it
--   source         where the row was first seen ('sebi_rss' | 'sebi_listing')
--   first_seen_at  when we first stored it; last_seen_at when a run last saw it
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.sebi_circulars (
    url            TEXT        PRIMARY KEY,
    title          TEXT        NOT NULL,
    kind           TEXT        NOT NULL,
    issued_on      DATE,
    department     TEXT,
    source         TEXT        NOT NULL DEFAULT 'sebi_rss',
    first_seen_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source_run_id  UUID,
    CONSTRAINT sebi_circulars_kind_chk CHECK (kind IN ('circular', 'master_circular'))
);

CREATE INDEX IF NOT EXISTS idx_sebi_circulars_issued_on
    ON nidp.sebi_circulars (issued_on DESC);

COMMENT ON TABLE nidp.sebi_circulars IS
    'SEBI circulars and master circulars (links under /legal/circulars/ and /legal/master-circulars/ only), from the SEBI RSS feed and listing pages. Written by services/sebi_circulars; read by DaaS GET /v1/circulars/sebi.';

-- A read-only role exists on some warehouses (see 131); grant it only where it exists.
DO $mig$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'nidp_ro') THEN
        EXECUTE 'GRANT SELECT ON nidp.sebi_circulars TO nidp_ro';
    END IF;
END
$mig$;
