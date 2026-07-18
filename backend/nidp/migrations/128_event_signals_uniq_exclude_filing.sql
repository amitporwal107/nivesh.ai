-- 128_event_signals_uniq_exclude_filing.sql
-- Exempt filing_insight rows from the (symbol,event_type,event_date,period,signal_type)
-- uniqueness — it is the wrong key for them.
--
-- corporate_event_signals_uniq (added by 037) enforces ONE signal per
-- (symbol, event_type, event_date, period, signal_type). That is right for the
-- d1_prep / post_event trading signals it was built for. It is WRONG for
-- filing_insight rows: two DISTINCT filings from the same company can share
-- symbol + event_category + filed-date + (null) period — e.g. a company files a
-- director appointment and a director resignation on the same day, both
-- 'management'. Those are two different announcements (different announcement_id)
-- and must yield two different insights, but they collide on this constraint and
-- the generator's batch crashed on the second one (measured on staging:
-- DSFCL / management / 2026-07-17 / null).
--
-- filing_insight rows already have their own correct key: the partial unique index
-- on (announcement_ref, announcement_source) from migration 126. So make THIS
-- constraint partial, excluding filing_insight. All other signal_types keep their
-- exact uniqueness. d1_prep's upsert adds the matching predicate so its ON CONFLICT
-- still infers this index (see nidp/services/d1_prep/service.py). Additive/idempotent.

SET search_path TO nidp, public;

ALTER TABLE nidp.corporate_event_signals
    DROP CONSTRAINT IF EXISTS corporate_event_signals_uniq;
-- (dropping the constraint drops its backing index; guard a stray same-named index too)
DROP INDEX IF EXISTS nidp.corporate_event_signals_uniq;

CREATE UNIQUE INDEX IF NOT EXISTS corporate_event_signals_uniq
    ON nidp.corporate_event_signals (symbol, event_type, event_date, period, signal_type)
    WHERE signal_type <> 'filing_insight';

INSERT INTO nidp.schema_migrations(filename)
VALUES ('128_event_signals_uniq_exclude_filing.sql')
ON CONFLICT DO NOTHING;
