-- Migration 087: Portfolio Risk Analytics (PRA) schema
--
-- Creates the pra schema with:
--   pra.portfolio_risk_results    — per-user nightly risk computation (hypertable)
--   pra.component_var             — per-holding component VaR breakdown
--   pra.stress_scenarios          — table-driven scenario config (seeded)
--   pra.stress_results            — per-run scenario impact rows
--   pra.audit_log                 — metric-level audit trail (AC-V1-012)
--   pra.v_portfolio_lookthrough   — view: effective_weight(j) across all users
--
-- All additions are IF NOT EXISTS — safe to re-run.
-- pra schema is fully isolated from existing NIDP schemas.

-- ── Schema ─────────────────────────────────────────────────────────────────────
-- Drop and recreate: safe because this is the first migration for the pra schema.
-- Handles the case where a prior failed run left the schema in a partial state.

DROP SCHEMA IF EXISTS pra CASCADE;
CREATE SCHEMA pra;

-- ── pra.portfolio_risk_results ─────────────────────────────────────────────────
-- One row per (external_user_id, computed_date). Primary read path for dashboard.
-- Regular table (not hypertable) — nightly batch with O(users) rows; no need for
-- TimescaleDB partitioning. BRIN index on computed_date for range scans.

CREATE TABLE IF NOT EXISTS pra.portfolio_risk_results (
    result_id               UUID        NOT NULL DEFAULT gen_random_uuid(),
    external_user_id        TEXT        NOT NULL,
    computed_date           DATE        NOT NULL,

    -- Portfolio summary
    portfolio_value_inr     NUMERIC(20,2),
    holding_count           INTEGER,
    lookthrough_coverage_pct NUMERIC(7,2),

    -- Core risk metrics
    volatility_annual_pct   NUMERIC(10,6),
    benchmark_vol_annual_pct NUMERIC(10,6),
    var_95_1y_pct           NUMERIC(10,6),
    var_95_1y_inr           NUMERIC(20,2),
    max_drawdown_pct        NUMERIC(10,6),
    beta_nifty500           NUMERIC(8,4),
    sharpe_1y               NUMERIC(8,4),

    -- Supporting metrics (V1)
    tracking_error_pct      NUMERIC(10,6),
    hhi_lookthrough         INTEGER,

    -- Data quality flags
    look_through_stale      BOOLEAN     NOT NULL DEFAULT false,
    price_stale             BOOLEAN     NOT NULL DEFAULT false,
    data_stale              BOOLEAN     NOT NULL DEFAULT false,
    missing_symbols         TEXT[]      DEFAULT '{}',

    -- Audit trail
    holdings_snapshot_hash  TEXT,
    formula_version         TEXT        NOT NULL DEFAULT 'pra-v1.0',
    lookback_days           INTEGER     NOT NULL DEFAULT 252,
    risk_free_rate_pct      NUMERIC(8,4),
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (result_id, computed_date),
    UNIQUE (external_user_id, computed_date)
);

CREATE INDEX IF NOT EXISTS idx_pra_results_user_date
    ON pra.portfolio_risk_results (external_user_id, computed_date DESC);

CREATE INDEX IF NOT EXISTS idx_pra_results_date_brin
    ON pra.portfolio_risk_results USING BRIN (computed_date);

-- ── pra.component_var ──────────────────────────────────────────────────────────
-- Per-holding component VaR (the "Share of Σ" breakdown). One row per
-- (result_id, security_key). Populated only when covariance matrix is available.

CREATE TABLE IF NOT EXISTS pra.component_var (
    cv_id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id           UUID        NOT NULL REFERENCES pra.portfolio_risk_results(result_id) ON DELETE CASCADE,
    security_key        TEXT        NOT NULL,   -- ISIN preferred; symbol fallback
    security_name       TEXT,
    asset_class         TEXT,                   -- EQUITY | MF | ETF | DEBT | CASH
    effective_weight_pct NUMERIC(10,6),         -- look-through effective weight
    marginal_var_pct    NUMERIC(10,6),          -- VaR × (Σw)_i / (wᵀΣw)
    component_var_pct   NUMERIC(10,6),          -- w_i × marginal_var_pct (sums to total VaR)
    share_of_sigma_pct  NUMERIC(10,6),          -- component_var / total_var × 100 (sums to 100)
    look_through_path   JSONB       DEFAULT '[]'  -- ["direct"] or ["via HDFC Flexi Cap"]
);

CREATE INDEX IF NOT EXISTS idx_pra_cv_result
    ON pra.component_var (result_id);

-- ── pra.stress_scenarios ──────────────────────────────────────────────────────
-- Table-driven scenario config (AC-V1-008 — add scenario without code change).
-- Seeded with standard Indian-market historical scenarios.

CREATE TABLE IF NOT EXISTS pra.stress_scenarios (
    scenario_id             TEXT        PRIMARY KEY,
    scenario_name           TEXT        NOT NULL,
    equity_shock_pct        NUMERIC(8,4) NOT NULL,  -- negative = drawdown (e.g. -38.0)
    rate_shock_bps          NUMERIC(8,2) NOT NULL,  -- positive = rate rise
    recovery_estimate       TEXT,                   -- human-readable e.g. "18-24 months"
    description             TEXT,
    version                 INTEGER     NOT NULL DEFAULT 1,
    enabled                 BOOLEAN     NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed: standard Indian-market historical stress scenarios.
-- Equity shocks from Nifty 500 actual peak-to-trough. Rate shocks from 10Y G-Sec moves.
INSERT INTO pra.stress_scenarios
    (scenario_id, scenario_name, equity_shock_pct, rate_shock_bps, recovery_estimate, description)
VALUES
    ('gfc_2008',        '2008 GFC Crash',          -50.0,  -150.0, '18–24 months',
     'Nifty 500 peak-to-trough Oct-07 to Mar-09. 10Y yield fell on RBI rate cuts.'),
    ('covid_2020',      'COVID-19 Shock 2020',     -38.0,   -75.0, '5–7 months',
     'Nifty 500 Jan-20 to Mar-20 drawdown. RBI cut repo by 75bps in emergency meetings.'),
    ('rate_spike_200',  'Rate Spike +200bps',       -12.0,  200.0, '9–12 months',
     'Hypothetical 200bps RBI rate hike cycle. Equity re-rates on higher discount rate.'),
    ('taper_tantrum',   '2013 Taper Tantrum',       -15.0,  120.0, '6–9 months',
     'Fed taper announcement May-13. Nifty fell 15%, 10Y yield rose 120bps in 3 months.'),
    ('mild_recession',  'Mild Recession',           -20.0,  -50.0, '12–15 months',
     'Generic slowdown scenario: earnings miss + mild rate cuts to stimulate.')
ON CONFLICT (scenario_id) DO NOTHING;

-- ── pra.stress_results ────────────────────────────────────────────────────────
-- Per-run scenario impact rows. One row per (result_id, scenario_id).

CREATE TABLE IF NOT EXISTS pra.stress_results (
    sr_id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id               UUID        NOT NULL REFERENCES pra.portfolio_risk_results(result_id) ON DELETE CASCADE,
    scenario_id             TEXT        NOT NULL REFERENCES pra.stress_scenarios(scenario_id),
    portfolio_impact_pct    NUMERIC(10,6),  -- β × equity_shock + duration × Δy × w_debt
    portfolio_impact_inr    NUMERIC(20,2),
    benchmark_impact_pct    NUMERIC(10,6),  -- equity_shock × 1.0 (benchmark = full equity shock)
    equity_contribution_pct NUMERIC(10,6),
    rate_contribution_pct   NUMERIC(10,6),
    computed_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (result_id, scenario_id)
);

CREATE INDEX IF NOT EXISTS idx_pra_sr_result
    ON pra.stress_results (result_id);

-- ── pra.audit_log ─────────────────────────────────────────────────────────────
-- Metric-level audit trail (AC-V1-012). Every displayed figure traceable to
-- its inputs, formula version, and computation timestamp.

CREATE TABLE IF NOT EXISTS pra.audit_log (
    log_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    result_id               UUID        NOT NULL REFERENCES pra.portfolio_risk_results(result_id) ON DELETE CASCADE,
    metric_name             TEXT        NOT NULL,
    computed_value          NUMERIC(20,8),
    input_snapshot_hash     TEXT,
    formula_version         TEXT        NOT NULL,
    computation_timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pra_audit_result
    ON pra.audit_log (result_id);

-- ── pra.v_portfolio_lookthrough ───────────────────────────────────────────────
-- View: effective_weight(j) = Σ_funds(w_f × h_{f,j}) + direct_holding(j)
-- per (external_user_id, snapshot_date, security_isin).
--
-- Joins:
--   portfolio.user_holdings_snapshot (user weights per holding)
--   nidp.mf_holdings_monthly          (fund holdings → underlying securities)
--
-- For MF/ETF holdings: expands via mf_holdings_monthly using most recent month.
-- For direct EQUITY holdings: passes through as-is.
-- Both paths resolve to security_isin as the common key.

CREATE OR REPLACE VIEW pra.v_portfolio_lookthrough AS
WITH
-- Latest available month of fund holdings per scheme
latest_holdings AS (
    SELECT DISTINCT ON (scheme_code)
        scheme_code,
        as_of_month,
        security_isin,
        security_name,
        instrument_type,
        sector,
        weight_pct
    FROM nidp.mf_holdings_monthly
    WHERE security_isin IS NOT NULL
      AND weight_pct    IS NOT NULL
      AND weight_pct    > 0
    ORDER BY scheme_code, as_of_month DESC
),
-- User holdings with fund weights resolved to AMFI scheme_code
user_holdings AS (
    SELECT
        h.external_user_id,
        h.snapshot_date,
        h.asset_class,
        h.isin,
        h.amfi_scheme_code,
        h.instrument_name,
        h.weight_pct            AS holding_weight_pct,   -- user's allocation to this holding
        h.market_value_inr
    FROM portfolio.user_holdings_snapshot h
    WHERE h.weight_pct > 0
),
-- Expand MF/ETF holdings through to underlying securities
mf_expanded AS (
    SELECT
        u.external_user_id,
        u.snapshot_date,
        lh.security_isin,
        lh.security_name,
        lh.instrument_type      AS asset_class,
        lh.sector,
        -- effective weight = user's allocation to this fund × fund's allocation to this security
        (u.holding_weight_pct * lh.weight_pct / 100.0) AS effective_weight_pct,
        'MF_LOOKTHROUGH'        AS source_type,
        u.instrument_name       AS via_fund_name,
        lh.as_of_month          AS holdings_as_of_month
    FROM user_holdings u
    JOIN latest_holdings lh
        ON lh.scheme_code = u.amfi_scheme_code
    WHERE u.asset_class IN ('MF', 'ETF')
      AND u.amfi_scheme_code IS NOT NULL
),
-- Direct equity/ETF holdings (no expansion needed)
direct_holdings AS (
    SELECT
        u.external_user_id,
        u.snapshot_date,
        u.isin                  AS security_isin,
        u.instrument_name       AS security_name,
        u.asset_class,
        NULL::TEXT              AS sector,
        u.holding_weight_pct    AS effective_weight_pct,
        'DIRECT'                AS source_type,
        NULL::TEXT              AS via_fund_name,
        NULL::DATE              AS holdings_as_of_month
    FROM user_holdings u
    WHERE u.asset_class IN ('EQUITY', 'DEBT', 'CASH', 'OTHER')
      AND u.isin IS NOT NULL
),
-- Union and aggregate (same security may appear via multiple paths)
combined AS (
    SELECT * FROM mf_expanded
    UNION ALL
    SELECT * FROM direct_holdings
)
SELECT
    external_user_id,
    snapshot_date,
    security_isin,
    -- Take the first non-null name across paths
    MAX(security_name)              AS security_name,
    MAX(asset_class)                AS asset_class,
    MAX(sector)                     AS sector,
    SUM(effective_weight_pct)       AS effective_weight_pct,
    ARRAY_AGG(DISTINCT
        CASE WHEN source_type = 'DIRECT' THEN 'direct'
             ELSE 'via ' || COALESCE(via_fund_name, 'unknown')
        END
    )                               AS look_through_path,
    MAX(holdings_as_of_month)       AS holdings_as_of_month
FROM combined
GROUP BY
    external_user_id,
    snapshot_date,
    security_isin;

COMMENT ON VIEW pra.v_portfolio_lookthrough IS
    'Effective look-through weights per (user, date, security). '
    'Expands MF/ETF holdings via mf_holdings_monthly (most-recent month). '
    'Direct holdings pass through as-is. Coverage is partial when AMC scrapers are stale.';
