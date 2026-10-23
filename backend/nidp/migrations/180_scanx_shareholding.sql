-- 180: quarterly shareholding history per stock from ScanX company pages.
--
-- WHY
-- nidp.shareholding_pattern (exchange XBRL) is too sparse to difference: 1,316 of 2,137 symbols
-- hold a SINGLE quarter, so no ownership delta exists for most of the universe. The company page
-- carries ~24 quarters per stock of Promoter / FII / DII / Public / Government / Others, which is
-- the only source found with DII at all — the Trendlyne feed has no DII token (it exposes
-- Institutional and FII, and deriving DII as the difference would invent a number no source
-- published).
--
-- THREE CONTROLS, each a column rather than a convention:
--
-- 1. REPORTING PERIOD IS NOT PUBLICATION TIME. The feed's YEAR label (YYYYMM) says which quarter
--    the row describes, never when it became public. A quarter ending 2026-06 is typically filed
--    weeks later. publication_provenance is therefore 'unknown' for every row: retrieved_at is a
--    true upper bound on availability and is the only honest basis for point-in-time use. Nothing
--    is derived from the period.
--
-- 2. CLASSIFICATION BREAK. FII is not comparable across the whole series. RELIANCE reads
--    ...|22.14|22.60|0.07|0.07|... while OTHERS jumps 2.15 -> 24.61 at exactly the same index:
--    FII was reported INSIDE Others before that quarter. Treating that as a 22-point collapse in
--    foreign ownership would be a fabricated signal of the worst kind. fii_in_others marks the
--    rows on the old basis; a delta spanning rows with different flags must be rejected, not
--    adjusted silently. The break is DETECTED per stock, not hardcoded to a date, because
--    different names may carry it at different quarters.
--
-- 3. INGESTION VERSION. ingest_version records the parser that wrote the row, so a field added
--    later is never assumed present on rows written earlier.
--
-- Kept apart from nidp.shareholding_pattern for the usual reason: a vendor's rendering of a
-- filing is not the filing. Reconcile, do not merge.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.scanx_shareholding (
    company_slug    TEXT        NOT NULL,       -- the key actually fetched
    period          DATE        NOT NULL,       -- reporting quarter, first-of-month from YYYYMM
    symbol          TEXT,
    promoter_pct    NUMERIC(9,4),
    fii_pct         NUMERIC(9,4),
    dii_pct         NUMERIC(9,4),
    public_pct      NUMERIC(9,4),
    government_pct  NUMERIC(9,4),
    others_pct      NUMERIC(9,4),
    no_of_shareholders BIGINT,

    -- Control 2: TRUE where this row predates the FII/Others reclassification for this stock, so
    -- its fii_pct and others_pct are on the OLD basis and are not comparable with later rows.
    fii_in_others   BOOLEAN     NOT NULL DEFAULT false,

    -- Control 1: we know when we saw it, never when it was published.
    publication_provenance TEXT NOT NULL DEFAULT 'unknown',
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Control 3
    ingest_version  TEXT        NOT NULL,
    slug_source     TEXT,                       -- 'harvested' | 'derived'
    source          TEXT        NOT NULL DEFAULT 'scanx',
    source_run_id   UUID,
    PRIMARY KEY (company_slug, period),
    CONSTRAINT scanx_sh_pub_chk CHECK (publication_provenance IN ('unknown', 'captured'))
);

CREATE INDEX IF NOT EXISTS idx_scanx_sh_symbol ON nidp.scanx_shareholding (symbol, period DESC);
CREATE INDEX IF NOT EXISTS idx_scanx_sh_period ON nidp.scanx_shareholding (period);

COMMENT ON COLUMN nidp.scanx_shareholding.fii_in_others IS
  'TRUE where FII was still reported inside Others for this stock, so fii_pct/others_pct are on '
  'the old basis. A quarter-on-quarter delta spanning rows whose flags differ is NOT comparable '
  'and must be excluded, never adjusted silently.';
COMMENT ON COLUMN nidp.scanx_shareholding.publication_provenance IS
  '''unknown'' everywhere: the feed gives a reporting period, not a filing date. Use retrieved_at '
  'as the availability upper bound for point-in-time work.';

-- Comparable quarter-on-quarter ownership deltas: pairs are emitted ONLY where both rows sit on
-- the same classification basis.
CREATE OR REPLACE VIEW nidp.v_scanx_ownership_delta AS
WITH s AS (
    SELECT company_slug, symbol, period, promoter_pct, fii_pct, dii_pct, public_pct,
           fii_in_others, retrieved_at,
           lag(period)        OVER w AS prev_period,
           lag(promoter_pct)  OVER w AS prev_promoter,
           lag(fii_pct)       OVER w AS prev_fii,
           lag(dii_pct)       OVER w AS prev_dii,
           lag(fii_in_others) OVER w AS prev_fii_in_others
      FROM nidp.scanx_shareholding
    WINDOW w AS (PARTITION BY company_slug ORDER BY period)
)
SELECT company_slug, symbol, period, prev_period,
       promoter_pct, dii_pct, fii_pct,
       round(promoter_pct - prev_promoter, 4) AS promoter_chg_pp,
       round(dii_pct - prev_dii, 4)           AS dii_chg_pp,
       -- Only comparable when both sides share the classification basis.
       CASE WHEN fii_in_others IS NOT DISTINCT FROM prev_fii_in_others
            THEN round(fii_pct - prev_fii, 4) END AS fii_chg_pp,
       (fii_in_others IS DISTINCT FROM prev_fii_in_others) AS fii_spans_classification_break,
       retrieved_at                           AS known_by
  FROM s
 WHERE prev_period IS NOT NULL;

COMMENT ON VIEW nidp.v_scanx_ownership_delta IS
  'Quarter-on-quarter ownership change. fii_chg_pp is NULL where the pair spans the FII/Others '
  'reclassification — the break is reported, not bridged. known_by is when we observed the data, '
  'which is the only availability bound the feed supports.';
