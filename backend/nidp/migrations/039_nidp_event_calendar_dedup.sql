-- ── Migration 039: Fix event_calendar NULL-period deduplication ─────────────
--
-- Root cause: UNIQUE (symbol, event_type, event_date, period) treats every
-- NULL as distinct (SQL standard). PSU banks like SBIN often have period=NULL
-- in the NSE feed, so:
--   • ON CONFLICT never fires → duplicate rows accumulate on each ingest run
--   • The LEFT JOIN in market_events returns the same event N times
--   • Events for SBI / other PSU banks appear duplicated or drop out of view
--
-- Fix: replace the inline UNIQUE constraint with a functional unique index that
-- normalises NULL period to '' so all NULLs collide with each other.
-- Works on PostgreSQL 14+.  (PG 15 has NULLS NOT DISTINCT, but the functional
-- index is safer across Cloud SQL versions.)
-- ─────────────────────────────────────────────────────────────────────────────

-- 1. Remove all exact duplicate rows (keep the one with the lowest id)
DELETE FROM nidp.event_calendar
WHERE id NOT IN (
    SELECT MIN(id)
    FROM   nidp.event_calendar
    GROUP  BY symbol, event_type, event_date, COALESCE(period, '')
);

-- 2. Drop the old broken UNIQUE constraint
--    (PG auto-names inline UNIQUE constraints as <table>_<cols>_key)
ALTER TABLE nidp.event_calendar
    DROP CONSTRAINT IF EXISTS event_calendar_symbol_event_type_event_date_period_key;

-- 3. Add a functional unique index — NULL period treated as empty string
CREATE UNIQUE INDEX IF NOT EXISTS event_calendar_uq
    ON nidp.event_calendar (symbol, event_type, event_date, COALESCE(period, ''));
