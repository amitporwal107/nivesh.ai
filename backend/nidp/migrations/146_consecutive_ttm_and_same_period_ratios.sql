-- 146_consecutive_ttm_and_same_period_ratios.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Data-validation fixes to nidp.v_stock_fundamentals_latest and the engine's
-- populate_stock_features_extended, found by reconciling the ratings report against
-- company filings on 2026-09-14. Generated from the LIVE definitions (140/142 guards kept).
--
-- 1. TTM windows must be consecutive. The view took "the latest 4 quarterly rows", so a
--    missing March quarter made TTM silently reach back an extra quarter: 124 of 950 stocks
--    had a wrong current TTM (wrong profit, P/E, ROE) and 147 a wrong prior-year window
--    (KPEL "TTM profit growth" +94% where the real figure is ~+49%; SMS Pharma TTM profit 89
--    instead of ~103). Current TTM now needs rows 1-4 to span exactly 9 months, prior TTM
--    rows 5-8 to be the four quarters before; otherwise NULL, never a wrong number.
-- 2. CFO/PAT compared a fiscal year's cash flow with trailing-12-month profit (AWFIS 7.25x
--    = FY26 CFO 616 / TTM-to-June PAT 85). It now divides by the SAME fiscal year's profit
--    (annual row, else four quarters ending that year) -> AWFIS 616/71 = 8.7x; the year is
--    exposed as cfo_pat_fy_end.
-- 3. Interest cover was (EBITDA - depreciation) / interest, excluding other income: AWFIS
--    0.9x, dragged down by Ind AS 116 lease depreciation. Now the standard
--    (PBT + interest) / interest over TTM -> AWFIS 1.5x.
-- 4. Growth definitions are separate columns, never mixed: pat_q_yoy_pct (latest quarter vs
--    the same quarter a year earlier), pat_q_qoq_pct, revenue_q_yoy_pct, revenue_q_qoq_pct,
--    and pat_q_yoy_state ('growth' | 'turned_profit' | 'turned_loss' | 'loss_narrowed' |
--    'loss_widened') so no percentage is computed off a loss or across a sign change (QUADFUTURE showed "+32%" for a
--    loss narrowing from -13.5 to -9.1 cr). The TTM pat_growth_yoy_pct keeps its 122 guards.
-- 5. With quarters and fiscal years in separate rows (migration 145), bs_annual breaks the
--    same-date tie deterministically, preferring a row with both current assets and
--    current liabilities.
-- ─────────────────────────────────────────────────────────────────────────────
BEGIN;
SET LOCAL search_path = nidp, public;

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
                CASE
                    WHEN count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS revenue_ttm_cr,
                CASE
                    WHEN count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS pat_ttm_cr,
                CASE
                    WHEN count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS eps_ttm,
                CASE
                    WHEN count(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS ebitda_ttm_cr,
                CASE
                    WHEN count(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS depreciation_ttm_cr,
                CASE
                    WHEN count(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS finance_costs_ttm_cr,
                CASE
                    WHEN count(ranked.pbt_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) = 4 THEN sum(ranked.pbt_cr) FILTER (WHERE ranked.rn_back <= 4)
                    ELSE NULL::numeric
                END AS pbt_ttm_cr,
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS prior_eps_ttm,
            count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_pat,
            count(ranked.pat_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_pat,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_rev,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_rev,
            count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 1 AND ranked.rn_back <= 4) AS cnt_cur_eps,
            count(ranked.eps_basic) FILTER (WHERE ranked.rn_back >= 5 AND ranked.rn_back <= 8) AS cnt_prior_eps,
            max(ranked.period_end) FILTER (WHERE ranked.rn_back = 1) AS q1_end,
            max(ranked.period_end) FILTER (WHERE ranked.rn_back = 2) AS q2_end,
            max(ranked.period_end) FILTER (WHERE ranked.rn_back = 4) AS q4_end,
            max(ranked.period_end) FILTER (WHERE ranked.rn_back = 5) AS q5_end,
            max(ranked.period_end) FILTER (WHERE ranked.rn_back = 8) AS q8_end,
            max(ranked.pat_cr) FILTER (WHERE ranked.rn_back = 1) AS pat_q1,
            max(ranked.pat_cr) FILTER (WHERE ranked.rn_back = 2) AS pat_q2,
            max(ranked.pat_cr) FILTER (WHERE ranked.rn_back = 5) AS pat_q5,
            max(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back = 1) AS rev_q1,
            max(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back = 2) AS rev_q2,
            max(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back = 5) AS rev_q5,
            bool_or(ranked.rn_back <= 8 AND ranked.pat_cr > (ranked.pbt_cr * 1.05)) AS f_pat_gt_pbt,
            bool_or(ranked.rn_back <= 8 AND ranked.revenue_from_ops_cr < 0::numeric) AS f_neg_rev,
            bool_or(ranked.rn_back <= 8 AND ranked.ebitda_cr IS NOT NULL AND ranked.ebitda_cr > 0::numeric AND COALESCE(ranked.sm_sector, ''::text) <> 'Finance'::text AND (ranked.pat_cr > ranked.ebitda_cr OR ranked.pbt_cr > (ranked.ebitda_cr * 1.10))) AS f_internal_inconsistent
           FROM ranked
          GROUP BY ranked.symbol
        ), ttm_span AS (
         SELECT ttm.*,
            COALESCE(ttm.q4_end = (date_trunc('month', ttm.q1_end::timestamp) - '8 mons'::interval - '1 day'::interval)::date, false) AS cur_consecutive,
            COALESCE(ttm.q5_end = (date_trunc('month', ttm.q1_end::timestamp) - '11 mons'::interval - '1 day'::interval)::date
                 AND ttm.q8_end = (date_trunc('month', ttm.q1_end::timestamp) - '20 mons'::interval - '1 day'::interval)::date, false) AS prior_consecutive,
            COALESCE(ttm.q2_end = (date_trunc('month', ttm.q1_end::timestamp) - '2 mons'::interval - '1 day'::interval)::date, false) AS q2_adjacent,
            COALESCE(ttm.q5_end = (date_trunc('month', ttm.q1_end::timestamp) - '11 mons'::interval - '1 day'::interval)::date, false) AS q5_same_quarter_last_year
           FROM ttm
        ), ttm_ok AS (
         SELECT s.symbol,
            CASE WHEN s.cur_consecutive THEN s.revenue_ttm_cr END AS revenue_ttm_cr,
            CASE WHEN s.cur_consecutive THEN s.pat_ttm_cr END AS pat_ttm_cr,
            CASE WHEN s.cur_consecutive THEN s.eps_ttm END AS eps_ttm,
            CASE WHEN s.cur_consecutive THEN s.ebitda_ttm_cr END AS ebitda_ttm_cr,
            CASE WHEN s.cur_consecutive THEN s.depreciation_ttm_cr END AS depreciation_ttm_cr,
            CASE WHEN s.cur_consecutive THEN s.finance_costs_ttm_cr END AS finance_costs_ttm_cr,
            CASE WHEN s.cur_consecutive THEN s.pbt_ttm_cr END AS pbt_ttm_cr,
            CASE WHEN s.prior_consecutive THEN s.prior_revenue_ttm_cr END AS prior_revenue_ttm_cr,
            CASE WHEN s.prior_consecutive THEN s.prior_pat_ttm_cr END AS prior_pat_ttm_cr,
            CASE WHEN s.prior_consecutive THEN s.prior_eps_ttm END AS prior_eps_ttm,
            CASE WHEN s.cur_consecutive THEN s.cnt_cur_pat ELSE 0::bigint END AS cnt_cur_pat,
            CASE WHEN s.prior_consecutive THEN s.cnt_prior_pat ELSE 0::bigint END AS cnt_prior_pat,
            CASE WHEN s.cur_consecutive THEN s.cnt_cur_rev ELSE 0::bigint END AS cnt_cur_rev,
            CASE WHEN s.prior_consecutive THEN s.cnt_prior_rev ELSE 0::bigint END AS cnt_prior_rev,
            CASE WHEN s.cur_consecutive THEN s.cnt_cur_eps ELSE 0::bigint END AS cnt_cur_eps,
            CASE WHEN s.prior_consecutive THEN s.cnt_prior_eps ELSE 0::bigint END AS cnt_prior_eps,
            s.f_pat_gt_pbt, s.f_neg_rev, s.f_internal_inconsistent,
            s.cur_consecutive, s.prior_consecutive, s.q2_adjacent, s.q5_same_quarter_last_year,
            s.pat_q1, s.pat_q2, s.pat_q5, s.rev_q1, s.rev_q2, s.rev_q5
           FROM ttm_span s
        ), bs_annual AS (
         SELECT DISTINCT ON (nse_financials_quarterly.symbol) nse_financials_quarterly.symbol,
            nse_financials_quarterly.current_assets_cr,
            nse_financials_quarterly.current_liabilities_cr
           FROM nse_financials_quarterly
          WHERE nse_financials_quarterly.current_assets_cr IS NOT NULL OR nse_financials_quarterly.current_liabilities_cr IS NOT NULL
          ORDER BY nse_financials_quarterly.symbol, nse_financials_quarterly.period_end DESC,
                   (nse_financials_quarterly.current_assets_cr IS NOT NULL AND nse_financials_quarterly.current_liabilities_cr IS NOT NULL) DESC,
                   nse_financials_quarterly.period_type
        ), cf_annual AS (
         SELECT DISTINCT ON (nse_financials_cashflow.symbol) nse_financials_cashflow.symbol,
            nse_financials_cashflow.cfo_cr,
            nse_financials_cashflow.period_end,
            nse_financials_cashflow.consolidated
           FROM nse_financials_cashflow
          ORDER BY nse_financials_cashflow.symbol, nse_financials_cashflow.period_end DESC, nse_financials_cashflow.consolidated DESC
        ), fy_annual AS (
         SELECT DISTINCT ON (c.symbol) c.symbol, a.pat_cr
           FROM cf_annual c
           JOIN nse_financials_quarterly a ON a.symbol = c.symbol AND a.period_end = c.period_end
            AND a.period_type ILIKE 'annual' AND a.pat_cr IS NOT NULL
          ORDER BY c.symbol, (a.consolidated = c.consolidated) DESC
        ), fy_quarters AS (
         SELECT c.symbol,
                CASE WHEN count(q.pat_cr) = 4 THEN sum(q.pat_cr) ELSE NULL::numeric END AS pat_4q
           FROM cf_annual c
           JOIN nse_financials_quarterly q ON q.symbol = c.symbol AND q.consolidated = c.consolidated
            AND q.period_type ILIKE 'quarterly'
            AND q.period_end > (c.period_end - '1 year'::interval)::date AND q.period_end <= c.period_end
          GROUP BY c.symbol
        ), fy_pat AS (
         SELECT c.symbol, c.cfo_cr, c.period_end AS cfo_fy_end,
                COALESCE(fa.pat_cr, fq.pat_4q) AS fy_pat_cr
           FROM cf_annual c
           LEFT JOIN fy_annual fa ON fa.symbol = c.symbol
           LEFT JOIN fy_quarters fq ON fq.symbol = c.symbol
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
            WHEN cf.fy_pat_cr <> 0::numeric AND cf.fy_pat_cr IS NOT NULL AND cf.cfo_cr IS NOT NULL THEN round(cf.cfo_cr / cf.fy_pat_cr, 2)
            ELSE NULL::numeric
        END AS cfo_pat_ratio,
    cf.cfo_fy_end AS cfo_pat_fy_end,
    t.cur_consecutive AS ttm_consecutive,
    t.prior_consecutive AS prior_ttm_consecutive,
        CASE WHEN t.q5_same_quarter_last_year AND t.pat_q5 > 0::numeric AND t.pat_q1 > 0::numeric
             THEN round((t.pat_q1 - t.pat_q5) / t.pat_q5 * 100::numeric, 2) END AS pat_q_yoy_pct,
        CASE WHEN NOT t.q5_same_quarter_last_year OR t.pat_q1 IS NULL OR t.pat_q5 IS NULL THEN NULL::text
             WHEN t.pat_q5 > 0::numeric AND t.pat_q1 > 0::numeric THEN 'growth'::text
             WHEN t.pat_q5 > 0::numeric THEN 'turned_loss'::text
             WHEN t.pat_q1 > 0::numeric THEN 'turned_profit'::text
             WHEN t.pat_q1 > t.pat_q5 THEN 'loss_narrowed'::text
             ELSE 'loss_widened'::text END AS pat_q_yoy_state,
        CASE WHEN t.q2_adjacent AND t.pat_q2 > 0::numeric AND t.pat_q1 > 0::numeric
             THEN round((t.pat_q1 - t.pat_q2) / t.pat_q2 * 100::numeric, 2) END AS pat_q_qoq_pct,
        CASE WHEN t.q5_same_quarter_last_year AND t.rev_q5 > 0::numeric AND t.rev_q1 IS NOT NULL
             THEN round((t.rev_q1 - t.rev_q5) / t.rev_q5 * 100::numeric, 2) END AS revenue_q_yoy_pct,
        CASE WHEN t.q2_adjacent AND t.rev_q2 > 0::numeric AND t.rev_q1 IS NOT NULL
             THEN round((t.rev_q1 - t.rev_q2) / t.rev_q2 * 100::numeric, 2) END AS revenue_q_qoq_pct
   FROM ranked r
     LEFT JOIN ttm_ok t ON t.symbol = r.symbol
     LEFT JOIN bs_annual ba ON ba.symbol = r.symbol
     LEFT JOIN fy_pat cf ON cf.symbol = r.symbol
  WHERE r.rn = 1;

CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date date)
 RETURNS integer
 LANGUAGE plpgsql
AS $function$
 DECLARE v_rows INTEGER; BEGIN
     UPDATE nidp.stock_features_daily f
        SET
            pe_ttm                 = CASE WHEN fund.eps_ttm > 0 AND f.close > 0
                                          THEN ROUND((f.close / fund.eps_ttm)::NUMERIC, 4) ELSE NULL END,
            pb                     = CASE WHEN fund.total_equity_cr > 0 AND fund.equity_share_capital_cr > 0
                                           AND sm.face_value > 0 AND f.close > 0
                                          THEN ROUND((f.close / (fund.total_equity_cr * sm.face_value / fund.equity_share_capital_cr))::NUMERIC, 4) ELSE NULL END,
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
                WHEN fund.pbt_ttm_cr IS NOT NULL AND fund.finance_costs_ttm_cr > 0
                THEN ROUND(((fund.pbt_ttm_cr + fund.finance_costs_ttm_cr) / fund.finance_costs_ttm_cr)::NUMERIC, 2) ELSE NULL END,
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

INSERT INTO nidp.schema_migrations (filename)
VALUES ('146_consecutive_ttm_and_same_period_ratios.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
