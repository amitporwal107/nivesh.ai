-- 054_nidp_v3_stock_signals.sql
--
-- Closes the V3 scoring engine gaps that are derivable from NIDP data:
--
--   3Y CAGR (from quarterly filing history):
--     eps_growth_3y_cagr_pct      -- 3Y EPS compound growth rate
--     revenue_growth_3y_cagr_pct  -- 3Y Revenue compound growth rate
--
--   Trend / delta signals (compare TTM windows):
--     profit_margin_trend_pct     -- current PAT margin − 1Y-ago PAT margin (pp)
--     debt_trend_pct              -- YoY % change in total debt
--
--   Derived binary flags (computable from columns already in stock_features_daily):
--     earnings_decline_flag       -- pat_growth_yoy_pct < 0
--     debt_spike_flag             -- debt_trend_pct > 20%
--
--   Composite signals (blended from existing technical + fundamental columns):
--     momentum_score              -- RSI + 1Y return + accumulation_score → 0-100
--     liquidity_score             -- market cap bucket + daily turnover → 0-100
--     earnings_consistency_score  -- % of last 8 quarters with PAT > 0 (Piotroski proxy)
--
-- Called by the V3 nightly batch AFTER populate_stock_features_extended()
-- and populate_stock_price_features() have already filled their respective
-- columns for the target date.

SET search_path TO nidp, public;


-- ── 1. Extend stock_features_daily ─────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'nidp' AND table_name = 'stock_features_daily'
    ) THEN
        RAISE NOTICE '054: stock_features_daily absent — ALTER deferred.';
        RETURN;
    END IF;

    EXECUTE $ddl$
        ALTER TABLE nidp.stock_features_daily
            ADD COLUMN IF NOT EXISTS eps_growth_3y_cagr_pct        NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS revenue_growth_3y_cagr_pct    NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS profit_margin_trend_pct        NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS debt_trend_pct                 NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS earnings_decline_flag          BOOLEAN,
            ADD COLUMN IF NOT EXISTS debt_spike_flag                BOOLEAN,
            ADD COLUMN IF NOT EXISTS momentum_score                 NUMERIC(6,2),
            ADD COLUMN IF NOT EXISTS liquidity_score                NUMERIC(6,2),
            ADD COLUMN IF NOT EXISTS earnings_consistency_score     NUMERIC(6,2)
    $ddl$;
END $$;


-- ── 2. populate_stock_features_v3(date) ────────────────────────────────
-- Fills all 9 new columns for a given as_of_date.
-- Dependency: run AFTER populate_stock_features_extended() and
--             populate_stock_price_features() for the same date.
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_v3(p_target_date DATE)
RETURNS INTEGER AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    WITH

    -- ── Quarterly rows ranked by recency, preferred consolidated ─────────
    q_ranked AS (
        SELECT *,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol, consolidated ORDER BY period_end DESC
               ) AS rn,
               MAX(consolidated::INT) OVER (PARTITION BY symbol) AS has_any_consol
          FROM nidp.nse_financials_quarterly
         WHERE period_type = 'QUARTERLY'
    ),

    -- Keep consolidated filings if they exist, else standalone
    q_pref AS (
        SELECT * FROM q_ranked
         WHERE (has_any_consol = 1 AND consolidated = TRUE)
            OR (has_any_consol = 0 AND consolidated = FALSE)
    ),

    -- ── Aggregate over four TTM windows per symbol ────────────────────────
    -- rn 1-4  → current TTM
    -- rn 5-8  → 1Y-ago TTM
    -- rn 13-16 → 3Y-ago TTM
    -- rn 1    → latest quarter debt
    -- rn 5    → 1Y-ago quarter debt (≈ same Q last year)
    cagr_src AS (
        SELECT
            symbol,
            SUM(eps_basic)           FILTER (WHERE rn BETWEEN 1  AND 4 ) AS eps_ttm_now,
            SUM(revenue_from_ops_cr) FILTER (WHERE rn BETWEEN 1  AND 4 ) AS rev_ttm_now,
            SUM(pat_cr)              FILTER (WHERE rn BETWEEN 1  AND 4 ) AS pat_ttm_now,
            SUM(eps_basic)           FILTER (WHERE rn BETWEEN 13 AND 16) AS eps_ttm_3y,
            SUM(revenue_from_ops_cr) FILTER (WHERE rn BETWEEN 13 AND 16) AS rev_ttm_3y,
            SUM(pat_cr)              FILTER (WHERE rn BETWEEN 5  AND 8 ) AS pat_ttm_1y,
            SUM(revenue_from_ops_cr) FILTER (WHERE rn BETWEEN 5  AND 8 ) AS rev_ttm_1y,
            MAX(COALESCE(long_term_debt_cr, 0) + COALESCE(short_term_debt_cr, 0))
                                     FILTER (WHERE rn = 1)               AS total_debt_now,
            MAX(COALESCE(long_term_debt_cr, 0) + COALESCE(short_term_debt_cr, 0))
                                     FILTER (WHERE rn = 5)               AS total_debt_1y,
            COUNT(*)                 FILTER (WHERE rn BETWEEN 1  AND 8  AND pat_cr > 0)
                                                                          AS positive_pat_q8
          FROM q_pref
         GROUP BY symbol
    )

    UPDATE nidp.stock_features_daily f
       SET
           -- ── 3Y EPS CAGR ───────────────────────────────────────────────
           -- Both endpoints must be positive for valid geometric mean.
           -- Encoding for special cases keeps the normaliser monotonic:
           --   profit→loss  → −50% (strong negative signal)
           --   loss→profit  → +50% (strong positive signal)
           eps_growth_3y_cagr_pct = CASE
               WHEN ci.eps_ttm_3y > 0 AND COALESCE(ci.eps_ttm_now, 0) > 0
               THEN ROUND(((ci.eps_ttm_now / ci.eps_ttm_3y) ^ (1.0/3.0) - 1.0) * 100, 4)
               WHEN ci.eps_ttm_3y > 0 AND COALESCE(ci.eps_ttm_now, 0) <= 0
               THEN -50.0
               WHEN COALESCE(ci.eps_ttm_3y, 0) <= 0 AND COALESCE(ci.eps_ttm_now, 0) > 0
               THEN 50.0
               ELSE NULL
           END,

           -- ── 3Y Revenue CAGR ───────────────────────────────────────────
           revenue_growth_3y_cagr_pct = CASE
               WHEN ci.rev_ttm_3y > 0 AND COALESCE(ci.rev_ttm_now, 0) > 0
               THEN ROUND(((ci.rev_ttm_now / ci.rev_ttm_3y) ^ (1.0/3.0) - 1.0) * 100, 4)
               ELSE NULL
           END,

           -- ── Profit margin trend (pp change, current vs 1Y-ago TTM) ────
           profit_margin_trend_pct = CASE
               WHEN ci.rev_ttm_now  > 0 AND ci.pat_ttm_now  IS NOT NULL
                AND ci.rev_ttm_1y   > 0 AND ci.pat_ttm_1y   IS NOT NULL
               THEN ROUND(
                   (ci.pat_ttm_now  / ci.rev_ttm_now  * 100)
                 - (ci.pat_ttm_1y   / ci.rev_ttm_1y   * 100),
                   4)
               ELSE NULL
           END,

           -- ── Debt trend YoY % ──────────────────────────────────────────
           debt_trend_pct = CASE
               WHEN ci.total_debt_1y  > 0 AND ci.total_debt_now IS NOT NULL
               THEN ROUND(
                   (ci.total_debt_now - ci.total_debt_1y) / ci.total_debt_1y * 100,
                   4)
               ELSE NULL
           END,

           -- ── Earnings decline flag ─────────────────────────────────────
           -- Uses pat_growth_yoy_pct already filled by populate_stock_features_extended().
           earnings_decline_flag = CASE
               WHEN f.pat_growth_yoy_pct IS NOT NULL THEN f.pat_growth_yoy_pct < 0
               ELSE NULL
           END,

           -- ── Debt spike flag (>20% YoY rise) ──────────────────────────
           debt_spike_flag = CASE
               WHEN ci.total_debt_1y > 0 AND ci.total_debt_now IS NOT NULL
               THEN (ci.total_debt_now - ci.total_debt_1y) / ci.total_debt_1y * 100 > 20
               ELSE NULL
           END,

           -- ── Momentum score (0-100) ────────────────────────────────────
           -- Components:
           --   rsi14 (0-100): 40% — already a 0-100 momentum proxy
           --   return_252d_pct band [−20, +40] → 0-100: 35%
           --   accumulation_score (0..1) × 100: 25% — OBV-derived buying pressure
           momentum_score = GREATEST(0.0, LEAST(100.0,
               0.40 * COALESCE(f.rsi14, 50.0)
             + 0.35 * GREATEST(0.0, LEAST(100.0,
                         (COALESCE(f.return_252d_pct, 0.0) + 20.0) / 60.0 * 100.0))
             + 0.25 * COALESCE(f.accumulation_score * 100.0, 50.0)
           ))::NUMERIC(6,2),

           -- ── Liquidity score (0-100) ───────────────────────────────────
           -- Components:
           --   market_cap_bucket (50%): proxy for institutional marketability
           --   daily turnover % of market cap (50%): measures real liquidity depth
           --   turnover band: 0.3% daily turnover → 100 (mid-liquidity = benchmark)
           liquidity_score = GREATEST(0.0, LEAST(100.0,
               0.50 * CASE f.market_cap_bucket
                          WHEN 'LARGE_CAP' THEN 100.0
                          WHEN 'MID_CAP'   THEN  65.0
                          WHEN 'SMALL_CAP' THEN  35.0
                          WHEN 'MICRO_CAP' THEN  10.0
                          ELSE 50.0
                      END
             + 0.50 * CASE
                          WHEN f.market_cap_cr > 0 AND f.close > 0 AND f.volume > 0
                          THEN LEAST(100.0,
                               -- daily traded value / market_cap as %: 0.3% → 100
                               (f.volume::NUMERIC * f.close / (f.market_cap_cr * 1.0e7) * 100.0)
                               / 0.30 * 100.0)
                          ELSE 50.0
                      END
           ))::NUMERIC(6,2),

           -- ── Earnings consistency score (0-100) ───────────────────────
           -- % of last 8 quarters with positive PAT.
           -- 8/8 = 100 (perfectly consistent); 4/8 = 50; 0/8 = 0.
           earnings_consistency_score = CASE
               WHEN ci.positive_pat_q8 IS NOT NULL
               THEN ROUND((ci.positive_pat_q8::NUMERIC / 8.0 * 100.0), 2)
               ELSE NULL
           END

      FROM cagr_src ci
     WHERE f.symbol     = ci.symbol
       AND f.as_of_date = p_target_date;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$ LANGUAGE plpgsql;


-- ── 3. Update refresh_stock_features() to include the new pass ─────────
CREATE OR REPLACE FUNCTION nidp.refresh_stock_features(p_target_date DATE)
RETURNS TEXT AS $$
DECLARE
    v_ext   INTEGER;
    v_price INTEGER;
    v_v3    INTEGER;
BEGIN
    -- Pass 1: fundamentals + shareholding + new 053 metrics
    SELECT nidp.populate_stock_features_extended(p_target_date) INTO v_ext;
    -- Pass 2: price-history (return, vol, beta, drawdown) from adj close window
    SELECT nidp.populate_stock_price_features(p_target_date)    INTO v_price;
    -- Pass 3: V3 scoring signals (3Y CAGRs, trends, flags, composite scores)
    SELECT nidp.populate_stock_features_v3(p_target_date)       INTO v_v3;
    RETURN FORMAT('extended=%s price=%s v3=%s', v_ext, v_price, v_v3);
END;
$$ LANGUAGE plpgsql;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('054_nidp_v3_stock_signals.sql')
ON CONFLICT (filename) DO NOTHING;
