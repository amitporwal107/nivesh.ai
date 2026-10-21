-- 169: point-in-time provenance for nidp.mf_holdings_monthly.
--
-- WHY NOW
-- The table recorded only as_of_month (which month the holdings describe) and ingested_at (when
-- we wrote them). Nothing recorded when the AMC PUBLISHED the disclosure, so the rule that makes
-- a holdings backtest honest — "do not treat a holding as known at the reporting-period end if it
-- was published later" — could not be enforced at all. SEBI allows ten days after month end, and
-- the third-party index we discover files through lags further, so the gap between "the month the
-- portfolio describes" and "the date a user could have known it" is routinely 10-40 days. A
-- signal backtested without that gap is reading the future.
--
-- Added while the backfill tooling is fresh, because every further month collected without these
-- columns is another month that can never be made point-in-time correct retroactively.
--
-- WHAT IS AND IS NOT KNOWABLE
-- published_at is NOT being invented for the 1.45M rows already collected. We did not capture it,
-- and deriving it from as_of_month (e.g. "month end + 10 days") would fabricate precision we never
-- had — the exact failure this feature exists to prevent. Existing rows are therefore marked
-- 'observed_only': we know when WE saw the file, not when the AMC released it.
--
-- source_observed_at IS knowable for existing rows and is NOT a fabrication: each row was fetched
-- and written by the same run, so ingested_at is that run's observation time. It is copied across
-- rather than left null, because "we had definitely seen this by <date>" is a true and useful
-- upper bound for point-in-time filtering: a signal may use a holding only after this timestamp.
--
-- Idempotent: safe to re-run.

ALTER TABLE nidp.mf_holdings_monthly
    -- When the AMC published the disclosure. NULL until an adapter captures it (HTTP
    -- Last-Modified, or a publication date on the listing page) — deliberately not derived.
    ADD COLUMN IF NOT EXISTS published_at            TIMESTAMPTZ,
    -- When Nivesh observed the file. A true upper bound on availability: the data existed by then.
    ADD COLUMN IF NOT EXISTS source_observed_at      TIMESTAMPTZ,
    -- Fingerprint of the parsed payload for this (amc, month). Detects a silent re-publication:
    -- same month, different numbers. Hashes the canonicalised PARSED rows, not the raw file, so it
    -- is uniform across adapters whose sources are zip/xlsx/xls/API; a raw-file hash would need
    -- per-adapter threading and is deliberately left as later work.
    ADD COLUMN IF NOT EXISTS source_payload_sha256   TEXT,
    ADD COLUMN IF NOT EXISTS publication_provenance  TEXT;

-- Existing rows: observation time is real, publication time is not known.
UPDATE nidp.mf_holdings_monthly
   SET source_observed_at = coalesce(source_observed_at, ingested_at)
 WHERE source_observed_at IS NULL;

UPDATE nidp.mf_holdings_monthly
   SET publication_provenance = CASE WHEN published_at IS NOT NULL THEN 'published_at_captured'
                                     WHEN source_observed_at IS NOT NULL THEN 'observed_only'
                                     ELSE 'unknown' END
 WHERE publication_provenance IS NULL;

ALTER TABLE nidp.mf_holdings_monthly
    ALTER COLUMN publication_provenance SET DEFAULT 'unknown';

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'mf_holdings_provenance_chk'
                      AND conrelid = 'nidp.mf_holdings_monthly'::regclass) THEN
        ALTER TABLE nidp.mf_holdings_monthly
            ADD CONSTRAINT mf_holdings_provenance_chk CHECK (
                publication_provenance IS NULL OR publication_provenance IN
                    ('published_at_captured', 'observed_only', 'unknown'));
    END IF;
END $$;

-- Point-in-time filtering reads (as_of_month, source_observed_at) together.
CREATE INDEX IF NOT EXISTS idx_mf_hold_observed
    ON nidp.mf_holdings_monthly (as_of_month, source_observed_at);

COMMENT ON COLUMN nidp.mf_holdings_monthly.published_at IS
  'When the AMC published the disclosure. NULL where not captured — never derived from as_of_month.';
COMMENT ON COLUMN nidp.mf_holdings_monthly.source_observed_at IS
  'When Nivesh observed the source file. A true upper bound on availability; use this, not '
  'as_of_month, as the earliest date a point-in-time signal may read the holding.';
COMMENT ON COLUMN nidp.mf_holdings_monthly.publication_provenance IS
  '''published_at_captured'' | ''observed_only'' (we know when we saw it, not when it was '
  'released) | ''unknown''. Everything collected before migration 169 is ''observed_only''.';

-- Which months can and cannot be used point-in-time, and how late the evidence actually arrived.
CREATE OR REPLACE VIEW nidp.v_mf_holdings_provenance AS
SELECT as_of_month,
       count(*)                                                        AS rows,
       count(DISTINCT scheme_code)                                     AS schemes,
       count(*) FILTER (WHERE publication_provenance = 'published_at_captured') AS rows_with_published_at,
       count(*) FILTER (WHERE publication_provenance = 'observed_only')         AS rows_observed_only,
       count(*) FILTER (WHERE publication_provenance = 'unknown'
                           OR publication_provenance IS NULL)                   AS rows_unknown,
       min(source_observed_at)                                         AS first_observed_at,
       max(source_observed_at)                                         AS last_observed_at,
       -- Days from the end of the portfolio month to our first observation. For backfilled months
       -- this is large by construction (we collected them late); it becomes the real publication
       -- lag only for months collected as they are released.
       (min(source_observed_at)::date
         - (as_of_month + INTERVAL '1 month - 1 day')::date)           AS days_month_end_to_observed
  FROM nidp.mf_holdings_monthly
 GROUP BY as_of_month;

COMMENT ON VIEW nidp.v_mf_holdings_provenance IS
  'Per disclosure month: how the availability of the holdings is known. days_month_end_to_observed '
  'is inflated for backfilled months (collected long after release) and is only a true publication '
  'lag for months collected as they appear.';
