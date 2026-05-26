-- Migration 070: Fix populate_stock_features_extended and populate_stock_features_v3
--
-- populate_stock_features_extended fixes:
--   1. v_sector_median_pe exposes 'median_pe' (not 'sector_median_pe'); subquery referenced
--      a non-existent column. Join directly on the view with as_of_date filter instead.
--   2. Round() on double precision argument from percentile_cont needs NUMERIC cast first.
--
-- populate_stock_features_v3 fix:
--   stock_features_daily has no 'volume' column; use avg_volume_20 as proxy.

-- ── Fix populate_stock_features_extended ──────────────────────────────────
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
 AS $function$
 DECLARE
     v_rows INTEGER;
 BEGIN
     -- ── Pass 1: fundamentals + shareholding + sector + new derived metrics ──
     UPDATE nidp.stock_features_daily f
        SET
            -- ── Existing metrics (unchanged) ─────────────────────────────
            pe_ttm                 = CASE WHEN fund.eps_ttm > 0 AND f.close > 0
                                          THEN ROUND((f.close / fund.eps_ttm)::NUMERIC, 4)
                                          ELSE NULL END,
            pb                     = CASE WHEN fund.total_equity_cr > 0 AND f.close > 0
                                          THEN ROUND((f.close / (fund.total_equity_cr * 1e7 / NULLIF(sm.face_value,0) / 1e7 * 1e7))::NUMERIC, 4)
                                          ELSE NULL END,
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

            -- ── Shares outstanding & market cap ─────────────────────────
            shares_outstanding = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0
                THEN ROUND((fund.equity_share_capital_cr * 1e7 / sm.face_value))::BIGINT
                ELSE NULL END,

            market_cap_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((fund.equity_share_capital_cr * f.close / sm.face_value)::NUMERIC, 2)
                ELSE NULL END,

            market_cap_bucket = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN (
                    CASE
                        WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 50000 THEN 'LARGE_CAP'
                        WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 10000 THEN 'MID_CAP'
                        WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >=  1000 THEN 'SMALL_CAP'
                        ELSE 'MICRO_CAP'
                    END
                )
                ELSE NULL END,

            -- ── Enterprise Value ─────────────────────────────────────────
            enterprise_value_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((
                    (fund.equity_share_capital_cr * f.close / sm.face_value)
                    + COALESCE(fund.long_term_debt_cr, 0)
                    + COALESCE(fund.short_term_debt_cr, 0)
                    - COALESCE(fund.cash_and_equiv_cr, 0)
                )::NUMERIC, 2)
                ELSE NULL END,

            -- ── EV/EBITDA ────────────────────────────────────────────────
            ev_ebitda = CASE
                WHEN fund.ebitda_ttm_cr > 0
                 AND fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((
                    (
                        (fund.equity_share_capital_cr * f.close / sm.face_value)
                        + COALESCE(fund.long_term_debt_cr, 0)
                        + COALESCE(fund.short_term_debt_cr, 0)
                        - COALESCE(fund.cash_and_equiv_cr, 0)
                    ) / fund.ebitda_ttm_cr
                )::NUMERIC, 2)
                ELSE NULL END,

            -- ── PE vs sector (overvaluation %) ───────────────────────────
            -- FIX: v_sector_median_pe exposes 'median_pe', not 'sector_median_pe'
            -- FIX: cast to NUMERIC before ROUND (percentile_cont returns double precision)
            pe_vs_sector_pct = CASE
                WHEN smp.median_pe > 0 AND fund.eps_ttm > 0 AND f.close > 0
                THEN ROUND((((f.close / fund.eps_ttm) / smp.median_pe - 1) * 100)::NUMERIC, 2)
                ELSE NULL END,

            -- ── ROCE ─────────────────────────────────────────────────────
            roce_pct = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.capital_employed_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.capital_employed_cr * 100)::NUMERIC, 2)
                ELSE NULL END,

            -- ── Interest Coverage ─────────────────────────────────────────
            interest_coverage = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL
                 AND fund.finance_costs_ttm_cr IS NOT NULL
                 AND fund.finance_costs_ttm_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.finance_costs_ttm_cr)::NUMERIC, 2)
                ELSE NULL END,

            -- ── Profit Margin ─────────────────────────────────────────────
            profit_margin_pct = CASE
                WHEN fund.pat_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
                THEN ROUND((fund.pat_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2)
                ELSE NULL END,

            -- ── Dividend Yield ────────────────────────────────────────────
            dividend_yield_pct = CASE
                WHEN f.close > 0 AND div.annual_dps IS NOT NULL AND div.annual_dps > 0
                THEN ROUND((div.annual_dps / f.close * 100)::NUMERIC, 4)
                ELSE 0 END

       FROM nidp.stock_features_daily f0
       LEFT JOIN nidp.v_stock_fundamentals_latest fund
              ON fund.symbol = f0.symbol
       LEFT JOIN nidp.v_shareholding_latest shp
              ON shp.symbol  = f0.symbol
       LEFT JOIN nidp.sector_master sm
              ON sm.symbol   = f0.symbol
       LEFT JOIN nidp.prices_eod_adjusted pea
              ON pea.symbol   = f0.symbol
             AND pea.as_of_date = f0.as_of_date
             AND pea.source  = 'NIDP_PRICE_ADJUSTER'
       -- FIX: join v_sector_median_pe directly (it has 'median_pe', not 'sector_median_pe')
       -- Also join on as_of_date to pick the correct period's sector PE
       LEFT JOIN nidp.v_sector_median_pe smp
              ON smp.sector = f0.sector
             AND smp.as_of_date = f0.as_of_date
       -- Dividend: sum ₹/share from corporate_actions in last 12 months
       LEFT JOIN LATERAL (
           SELECT COALESCE(SUM(dividend_amount), 0) AS annual_dps
             FROM nidp.corporate_actions
            WHERE symbol      = f0.symbol
              AND action_type = 'DIVIDEND'
              AND ex_date BETWEEN (p_target_date - INTERVAL '1 year') AND p_target_date
              AND dividend_amount > 0
       ) div ON TRUE
      WHERE f.symbol     = f0.symbol
        AND f.as_of_date = f0.as_of_date
        AND f.as_of_date = p_target_date;

     GET DIAGNOSTICS v_rows = ROW_COUNT;

     -- ── Pass 2: options aggregates (unchanged from migration 029) ────────
     UPDATE nidp.stock_features_daily f
        SET options_pcr           = opt.pcr,
            options_total_oi      = opt.total_oi,
            options_oi_change_pct = opt.oi_change_pct
       FROM (
         WITH nearest_exp AS (
             SELECT DISTINCT ON (ticker_symbol) ticker_symbol, expiry_date
               FROM nidp.fno_bhavcopy
              WHERE as_of_date = p_target_date
                AND option_type IN ('CE','PE')
                AND expiry_date >= p_target_date
              ORDER BY ticker_symbol, expiry_date ASC
         )
         SELECT
             f.ticker_symbol AS symbol,
             ROUND((SUM(CASE WHEN f.option_type='PE' THEN f.open_interest END)::NUMERIC
                  / NULLIF(SUM(CASE WHEN f.option_type='CE' THEN f.open_interest END), 0))::NUMERIC, 4) AS pcr,
             SUM(f.open_interest)::BIGINT AS total_oi,
             ROUND((SUM(f.change_in_oi)::NUMERIC
                  / NULLIF(SUM(f.open_interest) - SUM(f.change_in_oi), 0) * 100)::NUMERIC, 4) AS oi_change_pct
           FROM nidp.fno_bhavcopy f
           JOIN nearest_exp ne ON ne.ticker_symbol = f.ticker_symbol AND ne.expiry_date = f.expiry_date
          WHERE f.as_of_date = p_target_date AND f.option_type IN ('CE','PE')
          GROUP BY f.ticker_symbol
       ) opt
      WHERE f.symbol     = opt.symbol
        AND f.as_of_date = p_target_date;

     RETURN v_rows;
 END;
 $function$;


-- ── Fix populate_stock_features_v3 ────────────────────────────────────────
-- stock_features_daily has no 'volume' column; use avg_volume_20 as proxy.
DO $$
DECLARE
  func_src text;
  fixed_src text;
BEGIN
  SELECT pg_get_functiondef(oid) INTO func_src
  FROM pg_proc
  WHERE proname = 'populate_stock_features_v3'
    AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'nidp');

  IF func_src IS NULL THEN
    RAISE EXCEPTION 'populate_stock_features_v3 not found — run migration 054 first';
  END IF;

  fixed_src := replace(func_src, 'f.volume', 'f.avg_volume_20');
  EXECUTE fixed_src;
  RAISE NOTICE 'populate_stock_features_v3 updated: f.volume → f.avg_volume_20';
END;
$$;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('070_fix_populate_stock_features.sql')
ON CONFLICT (filename) DO NOTHING;
