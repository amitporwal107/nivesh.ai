-- 112_normalize_period_type_case.sql
-- Normalize nse_financials_quarterly.period_type to a single canonical case (lowercase).
-- Two writers produced mixed case ('QUARTERLY' from XBRL, 'quarterly' from Screener), which
-- the DQ canonical_casing check flags and which forced every reader to be case-insensitive.
--
-- SAFE because the live readers are already case-insensitive for quarterly:
--   - populate_stock_features_v3 uses UPPER(period_type) (migration 106)
--   - v_stock_fundamentals_latest ILIKEs 'QUARTERLY' and exact-matches lowercase 'annual'
-- Lowercasing keeps 'annual' lowercase (the view's exact leg) and turns 'QUARTERLY' ->
-- 'quarterly' (matched by ILIKE / UPPER). The writer (nse_financials/writer.py) now lowercases
-- on insert, so this is a one-time backfill. PREREQUISITE: migration 106 must be applied.
-- Idempotent.

UPDATE nidp.nse_financials_quarterly
   SET period_type = lower(period_type)
 WHERE period_type <> lower(period_type);

INSERT INTO nidp.schema_migrations (filename)
VALUES ('112_normalize_period_type_case.sql')
ON CONFLICT (filename) DO NOTHING;
