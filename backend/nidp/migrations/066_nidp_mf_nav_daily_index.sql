-- 066_nidp_mf_nav_daily_index.sql
-- T07 fix: mf_derived_refresh SQL function scans mf_nav_daily three times
-- per scheme_code (consistency, downside-capture, AUM-trend windows).
-- Without a covering index the function times out (~3 of 7 runs).
--
-- The function body in nidp.refresh_mf_derived_analytics() executes:
--   WHERE scheme_code = p_scheme_code                   (point lookup)
--   WHERE scheme_code = p_scheme_code ORDER BY nav_date  (range scan)
-- A single (scheme_code, nav_date DESC) index covers both patterns.
--
-- Also adds a composite index on (nav_date DESC) alone for the
-- bulk-batch outer loop that ORDER BY nav_date DESC across all schemes.

-- Index 1: per-scheme date range scans (covers the per-scheme sub-queries)
CREATE INDEX IF NOT EXISTS idx_mf_nav_daily_scheme_date
    ON nidp.mf_nav_daily (scheme_code, nav_date DESC);

-- Index 2: latest-NAV look-ups (WHERE nav_date = $latest, all schemes)
CREATE INDEX IF NOT EXISTS idx_mf_nav_daily_date_scheme
    ON nidp.mf_nav_daily (nav_date DESC, scheme_code);

-- Analyze so the planner picks up the new statistics immediately.
ANALYZE nidp.mf_nav_daily;
