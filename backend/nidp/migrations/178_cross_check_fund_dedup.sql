-- 178: de-duplicate plan variants in the MF ownership cross-check.
--
-- Migration 177 fixed BREADTH (fund counts) but this view sums raw quantity from
-- mf_holdings_monthly, where one fund's holding still appears once per plan-variant scheme_code.
-- So it kept reporting OURS_EXCEEDS_VENDOR for most comparable symbols — correct as a raw-data
-- statement, useless as a coverage check, because the known artefact drowned any real anomaly.
--
-- With variants collapsed, our seven-AMC sum should be a FRACTION of the vendor's all-AMC total.
-- Any symbol still exceeding it is then a genuine anomaly worth investigating (bad ISIN mapping,
-- a stale vendor figure, or a fund we are double-counting for some other reason).
--
-- Dedup key: within (source, security_isin, as_of_month), plan variants carry an identical
-- quantity, so one row per distinct quantity is one fund's decision. Same key as 177.
--
-- Idempotent: safe to re-run.

DROP VIEW IF EXISTS nidp.v_mf_ownership_cross_check;

CREATE VIEW nidp.v_mf_ownership_cross_check AS
WITH latest_month AS (SELECT max(as_of_month) AS m FROM nidp.mf_holdings_monthly),
-- One row per (source, isin, quantity): collapses a fund's plan variants to a single holding.
blocks AS (
    SELECT DISTINCT ON (h.source, h.security_isin, h.quantity)
           h.source, h.security_isin, h.quantity, h.scheme_code
      FROM nidp.mf_holdings_monthly h
     WHERE h.as_of_month = (SELECT m FROM latest_month)
       AND h.security_isin IS NOT NULL AND h.quantity IS NOT NULL
     ORDER BY h.source, h.security_isin, h.quantity, h.scheme_code
),
ours AS (
    SELECT sm.symbol,
           sum(b.quantity)            AS our_mf_shares,
           count(*)                   AS our_funds,
           count(DISTINCT b.source)   AS our_amcs
      FROM blocks b
      JOIN nidp.sector_master sm ON sm.isin = b.security_isin
     GROUP BY sm.symbol
),
theirs AS (
    SELECT symbol, mf_shares_m1, mf_hold_pct
      FROM nidp.trendlyne_ownership
     WHERE as_of_date = (SELECT max(as_of_date) FROM nidp.trendlyne_ownership)
)
SELECT coalesce(o.symbol, t.symbol)                     AS symbol,
       o.our_mf_shares,
       o.our_funds,
       o.our_amcs,
       t.mf_shares_m1                                   AS vendor_mf_shares,
       t.mf_hold_pct                                    AS vendor_mf_pct,
       CASE WHEN t.mf_shares_m1 > 0
            THEN round(100.0 * o.our_mf_shares / t.mf_shares_m1, 1) END
                                                        AS our_share_of_vendor_pct,
       CASE WHEN o.our_mf_shares IS NULL                 THEN 'vendor_only'
            WHEN t.mf_shares_m1 IS NULL OR t.mf_shares_m1 = 0 THEN 'ours_only'
            WHEN o.our_mf_shares > t.mf_shares_m1 * 1.05 THEN 'OURS_EXCEEDS_VENDOR'
            ELSE 'both' END                             AS agreement
  FROM ours o
  FULL OUTER JOIN theirs t ON t.symbol = o.symbol;

COMMENT ON VIEW nidp.v_mf_ownership_cross_check IS
  'Our scheme-level MF share sum (plan variants collapsed, migration 178) vs the vendor''s '
  'all-AMC total. We reach ~7 of ~40 AMCs, so our_share_of_vendor_pct should be well under 100; '
  'OURS_EXCEEDS_VENDOR is now a genuine anomaly rather than the known fan-out artefact.';
