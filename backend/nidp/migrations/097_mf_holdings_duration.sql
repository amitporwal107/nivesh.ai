-- 093_mf_holdings_duration.sql
--
-- Gap 6: Real modified duration computed from holdings.
--
-- Adds per-holding maturity_date and ytm_pct to mf_holdings_monthly so the
-- disclosure-snapshot ingester can record them as they appear in AMFI monthly
-- portfolio PDFs. Once populated, compute_mf_derived_analytics() computes
-- portfolio modified duration and weighted YTM from the actual holdings,
-- replacing the category-string proxy (duration_risk_score from sub_category).
--
-- Formula (simplified Macaulay approximation for bullet instruments):
--   tenor_years_i     = (maturity_date_i - today) / 365.25
--   mod_duration_i    = tenor_years_i / (1 + ytm_pct_i / 100)
--   portfolio_md      = Σ(weight_pct_i × mod_duration_i) / Σ(debt_weight_pct)
--
-- Changes:
--   A. ADD COLUMNS maturity_date, ytm_pct to nidp.mf_holdings_monthly
--   B. ADD COLUMNS modified_duration_years, portfolio_ytm_pct to nidp.mf_derived_analytics
--   C. Replace compute_mf_derived_analytics() with full body including duration
--   D. Rebuild nidp.v_v3_mf_primitives to expose the two new derived columns

SET search_path TO nidp, analytics, public;


-- ── A. Extend mf_holdings_monthly ────────────────────────────────────────────

ALTER TABLE nidp.mf_holdings_monthly
    ADD COLUMN IF NOT EXISTS maturity_date  DATE,
    ADD COLUMN IF NOT EXISTS ytm_pct        NUMERIC(8,4);

COMMENT ON COLUMN nidp.mf_holdings_monthly.maturity_date IS
'Instrument maturity date parsed from AMFI monthly portfolio PDF. '
'NULL for equity holdings and when not parsed. Required for real modified duration.';

COMMENT ON COLUMN nidp.mf_holdings_monthly.ytm_pct IS
'Yield to maturity (%) parsed from AMFI monthly portfolio PDF. '
'NULL for equity holdings and when not parsed.';


-- ── B. Extend mf_derived_analytics ───────────────────────────────────────────

ALTER TABLE nidp.mf_derived_analytics
    ADD COLUMN IF NOT EXISTS modified_duration_years  NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS portfolio_ytm_pct        NUMERIC(8,4);

COMMENT ON COLUMN nidp.mf_derived_analytics.modified_duration_years IS
'Portfolio-weighted modified duration (years) computed from mf_holdings_monthly. '
'NULL when maturity_date is not yet parsed. Replaces duration_risk_score as the '
'primary rate-sensitivity metric for debt funds once data is available.';

COMMENT ON COLUMN nidp.mf_derived_analytics.portfolio_ytm_pct IS
'Holdings-weighted average yield to maturity (%). NULL when ytm_pct not parsed.';


-- ── C. Replace compute_mf_derived_analytics() ────────────────────────────────

CREATE OR REPLACE FUNCTION nidp.compute_mf_derived_analytics(
    p_scheme_code   TEXT,
    p_as_of_date    DATE,
    p_window_days   INTEGER DEFAULT 1095
) RETURNS VOID AS $$
DECLARE
    v_cat            TEXT;
    v_sub_cat        TEXT;
    v_cat_avg_1y     NUMERIC;
    v_benchmark_idx  TEXT;

    v_nav_obs        INTEGER := 0;
    v_wins           INTEGER := 0;
    v_total          INTEGER := 0;
    v_consistency    NUMERIC;

    v_dc_fund_sum    NUMERIC := 0;
    v_dc_bench_sum   NUMERIC := 0;
    v_dc_count       INTEGER := 0;
    v_dc             NUMERIC;

    v_aum_obs        INTEGER := 0;
    v_aum_trend      NUMERIC;
    v_mx             NUMERIC;
    v_my             NUMERIC;
    v_num            NUMERIC := 0;
    v_den            NUMERIC := 0;
    v_slope          NUMERIC;
    v_ann_growth     NUMERIC;

    v_hold_months    INTEGER := 0;
    v_turnover       NUMERIC;
    v_credit_score   NUMERIC;
    v_duration_score NUMERIC;
    v_active_share   NUMERIC;
    v_mod_duration   NUMERIC;
    v_portfolio_ytm  NUMERIC;
BEGIN

    -- ── Metadata ─────────────────────────────────────────────────────────────
    SELECT
        COALESCE(fcr.category,    sm.scheme_category),
        COALESCE(fcr.sub_category, ''),
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

    -- ── Consistency score ─────────────────────────────────────────────────────
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
                   LAG(eom_nav, 12) OVER (ORDER BY month) AS nav_12m_ago
            FROM distinct_months
        )
        SELECT
            COUNT(*),
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

    -- ── Downside capture ─────────────────────────────────────────────────────
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

    -- ── AUM trend (OLS on ln(AUM)) ────────────────────────────────────────────
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
        SELECT COUNT(*) AS n, AVG(x) AS mx, AVG(y) AS my FROM aum_pts
    )
    SELECT m.n, m.mx, m.my,
           SUM((p.x - m.mx) * (p.y - m.my)),
           SUM((p.x - m.mx) ^ 2)
    INTO v_aum_obs, v_mx, v_my, v_num, v_den
    FROM aum_pts p CROSS JOIN aum_means m
    GROUP BY m.n, m.mx, m.my;

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

    -- ── Portfolio turnover ────────────────────────────────────────────────────
    WITH latest_months AS (
        SELECT DISTINCT as_of_month FROM nidp.mf_holdings_monthly
        WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
        ORDER BY as_of_month DESC LIMIT 13
    ),
    month_pairs AS (
        SELECT m1.as_of_month AS cur_month, m2.as_of_month AS prv_month
        FROM latest_months m1
        JOIN latest_months m2 ON m2.as_of_month < m1.as_of_month
        WHERE m2.as_of_month = (
            SELECT MAX(lm.as_of_month) FROM latest_months lm WHERE lm.as_of_month < m1.as_of_month
        )
        LIMIT 6
    ),
    turnover_per_pair AS (
        SELECT mp.cur_month,
               COALESCE(SUM(cur.weight_pct) FILTER (
                   WHERE prv.security_isin IS NULL AND cur.security_isin IS NOT NULL
               ), 0) AS churn_pct
        FROM month_pairs mp
        JOIN nidp.mf_holdings_monthly cur ON cur.scheme_code = p_scheme_code AND cur.as_of_month = mp.cur_month
        LEFT JOIN nidp.mf_holdings_monthly prv
            ON prv.scheme_code = p_scheme_code AND prv.as_of_month = mp.prv_month
           AND prv.security_isin = cur.security_isin
        GROUP BY mp.cur_month
    )
    SELECT COUNT(*), AVG(churn_pct) * 12
    INTO v_hold_months, v_turnover
    FROM turnover_per_pair;

    -- ── Credit quality (debt funds) ───────────────────────────────────────────
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
    FROM rated WHERE score IS NOT NULL AND weight_pct > 0;

    -- ── Duration risk (proxy fallback from sub_category) ─────────────────────
    v_duration_score := nidp.mf_duration_risk_from_category(v_cat, v_sub_cat);

    -- ── Active share (Gap 5) ──────────────────────────────────────────────────
    IF v_benchmark_idx IS NOT NULL THEN
        WITH latest_fund AS (
            SELECT security_isin, weight_pct
            FROM nidp.mf_holdings_monthly
            WHERE scheme_code = p_scheme_code
              AND as_of_month = (
                  SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly
                  WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
              )
              AND security_isin IS NOT NULL AND weight_pct IS NOT NULL AND weight_pct > 0
        ),
        latest_bench AS (
            SELECT DISTINCT ON (isin) isin, weight_pct
            FROM nidp.index_constituents
            WHERE index_name = v_benchmark_idx
              AND isin IS NOT NULL AND weight_pct IS NOT NULL AND weight_pct > 0
            ORDER BY isin, as_of_date DESC
        ),
        combined AS (
            SELECT
                COALESCE(f.security_isin, b.isin)  AS sec_isin,
                COALESCE(f.weight_pct, 0::NUMERIC) AS fund_wt,
                COALESCE(b.weight_pct, 0::NUMERIC) AS bench_wt
            FROM latest_fund f FULL OUTER JOIN latest_bench b ON b.isin = f.security_isin
        )
        SELECT ROUND(SUM(ABS(fund_wt - bench_wt)) / 2.0, 2)
        INTO v_active_share
        FROM combined HAVING COUNT(*) > 0;
    END IF;

    -- ── Modified duration from holdings (Gap 6) ───────────────────────────────
    -- Uses maturity_date + ytm_pct from mf_holdings_monthly (populated by
    -- the mf_holdings ingester when parsing AMFI monthly portfolio disclosures).
    -- Falls back gracefully when data not available (v_mod_duration stays NULL).
    WITH debt_hold AS (
        SELECT
            weight_pct,
            maturity_date,
            ytm_pct,
            -- Macaulay duration approx: tenor / (1 + ytm/2) for semi-annual coupon
            CASE
                WHEN maturity_date IS NOT NULL AND maturity_date > p_as_of_date
                THEN (maturity_date - p_as_of_date)::NUMERIC / 365.25
                     / (1.0 + COALESCE(ytm_pct, 7.0) / 100.0 / 2.0)
                ELSE NULL
            END AS mod_dur_i
        FROM nidp.mf_holdings_monthly
        WHERE scheme_code   = p_scheme_code
          AND as_of_month   = (
              SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly
              WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
          )
          AND instrument_type IN ('DEBT','MONEY_MARKET','TBILL','TREPS','GOVT_SEC')
          AND weight_pct IS NOT NULL AND weight_pct > 0
    )
    SELECT
        ROUND(SUM(weight_pct * mod_dur_i) / NULLIF(SUM(weight_pct) FILTER (WHERE mod_dur_i IS NOT NULL), 0), 4),
        ROUND(SUM(weight_pct * ytm_pct)   / NULLIF(SUM(weight_pct) FILTER (WHERE ytm_pct  IS NOT NULL), 0), 4)
    INTO v_mod_duration, v_portfolio_ytm
    FROM debt_hold
    WHERE mod_dur_i IS NOT NULL OR ytm_pct IS NOT NULL;

    -- ── Upsert result ─────────────────────────────────────────────────────────
    INSERT INTO nidp.mf_derived_analytics (
        scheme_code, as_of_date,
        consistency_score, downside_capture_pct, aum_trend_score,
        portfolio_turnover_pct, credit_quality_score, duration_risk_score,
        active_share_pct, modified_duration_years, portfolio_ytm_pct,
        nav_obs_count, aum_obs_count, holdings_months_count, benchmark_index
    ) VALUES (
        p_scheme_code, p_as_of_date,
        v_consistency, v_dc, v_aum_trend,
        ROUND(v_turnover, 2), v_credit_score, v_duration_score,
        v_active_share, v_mod_duration, v_portfolio_ytm,
        v_nav_obs, v_aum_obs, v_hold_months, v_benchmark_idx
    )
    ON CONFLICT (scheme_code, as_of_date) DO UPDATE SET
        consistency_score       = EXCLUDED.consistency_score,
        downside_capture_pct    = EXCLUDED.downside_capture_pct,
        aum_trend_score         = EXCLUDED.aum_trend_score,
        portfolio_turnover_pct  = EXCLUDED.portfolio_turnover_pct,
        credit_quality_score    = EXCLUDED.credit_quality_score,
        duration_risk_score     = EXCLUDED.duration_risk_score,
        active_share_pct        = EXCLUDED.active_share_pct,
        modified_duration_years = EXCLUDED.modified_duration_years,
        portfolio_ytm_pct       = EXCLUDED.portfolio_ytm_pct,
        nav_obs_count           = EXCLUDED.nav_obs_count,
        aum_obs_count           = EXCLUDED.aum_obs_count,
        holdings_months_count   = EXCLUDED.holdings_months_count,
        benchmark_index         = EXCLUDED.benchmark_index,
        built_at                = NOW();

END;
$$ LANGUAGE plpgsql;


-- ── D. Rebuild nidp.v_v3_mf_primitives to expose new duration columns ─────────

DROP VIEW IF EXISTS nidp.v_v3_mf_primitives;

CREATE VIEW nidp.v_v3_mf_primitives AS
WITH

latest_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, category, sub_category, scheme_launch_date,
        return_1y, return_3y, return_5y,
        return_1m, return_3m, return_6m, return_2y,
        return_since_launch_cagr,
        sharpe_1y, sortino_1y, max_drawdown_1y,
        alpha_1y, beta_1y, volatility_1y,
        r_squared_1y, tracking_error_1y, information_ratio_1y,
        return_1y_rank, composite_rank
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),

fallback_1y AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        return_1y AS fb_return_1y, return_3y AS fb_return_3y,
        return_5y AS fb_return_5y, return_2y AS fb_return_2y,
        sharpe_1y AS fb_sharpe_1y, sortino_1y AS fb_sortino_1y,
        max_drawdown_1y      AS fb_max_drawdown_1y,
        alpha_1y             AS fb_alpha_1y,
        beta_1y              AS fb_beta_1y,
        volatility_1y        AS fb_volatility_1y,
        r_squared_1y         AS fb_r_squared_1y,
        tracking_error_1y    AS fb_tracking_error_1y,
        information_ratio_1y AS fb_information_ratio_1y,
        return_1y_rank       AS fb_return_1y_rank
    FROM analytics.fund_category_rank
    WHERE return_1y IS NOT NULL
    ORDER BY scheme_code, rank_date DESC
),

cat_avg AS (
    SELECT lr.category,
        AVG(COALESCE(lr.return_1y, fb.fb_return_1y)) AS cat_avg_1y,
        AVG(COALESCE(lr.return_3y, fb.fb_return_3y)) AS cat_avg_3y,
        AVG(COALESCE(lr.return_5y, fb.fb_return_5y)) AS cat_avg_5y
    FROM latest_rank lr LEFT JOIN fallback_1y fb USING (scheme_code)
    GROUP BY lr.category
),

latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, ter_pct_direct AS ter_direct, ter_pct AS ter_regular,
        aum_inr_crore AS aum_cr, primary_manager, risk_o_meter
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),

snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, ter_pct_direct AS ter_direct_3y, ter_pct AS ter_regular_3y
    FROM nidp.mf_scheme_disclosure_snapshot
    WHERE snapshot_date <= NOW() - INTERVAL '3 years'
    ORDER BY scheme_code, snapshot_date DESC
),

manager_tenure AS (
    SELECT scheme_code, MAX(event_date) AS manager_since_date
    FROM nidp.mf_scheme_events WHERE event_type = 'manager_change'
    GROUP BY scheme_code
),

top10_conc AS (
    SELECT scheme_code, SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT scheme_code, weight_pct,
               ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY weight_pct DESC) AS rn
        FROM (
            SELECT DISTINCT ON (scheme_code, security_isin) scheme_code, weight_pct
            FROM nidp.mf_holdings_monthly
            WHERE weight_pct IS NOT NULL AND weight_pct > 0
            ORDER BY scheme_code, security_isin, as_of_month DESC
        ) deduped
    ) ranked WHERE rn <= 10
    GROUP BY scheme_code
),

derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        consistency_score, downside_capture_pct, aum_trend_score,
        portfolio_turnover_pct, credit_quality_score, duration_risk_score,
        active_share_pct, modified_duration_years, portfolio_ytm_pct
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),

nidp_avail AS (
    SELECT scheme_code, TRUE AS nidp_returns_available, TRUE AS nidp_snapshot_available
    FROM (SELECT DISTINCT scheme_code FROM nidp.mf_nav_daily WHERE nav_date >= NOW() - INTERVAL '35 days') r
),

isin_map AS (
    SELECT scheme_code, isin_growth AS isin, FALSE AS is_idcw
      FROM nidp.mf_scheme_master WHERE isin_growth IS NOT NULL
    UNION ALL
    SELECT scheme_code, isin_idcw AS isin, TRUE AS is_idcw
      FROM nidp.mf_scheme_master WHERE isin_idcw IS NOT NULL
),

latest_cat_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        category_rank AS corrected_category_rank,
        category_pct  AS corrected_category_pct,
        category_size AS corrected_category_size
    FROM nidp.mf_category_rank_daily
    WHERE status IN ('ranked', 'low_confidence')
    ORDER BY scheme_code, rank_date DESC
)

SELECT
    im.isin, lr.scheme_code, sm.scheme_name,
    lr.category, lr.sub_category, sn.aum_cr,
    EXTRACT(YEAR FROM AGE(NOW(), COALESCE(lr.scheme_launch_date, sm.launch_date)))::numeric AS fund_age_years,
    COALESCE(sn.ter_direct, sn.ter_regular)         AS expense_ratio,
    sn.ter_direct                                    AS expense_ratio_direct,
    sn.ter_regular                                   AS expense_ratio_regular,
    CASE WHEN sn.ter_regular IS NOT NULL AND s3.ter_regular_3y IS NOT NULL
         THEN sn.ter_regular - s3.ter_regular_3y END AS expense_trend_delta,
    EXTRACT(YEAR FROM AGE(NOW(), COALESCE(mt.manager_since_date, lr.scheme_launch_date, sm.launch_date)))::numeric AS manager_tenure_years,
    tc.top10_concentration_pct,
    ca.cat_avg_1y AS category_avg_1y,
    ca.cat_avg_3y AS category_avg_3y,
    ca.cat_avg_5y AS category_avg_5y,
    COALESCE(lr.max_drawdown_1y, fb.fb_max_drawdown_1y)           AS max_drawdown_pct,
    COALESCE(lr.return_1y,  fb.fb_return_1y)                      AS ret_1y,
    COALESCE(lr.return_3y,  fb.fb_return_3y)                      AS ret_3y,
    COALESCE(lr.return_5y,  fb.fb_return_5y)                      AS ret_5y,
    COALESCE(lr.sharpe_1y,  fb.fb_sharpe_1y)                      AS sharpe,
    COALESCE(lr.sortino_1y, fb.fb_sortino_1y)                     AS sortino,
    lr.return_1m, lr.return_3m, lr.return_6m,
    COALESCE(lr.return_2y, fb.fb_return_2y)                       AS return_2y,
    lr.return_since_launch_cagr,
    COALESCE(lr.alpha_1y,  fb.fb_alpha_1y)                        AS alpha_1y,
    COALESCE(lr.beta_1y,   fb.fb_beta_1y)                         AS beta_1y,
    COALESCE(lr.volatility_1y, fb.fb_volatility_1y)               AS volatility_1y,
    COALESCE(lr.r_squared_1y, fb.fb_r_squared_1y)                 AS r_squared_1y,
    (COALESCE(lr.r_squared_1y, fb.fb_r_squared_1y) >= 0.75)       AS benchmark_regression_reliable,
    COALESCE(lr.tracking_error_1y,    fb.fb_tracking_error_1y)    AS tracking_error_1y,
    COALESCE(lr.information_ratio_1y, fb.fb_information_ratio_1y) AS information_ratio_1y,
    im.is_idcw                                                     AS total_return_incomplete,
    cr.corrected_category_rank                                     AS category_rank,
    cr.corrected_category_pct                                      AS category_rank_pct,
    cr.corrected_category_size                                     AS category_size,
    COALESCE(lr.return_1y_rank, fb.fb_return_1y_rank)              AS return_1y_rank,
    lr.composite_rank,
    d.consistency_score, d.downside_capture_pct, d.aum_trend_score,
    d.portfolio_turnover_pct, d.credit_quality_score, d.duration_risk_score,
    d.active_share_pct,
    -- Gap 6: real modified duration from holdings (NULL until maturity_date populated)
    d.modified_duration_years,
    d.portfolio_ytm_pct,
    (na.nidp_returns_available IS TRUE)              AS nidp_returns_available,
    (na.nidp_snapshot_available IS TRUE)             AS nidp_snapshot_available,
    (tc.top10_concentration_pct IS NOT NULL)         AS nidp_holdings_available,
    sn.primary_manager, sn.risk_o_meter
FROM latest_rank lr
JOIN isin_map im ON im.scheme_code = lr.scheme_code
JOIN (SELECT DISTINCT ON (scheme_code) scheme_code, scheme_name, launch_date
      FROM nidp.mf_scheme_master ORDER BY scheme_code) sm ON sm.scheme_code = lr.scheme_code
LEFT JOIN fallback_1y      fb ON fb.scheme_code = lr.scheme_code
LEFT JOIN cat_avg          ca ON ca.category    = lr.category
LEFT JOIN latest_snap      sn ON sn.scheme_code = lr.scheme_code
LEFT JOIN snap_3y_ago      s3 ON s3.scheme_code = lr.scheme_code
LEFT JOIN manager_tenure   mt ON mt.scheme_code = lr.scheme_code
LEFT JOIN top10_conc       tc ON tc.scheme_code = lr.scheme_code
LEFT JOIN derived          d  ON d.scheme_code  = lr.scheme_code
LEFT JOIN nidp_avail       na ON na.scheme_code = lr.scheme_code
LEFT JOIN latest_cat_rank  cr ON cr.scheme_code = lr.scheme_code;

COMMENT ON VIEW nidp.v_v3_mf_primitives IS
'MF primitives for V3 scoring. Final gap-fill view (migration 093). '
'New columns: modified_duration_years (real, from holdings when maturity_date parsed), '
'portfolio_ytm_pct, active_share_pct (when index_constituents weights populated), '
'r_squared_1y, tracking_error_1y, information_ratio_1y, benchmark_regression_reliable, '
'total_return_incomplete. Restored: credit_quality_score, duration_risk_score.';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('097_mf_holdings_duration.sql')
ON CONFLICT (filename) DO NOTHING;
