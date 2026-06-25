-- 100_fix_mf_scorecard_dedupe_plan_variants.sql
--
-- Fix: nidp.v_mf_category_scorecard ranked every PLAN VARIANT (Growth / Direct /
-- IDCW / IDCW-Direct) of a scheme as a separate peer. Effects:
--   * total_in_category counted plan-variants (e.g. 153) not funds (~52)
--   * the SAME fund got different scores/ranks per plan (HDFC BAF: #23/#49/#122/#132)
--   * IDCW variants (whose NAV is dividend-reduced) polluted the peer set
--
-- Now we rank ONE canonical row per fund — prefer a Growth option, then the
-- non-Direct (plain Growth / Regular) plan, then lowest TER — and let every plan
-- variant of that fund inherit the fund-level composite_score, composite_rank,
-- total_in_category, quality_label, quartiles and metric ranks. Each variant still
-- exposes its OWN raw metrics (return_*, ter, aum, …) so per-scheme_code lookups
-- and the screener keep working unchanged. Returns/score accuracy of the
-- underlying analytics.fund_category_rank rows is out of scope for this migration.

CREATE OR REPLACE VIEW nidp.v_mf_category_scorecard AS
WITH
base AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, scheme_name, category,
        COALESCE(NULLIF(TRIM(sub_category), ''), category) AS sub_category,
        amc_code, ter, rank_date,
        return_1m, return_3m, return_6m,
        return_1y, return_2y, return_3y, return_5y,
        return_since_launch_cagr,
        volatility_1y, sharpe_1y, sortino_1y,
        max_drawdown_1y, alpha_1y, beta_1y,
        scheme_launch_date
    FROM analytics.fund_category_rank
    ORDER BY scheme_code, rank_date DESC
),
derived AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code, consistency_score, downside_capture_pct, aum_trend_score,
        portfolio_turnover_pct AS turnover_ratio, credit_quality_score, duration_risk_score
    FROM nidp.mf_derived_analytics
    ORDER BY scheme_code, as_of_date DESC
),
snap AS (
    SELECT DISTINCT ON (scheme_code) scheme_code, aum_inr_crore AS aum_cr
    FROM nidp.mf_scheme_disclosure_snapshot
    ORDER BY scheme_code, snapshot_date DESC
),
t10 AS (
    SELECT scheme_code, SUM(weight_pct) AS top10_concentration_pct
    FROM (
        SELECT scheme_code, weight_pct,
               ROW_NUMBER() OVER (PARTITION BY scheme_code ORDER BY weight_pct DESC NULLS LAST) AS rn
        FROM nidp.mf_holdings_monthly
        WHERE as_of_month = (SELECT MAX(as_of_month) FROM nidp.mf_holdings_monthly)
    ) ranked WHERE rn <= 10 GROUP BY scheme_code
),
combined AS (
    SELECT
        b.scheme_code, b.scheme_name, b.category, b.sub_category, b.amc_code,
        b.ter, b.rank_date, b.scheme_launch_date,
        b.return_1m, b.return_3m, b.return_6m,
        b.return_1y, b.return_2y, b.return_3y, b.return_5y,
        b.return_since_launch_cagr,
        b.volatility_1y, b.sharpe_1y, b.sortino_1y,
        b.max_drawdown_1y, b.alpha_1y, b.beta_1y,
        d.consistency_score, d.downside_capture_pct, d.aum_trend_score,
        d.turnover_ratio, d.credit_quality_score, d.duration_risk_score,
        s.aum_cr, t.top10_concentration_pct
    FROM base b
    LEFT JOIN derived d ON d.scheme_code = b.scheme_code
    LEFT JOIN snap    s ON s.scheme_code = b.scheme_code
    LEFT JOIN t10     t ON t.scheme_code = b.scheme_code
),

-- ── Fund identity: collapse plan/option variants to one fund_key ─────────────
-- Migration 100: the old view ranked every plan variant (Growth/Direct/IDCW) as a
-- separate "peer", so total_in_category counted variants (~153 not ~funds) and the
-- same fund got different ranks per plan. We now rank ONE canonical Growth row per
-- fund and let every variant inherit its fund's score/rank/quartiles.
ident AS (
    SELECT c.*,
        lower(regexp_replace(
            c.scheme_name,
            '\s*[-–]?\s*\y(direct|regular|growth|idcw|dividend|payout|reinvest\w*|bonus|plan|option|daily|weekly|monthly|quarterly|half.?yearly|annual|fortnightly)\y.*$',
            '', 'i')) AS fund_key,
        (c.scheme_name !~* '(idcw|dividend|payout|reinvest)') AS is_growth
    FROM combined c
),
-- One representative per fund: prefer a Growth option, then the non-Direct (plain
-- Growth / Regular) plan, then lowest TER. Falls back to any plan if no Growth row.
canon AS (
    SELECT DISTINCT ON (sub_category, amc_code, fund_key)
        sub_category, amc_code, fund_key, scheme_code AS canon_code
    FROM ident
    ORDER BY sub_category, amc_code, fund_key,
        is_growth DESC,
        (scheme_name ~* 'direct') ASC,
        ter ASC NULLS LAST,
        scheme_code
),
canon_combined AS (
    SELECT i.* FROM ident i JOIN canon k ON k.canon_code = i.scheme_code
),

-- ── Per-metric ranks/percentiles/quartiles — over CANONICAL funds only ───────
pct AS (
    SELECT *,
        COUNT(*) OVER (PARTITION BY sub_category) AS total_in_category,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_1y   DESC NULLS LAST) AS pct_ret1y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_3y   DESC NULLS LAST) AS pct_ret3y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY return_5y   DESC NULLS LAST) AS pct_ret5y,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY sharpe_1y   DESC NULLS LAST) AS pct_sharpe,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY sortino_1y  DESC NULLS LAST) AS pct_sortino,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY alpha_1y    DESC NULLS LAST) AS pct_alpha,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY consistency_score    DESC NULLS LAST) AS pct_consistency,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY credit_quality_score DESC NULLS LAST) AS pct_credit,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY aum_cr               DESC NULLS LAST) AS pct_aum,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY max_drawdown_1y       ASC  NULLS LAST) AS pct_maxdd,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY ter                   ASC  NULLS LAST) AS pct_ter,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY downside_capture_pct  ASC  NULLS LAST) AS pct_dc,
        PERCENT_RANK() OVER (PARTITION BY sub_category ORDER BY top10_concentration_pct ASC NULLS LAST) AS pct_conc,
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
    FROM canon_combined
),
scored AS (
    SELECT *,
        ROUND(GREATEST(0, LEAST(100,
            CASE
                WHEN category ~* '(debt|bond|gilt|credit risk|duration|income|short term|medium term|long term|banking and psu|psu|floater|liquid|overnight|money market|treasury|ultra short)'
                THEN (COALESCE(pct_credit,0.5)*30 + COALESCE(pct_maxdd,0.5)*20 + COALESCE(pct_sharpe,0.5)*15 + COALESCE(pct_ret1y,0.5)*15 + COALESCE(pct_ter,0.5)*20)
                WHEN category ~* '(hybrid|balanced|multi.?asset|arbitrage|equity savings|conservative hybrid|aggressive hybrid)'
                THEN (COALESCE(pct_sharpe,0.5)*25 + COALESCE(pct_dc,0.5)*20 + COALESCE(pct_ret3y,0.5)*20 + COALESCE(pct_consistency,0.5)*15 + COALESCE(pct_maxdd,0.5)*10 + COALESCE(pct_ter,0.5)*10)
                ELSE (COALESCE(pct_ret1y,0.5)*20 + COALESCE(pct_ret3y,0.5)*20 + COALESCE(pct_ret5y,0.5)*15 + COALESCE(pct_sharpe,0.5)*20 + COALESCE(pct_sortino,0.5)*10 + COALESCE(pct_maxdd,0.5)*10 + COALESCE(pct_ter,0.5)*5)
            END
        ))::NUMERIC(5,1)) AS composite_score
    FROM pct
),
-- Composite rank + label, computed over canonical funds only.
ranked AS (
    SELECT
        scheme_code AS canon_code, sub_category, amc_code, fund_key,
        total_in_category, composite_score,
        RANK() OVER (PARTITION BY sub_category ORDER BY composite_score DESC NULLS LAST) AS composite_rank,
        ROUND(RANK() OVER (PARTITION BY sub_category ORDER BY composite_score DESC NULLS LAST)::NUMERIC
              / NULLIF(total_in_category,0) * 100, 0)::INT AS top_position_pct,
        CASE
            WHEN composite_score >= 90 THEN 'Elite'
            WHEN composite_score >= 80 THEN 'Excellent'
            WHEN composite_score >= 70 THEN 'Strong'
            WHEN composite_score >= 60 THEN 'Average'
            WHEN composite_score >= 50 THEN 'Weak'
            ELSE 'Underperformer'
        END AS quality_label,
        rank_ret1y, rank_ret3y, rank_ret5y, rank_ret1m, rank_ret3m, rank_ret6m,
        rank_sharpe, rank_sortino, rank_alpha, rank_maxdd, rank_ter, rank_aum,
        rank_dc, rank_consistency, rank_conc,
        qtile_ret1y, qtile_ret3y, qtile_ret5y, qtile_sharpe, qtile_sortino,
        qtile_maxdd, qtile_ter, qtile_dc, qtile_consistency, qtile_alpha,
        pct_ret1y, pct_ret3y, pct_ret5y, pct_sharpe, pct_sortino, pct_alpha,
        pct_maxdd, pct_ter, pct_dc, pct_consistency, pct_credit, pct_aum, pct_conc
    FROM scored
)
-- ── Final: every scheme (all plan variants) inherits its fund's canon ranking ─
SELECT
    i.scheme_code, i.scheme_name, i.category, i.sub_category, i.amc_code,
    i.rank_date, i.scheme_launch_date,
    i.return_1m, i.return_3m, i.return_6m,
    i.return_1y, i.return_2y, i.return_3y, i.return_5y,
    i.return_since_launch_cagr,
    i.volatility_1y, i.sharpe_1y, i.sortino_1y,
    i.max_drawdown_1y, i.alpha_1y, i.beta_1y,
    i.ter, i.aum_cr, i.top10_concentration_pct,
    i.consistency_score, i.downside_capture_pct, i.aum_trend_score,
    i.turnover_ratio, i.credit_quality_score, i.duration_risk_score,
    r.total_in_category,
    r.composite_score,
    r.composite_rank,
    r.top_position_pct,
    r.quality_label,
    r.rank_ret1y, r.rank_ret3y, r.rank_ret5y, r.rank_ret1m, r.rank_ret3m, r.rank_ret6m,
    r.rank_sharpe, r.rank_sortino, r.rank_alpha, r.rank_maxdd, r.rank_ter, r.rank_aum,
    r.rank_dc, r.rank_consistency, r.rank_conc,
    r.qtile_ret1y, r.qtile_ret3y, r.qtile_ret5y, r.qtile_sharpe, r.qtile_sortino,
    r.qtile_maxdd, r.qtile_ter, r.qtile_dc, r.qtile_consistency, r.qtile_alpha,
    ROUND(r.pct_ret1y::NUMERIC,4) AS pct_ret1y,
    ROUND(r.pct_ret3y::NUMERIC,4) AS pct_ret3y,
    ROUND(r.pct_ret5y::NUMERIC,4) AS pct_ret5y,
    ROUND(r.pct_sharpe::NUMERIC,4) AS pct_sharpe,
    ROUND(r.pct_sortino::NUMERIC,4) AS pct_sortino,
    ROUND(r.pct_alpha::NUMERIC,4) AS pct_alpha,
    ROUND(r.pct_maxdd::NUMERIC,4) AS pct_maxdd,
    ROUND(r.pct_ter::NUMERIC,4) AS pct_ter,
    ROUND(r.pct_dc::NUMERIC,4) AS pct_dc,
    ROUND(r.pct_consistency::NUMERIC,4) AS pct_consistency,
    ROUND(r.pct_credit::NUMERIC,4) AS pct_credit,
    ROUND(r.pct_aum::NUMERIC,4) AS pct_aum,
    ROUND(r.pct_conc::NUMERIC,4) AS pct_conc
FROM ident i
JOIN canon k ON k.sub_category = i.sub_category
            AND k.amc_code IS NOT DISTINCT FROM i.amc_code
            AND k.fund_key = i.fund_key
JOIN ranked r ON r.canon_code = k.canon_code;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('100_fix_mf_scorecard_dedupe_plan_variants.sql')
ON CONFLICT (filename) DO NOTHING;
