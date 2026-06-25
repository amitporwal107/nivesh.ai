-- 114_nidp_earnings_estimates.sql — analyst consensus estimates + earnings
-- surprise / beat-miss derivation.
--
-- Implements the estimates design for the Earnings Tracker. Two deliberate
-- adaptations to this codebase's reality (see CONTEXT.md honesty rules):
--
--   1. ACTUALS ALREADY EXIST. The reference design did `ALTER TABLE earnings
--      ADD COLUMN eps_actual / revenue_actual / eps_estimate ...`. Here the
--      actuals are an append-only NSE-XBRL feed in nidp.nse_financials_quarterly
--      (eps_basic = EPS actual; revenue_from_ops_cr = revenue actual, ₹ crore).
--      Estimates are a SEPARATE external feed (vendor / manual) on a different
--      cadence, and each (symbol, period_end) actual has BOTH consolidated and
--      standalone rows. Bolting estimate columns onto every XBRL row would
--      duplicate estimates across bases and leave them NULL for the thousands of
--      uncovered filings. So estimates get their own table, joined to actuals.
--
--   2. SURPRISE + STATUS LIVE IN A VIEW, not STORED generated columns (those
--      can't span two tables). This still puts the formula and the tolerance in
--      ONE editable place — the v_earnings_surprise view below — which was the
--      whole point of the design.
--
-- Until an estimates feed populates nidp.earnings_estimates, every row resolves
-- to 'no_coverage' and the view is empty — by design, not a bug. This supersedes
-- the always-NULL earnings_surprise_pct placeholder in migration 055.

SET search_path TO nidp, public;

-- ── earnings_estimates ──────────────────────────────────────────────────
-- Consensus estimates feed sink. One row per (symbol, period_end, basis, source).
-- Keyed to line up with nidp.nse_financials_quarterly's (symbol, period_end,
-- consolidated) so the surprise join is exact.
CREATE TABLE IF NOT EXISTS nidp.earnings_estimates (
    symbol            TEXT    NOT NULL,
    period_end        DATE    NOT NULL,                 -- the quarter being forecast
    consolidated      BOOLEAN NOT NULL DEFAULT TRUE,    -- which actual basis this estimate is for
    eps_estimate      NUMERIC(14,4),                    -- consensus EPS (₹/share); NULL = no coverage
    revenue_estimate  NUMERIC(18,4),                    -- consensus revenue, ₹ CRORE (match revenue_from_ops_cr)
    estimate_type     TEXT,                             -- 'mean' | 'median'
    eps_basis         TEXT,                             -- 'reported' | 'gaap' | 'adjusted' — MUST match the actual's basis
    n_analysts        INTEGER,                          -- coverage breadth; NULL/0 ⇒ effectively uncovered
    source            TEXT    NOT NULL,                 -- vendor id, e.g. 'REFINITIV' | 'MORNINGSTAR' | 'MANUAL'
    as_of             DATE,                             -- consensus snapshot date
    source_run_id     UUID,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, period_end, consolidated, source)
);
CREATE INDEX IF NOT EXISTS idx_earnings_est_symbol_period
    ON nidp.earnings_estimates(symbol, period_end DESC);


-- ── v_earnings_surprise ─────────────────────────────────────────────────
-- Per company-quarter: actual vs estimate, % surprise, and a tolerance-based
-- beat / met / missed / no_coverage status for EPS and revenue independently,
-- plus a combined overall_status (with 'mixed' for beat-one/miss-other).
--
-- The two correctness traps from the design are handled here:
--   * eps_basis guard — an 'adjusted' consensus compared to our reported/GAAP
--     actual produces garbage; such rows resolve to 'basis_mismatch' (visible,
--     excluded from the headline) rather than a fake beat/miss.
--   * zero-estimate — a percent surprise is undefined when the estimate is 0
--     (NULLIF below makes *_surprise_pct NULL there), so status falls back to the
--     SIGN of the actual: positive actual vs breakeven estimate reads as 'beat'.
--
-- TOLERANCE lives in exactly one place: the `tol` CTE. Edit it to retune.
CREATE OR REPLACE VIEW nidp.v_earnings_surprise AS
WITH tol AS (
    SELECT 0.5::numeric AS eps_tol_pct,     -- |surprise| ≤ ε ⇒ 'met' (in-line)
           1.0::numeric AS rev_tol_pct
),
sect AS (   -- latest known industry per symbol (index membership is the sector source)
    SELECT DISTINCT ON (symbol) symbol, industry
      FROM nidp.index_constituents
     ORDER BY symbol, as_of_date DESC
),
mc AS (     -- latest market cap per symbol (for cap-weighted sector rollups)
    SELECT DISTINCT ON (symbol) symbol, market_cap_cr
      FROM nidp.stock_features_daily
     ORDER BY symbol, as_of_date DESC
),
base AS (
    SELECT e.symbol, e.period_end, e.consolidated,
           a.eps_basic                                    AS eps_actual,
           e.eps_estimate,
           a.revenue_from_ops_cr                          AS revenue_actual,
           e.revenue_estimate,
           e.estimate_type, e.eps_basis, e.n_analysts, e.source, e.as_of,
           sect.industry                                  AS sector,
           mc.market_cap_cr,
           ((a.eps_basic - e.eps_estimate)
                / NULLIF(ABS(e.eps_estimate), 0) * 100)    AS eps_surprise_pct,
           ((a.revenue_from_ops_cr - e.revenue_estimate)
                / NULLIF(ABS(e.revenue_estimate), 0) * 100) AS revenue_surprise_pct
      FROM nidp.earnings_estimates e
      JOIN nidp.nse_financials_quarterly a
        ON a.symbol = e.symbol
       AND a.period_end = e.period_end
       AND a.consolidated = e.consolidated
       AND LOWER(a.period_type) = 'quarterly'
      LEFT JOIN sect ON sect.symbol = e.symbol
      LEFT JOIN mc   ON mc.symbol   = e.symbol
),
scored AS (
    SELECT b.*,
        CASE
            WHEN b.eps_estimate IS NULL                                   THEN 'no_coverage'
            WHEN b.eps_basis IS NOT NULL
             AND b.eps_basis NOT IN ('reported', 'gaap')                  THEN 'basis_mismatch'
            WHEN b.eps_estimate = 0 THEN
                 CASE WHEN b.eps_actual > 0 THEN 'beat'
                      WHEN b.eps_actual < 0 THEN 'missed'
                      ELSE 'met' END
            WHEN ABS(b.eps_surprise_pct) <= t.eps_tol_pct                 THEN 'met'
            WHEN b.eps_surprise_pct > 0                                   THEN 'beat'
            ELSE                                                               'missed'
        END AS eps_status,
        CASE
            WHEN b.revenue_estimate IS NULL                               THEN 'no_coverage'
            WHEN b.revenue_estimate = 0 THEN
                 CASE WHEN b.revenue_actual > 0 THEN 'beat'
                      WHEN b.revenue_actual < 0 THEN 'missed'
                      ELSE 'met' END
            WHEN ABS(b.revenue_surprise_pct) <= t.rev_tol_pct             THEN 'met'
            WHEN b.revenue_surprise_pct > 0                               THEN 'beat'
            ELSE                                                               'missed'
        END AS revenue_status
      FROM base b CROSS JOIN tol t
)
SELECT s.*,
    CASE
        WHEN s.eps_status IN ('no_coverage', 'basis_mismatch')
         AND s.revenue_status = 'no_coverage'                THEN 'no_coverage'
        WHEN s.eps_status IN ('no_coverage', 'basis_mismatch') THEN s.revenue_status
        WHEN s.revenue_status = 'no_coverage'                THEN s.eps_status
        WHEN s.eps_status = s.revenue_status                 THEN s.eps_status
        ELSE                                                      'mixed'
    END AS overall_status
  FROM scored s;


-- ── v_earnings_surprise_sector ──────────────────────────────────────────
-- Cap-weighted "% of the sector that beat", per (period_end, sector), with the
-- uncovered names dropped from the denominator and surfaced as n_no_coverage so
-- the UI can caption a thin bar as low coverage rather than universal misses.
-- (Index scoping — Nifty 500 vs 50 — is applied by the API layer on top of this.)
CREATE OR REPLACE VIEW nidp.v_earnings_surprise_sector AS
SELECT period_end, sector,
       SUM(market_cap_cr) FILTER (WHERE overall_status = 'beat')
         / NULLIF(SUM(market_cap_cr) FILTER (WHERE overall_status <> 'no_coverage'), 0) AS pct_beat_mcap,
       SUM(market_cap_cr) FILTER (WHERE overall_status = 'missed')
         / NULLIF(SUM(market_cap_cr) FILTER (WHERE overall_status <> 'no_coverage'), 0) AS pct_missed_mcap,
       COUNT(*) FILTER (WHERE overall_status = 'beat')        AS n_beat,
       COUNT(*) FILTER (WHERE overall_status = 'met')         AS n_met,
       COUNT(*) FILTER (WHERE overall_status = 'missed')      AS n_missed,
       COUNT(*) FILTER (WHERE overall_status = 'mixed')       AS n_mixed,
       COUNT(*) FILTER (WHERE overall_status = 'no_coverage') AS n_no_coverage,
       COUNT(*)                                               AS n_total
  FROM nidp.v_earnings_surprise
 WHERE sector IS NOT NULL
 GROUP BY period_end, sector;


INSERT INTO nidp.schema_migrations(filename) VALUES ('114_nidp_earnings_estimates.sql')
    ON CONFLICT (filename) DO NOTHING;
