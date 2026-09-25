-- 155_corporate_transactions.sql — persistent transaction_id across a deal's filings.
--
-- Depends on: 154_announcement_security_resolution.sql
--
-- PRD v1.1 §3/§5.1 require one transaction_id spanning announcement → approval →
-- offer → completion, with sample sizes counted in unique transactions and never
-- in filings. nidp has no such concept: a repo-wide grep for transaction_id /
-- event_group / parent_event / deal_id returns nothing, and stock_events is one
-- row per filing. Migration 128 records a collision this already causes — "two
-- DISTINCT filings from the same company can share symbol + event_category +
-- filed-date + (null) period".
--
-- One real buyback, MATRIMONY 2026-01-20..02-26, is 12 filings across both
-- exchanges: record date → public announcement → board resolution → letter of
-- offer → post-buyback announcement → extinguishment. Counting those as 12
-- events would inflate a cohort twelvefold.
--
-- TWO TABLES, NOT ONE COLUMN
--
-- Classification is stored beside the filing, never inside corporate_announcements,
-- and carries its own provenance. The reason is sequencing: buyback stages resolve
-- from metadata today, QIP/preferential does not, and QIP stages will arrive later
-- from parsed attachments. With stage_source + classifier_version, that arrival is
-- an UPSERT of higher-provenance rows. If stage were a column filled from metadata,
-- it would be a migration plus an argument about which value wins.
--
-- Measured 2026-09-25 over every filing resolving to an NSE symbol:
--
--     family     staged  UNRESOLVED  % staged   provenance
--     BUYBACK       124          27       82%   subject 101, description 23
--     QIP_PREF       87         158       36%   subject  71, description 16
--
-- UNRESOLVED IS NOT A STAGE
--
-- NSE files the bare subject "Buyback" for every step of an offer; BSE files
-- "Announcement under Regulation 30 (LODR)-Preferential Issue" for most of a QIP.
-- For those the stage genuinely cannot be read. An earlier cut of this work called
-- them UPDATE — which is ALSO a real filing type ("Updates on Buyback Offer") — so
-- a filing the classifier could not read was indistinguishable from one it
-- positively classified, and both would have entered lifecycle statistics as known.
-- stage = 'UNRESOLVED' is the explicit "we could not tell", and every consumer must
-- exclude it rather than place it in the lifecycle.

SET search_path TO nidp, public;

-- Stage provenance ordering, defined ONCE. Python mirrors it in
-- lifecycle.SOURCE_RANK and a test asserts the two agree; without a single
-- definition the writer's guard and the classifier could disagree silently.
CREATE OR REPLACE FUNCTION nidp.stage_source_rank(src TEXT) RETURNS INTEGER AS $$
    SELECT CASE src
             WHEN 'document'    THEN 3
             WHEN 'description' THEN 2
             WHEN 'subject'     THEN 1
             ELSE 0                      -- 'none', NULL, anything unrecognised
           END;
$$ LANGUAGE SQL IMMUTABLE;

COMMENT ON FUNCTION nidp.stage_source_rank(TEXT) IS
    'none < subject < description < document. The writer overwrites a stored '
    'stage only when the incoming source ranks strictly higher.';

CREATE TABLE IF NOT EXISTS nidp.corporate_transactions (
    transaction_id   TEXT PRIMARY KEY,            -- <symbol>:<family>:<ordinal>
    nse_symbol       TEXT NOT NULL,
    family           TEXT NOT NULL,               -- BUYBACK | QIP_PREF
    txn_ordinal      INTEGER NOT NULL,            -- nth of this family for this symbol
    first_filed_on   DATE NOT NULL,
    last_filed_on    DATE NOT NULL,
    filing_count     INTEGER NOT NULL,
    stages_seen      TEXT[] NOT NULL DEFAULT '{}',-- distinct resolved stages, excl. UNRESOLVED
    unresolved_count INTEGER NOT NULL DEFAULT 0,  -- filings whose stage could not be read
    confounded_count INTEGER NOT NULL DEFAULT 0,  -- filings bundling results (PRD §7.5)

    -- Cohort gate. A family is ready only when its stages can actually be read;
    -- the cohort builder checks THIS rather than relying on everyone remembering
    -- that QIP is incomplete. QIP flips to true once document stages land and the
    -- gold set is extended.
    lifecycle_ready  BOOLEAN NOT NULL,

    classifier_version TEXT NOT NULL,
    source_run_id    UUID NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (nse_symbol, family, txn_ordinal)
);

COMMENT ON TABLE nidp.corporate_transactions IS
    'One row per corporate transaction (PRD v1.1 §5.1). Sample sizes are counted '
    'here, never in filings. lifecycle_ready = false means the family''s stages '
    'cannot yet be read reliably and it must not feed a cohort.';

COMMENT ON COLUMN nidp.corporate_transactions.unresolved_count IS
    'Filings whose stage could not be determined from the available text. NOT a '
    'stage — these are excluded from lifecycle statistics and reported out loud.';

CREATE INDEX IF NOT EXISTS idx_corp_txn_symbol_family
    ON nidp.corporate_transactions (nse_symbol, family, first_filed_on DESC);
CREATE INDEX IF NOT EXISTS idx_corp_txn_ready
    ON nidp.corporate_transactions (family, first_filed_on DESC) WHERE lifecycle_ready;


-- Per-filing classification. Separate from corporate_announcements, which stays
-- the raw exchange record.
CREATE TABLE IF NOT EXISTS nidp.corporate_transaction_filings (
    announcement_id  TEXT NOT NULL,
    source           TEXT NOT NULL,               -- 'NSE_ANN' | 'BSE_ANN'
    transaction_id   TEXT NOT NULL REFERENCES nidp.corporate_transactions (transaction_id),
    nse_symbol       TEXT NOT NULL,
    family           TEXT NOT NULL,
    filed_on         DATE NOT NULL,

    stage            TEXT NOT NULL,               -- a stage, or 'UNRESOLVED'
    -- Which input produced the stage, weakest to strongest:
    --   none < subject < description < document
    -- A later pass over parsed attachments upserts ONLY where this improves, so
    -- a document-derived stage can never be overwritten by a metadata guess.
    stage_source     TEXT NOT NULL,
    confounded       BOOLEAN NOT NULL DEFAULT FALSE,

    classifier_version TEXT NOT NULL,
    source_run_id    UUID NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (announcement_id, source)
);

COMMENT ON TABLE nidp.corporate_transaction_filings IS
    'Derived classification per filing, kept out of corporate_announcements so the '
    'raw exchange record stays raw. stage_source records provenance so QIP stages '
    'from parsed attachments arrive as an upsert, not a schema change.';

COMMENT ON COLUMN nidp.corporate_transaction_filings.stage_source IS
    'none | subject | description | document — weakest to strongest. Re-runs must '
    'only overwrite when the new source ranks higher.';

CREATE INDEX IF NOT EXISTS idx_corp_txn_filings_txn
    ON nidp.corporate_transaction_filings (transaction_id, filed_on);
CREATE INDEX IF NOT EXISTS idx_corp_txn_filings_symbol
    ON nidp.corporate_transaction_filings (nse_symbol, family, filed_on DESC);
-- Finds the filings a document pass could still improve.
CREATE INDEX IF NOT EXISTS idx_corp_txn_filings_unresolved
    ON nidp.corporate_transaction_filings (family, filed_on)
    WHERE stage = 'UNRESOLVED';


-- Cohort-facing view: only families whose lifecycle can be read, and only
-- filings whose stage is known. Studies should read THIS, not the base tables.
CREATE OR REPLACE VIEW nidp.v_corporate_transactions_ready AS
SELECT t.*
FROM nidp.corporate_transactions t
WHERE t.lifecycle_ready
  AND t.filing_count > t.unresolved_count;   -- at least one readable stage

COMMENT ON VIEW nidp.v_corporate_transactions_ready IS
    'Transactions eligible for a cohort: family lifecycle_ready AND at least one '
    'filing with a resolved stage. Excludes QIP/preferential until its stages are '
    'backfilled from parsed attachments.';
