-- Migration 071: Fix two formula bugs in v_stock_fundamentals_latest (introduced in 069)
--
-- Bug 1 — roe_annualised_pct used revenue as denominator (= profit margin, not ROE).
--          Fix: divide pat_ttm_cr by total_equity_cr.
--
-- Bug 2 — debt_to_equity and capital_employed_cr propagated NULL when
--          short_term_debt_cr is NULL (always the case for screener_in rows).
--          Fix: COALESCE both debt columns to 0 in those expressions.
--
-- v_stock_features_full depends on v_stock_fundamentals_latest via DROP CASCADE,
-- so we recreate it at the end (identical definition to migration 069/070).

DROP VIEW IF EXISTS nidp.v_stock_features_full;
DROP VIEW IF EXISTS nidp.v_stock_fundamentals_latest;

CREATE VIEW nidp.v_stock_fundamentals_latest AS
WITH ranked AS (
    SELECT f.*,
           ROW_NUMBER() OVER (PARTITION BY f.symbol ORDER BY f.consolidated DESC, f.period_end DESC) AS rn,
           ROW_NUMBER() OVER (PARTITION BY f.symbol, f.period_type ORDER BY f.period_end DESC) AS rn_back
      FROM nidp.nse_financials_quarterly f
     WHERE f.period_type ILIKE 'QUARTERLY'
),
ttm AS (
    SELECT symbol,
           SUM(revenue_from_ops_cr) FILTER (WHERE rn_back <= 4) AS revenue_ttm_cr,
           SUM(pat_cr)              FILTER (WHERE rn_back <= 4) AS pat_ttm_cr,
           SUM(eps_basic)           FILTER (WHERE rn_back <= 4) AS eps_ttm,
           SUM(ebitda_cr)           FILTER (WHERE rn_back <= 4) AS ebitda_ttm_cr,
           SUM(depreciation_cr)     FILTER (WHERE rn_back <= 4) AS depreciation_ttm_cr,
           SUM(finance_costs_cr)    FILTER (WHERE rn_back <= 4) AS finance_costs_ttm_cr,
           SUM(pbt_cr)              FILTER (WHERE rn_back <= 4) AS pbt_ttm_cr
      FROM ranked
     GROUP BY symbol
),
prior_year AS (
    SELECT DISTINCT ON (c.symbol)
           c.symbol,
           c.period_end AS current_period,
           p.revenue_from_ops_cr AS py_revenue,
           p.pat_cr              AS py_pat,
           p.eps_basic           AS py_eps
      FROM ranked c
      JOIN nidp.nse_financials_quarterly p
        ON p.symbol = c.symbol
       AND p.period_type ILIKE 'QUARTERLY'
       AND p.consolidated = c.consolidated
       AND p.period_end = (c.period_end - INTERVAL '1 year')::date
     WHERE c.rn = 1
     ORDER BY c.symbol
)
SELECT r.symbol,
       r.period_end,
       r.period_type,
       r.consolidated,
       r.revenue_from_ops_cr,
       r.pat_cr,
       r.eps_basic,
       r.eps_diluted,
       r.face_value,
       r.ebitda_cr,
       r.finance_costs_cr,
       r.depreciation_cr,
       r.total_equity_cr,
       r.long_term_debt_cr,
       r.short_term_debt_cr,
       r.cash_and_equiv_cr,
       r.equity_share_capital_cr,
       t.revenue_ttm_cr,
       t.pat_ttm_cr,
       t.eps_ttm,
       t.ebitda_ttm_cr,
       t.depreciation_ttm_cr,
       t.finance_costs_ttm_cr,
       t.pbt_ttm_cr,
       (t.ebitda_ttm_cr - t.depreciation_ttm_cr)                                       AS ebit_ttm_cr,
       -- FIX (bug 2): COALESCE debt columns so NULL short_term_debt doesn't null-out result
       (COALESCE(r.total_equity_cr, 0)
        + COALESCE(r.long_term_debt_cr, 0)
        + COALESCE(r.short_term_debt_cr, 0))                                            AS capital_employed_cr,
       -- FIX (bug 1): ROE = PAT / Equity, not PAT / Revenue
       CASE WHEN r.total_equity_cr > 0 AND t.pat_ttm_cr IS NOT NULL
            THEN ROUND((t.pat_ttm_cr / r.total_equity_cr * 100)::numeric, 4)
       END                                                                               AS roe_annualised_pct,
       -- FIX (bug 2): COALESCE debt columns — short_term_debt_cr is NULL for screener_in rows
       CASE WHEN r.total_equity_cr > 0
            THEN ROUND(((COALESCE(r.long_term_debt_cr, 0) + COALESCE(r.short_term_debt_cr, 0))
                        / r.total_equity_cr)::numeric, 4)
       END                                                                               AS debt_to_equity,
       CASE
           WHEN py.py_revenue > 0 AND r.revenue_from_ops_cr IS NOT NULL
           THEN ROUND(((r.revenue_from_ops_cr - py.py_revenue) / py.py_revenue * 100)::numeric, 4)
       END AS revenue_growth_yoy_pct,
       CASE
           WHEN py.py_pat > 0 AND r.pat_cr IS NOT NULL
           THEN ROUND(((r.pat_cr - py.py_pat) / py.py_pat * 100)::numeric, 4)
       END AS pat_growth_yoy_pct,
       CASE
           WHEN py.py_eps > 0 AND r.eps_basic IS NOT NULL
           THEN ROUND(((r.eps_basic - py.py_eps) / py.py_eps * 100)::numeric, 4)
       END AS eps_growth_yoy_pct,
       r.broadcast_at,
       r.source_run_id
  FROM ranked r
  LEFT JOIN ttm t         ON t.symbol = r.symbol
  LEFT JOIN prior_year py ON py.symbol = r.symbol
 WHERE r.rn = 1;


-- Recreate v_stock_features_full (dropped by CASCADE above; identical to 069/070)
CREATE OR REPLACE VIEW nidp.v_stock_features_full AS
SELECT
    f.*,
    fund.revenue_ttm_cr,
    fund.pat_ttm_cr,
    fund.eps_ttm,
    fund.total_equity_cr,
    fund.long_term_debt_cr,
    fund.short_term_debt_cr,
    fund.cash_and_equiv_cr,
    fund.equity_share_capital_cr,
    fund.ebitda_ttm_cr,
    fund.ebit_ttm_cr,
    fund.capital_employed_cr,
    fund.finance_costs_ttm_cr,
    shp.insurance_pct,
    shp.individual_pct,
    shp.mf_pct_change_qoq,
    shp.pledge_pct_change_qoq,
    sm.isin,
    sm.listing_date,
    sm.face_value
  FROM nidp.stock_features_daily f
  LEFT JOIN nidp.v_stock_fundamentals_latest fund ON fund.symbol = f.symbol
  LEFT JOIN nidp.v_shareholding_latest shp         ON shp.symbol  = f.symbol
  LEFT JOIN nidp.sector_master sm                  ON sm.symbol   = f.symbol;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('071_fix_view_roe_debt_equity.sql')
ON CONFLICT (filename) DO NOTHING;
