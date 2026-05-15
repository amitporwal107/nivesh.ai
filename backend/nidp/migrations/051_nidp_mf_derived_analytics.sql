-- 051_nidp_mf_derived_analytics.sql
--
-- Stores computed NAV-derived analytics for each MF scheme so the V3
-- engine can read them without recomputing per request.
--
-- Fields computed here replace the mutual_fund_metadata fallback in
-- nidp.v_v3_mf_primitives for:
--   consistency_score      — fraction of 1y windows beating category avg (0-10)
--   downside_capture_pct   — fund loss vs benchmark loss in down months (%)
--   aum_trend_score        — OLS slope of ln(AUM) annualised → 0-10
--   portfolio_turnover_pct — derived from holdings month-over-month churn (%)
--   credit_quality_score   — weighted avg of holding ratings → 0-10 (debt funds)
--   duration_risk_score    — category-derived interest rate risk → 0-10

SET search_path TO nidp, public;

-- ── Derived analytics table ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.mf_derived_analytics (
    scheme_code             TEXT    NOT NULL,
    as_of_date              DATE    NOT NULL,

    -- Consistency: fraction of rolling 12m windows fund beats category avg.
    -- 10 = beat every window; 0 = never beat. NULL if < 18m NAV history.
    consistency_score       NUMERIC(5,2),

    -- Downside capture vs benchmark index (nidp.index_eod).
    -- 80% = fund falls 80% as much as benchmark in down months. Lower is better.
    -- NULL if benchmark not mapped or < 6 down months in window.
    downside_capture_pct    NUMERIC(7,2),

    -- AUM trend 0-10 via OLS on ln(AUM monthly) from mf_scheme_disclosure_snapshot.
    -- 10 = strong growth (>30%/yr), 5 = flat, 0 = sharp decline.
    aum_trend_score         NUMERIC(5,2),

    -- Portfolio turnover proxy: % of holdings (by weight) that changed month-over-month.
    -- Source: mf_holdings_monthly. NULL when < 2 months available.
    portfolio_turnover_pct  NUMERIC(7,2),

    -- Credit quality (debt funds): weighted average of SEBI rating bucket → 0-10.
    -- Rating map: AAA/A1+ = 10, AA+ = 9, AA = 8, AA- = 7, A+ = 6, A = 5,
    --             A- = 4, BBB = 3, BB and below = 1, unrated/cash = 5.
    -- NULL for equity funds (no rated holdings).
    credit_quality_score    NUMERIC(5,2),

    -- Duration risk proxy from sub_category (0-10; 10 = very low rate risk).
    -- Liquid/Overnight → 10, Short Duration → 7, Medium → 5, Long/Gilt → 2.
    -- Always populated (never NULL) when sub_category is known.
    duration_risk_score     NUMERIC(5,2),

    -- Computation window actually used (may differ from requested 3y)
    nav_obs_count           INTEGER,          -- # daily NAV observations used
    aum_obs_count           INTEGER,          -- # monthly AUM snapshots used
    holdings_months_count   INTEGER,          -- # monthly holding disclosures used
    benchmark_index         TEXT,             -- index_name used for downside capture

    built_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (scheme_code, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_mf_derived_date
    ON nidp.mf_derived_analytics (as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_mf_derived_scheme_date
    ON nidp.mf_derived_analytics (scheme_code, as_of_date DESC);


-- ── Credit rating → numeric bucket ──────────────────────────────────
-- Called by the holdings-based credit_quality computation.
CREATE OR REPLACE FUNCTION nidp.mf_rating_to_score(rating TEXT)
RETURNS NUMERIC AS $$
BEGIN
    IF rating IS NULL THEN RETURN 5.0; END IF;
    CASE upper(trim(rating))
        WHEN 'AAA',  'A1+',  'AAA(SO)', 'AAA (SO)' THEN RETURN 10.0;
        WHEN 'AA+',  'A1'                            THEN RETURN 9.0;
        WHEN 'AA',   'AA (SO)'                       THEN RETURN 8.0;
        WHEN 'AA-'                                   THEN RETURN 7.0;
        WHEN 'A+',   'A2+'                           THEN RETURN 6.0;
        WHEN 'A',    'A2'                            THEN RETURN 5.0;
        WHEN 'A-'                                    THEN RETURN 4.0;
        WHEN 'BBB+', 'BBB', 'BBB-', 'A3'            THEN RETURN 3.0;
        WHEN 'BB+',  'BB',  'BB-',  'B'             THEN RETURN 2.0;
        WHEN 'D',    'DEFAULT'                       THEN RETURN 0.0;
        ELSE
            -- Cash / SOV / G-sec / TREPS treated as near-AAA
            IF upper(trim(rating)) IN ('SOV','SOVEREIGN','TBILL','TREPS','CASH',
                                       'NET CURRENT ASSETS','NCA') THEN
                RETURN 9.5;
            END IF;
            RETURN 5.0;  -- unrecognised → neutral
    END CASE;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ── Duration risk score from sub_category ────────────────────────────
CREATE OR REPLACE FUNCTION nidp.mf_duration_risk_from_category(
    p_category    TEXT,
    p_sub_category TEXT
) RETURNS NUMERIC AS $$
DECLARE
    combined TEXT;
BEGIN
    combined := upper(COALESCE(p_category,'') || ' ' || COALESCE(p_sub_category,''));
    -- Shorter duration = lower rate risk = higher score
    IF combined ~ '(OVERNIGHT|LIQUID FUND)'            THEN RETURN 10.0; END IF;
    IF combined ~ 'ULTRA SHORT'                         THEN RETURN 9.0;  END IF;
    IF combined ~ 'LOW DURATION|MONEY MARKET'           THEN RETURN 8.0;  END IF;
    IF combined ~ 'SHORT DURATION|SHORT TERM'           THEN RETURN 7.0;  END IF;
    IF combined ~ 'FLOATER|FLOATING'                    THEN RETURN 7.0;  END IF;
    IF combined ~ 'CORPORATE BOND|BANKING.*PSU'         THEN RETURN 6.0;  END IF;
    IF combined ~ 'MEDIUM DURATION|MEDIUM TERM'         THEN RETURN 5.0;  END IF;
    IF combined ~ 'MEDIUM.*LONG|DYNAMIC'                THEN RETURN 4.0;  END IF;
    IF combined ~ 'LONG DURATION|LONG TERM|10 YEAR'     THEN RETURN 2.0;  END IF;
    IF combined ~ 'GILT'                                THEN RETURN 1.0;  END IF;
    -- Equity / hybrid funds: not sensitive to rate risk
    IF combined ~ '(EQUITY|ELSS|HYBRID|MULTI.ASSET|BALANCED|FLEXICAP|MIDCAP|SMALLCAP|LARGECAP)'
                                                        THEN RETURN NULL; END IF;
    -- Debt not classified above → moderate
    IF combined ~ 'DEBT|BOND|CREDIT|INCOME'             THEN RETURN 5.0;  END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql IMMUTABLE;


-- ── Main compute function ────────────────────────────────────────────
-- Idempotent upsert for one scheme on one date.
-- Called by the mf_analytics_engine service after each rank cycle.
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

    -- Consistency
    v_nav_obs       INTEGER := 0;
    v_wins          INTEGER := 0;
    v_total         INTEGER := 0;
    v_consistency   NUMERIC;

    -- Downside capture
    v_dc_fund_sum   NUMERIC := 0;
    v_dc_bench_sum  NUMERIC := 0;
    v_dc_count      INTEGER := 0;
    v_dc            NUMERIC;

    -- AUM trend (OLS)
    v_aum_obs       INTEGER := 0;
    v_aum_trend     NUMERIC;
    v_n             INTEGER;
    v_mx            NUMERIC;
    v_my            NUMERIC;
    v_num           NUMERIC := 0;
    v_den           NUMERIC := 0;
    v_slope         NUMERIC;
    v_ann_growth    NUMERIC;

    -- Holdings turnover & credit quality
    v_hold_months   INTEGER := 0;
    v_turnover      NUMERIC;
    v_credit_score  NUMERIC;
    v_duration_score NUMERIC;
BEGIN

    -- ── Metadata ────────────────────────────────────────────────────
    SELECT
        COALESCE(fcr.category,    sm.scheme_category),
        COALESCE(fcr.sub_category,''),
        fcr.cat_avg_1y_latest,
        bmm.index_code
    INTO v_cat, v_sub_cat, v_cat_avg_1y, v_benchmark_idx
    FROM nidp.mf_scheme_master sm
    LEFT JOIN (
        SELECT DISTINCT ON (scheme_code)
            scheme_code,
            category,
            sub_category,
            AVG(return_1y) OVER (PARTITION BY category) AS cat_avg_1y_latest
        FROM analytics.fund_category_rank
        ORDER BY scheme_code, rank_date DESC
    ) fcr ON fcr.scheme_code = sm.scheme_code
    LEFT JOIN nidp.mf_benchmark_master bmm
           ON bmm.benchmark_id = sm.benchmark_id
    WHERE sm.scheme_code = p_scheme_code;

    -- ── Consistency score ────────────────────────────────────────────
    -- Fraction of rolling 12-month windows where fund return >= category avg 1y
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
            SELECT
                month,
                eom_nav,
                LAG(eom_nav, 12) OVER (ORDER BY month) AS nav_12m_ago,
                LAG(month,  12) OVER (ORDER BY month) AS month_12m_ago
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

    -- ── Downside capture ────────────────────────────────────────────
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
            FROM fund_ret fr
            JOIN bench_ret br USING (month)
            WHERE br.ret < 0 AND fr.ret IS NOT NULL AND br.ret IS NOT NULL
        )
        SELECT
            COUNT(*),
            COALESCE(SUM(fund_ret), 0),
            COALESCE(SUM(bench_ret), 0)
        INTO v_dc_count, v_dc_fund_sum, v_dc_bench_sum
        FROM down_months;

        IF v_dc_count >= 6 AND v_dc_bench_sum < 0 THEN
            v_dc := ROUND((v_dc_fund_sum / v_dc_bench_sum) * 100.0, 2);
        END IF;
    END IF;

    -- ── AUM trend (OLS on ln(aum)) ───────────────────────────────────
    WITH aum_pts AS (
        SELECT
            ROW_NUMBER() OVER (ORDER BY snapshot_date) - 1 AS x,
            LN(NULLIF(aum_inr_crore, 0))                   AS y
        FROM nidp.mf_scheme_disclosure_snapshot
        WHERE scheme_code   = p_scheme_code
          AND aum_inr_crore > 0
          AND snapshot_date BETWEEN (p_as_of_date - p_window_days) AND p_as_of_date
        ORDER BY snapshot_date
    )
    SELECT
        COUNT(*),
        AVG(x),
        AVG(y),
        SUM((x - AVG(x) OVER ()) * (y - AVG(y) OVER ())),
        SUM((x - AVG(x) OVER ()) ^ 2)
    INTO v_aum_obs, v_mx, v_my, v_num, v_den
    FROM aum_pts;

    IF v_aum_obs >= 3 AND v_den > 0 THEN
        -- slope is per-snapshot; snapshots are ~weekly → multiply by 52 for annual
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

    -- ── Portfolio turnover (month-over-month churn) ──────────────────
    -- Turnover % = weight of holdings that exited or entered vs prior month.
    WITH latest_months AS (
        SELECT DISTINCT as_of_month
        FROM nidp.mf_holdings_monthly
        WHERE scheme_code = p_scheme_code
          AND as_of_month <= p_as_of_date
        ORDER BY as_of_month DESC
        LIMIT 13   -- need up to 12 month pairs for a meaningful avg
    ),
    month_pairs AS (
        SELECT
            m1.as_of_month AS cur_month,
            m2.as_of_month AS prv_month
        FROM latest_months m1
        JOIN latest_months m2 ON m2.as_of_month < m1.as_of_month
        WHERE m2.as_of_month = (
            SELECT MAX(as_of_month)
            FROM latest_months lm
            WHERE lm.as_of_month < m1.as_of_month
        )
        LIMIT 6   -- avg over up to 6 month-over-month pairs
    ),
    turnover_per_pair AS (
        SELECT
            mp.cur_month,
            -- weight of new securities (in cur but not prv) as proxy for buys
            COALESCE(SUM(cur.weight_pct) FILTER (
                WHERE prv.security_isin IS NULL AND cur.security_isin IS NOT NULL
            ), 0) AS churn_pct
        FROM month_pairs mp
        JOIN nidp.mf_holdings_monthly cur
          ON cur.scheme_code = p_scheme_code AND cur.as_of_month = mp.cur_month
        LEFT JOIN nidp.mf_holdings_monthly prv
          ON prv.scheme_code   = p_scheme_code
         AND prv.as_of_month   = mp.prv_month
         AND prv.security_isin = cur.security_isin
        GROUP BY mp.cur_month
    )
    SELECT COUNT(*), AVG(churn_pct) * 12   -- annualise monthly churn
    INTO v_hold_months, v_turnover
    FROM turnover_per_pair;

    -- ── Credit quality (debt funds only) ────────────────────────────
    -- Weighted average rating score over latest holdings month.
    WITH latest_hold AS (
        SELECT DISTINCT ON (security_isin, security_name)
            security_isin, security_name, weight_pct, rating, instrument_type
        FROM nidp.mf_holdings_monthly
        WHERE scheme_code = p_scheme_code
          AND as_of_month = (
              SELECT MAX(as_of_month)
              FROM nidp.mf_holdings_monthly
              WHERE scheme_code = p_scheme_code AND as_of_month <= p_as_of_date
          )
        ORDER BY security_isin, security_name, as_of_month DESC
    ),
    rated AS (
        SELECT
            weight_pct,
            nidp.mf_rating_to_score(rating) AS score
        FROM latest_hold
        WHERE instrument_type IN ('DEBT','MONEY_MARKET','TBILL','TREPS','CASH','OTHER')
           OR (instrument_type IS NULL AND rating IS NOT NULL)
    )
    SELECT ROUND(
        SUM(weight_pct * score) / NULLIF(SUM(weight_pct), 0), 2
    )
    INTO v_credit_score
    FROM rated
    WHERE score IS NOT NULL AND weight_pct > 0;

    -- ── Duration risk (from category) ───────────────────────────────
    v_duration_score := nidp.mf_duration_risk_from_category(v_cat, v_sub_cat);

    -- ── Upsert result ────────────────────────────────────────────────
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


-- ── Batch runner ─────────────────────────────────────────────────────
-- Called by mf_analytics_engine after each rank cycle.
-- Skips schemes where derived analytics were computed in the last 6 days
-- (weekly cadence aligns with disclosure snapshot refresh).
CREATE OR REPLACE FUNCTION nidp.refresh_mf_derived_analytics(
    p_as_of_date DATE DEFAULT CURRENT_DATE,
    p_force      BOOLEAN DEFAULT FALSE
) RETURNS INTEGER AS $$
DECLARE
    v_scheme  TEXT;
    v_count   INTEGER := 0;
BEGIN
    FOR v_scheme IN
        SELECT sm.scheme_code
        FROM nidp.mf_scheme_master sm
        WHERE sm.status = 'active'
          AND (p_force OR NOT EXISTS (
              SELECT 1 FROM nidp.mf_derived_analytics da
              WHERE da.scheme_code = sm.scheme_code
                AND da.as_of_date  > p_as_of_date - 7
          ))
        ORDER BY sm.scheme_code
    LOOP
        PERFORM nidp.compute_mf_derived_analytics(v_scheme, p_as_of_date);
        v_count := v_count + 1;
    END LOOP;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;


-- ── Upgrade nidp.v_v3_mf_primitives to use mf_derived_analytics ─────
-- Migration 050 created the view using Groww fallbacks for 6 fields.
-- Now that mf_derived_analytics exists we drop and re-create the view
-- (CREATE OR REPLACE can't change column types in PostgreSQL).

DROP VIEW IF EXISTS nidp.v_v3_mf_primitives;
CREATE VIEW nidp.v_v3_mf_primitives AS

WITH

latest_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, category, sub_category, amc_code, scheme_name,
        return_1y, return_3y, return_5y, return_1m, return_3m, return_6m,
        return_2y, return_since_launch_cagr,
        sharpe_1y, sortino_1y, alpha_1y, beta_1y, volatility_1y,
        max_drawdown_1y, ter, composite_rank, return_1y_rank, scheme_launch_date, data_since_date
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),

cat_avg AS (
    SELECT category,
           AVG(return_1y) AS cat_avg_1y,
           AVG(return_3y) AS cat_avg_3y,
           AVG(return_5y) AS cat_avg_5y
    FROM latest_rank
    GROUP BY category
),

latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, ter_pct AS ter_regular, ter_pct_direct AS ter_direct,
        aum_inr_crore AS aum_cr, risk_o_meter, primary_manager, snapshot_date
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),

snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, ter_pct AS ter_regular_3y, ter_pct_direct AS ter_direct_3y
    FROM nidp.mf_scheme_disclosure_snapshot
    WHERE snapshot_date <= (CURRENT_DATE - INTERVAL '3 years')
    ORDER BY scheme_code, snapshot_date DESC
),

manager_tenure AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, event_date AS manager_since_date
    FROM nidp.mf_scheme_events
    WHERE event_type = 'manager_change'
    ORDER BY scheme_code, event_date DESC
),

top10_conc AS (
    SELECT scheme_code, SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT scheme_code, weight_pct,
               ROW_NUMBER() OVER (
                   PARTITION BY scheme_code ORDER BY weight_pct DESC NULLS LAST
               ) AS rn
        FROM nidp.mf_holdings_monthly
        WHERE as_of_month = (SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly)
    ) ranked
    WHERE rn <= 10
    GROUP BY scheme_code
),

nidp_derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, consistency_score, downside_capture_pct,
        aum_trend_score, portfolio_turnover_pct AS turnover_ratio,
        credit_quality_score, duration_risk_score
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),

mf_legacy AS (
    SELECT
        mfmd.instrument_id,
        mfmd.ytm, mfmd.modified_duration, mfmd.investment_style,
        mfmd.moneycontrol_imid, mfmd.morningstar_rating,
        mfmd.manager_tenure_years    AS legacy_manager_tenure_years,
        mfmd.category                AS legacy_category,
        mfmd.sub_category            AS legacy_sub_category,
        mfmd.aum_cr                  AS legacy_aum_cr,
        mfmd.expense_ratio_direct    AS legacy_er_direct,
        mfmd.expense_ratio_regular   AS legacy_er_regular,
        mfmd.expense_ratio           AS legacy_er,
        mfmd.category_avg_1y         AS legacy_cat_avg_1y,
        mfmd.category_avg_3y         AS legacy_cat_avg_3y,
        mfmd.category_avg_5y         AS legacy_cat_avg_5y,
        mfmd.max_drawdown_pct        AS legacy_max_drawdown,
        mfmd.top10_concentration_pct AS legacy_top10_conc,
        mfmd.expense_trend_delta     AS legacy_expense_trend,
        mfmd.turnover_ratio          AS legacy_turnover_ratio,
        mfmd.consistency_score       AS legacy_consistency,
        mfmd.downside_capture_pct    AS legacy_dc_pct,
        mfmd.aum_trend_score         AS legacy_aum_trend,
        mfmd.credit_quality_score    AS legacy_credit_quality,
        mfmd.duration_risk_score     AS legacy_duration_risk,
        mfpr.ret_1y AS legacy_ret_1y, mfpr.ret_3y AS legacy_ret_3y,
        mfpr.ret_5y AS legacy_ret_5y, mfpr.sharpe AS legacy_sharpe,
        mfpr.sortino AS legacy_sortino
    FROM mutual_fund_metadata mfmd
    LEFT JOIN LATERAL (
        SELECT ret_1y, ret_3y, ret_5y, sharpe, sortino
        FROM mutual_fund_performance_ratios
        WHERE instrument_id = mfmd.instrument_id
        ORDER BY ratios_date DESC LIMIT 1
    ) mfpr ON TRUE
)

SELECT
    im.instrument_id::TEXT                                          AS instrument_id,
    ms.scheme_code,
    COALESCE(lr.category,     leg.legacy_category)                  AS category,
    COALESCE(lr.sub_category, leg.legacy_sub_category)              AS sub_category,
    COALESCE(sn.aum_cr,       leg.legacy_aum_cr)                    AS aum_cr,
    CASE
        WHEN COALESCE(lr.scheme_launch_date, ms.launch_date) IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM (NOW() - COALESCE(lr.scheme_launch_date, ms.launch_date)::TIMESTAMPTZ))::NUMERIC / 86400.0 / 365.25, 2)
        ELSE leg.legacy_manager_tenure_years
    END                                                             AS fund_age_years,
    COALESCE(sn.ter_direct,  leg.legacy_er_direct)                  AS expense_ratio_direct,
    COALESCE(sn.ter_regular, leg.legacy_er_regular)                 AS expense_ratio_regular,
    COALESCE(sn.ter_direct, sn.ter_regular, leg.legacy_er)          AS expense_ratio,
    CASE
        WHEN sn.ter_direct IS NOT NULL AND s3.ter_direct_3y IS NOT NULL
        THEN ROUND((sn.ter_direct - s3.ter_direct_3y)::NUMERIC, 4)
        WHEN sn.ter_regular IS NOT NULL AND s3.ter_regular_3y IS NOT NULL
        THEN ROUND((sn.ter_regular - s3.ter_regular_3y)::NUMERIC, 4)
        ELSE leg.legacy_expense_trend
    END                                                             AS expense_trend_delta,
    CASE
        WHEN mt.manager_since_date IS NOT NULL
        THEN ROUND(EXTRACT(EPOCH FROM (NOW() - mt.manager_since_date::TIMESTAMPTZ))::NUMERIC / 86400.0 / 365.25, 2)
        ELSE leg.legacy_manager_tenure_years
    END                                                             AS manager_tenure_years,
    COALESCE(t10.top10_concentration_pct, leg.legacy_top10_conc)    AS top10_concentration_pct,
    COALESCE(nd.turnover_ratio,       leg.legacy_turnover_ratio)    AS turnover_ratio,
    COALESCE(ca.cat_avg_1y, leg.legacy_cat_avg_1y)                  AS category_avg_1y,
    COALESCE(ca.cat_avg_3y, leg.legacy_cat_avg_3y)                  AS category_avg_3y,
    COALESCE(ca.cat_avg_5y, leg.legacy_cat_avg_5y)                  AS category_avg_5y,
    COALESCE(lr.max_drawdown_1y, leg.legacy_max_drawdown)           AS max_drawdown_pct,
    COALESCE(nd.consistency_score,    leg.legacy_consistency)        AS consistency_score,
    COALESCE(nd.downside_capture_pct, leg.legacy_dc_pct)            AS downside_capture_pct,
    COALESCE(nd.aum_trend_score,      leg.legacy_aum_trend)         AS aum_trend_score,
    COALESCE(nd.credit_quality_score, leg.legacy_credit_quality)    AS credit_quality_score,
    COALESCE(nd.duration_risk_score,  leg.legacy_duration_risk)     AS duration_risk_score,
    leg.ytm, leg.modified_duration, leg.investment_style, leg.moneycontrol_imid,
    leg.morningstar_rating,
    COALESCE(lr.return_1y,  leg.legacy_ret_1y)                      AS ret_1y,
    COALESCE(lr.return_3y,  leg.legacy_ret_3y)                      AS ret_3y,
    COALESCE(lr.return_5y,  leg.legacy_ret_5y)                      AS ret_5y,
    COALESCE(lr.sharpe_1y,  leg.legacy_sharpe)                      AS sharpe,
    COALESCE(lr.sortino_1y, leg.legacy_sortino)                     AS sortino,
    lr.return_1m, lr.return_3m, lr.return_6m, lr.return_2y,
    lr.return_since_launch_cagr, lr.alpha_1y, lr.beta_1y, lr.volatility_1y,
    lr.composite_rank                                               AS category_rank,
    lr.return_1y_rank,
    (lr.return_1y IS NOT NULL)                                      AS nidp_returns_available,
    (sn.scheme_code IS NOT NULL)                                    AS nidp_snapshot_available,
    (t10.scheme_code IS NOT NULL)                                   AS nidp_holdings_available,
    sn.primary_manager,
    sn.risk_o_meter

FROM instrument_master im
JOIN nidp.mf_scheme_master ms ON ms.scheme_code = im.symbol AND im.instrument_type = 'MUTUAL_FUND'
LEFT JOIN latest_rank    lr  ON lr.scheme_code  = ms.scheme_code
LEFT JOIN cat_avg        ca  ON ca.category     = lr.category
LEFT JOIN latest_snap    sn  ON sn.scheme_code  = ms.scheme_code
LEFT JOIN snap_3y_ago    s3  ON s3.scheme_code  = ms.scheme_code
LEFT JOIN manager_tenure mt  ON mt.scheme_code  = ms.scheme_code
LEFT JOIN top10_conc     t10 ON t10.scheme_code = ms.scheme_code
LEFT JOIN nidp_derived   nd  ON nd.scheme_code  = ms.scheme_code
LEFT JOIN mf_legacy      leg ON leg.instrument_id = im.instrument_id;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('051_nidp_mf_derived_analytics.sql')
ON CONFLICT (filename) DO NOTHING;
