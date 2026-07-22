-- 126_corporate_event_signals_filing_key.sql
-- Give the new stage-7 `filing_insights` generator an idempotent upsert key.
--
-- The generator writes exactly ONE insight per corporate announcement, so it must
-- upsert keyed by the announcement's real identity. But that identity is
-- (announcement_id TEXT, source) — the composite PK of nidp.corporate_announcements
-- (announcement_id is a sha1, NOT an int). corporate_event_signals.announcement_id
-- is BIGINT (a soft ref to the long-dropped nidp.announcements table) and there is
-- no source column, so it cannot hold that identity.
--
-- Rather than repurpose the BIGINT column (and risk the existing d1_prep / post_event
-- rows), add the TEXT identity as new columns and a PARTIAL unique index scoped to
-- filing_insight rows only. That gives ON CONFLICT idempotency for the generator
-- without touching the existing UNIQUE (symbol,event_type,event_date,period,signal_type)
-- semantics used by every other signal_type. Additive + idempotent.

SET search_path TO nidp, public;

ALTER TABLE nidp.corporate_event_signals
    ADD COLUMN IF NOT EXISTS announcement_ref    TEXT,   -- corporate_announcements.announcement_id (sha1)
    ADD COLUMN IF NOT EXISTS announcement_source TEXT;   -- corporate_announcements.source (NSE_ANN / BSE_ANN)

COMMENT ON COLUMN nidp.corporate_event_signals.announcement_ref IS
    'For signal_type=''filing_insight'': the source corporate_announcements.announcement_id (TEXT sha1). Null for other signal_types.';
COMMENT ON COLUMN nidp.corporate_event_signals.announcement_source IS
    'For signal_type=''filing_insight'': the source corporate_announcements.source (NSE_ANN/BSE_ANN). Pairs with announcement_ref to reference the filing.';

-- One insight per filing. Partial, so it never collides with the general
-- (symbol,event_type,event_date,period,signal_type) uniqueness of other signal_types.
CREATE UNIQUE INDEX IF NOT EXISTS corporate_event_signals_filing_uniq
    ON nidp.corporate_event_signals (announcement_ref, announcement_source)
    WHERE signal_type = 'filing_insight';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('126_corporate_event_signals_filing_key.sql')
ON CONFLICT DO NOTHING;
