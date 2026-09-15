-- 140_ttm_requires_four_quarters.sql
-- v_stock_fundamentals_latest summed however many quarters existed and exposed the result as TTM.
-- With one quarter held (1,509 of ~2,000 symbols) pe_ttm became close/one-quarter-EPS: GENESYS read
-- 384.8x against a real ~60x. The view already computed cnt_cur_* and correctly guarded the GROWTH
-- columns with "= 4" -- that guard was simply never applied to the TTM aggregates themselves.
-- Every downstream metric (pe_ttm, pe_vs_sector_pct, ev_ebitda, roce_pct, interest_coverage,
-- profit_margin_pct, operating_margin_pct) is fixed by guarding at the source.
-- Coverage will DROP until the Screener history backfill lands the missing quarters. That is correct:
-- a null beats a wrong valuation.
CREATE OR REPLACE VIEW nidp.v_stock_fundamentals_latest AS
 WITH base AS (
         SELECT f.symbol,
            f.period_end,
            f.period_start,
            f.period_type,
            f.consolidated,
            f.audited,
            f.revenue_from_ops_cr,
            f.other_income_cr,
            f.total_income_cr,
            f.total_expenses_cr,
            f.ebitda_cr,
            f.finance_costs_cr,
            f.depreciation_cr,
            f.pbt_before_exc_cr,
            f.exceptional_items_cr,
            f.pbt_cr,
            f.tax_expense_cr,
            f.pat_continuing_cr,
            f.pat_discontinuing_cr,
            f.pat_cr,
            f.pat_attrib_owners_cr,
            f.pat_attrib_minority_cr,
            f.eps_basic,
            f.eps_diluted,
            f.face_value,
            f.equity_share_capital_cr,
            f.other_equity_cr,
            f.total_equity_cr,
            f.long_term_debt_cr,
            f.short_term_debt_cr,
            f.cash_and_equiv_cr,
            f.interest_earned_cr,
            f.interest_expended_cr,
            f.nim_pct,
            f.filing_id,
            f.xbrl_url,
            f.broadcast_at,
            f.source,
            f.source_run_id,
            f.ingested_at,
            f.ir_url,
            f.id,
            f.raw_data,
            f.current_assets_cr,
            f.current_liabilities_cr,
            f.trade_receivables_cr,
            f.inventory_cr,
            f.trade_payables_cr,
            sm.sector AS sm_sector,
            COALESCE(max(f.period_end) FILTER (WHERE f.consolidated) OVER (PARTITION BY f.symbol) >= (max(f.period_end) OVER (PARTITION BY f.symbol) - '100 days'::interval), false) AS prefer_consol
           FROM nse_financials_quarterly f
             LEFT JOIN sector_master sm ON sm.symbol = f.symbol
          WHERE f.period_type ~~* 'QUARTERLY'::text
        ), ranked AS (
         SELECT b.symbol,
            b.period_end,
            b.period_start,
            b.period_type,
            b.consolidated,
            b.audited,
            b.revenue_from_ops_cr,
            b.other_income_cr,
            b.total_income_cr,
            b.total_expenses_cr,
            b.ebitda_cr,
            b.finance_costs_cr,
            b.depreciation_cr,
            b.pbt_before_exc_cr,
            b.exceptional_items_cr,
            b.pbt_cr,
            b.tax_expense_cr,
            b.pat_continuing_cr,
            b.pat_discontinuing_cr,
            b.pat_cr,
            b.pat_attrib_owners_cr,
            b.pat_attrib_minority_cr,
            b.eps_basic,
            b.eps_diluted,
            b.face_value,
            b.equity_share_capital_cr,
            b.other_equity_cr,
            b.total_equity_cr,
            b.long_term_debt_cr,
            b.short_term_debt_cr,
            b.cash_and_equiv_cr,
            b.interest_earned_cr,
            b.interest_expended_cr,
            b.nim_pct,
            b.filing_id,
            b.xbrl_url,
            b.broadcast_at,
            b.source,
            b.source_run_id,
            b.ingested_at,
            b.ir_url,
            b.id,
            b.raw_data,
            b.current_assets_cr,
            b.current_liabilities_cr,
            b.trade_receivables_cr,
            b.inventory_cr,
            b.trade_payables_cr,
            b.sm_sector,
            b.prefer_consol,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.period_end DESC) AS rn,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.period_end DESC) AS rn_back
           FROM base b
          WHERE b.consolidated = b.prefer_consol
        ), ttm AS (
         SELECT ranked.symbol,
            CASE WHEN count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back <= 4) END AS revenue_ttm_cr,
            CASE WHEN count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back <= 4) END AS pat_ttm_cr,
            CASE WHEN count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back <= 4) END AS eps_ttm,
            CASE WHEN count(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back <= 4) END AS ebitda_ttm_cr,
            CASE WHEN count(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back <= 4) END AS depreciation_ttm_cr,
            CASE WHEN count(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back <= 4) END AS finance_costs_ttm_cr,
            CASE WHEN count(ranked.pbt_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.pbt_cr) FILTER (WHERE ranked.rn_back <= 4) END AS pbt_ttm_cr,
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_eps_ttm,
            count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_pat,
            count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_pat,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_rev,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_rev,
            count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_eps,
            count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_eps,
            bool_or(ranked.rn_back <= 8 AND ranked.pat_cr > (ranked.pbt_cr * 1.05)) AS f_pat_gt_pbt,
            bool_or(ranked.rn_back <= 8 AND ranked.revenue_from_ops_cr < 0::numeric) AS f_neg_rev,
            bool_or(ranked.rn_back <= 8 AND ranked.ebitda_cr IS NOT NULL AND ranked.ebitda_cr > 0::numeric AND COALESCE(ranked.sm_sector, ''::text) <> 'Finance'::text AND (ranked.pat_cr > ranked.ebitda_cr OR ranked.pbt_cr > (ranked.ebitda_cr * 1.10))) AS f_internal_inconsistent
           FROM ranked
          GROUP BY ranked.symbol
        ), bs_annual AS (
         SELECT DISTINCT ON (nse_financials_quarterly.symbol) nse_financials_quarterly.symbol,
            nse_financials_quarterly.current_assets_cr,
            nse_financials_quarterly.current_liabilities_cr
           FROM nse_financials_quarterly
          WHERE nse_financials_quarterly.period_type = 'annual'::text AND (nse_financials_quarterly.current_assets_cr IS NOT NULL OR nse_financials_quarterly.current_liabilities_cr IS NOT NULL)
          ORDER BY nse_financials_quarterly.symbol, nse_financials_quarterly.period_end DESC
        ), cf_annual AS (
         SELECT DISTINCT ON (nse_financials_cashflow.symbol) nse_financials_cashflow.symbol,
            nse_financials_cashflow.cfo_cr
           FROM nse_financials_cashflow
          ORDER BY nse_financials_cashflow.symbol, nse_financials_cashflow.period_end DESC
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
    t.ebitda_ttm_cr - t.depreciation_ttm_cr AS ebit_ttm_cr,
    COALESCE(r.total_equity_cr, 0::numeric) + COALESCE(r.long_term_debt_cr, 0::numeric) + COALESCE(r.short_term_debt_cr, 0::numeric) AS capital_employed_cr,
        CASE
            WHEN r.total_equity_cr > 0::numeric AND t.pat_ttm_cr IS NOT NULL THEN round(t.pat_ttm_cr / r.total_equity_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS roe_annualised_pct,
        CASE
            WHEN r.total_equity_cr > 0::numeric THEN round((COALESCE(r.long_term_debt_cr, 0::numeric) + COALESCE(r.short_term_debt_cr, 0::numeric)) / r.total_equity_cr, 4)
            ELSE NULL::numeric
        END AS debt_to_equity,
        CASE
            WHEN t.prior_revenue_ttm_cr > 0::numeric AND t.revenue_ttm_cr IS NOT NULL AND t.cnt_cur_rev = 4 AND t.cnt_prior_rev = 4 AND NOT COALESCE(t.f_neg_rev, false) AND NOT COALESCE(t.f_pat_gt_pbt, false) AND NOT COALESCE(t.f_internal_inconsistent, false) THEN round((t.revenue_ttm_cr - t.prior_revenue_ttm_cr) / t.prior_revenue_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS revenue_growth_yoy_pct,
        CASE
            WHEN t.prior_pat_ttm_cr > 25::numeric AND t.pat_ttm_cr IS NOT NULL AND t.cnt_cur_pat = 4 AND t.cnt_prior_pat = 4 AND NOT COALESCE(t.f_pat_gt_pbt, false) AND NOT COALESCE(t.f_neg_rev, false) AND NOT COALESCE(t.f_internal_inconsistent, false) THEN round((t.pat_ttm_cr - t.prior_pat_ttm_cr) / t.prior_pat_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS pat_growth_yoy_pct,
        CASE
            WHEN t.prior_eps_ttm > 0::numeric AND t.eps_ttm IS NOT NULL AND t.cnt_cur_eps = 4 AND t.cnt_prior_eps = 4 AND t.prior_pat_ttm_cr > 25::numeric AND NOT COALESCE(t.f_pat_gt_pbt, false) AND NOT COALESCE(t.f_neg_rev, false) AND NOT COALESCE(t.f_internal_inconsistent, false) THEN round((t.eps_ttm - t.prior_eps_ttm) / t.prior_eps_ttm * 100::numeric, 4)
            ELSE NULL::numeric
        END AS eps_growth_yoy_pct,
    r.broadcast_at,
    r.source_run_id,
    ba.current_assets_cr,
    ba.current_liabilities_cr,
    cf.cfo_cr,
        CASE
            WHEN ba.current_liabilities_cr > 0::numeric AND ba.current_assets_cr IS NOT NULL THEN round(ba.current_assets_cr / ba.current_liabilities_cr, 2)
            ELSE NULL::numeric
        END AS current_ratio,
        CASE
            WHEN t.pat_ttm_cr <> 0::numeric AND t.pat_ttm_cr IS NOT NULL AND cf.cfo_cr IS NOT NULL THEN round(cf.cfo_cr / t.pat_ttm_cr, 2)
            ELSE NULL::numeric
        END AS cfo_pat_ratio
   FROM ranked r
     LEFT JOIN ttm t ON t.symbol = r.symbol
     LEFT JOIN bs_annual ba ON ba.symbol = r.symbol
     LEFT JOIN cf_annual cf ON cf.symbol = r.symbol
  WHERE r.rn = 1;
