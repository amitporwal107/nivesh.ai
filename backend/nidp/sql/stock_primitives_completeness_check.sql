-- ─────────────────────────────────────────────────────────────────────
-- NIDP Stock Primitives — Completeness Check (standalone)
-- ─────────────────────────────────────────────────────────────────────
-- Run on the NIDP VM (SSH in, then `psql $NIDP_PG_DSN -f this_file.sql`)
-- Outputs a 4-section report in one transaction; safe to run any time.
--
-- Same checks the in-app `/api/admin/nidp/stock-primitives/completeness`
-- endpoint performs — useful when you can't (or don't want to) go
-- through the pod's SSH bridge.
-- ─────────────────────────────────────────────────────────────────────

\timing on
\pset pager off

-- 1. Existence check
SELECT '── 1. EXISTENCE ──' AS report;
SELECT
    table_schema || '.' || table_name AS object,
    table_type
FROM information_schema.tables
WHERE table_schema = 'nidp'
  AND table_name IN ('stock_features_daily', 'v_v3_stock_primitives')
UNION ALL
SELECT
    table_schema || '.' || table_name AS object,
    'VIEW'
FROM information_schema.views
WHERE table_schema = 'nidp'
  AND table_name = 'v_v3_stock_primitives';

-- 2. Basic counts
SELECT '── 2. ROW / SYMBOL / DATE RANGE ──' AS report;
SELECT
    COUNT(*)                                      AS total_rows,
    COUNT(DISTINCT symbol)                        AS distinct_symbols,
    MIN(as_of_date)                               AS earliest_date,
    MAX(as_of_date)                               AS latest_date,
    COUNT(*) FILTER (WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.v_v3_stock_primitives))
                                                  AS latest_snapshot_rows
FROM nidp.v_v3_stock_primitives;

-- 3. NULL percentages on the LATEST snapshot for the 17 fields
--    that services/stock_scoring.py reads via primitives.get()
SELECT '── 3. NULL % BY SCORING PRIMITIVE (latest snapshot) ──' AS report;
WITH latest AS (
    SELECT * FROM nidp.v_v3_stock_primitives
    WHERE as_of_date = (SELECT MAX(as_of_date) FROM nidp.v_v3_stock_primitives)
),
n AS (SELECT COUNT(*)::numeric AS total FROM latest)
SELECT
    metric,
    ROUND(100.0 * null_count / NULLIF(n.total, 0), 1) AS null_pct,
    null_count,
    n.total AS total_rows,
    CASE
        WHEN 100.0 * null_count / NULLIF(n.total, 0) >= 99 THEN 'HARD GAP'
        WHEN 100.0 * null_count / NULLIF(n.total, 0) >= 50 THEN 'SOFT GAP'
        ELSE 'OK'
    END AS status
FROM (
    SELECT 'roe_pct'                     AS metric, COUNT(*) FILTER (WHERE roe_pct IS NULL)                     AS null_count FROM latest UNION ALL
    SELECT 'debt_to_equity',                          COUNT(*) FILTER (WHERE debt_to_equity IS NULL)                                FROM latest UNION ALL
    SELECT 'eps_growth_3y_cagr_pct',                  COUNT(*) FILTER (WHERE eps_growth_3y_cagr_pct IS NULL)                        FROM latest UNION ALL
    SELECT 'earnings_consistency_score',              COUNT(*) FILTER (WHERE earnings_consistency_score IS NULL)                    FROM latest UNION ALL
    SELECT 'promoter_holding_pct',                    COUNT(*) FILTER (WHERE promoter_holding_pct IS NULL)                          FROM latest UNION ALL
    SELECT 'cap_bucket',                              COUNT(*) FILTER (WHERE cap_bucket IS NULL)                                    FROM latest UNION ALL
    SELECT 'revenue_growth_3y_cagr_pct',              COUNT(*) FILTER (WHERE revenue_growth_3y_cagr_pct IS NULL)                    FROM latest UNION ALL
    SELECT 'profit_margin_trend_pct',                 COUNT(*) FILTER (WHERE profit_margin_trend_pct IS NULL)                       FROM latest UNION ALL
    SELECT 'debt_trend_pct',                          COUNT(*) FILTER (WHERE debt_trend_pct IS NULL)                                FROM latest UNION ALL
    SELECT 'volatility_1y_pct',                       COUNT(*) FILTER (WHERE volatility_1y_pct IS NULL)                             FROM latest UNION ALL
    SELECT 'dividend_yield_pct',                      COUNT(*) FILTER (WHERE dividend_yield_pct IS NULL)                            FROM latest UNION ALL
    SELECT 'earnings_surprise_pct',                   COUNT(*) FILTER (WHERE earnings_surprise_pct IS NULL)                         FROM latest UNION ALL
    SELECT 'pe_overvaluation_pct',                    COUNT(*) FILTER (WHERE pe_overvaluation_pct IS NULL)                          FROM latest UNION ALL
    SELECT 'earnings_decline_flag',                   COUNT(*) FILTER (WHERE earnings_decline_flag IS NULL)                         FROM latest UNION ALL
    SELECT 'debt_spike_flag',                         COUNT(*) FILTER (WHERE debt_spike_flag IS NULL)                               FROM latest UNION ALL
    SELECT 'liquidity_score',                         COUNT(*) FILTER (WHERE liquidity_score IS NULL)                               FROM latest UNION ALL
    SELECT 'momentum_score',                          COUNT(*) FILTER (WHERE momentum_score IS NULL)                                FROM latest
) AS x
CROSS JOIN n
ORDER BY null_pct DESC NULLS LAST, metric;

-- 4. Date freshness check — flag stale daily snapshots
SELECT '── 4. SNAPSHOT FRESHNESS ──' AS report;
SELECT
    MAX(as_of_date)                                          AS latest_date,
    CURRENT_DATE - MAX(as_of_date)                           AS days_stale,
    CASE
        WHEN CURRENT_DATE - MAX(as_of_date) <= 1 THEN 'FRESH'
        WHEN CURRENT_DATE - MAX(as_of_date) <= 3 THEN 'WARN'
        ELSE 'STALE'
    END                                                      AS status
FROM nidp.v_v3_stock_primitives;
