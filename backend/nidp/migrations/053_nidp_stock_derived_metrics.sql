-- 053_nidp_stock_derived_metrics.sql
--
-- Adds the investor + advisor metric set that was missing from stock_features_daily:
--
--   Market / valuation:
--     shares_outstanding     -- (equity_share_capital_cr × 1e7) / face_value
--     market_cap_cr          -- shares_outstanding × close / 1e7
--     market_cap_bucket      -- LARGE_CAP / MID_CAP / SMALL_CAP / MICRO_CAP
--     enterprise_value_cr    -- market_cap + total_debt - cash
--     ev_ebitda              -- enterprise_value / ebitda_ttm
--     pe_vs_sector_pct       -- (pe_ttm / sector_median_pe - 1) × 100
--
--   Profitability / quality:
--     roce_pct               -- ebit_ttm / capital_employed × 100
--     interest_coverage      -- ebit_ttm / finance_costs_ttm
--     profit_margin_pct      -- pat_ttm / revenue_ttm × 100
--
--   Income:
--     dividend_yield_pct     -- sum(dividends last 12m) / close × 100
--
--   Price-history (Sprint 1 backlog — require ≥252 bars of adj. close):
--     return_252d_pct        -- (close_today / close_252d_ago - 1) × 100
--     volatility_1y_pct      -- stddev(daily log-ret, 252 bars) × √252 × 100
--     beta_1y                -- REGR_SLOPE(fund_log_ret, nifty_log_ret, 252 bars)
--     max_drawdown_1y_pct    -- max peak-to-trough drawdown over 252 bars
--
-- EBIT proxy used for ROCE / interest_coverage:
--   ebit_ttm = pbt_ttm + finance_costs_ttm    (both from XBRL P&L)
-- Capital Employed proxy (total_assets − current_liabilities not in XBRL):
--   capital_employed = total_equity + long_term_debt
--
-- All monetary values in ₹ crore (consistent with rest of NIDP schema).

SET search_path TO nidp, public;


-- ── 1. Refresh v_stock_fundamentals_latest ────────────────────────────
-- Adds: ebitda_ttm_cr, depreciation_ttm_cr, finance_costs_ttm_cr,
--        pbt_ttm_cr, ebit_ttm_cr, capital_employed_cr, equity_share_capital_cr.
-- DROP + CREATE because CREATE OR REPLACE can't reorder/insert columns;
-- v_stock_features_full (which joins this view) is recreated below.

DROP VIEW IF EXISTS nidp.v_stock_features_full;
DROP VIEW IF EXISTS nidp.v_stock_fundamentals_latest;
CREATE VIEW nidp.v_stock_fundamentals_latest AS
WITH

ranked AS (
    SELECT f.*,
           ROW_NUMBER() OVER (
               PARTITION BY f.symbol
               ORDER BY f.consolidated DESC, f.period_end DESC
           ) AS rn
      FROM nidp.nse_financials_quarterly f
     WHERE f.period_type IN ('QUARTERLY','HALF_YEARLY','NINE_MONTHS','ANNUAL')
),

-- Trailing 12-month sums (last 4 quarterly filings per symbol)
ttm AS (
    SELECT
        symbol, consolidated,
        SUM(revenue_from_ops_cr) FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS revenue_ttm_cr,
        SUM(pat_cr)              FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS pat_ttm_cr,
        SUM(eps_basic)           FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS eps_ttm,
        SUM(ebitda_cr)           FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS ebitda_ttm_cr,
        SUM(depreciation_cr)     FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS depreciation_ttm_cr,
        SUM(finance_costs_cr)    FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS finance_costs_ttm_cr,
        SUM(pbt_cr)              FILTER (WHERE rn_back <= 4 AND period_type = 'QUARTERLY') AS pbt_ttm_cr
      FROM (
          SELECT f.*,
                 ROW_NUMBER() OVER (
                     PARTITION BY symbol, consolidated ORDER BY period_end DESC
                 ) AS rn_back
            FROM nidp.nse_financials_quarterly f
           WHERE period_type = 'QUARTERLY'
      ) q
     GROUP BY symbol, consolidated
),

-- Year-over-year deltas (same quarter last year)
yoy AS (
    SELECT
        cur.symbol, cur.consolidated, cur.period_end AS cur_period_end,
        cur.revenue_from_ops_cr AS cur_revenue, prv.revenue_from_ops_cr AS prv_revenue,
        cur.pat_cr AS cur_pat,   prv.pat_cr AS prv_pat,
        cur.eps_basic AS cur_eps, prv.eps_basic AS prv_eps
      FROM nidp.nse_financials_quarterly cur
      LEFT JOIN nidp.nse_financials_quarterly prv
             ON prv.symbol       = cur.symbol
            AND prv.consolidated = cur.consolidated
            AND prv.period_type  = cur.period_type
            AND prv.period_end   = (cur.period_end - INTERVAL '1 year')::date
)

SELECT
    -- ── Original columns (must stay in original order for DROP+CREATE) ──
    r.symbol,
    r.period_end,
    r.period_type,
    r.consolidated,
    r.revenue_from_ops_cr,
    r.pat_cr,
    r.eps_basic,
    r.eps_diluted,
    r.total_equity_cr,
    r.long_term_debt_cr,
    r.short_term_debt_cr,
    r.cash_and_equiv_cr,
    t.revenue_ttm_cr,
    t.pat_ttm_cr,
    t.eps_ttm,
    CASE WHEN y.prv_revenue > 0
         THEN ROUND(((y.cur_revenue - y.prv_revenue) / y.prv_revenue * 100)::NUMERIC, 4)
         ELSE NULL
    END AS revenue_growth_yoy_pct,
    CASE WHEN y.prv_pat IS NOT NULL AND y.prv_pat <> 0
         THEN ROUND(((y.cur_pat - y.prv_pat) / ABS(y.prv_pat) * 100)::NUMERIC, 4)
         ELSE NULL
    END AS pat_growth_yoy_pct,
    CASE WHEN y.prv_eps IS NOT NULL AND y.prv_eps <> 0
         THEN ROUND(((y.cur_eps - y.prv_eps) / ABS(y.prv_eps) * 100)::NUMERIC, 4)
         ELSE NULL
    END AS eps_growth_yoy_pct,
    CASE WHEN r.total_equity_cr > 0 AND r.pat_cr IS NOT NULL
         THEN ROUND((r.pat_cr * 4 / r.total_equity_cr * 100)::NUMERIC, 4)
         ELSE NULL
    END AS roe_annualised_pct,
    CASE WHEN r.total_equity_cr > 0
         THEN ROUND((COALESCE(r.long_term_debt_cr, 0) + COALESCE(r.short_term_debt_cr, 0))
                    / r.total_equity_cr, 4)
         ELSE NULL
    END AS debt_to_equity,
    r.broadcast_at,
    r.source_run_id,

    -- ── New columns (appended — safe for DROP+CREATE) ─────────────────
    r.equity_share_capital_cr,
    t.ebitda_ttm_cr,
    t.depreciation_ttm_cr,
    t.finance_costs_ttm_cr,
    t.pbt_ttm_cr,
    -- EBIT TTM = PBT + Finance Costs (standard XBRL P&L identity)
    CASE WHEN t.pbt_ttm_cr IS NOT NULL AND t.finance_costs_ttm_cr IS NOT NULL
         THEN ROUND((t.pbt_ttm_cr + t.finance_costs_ttm_cr)::NUMERIC, 4)
         ELSE NULL
    END AS ebit_ttm_cr,
    -- Capital Employed = Equity + LT Debt (proxy for total_assets - current_liabilities)
    CASE WHEN r.total_equity_cr IS NOT NULL
         THEN ROUND((r.total_equity_cr + COALESCE(r.long_term_debt_cr, 0))::NUMERIC, 4)
         ELSE NULL
    END AS capital_employed_cr

  FROM ranked r
  LEFT JOIN ttm t ON t.symbol = r.symbol AND t.consolidated = r.consolidated
  LEFT JOIN yoy y ON y.symbol = r.symbol AND y.consolidated = r.consolidated
                  AND y.cur_period_end = r.period_end
 WHERE r.rn = 1;


-- ── 2. Add new columns to stock_features_daily ────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'nidp' AND table_name = 'stock_features_daily'
    ) THEN
        RAISE NOTICE '053: stock_features_daily absent — ALTER deferred.';
        RETURN;
    END IF;

    EXECUTE $ddl$
        ALTER TABLE nidp.stock_features_daily
            -- Market / shares
            ADD COLUMN IF NOT EXISTS shares_outstanding  BIGINT,
            ADD COLUMN IF NOT EXISTS market_cap_cr       NUMERIC(18,2),
            ADD COLUMN IF NOT EXISTS market_cap_bucket   TEXT,          -- LARGE_CAP / MID_CAP / SMALL_CAP / MICRO_CAP

            -- Valuation
            ADD COLUMN IF NOT EXISTS enterprise_value_cr NUMERIC(18,2),
            ADD COLUMN IF NOT EXISTS ev_ebitda           NUMERIC(10,2),
            ADD COLUMN IF NOT EXISTS pe_vs_sector_pct    NUMERIC(10,2), -- (pe_ttm/sector_median_pe - 1)*100

            -- Profitability
            ADD COLUMN IF NOT EXISTS roce_pct            NUMERIC(10,2),
            ADD COLUMN IF NOT EXISTS interest_coverage   NUMERIC(10,2),
            ADD COLUMN IF NOT EXISTS profit_margin_pct   NUMERIC(10,2),

            -- Income
            ADD COLUMN IF NOT EXISTS dividend_yield_pct  NUMERIC(8,4),

            -- Price-history (Sprint 1 backlog)
            ADD COLUMN IF NOT EXISTS return_252d_pct     NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS volatility_1y_pct   NUMERIC(10,4),
            ADD COLUMN IF NOT EXISTS beta_1y             NUMERIC(8,4),
            ADD COLUMN IF NOT EXISTS max_drawdown_1y_pct NUMERIC(10,4)
    $ddl$;

    -- Index market_cap for screener queries
    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_features_market_cap
            ON nidp.stock_features_daily(market_cap_cr DESC, as_of_date DESC)
            WHERE market_cap_cr IS NOT NULL
    $ddl$;

    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_features_cap_bucket_date
            ON nidp.stock_features_daily(market_cap_bucket, as_of_date DESC)
            WHERE market_cap_bucket IS NOT NULL
    $ddl$;
END $$;


-- ── 3. Update populate_stock_features_extended() ──────────────────────
-- Extends the existing function to also fill the new columns.
-- The price-history columns (return_252d, volatility, beta, maxdd) are
-- populated by the separate populate_stock_price_features() below.
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date DATE)
RETURNS INTEGER AS $$
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
           -- shares = (equity_share_capital_cr × 1e7) / face_value
           shares_outstanding = CASE
               WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0
               THEN ROUND((fund.equity_share_capital_cr * 1e7 / sm.face_value))::BIGINT
               ELSE NULL END,

           -- market_cap_cr = shares × close / 1e7
           -- = equity_share_capital_cr × close / face_value
           market_cap_cr = CASE
               WHEN fund.equity_share_capital_cr > 0 AND sm.face_value > 0 AND f.close > 0
               THEN ROUND((fund.equity_share_capital_cr * f.close / sm.face_value)::NUMERIC, 2)
               ELSE NULL END,

           -- SEBI cap bucket by approximate ₹ crore thresholds
           -- (dynamically by rank is better but requires full-scan; use value cutoffs)
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
           -- EV = market_cap + total_debt - cash  (all in ₹ crore)
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
           pe_vs_sector_pct = CASE
               WHEN smp.sector_median_pe > 0 AND fund.eps_ttm > 0 AND f.close > 0
               THEN ROUND(((f.close / fund.eps_ttm) / smp.sector_median_pe - 1) * 100, 2)::NUMERIC
               ELSE NULL END,

           -- ── ROCE ─────────────────────────────────────────────────────
           -- ROCE = EBIT_TTM / Capital_Employed × 100
           -- Capital Employed = total_equity + long_term_debt (proxy)
           roce_pct = CASE
               WHEN fund.ebit_ttm_cr IS NOT NULL AND fund.capital_employed_cr > 0
               THEN ROUND((fund.ebit_ttm_cr / fund.capital_employed_cr * 100)::NUMERIC, 2)
               ELSE NULL END,

           -- ── Interest Coverage ─────────────────────────────────────────
           -- IC = EBIT_TTM / Finance_Costs_TTM
           interest_coverage = CASE
               WHEN fund.ebit_ttm_cr IS NOT NULL
                AND fund.finance_costs_ttm_cr IS NOT NULL
                AND fund.finance_costs_ttm_cr > 0
               THEN ROUND((fund.ebit_ttm_cr / fund.finance_costs_ttm_cr)::NUMERIC, 2)
               ELSE NULL END,

           -- ── Profit Margin ─────────────────────────────────────────────
           -- PAT Margin = PAT_TTM / Revenue_TTM × 100
           profit_margin_pct = CASE
               WHEN fund.pat_ttm_cr IS NOT NULL AND fund.revenue_ttm_cr > 0
               THEN ROUND((fund.pat_ttm_cr / fund.revenue_ttm_cr * 100)::NUMERIC, 2)
               ELSE NULL END,

           -- ── Dividend Yield ────────────────────────────────────────────
           -- Sum of all dividends declared (ex_date) in last 12 months / close
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
      -- Sector median PE (from migration 048)
      LEFT JOIN (
          SELECT DISTINCT sector, sector_median_pe
            FROM nidp.v_sector_median_pe
      ) smp ON smp.sector = f0.sector
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
$$ LANGUAGE plpgsql;


-- ── 4. populate_stock_price_features() ───────────────────────────────
-- Computes the four price-history metrics that require a 252-bar window
-- of adjusted close prices:
--   return_252d_pct     — (close_today / close_252d_ago - 1) × 100
--   volatility_1y_pct   — std(log-returns, 252 bars) × √252 × 100
--   beta_1y             — REGR_SLOPE(fund_log_ret, nifty_log_ret)
--   max_drawdown_1y_pct — max peak-to-trough over 252 bars (negative)
--
-- Called separately from populate_stock_features_extended because it
-- reads a large window (252 rows/symbol) rather than a point-in-time join.
-- Benchmark: Nifty 50 from nidp.index_eod.
CREATE OR REPLACE FUNCTION nidp.populate_stock_price_features(
    p_target_date DATE,
    p_window_days INTEGER DEFAULT 365,   -- calendar days to look back (~252 trading days)
    p_min_bars    INTEGER DEFAULT 60     -- minimum bars to compute; skip below this
)
RETURNS INTEGER AS $$
DECLARE
    v_rows INTEGER;
    v_since DATE;
BEGIN
    v_since := p_target_date - p_window_days;

    -- Single-pass CTE: join 252 bars of fund prices with Nifty 50, compute
    -- daily log-returns for both, then aggregate into the 4 metrics.
    WITH

    -- Nifty 50 daily close (benchmark)
    nifty AS (
        SELECT as_of_date,
               LN(close_price / NULLIF(LAG(close_price) OVER (ORDER BY as_of_date), 0)) AS log_ret
          FROM nidp.index_eod
         WHERE index_name = 'Nifty 50'
           AND as_of_date BETWEEN v_since AND p_target_date
           AND close_price > 0
    ),

    -- Fund daily log-returns from adjusted close
    fund_daily AS (
        SELECT
            symbol,
            as_of_date,
            adj_close,
            LN(adj_close / NULLIF(LAG(adj_close) OVER (PARTITION BY symbol ORDER BY as_of_date), 0)) AS log_ret
          FROM nidp.prices_eod_adjusted
         WHERE as_of_date BETWEEN v_since AND p_target_date
           AND adj_close > 0
           AND source = 'NIDP_PRICE_ADJUSTER'
    ),

    -- Join fund with benchmark on matching dates
    paired AS (
        SELECT
            f.symbol,
            f.as_of_date,
            f.adj_close,
            f.log_ret         AS fund_log_ret,
            n.log_ret         AS nifty_log_ret
          FROM fund_daily f
          JOIN nifty n ON n.as_of_date = f.as_of_date
         WHERE f.log_ret IS NOT NULL
           AND n.log_ret IS NOT NULL
    ),

    -- Running maximum for drawdown (per symbol, over window)
    with_peak AS (
        SELECT
            symbol,
            as_of_date,
            adj_close,
            fund_log_ret,
            nifty_log_ret,
            MAX(adj_close) OVER (
                PARTITION BY symbol
                ORDER BY as_of_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
            ) AS running_peak
          FROM paired
    ),

    -- Per-symbol aggregates (Beta via REGR_SLOPE = cov(Y,X)/var(X))
    agg AS (
        SELECT
            symbol,
            COUNT(*)                                                               AS bar_count,
            -- 1Y return: last adj_close vs first adj_close in window
            ROUND(((LAST_VALUE(adj_close) OVER w_full
                  / NULLIF(FIRST_VALUE(adj_close) OVER w_full, 0) - 1) * 100)::NUMERIC, 4)
                                                                                   AS return_252d_pct,
            -- Annualised volatility (std of log-returns × √252 × 100)
            ROUND((STDDEV_SAMP(fund_log_ret) OVER w_full * SQRT(252) * 100)::NUMERIC, 4)
                                                                                   AS volatility_1y_pct,
            -- Beta = slope of fund_log_ret on nifty_log_ret (OLS)
            ROUND(REGR_SLOPE(fund_log_ret, nifty_log_ret) OVER w_full::NUMERIC, 4) AS beta_1y,
            -- Max drawdown: worst (adj_close - peak) / peak (negative value)
            ROUND(MIN((adj_close - running_peak) / NULLIF(running_peak, 0) * 100) OVER w_full::NUMERIC, 4)
                                                                                   AS max_drawdown_1y_pct
          FROM with_peak
          WINDOW w_full AS (PARTITION BY symbol)
    ),

    -- Deduplicate: one row per symbol (all window functions give same result per partition)
    summary AS (
        SELECT DISTINCT ON (symbol)
            symbol,
            bar_count,
            return_252d_pct,
            volatility_1y_pct,
            beta_1y,
            max_drawdown_1y_pct
          FROM agg
    )

    -- Apply to stock_features_daily for p_target_date
    UPDATE nidp.stock_features_daily f
       SET return_252d_pct     = CASE WHEN s.bar_count >= p_min_bars THEN s.return_252d_pct     ELSE NULL END,
           volatility_1y_pct   = CASE WHEN s.bar_count >= p_min_bars THEN s.volatility_1y_pct   ELSE NULL END,
           beta_1y             = CASE WHEN s.bar_count >= p_min_bars THEN s.beta_1y             ELSE NULL END,
           max_drawdown_1y_pct = CASE WHEN s.bar_count >= p_min_bars THEN s.max_drawdown_1y_pct ELSE NULL END
      FROM summary s
     WHERE f.symbol     = s.symbol
       AND f.as_of_date = p_target_date;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$ LANGUAGE plpgsql;


-- ── 5. Convenience: refresh both passes in one call ───────────────────
CREATE OR REPLACE FUNCTION nidp.refresh_stock_features(p_target_date DATE)
RETURNS TEXT AS $$
DECLARE
    v_ext  INTEGER;
    v_price INTEGER;
BEGIN
    SELECT nidp.populate_stock_features_extended(p_target_date) INTO v_ext;
    SELECT nidp.populate_stock_price_features(p_target_date)    INTO v_price;
    RETURN FORMAT('extended=%s price=%s', v_ext, v_price);
END;
$$ LANGUAGE plpgsql;


-- ── 6. Recreate v_stock_features_full (dropped by CASCADE above) ─────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'nidp' AND table_name = 'stock_features_daily'
    ) THEN
        RAISE NOTICE '053: stock_features_daily absent — v_stock_features_full deferred.';
        RETURN;
    END IF;
    EXECUTE $ddl$
CREATE OR REPLACE VIEW nidp.v_stock_features_full AS
SELECT
    f.*,
    fund.revenue_ttm_cr,
    fund.pat_ttm_cr,
    fund.eps_ttm,
    fund.total_equity_cr,
    fund.long_term_debt_cr,
    fund.short_term_debt_cr,
    fund.cash_and_equiv_cr,
    fund.equity_share_capital_cr,
    fund.ebitda_ttm_cr,
    fund.ebit_ttm_cr,
    fund.capital_employed_cr,
    fund.finance_costs_ttm_cr,
    shp.insurance_pct,
    shp.individual_pct,
    shp.mf_pct_change_qoq,
    shp.pledge_pct_change_qoq,
    sm.isin,
    sm.listing_date,
    sm.face_value
  FROM nidp.stock_features_daily f
  LEFT JOIN nidp.v_stock_fundamentals_latest fund ON fund.symbol = f.symbol
  LEFT JOIN nidp.v_shareholding_latest shp         ON shp.symbol  = f.symbol
  LEFT JOIN nidp.sector_master sm                  ON sm.symbol   = f.symbol
    $ddl$;
END $$;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('053_nidp_stock_derived_metrics.sql')
ON CONFLICT (filename) DO NOTHING;
