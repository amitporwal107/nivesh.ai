-- 148_tpd_corporate_actions_history.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Model-only corporate-actions history for Ten-Percent Days 3.0 (tpd_model).
--
-- The shared corporate_actions table starts 2026-05-26, but the model's point-in-time price
-- adjustment and its "no label across a corporate action" rule need actions back to 2024-06.
-- The NSE API archive (research/tpd_run/data/nse_api/ca, 5,746 records 2024-06..2026-09) covers it.
--
-- Deliberately a separate table: price_adjuster rebuilds the full adjusted history of any symbol
-- with an action ex-dated OR ingested in its 30-day window, so bulk-loading history into the shared
-- table would rewrite adjusted prices and the 1y metrics prod reads. Nothing but tpd_model reads
-- this table; no DaaS route exposes it. Same columns and key as the shared table so the model can
-- union the two (source = 'NSE_CA_ARCHIVE' here).
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;

CREATE TABLE IF NOT EXISTS nidp.tpd_corporate_actions_history (
    symbol              TEXT NOT NULL,
    series              TEXT,
    action_type         TEXT NOT NULL,
    action_subtype      TEXT,
    purpose             TEXT,
    ratio               TEXT,
    face_value_pre      NUMERIC(10,4),
    face_value_post     NUMERIC(10,4),
    dividend_amount     NUMERIC(14,4),
    record_date         DATE,
    ex_date             DATE NOT NULL,
    bc_start_date       DATE,
    bc_end_date         DATE,
    announcement_date   DATE,
    source              TEXT NOT NULL,
    source_run_id       UUID NOT NULL,
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, action_type, ex_date, source)
);

CREATE INDEX IF NOT EXISTS idx_tpd_ca_history_symbol_ex_date
    ON nidp.tpd_corporate_actions_history (symbol, ex_date);

COMMENT ON TABLE nidp.tpd_corporate_actions_history IS
    'Ten-Percent Days 3.0 model-only corporate-actions history (NSE API archive). Not read by price_adjuster or DaaS.';

COMMIT;
