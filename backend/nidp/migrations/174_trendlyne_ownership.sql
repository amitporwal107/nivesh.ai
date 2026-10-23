-- 174: aggregate institutional ownership per stock from the Trendlyne MCP feed.
--
-- WHY A SEPARATE TABLE, NOT shareholding_pattern
-- nidp.shareholding_pattern holds NSE/BSE XBRL FILINGS. This feed is a vendor's aggregation with
-- its own cadence, revision behaviour and definitions. The source requirement is explicit about
-- not merging incompatible sources ("preserve source labels and definitions"), and a disagreement
-- between the two is diagnostic information we want to keep, not average away. They are joined at
-- read time, never written into one row.
--
-- WHAT THIS FILLS
-- Scheme-level disclosures reach only the AMCs whose files we can fetch (7 at full depth; HDFC and
-- Mirae unreachable), so breadth is known for a subset of the market. This feed is the AGGREGATE
-- across ALL mutual funds for essentially the whole universe, which is the complement:
--   * scheme-level (mf_holdings_deltas) -> breadth, concentration, which AMCs
--   * aggregate (this table)            -> total MF ownership and its change, no survivor AMCs
-- It also replaces a genuine hole: nidp.stock_features_daily.fii_pct_change_qoq was populated for
-- only 5.9% of the scored universe.
--
-- WHAT IT CANNOT DO
-- No per-scheme or per-AMC breakdown exists in this feed (verified against the live API), so it
-- cannot produce accumulation BREADTH or the independent-holder count. It must not be used as a
-- substitute for the scheme-level layer, only alongside it.
--
-- mf_shares_m1..m4 are SHARE COUNTS, which is what a share-count change needs; the *_pct columns
-- are the vendor's own percentage changes and are stored as given rather than recomputed.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS nidp.trendlyne_ownership (
    symbol              TEXT        NOT NULL,   -- NSE code as the vendor returns it
    as_of_date          DATE        NOT NULL,   -- the vendor's own data date, not our fetch date
    stock_id            INTEGER,                -- vendor id, kept so a rename can be traced
    isin                TEXT,

    -- Mutual funds (aggregate across all schemes and AMCs)
    mf_hold_pct         NUMERIC(9,4),           -- current quarter %
    mf_shares_m1        NUMERIC,                -- total shares, previous month
    mf_shares_m2        NUMERIC,
    mf_shares_m3        NUMERIC,
    mf_shares_m4        NUMERIC,
    mf_chg_1m_pct       NUMERIC(9,4),
    mf_chg_2m_pct       NUMERIC(9,4),
    mf_chg_3m_pct       NUMERIC(9,4),
    mf_chg_qoq_pct      NUMERIC(9,4),
    mf_chg_1y_pct       NUMERIC(9,4),
    mf_chg_2y_pct       NUMERIC(9,4),

    -- Other disclosed categories. DII is deliberately NOT stored: the feed exposes no DII token,
    -- and deriving it as institutional - FII would invent a number the source never published.
    fii_hold_pct        NUMERIC(9,4),
    fii_chg_qoq_pct     NUMERIC(9,4),
    insti_hold_pct      NUMERIC(9,4),
    insti_chg_qoq_pct   NUMERIC(9,4),
    promoter_pct        NUMERIC(9,4),

    source              TEXT        NOT NULL DEFAULT 'trendlyne_mcp',
    retrieved_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_run_id       UUID,

    PRIMARY KEY (symbol, as_of_date)
);

CREATE INDEX IF NOT EXISTS idx_tl_own_date ON nidp.trendlyne_ownership (as_of_date);
CREATE INDEX IF NOT EXISTS idx_tl_own_mfchg
    ON nidp.trendlyne_ownership (as_of_date, mf_chg_1m_pct DESC NULLS LAST);

COMMENT ON TABLE nidp.trendlyne_ownership IS
  'Aggregate institutional ownership per stock from the Trendlyne MCP feed. Complements '
  'nidp.mf_holdings_deltas (scheme-level breadth for reachable AMCs) with all-AMC aggregate '
  'levels and changes. Kept separate from nidp.shareholding_pattern (exchange XBRL filings) so '
  'the two sources can be compared rather than conflated. No per-scheme breakdown exists here.';
COMMENT ON COLUMN nidp.trendlyne_ownership.as_of_date IS
  'The data date the vendor reports for the row, not when we fetched it (see retrieved_at).';

-- Cross-source agreement on aggregate MF ownership. Two independent derivations of the same
-- quantity: the vendor''s all-AMC figure, and what our scheme-level holdings sum to (which covers
-- only reachable AMCs and so should be LOWER). A scheme sum exceeding the vendor total would mean
-- double-counting somewhere in our own layer.
CREATE OR REPLACE VIEW nidp.v_mf_ownership_cross_check AS
WITH latest_month AS (
    SELECT max(as_of_month) AS m FROM nidp.mf_holdings_monthly
),
ours AS (
    SELECT sm.symbol,
           sum(h.quantity)               AS our_mf_shares,
           count(DISTINCT h.scheme_code)  AS our_schemes
      FROM nidp.mf_holdings_monthly h
      JOIN nidp.sector_master sm ON sm.isin = h.security_isin
     WHERE h.as_of_month = (SELECT m FROM latest_month)
       AND h.security_isin IS NOT NULL
     GROUP BY sm.symbol
),
theirs AS (
    SELECT symbol, mf_shares_m1, mf_hold_pct, as_of_date
      FROM nidp.trendlyne_ownership t
     WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.trendlyne_ownership)
)
SELECT coalesce(o.symbol, t.symbol)                     AS symbol,
       o.our_mf_shares,
       o.our_schemes,
       t.mf_shares_m1                                   AS vendor_mf_shares,
       t.mf_hold_pct                                    AS vendor_mf_pct,
       CASE WHEN t.mf_shares_m1 > 0
            THEN round(100.0 * o.our_mf_shares / t.mf_shares_m1, 1) END
                                                        AS our_share_of_vendor_pct,
       CASE WHEN o.our_mf_shares IS NULL     THEN 'vendor_only'
            WHEN t.mf_shares_m1 IS NULL      THEN 'ours_only'
            WHEN o.our_mf_shares > t.mf_shares_m1 * 1.05 THEN 'OURS_EXCEEDS_VENDOR'
            ELSE 'both' END                             AS agreement
  FROM ours o
  FULL OUTER JOIN theirs t ON t.symbol = o.symbol;

COMMENT ON VIEW nidp.v_mf_ownership_cross_check IS
  'Our scheme-level MF share sum vs the vendor''s all-AMC total, latest period each. Ours should '
  'be a FRACTION of theirs (we reach 7 AMCs of ~40); agreement = OURS_EXCEEDS_VENDOR flags a '
  'double-count or a bad ISIN mapping on our side and should be empty.';
