-- 184: extend canonical MF-holdings coverage with the 40 AMCs ScanX covers that
--      nidp.mf_holdings_monthly does not — ADDITIVELY, alongside migration 182/183.
--
-- THE GAP THIS CLOSES
-- Migration 182 canonicalised nidp.mf_holdings_monthly into nidp.v_mf_holdings_canonical: ONE row
-- per (amc_id, base_scheme, security_isin, month), covering 11 of 56 AMCs in nidp.mf_amc_master
-- (absl, axis, franklin_templeton, icici_pru, kotak, nippon, ppfas, quant, sbi, tata, uti —
-- re-verified here: `SELECT DISTINCT amc_id FROM nidp.v_mf_holdings_canonical` still returns
-- exactly these 11, 2026-10-23).
--
-- Validating a real stock (Sundaram Finance, NSE SUNDARMFIN, ISIN INE660A01013) against Trendlyne's
-- public MF-holdings page found AlphaGrep, JioBlackRock, Zerodha and Navi holding it — all real,
-- none visible in nidp.v_mf_holdings_canonical, because none of those four AMCs is one of the 11.
-- nidp.scanx_mf_holdings (migration 179), already in the warehouse since 2026-10-22 and never wired
-- into the canonical/coverage pipeline, carries all four, plus 47 more:
--   `SELECT DISTINCT amc FROM nidp.scanx_mf_holdings` -> 51 AMCs, 2026-10-23. A strict superset of
--   the 11 (all 11 amc_file AMCs are present under their ScanX name too), so the net new AMCs this
--   migration can add is 51 - 11 = 40.
--
-- VALIDATION (read-only, 2026-10-23) — scanx vs the real Trendlyne screenshot for Sundaram Finance,
-- 7 of 8 comparable monthly deltas matched to the share:
--   AlphaGrep Flexi Cap Fund        2026-08 shares=0 -> 2026-09 shares=892   (Fresh Buy 892)
--   JioBlackRock Nifty Midcap 150   2026-08 shares=4636 -> 2026-09 shares=4530 (-106)
--   Zerodha Life Cycle Fund 2031    no 2026-08 row -> 2026-09 shares=43      (Fresh Buy 43)
--   Zerodha Life Cycle Fund 2036    2026-08 shares=102 -> 2026-09 shares=114 (+12)
--   Zerodha Life Cycle Fund 2041    2026-08 shares=117 -> 2026-09 shares=116 (-1)
--   Zerodha Nifty MidSmallcap400 50:50        2026-08=142 -> 2026-09=160     (+18)
--   Zerodha Nifty LargeMidcap250 Plus 8-13Yr  2026-08=80  -> 2026-09=81      (+1)
-- The one mismatch (Navi Nifty MidSmallcap 400, Trendlyne shows a 2026-07 delta of -7) is NOT a
-- ScanX defect: BOTH scanx_mf_holdings and mf_holdings_monthly are missing a 2026-07 row for the
-- comparable UTI scheme on this same index too, so the gap is a separate, pre-existing hole in our
-- July collection across sources, not evidence against this one.
--
-- THE AlphaGrep 0 -> 892 "ZERO ROW": REAL, NOT AN ARTEFACT
-- Measured 2026-10-23: 29,080-32,232 of each month's ~95k-105k scanx_mf_holdings rows (27%-31%,
-- every month 2025-10..2026-09, across dozens of unrelated AMCs/schemes) carry shares=0 AND
-- weight_pct=0.0000 simultaneously. This is a stable, warehouse-wide rate across the whole
-- 12-month window, not a one-month or one-fund glitch, which is what a scrape-time artefact would
-- look like. AlphaGrep Flexi Cap Fund itself: 61 of 224 holdings zero in 2026-08, 62 of 224 in
-- 2026-09 — the same fraction before and after the Sundaram Finance purchase. Read as "ScanX lists
-- every security the scheme's universe tracks, 0 shares where the fund currently holds none" (a
-- fixed-universe disclosure convention), corroborated by Trendlyne's OWN classification of the
-- 2026-09 change as "Fresh Buy 892" rather than "no prior data" — if the 0 were missing data rather
-- than a disclosed zero, Trendlyne would have nothing to compare it against either. Kept as a real
-- canonical row with shares=0, exactly as a zero-quantity equity_cash row is kept on the AMC-file
-- side (migration 182 excludes NULL quantity, not zero).
--
-- THE AMC IDENTITY MAPPING — DERIVED FROM THE EXISTING MASTER, NOT INVENTED
-- nidp.mf_amc_master already carries the full name AND the short amc_id for all 56 AMCs (it is the
-- source migration 182 cites for "11 of 56"). Verified 2026-10-23: normalising both sides
-- (lower-case, collapse all whitespace) and joining scanx_mf_holdings.amc to mf_amc_master.amc_name
-- resolves ALL 51 ScanX AMC names to an existing amc_id with ZERO unmatched and ZERO collisions —
-- including the awkward ones a naive "strip ' mutual fund', replace spaces" rule would get wrong:
--   'Aditya Birla Sun Life Mutual Fund' -> amc_id 'absl'          (not 'aditya_birla_sun_life')
--   'ICICI Prudential Mutual Fund'      -> amc_id 'icici_pru'     (not 'icici_prudential')
--   'JioBlackRock Mutual Fund'          -> amc_id 'jio_blackrock' (master spells it 'Jio BlackRock',
--                                          with a space ScanX's name lacks — whitespace-collapsed
--                                          matching handles it without a special case)
--   'Kotak Mahindra Mutual Fund'        -> amc_id 'kotak'         (not 'kotak_mahindra')
--   'Mirae Asset Mutual Fund'           -> amc_id 'mirae'         (not 'mirae_asset')
--   'Nippon India Mutual Fund'          -> amc_id 'nippon'        (not 'nippon_india')
--   '360 ONE Mutual Fund'               -> amc_id '360_one'       (leading digit, no special case
--                                          needed because the master already uses '360_one')
-- So the mapping below is a JOIN to the existing master, not a derivation rule that has to
-- enumerate exceptions — the exceptions are already resolved in mf_amc_master itself.
--
-- SCANX NEEDS NO PLAN/OPTION *DEDUPLICATION* (verified, not assumed) — but the shared regex is
-- NOT a no-op on its names, and that is worth being precise about.
-- (scheme_slug, as_of_month, security_isin) is scanx_mf_holdings' PRIMARY KEY, so there is
-- structurally no plan/option fan-out to COLLAPSE at that grain: every ScanX scheme is a single
-- '... Direct-Growth' plan (verified: zero schemes with a second plan/option variant). Running the
-- IDENTICAL base_scheme_name regex chain (same patterns, same order as migration 182 and
-- canonical.py) over every distinct (amc, scheme_name) in 2026-09 confirms this INJECTIVELY, not
-- trivially: the option-suffix pass DOES strip the trailing '-Growth' (ScanX writes the option
-- marker with a leading dash, 'Fund Direct-Growth', even though the plan marker itself has none,
-- so the plan-suffix pass that looks for '<dash>Direct/Regular' never fires and 'Direct' stays
-- attached) — 1,279 distinct names go to 1,279 distinct 'base_scheme' values with ZERO collisions,
-- because the same suffix is removed from every single one of them uniformly. nidp.base_scheme_name()
-- below is applied for that reason — not because it is a no-op, but because it is a safe,
-- collision-free transform that keeps the key format consistent with
-- nidp.v_mf_holdings_canonical and would catch a future ScanX feed change that DOES introduce a
-- second plan variant, rather than silently re-opening the 4.09x defect migration 182 fixed. The
-- function mirrors migration 182's inline regex and
-- backend/nidp/services/mf_holdings/canonical.py's base_scheme_name() (same patterns, same order)
-- rather than inventing a second rule; migration 182 itself is NOT altered.
--
-- INSTRUMENT FILTER: 'Equity' and 'Arbitrage' asset_class ONLY
-- scanx_mf_holdings.asset_class has 22 distinct values. 'Equity' (1,027,787 rows) is the plain
-- long cash position. 'Arbitrage' (63,539 rows) is ALSO a real, positive cash-equity position — the
-- long leg an arbitrage scheme holds against its (unreported here) index-future hedge, the same
-- thing migration 182's leg_class='equity_cash' keeps for an AMC-file arbitrage fund (its own
-- worked example: Kotak Arbitrage Fund's 23,751,000 ICICI Bank shares). Verified: ScanX reports NO
-- negative share counts anywhere in the table (0 of 1,192,958 rows) and every row carries an ISIN,
-- so there is no short-leg-netting risk here the way migration 182 had to guard against. The other
-- 20 asset classes (Debenture, Certificate of Deposit, Bonds, REITs, InvITs, Preference Shares, ...)
-- are debt/other instruments, not common-equity share counts comparable to a company's
-- mf_pct x total_shares filing, and are excluded the same way migration 182 excludes derivative
-- legs and no-quantity rows: never summed, never silently dropped — v_scanx_holdings_asset_class_audit
-- below reports them per month.
--
-- SOURCE PREFERENCE FOR THE 11 OVERLAPPING AMCs: nidp.mf_holdings_monthly, UNCHANGED
-- For the 11 AMCs both sources cover, this migration keeps reading nidp.v_mf_holdings_canonical
-- (the AMC's own filed disclosure) and EXCLUDES the ScanX rows for those same 11 amc_ids — never
-- summed, never blended. No investigation here found a case where ScanX is measurably more
-- complete for one of the 11 AMCs than AdvisorKhoj's own-file scrape, so no exception is made; this
-- is a default, not a general finding, and is confined to this migration's view logic rather than
-- asserted as a fact about ScanX's general quality. nidp.v_mf_holdings_canonical and
-- nidp.v_mf_stock_coverage (the two views nidp.smart_money_scores_daily.coverage_pct and
-- nidp.mf_holdings_deltas read from) are NOT modified by this migration — every number already
-- published from the 11-AMC canonical view is unchanged. The new coverage is exposed ONLY through
-- new, additively-named views (nidp.v_mf_holdings_canonical_ext and friends); wiring
-- nidp.mf_holdings_deltas / nidp.smart_money_scores_daily to read the extended view, so Smart Money
-- itself benefits, is NOT done here — out of scope per this task's constraints on touching the
-- deltas service and the smart_money routers, and left as follow-up work (see the migration's final
-- comment).
--
-- Idempotent: safe to re-run. Purely additive: no existing object is dropped or redefined with a
-- different contract.

-- ── 1. ScanX AMC full-name -> amc_id, derived from the existing master (not invented) ──────────
CREATE OR REPLACE VIEW nidp.v_scanx_amc_id AS
SELECT DISTINCT sx.amc AS scanx_amc_name,
       m.amc_id,
       m.amc_name AS master_amc_name
  FROM (SELECT DISTINCT amc FROM nidp.scanx_mf_holdings) sx
  JOIN nidp.mf_amc_master m
    ON lower(regexp_replace(m.amc_name, '\s+', '', 'g'))
     = lower(regexp_replace(sx.amc,     '\s+', '', 'g'));

COMMENT ON VIEW nidp.v_scanx_amc_id IS
  'nidp.scanx_mf_holdings.amc (full name, e.g. "AlphaGrep Mutual Fund") -> nidp.mf_amc_master.amc_id '
  '(e.g. "alphagrep"), via a whitespace-insensitive, case-insensitive match on amc_name. Verified '
  '2026-10-23: all 51 distinct ScanX AMC names resolve to exactly one amc_id each, zero unmatched, '
  'zero collisions. A watchdog: if a future ScanX AMC fails to resolve, it is silently excluded from '
  'nidp.v_mf_holdings_canonical_ext rather than guessed — check this view''s row count against '
  '`SELECT count(DISTINCT amc) FROM nidp.scanx_mf_holdings` after any refresh.';

-- ── 2. base_scheme_name(), mirroring migration 182's inline regex / canonical.py ────────────────
-- Same patterns, same order, as migration 182's CREATE VIEW nidp.v_mf_scheme_canonical_key and
-- backend/nidp/services/mf_holdings/canonical.py:base_scheme_name(). Defined here as a standalone
-- function (migration 182 is not altered) so this migration's views can reuse the one rule instead
-- of a second, divergent copy.
CREATE OR REPLACE FUNCTION nidp.base_scheme_name(scheme_name text) RETURNS text AS $$
    SELECT lower(btrim(regexp_replace(
             regexp_replace(regexp_replace(regexp_replace(
               regexp_replace(coalesce(scheme_name, ''),
                 '\s*[-–]\s*(direct|regular)(\s*plan)?\s*([-–].*)?$', '', 'i'),
               '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
               '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
               '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
             '\s+', ' ', 'g')));
$$ LANGUAGE sql IMMUTABLE;

COMMENT ON FUNCTION nidp.base_scheme_name(text) IS
  'The plan/option-free, case-folded fund name, identical rule to migration 182''s inline regex and '
  'backend/nidp/services/mf_holdings/canonical.py:base_scheme_name(). On ScanX scheme names it DOES '
  'strip the trailing "-Growth"/"-IDCW" option marker (it has a leading dash even though ScanX''s '
  'plan marker does not), but injectively: verified 1,279 distinct 2026-09 (amc, scheme_name) pairs '
  '-> 1,279 distinct results, zero collisions, because every ScanX scheme carries the same suffix '
  'shape. Kept so a future ScanX format change that DOES introduce a second plan/option variant per '
  'fund is caught by the same rule rather than silently re-opening the 4.09x defect.';

-- ── 3. Non-equity ScanX rows, excluded and counted (never silently dropped) ────────────────────
CREATE OR REPLACE VIEW nidp.v_scanx_holdings_asset_class_audit AS
SELECT as_of_month,
       count(*)                                               AS total_rows,
       count(*) FILTER (WHERE asset_class IN ('Equity','Arbitrage'))     AS equity_like_rows,
       count(*) FILTER (WHERE asset_class NOT IN ('Equity','Arbitrage')) AS excluded_other_asset_class_rows,
       count(*) FILTER (WHERE shares = 0 AND weight_pct = 0)              AS zero_holding_rows,
       count(DISTINCT amc)                                                AS amcs
  FROM nidp.scanx_mf_holdings
 GROUP BY 1;

COMMENT ON VIEW nidp.v_scanx_holdings_asset_class_audit IS
  'Per month: how much of nidp.scanx_mf_holdings is equity-like (Equity + Arbitrage long cash leg, '
  'the two classes nidp.v_mf_holdings_canonical_scanx keeps) vs excluded debt/REIT/InvIT/other '
  'instruments, and how many rows are a disclosed zero holding (shares=0 AND weight_pct=0 — a real '
  'reported zero, ~27-31% of all rows every month across unrelated AMCs, not a one-off artefact; see '
  'the migration header). Read before trusting a ScanX-sourced coverage figure for one AMC-month.';

-- ── 4. ScanX canonical grain, same shape as nidp.v_mf_holdings_canonical ───────────────────────
-- No collapsing is needed (the primary key already guarantees one row per scheme x ISIN x month;
-- base_scheme_name() is applied for key-format consistency, see header). Columns are named and
-- ordered to match nidp.v_mf_holdings_canonical wherever the concept exists, NULL/0 where ScanX
-- carries no equivalent (market_value_inr, derivative_*, published_at — ScanX gives no publication
-- date, only retrieved_at, so known_from_basis is always 'observed').
CREATE OR REPLACE VIEW nidp.v_mf_holdings_canonical_scanx AS
SELECT a.amc_id,
       nidp.base_scheme_name(h.scheme_name)                 AS base_scheme,
       a.amc_id || '|' || nidp.base_scheme_name(h.scheme_name) AS canonical_fund_key,
       h.security_isin,
       h.as_of_month,
       h.security_name,
       h.scheme_slug                                         AS representative_scheme_code,
       h.shares                                               AS shares,
       NULL::numeric                                          AS market_value_inr,
       h.weight_pct,
       h.asset_class                                          AS instrument_type,
       1                                                       AS variant_rows,
       1                                                       AS variant_scheme_codes_n,
       ARRAY[h.scheme_slug]                                    AS variant_scheme_codes,
       1                                                       AS qty_variants,
       h.shares                                                AS naive_sum_quantity,
       0                                                       AS derivative_rows,
       0                                                       AS derivative_legs,
       NULL::numeric                                           AS derivative_net_quantity,
       ARRAY['scanx']                                          AS sources,
       NULL::text[]                                            AS source_urls,
       'scanx'                                                 AS representative_source,
       'scanx_scheme_name'                                     AS key_basis,
       false                                                   AS scheme_unresolved,
       NULL::timestamptz                                       AS published_at,
       h.retrieved_at                                          AS source_observed_at_min,
       h.retrieved_at                                          AS source_observed_at_max,
       h.retrieved_at                                          AS ingested_at,
       h.retrieved_at                                          AS known_from,
       'observed'                                              AS known_from_basis
  FROM nidp.scanx_mf_holdings h
  JOIN nidp.v_scanx_amc_id a ON a.scanx_amc_name = h.amc
 WHERE h.asset_class IN ('Equity', 'Arbitrage')
   AND h.security_isin IS NOT NULL AND h.security_isin <> '';

COMMENT ON VIEW nidp.v_mf_holdings_canonical_scanx IS
  'ScanX-sourced holdings (nidp.scanx_mf_holdings) in the SAME shape as nidp.v_mf_holdings_canonical, '
  'covering all 51 ScanX AMCs including the 11 nidp.v_mf_holdings_canonical already covers from '
  'mf_holdings_monthly. Read nidp.v_mf_holdings_canonical_ext, not this view directly, for a '
  'no-double-count union. shares is never a sum across scheme variants (there are none to sum — see '
  'the migration header) and 0 is a real disclosed zero, not a missing value.';

-- ── 5. THE EXTENSION: union, scanx fills only the ~40 AMCs amc-file does not cover ─────────────
CREATE OR REPLACE VIEW nidp.v_mf_holdings_canonical_ext AS
SELECT amc_id, base_scheme, canonical_fund_key, security_isin, as_of_month, security_name,
       representative_scheme_code, shares, market_value_inr, weight_pct, instrument_type,
       variant_rows, variant_scheme_codes_n, qty_variants, naive_sum_quantity,
       derivative_rows, derivative_legs, sources, source_urls, representative_source,
       known_from, known_from_basis,
       'amc_file'::text AS holding_source
  FROM nidp.v_mf_holdings_canonical
UNION ALL
SELECT amc_id, base_scheme, canonical_fund_key, security_isin, as_of_month, security_name,
       representative_scheme_code, shares, market_value_inr, weight_pct, instrument_type,
       variant_rows, variant_scheme_codes_n, qty_variants, naive_sum_quantity,
       derivative_rows, derivative_legs, sources, source_urls, representative_source,
       known_from, known_from_basis,
       'scanx'::text AS holding_source
  FROM nidp.v_mf_holdings_canonical_scanx
 WHERE amc_id NOT IN (SELECT DISTINCT amc_id FROM nidp.v_mf_holdings_canonical);

COMMENT ON VIEW nidp.v_mf_holdings_canonical_ext IS
  'nidp.v_mf_holdings_canonical (11 AMC-filed houses, preferred, UNCHANGED) union ScanX-sourced '
  'canonical rows for every AMC the AMC-file side does NOT cover (dynamically excluded by amc_id, '
  'not a hardcoded 11-name list, so this adapts if amc-file coverage grows). Never sums the two '
  'sources for the same amc_id. holding_source says which side a row came from. This is the view to '
  'read for coverage/breadth that should include the ScanX-only AMCs; '
  'nidp.v_mf_holdings_canonical itself, and everything already reading it '
  '(nidp.mf_holdings_deltas, nidp.smart_money_scores_daily.coverage_pct), is untouched.';

-- ── 6. Per-stock shares on the extended panel, same shape as nidp.v_mf_stock_shares_monthly ────
CREATE OR REPLACE VIEW nidp.v_mf_stock_shares_monthly_ext AS
SELECT security_isin,
       as_of_month,
       sum(shares)                                                      AS mf_shares,
       count(*)                                                         AS funds,
       count(DISTINCT amc_id)                                           AS amcs,
       count(DISTINCT amc_id) FILTER (WHERE holding_source = 'amc_file') AS amcs_amc_file,
       count(DISTINCT amc_id) FILTER (WHERE holding_source = 'scanx')    AS amcs_scanx,
       count(*) FILTER (WHERE holding_source = 'scanx')                  AS funds_scanx,
       sum(naive_sum_quantity)                                          AS naive_mf_shares,
       sum(market_value_inr)                                            AS mf_market_value_inr,
       max(known_from)                                                  AS known_from,
       CASE WHEN count(*) = count(*) FILTER (WHERE known_from_basis = 'published')
            THEN 'published' ELSE 'observed' END                       AS known_from_basis
  FROM nidp.v_mf_holdings_canonical_ext
 GROUP BY security_isin, as_of_month;

COMMENT ON VIEW nidp.v_mf_stock_shares_monthly_ext IS
  'Per (ISIN, month): disclosed mutual-fund shares over the EXTENDED panel (11 amc-file AMCs + up to '
  '40 ScanX-only AMCs). amcs_amc_file/amcs_scanx and funds_scanx report how much of the row came from '
  'which side, so a consumer can tell the new coverage apart from the original. Compare against '
  'nidp.v_mf_stock_shares_monthly (unchanged, amc-file-only) to see exactly what this migration adds.';

-- ── 7. Measured coverage on the extended panel, same shape/semantics as nidp.v_mf_stock_coverage ─
CREATE OR REPLACE VIEW nidp.v_mf_stock_coverage_ext AS
WITH px_date AS (
    SELECT s.as_of_month,
           (SELECT max(p.as_of_date) FROM nidp.prices_eod p
             WHERE p.series IN ('EQ','BE')
               AND p.as_of_date <= (s.as_of_month + INTERVAL '1 month - 1 day')::date) AS px_date
      FROM (SELECT DISTINCT as_of_month FROM nidp.v_mf_stock_shares_monthly_ext) s
),
sym AS (
    SELECT DISTINCT ON (p.isin, d.as_of_month)
           p.isin, d.as_of_month, p.symbol
      FROM px_date d
      JOIN nidp.prices_eod p ON p.as_of_date = d.px_date AND p.series IN ('EQ','BE')
     WHERE p.isin IS NOT NULL
     ORDER BY p.isin, d.as_of_month, p.symbol
),
shp AS (
    SELECT DISTINCT ON (s.symbol, m.as_of_month)
           s.symbol, m.as_of_month, s.period_end, s.mf_pct, s.total_shares, s.source,
           s.total_shares * s.mf_pct / 100.0 AS expected_mf_shares
      FROM (SELECT DISTINCT as_of_month FROM nidp.v_mf_stock_shares_monthly_ext) m
      JOIN nidp.shareholding_pattern s
        ON s.period_end <= (m.as_of_month + INTERVAL '1 month - 1 day')::date
       AND s.mf_pct IS NOT NULL AND s.mf_pct > 0
       AND s.total_shares IS NOT NULL AND s.total_shares > 0
     ORDER BY s.symbol, m.as_of_month, s.period_end DESC, s.source
)
SELECT h.security_isin,
       h.as_of_month,
       sy.symbol,
       h.mf_shares,
       h.naive_mf_shares,
       h.funds,
       h.amcs,
       h.amcs_amc_file,
       h.amcs_scanx,
       h.funds_scanx,
       sh.expected_mf_shares,
       sh.mf_pct                                                   AS disclosed_mf_pct,
       sh.total_shares                                             AS disclosed_total_shares,
       sh.period_end                                               AS disclosure_period_end,
       sh.source                                                   AS disclosure_source,
       round(h.mf_shares / nullif(sh.expected_mf_shares, 0), 4)     AS coverage_ratio,
       round(100.0 * h.mf_shares / nullif(sh.expected_mf_shares, 0), 2) AS coverage_pct,
       round(h.naive_mf_shares / nullif(sh.expected_mf_shares, 0), 4) AS naive_ratio,
       CASE WHEN sy.symbol IS NULL                 THEN 'isin_not_listed_eq_be'
            WHEN sh.expected_mf_shares IS NULL     THEN 'company_discloses_no_mf_pct_or_total_shares'
            WHEN h.mf_shares > sh.expected_mf_shares * 1.05 THEN 'measured_exceeds_disclosed'
            ELSE 'measured' END                                    AS coverage_basis,
       h.known_from,
       h.known_from_basis
  FROM nidp.v_mf_stock_shares_monthly_ext h
  LEFT JOIN sym sy ON sy.isin = h.security_isin AND sy.as_of_month = h.as_of_month
  LEFT JOIN shp sh ON sh.symbol = sy.symbol     AND sh.as_of_month = h.as_of_month;

COMMENT ON VIEW nidp.v_mf_stock_coverage_ext IS
  'nidp.v_mf_stock_coverage, recomputed over the EXTENDED panel (nidp.v_mf_holdings_canonical_ext: '
  '11 amc-file AMCs + up to 40 ScanX-only AMCs). Same NULL-not-zero semantics: coverage_ratio is '
  'NULL wherever the company has not disclosed both mf_pct and total_shares. Compare its median '
  'against nidp.v_mf_stock_coverage''s to see the measured effect of adding the ScanX AMCs. '
  'nidp.v_mf_stock_coverage and nidp.smart_money_scores_daily.coverage_pct are UNCHANGED by this '
  'migration — this is a parallel, additive measurement, not a replacement.';

-- NOT DONE HERE, BY DESIGN (see header "SOURCE PREFERENCE..."):
--   * nidp.mf_holdings_deltas / backend/nidp/services/mf_holdings_deltas/service.py is not changed
--     to read nidp.v_mf_holdings_canonical_ext, so month-over-month deltas and panel_status for the
--     40 new AMCs are NOT yet computed anywhere. fund_months in that service is still built from
--     mf_holdings_monthly only.
--   * nidp.smart_money_scores_daily.coverage_pct is not repointed at v_mf_stock_coverage_ext, so the
--     Smart Money score itself does not yet benefit from the wider panel.
-- Both are explicitly out of scope for this migration (constraints: do not alter migrations 179-183
-- or the deltas service's existing logic beyond what reading the extended view strictly requires,
-- and this task does not require the deltas/scorer to read it). Wiring either in is a candidate
-- follow-up, and would need its own coverage-shift review before touching published numbers.
