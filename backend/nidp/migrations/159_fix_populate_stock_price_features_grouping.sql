-- 159_fix_populate_stock_price_features_grouping.sql
--
-- nidp.populate_stock_price_features (migration 053) could never run: its `agg`
-- CTE selected a plain COUNT(*) next to window functions with no GROUP BY, so
-- every call raised
--     GroupingError: column "with_peak.symbol" must appear in the GROUP BY
--     clause or be used in an aggregate function
-- plpgsql only checks a function body when it is executed, so the migration
-- applied cleanly and the technical_indicator_engine reported the error on each
-- run (exit code 2), leaving return_252d_pct, volatility_1y_pct, beta_1y and
-- max_drawdown_1y_pct NULL in nidp.stock_features_daily.
--
-- The count is a per-symbol window count like the other columns of that CTE.
-- The function is otherwise identical to 053.

SET search_path TO nidp, public;

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
            COUNT(*) OVER w_full                                                   AS bar_count,
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
