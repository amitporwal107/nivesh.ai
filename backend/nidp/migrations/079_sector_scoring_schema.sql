-- Migration 079: Sector-aware scoring columns on v3_stock_scores_daily
-- ─────────────────────────────────────────────────────────────────────────────
-- Extends the existing v3_stock_scores_daily table with the new columns
-- described in the NIDP Sector-Aware Stock Quality Scoring Framework PRD.
--
-- Existing quality_score / health_score columns are PRESERVED for
-- backward compatibility. New columns are populated by the sector-aware
-- scoring path in v3_scores_engine (v2+).
--
-- sector_profile values: BANK | NBFC | CYCLICAL | IT | FMCG | PHARMA |
--                        CAPGOODS | DEFAULT
-- band values: STRONG_BUY | BUY | HOLD | REDUCE | AVOID
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE nidp.v3_stock_scores_daily
  ADD COLUMN IF NOT EXISTS sector_profile       VARCHAR(16),
  ADD COLUMN IF NOT EXISTS fundamental_score    NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS technical_score      NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS cycle_position_score NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS event_overlay        NUMERIC(5,2)  DEFAULT 0,
  ADD COLUMN IF NOT EXISTS red_flag_penalty     NUMERIC(5,2)  DEFAULT 0,
  ADD COLUMN IF NOT EXISTS sub_scores_jsonb     JSONB,
  ADD COLUMN IF NOT EXISTS final_score          NUMERIC(5,2),
  ADD COLUMN IF NOT EXISTS band                 VARCHAR(16);

-- Index for band-based filtering (copilot recommendation queries)
CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_band
    ON nidp.v3_stock_scores_daily (band, as_of_date DESC)
    WHERE band IS NOT NULL;

-- Index for sector_profile lookups
CREATE INDEX IF NOT EXISTS idx_v3_stock_scores_profile
    ON nidp.v3_stock_scores_daily (sector_profile, as_of_date DESC)
    WHERE sector_profile IS NOT NULL;

COMMENT ON COLUMN nidp.v3_stock_scores_daily.sector_profile IS
    'Scoring framework applied: BANK|NBFC|CYCLICAL|IT|FMCG|PHARMA|CAPGOODS|DEFAULT';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.fundamental_score IS
    'Sector-weighted fundamental sub-score (0–100)';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.technical_score IS
    'Cross-sector technical sub-score (0–100)';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.cycle_position_score IS
    'Cycle position sub-score (0–100); populated for CYCLICAL only';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.event_overlay IS
    'Net event boost/penalty from corporate_event_signals (time-decayed)';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.red_flag_penalty IS
    'Hard penalty subtracted from total (RBI PCA, auditor resignation, etc.)';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.sub_scores_jsonb IS
    'Full pillar breakdown for copilot explainability';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.final_score IS
    'Composite sector-aware score: fund×w + tech×w + cycle×w + overlay - penalty';
COMMENT ON COLUMN nidp.v3_stock_scores_daily.band IS
    'Signal band: STRONG_BUY|BUY|HOLD|REDUCE|AVOID (sector-relative)';

-- ── Primitive coverage / feed-gap view ───────────────────────────────────────
-- The engine writes a sentinel row (symbol='__coverage__') with the full
-- aggregate feed-gap report in sub_scores_jsonb.  This view surfaces it in
-- an easy-to-query form.
--
-- Usage:
--   SELECT * FROM nidp.v_scoring_feed_gaps ORDER BY missing_pct DESC;
-- ─────────────────────────────────────────────────────────────────────────────
CREATE OR REPLACE VIEW nidp.v_scoring_feed_gaps AS
SELECT
    s.as_of_date,
    field_entry.key                                         AS primitive_name,
    (field_entry.value ->> 'feed')                         AS feed,
    (field_entry.value ->> 'missing_count')::INT           AS missing_count,
    (field_entry.value ->> 'missing_pct')::NUMERIC(6,2)    AS missing_pct,
    (s.sub_scores_jsonb ->> 'total_stocks')::INT           AS total_stocks
FROM nidp.v3_stock_scores_daily s,
     jsonb_each(s.sub_scores_jsonb -> 'by_field') AS field_entry
WHERE s.symbol = '__coverage__'
  AND s.as_of_date = (
      SELECT MAX(as_of_date)
        FROM nidp.v3_stock_scores_daily
       WHERE symbol = '__coverage__'
  )
ORDER BY missing_pct DESC, primitive_name;

COMMENT ON VIEW nidp.v_scoring_feed_gaps IS
    'Latest scoring run: per-primitive coverage gaps with owning feed. '
    'Use to identify which ingesters to fix when primitives are missing.';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('079_sector_scoring_schema.sql')
ON CONFLICT (filename) DO NOTHING;
