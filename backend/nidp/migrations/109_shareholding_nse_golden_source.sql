-- 109_shareholding_nse_golden_source.sql
-- Shareholding has ONE golden source: the NSE regulatory filing (source='NSE_SHP').
-- The SD-07 historical backfill also wrote Screener shareholding (source='screener_in'),
-- which (a) duplicated NSE on the same (symbol, period) and (b) disagreed with NSE on most
-- overlaps (only 178 of 1,323 agreed within 0.5pp). Drop the non-golden source. The backfill
-- code no longer writes it. NOTE: QoQ depth must now come from backfilling NSE *history*
-- (the nse_shareholding ingester currently stores only the latest filing per symbol).
DELETE FROM nidp.shareholding_pattern WHERE source ILIKE '%screener%';

INSERT INTO nidp.schema_migrations (filename)
VALUES ('109_shareholding_nse_golden_source.sql')
ON CONFLICT (filename) DO NOTHING;
