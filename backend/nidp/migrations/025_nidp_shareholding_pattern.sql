-- 025_nidp_shareholding_pattern.sql — NSE quarterly shareholding pattern.
--
-- Source:   NSE corporate-share-holdings-master (XBRL filings)
-- Cadence:  Daily ingest of rolling-list (filings have ~45-day lag
--           post quarter-end, but the LIST endpoint refreshes daily
--           as new SEBI Reg 31 filings arrive)
-- Output:   nidp.shareholding_pattern  +  v_shareholding_latest view
--
-- Append-only by (symbol, period_end, source). When a company refiles
-- (correction within the disclosure window), ON CONFLICT replaces.

SET search_path TO nidp, public;

-- ── shareholding_pattern ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.shareholding_pattern (
    symbol                  TEXT NOT NULL,
    period_end              DATE NOT NULL,                 -- end of quarter

    -- Promoter group
    promoter_pct            NUMERIC(8,4),                  -- total promoter & PG holding %
    promoter_pledged_pct    NUMERIC(8,4),                  -- pledged shares as % of promoter holding
    promoter_pledged_to_total_pct NUMERIC(8,4),            -- pledged as % of total shares

    -- Public — institutional
    fii_pct                 NUMERIC(8,4),                  -- Foreign Portfolio Investors
    dii_pct                 NUMERIC(8,4),                  -- Domestic Institutional Investors (sum of below)
    mf_pct                  NUMERIC(8,4),                  -- Mutual Funds
    insurance_pct           NUMERIC(8,4),                  -- Insurance companies
    bank_fi_pct             NUMERIC(8,4),                  -- Banks & FIs
    govt_holding_pct        NUMERIC(8,4),                  -- Central / State govt holding

    -- Public — non-institutional
    public_pct              NUMERIC(8,4),                  -- total public holding (= 100 − promoter)
    individual_pct          NUMERIC(8,4),                  -- retail individuals
    nri_pct                 NUMERIC(8,4),                  -- NRIs
    bodies_corporate_pct    NUMERIC(8,4),                  -- domestic bodies corporate

    -- Aggregate counts (when filed)
    total_shares            BIGINT,
    promoter_shares         BIGINT,
    public_shares           BIGINT,
    pledged_shares          BIGINT,

    -- Provenance
    filing_id               TEXT,
    xbrl_url                TEXT,
    broadcast_at            TIMESTAMPTZ,
    source                  TEXT NOT NULL,                 -- 'NSE_SHP'
    source_run_id           UUID NOT NULL,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (symbol, period_end, source)
);

CREATE INDEX IF NOT EXISTS idx_shp_symbol_period
    ON nidp.shareholding_pattern(symbol, period_end DESC);
CREATE INDEX IF NOT EXISTS idx_shp_period
    ON nidp.shareholding_pattern(period_end DESC);


-- ── v_shareholding_latest ───────────────────────────────────────────
-- Latest quarter per symbol + QoQ deltas for FII / DII / promoter.
-- These deltas are the "smart money" signals consumed by the alpha
-- workflow + Strategy Builder DSL `shareholding.fii_pct_change_qoq`.
CREATE OR REPLACE VIEW nidp.v_shareholding_latest AS
WITH ranked AS (
    SELECT s.*,
           ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY period_end DESC) AS rn
      FROM nidp.shareholding_pattern s
),
prev AS (
    SELECT cur.symbol, cur.period_end,
           cur.promoter_pct AS cur_promoter,  prv.promoter_pct AS prv_promoter,
           cur.fii_pct      AS cur_fii,       prv.fii_pct      AS prv_fii,
           cur.dii_pct      AS cur_dii,       prv.dii_pct      AS prv_dii,
           cur.mf_pct       AS cur_mf,        prv.mf_pct       AS prv_mf,
           cur.promoter_pledged_to_total_pct AS cur_pledge,
           prv.promoter_pledged_to_total_pct AS prv_pledge
      FROM nidp.shareholding_pattern cur
      LEFT JOIN nidp.shareholding_pattern prv
        ON prv.symbol = cur.symbol
       AND prv.period_end < cur.period_end
       AND prv.period_end = (
           SELECT MAX(period_end) FROM nidp.shareholding_pattern
            WHERE symbol = cur.symbol AND period_end < cur.period_end
       )
)
SELECT
    r.symbol,
    r.period_end,
    r.promoter_pct,
    r.promoter_pledged_pct,
    r.promoter_pledged_to_total_pct,
    r.fii_pct,
    r.dii_pct,
    r.mf_pct,
    r.insurance_pct,
    r.public_pct,
    r.individual_pct,
    -- QoQ deltas (in percentage points)
    ROUND((p.cur_promoter - p.prv_promoter)::numeric, 4)        AS promoter_pct_change_qoq,
    ROUND((p.cur_fii      - p.prv_fii)::numeric, 4)             AS fii_pct_change_qoq,
    ROUND((p.cur_dii      - p.prv_dii)::numeric, 4)             AS dii_pct_change_qoq,
    ROUND((p.cur_mf       - p.prv_mf)::numeric, 4)              AS mf_pct_change_qoq,
    ROUND((p.cur_pledge   - p.prv_pledge)::numeric, 4)          AS pledge_pct_change_qoq,
    r.broadcast_at,
    r.source_run_id
  FROM ranked r
  LEFT JOIN prev p
    ON p.symbol = r.symbol AND p.period_end = r.period_end
 WHERE r.rn = 1;


DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable(
            'nidp.shareholding_pattern', 'period_end',
            chunk_time_interval => INTERVAL '1 year',
            if_not_exists => TRUE,
            migrate_data => TRUE
        );
    END IF;
END $$;


INSERT INTO nidp.schema_migrations(filename) VALUES ('025_nidp_shareholding_pattern.sql')
    ON CONFLICT (filename) DO NOTHING;
