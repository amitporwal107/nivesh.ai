-- 046_nidp_portfolio_sync_log.sql
-- Audit + client-registry tables for the portfolio_holdings_sync service.
--
-- portfolio.client_master  — canonical client registry (email as PK).
--   Populated by portfolio_holdings_sync on every sync run, mirroring
--   Nivesh's client_user_map.  Acts as the ACL: if a client has no
--   row here, their holdings are not synced and no analytics run.
--
-- portfolio.sync_audit_log — append-only run log; one row per
--   (client, snapshot_date) per sync run.  Powers the NIDP admin
--   dashboard's "last synced" view and the incremental watermark.

SET search_path TO public;

-- ── Client master (canonical registry) ───────────────────────────
CREATE TABLE IF NOT EXISTS portfolio.client_master (
    external_user_id    TEXT PRIMARY KEY,           -- email
    client_id           TEXT NOT NULL,              -- Nivesh MongoDB user_id
    display_name        TEXT,
    registered_at       TIMESTAMPTZ,
    last_sync_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_client_master_client_id
    ON portfolio.client_master (client_id);

CREATE INDEX IF NOT EXISTS idx_client_master_last_sync
    ON portfolio.client_master (last_sync_at DESC NULLS LAST);


-- ── Sync audit log ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS portfolio.sync_audit_log (
    log_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_run_id         UUID NOT NULL,
    external_user_id    TEXT NOT NULL,
    snapshot_date       DATE NOT NULL,
    status              TEXT NOT NULL,              -- SUCCESS | SKIPPED | ERROR
    holdings_upserted   INTEGER NOT NULL DEFAULT 0,
    portfolio_hash      TEXT,                       -- SHA-256 of holdings payload; detect no-ops on re-runs
    error_detail        TEXT,
    synced_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('SUCCESS', 'SKIPPED', 'ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_sync_audit_run
    ON portfolio.sync_audit_log (sync_run_id, synced_at DESC);

CREATE INDEX IF NOT EXISTS idx_sync_audit_user_date
    ON portfolio.sync_audit_log (external_user_id, snapshot_date DESC, synced_at DESC);


INSERT INTO nidp.schema_migrations (filename)
VALUES ('046_nidp_portfolio_sync_log.sql')
ON CONFLICT (filename) DO NOTHING;
