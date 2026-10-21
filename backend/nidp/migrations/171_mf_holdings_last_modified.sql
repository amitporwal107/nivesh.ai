-- 171: capture the source file's Last-Modified, and derive published_at from it where credible.
--
-- WHY
-- Migration 169 added published_at but left it NULL everywhere, because nothing captured it and
-- deriving it from as_of_month would have been invention. Without it, no point-in-time backtest of
-- the Smart Money pillar is honest (Gate C), and "do not treat a holding as known before it was
-- published" cannot be enforced.
--
-- WHAT WAS MEASURED (2026-10-22, all 118 stored AMC-month source URLs)
-- Every source returns a Last-Modified header, but the values are a MIXTURE:
--   90 plausible publication dates — lag from month end: min 5, median 9, max 51 days.
--      A median of 9 days matches SEBI's "within 10 days of month end" requirement almost exactly,
--      which is the corroboration that these are real publication timestamps and not noise.
--   14 late re-uploads (icici_pru 8, ppfas 5, uti 1) — the file was replaced months later.
--   13 cache touches equal to our own fetch time (franklin 11 of 13, axis 2 of 4) — the CDN
--      rewrites the header on access, so it carries no information at all.
--    1 unparseable.
--
-- THE RULE, AND WHY IT IS CONSERVATIVE
-- Last-Modified is an UPPER BOUND on publication, never publication itself. published_at is
-- therefore derived only when the header is credible as a publication date for that month:
--
--     month_end <= last_modified <= month_end + 60 days
--
-- Outside that window the header is a re-upload or a cache artefact and published_at stays NULL
-- with provenance 'observed_only' — we keep the weaker true statement instead of a stronger false
-- one. A value before month end is impossible for that month's portfolio and is rejected outright.
--
-- Consumers must still treat published_at as an upper bound: the real release may have been
-- slightly earlier. For point-in-time filtering use
--     coalesce(published_at, source_observed_at)
-- which is correct either way — never as_of_month.
--
-- Idempotent: safe to re-run.

ALTER TABLE nidp.mf_holdings_monthly
    -- The raw header, kept whether or not it was judged credible, so the derivation can be
    -- re-run with a different rule without re-fetching 118 files.
    ADD COLUMN IF NOT EXISTS source_last_modified TIMESTAMPTZ;

ALTER TABLE nidp.mf_holdings_coverage
    ADD COLUMN IF NOT EXISTS source_last_modified TIMESTAMPTZ,
    -- plausible_publication | late_reupload | cache_touch | before_month_end | unparseable | absent
    ADD COLUMN IF NOT EXISTS last_modified_class  TEXT;

CREATE INDEX IF NOT EXISTS idx_mf_hold_published
    ON nidp.mf_holdings_monthly (as_of_month, published_at);

COMMENT ON COLUMN nidp.mf_holdings_monthly.source_last_modified IS
  'Raw Last-Modified of the source file. An UPPER BOUND on publication; for ~24% of AMC-months it '
  'is a re-upload or a CDN cache touch rather than the release, so it is not itself published_at.';
COMMENT ON COLUMN nidp.mf_holdings_coverage.last_modified_class IS
  'How the Last-Modified was judged: plausible_publication (month_end..+60d, used to derive '
  'published_at) | late_reupload | cache_touch | before_month_end | unparseable | absent.';

-- The point-in-time date to use, with its basis stated. Replaces guesswork at the call site.
CREATE OR REPLACE VIEW nidp.v_mf_holdings_asof AS
SELECT scheme_code,
       as_of_month,
       security_isin,
       quantity,
       weight_pct,
       market_value_inr,
       source,
       -- The earliest moment this holding may legitimately be used by a point-in-time consumer.
       coalesce(published_at, source_observed_at)                   AS known_from,
       CASE WHEN published_at IS NOT NULL THEN 'published_at'
            WHEN source_observed_at IS NOT NULL THEN 'observed_only'
            ELSE 'unknown' END                                      AS known_from_basis,
       published_at,
       source_observed_at,
       source_last_modified,
       publication_provenance
  FROM nidp.mf_holdings_monthly;

COMMENT ON VIEW nidp.v_mf_holdings_asof IS
  'Holdings with known_from = coalesce(published_at, source_observed_at): the earliest date a '
  'point-in-time signal may read each holding. Filter on known_from, never on as_of_month. '
  'known_from_basis says whether that came from a real publication timestamp or only from when we '
  'observed the file (which, for backfilled months, is October 2026).';
