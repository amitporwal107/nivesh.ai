-- 050_nidp_v3_mf_primitives_view.sql
--
-- Creates nidp.v_v3_mf_primitives: a single view that maps NIDP MF tables
-- to the exact field set consumed by the V3 scoring engine
-- (v3_integration._load_v3_primitives_bulk).
--
-- Join spine: instrument_master.symbol = nidp.mf_scheme_master.scheme_code
-- (pg_writer.upsert_mf stores the AMFI scheme_code as instrument_master.symbol)
--
-- NIDP sources used:
--   analytics.fund_category_rank      — returns, sharpe, sortino, max_drawdown
--   nidp.mf_scheme_disclosure_snapshot — TER direct/regular, AUM, manager name
--   nidp.mf_scheme_master              — launch_date → fund_age_years
--   nidp.mf_scheme_events              — manager_change events → tenure
--   nidp.mf_holdings_monthly           — top-10 concentration
--
-- Fallback to mutual_fund_metadata for fields not yet in NIDP:
--   consistency_score, downside_capture_pct, aum_trend_score  (nav_analytics computed)
--   turnover_ratio                                             (not yet ingested)
--   credit_quality_score, duration_risk_score                  (MoneyControl debt-only)
--   ytm, modified_duration, investment_style, moneycontrol_imid
--   expense_trend_delta                                        (computed from snapshots below)
--
-- When NIDP fills those gaps, remove the fallback COALESCEs — the view is the
-- single place to update.

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_v3_mf_primitives AS

WITH

-- ── Latest analytics rank per scheme ────────────────────────────────
latest_rank AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        category,
        sub_category,
        amc_code,
        scheme_name,
        return_1y,
        return_3y,
        return_5y,
        return_1m,
        return_3m,
        return_6m,
        return_2y,
        return_since_launch_cagr,
        sharpe_1y,
        sortino_1y,
        alpha_1y,
        beta_1y,
        volatility_1y,
        max_drawdown_1y,
        ter,
        composite_rank,
        return_1y_rank,
        scheme_launch_date,
        data_since_date
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),

-- ── Category averages (1y/3y/5y) for excess-return normaliser ───────
cat_avg AS (
    SELECT
        category,
        AVG(return_1y) AS cat_avg_1y,
        AVG(return_3y) AS cat_avg_3y,
        AVG(return_5y) AS cat_avg_5y
    FROM latest_rank
    GROUP BY category
),

-- ── Latest disclosure snapshot per scheme ───────────────────────────
latest_snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct         AS ter_regular,
        ter_pct_direct  AS ter_direct,
        aum_inr_crore   AS aum_cr,
        risk_o_meter,
        primary_manager,
        snapshot_date
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),

-- ── Snapshot from ~3 years ago for expense trend ─────────────────────
snap_3y_ago AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        ter_pct         AS ter_regular_3y,
        ter_pct_direct  AS ter_direct_3y
    FROM nidp.mf_scheme_disclosure_snapshot
    WHERE snapshot_date <= (CURRENT_DATE - INTERVAL '3 years')
    ORDER BY scheme_code, snapshot_date DESC
),

-- ── Most recent manager-change event → tenure ────────────────────────
-- Falls back to mutual_fund_metadata.manager_tenure_years when no
-- manager_change event has been recorded yet (e.g. scheme pre-dates
-- our event tracking).
manager_tenure AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        event_date AS manager_since_date
    FROM nidp.mf_scheme_events
    WHERE event_type = 'manager_change'
    ORDER BY scheme_code, event_date DESC
),

-- ── Top-10 holding concentration (latest month) ─────────────────────
top10_conc AS (
    SELECT
        scheme_code,
        SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT
            scheme_code,
            security_name,
            weight_pct,
            ROW_NUMBER() OVER (
                PARTITION BY scheme_code
                ORDER BY weight_pct DESC NULLS LAST
            ) AS rn
        FROM nidp.mf_holdings_monthly
        WHERE as_of_month = (
            SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly
        )
    ) ranked
    WHERE rn <= 10
    GROUP BY scheme_code
),

-- ── Groww-scraped fallback ───────────────────────────────────────────
-- Provides ytm, modified_duration, investment_style, moneycontrol_imid,
-- morningstar_rating, and temporary fallbacks for the 6 fields that will
-- be replaced by nidp.mf_derived_analytics once migration 051 is applied
-- and nidp.refresh_mf_derived_analytics() has been run.
-- Migration 051 re-creates this view with a nidp_derived CTE that takes
-- priority over these legacy_* fallbacks.
mf_legacy AS (
    SELECT
        mfmd.instrument_id,
        mfmd.ytm,
        mfmd.modified_duration,
        mfmd.investment_style,
        mfmd.moneycontrol_imid,
        mfmd.morningstar_rating,
        mfmd.manager_tenure_years        AS legacy_manager_tenure_years,
        mfmd.category                    AS legacy_category,
        mfmd.sub_category                AS legacy_sub_category,
        mfmd.aum_cr                      AS legacy_aum_cr,
        mfmd.expense_ratio_direct        AS legacy_er_direct,
        mfmd.expense_ratio_regular       AS legacy_er_regular,
        mfmd.expense_ratio               AS legacy_er,
        mfmd.category_avg_1y             AS legacy_cat_avg_1y,
        mfmd.category_avg_3y             AS legacy_cat_avg_3y,
        mfmd.category_avg_5y             AS legacy_cat_avg_5y,
        mfmd.max_drawdown_pct            AS legacy_max_drawdown,
        mfmd.top10_concentration_pct     AS legacy_top10_conc,
        mfmd.expense_trend_delta         AS legacy_expense_trend,
        -- Fallbacks for the 4 previously-Groww-only fields
        mfmd.turnover_ratio              AS legacy_turnover_ratio,
        mfmd.consistency_score           AS legacy_consistency,
        mfmd.downside_capture_pct        AS legacy_dc_pct,
        mfmd.aum_trend_score             AS legacy_aum_trend,
        mfmd.credit_quality_score        AS legacy_credit_quality,
        mfmd.duration_risk_score         AS legacy_duration_risk,
        mfpr.ret_1y                      AS legacy_ret_1y,
        mfpr.ret_3y                      AS legacy_ret_3y,
        mfpr.ret_5y                      AS legacy_ret_5y,
        mfpr.sharpe                      AS legacy_sharpe,
        mfpr.sortino                     AS legacy_sortino
    FROM mutual_fund_metadata mfmd
    LEFT JOIN LATERAL (
        SELECT ret_1y, ret_3y, ret_5y, sharpe, sortino
        FROM mutual_fund_performance_ratios
        WHERE instrument_id = mfmd.instrument_id
        ORDER BY ratios_date DESC
        LIMIT 1
    ) mfpr ON TRUE
)

SELECT
    im.instrument_id::TEXT                                         AS instrument_id,
    ms.scheme_code,

    -- Identity
    COALESCE(lr.category,     leg.legacy_category)                 AS category,
    COALESCE(lr.sub_category, leg.legacy_sub_category)             AS sub_category,
    COALESCE(sn.aum_cr,       leg.legacy_aum_cr)                   AS aum_cr,

    -- Fund age (years): prefer NIDP launch_date, fall back to legacy
    CASE
        WHEN COALESCE(lr.scheme_launch_date, ms.launch_date) IS NOT NULL
        THEN ROUND(
            EXTRACT(
                EPOCH FROM (NOW() - COALESCE(lr.scheme_launch_date, ms.launch_date)::TIMESTAMPTZ)
            )::NUMERIC / 86400.0 / 365.25, 2
        )
        ELSE leg.legacy_manager_tenure_years   -- last resort (wrong, but prevents NULL cascade)
    END                                                            AS fund_age_years,

    -- Expense ratios
    COALESCE(sn.ter_direct,  leg.legacy_er_direct)                 AS expense_ratio_direct,
    COALESCE(sn.ter_regular, leg.legacy_er_regular)                AS expense_ratio_regular,
    COALESCE(sn.ter_direct, sn.ter_regular, leg.legacy_er)         AS expense_ratio,

    -- Expense trend: (latest TER direct) − (TER direct 3y ago).
    -- Negative means fees fell — good for the Health score.
    -- Falls back to legacy when snapshot history is thin.
    CASE
        WHEN sn.ter_direct IS NOT NULL AND s3.ter_direct_3y IS NOT NULL
        THEN ROUND((sn.ter_direct - s3.ter_direct_3y)::NUMERIC, 4)
        WHEN sn.ter_regular IS NOT NULL AND s3.ter_regular_3y IS NOT NULL
        THEN ROUND((sn.ter_regular - s3.ter_regular_3y)::NUMERIC, 4)
        ELSE leg.legacy_expense_trend
    END                                                            AS expense_trend_delta,

    -- Manager tenure (years since last manager-change event)
    CASE
        WHEN mt.manager_since_date IS NOT NULL
        THEN ROUND(
            EXTRACT(
                EPOCH FROM (NOW() - mt.manager_since_date::TIMESTAMPTZ)
            )::NUMERIC / 86400.0 / 365.25, 2
        )
        ELSE leg.legacy_manager_tenure_years
    END                                                            AS manager_tenure_years,

    -- Portfolio structure
    COALESCE(t10.top10_concentration_pct, leg.legacy_top10_conc)   AS top10_concentration_pct,
    -- Turnover: falls back to Groww until migration 051 populates mf_derived_analytics
    leg.legacy_turnover_ratio                                        AS turnover_ratio,

    -- Category averages for excess-return computation
    COALESCE(ca.cat_avg_1y, leg.legacy_cat_avg_1y)                 AS category_avg_1y,
    COALESCE(ca.cat_avg_3y, leg.legacy_cat_avg_3y)                 AS category_avg_3y,
    COALESCE(ca.cat_avg_5y, leg.legacy_cat_avg_5y)                 AS category_avg_5y,

    -- Risk metrics — fallback to Groww until migration 051 upgrades this view
    COALESCE(lr.max_drawdown_1y, leg.legacy_max_drawdown)          AS max_drawdown_pct,
    leg.legacy_consistency                                           AS consistency_score,
    leg.legacy_dc_pct                                               AS downside_capture_pct,
    leg.legacy_aum_trend                                            AS aum_trend_score,

    -- Debt-specific — fallback until migration 051 upgrades this view
    leg.legacy_credit_quality                                        AS credit_quality_score,
    leg.legacy_duration_risk                                         AS duration_risk_score,
    leg.ytm,
    leg.modified_duration,
    leg.investment_style,
    leg.moneycontrol_imid,

    -- Proprietary (cannot be sourced from NIDP)
    leg.morningstar_rating,

    -- Performance returns: NIDP first, Groww fallback
    COALESCE(lr.return_1y,  leg.legacy_ret_1y)                     AS ret_1y,
    COALESCE(lr.return_3y,  leg.legacy_ret_3y)                     AS ret_3y,
    COALESCE(lr.return_5y,  leg.legacy_ret_5y)                     AS ret_5y,
    COALESCE(lr.sharpe_1y,  leg.legacy_sharpe)                     AS sharpe,
    COALESCE(lr.sortino_1y, leg.legacy_sortino)                    AS sortino,

    -- Extended returns (NIDP only — not in legacy Groww scrape)
    lr.return_1m,
    lr.return_3m,
    lr.return_6m,
    lr.return_2y,
    lr.return_since_launch_cagr,
    lr.alpha_1y,
    lr.beta_1y,
    lr.volatility_1y,

    -- Category rank
    lr.composite_rank                                               AS category_rank,
    lr.return_1y_rank,

    -- Provenance flags (let callers see which source won)
    (lr.return_1y IS NOT NULL)                                      AS nidp_returns_available,
    (sn.scheme_code IS NOT NULL)                                    AS nidp_snapshot_available,
    (t10.scheme_code IS NOT NULL)                                   AS nidp_holdings_available,

    -- Manager name (for display)
    sn.primary_manager,
    sn.risk_o_meter

FROM instrument_master im
JOIN nidp.mf_scheme_master ms
    ON ms.scheme_code = im.symbol
   AND im.instrument_type = 'MUTUAL_FUND'
LEFT JOIN latest_rank     lr  ON lr.scheme_code  = ms.scheme_code
LEFT JOIN cat_avg         ca  ON ca.category     = lr.category
LEFT JOIN latest_snap     sn  ON sn.scheme_code  = ms.scheme_code
LEFT JOIN snap_3y_ago     s3  ON s3.scheme_code  = ms.scheme_code
LEFT JOIN manager_tenure  mt  ON mt.scheme_code  = ms.scheme_code
LEFT JOIN top10_conc      t10 ON t10.scheme_code = ms.scheme_code
LEFT JOIN mf_legacy       leg ON leg.instrument_id = im.instrument_id;


-- ── Index hint for V3 bulk lookup ────────────────────────────────────
-- The view itself can't be indexed, but the underlying tables are.
-- The hot path is instrument_master.instrument_id → mf_scheme_master via symbol.
-- Ensure the instrument_master→mf_scheme_master join is index-backed:
CREATE INDEX IF NOT EXISTS idx_mf_scheme_master_scheme_code
    ON nidp.mf_scheme_master (scheme_code);   -- already PK, this is a no-op on most DBs

CREATE INDEX IF NOT EXISTS idx_instrument_master_symbol_mf
    ON instrument_master (symbol)
 WHERE instrument_type = 'MUTUAL_FUND';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('050_nidp_v3_mf_primitives_view.sql')
ON CONFLICT (filename) DO NOTHING;
