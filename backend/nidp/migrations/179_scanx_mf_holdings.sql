-- 179: scheme-level mutual-fund holdings from the ScanX (Dhan) insight pages.
--
-- WHY A THIRD HOLDINGS SOURCE
-- The two we had each miss something structural:
--   * AMC files (nidp.mf_holdings_monthly) are scheme-level but only reach the AMCs whose sites we
--     can scrape — 7 at full depth; HDFC is Akamai-blocked and Mirae is JS-only with one month.
--   * Trendlyne (nidp.trendlyne_ownership) covers the whole universe but is AGGREGATE: it has no
--     scheme or AMC breakdown at all, so it cannot produce breadth.
-- ScanX is the first source that is BOTH scheme-level AND industry-wide: its directory lists
-- 52 AMCs and 1,434 schemes, HDFC and Mirae among them.
--
-- SHAPE
-- Each scheme page server-renders a 12-month series per holding, so ONE request yields the whole
-- backfill window for that scheme (verified: 85 equity holdings x 12 months = 1,020 points,
-- 2025-10..2026-09). The AMC-file route needs one 25MB download per AMC per month for the same
-- thing.
--
-- NO PLAN-VARIANT FAN-OUT
-- Every slug is a '-direct-growth' plan, i.e. one row per FUND, not one per Regular/Direct x
-- Growth/IDCW variant. The 2.5-3.4x inflation that migration 177 had to correct in the AMC-file
-- data does not arise here — which is also why this table must never be summed together with
-- mf_holdings_monthly without de-duplicating that side first.
--
-- KEPT SEPARATE, DELIBERATELY
-- A third-party aggregator's rendering of AMFI/AMC disclosures is not the same artefact as the
-- AMC's own file. Storing it apart lets the two be reconciled (see v_mf_holdings_source_compare)
-- rather than silently averaged, and keeps provenance answerable per row.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.scanx_mf_holdings (
    scheme_slug     TEXT        NOT NULL,       -- ScanX 'seo' slug, the stable per-scheme key
    as_of_month     DATE        NOT NULL,       -- first-of-month
    security_isin   TEXT        NOT NULL,
    symbol          TEXT,                       -- NSE code; empty for debt instruments
    security_name   TEXT,
    shares          NUMERIC,
    weight_pct      NUMERIC(9,4),
    asset_class     TEXT,                       -- Equity | Arbitrage | Certificate of Deposit | ...
    sector          TEXT,
    industry        TEXT,
    amc             TEXT,
    scheme_name     TEXT,
    plan_id         TEXT,
    source          TEXT        NOT NULL DEFAULT 'scanx',
    retrieved_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_run_id   UUID,
    PRIMARY KEY (scheme_slug, as_of_month, security_isin)
);

CREATE INDEX IF NOT EXISTS idx_scanx_mf_isin_month ON nidp.scanx_mf_holdings (security_isin, as_of_month);
CREATE INDEX IF NOT EXISTS idx_scanx_mf_month      ON nidp.scanx_mf_holdings (as_of_month);
CREATE INDEX IF NOT EXISTS idx_scanx_mf_amc        ON nidp.scanx_mf_holdings (amc, as_of_month);

COMMENT ON TABLE nidp.scanx_mf_holdings IS
  'Scheme-level MF holdings from ScanX insight pages: 52 AMCs / 1,434 schemes, 12 months per '
  'request. One row per FUND (all slugs are direct-growth), so no plan-variant fan-out. Kept '
  'apart from nidp.mf_holdings_monthly (AMC files) so the two can be reconciled, not conflated.';

-- Per month and AMC: what each source sees. The AMC-file side is de-duplicated on the same key as
-- migration 177, otherwise its plan-variant fan-out would make the comparison meaningless.
CREATE OR REPLACE VIEW nidp.v_mf_holdings_source_compare AS
WITH amc_file AS (
    SELECT h.as_of_month,
           split_part(h.source, '_', 1)                      AS src_amc,
           count(DISTINCT (h.source, h.security_isin, h.quantity)) AS fund_isin_blocks,
           count(DISTINCT h.security_isin)                   AS isins
      FROM nidp.mf_holdings_monthly h
     WHERE h.security_isin IS NOT NULL
     GROUP BY 1, 2
),
scanx AS (
    SELECT as_of_month, amc,
           count(*)                                          AS rows,
           count(DISTINCT scheme_slug)                       AS schemes,
           count(DISTINCT security_isin)                     AS isins
      FROM nidp.scanx_mf_holdings
     GROUP BY 1, 2
)
SELECT coalesce(s.as_of_month, a.as_of_month) AS as_of_month,
       s.amc                                  AS scanx_amc,
       a.src_amc                               AS amc_file_source,
       s.schemes                               AS scanx_schemes,
       s.isins                                 AS scanx_isins,
       a.isins                                 AS amc_file_isins,
       a.fund_isin_blocks                      AS amc_file_fund_blocks
  FROM scanx s
  FULL OUTER JOIN amc_file a ON a.as_of_month = s.as_of_month AND false;  -- no reliable AMC join key yet

COMMENT ON VIEW nidp.v_mf_holdings_source_compare IS
  'Side-by-side coverage of the two scheme-level holdings sources per month. The AMC join is '
  'deliberately not attempted: ScanX names AMCs in full ("HDFC Mutual Fund") while the file source '
  'encodes them in a source tag ("HDFC_..."), and guessing a mapping would silently mis-pair them. '
  'Compare by month and read the AMC columns side by side until a mapping table exists.';
