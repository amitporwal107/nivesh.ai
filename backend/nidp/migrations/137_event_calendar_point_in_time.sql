-- 137_event_calendar_point_in_time.sql
--
-- nidp.event_calendar could not say when a meeting became known. fetched_at is
-- overwritten on every refresh, so on 2026-09-11 it sat AFTER the meeting date
-- for 99% of rows (median 7 days after) — useless for "was this results meeting
-- known the evening before?", which is the strongest single predictor of a
-- 10% move.
--
--   intimated_at   NSE's bm_timestamp: when the company intimated the exchange.
--                  The exchange's own point-in-time "known since".
--   first_seen_at  When NIDP first ingested the row. Set on INSERT, never
--                  updated. NULL for rows NIDP did not observe live: everything
--                  that existed before this migration, and the 2-year backfill.
--
-- Additive and nullable; re-runnable.

ALTER TABLE nidp.event_calendar
    ADD COLUMN IF NOT EXISTS intimated_at  TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ;

COMMENT ON COLUMN nidp.event_calendar.intimated_at IS
  'NSE bm_timestamp: when the company intimated the exchange (point-in-time known-since)';
COMMENT ON COLUMN nidp.event_calendar.first_seen_at IS
  'When NIDP first ingested the row; set on insert, never updated; NULL when not observed live';

CREATE INDEX IF NOT EXISTS idx_event_calendar_symbol_event_date
    ON nidp.event_calendar (symbol, event_date);

INSERT INTO nidp.schema_migrations (filename)
VALUES ('137_event_calendar_point_in_time.sql')
ON CONFLICT (filename) DO NOTHING;
