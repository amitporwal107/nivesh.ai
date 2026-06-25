-- 090_mf_analytics_gaps_r2_te_ir.sql
--
-- Fills three of the six identified MF analytics gaps:
--   Gap 2 — R² (OLS regression validity gate for alpha/beta)
--   Gap 3 — Tracking error + Information ratio
--   Gap 1 — IDCW total-return-incomplete flag (skip+flag approach;
--            no distribution data source available yet)
--
-- Changes:
--   A. ADD COLUMNS to analytics.fund_category_rank
--   B. Rebuild nidp.v_v3_mf_primitives:
--      • New columns: r_squared_1y, tracking_error_1y, information_ratio_1y
--      • New computed column: benchmark_regression_reliable (TRUE when r² ≥ 0.75)
--      • New flag: total_return_incomplete (TRUE for IDCW ISINs)
--      • Restore: credit_quality_score + duration_risk_score (dropped in 085)
--      • Retain: all columns from migration 085

SET search_path TO nidp, analytics, public;


-- ── A. Extend analytics.fund_category_rank ───────────────────────────────────

ALTER TABLE analytics.fund_category_rank
    ADD COLUMN IF NOT EXISTS r_squared_1y          NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS tracking_error_1y     NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS information_ratio_1y  NUMERIC(10,4);

COMMENT ON COLUMN analytics.fund_category_rank.r_squared_1y IS
'OLS R² of fund vs benchmark (1-year window). Values < 0.75 indicate alpha/beta'
' are unreliable. Gate: benchmark_regression_reliable in v_v3_mf_primitives.';

COMMENT ON COLUMN analytics.fund_category_rank.tracking_error_1y IS
'Annualised std dev of daily (fund − benchmark) log-returns, %. 1-year window.';

COMMENT ON COLUMN analytics.fund_category_rank.information_ratio_1y IS
'(fund_return_1y − bench_return_1y) / tracking_error_1y. '
'Measures manager skill per unit of active risk.';


-- ── B. Rebuild nidp.v_v3_mf_primitives ──────────────────────────────────────

DROP VIEW IF EXISTS nidp.v_v3_mf_primitives;

CREATE VIEW nidp.v_v3_mf_primitives AS
WITH

latest_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        category,
        sub_category,
        scheme_launch_date,
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

-- Fallback to last row with a non-NULL return_1y (handles stale data windows)
fallback_1y AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        return_1y   AS fb_return_1y,
        return_3y   AS fb_return_3y,
        return_5y   AS fb_return_5y,
        return_2y   AS fb_return_2y,
        sharpe_1y   AS fb_sharpe_1y,
        sortino_1y  AS fb_sortino_1y,
        max_drawdown_1y         AS fb_max_drawdown_1y,
        alpha_1y                AS fb_alpha_1y,
        beta_1y                 AS fb_beta_1y,
        volatility_1y           AS fb_volatility_1y,
        r_squared_1y            AS fb_r_squared_1y,
        tracking_error_1y       AS fb_tracking_error_1y,
        information_ratio_1y    AS fb_information_ratio_1y,
        return_1y_rank          AS fb_return_1y_rank
    FROM analytics.fund_category_rank
    WHERE return_1y IS NOT NULL
    ORDER BY scheme_code, rank_date DESC
),

cat_avg AS (
    SELECT lr.category,
        AVG(COALESCE(lr.return_1y, fb.fb_return_1y)) AS cat_avg_1y,
        AVG(COALESCE(lr.return_3y, fb.fb_return_3y)) AS cat_avg_3y,
        AVG(COALESCE(lr.return_5y, fb.fb_return_5y)) AS cat_avg_5y
    FROM latest_rank lr
    LEFT JOIN fallback_1y fb USING (scheme_code)
    GROUP BY lr.category
),

latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct AS ter_direct,
        ter_pct        AS ter_regular,
        aum_inr_crore  AS aum_cr,
        primary_manager,
        risk_o_meter
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),

snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct AS ter_direct_3y,
        ter_pct        AS ter_regular_3y
    FROM nidp.mf_scheme_disclosure_snapshot
    WHERE snapshot_date <= NOW() - INTERVAL '3 years'
    ORDER BY scheme_code, snapshot_date DESC
),

manager_tenure AS (
    SELECT scheme_code, MAX(event_date) AS manager_since_date
    FROM nidp.mf_scheme_events
    WHERE event_type = 'manager_change'
    GROUP BY scheme_code
),

top10_conc AS (
    SELECT scheme_code, SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT scheme_code, weight_pct,
               ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY weight_pct DESC) AS rn
        FROM (
            SELECT DISTINCT ON (scheme_code, security_isin)
                   scheme_code, weight_pct
              FROM nidp.mf_holdings_monthly
             WHERE weight_pct IS NOT NULL AND weight_pct > 0
             ORDER BY scheme_code, security_isin, as_of_month DESC
        ) deduped
    ) ranked
    WHERE rn <= 10
    GROUP BY scheme_code
),

derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        consistency_score,
        downside_capture_pct,
        aum_trend_score,
        portfolio_turnover_pct,
        credit_quality_score,
        duration_risk_score
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),

nidp_avail AS (
    SELECT scheme_code,
           TRUE AS nidp_returns_available,
           TRUE AS nidp_snapshot_available
    FROM (
        SELECT DISTINCT scheme_code
          FROM nidp.mf_nav_daily
         WHERE nav_date >= NOW() - INTERVAL '35 days'
    ) recent_nav
),

-- One row per (scheme_code, ISIN). is_idcw = TRUE for IDCW variant.
isin_map AS (
    SELECT scheme_code, isin_growth AS isin, FALSE AS is_idcw
      FROM nidp.mf_scheme_master
     WHERE isin_growth IS NOT NULL
    UNION ALL
    SELECT scheme_code, isin_idcw AS isin, TRUE AS is_idcw
      FROM nidp.mf_scheme_master
     WHERE isin_idcw IS NOT NULL
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
    im.isin,
    lr.scheme_code,
    sm.scheme_name,

    -- Identity
    lr.category,
    lr.sub_category,
    sn.aum_cr,
    EXTRACT(YEAR FROM AGE(NOW(),
        COALESCE(lr.scheme_launch_date, sm.launch_date)))::numeric          AS fund_age_years,

    -- Expense ratios
    COALESCE(sn.ter_direct, sn.ter_regular)                                 AS expense_ratio,
    sn.ter_direct                                                            AS expense_ratio_direct,
    sn.ter_regular                                                           AS expense_ratio_regular,
    CASE
        WHEN sn.ter_regular IS NOT NULL AND s3.ter_regular_3y IS NOT NULL
        THEN sn.ter_regular - s3.ter_regular_3y
    END                                                                      AS expense_trend_delta,

    -- Manager tenure
    EXTRACT(YEAR FROM AGE(NOW(), COALESCE(
        mt.manager_since_date,
        lr.scheme_launch_date,
        sm.launch_date)))::numeric                                           AS manager_tenure_years,

    -- Portfolio structure
    tc.top10_concentration_pct,

    -- Category averages (for excess-return benchmarking in V3)
    ca.cat_avg_1y                                                            AS category_avg_1y,
    ca.cat_avg_3y                                                            AS category_avg_3y,
    ca.cat_avg_5y                                                            AS category_avg_5y,

    -- Drawdown
    COALESCE(lr.max_drawdown_1y, fb.fb_max_drawdown_1y)                     AS max_drawdown_pct,

    -- Performance returns
    COALESCE(lr.return_1y,  fb.fb_return_1y)                                AS ret_1y,
    COALESCE(lr.return_3y,  fb.fb_return_3y)                                AS ret_3y,
    COALESCE(lr.return_5y,  fb.fb_return_5y)                                AS ret_5y,
    COALESCE(lr.sharpe_1y,  fb.fb_sharpe_1y)                                AS sharpe,
    COALESCE(lr.sortino_1y, fb.fb_sortino_1y)                               AS sortino,
    lr.return_1m,
    lr.return_3m,
    lr.return_6m,
    COALESCE(lr.return_2y, fb.fb_return_2y)                                 AS return_2y,
    lr.return_since_launch_cagr,

    -- Benchmark-relative risk
    COALESCE(lr.alpha_1y,  fb.fb_alpha_1y)                                  AS alpha_1y,
    COALESCE(lr.beta_1y,   fb.fb_beta_1y)                                   AS beta_1y,
    COALESCE(lr.volatility_1y, fb.fb_volatility_1y)                         AS volatility_1y,

    -- Gap 2: R² validity gate
    COALESCE(lr.r_squared_1y, fb.fb_r_squared_1y)                           AS r_squared_1y,
    -- Gate: suppress alpha/beta when R² < 0.75 (NULL or below threshold = unreliable)
    (COALESCE(lr.r_squared_1y, fb.fb_r_squared_1y) >= 0.75)                 AS benchmark_regression_reliable,

    -- Gap 3: Tracking error + Information ratio
    COALESCE(lr.tracking_error_1y,    fb.fb_tracking_error_1y)              AS tracking_error_1y,
    COALESCE(lr.information_ratio_1y, fb.fb_information_ratio_1y)           AS information_ratio_1y,

    -- Gap 1: IDCW return-completeness flag
    -- TRUE = IDCW variant; distributions not captured; returns are NAV-only (understated)
    im.is_idcw                                                               AS total_return_incomplete,

    -- Corrected category rank (from mf_category_rank_daily, migration 085)
    cr.corrected_category_rank                                               AS category_rank,
    cr.corrected_category_pct                                                AS category_rank_pct,
    cr.corrected_category_size                                               AS category_size,

    -- Deprecated rank columns (kept for backward compat)
    COALESCE(lr.return_1y_rank, fb.fb_return_1y_rank)                       AS return_1y_rank,
    lr.composite_rank,

    -- Derived analytics (restored: credit_quality_score + duration_risk_score
    -- were accidentally dropped from the view in migration 085)
    d.consistency_score,
    d.downside_capture_pct,
    d.aum_trend_score,
    d.portfolio_turnover_pct,
    d.credit_quality_score,
    d.duration_risk_score,

    -- Availability flags
    (na.nidp_returns_available IS TRUE)              AS nidp_returns_available,
    (na.nidp_snapshot_available IS TRUE)             AS nidp_snapshot_available,
    (tc.top10_concentration_pct IS NOT NULL)         AS nidp_holdings_available,

    -- Display
    sn.primary_manager,
    sn.risk_o_meter

FROM latest_rank lr
JOIN isin_map im ON im.scheme_code = lr.scheme_code
JOIN (
    SELECT DISTINCT ON (scheme_code)
           scheme_code, scheme_name, launch_date
      FROM nidp.mf_scheme_master
     ORDER BY scheme_code
) sm ON sm.scheme_code = lr.scheme_code
LEFT JOIN fallback_1y      fb  ON fb.scheme_code = lr.scheme_code
LEFT JOIN cat_avg          ca  ON ca.category    = lr.category
LEFT JOIN latest_snap      sn  ON sn.scheme_code = lr.scheme_code
LEFT JOIN snap_3y_ago      s3  ON s3.scheme_code = lr.scheme_code
LEFT JOIN manager_tenure   mt  ON mt.scheme_code = lr.scheme_code
LEFT JOIN top10_conc       tc  ON tc.scheme_code = lr.scheme_code
LEFT JOIN derived          d   ON d.scheme_code  = lr.scheme_code
LEFT JOIN nidp_avail       na  ON na.scheme_code = lr.scheme_code
LEFT JOIN latest_cat_rank  cr  ON cr.scheme_code = lr.scheme_code;

COMMENT ON VIEW nidp.v_v3_mf_primitives IS
'MF primitives for V3 scoring. Migration 090 adds: r_squared_1y, '
'tracking_error_1y, information_ratio_1y, benchmark_regression_reliable, '
'total_return_incomplete. Restores credit_quality_score + duration_risk_score '
'(dropped in migration 085). category_rank from mf_category_rank_daily (085).';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('094_mf_analytics_gaps_r2_te_ir.sql')
ON CONFLICT (filename) DO NOTHING;
