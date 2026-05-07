-- 029_nidp_stock_features_extended.sql — extend stock_features_daily.
--
-- Joins fundamentals (Migration 024), shareholding (025), sector
-- master (027), and adjusted close (026) into the per-(symbol,date)
-- feature row that the Strategy Builder DSL queries against.
--
-- Approach:
--   • ALTER TABLE adds new nullable columns for the highest-frequency
--     filters (PE, ROE, FII Δ, sector) — strategy compiler queries
--     these directly. No view-of-view overhead.
--   • A SQL function nidp.populate_stock_features_extended(date)
--     fills the new columns by joining the latest views; the
--     feature_snapshotter calls it post-insert. Idempotent.
--   • A view nidp.v_stock_features_full exposes EVERY downstream
--     column for ad-hoc analytics where columns weren't promoted.

SET search_path TO nidp, public;

-- ── ALTER stock_features_daily ──────────────────────────────────────
ALTER TABLE nidp.stock_features_daily
    ADD COLUMN IF NOT EXISTS pe_ttm                    NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS pb                        NUMERIC(14,4),
    ADD COLUMN IF NOT EXISTS roe_pct                   NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS debt_to_equity            NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS revenue_growth_yoy_pct    NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS pat_growth_yoy_pct        NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS eps_growth_yoy_pct        NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS latest_quarter_end        DATE,

    ADD COLUMN IF NOT EXISTS promoter_pct              NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS fii_pct                   NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS dii_pct                   NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS mf_pct                    NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS promoter_pledged_pct      NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS fii_pct_change_qoq        NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS dii_pct_change_qoq        NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS promoter_pct_change_qoq   NUMERIC(8,4),
    ADD COLUMN IF NOT EXISTS shareholding_period_end   DATE,

    ADD COLUMN IF NOT EXISTS sector                    TEXT,
    ADD COLUMN IF NOT EXISTS industry                  TEXT,

    ADD COLUMN IF NOT EXISTS cumulative_adj_factor     NUMERIC(14,8),
    ADD COLUMN IF NOT EXISTS adj_close                 NUMERIC(14,6),

    -- Options (per-day aggregate, not per-strike)
    ADD COLUMN IF NOT EXISTS options_pcr               NUMERIC(8,4),    -- PE_OI / CE_OI for nearest expiry
    ADD COLUMN IF NOT EXISTS options_total_oi          BIGINT,
    ADD COLUMN IF NOT EXISTS options_oi_change_pct     NUMERIC(10,4);

CREATE INDEX IF NOT EXISTS idx_features_sector_date
    ON nidp.stock_features_daily(sector, as_of_date DESC) WHERE sector IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_features_pe
    ON nidp.stock_features_daily(pe_ttm, as_of_date DESC) WHERE pe_ttm IS NOT NULL;


-- ── populate function ──────────────────────────────────────────────
-- Idempotent. Run after feature_snapshotter completes (or on demand).
-- All joins are LEFT — missing fundamentals or shareholding leave the
-- corresponding columns NULL, the row is still useful for technicals.
CREATE OR REPLACE FUNCTION nidp.populate_stock_features_extended(p_target_date DATE)
RETURNS INTEGER AS $$
DECLARE
    v_rows INTEGER;
BEGIN
    UPDATE nidp.stock_features_daily f
       SET
           -- Fundamentals (latest filed per symbol)
           pe_ttm                 = CASE WHEN fund.eps_ttm > 0 AND f.close > 0
                                          THEN ROUND((f.close / fund.eps_ttm)::numeric, 4)
                                          ELSE NULL END,
           pb                     = CASE WHEN fund.total_equity_cr > 0 AND f.close > 0
                                          THEN ROUND((f.close * 1e7 / (fund.total_equity_cr * 1e7))::numeric, 4)
                                          ELSE NULL END,
           roe_pct                = fund.roe_annualised_pct,
           debt_to_equity         = fund.debt_to_equity,
           revenue_growth_yoy_pct = fund.revenue_growth_yoy_pct,
           pat_growth_yoy_pct     = fund.pat_growth_yoy_pct,
           eps_growth_yoy_pct     = fund.eps_growth_yoy_pct,
           latest_quarter_end     = fund.period_end,

           -- Shareholding (latest quarter per symbol)
           promoter_pct              = shp.promoter_pct,
           fii_pct                   = shp.fii_pct,
           dii_pct                   = shp.dii_pct,
           mf_pct                    = shp.mf_pct,
           promoter_pledged_pct      = shp.promoter_pledged_to_total_pct,
           fii_pct_change_qoq        = shp.fii_pct_change_qoq,
           dii_pct_change_qoq        = shp.dii_pct_change_qoq,
           promoter_pct_change_qoq   = shp.promoter_pct_change_qoq,
           shareholding_period_end   = shp.period_end,

           -- Sector classification
           sector   = sm.sector,
           industry = sm.industry,

           -- Adjusted close
           cumulative_adj_factor = pea.cumulative_adj_factor,
           adj_close             = pea.adj_close
      FROM nidp.stock_features_daily f0
      LEFT JOIN nidp.v_stock_fundamentals_latest fund
             ON fund.symbol = f0.symbol
      LEFT JOIN nidp.v_shareholding_latest shp
             ON shp.symbol = f0.symbol
      LEFT JOIN nidp.sector_master sm
             ON sm.symbol = f0.symbol
      LEFT JOIN nidp.prices_eod_adjusted pea
             ON pea.symbol = f0.symbol
            AND pea.as_of_date = f0.as_of_date
            AND pea.source = 'NIDP_PRICE_ADJUSTER'
     WHERE f.symbol = f0.symbol
       AND f.as_of_date = f0.as_of_date
       AND f.as_of_date = p_target_date;

    GET DIAGNOSTICS v_rows = ROW_COUNT;

    -- Options aggregates (PCR + total OI for nearest expiry)
    -- Computed separately to keep the main UPDATE statement simple.
    UPDATE nidp.stock_features_daily f
       SET options_pcr           = opt.pcr,
           options_total_oi      = opt.total_oi,
           options_oi_change_pct = opt.oi_change_pct
      FROM (
        WITH nearest_exp AS (
            SELECT DISTINCT ON (ticker_symbol)
                   ticker_symbol, expiry_date
              FROM nidp.fno_bhavcopy
             WHERE as_of_date = p_target_date
               AND option_type IN ('CE','PE')
               AND expiry_date >= p_target_date
             ORDER BY ticker_symbol, expiry_date ASC
        )
        SELECT
            f.ticker_symbol AS symbol,
            ROUND((SUM(CASE WHEN f.option_type='PE' THEN f.open_interest END)::numeric
                 / NULLIF(SUM(CASE WHEN f.option_type='CE' THEN f.open_interest END),0))::numeric, 4) AS pcr,
            SUM(f.open_interest)::bigint AS total_oi,
            ROUND((SUM(f.change_in_oi)::numeric
                 / NULLIF(SUM(f.open_interest)-SUM(f.change_in_oi),0) * 100)::numeric, 4) AS oi_change_pct
          FROM nidp.fno_bhavcopy f
          JOIN nearest_exp ne
            ON ne.ticker_symbol = f.ticker_symbol
           AND ne.expiry_date = f.expiry_date
         WHERE f.as_of_date = p_target_date
           AND f.option_type IN ('CE','PE')
         GROUP BY f.ticker_symbol
      ) opt
     WHERE f.symbol = opt.symbol
       AND f.as_of_date = p_target_date;

    RETURN v_rows;
END;
$$ LANGUAGE plpgsql;


-- ── v_stock_features_full ───────────────────────────────────────────
-- Convenience view exposing every column the strategy builder might
-- need but didn't promote into stock_features_daily. Use this for
-- ad-hoc queries; promote a column to the table if it shows up in
-- a hot strategy filter.
CREATE OR REPLACE VIEW nidp.v_stock_features_full AS
SELECT
    f.*,
    fund.revenue_ttm_cr,
    fund.pat_ttm_cr,
    fund.eps_ttm,
    fund.total_equity_cr,
    fund.long_term_debt_cr,
    fund.short_term_debt_cr,
    fund.cash_and_equiv_cr,
    shp.insurance_pct,
    shp.individual_pct,
    shp.mf_pct_change_qoq,
    shp.pledge_pct_change_qoq,
    sm.isin,
    sm.listing_date,
    sm.face_value
  FROM nidp.stock_features_daily f
  LEFT JOIN nidp.v_stock_fundamentals_latest fund
         ON fund.symbol = f.symbol
  LEFT JOIN nidp.v_shareholding_latest shp
         ON shp.symbol = f.symbol
  LEFT JOIN nidp.sector_master sm
         ON sm.symbol = f.symbol;


INSERT INTO nidp.schema_migrations(filename) VALUES ('029_nidp_stock_features_extended.sql')
    ON CONFLICT (filename) DO NOTHING;
