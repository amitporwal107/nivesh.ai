-- Migration 089: Fix revenue_growth_3y_cagr_pct to use annual P&L data
--
-- Root cause: populate_stock_features_v3 computed 3Y CAGR from quarterly rows
-- ranked 13-16 (the TTM window from 3 years ago). Our nse_financials_quarterly
-- table has max 15 quarterly rows per symbol so rn 13-16 is always empty →
-- revenue_growth_3y_cagr_pct and eps_growth_3y_cagr_pct are NULL for all symbols
-- via this path. Only the Groww scraper path was populating ~238 symbols.
--
-- Fix: rewrite the 3Y CAGR CTEs to use period_type IN ('annual','ANNUAL') rows.
-- For each symbol:
--   • rev_now  = revenue_from_ops_cr from the most recent annual row
--   • rev_base = revenue_from_ops_cr from the annual row closest to (latest_fy - 3y)
--                that is at least 2 years before latest_fy
--   • year_span = EXTRACT(YEAR FROM latest_fy) - EXTRACT(YEAR FROM base_fy)
--   • CAGR = (rev_now/rev_base)^(1/year_span) - 1
-- Only computed when year_span >= 2 and both revenue values > 0.
--
-- All non-CAGR fields (margin trend, debt trend, consistency, momentum, liquidity)
-- continue to use quarterly rows as before.
--
-- Coverage gain on Nifty 500: 47% → ~85%+ (limited by annual data staleness;
-- run nse_financials_backfill for FY2023-FY2025 to reach full 3Y accuracy).

CREATE OR REPLACE FUNCTION nidp.populate_stock_features_v3(p_target_date date)
  RETURNS integer
  LANGUAGE plpgsql
 AS $function$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH

    -- ── Annual rows, prefer consolidated if available ─────────────────────
    ann_raw AS (
        SELECT *,
               MAX(consolidated::INT) OVER (PARTITION BY symbol) AS has_any_consol
          FROM nidp.nse_financials_quarterly
         WHERE period_type IN ('annual', 'ANNUAL')
    ),
    ann_pref AS (
        SELECT * FROM ann_raw
         WHERE (has_any_consol = 1 AND consolidated = TRUE)
            OR (has_any_consol = 0 AND consolidated = FALSE)
    ),

    -- ── Latest annual row per symbol ──────────────────────────────────────
    ann_latest AS (
        SELECT DISTINCT ON (symbol)
               symbol,
               period_end          AS latest_fy,
               revenue_from_ops_cr AS rev_now,
               eps_basic           AS eps_now
          FROM ann_pref
         ORDER BY symbol, period_end DESC
    ),

    -- ── Base annual row: closest to (latest_fy - 3y), min 2y before latest ─
    ann_base AS (
        SELECT DISTINCT ON (a.symbol)
               a.symbol,
               a.period_end          AS base_fy,
               a.revenue_from_ops_cr AS rev_base,
               a.eps_basic           AS eps_base
          FROM ann_pref a
          JOIN ann_latest l ON l.symbol = a.symbol
         WHERE a.period_end <= l.latest_fy - INTERVAL '2 years'
         ORDER BY a.symbol,
                  ABS(EXTRACT(EPOCH FROM (a.period_end - (l.latest_fy - INTERVAL '3 years'))))
    ),

    -- ── Combined annual CAGR source ───────────────────────────────────────
    ann_cagr AS (
        SELECT
            l.symbol,
            l.latest_fy,
            b.base_fy,
            EXTRACT(YEAR FROM l.latest_fy) - EXTRACT(YEAR FROM b.base_fy) AS year_span,
            l.rev_now,
            b.rev_base,
            l.eps_now,
            b.eps_base
          FROM ann_latest l
          JOIN ann_base b ON b.symbol = l.symbol
    ),

    -- ── Quarterly rows for non-CAGR V3 metrics (unchanged logic) ─────────
    q_ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol, consolidated ORDER BY period_end DESC
               ) AS rn,
               MAX(consolidated::INT) OVER (PARTITION BY symbol) AS has_any_consol
          FROM nidp.nse_financials_quarterly
         WHERE period_type = 'QUARTERLY'
    ),
    q_pref AS (
        SELECT * FROM q_ranked
         WHERE (has_any_consol = 1 AND consolidated = TRUE)
            OR (has_any_consol = 0 AND consolidated = FALSE)
    ),
    q_agg AS (
        SELECT
            symbol,
            SUM(pat_cr)              FILTER (WHERE rn BETWEEN 1 AND 4)  AS pat_ttm_now,
            SUM(revenue_from_ops_cr) FILTER (WHERE rn BETWEEN 1 AND 4)  AS rev_ttm_now,
            SUM(pat_cr)              FILTER (WHERE rn BETWEEN 5 AND 8)  AS pat_ttm_1y,
            SUM(revenue_from_ops_cr) FILTER (WHERE rn BETWEEN 5 AND 8)  AS rev_ttm_1y,
            MAX(COALESCE(long_term_debt_cr, 0) + COALESCE(short_term_debt_cr, 0))
                                     FILTER (WHERE rn = 1)               AS total_debt_now,
            MAX(COALESCE(long_term_debt_cr, 0) + COALESCE(short_term_debt_cr, 0))
                                     FILTER (WHERE rn = 5)               AS total_debt_1y,
            COUNT(*)                 FILTER (WHERE rn BETWEEN 1 AND 8 AND pat_cr > 0)
                                                                          AS positive_pat_q8
          FROM q_pref
         GROUP BY symbol
    ),

    -- ── Merge: all symbols that have either annual or quarterly data ───────
    merged AS (
        SELECT
            COALESCE(a.symbol, q.symbol) AS symbol,
            a.rev_now,
            a.rev_base,
            a.eps_now,
            a.eps_base,
            a.year_span,
            q.pat_ttm_now,
            q.rev_ttm_now,
            q.pat_ttm_1y,
            q.rev_ttm_1y,
            q.total_debt_now,
            q.total_debt_1y,
            q.positive_pat_q8
          FROM ann_cagr a
          FULL OUTER JOIN q_agg q ON q.symbol = a.symbol
    )

    UPDATE nidp.stock_features_daily f
       SET

           -- ── 3Y Revenue CAGR (annual source) ───────────────────────────
           revenue_growth_3y_cagr_pct = CASE
               WHEN ci.rev_now  > 0
                AND ci.rev_base > 0
                AND ci.year_span >= 2
               THEN ROUND((
                   (ci.rev_now / ci.rev_base) ^ (1.0 / ci.year_span) - 1.0
               ) * 100, 4)
               ELSE NULL
           END,

           -- ── 3Y EPS CAGR (annual source) ───────────────────────────────
           eps_growth_3y_cagr_pct = CASE
               WHEN ci.eps_now  > 0 AND ci.eps_base  > 0 AND ci.year_span >= 2
               THEN ROUND((
                   (ci.eps_now / ci.eps_base) ^ (1.0 / ci.year_span) - 1.0
               ) * 100, 4)
               WHEN COALESCE(ci.eps_base, 0) > 0 AND COALESCE(ci.eps_now, 0) <= 0
               THEN -50.0
               WHEN COALESCE(ci.eps_base, 0) <= 0 AND COALESCE(ci.eps_now, 0) > 0
               THEN 50.0
               ELSE NULL
           END,

           -- ── Profit margin trend (quarterly TTM, unchanged) ────────────
           profit_margin_trend_pct = CASE
               WHEN ci.rev_ttm_now  > 0 AND ci.pat_ttm_now  IS NOT NULL
                AND ci.rev_ttm_1y   > 0 AND ci.pat_ttm_1y   IS NOT NULL
               THEN ROUND(
                   (ci.pat_ttm_now  / ci.rev_ttm_now  * 100)
                 - (ci.pat_ttm_1y   / ci.rev_ttm_1y   * 100), 4)
               ELSE NULL
           END,

           -- ── Debt trend YoY % (quarterly, unchanged) ───────────────────
           debt_trend_pct = CASE
               WHEN ci.total_debt_1y  > 0 AND ci.total_debt_now IS NOT NULL
               THEN ROUND(
                   (ci.total_debt_now - ci.total_debt_1y) / ci.total_debt_1y * 100, 4)
               ELSE NULL
           END,

           -- ── Earnings decline flag (unchanged) ─────────────────────────
           earnings_decline_flag = CASE
               WHEN f.pat_growth_yoy_pct IS NOT NULL THEN f.pat_growth_yoy_pct < 0
               ELSE NULL
           END,

           -- ── Debt spike flag >20% YoY (unchanged) ──────────────────────
           debt_spike_flag = CASE
               WHEN ci.total_debt_1y > 0 AND ci.total_debt_now IS NOT NULL
               THEN (ci.total_debt_now - ci.total_debt_1y) / ci.total_debt_1y * 100 > 20
               ELSE NULL
           END,

           -- ── Momentum score (unchanged) ────────────────────────────────
           momentum_score = GREATEST(0.0, LEAST(100.0,
               0.40 * COALESCE(f.rsi14, 50.0)
             + 0.35 * GREATEST(0.0, LEAST(100.0,
                         (COALESCE(f.return_252d_pct, 0.0) + 20.0) / 60.0 * 100.0))
             + 0.25 * COALESCE(f.accumulation_score * 100.0, 50.0)
           ))::NUMERIC(6,2),

           -- ── Liquidity score (unchanged) ───────────────────────────────
           liquidity_score = GREATEST(0.0, LEAST(100.0,
               0.50 * CASE f.market_cap_bucket
                          WHEN 'LARGE_CAP' THEN 100.0
                          WHEN 'MID_CAP'   THEN  65.0
                          WHEN 'SMALL_CAP' THEN  35.0
                          WHEN 'MICRO_CAP' THEN  10.0
                          ELSE 50.0
                      END
             + 0.50 * CASE
                          WHEN f.market_cap_cr > 0 AND f.close > 0 AND f.avg_volume_20 > 0
                          THEN LEAST(100.0,
                               (f.avg_volume_20::NUMERIC * f.close / (f.market_cap_cr * 1.0e7) * 100.0)
                               / 0.30 * 100.0)
                          ELSE 50.0
                      END
           ))::NUMERIC(6,2),

           -- ── Earnings consistency score (unchanged) ────────────────────
           earnings_consistency_score = CASE
               WHEN ci.positive_pat_q8 IS NOT NULL
               THEN ROUND((ci.positive_pat_q8::NUMERIC / 8.0 * 100.0), 2)
               ELSE NULL
           END

      FROM merged ci
     WHERE f.symbol     = ci.symbol
       AND f.as_of_date = p_target_date;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$function$;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('089_fix_revenue_3y_cagr_annual_source.sql')
ON CONFLICT (filename) DO NOTHING;
