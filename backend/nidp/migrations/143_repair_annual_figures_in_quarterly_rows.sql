-- 143_repair_annual_figures_in_quarterly_rows.sql
-- ─────────────────────────────────────────────────────────────────────────────
-- Repair: full-year P&L sitting in a row typed 'quarterly'.
--
-- nse_financials_quarterly is unique on (symbol, period_end, consolidated), so a March
-- quarter and its fiscal year share ONE row. Until commit 420808e1 the upsert took
-- COALESCE(EXCLUDED, row) for every column, so backfill_screener_historical — which writes
-- the quarters and THEN the annual P&L — replaced each March quarter's income statement with
-- the full year while leaving period_type = 'quarterly' and source = 'screener_in_annual'.
-- On 2026-09-12/13 that put a year inside the trailing-12-month window of 756 of the
-- Nifty 500 + next 500 (RELIANCE revenue_ttm 18.8 lakh cr, P/E 12.3).
--
-- Most rows are repaired by re-running the backfill with the fixed writer: Screener serves 13
-- quarters, so March 2024 onward comes back as real quarters. Older rows (March 2023: 408) are
-- outside that window and are repaired here the way migration 108 did it:
--     true Q4 = reported year - (Q1 + Q2 + Q3)
-- Only rows that still carry the annual figure are touched (source = 'screener_in_annual'),
-- and only when all three preceding quarters of the same fiscal year and basis are present,
-- so this is idempotent and cannot fire on an already-repaired row.
--
-- A column is derived only when all three preceding quarters carry that column, and a derived
-- revenue below zero is rejected (MEESHO's year and quarters do not line up: -16,487). Anything
-- not derivable is set NULL rather than left as a year wearing a quarter's label, because a wrong
-- value that passes a screen is worse than a missing one (migration 122's rule) and because a
-- NULL still occupies its slot in the TTM window, so the window reports NULL instead of silently
-- reaching back an extra quarter.
--
-- KNOWN LOSS: the annual figure in these rows is not preserved anywhere - with one row per
-- (symbol, period_end, consolidated) an FY that has a March quarter has nowhere else to live.
-- Annual P&L needs its own key or table before 3Y CAGR can rely on recent years.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

WITH contaminated AS (
    SELECT id, symbol, consolidated, period_end,
           revenue_from_ops_cr, pat_cr, eps_basic, ebitda_cr, pbt_cr,
           finance_costs_cr, depreciation_cr, total_income_cr
      FROM nidp.nse_financials_quarterly
     WHERE period_type ILIKE 'quarterly'
       AND source = 'screener_in_annual'
),
-- The three quarters that precede a fiscal-year end, on the same reporting basis.
prior3 AS (
    SELECT c.id,
           count(*)                           AS nq,
           sum(p.revenue_from_ops_cr)         AS p_rev,
           sum(p.pat_cr)                      AS p_pat,
           sum(p.eps_basic)                   AS p_eps,
           sum(p.ebitda_cr)                   AS p_ebitda,
           sum(p.pbt_cr)                      AS p_pbt,
           sum(p.finance_costs_cr)            AS p_fin,
           sum(p.depreciation_cr)             AS p_dep,
           sum(p.total_income_cr)             AS p_ti,
           count(p.revenue_from_ops_cr)       AS n_rev,
           count(p.pat_cr)                    AS n_pat,
           count(p.eps_basic)                 AS n_eps,
           count(p.ebitda_cr)                 AS n_ebitda,
           count(p.pbt_cr)                    AS n_pbt,
           count(p.finance_costs_cr)          AS n_fin,
           count(p.depreciation_cr)           AS n_dep,
           count(p.total_income_cr)           AS n_ti
      FROM contaminated c
      JOIN nidp.nse_financials_quarterly p
        ON p.symbol       = c.symbol
       AND p.consolidated = c.consolidated
       AND p.period_type ILIKE 'quarterly'
       AND p.source      <> 'screener_in_annual'          -- never subtract another annual figure
       AND p.period_end IN ((c.period_end - INTERVAL '3 months')::date,
                            (c.period_end - INTERVAL '6 months')::date,
                            (c.period_end - INTERVAL '9 months')::date)
     GROUP BY c.id
)
UPDATE nidp.nse_financials_quarterly t
   SET revenue_from_ops_cr = CASE WHEN p.n_rev = 3 AND t.revenue_from_ops_cr - p.p_rev >= 0
                                       THEN t.revenue_from_ops_cr - p.p_rev END,
       pat_cr              = CASE WHEN p.n_pat    = 3 THEN t.pat_cr           - p.p_pat END,
       eps_basic           = CASE WHEN p.n_eps    = 3 THEN t.eps_basic        - p.p_eps END,
       ebitda_cr           = CASE WHEN p.n_ebitda = 3 THEN t.ebitda_cr        - p.p_ebitda END,
       pbt_cr              = CASE WHEN p.n_pbt    = 3 THEN t.pbt_cr           - p.p_pbt END,
       finance_costs_cr    = CASE WHEN p.n_fin    = 3 THEN t.finance_costs_cr - p.p_fin END,
       depreciation_cr     = CASE WHEN p.n_dep    = 3 THEN t.depreciation_cr  - p.p_dep END,
       total_income_cr     = CASE WHEN p.n_ti     = 3 THEN t.total_income_cr  - p.p_ti END,
       period_start        = (t.period_end - INTERVAL '3 months' + INTERVAL '1 day')::date,
       source              = 'screener_in_derived_q4',
       ingested_at         = NOW()
  FROM prior3 p
 WHERE t.id = p.id
   AND p.nq = 3;

-- ── Rows that cannot be derived: blank the year rather than keep it as a quarter ─────
-- Typically March 2023, whose Jun/Sep/Dec 2022 quarters predate Screener's 13-quarter window.
-- The NULL keeps its place in the TTM window, so any window covering it reports NULL.
UPDATE nidp.nse_financials_quarterly
   SET revenue_from_ops_cr = NULL,
       pat_cr              = NULL,
       eps_basic           = NULL,
       ebitda_cr           = NULL,
       pbt_cr              = NULL,
       finance_costs_cr    = NULL,
       depreciation_cr     = NULL,
       total_income_cr     = NULL,
       source              = 'screener_in_annual_voided',
       ingested_at         = NOW()
 WHERE period_type ILIKE 'quarterly'
   AND source = 'screener_in_annual';

-- ── Report what is left ──────────────────────────────────────────────────────
DO $$
DECLARE
    v_derived INT;
    v_left    INT;
    v_syms    INT;
BEGIN
    SELECT count(*) INTO v_derived
      FROM nidp.nse_financials_quarterly
     WHERE source = 'screener_in_derived_q4';

    SELECT count(*), count(DISTINCT symbol) INTO v_left, v_syms
      FROM nidp.nse_financials_quarterly
     WHERE source = 'screener_in_annual_voided';

    RAISE NOTICE '143: % rows now hold a derived Q4; % rows (% symbols) had no three preceding '
                 'quarters and were blanked', v_derived, v_left, v_syms;
END $$;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('143_repair_annual_figures_in_quarterly_rows.sql')
ON CONFLICT (filename) DO NOTHING;

COMMIT;
