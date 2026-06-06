-- Migration 090: Screener.in balance sheet + cashflow ingestion
--
-- 1. Add missing balance sheet columns to nse_financials_quarterly
--    (cash_and_equiv_cr + short_term_debt_cr already exist — add current/working-capital items)
-- 2. Create nidp.nse_financials_cashflow for annual CFO/capex data
-- 3. Add operating_margin_pct + free_float_pct to stock_features_daily
-- 4. Update populate_stock_features_extended() to compute both new columns

-- ── 1. Balance sheet columns on nse_financials_quarterly ──────────────────
ALTER TABLE nidp.nse_financials_quarterly
    ADD COLUMN IF NOT EXISTS current_assets_cr      NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS current_liabilities_cr NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS trade_receivables_cr   NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS inventory_cr           NUMERIC(18,4),
    ADD COLUMN IF NOT EXISTS trade_payables_cr      NUMERIC(18,4);

-- ── 2. Annual cashflow table ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.nse_financials_cashflow (
    id                 BIGSERIAL    PRIMARY KEY,
    symbol             TEXT         NOT NULL,
    period_end         DATE         NOT NULL,
    consolidated       BOOLEAN      NOT NULL DEFAULT FALSE,
    cfo_cr             NUMERIC(18,4),   -- Cash from Operating Activity
    cfi_cr             NUMERIC(18,4),   -- Cash from Investing Activity
    cff_cr             NUMERIC(18,4),   -- Cash from Financing Activity
    capex_cr           NUMERIC(18,4),   -- Capital Expenditure (negative = outflow)
    net_change_cash_cr NUMERIC(18,4),   -- Net change in cash & equivalents
    source             TEXT,
    source_run_id      UUID,
    ingested_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_cashflow UNIQUE (symbol, period_end, consolidated)
);

CREATE INDEX IF NOT EXISTS idx_cashflow_symbol
    ON nidp.nse_financials_cashflow (symbol, period_end DESC);

-- ── 3. New derived columns on stock_features_daily ────────────────────────
ALTER TABLE nidp.stock_features_daily
    ADD COLUMN IF NOT EXISTS operating_margin_pct NUMERIC(10,2),
    ADD COLUMN IF NOT EXISTS free_float_pct        NUMERIC(10,2);

-- ── 4. Update populate_stock_features_extended to fill new columns ─────────
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
 AS $function$
 DECLARE
     v_rows INTEGER;
 BEGIN
     UPDATE nidp.stock_features_daily f
        SET
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

            shares_outstanding = CASE
                WHEN fund.equity_share_capital_cr IS NOT NULL AND sm.face_value > 0
                THEN ROUND((fund.equity_share_capital_cr * 1e7 / sm.face_value)::NUMERIC, 0)
                ELSE NULL END,

            market_cap_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((fund.equity_share_capital_cr * f.close / sm.face_value)::NUMERIC, 2)
                ELSE NULL END,

            market_cap_bucket = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN CASE
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 50000 THEN 'LARGE_CAP'
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >= 10000 THEN 'MID_CAP'
                    WHEN (fund.equity_share_capital_cr * f.close / sm.face_value) >=  1000 THEN 'SMALL_CAP'
                    ELSE 'MICRO_CAP'
                END
                ELSE NULL END,

            enterprise_value_cr = CASE
                WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
                THEN ROUND((
                    (fund.equity_share_capital_cr * f.close / sm.face_value)
                    + COALESCE(fund.long_term_debt_cr, 0)
                    + COALESCE(fund.short_term_debt_cr, 0)
                    - COALESCE(fund.cash_and_equiv_cr, 0)
                )::NUMERIC, 2)
                ELSE NULL END,

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

            pe_vs_sector_pct = CASE
                WHEN f.close > 0 AND fund.eps_ttm > 0 AND sec.median_pe > 0
                THEN ROUND(((f.close / fund.eps_ttm - sec.median_pe) / sec.median_pe * 100)::NUMERIC, 2)
                ELSE NULL END,

            roce_pct = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.capital_employed_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.capital_employed_cr * 100)::NUMERIC, 2)
                ELSE NULL END,

            interest_coverage = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.finance_costs_ttm_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.finance_costs_ttm_cr)::NUMERIC, 2)
                ELSE NULL END,

            -- Net margin (PAT / Revenue) — kept for backwards compatibility
            profit_margin_pct = CASE
                WHEN fund.pat_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
                THEN ROUND((fund.pat_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2)
                ELSE NULL END,

            -- Operating margin (EBIT / Revenue) — the correct profitability measure
            operating_margin_pct = CASE
                WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
                THEN ROUND((fund.ebit_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2)
                ELSE NULL END,

            -- Free float: 100% minus promoter holding (standard Indian market definition)
            free_float_pct = CASE
                WHEN shp.promoter_pct IS NOT NULL
                THEN ROUND((100.0 - shp.promoter_pct)::NUMERIC, 2)
                ELSE NULL END,

            dividend_yield_pct = CASE
                WHEN f.close > 0 AND div.annual_dps IS NOT NULL AND div.annual_dps > 0
                THEN ROUND((div.annual_dps / f.close * 100)::NUMERIC, 4)
                ELSE 0 END

       FROM nidp.stock_features_daily f0
       LEFT JOIN nidp.v_stock_fundamentals_latest fund ON fund.symbol  = f0.symbol
       LEFT JOIN nidp.v_shareholding_latest        shp  ON shp.symbol  = f0.symbol
       LEFT JOIN nidp.sector_master                sm   ON sm.symbol   = f0.symbol
       LEFT JOIN nidp.prices_eod_adjusted          pea
              ON pea.symbol = f0.symbol
             AND pea.as_of_date = p_target_date
             AND pea.source = 'NIDP_PRICE_ADJUSTER'
       LEFT JOIN nidp.v_sector_median_pe            sec
              ON sec.sector    = sm.sector
             AND sec.as_of_date = p_target_date
       LEFT JOIN (
           SELECT symbol,
                  COALESCE(SUM(dividend_amount), 0) AS annual_dps
             FROM nidp.corporate_actions
            WHERE action_type = 'DIVIDEND'
              AND ex_date >= CURRENT_DATE - 365
              AND dividend_amount > 0
            GROUP BY symbol
       ) div ON div.symbol = f0.symbol
      WHERE f0.symbol = f.symbol
        AND f0.as_of_date = p_target_date;

     GET DIAGNOSTICS v_rows = ROW_COUNT;
     RETURN v_rows;
 END;
 $function$;
