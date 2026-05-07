-- 027_nidp_sector_master.sql — NSE listed-equity master + sector classification.
--
-- Source:   NSE archives EQUITY_L.csv (master listing)
-- Cadence:  Weekly (the listing universe drifts slowly — IPOs, delistings)
-- Output:   nidp.sector_master — one row per active NSE-listed symbol
--
-- EQUITY_L.csv has symbol, name, series, listing_date, ISIN, face_value,
-- paid-up value, market lot. It does NOT publish sector/industry directly.
-- We add nullable `sector` / `industry` columns; a follow-up derivation
-- pass populates them from `nidp.index_constituents` membership
-- (e.g. Nifty Bank member → sector='BANKING'). Until that runs, those
-- columns stay NULL — rows are still useful as the canonical symbol
-- master with ISIN, listing date, etc.

SET search_path TO nidp, public;

CREATE TABLE IF NOT EXISTS nidp.sector_master (
    symbol           TEXT PRIMARY KEY,
    company_name     TEXT,
    series           TEXT,                               -- 'EQ', 'BE', 'BZ', etc.
    isin             TEXT,
    listing_date     DATE,
    face_value       NUMERIC(10,4),
    paid_up_value    NUMERIC(10,4),
    market_lot       INTEGER,

    -- Sector / industry — nullable, filled by index-membership derivation
    sector           TEXT,                               -- e.g. 'BANKING', 'IT', 'PHARMA'
    industry         TEXT,                               -- finer-grained
    sector_source    TEXT,                               -- 'INDEX_MEMBERSHIP' | 'NSE_DIRECT' | 'MANUAL'
    sector_resolved_at TIMESTAMPTZ,

    -- Provenance
    source           TEXT NOT NULL DEFAULT 'NSE_EQUITY_MASTER',
    source_run_id    UUID NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sector_master_isin
    ON nidp.sector_master(isin) WHERE isin IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sector_master_sector
    ON nidp.sector_master(sector) WHERE sector IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_sector_master_listing
    ON nidp.sector_master(listing_date DESC);


INSERT INTO nidp.schema_migrations(filename) VALUES ('027_nidp_sector_master.sql')
    ON CONFLICT (filename) DO NOTHING;
