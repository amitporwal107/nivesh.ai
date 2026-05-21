-- 060_fix_populate_stock_price_features.sql
--
-- Repo-commits the hot-patch that was applied in prod to fix migration 053's
-- populate_stock_price_features() function.
--
-- Why this exists:
--   The original `agg` CTE in 053 selected `symbol` (raw column) plus
--   `COUNT(*)` (bare aggregate) plus four window expressions OVER w_full.
--   With a bare aggregate in the SELECT list, Postgres applies implicit
--   GROUP-BY semantics — which require `symbol` in the GROUP BY clause.
--   But `symbol` is the partition key of w_full, not a group key, so the
--   function raised:
--     ERROR: column "with_peak.symbol" must appear in the GROUP BY clause
--   The whole price-features pass died silently → volatility_1y_pct,
--   beta_1y, return_252d_pct, max_drawdown_1y_pct stayed NULL across the
--   universe → the Risk ribbon in V3 went dark.
--
-- The fix:
--   Replace `COUNT(*)` with `COUNT(*) OVER w_full` so every projected
--   column is a window expression — no implicit GROUP BY, no error.
--
-- History:
--   - 2026-05-20 — applied directly to prod via `CREATE OR REPLACE FUNCTION`
--     (undocumented hot-patch); 99% volatility/beta coverage on 2026-05-18.
--   - 2026-05-21 — committed to repo as migration 060 so a fresh DB rebuild
--     keeps the fix (otherwise rerunning 053 would re-introduce the bug).
--
-- Idempotent: CREATE OR REPLACE FUNCTION is a no-op if the body already
-- matches. Safe to run after 053 has already been applied.

SET search_path TO nidp, public;

CREATE OR REPLACE FUNCTION nidp.populate_stock_price_features(
    p_target_date DATE,
    p_window_days INTEGER DEFAULT 365,
    p_min_bars    INTEGER DEFAULT 60
)
RETURNS INTEGER AS $$
DECLARE
    v_rows INTEGER;
    v_since DATE;
BEGIN
    v_since := p_target_date - p_window_days;

    WITH
    nifty AS (
        SELECT as_of_date,
               LN(close_price / NULLIF(LAG(close_price) OVER (ORDER BY as_of_date), 0)) AS log_ret
          FROM nidp.index_eod
         WHERE index_name = 'Nifty 50'
           AND as_of_date BETWEEN v_since AND p_target_date
           AND close_price > 0
    ),
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
    agg AS (
        SELECT
            symbol,
            -- FIX (migration 060): COUNT(*) OVER w_full, not bare COUNT(*).
            -- The bare aggregate triggered implicit GROUP BY and the
            -- function aborted with "column with_peak.symbol must appear
            -- in the GROUP BY clause". All columns here MUST be window
            -- expressions or the partition-key column itself.
            COUNT(*) OVER w_full                                                   AS bar_count,
            ROUND(((LAST_VALUE(adj_close) OVER w_full
                  / NULLIF(FIRST_VALUE(adj_close) OVER w_full, 0) - 1) * 100)::NUMERIC, 4)
                                                                                   AS return_252d_pct,
            ROUND((STDDEV_SAMP(fund_log_ret) OVER w_full * SQRT(252) * 100)::NUMERIC, 4)
                                                                                   AS volatility_1y_pct,
            ROUND(REGR_SLOPE(fund_log_ret, nifty_log_ret) OVER w_full::NUMERIC, 4) AS beta_1y,
            ROUND(MIN((adj_close - running_peak) / NULLIF(running_peak, 0) * 100) OVER w_full::NUMERIC, 4)
                                                                                   AS max_drawdown_1y_pct
          FROM with_peak
          WINDOW w_full AS (PARTITION BY symbol)
    ),
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


INSERT INTO nidp.schema_migrations (filename)
VALUES ('060_fix_populate_stock_price_features.sql')
ON CONFLICT (filename) DO NOTHING;
