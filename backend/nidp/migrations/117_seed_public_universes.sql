-- Migration 117: Seed public Strategy-Builder universes (sector baskets + Nifty Bank)
-- from REAL constituent data, so the Universe step shows a curated catalog instead
-- of only the Nifty index presets + a user's own custom universes.
--
--   • Sector baskets — one public STOCK universe per sector, membership from
--     nidp.sector_master.sector (the 20-value NSE macro taxonomy seeded by 080).
--     Only sectors with >= 8 members are shipped (thin 3-5 name "baskets" are not
--     meaningful to screen); symbol_count stays visible on every card either way.
--   • Nifty Bank — banks are folded into the 'Finance' sector in the live snapshot,
--     so a dedicated Bank basket is derived from the ingested NSE constituents.
--
-- Every symbol comes from real data (array_agg over the source tables) — nothing is
-- hand-typed. is_public = TRUE so all users see them via GET /api/strategy-builder/universes.
--
-- Idempotent: a partial unique index on system-owned rows lets a re-run upsert
-- membership in place, keeping STABLE ids (saved strategies may reference basket ids).
-- The '__system_sector__' / '__system_index__' owner sentinels also let the
-- /universe-catalog route classify a basket (Sector vs Index Theme) with no schema change.

SET search_path TO public, nidp;

-- Stable-id upsert key for system-seeded baskets (owner_id is TEXT after 115).
CREATE UNIQUE INDEX IF NOT EXISTS ux_user_universes_system
  ON user_universes (owner_id, name)
  WHERE owner_id LIKE '\_\_system%';

-- ── Sector baskets — real membership from nidp.sector_master ──────────────────
INSERT INTO user_universes (owner_id, name, description, asset_class, symbols, is_public)
SELECT '__system_sector__',
       sm.sector,
       'Nifty 500 ' || sm.sector || ' stocks (' ||
         COUNT(DISTINCT sm.symbol) || ' names, from nidp.sector_master).',
       'STOCK',
       array_agg(DISTINCT sm.symbol ORDER BY sm.symbol),
       TRUE
  FROM nidp.sector_master sm
 WHERE sm.sector IS NOT NULL
 GROUP BY sm.sector
HAVING COUNT(DISTINCT sm.symbol) >= 8
ON CONFLICT (owner_id, name) WHERE owner_id LIKE '\_\_system%'
DO UPDATE SET symbols     = EXCLUDED.symbols,
              description = EXCLUDED.description,
              updated_at  = NOW();

-- ── Nifty Bank — real membership from ingested NSE index constituents ─────────
INSERT INTO user_universes (owner_id, name, description, asset_class, symbols, is_public)
SELECT '__system_index__',
       'Nifty Bank',
       'Nifty Bank index constituents (from nidp.index_constituents).',
       'STOCK',
       array_agg(DISTINCT ic.symbol ORDER BY ic.symbol),
       TRUE
  FROM nidp.index_constituents ic
 WHERE ic.index_name = 'Nifty Bank'
   AND ic.as_of_date = (SELECT MAX(as_of_date) FROM nidp.index_constituents
                         WHERE index_name = 'Nifty Bank')
 GROUP BY ic.index_name
HAVING COUNT(DISTINCT ic.symbol) >= 5
ON CONFLICT (owner_id, name) WHERE owner_id LIKE '\_\_system%'
DO UPDATE SET symbols     = EXCLUDED.symbols,
              description = EXCLUDED.description,
              updated_at  = NOW();

INSERT INTO nidp.schema_migrations(filename) VALUES ('117_seed_public_universes.sql')
  ON CONFLICT (filename) DO NOTHING;
