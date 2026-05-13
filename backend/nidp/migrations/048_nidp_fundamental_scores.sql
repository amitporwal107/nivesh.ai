-- 048_nidp_fundamental_scores.sql
-- Adds Piotroski F-Score and Altman Z-Score columns to stock_features_daily,
-- plus a sector_median_pe view for valuation comparison (TASK-023/024).
--
-- Piotroski F-Score: 0–9, where 8–9=strong, 6–7=good, 3–5=average, 0–2=weak.
-- Altman Z-Score (modified for Indian XBRL data, no total-assets column):
--   Z > 2.99 = safe, 1.81–2.99 = grey, < 1.81 = distress.

SET search_path TO nidp, public;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'nidp' AND table_name = 'stock_features_daily'
    ) THEN
        RAISE NOTICE '048 deferred: stock_features_daily not yet present.';
        RETURN;
    END IF;

    EXECUTE $ddl$
        ALTER TABLE nidp.stock_features_daily
            ADD COLUMN IF NOT EXISTS piotroski_score    SMALLINT,        -- 0..9
            ADD COLUMN IF NOT EXISTS piotroski_signals  TEXT[],          -- which of 9 fired
            ADD COLUMN IF NOT EXISTS altman_z_score     NUMERIC(10,4),   -- modified Z
            ADD COLUMN IF NOT EXISTS valuation_signal   TEXT,            -- undervalued/fairly_valued/overvalued
            ADD COLUMN IF NOT EXISTS sector_median_pe   NUMERIC(10,4)    -- peer median PE for context
    $ddl$;

    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_features_piotroski
            ON nidp.stock_features_daily(piotroski_score DESC, as_of_date DESC)
            WHERE piotroski_score IS NOT NULL
    $ddl$;
    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_features_altman
            ON nidp.stock_features_daily(altman_z_score, as_of_date DESC)
            WHERE altman_z_score IS NOT NULL
    $ddl$;
    EXECUTE $ddl$
        CREATE INDEX IF NOT EXISTS idx_features_valuation_signal
            ON nidp.stock_features_daily(valuation_signal, as_of_date DESC)
            WHERE valuation_signal IS NOT NULL
    $ddl$;
END $$;


-- ── Sector median PE view ────────────────────────────────────────────
-- Used by the valuation signal computation and peer comparison API.
-- Refreshed daily by the fundamental engine after upsert completes.
CREATE OR REPLACE VIEW nidp.v_sector_median_pe AS
SELECT
    sector,
    as_of_date,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pe_ttm) AS median_pe,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY pb)     AS median_pb,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY roe_pct) AS median_roe,
    COUNT(*) AS stock_count
  FROM nidp.stock_features_daily
 WHERE sector IS NOT NULL
   AND pe_ttm BETWEEN 0 AND 200       -- exclude outliers
   AND pe_ttm IS NOT NULL
 GROUP BY sector, as_of_date;


INSERT INTO nidp.schema_migrations(filename) VALUES ('048_nidp_fundamental_scores.sql')
    ON CONFLICT (filename) DO NOTHING;
