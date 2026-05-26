-- 067_fix_mf_derived_ols.sql
--
-- Fix GroupingError in compute_mf_derived_analytics():
-- AVG(x) OVER () is a window function; wrapping it in SUM() (aggregate)
-- is illegal in PostgreSQL. Pre-compute means in an intermediate CTE instead.

SET search_path TO nidp, public;

CREATE OR REPLACE FUNCTION nidp.compute_mf_derived_analytics(
    p_scheme_code   TEXT,
    p_as_of_date    DATE,
    p_window_days   INTEGER DEFAULT 1095   -- 3 years
) RETURNS VOID AS $$
DECLARE
    v_cat           TEXT;
    v_sub_cat       TEXT;
    v_cat_avg_1y    NUMERIC;
    v_benchmark_idx TEXT;
    v_nav_obs       INTEGER := 0;
    v_wins          INTEGER := 0;
    v_total         INTEGER := 0;
    v_consistency   NUMERIC;
    v_dc_fund_sum   NUMERIC := 0;
    v_dc_bench_sum  NUMERIC := 0;
    v_dc_count      INTEGER := 0;
    v_dc            NUMERIC;
    v_aum_obs       INTEGER := 0;
    v_aum_trend     NUMERIC;
    v_n             INTEGER;
    v_mx            NUMERIC;
    v_my            NUMERIC;
    v_num           NUMERIC := 0;
    v_den           NUMERIC := 0;
    v_slope         NUMERIC;
    v_ann_growth    NUMERIC;
    v_hold_months   INTEGER := 0;
    v_turnover      NUMERIC;
    v_credit_score  NUMERIC;
    v_duration_score NUMERIC;
BEGIN

    SELECT
        COALESCE(fcr.category,    sm.scheme_category),
        COALESCE(fcr.sub_category,''),
        fcr.cat_avg_1y_latest,
        bmm.index_code
    INTO v_cat, v_sub_cat, v_cat_avg_1y, v_benchmark_idx
    FROM nidp.mf_scheme_master sm
    LEFT JOIN (
        SELECT DISTINCT ON (scheme_code)
            scheme_code, category, sub_category,
            AVG(return_1y) OVER (PARTITION BY category) AS cat_avg_1y_latest
        FROM analytics.fund_category_rank
        ORDER BY scheme_code, rank_date DESC
    ) fcr ON fcr.scheme_code = sm.scheme_code
    LEFT JOIN nidp.mf_benchmark_master bmm ON bmm.benchmark_id = sm.benchmark_id
    WHERE sm.scheme_code = p_scheme_code;

    IF v_cat_avg_1y IS NOT NULL THEN
        WITH monthly_nav AS (
            SELECT
                date_trunc('month', nav_date)::date AS month,
                LAST_VALUE(nav) OVER (
                    PARTITION BY date_trunc('month', nav_date)
                    ORDER BY nav_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS eom_nav
            FROM nidp.mf_nav_daily
            WHERE scheme_code = p_scheme_code
              AND nav_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date
        ),
        distinct_months AS (
            SELECT DISTINCT month, eom_nav FROM monthly_nav ORDER BY month
        ),
        windowed AS (
            SELECT month, eom_nav,
                   LAG(eom_nav, 12) OVER (ORDER BY month) AS nav_12m_ago,
                   LAG(month,  12) OVER (ORDER BY month)  AS month_12m_ago
            FROM distinct_months
        )
        SELECT COUNT(*),
               COUNT(*) FILTER (
                   WHERE nav_12m_ago > 0
                     AND ((eom_nav / nav_12m_ago - 1) * 100.0) >= v_cat_avg_1y
               )
        INTO v_total, v_wins
        FROM windowed
        WHERE nav_12m_ago IS NOT NULL AND nav_12m_ago > 0;

        SELECT COUNT(*) INTO v_nav_obs
        FROM nidp.mf_nav_daily
        WHERE scheme_code = p_scheme_code
          AND nav_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date;

        IF v_total >= 6 THEN
            v_consistency := ROUND((v_wins::NUMERIC / v_total) * 10.0, 2);
        END IF;
    END IF;

    IF v_benchmark_idx IS NOT NULL THEN
        WITH fund_monthly AS (
            SELECT
                date_trunc('month', nav_date)::date AS month,
                LAST_VALUE(nav) OVER (
                    PARTITION BY date_trunc('month', nav_date)
                    ORDER BY nav_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS eom_nav
            FROM nidp.mf_nav_daily
            WHERE scheme_code = p_scheme_code
              AND nav_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date
        ),
        bench_monthly AS (
            SELECT
                date_trunc('month', as_of_date)::date AS month,
                LAST_VALUE(close_value) OVER (
                    PARTITION BY date_trunc('month', as_of_date)
                    ORDER BY as_of_date
                    ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                ) AS eom_close
            FROM nidp.index_eod
            WHERE index_name = v_benchmark_idx
              AND as_of_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date
        ),
        fund_ret AS (
            SELECT month,
                   (eom_nav / LAG(eom_nav) OVER (ORDER BY month) - 1) * 100.0 AS ret
            FROM (SELECT DISTINCT month, eom_nav FROM fund_monthly) fm
        ),
        bench_ret AS (
            SELECT month,
                   (eom_close / LAG(eom_close) OVER (ORDER BY month) - 1) * 100.0 AS ret
            FROM (SELECT DISTINCT month, eom_close FROM bench_monthly) bm
        ),
        down_months AS (
            SELECT fr.ret AS fund_ret, br.ret AS bench_ret
            FROM fund_ret fr JOIN bench_ret br USING (month)
            WHERE br.ret < 0 AND fr.ret IS NOT NULL AND br.ret IS NOT NULL
        )
        SELECT COUNT(*), COALESCE(SUM(fund_ret), 0), COALESCE(SUM(bench_ret), 0)
        INTO v_dc_count, v_dc_fund_sum, v_dc_bench_sum
        FROM down_months;

        IF v_dc_count >= 6 AND v_dc_bench_sum < 0 THEN
            v_dc := ROUND((v_dc_fund_sum / v_dc_bench_sum) * 100.0, 2);
        END IF;
    END IF;

    -- AUM trend OLS fix: pre-compute means in aum_means CTE so SUM()
    -- references plain columns, not nested window function calls.
    -- Old code: SUM((x - AVG(x) OVER()) * ...) => GroupingError in PostgreSQL.
    WITH aum_pts AS (
        SELECT
            ROW_NUMBER() OVER (ORDER BY snapshot_date) - 1 AS x,
            LN(NULLIF(aum_inr_crore, 0))                   AS y
        FROM nidp.mf_scheme_disclosure_snapshot
        WHERE scheme_code   = p_scheme_code
          AND aum_inr_crore > 0
          AND snapshot_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date
        ORDER BY snapshot_date
    ),
    aum_means AS (
        SELECT x, y,
               AVG(x) OVER () AS mx,
               AVG(y) OVER () AS my
        FROM aum_pts
    )
    SELECT COUNT(*), AVG(x), AVG(y),
           SUM((x - mx) * (y - my)),
           SUM((x - mx) ^ 2)
    INTO v_aum_obs, v_mx, v_my, v_num, v_den
    FROM aum_means;

    IF v_aum_obs >= 3 AND v_den > 0 THEN
        v_slope      := v_num / v_den;
        v_ann_growth := (EXP(v_slope * 52) - 1) * 100.0;
        v_aum_trend  := CASE
            WHEN v_ann_growth >= 30  THEN 10.0
            WHEN v_ann_growth >= 10  THEN 7.0 + (v_ann_growth - 10) / 20.0 * 3.0
            WHEN v_ann_growth >= -5  THEN 5.0 + (v_ann_growth + 5)  / 15.0 * 2.0
            WHEN v_ann_growth >= -15 THEN 3.0 + (v_ann_growth + 15) / 10.0 * 2.0
            ELSE GREATEST(0.0, 3.0 + (v_ann_growth + 15) / 30.0 * 3.0)
        END;
        v_aum_trend := ROUND(LEAST(10.0, GREATEST(0.0, v_aum_trend)), 2);
    END IF;

    WITH latest_months AS (
        SELECT DISTINCT as_of_month
        FROM nidp.mf_holdings_monthly
        WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
        ORDER BY as_of_month DESC LIMIT 13
    ),
    month_pairs AS (
        SELECT m1.as_of_month AS cur_month, m2.as_of_month AS prv_month
        FROM latest_months m1
        JOIN latest_months m2 ON m2.as_of_month < m1.as_of_month
        WHERE m2.as_of_month = (
            SELECT MAX(as_of_month) FROM latest_months lm
            WHERE lm.as_of_month < m1.as_of_month
        )
        LIMIT 6
    ),
    turnover_per_pair AS (
        SELECT mp.cur_month,
               COALESCE(SUM(cur.weight_pct) FILTER (
                   WHERE prv.security_isin IS NULL AND cur.security_isin IS NOT NULL
               ), 0) AS churn_pct
        FROM month_pairs mp
        JOIN nidp.mf_holdings_monthly cur
          ON cur.scheme_code = p_scheme_code AND cur.as_of_month = mp.cur_month
        LEFT JOIN nidp.mf_holdings_monthly prv
          ON prv.scheme_code = p_scheme_code AND prv.as_of_month = mp.prv_month
         AND prv.security_isin = cur.security_isin
        GROUP BY mp.cur_month
    )
    SELECT COUNT(*), AVG(churn_pct) * 12
    INTO v_hold_months, v_turnover
    FROM turnover_per_pair;

    WITH latest_hold AS (
        SELECT DISTINCT ON (security_isin, security_name)
            security_isin, security_name, weight_pct, rating, instrument_type
        FROM nidp.mf_holdings_monthly
        WHERE scheme_code = p_scheme_code
          AND as_of_month = (
              SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly
              WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
          )
        ORDER BY security_isin, security_name, as_of_month DESC
    ),
    rated AS (
        SELECT weight_pct, nidp.mf_rating_to_score(rating) AS score
        FROM latest_hold
        WHERE instrument_type IN ('DEBT','MONEY_MARKET','TBILL','TREPS','CASH','OTHER')
           OR (instrument_type IS NULL AND rating IS NOT NULL)
    )
    SELECT ROUND(SUM(weight_pct * score) / NULLIF(SUM(weight_pct), 0), 2)
    INTO v_credit_score
    FROM rated
    WHERE score IS NOT NULL AND weight_pct > 0;

    v_duration_score := nidp.mf_duration_risk_from_category(v_cat, v_sub_cat);

    INSERT INTO nidp.mf_derived_analytics (
        scheme_code, as_of_date,
        consistency_score, downside_capture_pct, aum_trend_score,
        portfolio_turnover_pct, credit_quality_score, duration_risk_score,
        nav_obs_count, aum_obs_count, holdings_months_count, benchmark_index
    ) VALUES (
        p_scheme_code, p_as_of_date,
        v_consistency, v_dc, v_aum_trend,
        ROUND(v_turnover, 2), v_credit_score, v_duration_score,
        v_nav_obs, v_aum_obs, v_hold_months, v_benchmark_idx
    )
    ON CONFLICT (scheme_code, as_of_date) DO UPDATE SET
        consistency_score      = EXCLUDED.consistency_score,
        downside_capture_pct   = EXCLUDED.downside_capture_pct,
        aum_trend_score        = EXCLUDED.aum_trend_score,
        portfolio_turnover_pct = EXCLUDED.portfolio_turnover_pct,
        credit_quality_score   = EXCLUDED.credit_quality_score,
        duration_risk_score    = EXCLUDED.duration_risk_score,
        nav_obs_count          = EXCLUDED.nav_obs_count,
        aum_obs_count          = EXCLUDED.aum_obs_count,
        holdings_months_count  = EXCLUDED.holdings_months_count,
        benchmark_index        = EXCLUDED.benchmark_index,
        built_at               = NOW();

END;
$$ LANGUAGE plpgsql;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('067_fix_mf_derived_ols.sql')
ON CONFLICT (filename) DO NOTHING;
