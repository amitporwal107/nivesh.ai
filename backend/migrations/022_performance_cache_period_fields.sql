-- 022_performance_cache_period_fields.sql
-- Adds period-matched return fields to portfolio_performance_cache.
--
-- Context: Migration 021 created the cache with portfolio_xirr / benchmark_xirr which are
-- since-inception metrics. For bounded periods (1M/3M/6M/1Y/3Y) the engine now computes a
-- simple period return (current_value / value_N_days_ago − 1) which is the correct metric to
-- compare against benchmark period returns (return_1y, return_3m etc.). XIRR is kept for the
-- "Since inception" period only.
--
-- New columns:
--   portfolio_return — period-matched simple return (NULL for old cache rows → falls back to portfolio_xirr)
--   return_type      — 'period' for bounded periods, 'xirr' for inception
--   benchmark_return — period-matched benchmark (same window as portfolio_return)
--
-- Forward-only; all statements are ADD COLUMN IF NOT EXISTS.

ALTER TABLE portfolio_performance_cache
    ADD COLUMN IF NOT EXISTS portfolio_return  NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS return_type       VARCHAR(16),
    ADD COLUMN IF NOT EXISTS benchmark_return  NUMERIC(8,4);

COMMENT ON COLUMN portfolio_performance_cache.portfolio_return IS
    'Period-matched simple return: (current_value / value_N_days_ago − 1) × 100. '
    'NULL on rows computed before this migration → frontend falls back to portfolio_xirr.';

COMMENT ON COLUMN portfolio_performance_cache.return_type IS
    'How portfolio_return was computed: "period" for bounded periods (1M/3M/6M/1Y/3Y), '
    '"xirr" for inception. Drives the KPI label ("Return (1Y)" vs "XIRR (Since inception)").';

COMMENT ON COLUMN portfolio_performance_cache.benchmark_return IS
    'Period-matched benchmark return (same window as portfolio_return). '
    'Alpha = portfolio_return − benchmark_return (both same window, never mixed).';
