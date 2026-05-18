-- 056_nidp_portfolio_transactions_goals.sql
--
-- Extends the portfolio bridge (migration 042) with two missing slices of
-- user state that the V3 engine needs:
--   1. portfolio.user_transactions  — raw CAS transaction lots (BUY/SELL).
--      FIFO matching can be derived from this; it replaces the in-memory
--      compute in services/tax_engine_fifo on the Nivesh side once DaaS
--      exposes /v1/portfolio/v3-bundle/{user}.
--   2. portfolio.user_goals         — financial goals (target amount,
--      horizon, allocation, on-track %). Needed for V3 Add score's
--      gap-fit and need-score inputs.
--
-- Source of truth on the Nivesh side:
--   * cas_transactions  — Mongo (db.cas_transactions)
--   * user_goals        — Nivesh Postgres (migrations/007_goal_planning.sql)
--
-- Both feed in via GCS JSONL exports, mirroring the established pattern
-- used by portfolio.user_holdings_snapshot (migration 042).

SET search_path TO nidp, public;


-- ── 1. portfolio.user_transactions ───────────────────────────────────
-- One row per CAS transaction. Natural key = (external_user_id, folio,
-- isin, txn_date, txn_type, units, amount) — same dedup composite Mongo
-- uses, so re-syncs are idempotent.
CREATE TABLE IF NOT EXISTS portfolio.user_transactions (
    txn_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_user_id   TEXT NOT NULL,
    source_system      TEXT NOT NULL DEFAULT 'nivesh_cas',
    txn_date           DATE NOT NULL,
    txn_type           TEXT NOT NULL,                      -- PURCHASE | SIP_PURCHASE | REDEMPTION | DIVIDEND | BONUS | OTHER
    folio              TEXT,
    isin               TEXT,
    amfi_scheme_code   TEXT,
    symbol             TEXT,
    instrument_name    TEXT,
    asset_class        TEXT NOT NULL,                      -- EQUITY | MF | ETF | DEBT | CASH | OTHER
    units              NUMERIC(20,6),                      -- signed positive for BUY, positive for SELL too (txn_type carries sign)
    amount_inr         NUMERIC(20,2),                      -- gross amount transacted
    nav_or_price       NUMERIC(20,6),                      -- amount / units when both present
    cas_file_id        TEXT,
    metadata_json      JSONB,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotent upserts: identical (user, folio, isin, date, type, units, amount)
-- replaces the metadata. Same composite as Mongo's natural key.
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_transactions_dedup
    ON portfolio.user_transactions (
        external_user_id, txn_date, txn_type,
        COALESCE(folio, ''), COALESCE(isin, ''),
        COALESCE(units, 0), COALESCE(amount_inr, 0),
        source_system
    );

CREATE INDEX IF NOT EXISTS idx_user_txn_user_date
    ON portfolio.user_transactions (external_user_id, txn_date DESC);
CREATE INDEX IF NOT EXISTS idx_user_txn_isin
    ON portfolio.user_transactions (isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_user_txn_symbol
    ON portfolio.user_transactions (symbol) WHERE symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_user_txn_type
    ON portfolio.user_transactions (external_user_id, txn_type, txn_date DESC);


-- ── 2. portfolio.user_goals ──────────────────────────────────────────
-- Mirror of user_goals on the Nivesh Postgres side. UUID `goal_id` is
-- preserved from upstream so cross-system joins work.
CREATE TABLE IF NOT EXISTS portfolio.user_goals (
    goal_id              UUID PRIMARY KEY,                 -- preserved from upstream
    external_user_id     TEXT NOT NULL,
    source_system        TEXT NOT NULL DEFAULT 'nivesh_pg',
    goal_type            TEXT NOT NULL,                    -- retirement | education | home | wealth | custom
    goal_name            TEXT NOT NULL,
    target_amount_rs     NUMERIC(14,2) NOT NULL,
    horizon_years        NUMERIC(5,2) NOT NULL,
    priority             TEXT NOT NULL DEFAULT 'medium',   -- high | medium | low
    inflation_pct        NUMERIC(5,2) DEFAULT 6.0,
    expected_return_pct  NUMERIC(5,2),
    current_corpus_rs    NUMERIC(14,2) DEFAULT 0,
    monthly_sip_rs       NUMERIC(14,2) DEFAULT 0,
    allocation           JSONB,                            -- {equity, debt, hybrid}
    selected_funds       JSONB,
    manual_fund_override BOOLEAN DEFAULT FALSE,
    status               TEXT NOT NULL DEFAULT 'active',   -- active | achieved | abandoned | paused
    on_track_pct         NUMERIC(5,2),
    last_simulated_at    TIMESTAMPTZ,
    last_simulation      JSONB,
    upstream_created_at  TIMESTAMPTZ,
    upstream_updated_at  TIMESTAMPTZ,
    synced_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_goals_user
    ON portfolio.user_goals (external_user_id);
CREATE INDEX IF NOT EXISTS idx_user_goals_status
    ON portfolio.user_goals (external_user_id, status);
CREATE INDEX IF NOT EXISTS idx_user_goals_horizon
    ON portfolio.user_goals (horizon_years);


-- ── 3. Sync audit log additions ──────────────────────────────────────
-- The existing portfolio.sync_audit_log table (migration 046) uses a
-- generic shape that doesn't distinguish dataset. Add a dataset column
-- so the new syncs share the same audit trail.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'portfolio' AND table_name = 'sync_audit_log'
    ) THEN
        ALTER TABLE portfolio.sync_audit_log
            ADD COLUMN IF NOT EXISTS dataset TEXT NOT NULL DEFAULT 'holdings',
            ADD COLUMN IF NOT EXISTS rows_upserted INTEGER;
        CREATE INDEX IF NOT EXISTS idx_sync_audit_dataset
            ON portfolio.sync_audit_log (dataset, synced_at DESC);
    END IF;
END $$;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('056_nidp_portfolio_transactions_goals.sql')
ON CONFLICT (filename) DO NOTHING;
