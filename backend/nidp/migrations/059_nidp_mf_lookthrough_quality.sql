-- 059_nidp_mf_lookthrough_quality.sql
--
-- Look-through quality view for mutual funds — weighted-average fundamentals
-- of the underlying stocks each scheme holds. Feeds the Action Matrix
-- scoring engine's "Fundamentals" factor (15% weight) for MF holdings.
--
-- Join chain:
--   mf_holdings_monthly.security_isin
--     → sector_master.isin → sector_master.symbol
--     → stock_features_daily.symbol (latest as_of_date)
--
-- Output columns are weighted by holding.weight_pct (NAV % allocation).
-- Holdings without an ISIN (cash, derivatives) or whose ISIN doesn't map
-- to a known equity symbol are silently excluded — `coverage_pct` reports
-- what fraction of the fund's NAV the lookthrough math actually covers.
--
-- Caveats the scoring engine downstream MUST respect:
--   • mf_holdings_monthly is published with an M+10 reporting lag.
--   • SEBI v1 disclosure covers top-10 AMCs only; coverage_pct for
--     remaining funds will trend toward 0.
--   • Lookthrough numbers are only meaningful when coverage_pct ≥ 60.
--   • Piotroski/Altman columns require fundamental_engine to have run
--     for the latest stock_features_daily date (added to nidp.cron in
--     the same PR as this migration).

SET search_path TO nidp, public;


CREATE OR REPLACE VIEW nidp.v_mf_lookthrough_quality AS
WITH

-- Latest disclosure month present in the holdings table
latest_month AS (
    SELECT MAX(as_of_month) AS m FROM nidp.mf_holdings_monthly
),

-- Latest features date present in the stock features table
latest_features AS (
    SELECT MAX(as_of_date) AS d FROM nidp.stock_features_daily
),

-- Holdings for that latest month, equity-only, with mapped symbol
holdings AS (
    SELECT
        h.scheme_code,
        h.security_isin,
        h.weight_pct,
        sm.symbol
      FROM nidp.mf_holdings_monthly h
      LEFT JOIN nidp.sector_master  sm ON sm.isin = h.security_isin
     WHERE h.as_of_month     = (SELECT m FROM latest_month)
       AND h.security_isin IS NOT NULL
       AND h.weight_pct    IS NOT NULL
       -- Restrict to equity-type holdings; debt/cash/derivative rows
       -- have no stock-fundamentals to look through to.
       AND COALESCE(UPPER(h.instrument_type), 'EQUITY') = 'EQUITY'
),

-- Latest stock features for any symbol we'll need
stock_latest AS (
    SELECT
        f.symbol,
        f.pe_ttm,
        f.roe_pct,
        f.debt_to_equity,
        f.piotroski_score,
        f.altman_z_score
      FROM nidp.stock_features_daily f
     WHERE f.as_of_date = (SELECT d FROM latest_features)
),

-- Weighted contributions per holding row
joined AS (
    SELECT
        h.scheme_code,
        h.weight_pct,
        s.pe_ttm,
        s.roe_pct,
        s.debt_to_equity,
        s.piotroski_score,
        s.altman_z_score,
        -- Coverage contribution: only count rows that actually have a
        -- symbol match (LEFT JOIN above keeps unmatched holdings out
        -- of the numerator but their weight already missed the JOIN).
        CASE WHEN s.symbol IS NOT NULL THEN h.weight_pct ELSE 0 END AS covered_weight
      FROM holdings h
      LEFT JOIN stock_latest s ON s.symbol = h.symbol
)

SELECT
    scheme_code,

    -- ── Weighted averages (NULL when no matching constituents) ───
    -- Each metric is normalised by *covered* weight, not raw weight —
    -- otherwise a fund with 30% mappable holdings would have its PE
    -- diluted by 70% NULL contributors.
    CASE WHEN SUM(covered_weight) > 0 THEN
        ROUND(SUM(pe_ttm * covered_weight)::NUMERIC / SUM(covered_weight), 4)
    END AS lookthrough_pe,

    CASE WHEN SUM(covered_weight) > 0 THEN
        ROUND(SUM(roe_pct * covered_weight)::NUMERIC / SUM(covered_weight), 4)
    END AS lookthrough_roe_pct,

    CASE WHEN SUM(covered_weight) > 0 THEN
        ROUND(SUM(debt_to_equity * covered_weight)::NUMERIC / SUM(covered_weight), 4)
    END AS lookthrough_debt_to_equity,

    CASE WHEN SUM(covered_weight) > 0 THEN
        ROUND(SUM(piotroski_score * covered_weight)::NUMERIC / SUM(covered_weight), 4)
    END AS lookthrough_piotroski,

    CASE WHEN SUM(covered_weight) > 0 THEN
        ROUND(SUM(altman_z_score * covered_weight)::NUMERIC / SUM(covered_weight), 4)
    END AS lookthrough_altman,

    -- ── Coverage diagnostic ──────────────────────────────────────
    -- 0–100. Tells callers how much of the fund's NAV the lookthrough
    -- actually represents. Scoring engine should treat coverage < 60%
    -- as "insufficient evidence" and skip the Fundamentals factor
    -- (redistribute its weight) for that scheme.
    ROUND(LEAST(SUM(covered_weight)::NUMERIC, 100), 2) AS coverage_pct,

    -- Count of equity holdings that mapped to a symbol with features
    COUNT(*) FILTER (WHERE covered_weight > 0) AS matched_constituents,

    -- For freshness debugging in support tickets
    (SELECT m FROM latest_month)    AS holdings_as_of_month,
    (SELECT d FROM latest_features) AS features_as_of_date

  FROM joined
 GROUP BY scheme_code;


COMMENT ON VIEW nidp.v_mf_lookthrough_quality IS
'Weighted-avg PE / ROE / D-E / Piotroski / Altman for each MF scheme via '
'mf_holdings_monthly × sector_master × stock_features_daily. '
'Equity-type holdings only. coverage_pct tells callers how much of NAV is covered. '
'See migration 059 for join semantics.';


INSERT INTO nidp.schema_migrations (filename)
VALUES ('059_nidp_mf_lookthrough_quality.sql')
ON CONFLICT (filename) DO NOTHING;
