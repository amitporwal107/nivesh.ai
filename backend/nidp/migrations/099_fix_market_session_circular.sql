-- 099_fix_market_session_circular.sql
--
-- Fix: bhavcopy (and every downstream ingester that targets "last NSE close")
-- froze its target_date for the rest of each trading week, leaving daily gaps
-- in nidp.prices_eod and therefore in stock_features_daily / V3 scores.
--
-- Root cause — circular dependency in nidp.v_market_session (migration 023):
--   The view returned the CACHED market_session_state.last_close_date whenever
--   last_close_observed_at was < 24h old, and only recomputed from the calendar
--   when it was older. But bhavcopy runs DAILY (Mon-Fri) and bumps
--   last_close_observed_at to NOW() on every successful run, so observed_at was
--   never > 24h old during the week. Result: after the first post-weekend run
--   the date latched to that Monday and the view kept handing back the stale
--   stored value (its own output) for the rest of the week. e.g. 2026-06-15
--   (Mon) ingested fresh, then re-ingested Tue-Fri while 16/17/18/19 were never
--   fetched. (This recurred after a manual 2026-05-21 reset — the reset only
--   moved the latch, it didn't break the loop.)
--
-- Fix: derive the canonical last-close straight from the calendar function
-- (which already honours nse_holidays + the 18:30 IST cutoff), floored by the
-- stored value so it can never regress. No 24h cache, so the date advances
-- every day regardless of how recently a run bumped observed_at.

CREATE OR REPLACE VIEW nidp.v_market_session AS
SELECT
    s.market,
    -- Calendar is the source of truth; GREATEST keeps the "never go backwards"
    -- guarantee the old cache was trying (badly) to provide.
    GREATEST(s.last_close_date, nidp.compute_last_trading_day_ist()) AS last_close_date,
    s.last_close_observed_at,
    s.notes
FROM nidp.market_session_state s;

COMMENT ON VIEW nidp.v_market_session IS
    'Canonical "last NSE close" = GREATEST(stored last_close_date, '
    'compute_last_trading_day_ist()). Calendar-driven (holidays + 18:30 IST '
    'cutoff), floored by the stored value. Replaces the 24h-cache CASE from '
    'migration 023, which created a circular dependency that froze the date '
    'mid-week (see migration 099 header).';
