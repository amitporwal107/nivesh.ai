-- 172: carry the point-in-time knowledge date into nidp.mf_holdings_deltas.
--
-- WHY
-- Migration 171 established when each holding became knowable (published_at where credible, else
-- source_observed_at). A DELTA, though, is only knowable once BOTH of the months it compares have
-- been published: a September-vs-August change cannot be computed by anyone until September's
-- disclosure is out. Without that date on the delta row, a consumer filtering by as_of_month would
-- read a change weeks before it could have been known — look-ahead, which is the single easiest
-- way to manufacture a signal that backtests well and fails live.
--
--     known_from = max(known_from of the current month, known_from of the comparison month)
--
-- Measured after backfilling 171: 74.8% of holdings rows carry a real published_at, so most deltas
-- get a true knowledge date. The rest fall back to source_observed_at (October 2026 for everything
-- backfilled), which correctly makes them unusable for historical point-in-time work rather than
-- quietly usable.
--
-- Idempotent: safe to re-run.

ALTER TABLE nidp.mf_holdings_deltas
    ADD COLUMN IF NOT EXISTS known_from TIMESTAMPTZ,
    -- 'published' when BOTH months had a credible publication date, else 'observed' (at least one
    -- side is only bounded by when we fetched it). Only 'published' rows are safe for a backtest.
    ADD COLUMN IF NOT EXISTS known_from_basis TEXT;

CREATE INDEX IF NOT EXISTS idx_mf_hold_delta_known
    ON nidp.mf_holdings_deltas (known_from, current_month);

COMMENT ON COLUMN nidp.mf_holdings_deltas.known_from IS
  'Earliest moment this change could have been known: max of the two compared months'' '
  'known_from. Filter on this for point-in-time work, never on current_month.';
COMMENT ON COLUMN nidp.mf_holdings_deltas.known_from_basis IS
  '''published'' = both months had a credible publication timestamp (safe for a backtest). '
  '''observed'' = at least one side is dated only by when we fetched it, so a historical scoring '
  'date would see it earlier than any user could have.';

-- Per disclosure month: what fraction of the delta layer is backtest-safe.
CREATE OR REPLACE VIEW nidp.v_mf_deltas_pit_readiness AS
SELECT current_month,
       count(*)                                                           AS delta_rows,
       count(*) FILTER (WHERE known_from_basis = 'published')              AS pit_safe_rows,
       round(100.0 * count(*) FILTER (WHERE known_from_basis = 'published')
             / nullif(count(*), 0), 1)                                     AS pit_safe_pct,
       min(known_from) FILTER (WHERE known_from_basis = 'published')        AS earliest_known,
       max(known_from) FILTER (WHERE known_from_basis = 'published')        AS latest_known,
       -- Days from month end until the whole month's comparison was knowable.
       (max(known_from) FILTER (WHERE known_from_basis = 'published')::date
         - (current_month + INTERVAL '1 month - 1 day')::date)             AS days_to_fully_known
  FROM nidp.mf_holdings_deltas
 GROUP BY current_month;

COMMENT ON VIEW nidp.v_mf_deltas_pit_readiness IS
  'Per month: how much of the holdings-delta layer can be used in a point-in-time backtest, and '
  'how long after month end the month became fully knowable.';
