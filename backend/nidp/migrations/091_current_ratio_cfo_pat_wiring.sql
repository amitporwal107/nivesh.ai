-- Migration 091: Wire current_ratio + cfo_pat_ratio into stock_features_daily
--
-- Data already exists:
--   - current_assets_cr / current_liabilities_cr in nse_financials_quarterly (annual rows)
--   - cfo_cr in nse_financials_cashflow (annual rows)
--
-- Steps:
--   1. Add current_ratio + cfo_pat_ratio columns to stock_features_daily
--   2. Recreate v_stock_fundamentals_latest with new CTEs for annual BS + cashflow
--   3. Update populate_stock_features_extended to fill the new columns

-- ── 1. New columns ────────────────────────────────────────────────────────
ALTER TABLE nidp.stock_features_daily
    ADD COLUMN IF NOT EXISTS current_ratio  NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS cfo_pat_ratio  NUMERIC(10,2);

-- ── 2. Recreate v_stock_fundamentals_latest ───────────────────────────────
-- CASCADE also drops v_stock_features_full which depends on this view; recreated below
DROP VIEW IF EXISTS nidp.v_stock_fundamentals_latest CASCADE;
CREATE VIEW nidp.v_stock_fundamentals_latest AS
WITH ranked AS (
    SELECT f.*,
           row_number() OVER (PARTITION BY f.symbol
                              ORDER BY f.consolidated DESC, f.period_end DESC) AS rn,
           row_number() OVER (PARTITION BY f.symbol, f.period_type
                              ORDER BY f.period_end DESC) AS rn_back
      FROM nidp.nse_financials_quarterly f
     WHERE f.period_type ILIKE 'QUARTERLY'
),
ttm AS (
    SELECT symbol,
           SUM(revenue_from_ops_cr)  FILTER (WHERE rn_back <= 4) AS revenue_ttm_cr,
           SUM(pat_cr)               FILTER (WHERE rn_back <= 4) AS pat_ttm_cr,
           SUM(eps_basic)            FILTER (WHERE rn_back <= 4) AS eps_ttm,
           SUM(ebitda_cr)            FILTER (WHERE rn_back <= 4) AS ebitda_ttm_cr,
           SUM(depreciation_cr)      FILTER (WHERE rn_back <= 4) AS depreciation_ttm_cr,
           SUM(finance_costs_cr)     FILTER (WHERE rn_back <= 4) AS finance_costs_ttm_cr,
           SUM(pbt_cr)               FILTER (WHERE rn_back <= 4) AS pbt_ttm_cr
      FROM ranked
     GROUP BY symbol
),
prior_year AS (
    SELECT c.symbol,
           p.revenue_from_ops_cr AS py_revenue,
           p.pat_cr              AS py_pat,
           p.eps_basic           AS py_eps
      FROM ranked c
      JOIN nidp.nse_financials_quarterly p
        ON p.symbol      = c.symbol
       AND p.period_type ILIKE 'QUARTERLY'
       AND p.consolidated = c.consolidated
       AND p.period_end  = (c.period_end - INTERVAL '1 year')::date
     WHERE c.rn = 1
     ORDER BY c.symbol
),
-- Latest annual balance sheet (current assets/liabilities from backfill)
bs_annual AS (
    SELECT DISTINCT ON (symbol)
        symbol, current_assets_cr, current_liabilities_cr
      FROM nidp.nse_financials_quarterly
     WHERE period_type = 'annual'
       AND (current_assets_cr IS NOT NULL OR current_liabilities_cr IS NOT NULL)
     ORDER BY symbol, period_end DESC
),
-- Latest annual cashflow
cf_annual AS (
    SELECT DISTINCT ON (symbol)
        symbol, cfo_cr
      FROM nidp.nse_financials_cashflow
     ORDER BY symbol, period_end DESC
)
SELECT
    r.symbol,
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
    t.ebitda_ttm_cr - t.depreciation_ttm_cr                          AS ebit_ttm_cr,
    COALESCE(r.total_equity_cr, 0)
        + COALESCE(r.long_term_debt_cr, 0)
        + COALESCE(r.short_term_debt_cr, 0)                           AS capital_employed_cr,
    CASE WHEN r.total_equity_cr > 0 AND t.pat_ttm_cr IS NOT NULL
         THEN ROUND(t.pat_ttm_cr / r.total_equity_cr * 100, 4) END    AS roe_annualised_pct,
    CASE WHEN r.total_equity_cr > 0
         THEN ROUND((COALESCE(r.long_term_debt_cr,0)
                   + COALESCE(r.short_term_debt_cr,0))
                   / r.total_equity_cr, 4) END                         AS debt_to_equity,
    CASE WHEN py.py_revenue > 0 AND r.revenue_from_ops_cr IS NOT NULL
         THEN ROUND((r.revenue_from_ops_cr - py.py_revenue)
                   / py.py_revenue * 100, 4) END                       AS revenue_growth_yoy_pct,
    CASE WHEN py.py_pat > 0 AND r.pat_cr IS NOT NULL
         THEN ROUND((r.pat_cr - py.py_pat) / py.py_pat * 100, 4) END  AS pat_growth_yoy_pct,
    CASE WHEN py.py_eps > 0 AND r.eps_basic IS NOT NULL
         THEN ROUND((r.eps_basic - py.py_eps) / py.py_eps * 100, 4) END AS eps_growth_yoy_pct,
    r.broadcast_at,
    r.source_run_id,
    -- New: annual balance sheet items
    ba.current_assets_cr,
    ba.current_liabilities_cr,
    -- New: latest annual CFO
    cf.cfo_cr,
    -- New: derived ratios (appended at end to satisfy CREATE OR REPLACE column-order rules)
    CASE WHEN ba.current_liabilities_cr > 0 AND ba.current_assets_cr IS NOT NULL
         THEN ROUND(ba.current_assets_cr / ba.current_liabilities_cr, 2) END AS current_ratio,
    CASE WHEN t.pat_ttm_cr <> 0 AND t.pat_ttm_cr IS NOT NULL AND cf.cfo_cr IS NOT NULL
         THEN ROUND(cf.cfo_cr / t.pat_ttm_cr, 2) END                        AS cfo_pat_ratio
  FROM ranked r
  LEFT JOIN ttm         t  ON t.symbol  = r.symbol
  LEFT JOIN prior_year  py ON py.symbol = r.symbol
  LEFT JOIN bs_annual   ba ON ba.symbol = r.symbol
  LEFT JOIN cf_annual   cf ON cf.symbol = r.symbol
 WHERE r.rn = 1;

-- ── 3. Update populate_stock_features_extended to fill the new columns ────
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
 AS $function$
 DECLARE v_rows INTEGER; BEGIN
     UPDATE nidp.stock_features_daily f
        SET
            pe_ttm                 = CASE WHEN fund.eps_ttm > 0 AND f.close > 0
                                          THEN ROUND((f.close / fund.eps_ttm)::NUMERIC, 4) ELSE NULL END,
            pb                     = CASE WHEN fund.total_equity_cr > 0 AND f.close > 0
                                          THEN ROUND((f.close / (fund.total_equity_cr * 1e7 / NULLIF(sm.face_value,0) / 1e7 * 1e7))::NUMERIC, 4) ELSE NULL END,
            roe_pct                = fund.roe_annualised_pct,
            debt_to_equity         = fund.debt_to_equity,
            revenue_growth_yoy_pct = fund.revenue_growth_yoy_pct,
            pat_growth_yoy_pct     = fund.pat_growth_yoy_pct,
            eps_growth_yoy_pct     = fund.eps_growth_yoy_pct,
            latest_quarter_end     = fund.period_end,
            promoter_pct              = shp.promoter_pct,
            fii_pct                   = shp.fii_pct,
            dii_pct                   = shp.dii_pct,
            mf_pct                    = shp.mf_pct,
            promoter_pledged_pct      = shp.promoter_pledged_to_total_pct,
            fii_pct_change_qoq        = shp.fii_pct_change_qoq,
            dii_pct_change_qoq        = shp.dii_pct_change_qoq,
            promoter_pct_change_qoq   = shp.promoter_pct_change_qoq,
            shareholding_period_end   = shp.period_end,
            sector   = sm.sector,
            industry = sm.industry,
            cumulative_adj_factor = pea.cumulative_adj_factor,
            adj_close             = pea.adj_close,
            shares_outstanding = CASE
                WHEN fund.equity_share_capital_cr IS NOT NULL AND sm.face_value > 0
                THEN ROUND((fund.equity_share_capital_cr * 1e7 / sm.face_value)::NUMERIC, 0) ELSE NULL END,
            market_cap_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((fund.equity_share_capital_cr * f.close / sm.face_value)::NUMERIC, 2) ELSE NULL END,
            market_cap_bucket = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN CASE
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 50000 THEN 'LARGE_CAP'
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 10000 THEN 'MID_CAP'
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >=  1000 THEN 'SMALL_CAP'
                    ELSE 'MICRO_CAP' END ELSE NULL END,
            enterprise_value_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((
                    (fund.equity_share_capital_cr * f.close / sm.face_value)
                    + COALESCE(fund.long_term_debt_cr, 0)
                    + COALESCE(fund.short_term_debt_cr, 0)
                    - COALESCE(fund.cash_and_equiv_cr, 0)
                )::NUMERIC, 2) ELSE NULL END,
            ev_ebitda = CASE
                WHEN fund.ebitda_ttm_cr > 0 AND fund.equity_share_capital_cr > 0
                 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND(((
                    (fund.equity_share_capital_cr * f.close / sm.face_value)
                    + COALESCE(fund.long_term_debt_cr, 0)
                    + COALESCE(fund.short_term_debt_cr, 0)
                    - COALESCE(fund.cash_and_equiv_cr, 0)
                ) / fund.ebitda_ttm_cr)::NUMERIC, 2) ELSE NULL END,
            pe_vs_sector_pct = CASE
                WHEN f.close > 0 AND fund.eps_ttm > 0 AND sec.median_pe > 0
                THEN ROUND(((f.close / fund.eps_ttm - sec.median_pe) / sec.median_pe * 100)::NUMERIC, 2) ELSE NULL END,
            roce_pct = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.capital_employed_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.capital_employed_cr * 100)::NUMERIC, 2) ELSE NULL END,
            interest_coverage = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.finance_costs_ttm_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.finance_costs_ttm_cr)::NUMERIC, 2) ELSE NULL END,
            profit_margin_pct = CASE
                WHEN fund.pat_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
                THEN ROUND((fund.pat_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2) ELSE NULL END,
            operating_margin_pct = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2) ELSE NULL END,
            free_float_pct = CASE
                WHEN shp.promoter_pct IS NOT NULL
                THEN ROUND((100.0 - shp.promoter_pct)::NUMERIC, 2) ELSE NULL END,
            current_ratio  = fund.current_ratio,
            cfo_pat_ratio  = fund.cfo_pat_ratio,
            dividend_yield_pct = CASE
                WHEN f.close > 0 AND div.annual_dps IS NOT NULL AND div.annual_dps > 0
                THEN ROUND((div.annual_dps / f.close * 100)::NUMERIC, 4)
                ELSE 0 END
       FROM nidp.stock_features_daily f0
       LEFT JOIN nidp.v_stock_fundamentals_latest fund ON fund.symbol  = f0.symbol
       LEFT JOIN nidp.v_shareholding_latest        shp  ON shp.symbol  = f0.symbol
       LEFT JOIN nidp.sector_master                sm   ON sm.symbol   = f0.symbol
       LEFT JOIN nidp.prices_eod_adjusted          pea
              ON pea.symbol = f0.symbol AND pea.as_of_date = p_target_date
             AND pea.source = 'NIDP_PRICE_ADJUSTER'
       LEFT JOIN nidp.v_sector_median_pe            sec
              ON sec.sector = sm.sector AND sec.as_of_date = p_target_date
       LEFT JOIN (
           SELECT symbol,
                  COALESCE(SUM(dividend_amount), 0) AS annual_dps
             FROM nidp.corporate_actions
            WHERE action_type = 'DIVIDEND'
              AND ex_date >= CURRENT_DATE - 365
              AND dividend_amount > 0
            GROUP BY symbol
       ) div ON div.symbol = f0.symbol
      WHERE f0.symbol = f.symbol AND f0.as_of_date = p_target_date;
     GET DIAGNOSTICS v_rows = ROW_COUNT;
     RETURN v_rows;
 END;
 $function$;

-- ── 4. Recreate v_stock_features_full (dropped by CASCADE above) ──────────
CREATE VIEW nidp.v_stock_features_full AS
 SELECT f.symbol, f.as_of_date, f.close, f.sma20, f.sma50, f.sma100, f.sma200,
        f.sma50_slope, f.dist_200dma_pct, f.dist_52w_high_pct, f.dist_52w_low_pct,
        f.rsi14, f.macd, f.macd_signal, f.macd_hist,
        f.return_5d_pct, f.return_20d_pct, f.return_60d_pct,
        f.atr14, f.atr_pct, f.bb_width, f.bb_pos, f.avg_volume_20, f.vol_z20,
        f.deliv_pct_avg_20, f.deliv_trend10, f.swing_high_20, f.swing_low_20,
        f.pivot_breakout_flag, f.accumulation_score, f.accumulation_signals,
        f.pe_ttm, f.pb, f.roe_pct, f.debt_to_equity,
        f.revenue_growth_yoy_pct, f.pat_growth_yoy_pct, f.eps_growth_yoy_pct,
        f.latest_quarter_end, f.promoter_pct, f.fii_pct, f.dii_pct, f.mf_pct,
        f.promoter_pledged_pct, f.fii_pct_change_qoq, f.dii_pct_change_qoq,
        f.promoter_pct_change_qoq, f.shareholding_period_end,
        f.sector, f.industry, f.cumulative_adj_factor, f.adj_close,
        f.options_pcr, f.options_total_oi, f.options_oi_change_pct,
        f.piotroski_score, f.piotroski_signals, f.altman_z_score, f.valuation_signal,
        f.sector_median_pe, f.shares_outstanding, f.market_cap_cr, f.market_cap_bucket,
        f.enterprise_value_cr, f.ev_ebitda, f.pe_vs_sector_pct, f.roce_pct,
        f.interest_coverage, f.profit_margin_pct, f.dividend_yield_pct,
        f.return_252d_pct, f.volatility_1y_pct, f.beta_1y, f.max_drawdown_1y_pct,
        f.eps_growth_3y_cagr_pct, f.revenue_growth_3y_cagr_pct,
        f.profit_margin_trend_pct, f.debt_trend_pct,
        f.earnings_decline_flag, f.debt_spike_flag,
        f.momentum_score, f.liquidity_score, f.earnings_consistency_score,
        fund.revenue_ttm_cr, fund.pat_ttm_cr, fund.eps_ttm,
        fund.total_equity_cr, fund.long_term_debt_cr, fund.short_term_debt_cr,
        fund.cash_and_equiv_cr, fund.equity_share_capital_cr,
        fund.ebitda_ttm_cr, fund.ebit_ttm_cr, fund.capital_employed_cr,
        fund.finance_costs_ttm_cr,
        shp.insurance_pct, shp.individual_pct, shp.mf_pct_change_qoq, shp.pledge_pct_change_qoq,
        sm.isin, sm.listing_date, sm.face_value
   FROM nidp.stock_features_daily f
   LEFT JOIN nidp.v_stock_fundamentals_latest fund ON fund.symbol = f.symbol
   LEFT JOIN nidp.v_shareholding_latest        shp  ON shp.symbol = f.symbol
   LEFT JOIN nidp.sector_master                sm   ON sm.symbol  = f.symbol;
