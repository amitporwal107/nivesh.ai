-- 024_nidp_nse_financials.sql — NSE quarterly/annual financial results.
--
-- Source:   NSE corporate-filings-financial-results (XBRL filings)
-- Endpoint: /api/corporates-financial-results?index=equities&period=Quarterly
-- Cadence:  Daily (rolling list of recent filings; ~30 day window)
--
-- Append-only by (symbol, period_end, consolidated, source). When a
-- company refiles a prior quarter (rare — restatement), the new row
-- replaces the old via ON CONFLICT.
--
-- Why per-period granularity matters: factor scoring (quality, growth)
-- needs trailing-12m and YoY comparisons; the Strategy Builder DSL
-- references `fundamentals.eps_growth_yoy`, `fundamentals.roe`, etc.
-- A flat per-(symbol, period_end) table makes those joins trivial.

SET search_path TO nidp, public;

-- ── nse_financials_quarterly ────────────────────────────────────────
-- One row per (symbol, period_end, consolidated). Quarterly OR annual
-- (the period_type column distinguishes). All monetary values in INR
-- crores (NSE XBRL files report in scaled units; parser normalises).
CREATE TABLE IF NOT EXISTS nidp.nse_financials_quarterly (
    symbol                  TEXT NOT NULL,
    period_end              DATE NOT NULL,                 -- end of reporting period
    period_start            DATE,                          -- start of reporting period
    period_type             TEXT NOT NULL,                 -- 'QUARTERLY' | 'HALF_YEARLY' | 'NINE_MONTHS' | 'ANNUAL'
    consolidated            BOOLEAN NOT NULL,              -- true = consolidated, false = standalone
    audited                 BOOLEAN,                       -- true = audited (full-year typically)

    -- Income statement (₹ crores)
    revenue_from_ops_cr     NUMERIC(18,4),
    other_income_cr         NUMERIC(18,4),
    total_income_cr         NUMERIC(18,4),
    total_expenses_cr       NUMERIC(18,4),
    ebitda_cr               NUMERIC(18,4),                 -- derived: total_income − (total_expenses − D&A − interest)
    finance_costs_cr        NUMERIC(18,4),
    depreciation_cr         NUMERIC(18,4),
    pbt_before_exc_cr       NUMERIC(18,4),                 -- Profit Before Tax & Exceptional Items
    exceptional_items_cr    NUMERIC(18,4),
    pbt_cr                  NUMERIC(18,4),                 -- Profit Before Tax
    tax_expense_cr          NUMERIC(18,4),
    pat_continuing_cr       NUMERIC(18,4),                 -- PAT from continuing ops
    pat_discontinuing_cr    NUMERIC(18,4),
    pat_cr                  NUMERIC(18,4),                 -- Net PAT (the headline number)
    pat_attrib_owners_cr    NUMERIC(18,4),                 -- PAT attributable to owners (consolidated only)
    pat_attrib_minority_cr  NUMERIC(18,4),                 -- minority/non-controlling interest

    -- Per-share
    eps_basic               NUMERIC(14,4),                 -- ₹/share, NOT annualised
    eps_diluted             NUMERIC(14,4),
    face_value              NUMERIC(10,4),

    -- Equity / debt (when filed; balance-sheet not always present in
    -- quarterlies — annual filings have the full set)
    equity_share_capital_cr NUMERIC(18,4),
    other_equity_cr         NUMERIC(18,4),
    total_equity_cr         NUMERIC(18,4),
    long_term_debt_cr       NUMERIC(18,4),
    short_term_debt_cr      NUMERIC(18,4),
    cash_and_equiv_cr       NUMERIC(18,4),

    -- Bank/NBFC subset (different taxonomy; populated only when
    -- detected). Kept as separate columns rather than a JSONB so
    -- factor queries remain SQL-native.
    interest_earned_cr      NUMERIC(18,4),                 -- banks
    interest_expended_cr    NUMERIC(18,4),                 -- banks
    nim_pct                 NUMERIC(8,4),                  -- derived

    -- Provenance
    filing_id               TEXT,                          -- NSE filing identifier (broadcast id)
    xbrl_url                TEXT,                          -- source XBRL document
    broadcast_at            TIMESTAMPTZ,                   -- when NSE broadcast the filing
    source                  TEXT NOT NULL,                 -- 'NSE_FIN'
    source_run_id           UUID NOT NULL,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, period_end, consolidated, source)
);

CREATE INDEX IF NOT EXISTS idx_nse_fin_symbol_period
    ON nidp.nse_financials_quarterly(symbol, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_nse_fin_period_end
    ON nidp.nse_financials_quarterly(period_end DESC);
CREATE INDEX IF NOT EXISTS idx_nse_fin_broadcast
    ON nidp.nse_financials_quarterly(broadcast_at DESC) WHERE broadcast_at IS NOT NULL;


-- ── v_stock_fundamentals_latest ─────────────────────────────────────
-- One row per symbol with the latest filed quarter (consolidated when
-- available, falls back to standalone). Computes derived ratios that
-- the Strategy Builder DSL and AI feature store consume.
--
-- Trailing-12m (TTM) values: sum of last 4 quarters where available.
-- This view returns NULL for TTM when fewer than 4 quarters exist.
CREATE OR REPLACE VIEW nidp.v_stock_fundamentals_latest AS
WITH ranked AS (
    SELECT
        f.*,
        ROW_NUMBER() OVER (
            PARTITION BY f.symbol
            ORDER BY f.consolidated DESC, f.period_end DESC
        ) AS rn
      FROM nidp.nse_financials_quarterly f
     WHERE f.period_type IN ('QUARTERLY','HALF_YEARLY','NINE_MONTHS','ANNUAL')
),
ttm AS (
    SELECT
        symbol,
        consolidated,
        SUM(revenue_from_ops_cr) FILTER (
            WHERE rn_back <= 4 AND period_type = 'QUARTERLY'
        ) AS revenue_ttm_cr,
        SUM(pat_cr) FILTER (
            WHERE rn_back <= 4 AND period_type = 'QUARTERLY'
        ) AS pat_ttm_cr,
        SUM(eps_basic) FILTER (
            WHERE rn_back <= 4 AND period_type = 'QUARTERLY'
        ) AS eps_ttm
      FROM (
        SELECT f.*,
               ROW_NUMBER() OVER (
                   PARTITION BY symbol, consolidated
                   ORDER BY period_end DESC
               ) AS rn_back
          FROM nidp.nse_financials_quarterly f
         WHERE period_type = 'QUARTERLY'
      ) q
     GROUP BY symbol, consolidated
),
yoy AS (
    SELECT
        cur.symbol,
        cur.consolidated,
        cur.period_end                                           AS cur_period_end,
        cur.revenue_from_ops_cr                                  AS cur_revenue,
        prv.revenue_from_ops_cr                                  AS prv_revenue,
        cur.pat_cr                                               AS cur_pat,
        prv.pat_cr                                               AS prv_pat,
        cur.eps_basic                                            AS cur_eps,
        prv.eps_basic                                            AS prv_eps
      FROM nidp.nse_financials_quarterly cur
      LEFT JOIN nidp.nse_financials_quarterly prv
        ON prv.symbol       = cur.symbol
       AND prv.consolidated = cur.consolidated
       AND prv.period_type  = cur.period_type
       AND prv.period_end   = (cur.period_end - INTERVAL '1 year')::date
)
SELECT
    r.symbol,
    r.period_end,
    r.period_type,
    r.consolidated,
    r.revenue_from_ops_cr,
    r.pat_cr,
    r.eps_basic,
    r.eps_diluted,
    r.total_equity_cr,
    r.long_term_debt_cr,
    r.short_term_debt_cr,
    r.cash_and_equiv_cr,
    -- Derived: TTM
    t.revenue_ttm_cr,
    t.pat_ttm_cr,
    t.eps_ttm,
    -- Derived: YoY growth (%)
    CASE WHEN y.prv_revenue > 0
         THEN ROUND(((y.cur_revenue - y.prv_revenue) / y.prv_revenue * 100)::numeric, 4)
         ELSE NULL END                                            AS revenue_growth_yoy_pct,
    CASE WHEN y.prv_pat IS NOT NULL AND y.prv_pat <> 0
         THEN ROUND(((y.cur_pat - y.prv_pat) / ABS(y.prv_pat) * 100)::numeric, 4)
         ELSE NULL END                                            AS pat_growth_yoy_pct,
    CASE WHEN y.prv_eps IS NOT NULL AND y.prv_eps <> 0
         THEN ROUND(((y.cur_eps - y.prv_eps) / ABS(y.prv_eps) * 100)::numeric, 4)
         ELSE NULL END                                            AS eps_growth_yoy_pct,
    -- Derived: ROE quarterly (PAT / equity, annualised ×4 for quarter)
    CASE WHEN r.total_equity_cr > 0 AND r.pat_cr IS NOT NULL
         THEN ROUND((r.pat_cr * 4 / r.total_equity_cr * 100)::numeric, 4)
         ELSE NULL END                                            AS roe_annualised_pct,
    -- Derived: Debt-to-equity
    CASE WHEN r.total_equity_cr > 0
         THEN ROUND((COALESCE(r.long_term_debt_cr,0) + COALESCE(r.short_term_debt_cr,0))
                    / r.total_equity_cr, 4)
         ELSE NULL END                                            AS debt_to_equity,
    r.broadcast_at,
    r.source_run_id
  FROM ranked r
  LEFT JOIN ttm t
    ON t.symbol = r.symbol AND t.consolidated = r.consolidated
  LEFT JOIN yoy y
    ON y.symbol = r.symbol AND y.consolidated = r.consolidated
   AND y.cur_period_end = r.period_end
 WHERE r.rn = 1;


-- TimescaleDB hypertable conversion — guarded by extension presence.
-- 1-year chunks (financials are quarterly, low volume per symbol).
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.nse_financials_quarterly', 'period_end',
            chunk_time_interval => INTERVAL '1 year',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('024_nidp_nse_financials.sql')
    ON CONFLICT (filename) DO NOTHING;
