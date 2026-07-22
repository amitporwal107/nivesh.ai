-- 122_fix_pat_yoy_data_quality_guards.sql
--
-- Fix: the Nifty-500 "grew profit > X%" screen served untrustworthy growth values —
-- JSWSTEEL 630.7%, NUVOCO 540.9%, HINDPETRO 428.4%, with 152/454 names (33% of the
-- universe) showing >30% TTM profit growth. That is not a believable distribution.
--
-- The formula is NOT the problem. Migration 100 (live — it superseded 091) computes
-- growth on a TTM-vs-prior-TTM basis over a SINGLE reporting basis:
--     pat_growth_yoy_pct = (pat_ttm_cr - prior_pat_ttm_cr) / prior_pat_ttm_cr * 100
--     pat_ttm_cr       = SUM(pat_cr) FILTER (rn_back 1..4)
--     prior_pat_ttm_cr = SUM(pat_cr) FILTER (rn_back 5..8)
-- That basis is correct and is KEPT (it smooths seasonality and, unlike 091's
-- single-quarter YoY, largely avoids a one-off tiny quarter becoming the denominator).
--
-- The problem is that a correct formula is being fed untrustworthy SOURCE rows. The
-- only guard today is `prior_*_ttm_cr > 0`, so three distinct defects leak through
-- (each verified against live nidp_staging, screen data as_of 2026-07-14):
--
--   1. INCOMPLETE WINDOW (the largest failure — 264 of 484 Nifty-500 names).
--      nse_financials_quarterly holds 3,068 NULL-pat_cr quarterly rows in the Nifty
--      500 (3,053 of them written by nse_xbrl_backfill, which populated ebitda_cr /
--      pbt_cr but left pat_cr NULL). SUM() silently skips NULLs, so a "TTM" can be
--      built from a single quarter and compared against a 4-quarter prior window.
--      NUVOCO: current "TTM" = 141 (ONE quarter, Q1-Q3 FY26 are NULL) vs prior 22
--      -> 540.9%. Meaningless.
--
--   2. CONTAMINATED / EXCEPTIONAL QUARTER inside a window.
--      JSWSTEEL Q4 FY26: pat_cr = 19243 while ebitda_cr = 8464 and pbt_cr = 22377.
--      PAT and PBT both exceed EBITDA, which is impossible for an operating company
--      (its normal quarters run 700-2500). That one row inflates the current TTM to
--      25508 vs a 3491 prior -> 630.7%.
--
--   3. IMPOSSIBLE ROW in a window.
--      HINDPETRO's prior window holds a Q4-FY25 row with revenue_from_ops_cr =
--      -214820 (negative revenue). Its prior TTM is NOT small (3415), so a base
--      floor alone does not catch it -> 428.4%.
--
-- Fix (derivation-layer, defense-in-depth): compute per-window completeness counts
-- and per-symbol data-quality flags, and emit the growth metric ONLY when the window
-- is clean. Otherwise NULL, so the name drops out of a "> X%" predicate rather than
-- surfacing a wrong value to a user — a wrong value that PASSES a filter is worse
-- than a missing one.
--
-- Guards applied (all three sibling metrics: pat / revenue / eps):
--   * completeness  : 4 non-null values in BOTH the current and prior windows
--   * pat > pbt*1.05: universal impossibility (works for banks/NBFCs, which report pbt)
--   * negative revenue in either window
--   * internal inconsistency (NON-FINANCIAL only): ebitda > 0 AND
--     (pat > ebitda OR pbt > ebitda*1.10)
--   * materiality floor on the PAT denominator: prior_pat_ttm_cr > 25 (was > 0)
--
-- FINANCIAL CARVE-OUT (required): banks/NBFCs carry ebitda_cr = NULL so the EBITDA
-- leg already skips them, but INSURERS do report an ebitda_cr and would be
-- false-flagged (HDFCLIFE pat 1912 > ebitda 1753; SBILIFE ebitda = -1046). All of
-- these carry sector_master.sector = 'Finance', so the EBITDA leg is gated on
-- sector <> 'Finance'. The universal pat > pbt leg still protects financials.
--
-- Materiality floor = 25 (not 50): on a TTM basis only 2 Nifty-500 names have a
-- positive prior base under 50, and the smallest legitimate survivor (NYKAA, prior
-- TTM 72) must be kept. 25 kills the near-break-even artifacts without punishing
-- small-but-real names.
--
-- Expected effect (measured on live staging before/after):
--   >30%: 152 -> ~34 (~7% of universe)   >100%: 48 -> 6   >200%: 18 -> 1   >500%: 6 -> 0
--   names with pat_ttm > ebitda_ttm: present -> none
--   TATASTEEL 242.9% SURVIVES (pat_ttm 10885 < ebitda_ttm 34354) — a genuine
--   cyclical-steel recovery off a weak FY25, correctly NOT rejected.
--
-- KNOWN COVERAGE TRADE-OFF (deliberate, and the paired follow-up): the completeness
-- guard leaves ~132 computable Nifty-500 names because ~229 are NULLed purely for the
-- upstream missing-pat_cr gap. This migration buys CORRECTNESS now; the coverage
-- unlock is a pat_cr backfill over the nse_xbrl_backfill rows, tracked separately.
-- NULLing them is the honest state — we do not know their growth.
--
-- Re-runnable. Column list is unchanged, so CREATE OR REPLACE VIEW is valid.

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_stock_fundamentals_latest AS
 WITH base AS (
         SELECT f.*,
            -- sector is needed ONLY for the non-financial EBITDA guard below.
            sm.sector AS sm_sector,
            -- prefer consolidated only if it is (roughly) as fresh as the freshest
            -- filing for this symbol; otherwise fall back to standalone. (From 100.)
            COALESCE(
              max(f.period_end) FILTER (WHERE f.consolidated) OVER (PARTITION BY f.symbol)
                >= max(f.period_end) OVER (PARTITION BY f.symbol) - interval '100 days',
              false
            ) AS prefer_consol
           FROM nidp.nse_financials_quarterly f
           LEFT JOIN nidp.sector_master sm ON sm.symbol = f.symbol
          WHERE f.period_type ~~* 'QUARTERLY'::text
        ), ranked AS (
         SELECT b.*,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.period_end DESC) AS rn,
            row_number() OVER (PARTITION BY b.symbol ORDER BY b.period_end DESC) AS rn_back
           FROM base b
          WHERE b.consolidated = b.prefer_consol
        ), ttm AS (
         SELECT ranked.symbol,
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back <= 4) AS revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back <= 4) AS pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back <= 4) AS eps_ttm,
            sum(ranked.ebitda_cr) FILTER (WHERE ranked.rn_back <= 4) AS ebitda_ttm_cr,
            sum(ranked.depreciation_cr) FILTER (WHERE ranked.rn_back <= 4) AS depreciation_ttm_cr,
            sum(ranked.finance_costs_cr) FILTER (WHERE ranked.rn_back <= 4) AS finance_costs_ttm_cr,
            sum(ranked.pbt_cr) FILTER (WHERE ranked.rn_back <= 4) AS pbt_ttm_cr,
            sum(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_revenue_ttm_cr,
            sum(ranked.pat_cr) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_pat_ttm_cr,
            sum(ranked.eps_basic) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS prior_eps_ttm,
            -- ── DQ guard 1: window completeness (SUM silently skips NULLs) ──────
            count(ranked.pat_cr)              FILTER (WHERE ranked.rn_back BETWEEN 1 AND 4) AS cnt_cur_pat,
            count(ranked.pat_cr)              FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS cnt_prior_pat,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back BETWEEN 1 AND 4) AS cnt_cur_rev,
            count(ranked.revenue_from_ops_cr) FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS cnt_prior_rev,
            count(ranked.eps_basic)           FILTER (WHERE ranked.rn_back BETWEEN 1 AND 4) AS cnt_cur_eps,
            count(ranked.eps_basic)           FILTER (WHERE ranked.rn_back BETWEEN 5 AND 8) AS cnt_prior_eps,
            -- ── DQ guard 2: universal impossibility (PAT cannot exceed PBT) ─────
            -- NULL pbt_cr yields NULL, which bool_or ignores — no false flag.
            bool_or(ranked.rn_back <= 8 AND ranked.pat_cr > ranked.pbt_cr * 1.05) AS f_pat_gt_pbt,
            -- ── DQ guard 3: impossible row in either window ─────────────────────
            bool_or(ranked.rn_back <= 8 AND ranked.revenue_from_ops_cr < 0::numeric) AS f_neg_rev,
            -- ── DQ guard 4: internal inconsistency, NON-FINANCIAL only ──────────
            bool_or(ranked.rn_back <= 8
                    AND ranked.ebitda_cr IS NOT NULL AND ranked.ebitda_cr > 0::numeric
                    AND COALESCE(ranked.sm_sector, ''::text) <> 'Finance'::text
                    AND (ranked.pat_cr > ranked.ebitda_cr
                         OR ranked.pbt_cr > ranked.ebitda_cr * 1.10)) AS f_internal_inconsistent
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
        -- ── GUARDED: revenue TTM growth ─────────────────────────────────────────
        CASE
            WHEN t.prior_revenue_ttm_cr > 0::numeric
             AND t.revenue_ttm_cr IS NOT NULL
             AND t.cnt_cur_rev = 4 AND t.cnt_prior_rev = 4
             AND NOT COALESCE(t.f_neg_rev, false)
             AND NOT COALESCE(t.f_pat_gt_pbt, false)
             AND NOT COALESCE(t.f_internal_inconsistent, false)
            THEN round((t.revenue_ttm_cr - t.prior_revenue_ttm_cr) / t.prior_revenue_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS revenue_growth_yoy_pct,
        -- ── GUARDED: PAT TTM growth (the metric the profit screen filters on) ───
        CASE
            WHEN t.prior_pat_ttm_cr > 25::numeric          -- materiality floor (was > 0)
             AND t.pat_ttm_cr IS NOT NULL
             AND t.cnt_cur_pat = 4 AND t.cnt_prior_pat = 4 -- complete windows
             AND NOT COALESCE(t.f_pat_gt_pbt, false)
             AND NOT COALESCE(t.f_neg_rev, false)
             AND NOT COALESCE(t.f_internal_inconsistent, false)
            THEN round((t.pat_ttm_cr - t.prior_pat_ttm_cr) / t.prior_pat_ttm_cr * 100::numeric, 4)
            ELSE NULL::numeric
        END AS pat_growth_yoy_pct,
        -- ── GUARDED: EPS TTM growth ─────────────────────────────────────────────
        CASE
            WHEN t.prior_eps_ttm > 0::numeric
             AND t.eps_ttm IS NOT NULL
             AND t.cnt_cur_eps = 4 AND t.cnt_prior_eps = 4
             AND t.prior_pat_ttm_cr > 25::numeric          -- EPS tracks PAT; same floor
             AND NOT COALESCE(t.f_pat_gt_pbt, false)
             AND NOT COALESCE(t.f_neg_rev, false)
             AND NOT COALESCE(t.f_internal_inconsistent, false)
            THEN round((t.eps_ttm - t.prior_eps_ttm) / t.prior_eps_ttm * 100::numeric, 4)
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

COMMENT ON VIEW nidp.v_stock_fundamentals_latest IS
    'Latest single-basis quarterly fundamentals + TTM aggregates. Growth metrics are '
    'TTM-vs-prior-TTM (NOT single-quarter YoY) and are emitted only when both 4-quarter '
    'windows are complete and free of DQ defects (pat>pbt, negative revenue, non-financial '
    'pat/pbt>ebitda), with a materiality floor of 25cr on the prior PAT denominator. '
    'A NULL means "not trustworthy / not computable", never "zero growth". See migration 122.';

-- Refresh the served feature store for the date the screen reads (MAX as_of_date).
-- The view change alone does not rewrite nidp.stock_features_daily — the populate
-- function materialises it. Forward dates pick the guards up via the daily cron.
DO $$
DECLARE v_date date;
BEGIN
    SELECT MAX(as_of_date) INTO v_date FROM nidp.stock_features_daily;
    IF v_date IS NOT NULL THEN
        PERFORM nidp.populate_stock_features_extended(v_date);
        RAISE NOTICE 'migration 122: repopulated stock_features_daily for %', v_date;
    END IF;
END $$;

INSERT INTO nidp.schema_migrations(filename)
VALUES ('122_fix_pat_yoy_data_quality_guards.sql')
ON CONFLICT DO NOTHING;
