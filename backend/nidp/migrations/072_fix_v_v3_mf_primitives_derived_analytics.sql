-- Migration 072: Fix v_v3_mf_primitives
--
-- Two problems introduced when migration 058 rewrote the view as isin-keyed:
--
-- 1. The mf_derived_analytics JOIN was omitted entirely.
--    Missing columns (all NULL for every scheme):
--      consistency_score      → quality: consistency (20% weight)
--      downside_capture_pct   → health: downside_protection (15%)
--      aum_trend_score        → health: aum_stability (20%)
--      portfolio_turnover_pct → health: turnover (15%)
--
-- 2. manager_tenure_years has no fallback when mf_scheme_events is empty
--    (it currently has 0 rows for 'manager_change' events).
--    Fix: COALESCE to mf_scheme_master.launch_date so all schemes with a
--    known launch date get a proxy tenure.
--
-- Net effect: MF health score goes from 0% coverage → ~35–60% immediately,
-- using data already in mf_derived_analytics (consistency for ~7.7k schemes).

CREATE OR REPLACE VIEW nidp.v_v3_mf_primitives AS
WITH latest_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        category,
        sub_category,
        scheme_launch_date,
        return_1y,
        return_3y,
        return_5y,
        return_1m,
        return_3m,
        return_6m,
        return_2y,
        return_since_launch_cagr,
        sharpe_1y,
        sortino_1y,
        max_drawdown_1y,
        alpha_1y,
        beta_1y,
        volatility_1y,
        return_1y_rank,
        composite_rank
      FROM analytics.fund_category_rank
     ORDER BY scheme_code, rank_date DESC
),
cat_avg AS (
    SELECT
        category,
        AVG(return_1y) AS cat_avg_1y,
        AVG(return_3y) AS cat_avg_3y,
        AVG(return_5y) AS cat_avg_5y
      FROM (
          SELECT DISTINCT ON (scheme_code)
              category,
              return_1y,
              return_3y,
              return_5y
            FROM analytics.fund_category_rank
           ORDER BY scheme_code, rank_date DESC
      ) latest_per_scheme
     GROUP BY category
),
latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct  AS ter_direct,
        ter_pct         AS ter_regular,
        aum_inr_crore   AS aum_cr,
        primary_manager,
        risk_o_meter
      FROM nidp.mf_scheme_disclosure_snapshot
     ORDER BY scheme_code, snapshot_date DESC
),
snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct AS ter_direct_3y,
        ter_pct        AS ter_regular_3y
      FROM nidp.mf_scheme_disclosure_snapshot
     WHERE snapshot_date <= NOW() - INTERVAL '3 years'
     ORDER BY scheme_code, snapshot_date DESC
),
manager_tenure AS (
    SELECT
        scheme_code,
        MAX(event_date) AS manager_since_date
      FROM nidp.mf_scheme_events
     WHERE event_type = 'manager_change'
     GROUP BY scheme_code
),
top10_conc AS (
    SELECT
        r.scheme_code,
        SUM(r.weight_pct) AS top10_concentration_pct
      FROM (
          SELECT
              scheme_code,
              weight_pct,
              ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY weight_pct DESC) AS rn
            FROM (
                SELECT DISTINCT ON (scheme_code, security_isin)
                    scheme_code,
                    security_isin,
                    weight_pct
                  FROM nidp.mf_holdings_monthly
                 WHERE security_isin IS NOT NULL
                 ORDER BY scheme_code, security_isin, as_of_month DESC
            ) ranked
      ) r
     WHERE r.rn <= 10
     GROUP BY r.scheme_code
),
-- Proxy launch date from first NAV observation (mf_scheme_master.launch_date is NULL for all rows)
first_nav AS (
    SELECT scheme_code, MIN(nav_date) AS first_nav_date
      FROM nidp.mf_nav_daily
     GROUP BY scheme_code
),
-- NEW: join mf_derived_analytics for consistency, downside, aum_trend, turnover
nidp_derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        consistency_score,
        downside_capture_pct,
        aum_trend_score,
        portfolio_turnover_pct AS turnover_ratio
      FROM nidp.mf_derived_analytics
     ORDER BY scheme_code, as_of_date DESC
),
scheme_isins AS (
    SELECT
        ms.scheme_code,
        ms.scheme_name,
        ms.launch_date,
        i.isin
      FROM nidp.mf_scheme_master ms,
      LATERAL (SELECT UNNEST(ARRAY[ms.isin_growth, ms.isin_idcw]) AS isin) i
     WHERE i.isin IS NOT NULL AND i.isin <> ''
)
SELECT
    si.isin,
    si.scheme_code,
    si.scheme_name,
    lr.category,
    lr.sub_category,
    sn.aum_cr,
    CASE
        WHEN COALESCE(lr.scheme_launch_date, si.launch_date) IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM NOW() - COALESCE(lr.scheme_launch_date, si.launch_date)::TIMESTAMPTZ) / 86400.0 / 365.25, 2)
        ELSE NULL
    END                                                                     AS fund_age_years,
    sn.ter_direct                                                           AS expense_ratio_direct,
    sn.ter_regular                                                          AS expense_ratio_regular,
    COALESCE(sn.ter_direct, sn.ter_regular)                                 AS expense_ratio,
    CASE
        WHEN sn.ter_direct   IS NOT NULL AND s3.ter_direct_3y  IS NOT NULL THEN ROUND(sn.ter_direct  - s3.ter_direct_3y,  4)
        WHEN sn.ter_regular  IS NOT NULL AND s3.ter_regular_3y IS NOT NULL THEN ROUND(sn.ter_regular - s3.ter_regular_3y, 4)
        ELSE NULL
    END                                                                     AS expense_trend_delta,
    -- FIX: fall back to first NAV date when no manager_change event exists
    -- (mf_scheme_master.launch_date is NULL for all rows; use mf_nav_daily MIN as proxy)
    CASE
        WHEN mt.manager_since_date IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM NOW() - mt.manager_since_date::TIMESTAMPTZ) / 86400.0 / 365.25, 2)
        WHEN fn.first_nav_date IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM NOW() - fn.first_nav_date::TIMESTAMPTZ)     / 86400.0 / 365.25, 2)
        ELSE NULL
    END                                                                     AS manager_tenure_years,
    t10.top10_concentration_pct,
    ca.cat_avg_1y                                                           AS category_avg_1y,
    ca.cat_avg_3y                                                           AS category_avg_3y,
    ca.cat_avg_5y                                                           AS category_avg_5y,
    lr.max_drawdown_1y                                                      AS max_drawdown_pct,
    lr.return_1y                                                            AS ret_1y,
    lr.return_3y                                                            AS ret_3y,
    lr.return_5y                                                            AS ret_5y,
    lr.sharpe_1y                                                            AS sharpe,
    lr.sortino_1y                                                           AS sortino,
    lr.return_1m,
    lr.return_3m,
    lr.return_6m,
    lr.return_2y,
    lr.return_since_launch_cagr,
    lr.alpha_1y,
    lr.beta_1y,
    lr.volatility_1y,
    lr.composite_rank                                                       AS category_rank,
    lr.return_1y_rank,
    lr.return_1y IS NOT NULL                                                AS nidp_returns_available,
    sn.scheme_code IS NOT NULL                                              AS nidp_snapshot_available,
    t10.scheme_code IS NOT NULL                                             AS nidp_holdings_available,
    sn.primary_manager,
    sn.risk_o_meter,
    -- NEW columns from mf_derived_analytics:
    nd.consistency_score,
    nd.downside_capture_pct,
    nd.aum_trend_score,
    nd.turnover_ratio
  FROM scheme_isins si
  LEFT JOIN latest_rank lr ON lr.scheme_code = si.scheme_code
  LEFT JOIN cat_avg      ca ON ca.category    = lr.category
  LEFT JOIN latest_snap  sn ON sn.scheme_code = si.scheme_code
  LEFT JOIN snap_3y_ago  s3 ON s3.scheme_code = si.scheme_code
  LEFT JOIN manager_tenure mt ON mt.scheme_code = si.scheme_code
  LEFT JOIN top10_conc   t10 ON t10.scheme_code = si.scheme_code
  LEFT JOIN nidp_derived nd  ON nd.scheme_code  = si.scheme_code
  LEFT JOIN first_nav    fn  ON fn.scheme_code  = si.scheme_code;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('072_fix_v_v3_mf_primitives_derived_analytics.sql')
ON CONFLICT (filename) DO NOTHING;
