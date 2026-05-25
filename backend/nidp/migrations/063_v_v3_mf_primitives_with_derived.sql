-- 063_v_v3_mf_primitives_with_derived.sql
--
-- Extend nidp.v_v3_mf_primitives to expose the 6 derived columns from
-- nidp.mf_derived_analytics. Migration 058 created the view with NO join
-- to derived_analytics, so the engine got NULL for these fields and the
-- weight-redistribution code silently dropped them — collapsing MF
-- composite weight from 100% → ~50% on Health and 80% on Quality.
--
-- After this migration, v_v3_mf_primitives returns:
--   - consistency_score      (Quality.consistency       — 20% in equity profile)
--   - downside_capture_pct   (Quality.downside_capture  + Health.downside_protection)
--   - aum_trend_score        (Health.aum_stability      — 20% in equity, 15% in debt)
--   - turnover_ratio         (Health.turnover           — 15% in equity)
--   - credit_quality_score   (Quality.credit_quality    — 30% in debt profile)
--   - duration_risk_score    (Quality.duration_risk     — 20% in debt profile)
--
-- The view picks the LATEST row per scheme from mf_derived_analytics
-- (DISTINCT ON scheme_code, as_of_date DESC). The table is refreshed
-- nightly by mf_derived_refresh (cron entry, 23:50 IST weekdays).
--
-- Coverage today (verified live 2026-05-21):
--   14,367 schemes × 6 columns present in mf_derived_analytics for
--   as_of_date=CURRENT_DATE. The view now lights all of them up.
--
-- Why a new migration instead of editing 058: the original 058 file is
-- already applied in prod and tracked by sha256. Forking the historic
-- migration would invalidate the hash. Cleaner to drop+create the view
-- here under a fresh migration ID.
--
-- Idempotent: DROP VIEW IF EXISTS + CREATE VIEW. Safe to re-run.

SET search_path TO nidp, public;

DROP VIEW IF EXISTS nidp.v_v3_mf_primitives;

CREATE VIEW nidp.v_v3_mf_primitives AS
WITH

-- Latest fund_category_rank row per scheme
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
        return_1y_rank, composite_rank
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),

-- Category-average returns
cat_avg AS (
    SELECT
        category,
        AVG(return_1y) AS cat_avg_1y,
        AVG(return_3y) AS cat_avg_3y,
        AVG(return_5y) AS cat_avg_5y
    FROM (
        SELECT DISTINCT ON (scheme_code) category, return_1y, return_3y, return_5y
        FROM analytics.fund_category_rank
        ORDER BY scheme_code, rank_date DESC
    ) latest_per_scheme
    GROUP BY category
),

-- Latest disclosure snapshot (TER, AUM, manager)
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

-- TER 3 years ago (for expense_trend_delta)
snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct_direct AS ter_direct_3y,
        ter_pct        AS ter_regular_3y
    FROM nidp.mf_scheme_disclosure_snapshot
    WHERE snapshot_date <= NOW() - INTERVAL '3 years'
    ORDER BY scheme_code, snapshot_date DESC
),

-- Manager since (most-recent manager-change event date)
manager_tenure AS (
    SELECT
        scheme_code,
        MAX(event_date) AS manager_since_date
    FROM nidp.mf_scheme_events
    WHERE event_type = 'manager_change'
    GROUP BY scheme_code
),

-- Top-10 holding concentration % (from latest holdings month)
top10_conc AS (
    SELECT scheme_code, SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT
            scheme_code,
            weight_pct,
            ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY weight_pct DESC) AS rn
        FROM (
            SELECT DISTINCT ON (scheme_code, security_isin)
                scheme_code, security_isin, weight_pct
            FROM nidp.mf_holdings_monthly
            WHERE security_isin IS NOT NULL
            ORDER BY scheme_code, security_isin, as_of_month DESC
        ) ranked
    ) r
    WHERE rn <= 10
    GROUP BY scheme_code
),

-- ── NEW IN 063: latest derived-analytics row per scheme ──
latest_derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        consistency_score,
        downside_capture_pct,
        aum_trend_score,
        portfolio_turnover_pct,
        credit_quality_score,
        duration_risk_score,
        nav_obs_count,
        aum_obs_count,
        holdings_months_count
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),

-- One row per (scheme_code, ISIN) — unnest both growth and idcw ISINs
scheme_isins AS (
    SELECT
        ms.scheme_code,
        ms.scheme_name,
        ms.launch_date,
        i.isin
    FROM nidp.mf_scheme_master ms,
    LATERAL (
        SELECT unnest(ARRAY[ms.isin_growth, ms.isin_idcw]) AS isin
    ) i
    WHERE i.isin IS NOT NULL AND i.isin <> ''
)

SELECT
    si.isin                                                         AS isin,
    si.scheme_code,
    si.scheme_name,

    -- Identity
    lr.category,
    lr.sub_category,
    sn.aum_cr,

    -- Fund age (years since launch)
    CASE
        WHEN COALESCE(lr.scheme_launch_date, si.launch_date) IS NOT NULL
        THEN ROUND(
            EXTRACT(EPOCH FROM (NOW() - COALESCE(lr.scheme_launch_date, si.launch_date)::TIMESTAMPTZ))::NUMERIC
            / 86400.0 / 365.25, 2
        )
        ELSE NULL
    END                                                              AS fund_age_years,

    -- Expense ratios
    sn.ter_direct                                                    AS expense_ratio_direct,
    sn.ter_regular                                                   AS expense_ratio_regular,
    COALESCE(sn.ter_direct, sn.ter_regular)                          AS expense_ratio,

    -- Expense trend (latest direct − 3y-ago direct)
    CASE
        WHEN sn.ter_direct IS NOT NULL AND s3.ter_direct_3y IS NOT NULL
        THEN ROUND((sn.ter_direct - s3.ter_direct_3y)::NUMERIC, 4)
        WHEN sn.ter_regular IS NOT NULL AND s3.ter_regular_3y IS NOT NULL
        THEN ROUND((sn.ter_regular - s3.ter_regular_3y)::NUMERIC, 4)
        ELSE NULL
    END                                                              AS expense_trend_delta,

    -- Manager tenure (years since last manager change)
    CASE
        WHEN mt.manager_since_date IS NOT NULL
        THEN ROUND(
            EXTRACT(EPOCH FROM (NOW() - mt.manager_since_date::TIMESTAMPTZ))::NUMERIC
            / 86400.0 / 365.25, 2
        )
        ELSE NULL
    END                                                              AS manager_tenure_years,

    -- Portfolio structure
    t10.top10_concentration_pct,

    -- Category averages
    ca.cat_avg_1y                                                    AS category_avg_1y,
    ca.cat_avg_3y                                                    AS category_avg_3y,
    ca.cat_avg_5y                                                    AS category_avg_5y,

    -- Risk metrics (NIDP-native only)
    lr.max_drawdown_1y                                               AS max_drawdown_pct,

    -- Performance returns
    lr.return_1y                                                     AS ret_1y,
    lr.return_3y                                                     AS ret_3y,
    lr.return_5y                                                     AS ret_5y,
    lr.sharpe_1y                                                     AS sharpe,
    lr.sortino_1y                                                    AS sortino,

    -- Extended returns
    lr.return_1m,
    lr.return_3m,
    lr.return_6m,
    lr.return_2y,
    lr.return_since_launch_cagr,
    lr.alpha_1y,
    lr.beta_1y,
    lr.volatility_1y,

    -- Category rank
    lr.composite_rank                                                AS category_rank,
    lr.return_1y_rank,

    -- ── NEW IN 063: derived-analytics columns the engine reads ──
    ld.consistency_score,
    ld.downside_capture_pct,
    ld.aum_trend_score,
    ld.portfolio_turnover_pct                                        AS turnover_ratio,
    ld.credit_quality_score,
    ld.duration_risk_score,

    -- Derived diagnostics (debugging which schemes have enough history)
    ld.nav_obs_count,
    ld.aum_obs_count,
    ld.holdings_months_count,

    -- Provenance flags
    (lr.return_1y IS NOT NULL)                                       AS nidp_returns_available,
    (sn.scheme_code IS NOT NULL)                                     AS nidp_snapshot_available,
    (t10.scheme_code IS NOT NULL)                                    AS nidp_holdings_available,
    (ld.scheme_code IS NOT NULL)                                     AS nidp_derived_available,

    -- Display
    sn.primary_manager,
    sn.risk_o_meter

FROM scheme_isins si
LEFT JOIN latest_rank     lr  ON lr.scheme_code  = si.scheme_code
LEFT JOIN cat_avg         ca  ON ca.category     = lr.category
LEFT JOIN latest_snap     sn  ON sn.scheme_code  = si.scheme_code
LEFT JOIN snap_3y_ago     s3  ON s3.scheme_code  = si.scheme_code
LEFT JOIN manager_tenure  mt  ON mt.scheme_code  = si.scheme_code
LEFT JOIN top10_conc      t10 ON t10.scheme_code = si.scheme_code
LEFT JOIN latest_derived  ld  ON ld.scheme_code  = si.scheme_code;

COMMENT ON VIEW nidp.v_v3_mf_primitives IS
    'V3 MF primitives keyed on ISIN. One row per (scheme_code, ISIN). '
    'Migration 063 added LEFT JOIN to nidp.mf_derived_analytics, exposing '
    'consistency_score, downside_capture_pct, aum_trend_score, turnover_ratio, '
    'credit_quality_score, duration_risk_score — the 6 fields that the V3 '
    'engine reads but migration 058 silently dropped.';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('063_v_v3_mf_primitives_with_derived.sql')
ON CONFLICT (filename) DO NOTHING;
