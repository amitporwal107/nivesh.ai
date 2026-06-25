-- 100_fix_fundamentals_ttm_single_basis.sql
--
-- Fix: stock P/E was ~half, ROE ~2x, sector-median P/E far too low, and PEG
-- (derived from P/E) all wrong — because nidp.v_stock_fundamentals_latest summed
-- TTM revenue/PAT/EPS across BOTH reporting bases at once.
--
-- Root cause: the `ranked` CTE computed
--     rn_back = row_number() OVER (PARTITION BY symbol, period_type ORDER BY period_end DESC)
-- and the TTM CTE did `SUM(...) FILTER (WHERE rn_back <= 4)`. Consolidated rows
-- carry period_type 'QUARTERLY' and standalone rows 'quarterly' — DIFFERENT
-- strings, so each basis got its own rn_back 1..4 and BOTH were summed. The TTM
-- therefore mixed consolidated + standalone, inflating pat_ttm/eps_ttm (e.g.
-- RELIANCE pat_ttm 192,147 vs true ~95,754). That cascaded into pe_ttm (= close /
-- eps_ttm), roe_annualised_pct (= pat_ttm / equity), the sector P/E median, PEG,
-- and the V3 fundamental score.
--
-- Fix: restrict the TTM (and the point-in-time `rn=1` row) to a SINGLE basis per
-- symbol — consolidated when the symbol files consolidated, else standalone —
-- via a per-symbol has_consol flag, then rank trailing quarters within that one
-- basis. Everything downstream of the CTE is unchanged.
--
-- NOTE: a second, data-level issue exists on some environments where the March
-- (Q4) row stores the ANNUAL figure instead of the true quarter; that is an
-- nse_financials ingestion problem handled separately. This migration fixes the
-- basis-mixing, which is correct on every environment.

CREATE OR REPLACE VIEW nidp.v_stock_fundamentals_latest AS
 WITH base AS (
         SELECT f.*,
            bool_or(f.consolidated) OVER (PARTITION BY f.symbol) AS has_consol
           FROM nidp.nse_financials_quarterly f
          WHERE f.period_type ~~* 'QUARTERLY'::text
        ), ranked AS (
         SELECT b.*,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.consolidated DESC, b.period_end DESC) AS rn,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.period_end DESC) AS rn_back
           FROM base b
          -- keep only the preferred basis: consolidated if the symbol files it,
          -- otherwise standalone. This stops the TTM summing both bases.
          WHERE b.consolidated = b.has_consol
        ), ttm AS (
         SELECT ranked.symbol,
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back <= 4) AS revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back <= 4) AS pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back <= 4) AS eps_ttm,
            sum(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back <= 4) AS ebitda_ttm_cr,
            sum(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back <= 4) AS depreciation_ttm_cr,
            sum(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back <= 4) AS finance_costs_ttm_cr,
            sum(ranked.pbt_cr) FILTER (WHERE ranked.rn_back <= 4) AS pbt_ttm_cr,
            -- prior-year TTM (quarters 5-8 back) for YoY growth on a TTM basis,
            -- so growth = FY-vs-FY (consistent with the TTM valuation) rather
            -- than single-quarter-vs-quarter.
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_eps_ttm
           FROM ranked
          GROUP BY ranked.symbol
        ), bs_annual AS (
         SELECT DISTINCT ON (nse_financials_quarterly.symbol) nse_financials_quarterly.symbol,
            nse_financials_quarterly.current_assets_cr,
            nse_financials_quarterly.current_liabilities_cr
           FROM nidp.nse_financials_quarterly
          WHERE nse_financials_quarterly.period_type = 'annual'::text AND (nse_financials_quarterly.current_assets_cr IS NOT NULL OR nse_financials_quarterly.current_liabilities_cr IS NOT NULL)
          ORDER BY nse_financials_quarterly.symbol, nse_financials_quarterly.period_end DESC
        ), cf_annual AS (
         SELECT DISTINCT ON (nse_financials_cashflow.symbol) nse_financials_cashflow.symbol,
            nse_financials_cashflow.cfo_cr
           FROM nidp.nse_financials_cashflow
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
            WHEN t.prior_revenue_ttm_cr > 0::numeric AND t.revenue_ttm_cr IS NOT NULL THEN round((t.revenue_ttm_cr - t.prior_revenue_ttm_cr) / t.prior_revenue_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS revenue_growth_yoy_pct,
        CASE
            WHEN t.prior_pat_ttm_cr > 0::numeric AND t.pat_ttm_cr IS NOT NULL THEN round((t.pat_ttm_cr - t.prior_pat_ttm_cr) / t.prior_pat_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS pat_growth_yoy_pct,
        CASE
            WHEN t.prior_eps_ttm > 0::numeric AND t.eps_ttm IS NOT NULL THEN round((t.eps_ttm - t.prior_eps_ttm) / t.prior_eps_ttm * 100::numeric, 4)
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
