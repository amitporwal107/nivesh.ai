-- 020_portfolio_pg_user_map.sql
-- Maps Nivesh internal user_id → email so the NIDP portfolio sync agent
-- can use email as the canonical external_user_id without touching MongoDB.
--
-- Populated by cas_snapshot_engine._persist_pg_snapshot() on every CAS
-- upload and EOD snapshot write. Best-effort — the NIDP sync skips any
-- client_id with no email entry rather than failing the whole run.

CREATE TABLE IF NOT EXISTS client_user_map (
    client_id   TEXT PRIMARY KEY,           -- = MongoDB user_id (e.g. "user_abc123")
    email       TEXT NOT NULL,
    display_name TEXT,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_client_user_map_email
    ON client_user_map (email);

CREATE INDEX IF NOT EXISTS idx_client_user_map_updated
    ON client_user_map (updated_at DESC);

-- Ensure portfolio_snapshot_master tracks mutation time so the sync
-- agent can do incremental extraction via updated_at watermark.
ALTER TABLE portfolio_snapshot_master
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_psm_updated
    ON portfolio_snapshot_master (updated_at DESC);

-- Back-fill updated_at = created_at for existing rows.
UPDATE portfolio_snapshot_master
   SET updated_at = created_at
 WHERE updated_at = NOW()          -- only rows where the default just fired
   AND created_at IS NOT NULL;
