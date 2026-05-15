-- 052_nidp_mf_category_scorecard.sql
--
-- Creates nidp.v_mf_category_scorecard: a view that computes per-metric ranks,
-- percentiles, quartile labels, a category-aware composite score (0–100), and
-- a quality label for every MF scheme within its sub-category peer group.
--
-- Partition key: sub_category (Large Cap, Mid Cap, Flexi Cap, …)
--   Falls back to category when sub_category is NULL.
--
-- Sources:
--   analytics.fund_category_rank      — returns, risk metrics, TER
--   nidp.mf_derived_analytics         — consistency, downside_capture, aum_trend,
--                                       turnover, credit_quality, duration_risk
--   nidp.mf_scheme_disclosure_snapshot — AUM
--   nidp.mf_holdings_monthly           — top-10 concentration
--
-- Composite score weights (category-aware):
--   Equity:  ret_1y(20) + ret_3y(20) + ret_5y(15) + sharpe(20) + sortino(10) + maxdd(10) + ter(5)
--   Hybrid:  sharpe(25) + downside_capture(20) + ret_3y(20) + consistency(15) + maxdd(10) + ter(10)
--   Debt:    credit_quality(30) + maxdd(20) + sharpe(15) + ret_1y(15) + ter(20)
--
-- Quality labels: Elite(90+) / Excellent(80+) / Strong(70+) / Average(60+) / Weak(50+) / Underperformer(<50)

SET search_path TO nidp, public;

CREATE OR REPLACE VIEW nidp.v_mf_category_scorecard AS

WITH

-- ── Latest row per scheme from analytics ─────────────────────────────
base AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        scheme_name,
        category,
        COALESCE(NULLIF(TRIM(sub_category), ''), category) AS sub_category,
        amc_code,
        ter,
        rank_date,
        return_1m, return_3m, return_6m,
        return_1y, return_2y, return_3y, return_5y,
        return_since_launch_cagr,
        volatility_1y, sharpe_1y, sortino_1y,
        max_drawdown_1y, alpha_1y, beta_1y,
        scheme_launch_date
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),

-- ── NIDP-derived analytics (migration 051) ───────────────────────────
derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        consistency_score,
        downside_capture_pct,
        aum_trend_score,
        portfolio_turnover_pct  AS turnover_ratio,
        credit_quality_score,
        duration_risk_score
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),

-- ── Latest AUM ───────────────────────────────────────────────────────
snap AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        aum_inr_crore AS aum_cr
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),

-- ── Top-10 holding concentration (latest month) ──────────────────────
t10 AS (
    SELECT
        scheme_code,
        SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT
            scheme_code,
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

-- ── Combine all sources ───────────────────────────────────────────────
combined AS (
    SELECT
        b.scheme_code, b.scheme_name, b.category, b.sub_category, b.amc_code,
        b.ter, b.rank_date, b.scheme_launch_date,
        b.return_1m, b.return_3m, b.return_6m,
        b.return_1y, b.return_2y, b.return_3y, b.return_5y,
        b.return_since_launch_cagr,
        b.volatility_1y, b.sharpe_1y, b.sortino_1y,
        b.max_drawdown_1y, b.alpha_1y, b.beta_1y,
        d.consistency_score,
        d.downside_capture_pct,
        d.aum_trend_score,
        d.turnover_ratio,
        d.credit_quality_score,
        d.duration_risk_score,
        s.aum_cr,
        t.top10_concentration_pct
    FROM base b
    LEFT JOIN derived d ON d.scheme_code = b.scheme_code
    LEFT JOIN snap    s ON s.scheme_code  = b.scheme_code
    LEFT JOIN t10     t ON t.scheme_code  = b.scheme_code
),

-- ── Per-metric PERCENT_RANK, RANK, and NTILE within sub_category ─────
pct AS (
    SELECT
        *,
        -- Total peers in sub-category
        COUNT(*) OVER (PARTITION BY sub_category) AS total_in_category,

        -- PERCENT_RANK (0=worst, 1=best for this fund vs peers)
        -- Higher-is-better metrics — DESC ordering → top fund gets pct=1
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_1y   DESC NULLS LAST) AS pct_ret1y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_3y   DESC NULLS LAST) AS pct_ret3y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_5y   DESC NULLS LAST) AS pct_ret5y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY sharpe_1y   DESC NULLS LAST) AS pct_sharpe,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY sortino_1y  DESC NULLS LAST) AS pct_sortino,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY alpha_1y    DESC NULLS LAST) AS pct_alpha,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY consistency_score    DESC NULLS LAST) AS pct_consistency,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY credit_quality_score DESC NULLS LAST) AS pct_credit,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY aum_cr               DESC NULLS LAST) AS pct_aum,
        -- Lower-is-better metrics — ASC ordering → top (best) fund gets pct=1
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY max_drawdown_1y       ASC  NULLS LAST) AS pct_maxdd,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY ter                   ASC  NULLS LAST) AS pct_ter,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY downside_capture_pct  ASC  NULLS LAST) AS pct_dc,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY top10_concentration_pct ASC NULLS LAST) AS pct_conc,

        -- Integer ranks (1=best, higher=worse)
        RANK() OVER (PARTITION BY sub_category ORDER BY return_1y   DESC NULLS LAST) AS rank_ret1y,
        RANK() OVER (PARTITION BY sub_category ORDER BY return_3y   DESC NULLS LAST) AS rank_ret3y,
        RANK() OVER (PARTITION BY sub_category ORDER BY return_5y   DESC NULLS LAST) AS rank_ret5y,
        RANK() OVER (PARTITION BY sub_category ORDER BY return_1m   DESC NULLS LAST) AS rank_ret1m,
        RANK() OVER (PARTITION BY sub_category ORDER BY return_3m   DESC NULLS LAST) AS rank_ret3m,
        RANK() OVER (PARTITION BY sub_category ORDER BY return_6m   DESC NULLS LAST) AS rank_ret6m,
        RANK() OVER (PARTITION BY sub_category ORDER BY sharpe_1y   DESC NULLS LAST) AS rank_sharpe,
        RANK() OVER (PARTITION BY sub_category ORDER BY sortino_1y  DESC NULLS LAST) AS rank_sortino,
        RANK() OVER (PARTITION BY sub_category ORDER BY alpha_1y    DESC NULLS LAST) AS rank_alpha,
        RANK() OVER (PARTITION BY sub_category ORDER BY max_drawdown_1y  ASC  NULLS LAST) AS rank_maxdd,
        RANK() OVER (PARTITION BY sub_category ORDER BY ter              ASC  NULLS LAST) AS rank_ter,
        RANK() OVER (PARTITION BY sub_category ORDER BY aum_cr           DESC NULLS LAST) AS rank_aum,
        RANK() OVER (PARTITION BY sub_category ORDER BY downside_capture_pct ASC  NULLS LAST) AS rank_dc,
        RANK() OVER (PARTITION BY sub_category ORDER BY consistency_score    DESC NULLS LAST) AS rank_consistency,
        RANK() OVER (PARTITION BY sub_category ORDER BY top10_concentration_pct ASC NULLS LAST) AS rank_conc,

        -- Quartile labels (1=top quartile, 4=bottom quartile)
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY return_1y        DESC NULLS LAST) AS qtile_ret1y,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY return_3y        DESC NULLS LAST) AS qtile_ret3y,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY return_5y        DESC NULLS LAST) AS qtile_ret5y,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY sharpe_1y        DESC NULLS LAST) AS qtile_sharpe,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY sortino_1y       DESC NULLS LAST) AS qtile_sortino,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY max_drawdown_1y  ASC  NULLS LAST) AS qtile_maxdd,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY ter              ASC  NULLS LAST) AS qtile_ter,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY downside_capture_pct ASC NULLS LAST) AS qtile_dc,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY consistency_score    DESC NULLS LAST) AS qtile_consistency,
        NTILE(4) OVER (PARTITION BY sub_category ORDER BY alpha_1y         DESC NULLS LAST) AS qtile_alpha
    FROM combined
),

-- ── Category-aware composite score (0–100) ───────────────────────────
-- COALESCE to 0.5 (neutral midpoint) when a metric has no data,
-- so missing metrics don't pull the score to zero.
scored AS (
    SELECT
        *,
        ROUND(GREATEST(0, LEAST(100,
            CASE
                -- Debt / Fixed Income
                WHEN category ~* '(debt|bond|gilt|credit risk|duration|income|short term|medium term|long term|banking and psu|psu|floater|liquid|overnight|money market|treasury|ultra short)'
                THEN (
                    COALESCE(pct_credit,  0.5) * 30 +
                    COALESCE(pct_maxdd,   0.5) * 20 +
                    COALESCE(pct_sharpe,  0.5) * 15 +
                    COALESCE(pct_ret1y,   0.5) * 15 +
                    COALESCE(pct_ter,     0.5) * 20
                )
                -- Hybrid / Balanced / Multi Asset
                WHEN category ~* '(hybrid|balanced|multi.?asset|arbitrage|equity savings|conservative hybrid|aggressive hybrid)'
                THEN (
                    COALESCE(pct_sharpe,      0.5) * 25 +
                    COALESCE(pct_dc,          0.5) * 20 +
                    COALESCE(pct_ret3y,       0.5) * 20 +
                    COALESCE(pct_consistency, 0.5) * 15 +
                    COALESCE(pct_maxdd,       0.5) * 10 +
                    COALESCE(pct_ter,         0.5) * 10
                )
                -- Equity (large cap, mid cap, small cap, flexi cap, ELSS, sector, thematic, international)
                ELSE (
                    COALESCE(pct_ret1y,       0.5) * 20 +
                    COALESCE(pct_ret3y,       0.5) * 20 +
                    COALESCE(pct_ret5y,       0.5) * 15 +
                    COALESCE(pct_sharpe,      0.5) * 20 +
                    COALESCE(pct_sortino,     0.5) * 10 +
                    COALESCE(pct_maxdd,       0.5) * 10 +
                    COALESCE(pct_ter,         0.5) *  5
                )
            END
        ))::NUMERIC(5, 1)) AS composite_score
    FROM pct
)

-- ── Final SELECT: add composite rank + quality label ─────────────────
SELECT
    s.scheme_code,
    s.scheme_name,
    s.category,
    s.sub_category,
    s.amc_code,
    s.rank_date,
    s.scheme_launch_date,

    -- Raw metrics
    s.return_1m, s.return_3m, s.return_6m,
    s.return_1y, s.return_2y, s.return_3y, s.return_5y,
    s.return_since_launch_cagr,
    s.volatility_1y, s.sharpe_1y, s.sortino_1y,
    s.max_drawdown_1y, s.alpha_1y, s.beta_1y,
    s.ter,
    s.aum_cr,
    s.top10_concentration_pct,
    s.consistency_score,
    s.downside_capture_pct,
    s.aum_trend_score,
    s.turnover_ratio,
    s.credit_quality_score,
    s.duration_risk_score,

    -- Peer count
    s.total_in_category,

    -- Composite score and rank
    s.composite_score,
    RANK() OVER (
        PARTITION BY s.sub_category
        ORDER BY s.composite_score DESC NULLS LAST
    ) AS composite_rank,

    -- Position from top (e.g. rank 8 of 31 → top_position_pct = 26)
    ROUND(
        RANK() OVER (PARTITION BY s.sub_category ORDER BY s.composite_score DESC NULLS LAST)
        ::NUMERIC / NULLIF(s.total_in_category, 0) * 100,
        0
    )::INT AS top_position_pct,

    -- Quality label
    CASE
        WHEN s.composite_score >= 90 THEN 'Elite'
        WHEN s.composite_score >= 80 THEN 'Excellent'
        WHEN s.composite_score >= 70 THEN 'Strong'
        WHEN s.composite_score >= 60 THEN 'Average'
        WHEN s.composite_score >= 50 THEN 'Weak'
        ELSE 'Underperformer'
    END AS quality_label,

    -- Integer ranks per metric
    s.rank_ret1y, s.rank_ret3y, s.rank_ret5y,
    s.rank_ret1m, s.rank_ret3m, s.rank_ret6m,
    s.rank_sharpe, s.rank_sortino, s.rank_alpha,
    s.rank_maxdd, s.rank_ter, s.rank_aum,
    s.rank_dc, s.rank_consistency, s.rank_conc,

    -- Quartile per key metric (1=top quartile, 4=bottom)
    s.qtile_ret1y, s.qtile_ret3y, s.qtile_ret5y,
    s.qtile_sharpe, s.qtile_sortino,
    s.qtile_maxdd, s.qtile_ter,
    s.qtile_dc, s.qtile_consistency, s.qtile_alpha,

    -- PERCENT_RANK (0–1, 1=best in category) per metric — useful for charts
    ROUND(s.pct_ret1y::NUMERIC,   4) AS pct_ret1y,
    ROUND(s.pct_ret3y::NUMERIC,   4) AS pct_ret3y,
    ROUND(s.pct_ret5y::NUMERIC,   4) AS pct_ret5y,
    ROUND(s.pct_sharpe::NUMERIC,  4) AS pct_sharpe,
    ROUND(s.pct_sortino::NUMERIC, 4) AS pct_sortino,
    ROUND(s.pct_alpha::NUMERIC,   4) AS pct_alpha,
    ROUND(s.pct_maxdd::NUMERIC,   4) AS pct_maxdd,
    ROUND(s.pct_ter::NUMERIC,     4) AS pct_ter,
    ROUND(s.pct_dc::NUMERIC,      4) AS pct_dc,
    ROUND(s.pct_consistency::NUMERIC, 4) AS pct_consistency,
    ROUND(s.pct_credit::NUMERIC,  4) AS pct_credit,
    ROUND(s.pct_aum::NUMERIC,     4) AS pct_aum,
    ROUND(s.pct_conc::NUMERIC,    4) AS pct_conc

FROM scored s;


INSERT INTO nidp.schema_migrations (filename)
VALUES ('052_nidp_mf_category_scorecard.sql')
ON CONFLICT (filename) DO NOTHING;
