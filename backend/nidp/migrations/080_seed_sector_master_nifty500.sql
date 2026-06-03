-- Migration 080: Seed sector_master.sector from index_constituents.industry (Nifty 500)
-- ─────────────────────────────────────────────────────────────────────────────
-- Problem: 97% of Nifty 500 stocks have NULL sector in sector_master because
--   only BANKING (14) and IT (9) stocks were manually tagged.  This causes the
--   V3 sector-aware scorer to fall through to the DEFAULT profile for 484 stocks,
--   producing generic scores instead of sector-specific ones.
--
-- Fix: Use NSE GICS industry labels from index_constituents to set sector for
--   all Nifty 500 stocks where sector IS NULL.  The values are chosen to match
--   the keyword patterns in nidp.services.sector_scoring.classifier.py.
--
-- sector_master.sector → classifier.py profile:
--   "Finance"                → NBFC   (via "finance" keyword)
--   "Capital Goods"          → CAPGOODS
--   "Healthcare"             → PHARMA
--   "Automobile"             → CYCLICAL
--   "FMCG"                   → FMCG
--   "Information Technology" → IT
--   "Chemicals"              → CYCLICAL
--   "Metals"                 → CYCLICAL
--   "Construction Materials" → CYCLICAL
--   "Realty"                 → CYCLICAL
--   "Construction"           → CAPGOODS
--   "Oil Gas"                → CYCLICAL
--   "Power"                  → CYCLICAL
--   "Consumer Durables"      → FMCG
--   "Textiles"               → CYCLICAL
--   (Telecom, Services, Media, Diversified) → DEFAULT (no profile match)
--
-- NOTE: Rows where sector IS NOT NULL (BANKING, IT) are intentionally skipped.
-- ─────────────────────────────────────────────────────────────────────────────

BEGIN;

-- ── Step 1: Update sector_master for Nifty 500 stocks with null sector ────────
UPDATE nidp.sector_master sm
SET
    sector = CASE ic.industry
        -- Financial: non-bank finance companies (banks already tagged as BANKING)
        WHEN 'Financial Services'                  THEN 'Finance'
        -- Capital Goods
        WHEN 'Capital Goods'                       THEN 'Capital Goods'
        -- Healthcare → PHARMA scorer
        WHEN 'Healthcare'                          THEN 'Healthcare'
        -- Automobile → CYCLICAL scorer
        WHEN 'Automobile and Auto Components'      THEN 'Automobile'
        -- Consumer
        WHEN 'Fast Moving Consumer Goods'          THEN 'FMCG'
        WHEN 'Consumer Durables'                   THEN 'Consumer Durables'
        WHEN 'Consumer Services'                   THEN 'Consumer Services'
        -- IT
        WHEN 'Information Technology'              THEN 'Information Technology'
        -- Cyclicals
        WHEN 'Chemicals'                           THEN 'Chemicals'
        WHEN 'Metals & Mining'                     THEN 'Metals'
        WHEN 'Construction Materials'              THEN 'Construction Materials'
        WHEN 'Construction'                        THEN 'Construction'
        WHEN 'Realty'                              THEN 'Realty'
        WHEN 'Oil Gas & Consumable Fuels'          THEN 'Oil Gas'
        WHEN 'Power'                               THEN 'Power'
        WHEN 'Textiles'                            THEN 'Textiles'
        -- DEFAULT (no specific scoring profile)
        WHEN 'Telecommunication'                   THEN 'Telecommunication'
        WHEN 'Services'                            THEN 'Services'
        WHEN 'Media Entertainment & Publication'   THEN 'Media'
        WHEN 'Diversified'                         THEN 'Diversified'
        ELSE ic.industry  -- pass through any new NSE category as-is
    END,
    industry           = ic.industry,
    sector_source      = 'index_constituents',
    sector_resolved_at = NOW()
FROM (
    SELECT DISTINCT ON (symbol) symbol, industry
    FROM nidp.index_constituents
    WHERE index_name  = 'Nifty 500'
      AND industry    IS NOT NULL
    ORDER BY symbol, as_of_date DESC
) ic
WHERE sm.symbol    = ic.symbol
  AND sm.sector    IS NULL;     -- preserve BANKING / IT already set manually

-- ── Step 2: Immediately propagate sector into stock_features_daily ────────────
-- stock_features_daily is a TimescaleDB hypertable.  Older chunks are compressed
-- and cannot be updated in a single DML without raising a decompression limit
-- error.  We limit to uncompressed chunks only (>= 30 days ago); nightly
-- populate_stock_price_features() will re-join sector_master for older dates
-- if ever needed, and will correctly populate sector for all future dates.
UPDATE nidp.stock_features_daily sfd
SET
    sector   = sm.sector,
    industry = sm.industry
FROM nidp.sector_master sm
WHERE sfd.symbol     = sm.symbol
  AND sfd.sector     IS NULL
  AND sm.sector      IS NOT NULL
  AND sfd.as_of_date >= (CURRENT_DATE - INTERVAL '60 days');

-- ── Step 3: Report what was tagged ───────────────────────────────────────────
DO $$
DECLARE
    tagged_count INT;
    sfd_count    INT;
BEGIN
    SELECT COUNT(*) INTO tagged_count
    FROM nidp.sector_master
    WHERE sector_source = 'index_constituents';

    SELECT COUNT(DISTINCT symbol) INTO sfd_count
    FROM nidp.stock_features_daily
    WHERE sector IS NOT NULL;

    RAISE NOTICE 'sector_master: % rows updated from index_constituents', tagged_count;
    RAISE NOTICE 'stock_features_daily: % distinct symbols now have sector', sfd_count;
END $$;

-- ── Step 3: Normalize legacy sector='IT' → 'Information Technology' ──────────
-- 'IT' as a two-letter string cannot be safely used as a substring keyword in
-- the classifier (it is a substring of 'capital', 'utility', etc.).  Normalize
-- to the full label so the 'information technology' keyword fires correctly.
UPDATE nidp.sector_master
SET sector = 'Information Technology'
WHERE sector = 'IT';

UPDATE nidp.stock_features_daily
SET sector = 'Information Technology'
WHERE sector = 'IT'
  AND as_of_date >= (CURRENT_DATE - INTERVAL '60 days');

COMMIT;

INSERT INTO nidp.schema_migrations (filename)
VALUES ('080_seed_sector_master_nifty500.sql')
ON CONFLICT (filename) DO NOTHING;
