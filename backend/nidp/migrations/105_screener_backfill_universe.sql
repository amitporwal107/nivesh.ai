-- 105_screener_backfill_universe.sql
-- SD-05 (scoring-depth): widen the Screener fundamentals backfill beyond Nifty 500.
--
-- Problem: nidp.v_stock_fundamentals_latest covers only ~579 of the ~2,275 scored
-- stocks. All 499 scored Nifty-500 names have fundamentals (the existing backfill,
-- which reads nidp.v_nifty500_members, works at 100%), but 1,696 scored stocks are
-- OUTSIDE Nifty 500 (small/micro caps) and only ~80 of those have any fundamentals.
-- Nifty Midcap/Smallcap 100 are SUBSETS of Nifty 500, so adding those index views
-- adds nothing — the gap is the broader market, defined by what the engine scores.
--
-- This view exposes the full scoring universe (symbols with recent features) plus a
-- has_fundamentals flag, so the backfill can target the missing names first. The
-- backfill's own 180-day freshness check (nse_financials_quarterly, source=screener_in)
-- remains the authoritative skip gate; has_fundamentals here is only for ordering.

CREATE OR REPLACE VIEW nidp.v_screener_backfill_universe AS
SELECT DISTINCT
       sf.symbol,
       (vf.symbol IS NOT NULL) AS has_fundamentals
  FROM nidp.stock_features_daily sf
  LEFT JOIN (
        SELECT DISTINCT symbol FROM nidp.v_stock_fundamentals_latest
  ) vf ON vf.symbol = sf.symbol
 WHERE sf.as_of_date > (CURRENT_DATE - INTERVAL '30 days');

COMMENT ON VIEW nidp.v_screener_backfill_universe IS
  'SD-05: full scored stock universe (recent stock_features_daily) for the Screener '
  'fundamentals backfill, with has_fundamentals flag for missing-first ordering. '
  'Replaces the Nifty-500-only v_nifty500_members source in backfill_screener.';
