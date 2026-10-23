-- 182: canonical MF holdings — ONE row per fund, not one per plan/option variant.
--
-- THE DEFECT
-- nidp.mf_holdings_monthly stores a scheme's holding once per PLAN/OPTION scheme_code, each row
-- carrying an IDENTICAL quantity, and every consumer that sums `quantity` therefore multiplies
-- the holding. Measured on staging 2026-09-01 (read-only queries, 2026-10-23):
--
--   * Axis Children's Fund holds 145,772 Bajaj Finance shares and the table carries it EIGHT
--     times: Direct/Regular x Growth/IDCW, and two AMFI scheme_codes per variant.
--   * 156,682 equity-leg rows collapse to 38,317 canonical (fund x ISIN) rows -> 4.09x.
--     Every month from 2025-09 to 2026-09 sits between 3.72x and 4.33x.
--   * 99.906% of canonical groups carry exactly ONE distinct quantity, so the duplicates are
--     pure copies and not genuine share-class splits (36 groups of 38,317 disagree; see LEGS).
--   * HAL (INE066F01020), 2026-09: summing every row gives 101,960,101 shares against the
--     44,941,680 implied by the company's own filing (6.72% x 668,775,000). The canonical sum
--     is 25,942,001 — 0.58x of the disclosed figure, which is the honest number for a book
--     that indexes 11 of the 56 AMCs in nidp.mf_amc_master.
--   * Nifty 500, 2026-09, n=408 names with both sides disclosed: median ratio of our summed
--     shares to the disclosed MF holding 2.075 (mean 2.134); after dedupe 0.573 (mean 0.569).
--     Cross-checked against a second, independent expected side (nidp.trendlyne_ownership,
--     n=481): 2.072 raw, 0.567 deduped. Two unrelated sources agree, so the 2x is ours.
--
-- Nothing is deleted or rewritten here. The fix is a canonicalisation LAYER: the facts stay as
-- the AMC published them (plan variants and all), and consumers read one row per fund.
--
-- THE KEY, AND WHY EACH PART OF IT IS NEEDED
--   amc_id       — from nidp.mf_scheme_master, else DERIVED FROM THE SOURCE (a `source` belongs
--                  to exactly one AMC; verified: all 14 sources map to exactly one amc_id).
--                  This matters: QUANT_MF_PORTFOLIO_XLSX keys its rows by scheme NAME rather
--                  than AMFI code, so 2,544 of its rows resolve to no master row at all. Without
--                  the source fallback they looked like a 12th AMC and quant's holdings were
--                  counted twice — once from the AMC's own file and once from the third-party
--                  index.
--   base_scheme  — the scheme name with the plan and option suffixes stripped, lower-cased and
--                  whitespace-squeezed. Case matters: the same fund appears as both
--                  'ADITYA BIRLA SUN LIFE ARBITRAGE FUND - ...' and 'Aditya Birla Sun Life ...'.
--   security_isin, as_of_month — the holding's instrument and reporting period.
--
-- The suffix rule is applied in two stages because the real names need both:
--   stage 1  strip from a dash-delimited 'Direct'/'Regular' [Plan] to the end of the string. The
--            plan marker must be followed by end-of-string or another dash, so a fund whose NAME
--            contains the word (e.g. '... Regular Savings Fund - Direct Plan - Growth') is cut at
--            the real plan marker and not mid-name.
--   stage 2  strip a trailing dash-delimited option (Growth / IDCW / Dividend / Bonus / Payout /
--            Re-investment / ... with an optional Daily|Weekly|Monthly|... qualifier), three
--            times, because names stack up to three such suffixes
--            ('Nippon India Nifty 1D Rate Liquid ETF- Growth - Direct Plan').
--
-- LEGS: AN ARBITRAGE FUND IS NOT A SHAREHOLDER OF ITS OWN SHORT
-- 2,931 of the 2026-09 rows are DERIVATIVE legs mapped to the underlying's ISIN: 1,788 short and
-- 495 long expiry-named futures ('ICICI Bank Ltd.-OCT2026'), plus 647 plain-named negatives,
-- including written options ('Kotak Mahindra Bank Ltd. (CALL Option)', -10,208,000). Summing
-- them into a share count is wrong twice over: a short future is not ownership, and netting it
-- against the cash leg erases a real holding. They are therefore classified, EXCLUDED from the
-- share count, and REPORTED per canonical row (derivative_rows = raw source rows,
-- derivative_legs = distinct contracts, derivative_net_quantity = their deduplicated net) so the
-- exclusion is visible rather than silent.
--
-- The residual the classifier cannot catch is measured, not assumed: 36 canonical groups of
-- 38,317 (0.094%) still carry two positive quantities, and they are the long-futures legs whose
-- names carry no expiry marker — e.g. quant BFSI Fund holds Manappuram at both 2,453,969 shares
-- (implied price 315.85, exactly the EQ close) and 159,000 (implied 318.40, the futures basis).
-- The representative is the largest positive quantity, which picks the cash leg in every case
-- inspected; qty_variants exposes the 0.094% so a consumer can exclude them.
--
-- WHAT THIS DOES NOT CLAIM
-- Canonical shares are what ELEVEN AMCs disclosed, not what the industry holds. The coverage view
-- below measures that gap per stock instead of hiding it: coverage_ratio is NULL where the
-- company has not disclosed both mf_pct and total_shares — never 0, never a constant 100.
--
-- Idempotent: safe to re-run.

-- ── 1. Which AMC does each source belong to? Derived, never hardcoded ───────────────────────
-- A `source` is one adapter against one AMC's disclosures, so the amc_id of its rows that DO
-- resolve to the master is the amc_id of the rows that do not. Verified 2026-10-23: each of the
-- 14 sources resolves to exactly one amc_id (distinct_amc_ids = 1 for all).
CREATE OR REPLACE VIEW nidp.v_mf_holdings_source_amc AS
SELECT h.source,
       (array_agg(DISTINCT sm.amc_id) FILTER (WHERE sm.amc_id IS NOT NULL AND sm.amc_id <> ''))[1]
           AS amc_id,
       count(DISTINCT sm.amc_id)                       AS distinct_amc_ids,
       count(*)                                        AS rows_resolved
  FROM nidp.mf_holdings_monthly h
  JOIN nidp.mf_scheme_master sm ON sm.scheme_code = h.scheme_code
 GROUP BY h.source;

COMMENT ON VIEW nidp.v_mf_holdings_source_amc IS
  'source -> amc_id, derived from the scheme codes that resolve to nidp.mf_scheme_master. Used to '
  'attribute rows whose scheme_code is not in the master (QUANT_MF_PORTFOLIO_XLSX keys by scheme '
  'name, 2,544 rows). distinct_amc_ids must stay 1 for every source; > 1 means a source now '
  'carries two houses and the fallback is no longer safe.';

-- ── 2. The canonical key per (scheme_code, source) ─────────────────────────────────────────
-- Computed at the SCHEME grain (a few thousand rows), not per holding (1.7M), so the regex work
-- is paid once and joined.
CREATE OR REPLACE VIEW nidp.v_mf_scheme_canonical_key AS
WITH codes AS (
    SELECT DISTINCT scheme_code, source FROM nidp.mf_holdings_monthly
)
SELECT c.scheme_code,
       c.source,
       coalesce(nullif(sm.amc_id, ''), sa.amc_id, 'unmapped_source:' || c.source) AS amc_id,
       -- Stage 1 then stage 2 x3; see the header for why each exists.
       lower(btrim(regexp_replace(
         regexp_replace(regexp_replace(regexp_replace(
           regexp_replace(coalesce(sm.scheme_name, c.scheme_code),
             '\s*[-–]\s*(direct|regular)(\s*plan)?\s*([-–].*)?$', '', 'i'),
           '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
           '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
           '\s*[-–]\s*((daily|weekly|fortnightly|monthly|quarterly|half[\s-]*yearly|annual|adhoc)\s*)?(growth|idcw|dividend|bonus|payout|re-?investment|appreciation|cumulative)([^-–]*)?$', '', 'i'),
         '\s+', ' ', 'g'))) AS base_scheme,
       sm.scheme_name,
       -- How the key was built, so a consumer can tell a named fund from one we only know by code.
       CASE WHEN sm.scheme_name IS NOT NULL THEN 'master_scheme_name'
            ELSE 'scheme_code_as_name' END                                        AS key_basis,
       (sm.scheme_code IS NULL)                                                   AS scheme_unresolved,
       (sm.amc_id IS NULL OR sm.amc_id = '')                                      AS amc_from_source
  FROM codes c
  LEFT JOIN nidp.mf_scheme_master sm ON sm.scheme_code = c.scheme_code
  LEFT JOIN nidp.v_mf_holdings_source_amc sa ON sa.source = c.source;

COMMENT ON VIEW nidp.v_mf_scheme_canonical_key IS
  'One row per (scheme_code, source) carrying the canonical fund identity: amc_id (master, else '
  'derived from the source) and base_scheme (name with plan/option suffixes stripped, lower-cased). '
  'key_basis / scheme_unresolved / amc_from_source say how much of the identity was inferred.';

-- ── 3. Holdings with the canonical key and the instrument leg attached ─────────────────────
CREATE OR REPLACE VIEW nidp.v_mf_holdings_keyed AS
SELECT h.scheme_code,
       h.as_of_month,
       h.security_isin,
       h.security_name,
       h.instrument_type,
       h.quantity,
       h.market_value_inr,
       h.weight_pct,
       h.source,
       h.source_url,
       h.ingested_at,
       h.published_at,
       h.source_observed_at,
       h.publication_provenance,
       k.amc_id,
       k.base_scheme,
       k.key_basis,
       k.scheme_unresolved,
       -- A fund's own file is the primary disclosure; a third-party index is a rendering of it.
       -- Used only as a tie-break when one fund-ISIN-month is carried by two sources.
       CASE WHEN h.source ILIKE '%ADVISORKHOJ%' THEN 2 ELSE 1 END AS source_rank,
       -- Instrument leg. 'derivative' is never counted as share ownership and never netted
       -- against the cash leg; 'no_quantity' is cash/receivables/unparsed and carries no count.
       CASE
         WHEN h.quantity IS NULL                                                   THEN 'no_quantity'
         WHEN h.security_name ~* '[-–]\s*(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*[-/ ]?\d{2,4}\s*$'
                                                                                   THEN 'derivative'
         WHEN h.security_name ~* '\((CALL|PUT)\s*OPTION\)'                          THEN 'derivative'
         WHEN h.quantity < 0                                                        THEN 'derivative'
         ELSE 'equity_cash'
       END AS leg_class
  FROM nidp.mf_holdings_monthly h
  JOIN nidp.v_mf_scheme_canonical_key k
    ON k.scheme_code = h.scheme_code AND k.source = h.source;

COMMENT ON VIEW nidp.v_mf_holdings_keyed IS
  'nidp.mf_holdings_monthly with the canonical fund identity and the instrument leg attached. '
  'leg_class: equity_cash | derivative (expiry-named future, written option, or a negative '
  'quantity) | no_quantity (cash/receivables). Row grain is unchanged — this is the input to the '
  'canonical view, not a deduplicated one.';

-- ── 4. THE CANONICAL GRAIN: one row per (amc, base scheme, ISIN, month) ────────────────────
CREATE OR REPLACE VIEW nidp.v_mf_holdings_canonical AS
-- NOT MATERIALIZED on purpose. The leg-classification regexes are the cost of this view, and a
-- materialised CTE would block qual pushdown: the delta service and the coverage view both read
-- ONE month, and they must not pay for 1.7M rows to get 190k. Inlined, `as_of_month = X` reaches
-- the base-table index. The all-months audit query pays several passes instead, which is the
-- right way round — it runs monthly, the per-month path runs every day.
WITH k AS NOT MATERIALIZED (
    SELECT scheme_code, as_of_month, security_isin, security_name, instrument_type, quantity,
           market_value_inr, weight_pct, source, source_url, ingested_at, published_at,
           source_observed_at, amc_id, base_scheme, key_basis, scheme_unresolved, source_rank,
           leg_class
      FROM nidp.v_mf_holdings_keyed
     WHERE security_isin IS NOT NULL AND security_isin <> ''
),
eq AS NOT MATERIALIZED (
    SELECT * FROM k WHERE leg_class = 'equity_cash'
),
rep AS (
    -- The representative row: largest positive quantity (the cash leg wherever a stray long
    -- future shares the group), then the AMC's own file over the third-party index, then the
    -- lowest scheme_code so the choice is deterministic across runs.
    SELECT DISTINCT ON (amc_id, base_scheme, security_isin, as_of_month)
           amc_id, base_scheme, security_isin, as_of_month,
           scheme_code, security_name, quantity, market_value_inr, weight_pct,
           source, source_url, instrument_type, key_basis, scheme_unresolved
      FROM eq
     ORDER BY amc_id, base_scheme, security_isin, as_of_month,
              quantity DESC NULLS LAST, source_rank, scheme_code
),
agg AS (
    SELECT amc_id, base_scheme, security_isin, as_of_month,
           count(*)                                                     AS variant_rows,
           count(DISTINCT quantity)                                     AS qty_variants,
           count(DISTINCT scheme_code)                                  AS variant_scheme_codes_n,
           array_agg(DISTINCT scheme_code ORDER BY scheme_code)         AS variant_scheme_codes,
           array_agg(DISTINCT source ORDER BY source)                   AS sources,
           array_agg(DISTINCT source_url) FILTER (WHERE source_url IS NOT NULL) AS source_urls,
           -- The pre-dedupe sum, kept so the inflation this view removes stays auditable.
           sum(quantity)                                                AS naive_sum_quantity,
           -- Provenance (criterion: reporting period, publication, ingestion all preserved).
           max(published_at)                                            AS published_at,
           min(source_observed_at)                                      AS source_observed_at_min,
           max(source_observed_at)                                      AS source_observed_at_max,
           max(ingested_at)                                             AS ingested_at,
           -- A file is knowable only once all of it is: take the latest of the group.
           max(coalesce(published_at, source_observed_at))              AS known_from,
           CASE WHEN count(*) = count(published_at) THEN 'published' ELSE 'observed' END
                                                                        AS known_from_basis
      FROM eq
     GROUP BY 1,2,3,4
),
-- Derivative legs are deduplicated the SAME way as the cash leg, because they fan out across
-- plan variants identically: one contract (security_name + quantity) is one leg however many
-- scheme_codes repeat it. Summing them raw would report a 4x-inflated short position — the very
-- defect this migration exists to remove, in the column that reports the exclusion.
der AS (
    SELECT amc_id, base_scheme, security_isin, as_of_month,
           sum(rows_for_leg)                 AS derivative_rows,   -- raw source rows, pre-dedupe
           count(*)                          AS derivative_legs,   -- distinct contracts
           sum(quantity)                     AS derivative_net_quantity
      FROM (SELECT amc_id, base_scheme, security_isin, as_of_month, security_name, quantity,
                   count(*) AS rows_for_leg
              FROM k WHERE leg_class = 'derivative'
             GROUP BY 1,2,3,4,5,6) legs
     GROUP BY 1,2,3,4
)
SELECT r.amc_id,
       r.base_scheme,
       r.amc_id || '|' || r.base_scheme                AS canonical_fund_key,
       r.security_isin,
       r.as_of_month,
       r.security_name,
       r.scheme_code                                   AS representative_scheme_code,
       r.quantity                                      AS shares,
       r.market_value_inr,
       r.weight_pct,
       r.instrument_type,
       a.variant_rows,
       a.variant_scheme_codes_n,
       a.variant_scheme_codes,
       -- > 1 means the plan variants did NOT agree on the quantity (0.094% of groups in 2026-09,
       -- almost all a long-futures leg the name does not mark). Exclude these if the use needs
       -- certainty rather than coverage.
       a.qty_variants,
       a.naive_sum_quantity,
       coalesce(d.derivative_rows, 0)                  AS derivative_rows,
       coalesce(d.derivative_legs, 0)                  AS derivative_legs,
       d.derivative_net_quantity,
       a.sources,
       a.source_urls,
       r.source                                        AS representative_source,
       r.key_basis,
       r.scheme_unresolved,
       a.published_at,
       a.source_observed_at_min,
       a.source_observed_at_max,
       a.ingested_at,
       a.known_from,
       a.known_from_basis
  FROM rep r
  JOIN agg a USING (amc_id, base_scheme, security_isin, as_of_month)
  LEFT JOIN der d USING (amc_id, base_scheme, security_isin, as_of_month);

COMMENT ON VIEW nidp.v_mf_holdings_canonical IS
  'ONE row per (amc_id, base_scheme, security_isin, as_of_month): a fund''s disclosed equity '
  'holding, with plan/option variants collapsed (4.09x fan-out in 2026-09) and derivative legs '
  'excluded but reported. `shares` is the representative quantity — never a sum across variants. '
  'naive_sum_quantity keeps the pre-dedupe figure for audit. Read THIS, not '
  'nidp.mf_holdings_monthly, for anything that adds share counts together.';

-- ── 5. Per-stock canonical MF shares, with the naive figure beside it ──────────────────────
CREATE OR REPLACE VIEW nidp.v_mf_stock_shares_monthly AS
SELECT security_isin,
       as_of_month,
       sum(shares)                                   AS mf_shares,
       count(*)                                      AS funds,
       count(DISTINCT amc_id)                        AS amcs,
       sum(naive_sum_quantity)                       AS naive_mf_shares,
       round(sum(naive_sum_quantity) / nullif(sum(shares), 0), 3) AS naive_inflation_x,
       sum(variant_rows)                             AS variant_rows,
       sum(derivative_rows)                          AS derivative_rows,
       sum(derivative_legs)                          AS derivative_legs,
       sum(derivative_net_quantity)                  AS derivative_net_quantity,
       count(*) FILTER (WHERE qty_variants > 1)       AS funds_with_qty_conflict,
       count(*) FILTER (WHERE scheme_unresolved)      AS funds_scheme_unresolved,
       sum(market_value_inr)                         AS mf_market_value_inr,
       count(*) FILTER (WHERE market_value_inr IS NULL) AS funds_without_market_value,
       max(known_from)                               AS known_from,
       CASE WHEN count(*) = count(*) FILTER (WHERE known_from_basis = 'published')
            THEN 'published' ELSE 'observed' END      AS known_from_basis
  FROM nidp.v_mf_holdings_canonical
 GROUP BY security_isin, as_of_month;

COMMENT ON VIEW nidp.v_mf_stock_shares_monthly IS
  'Per (ISIN, month): the mutual-fund shares our indexed AMCs disclosed, deduplicated. '
  'naive_mf_shares / naive_inflation_x carry the pre-dedupe sum so the defect stays measurable. '
  'mf_market_value_inr is a partial sum where some AMCs publish no value (TATA and UTI publish '
  'none at all), which funds_without_market_value states — do not read it as a full total.';

-- ── 6. MEASURED coverage per stock-month ───────────────────────────────────────────────────
-- coverage_ratio = canonical MF shares / (total_shares x mf_pct), i.e. what share of the mutual
-- funds' holding of this company we actually see. It is NULL — not 0, not 100 — whenever the
-- company has not disclosed both inputs.
CREATE OR REPLACE VIEW nidp.v_mf_stock_coverage AS
WITH px_date AS (
    -- Symbols are resolved at the LAST EQ/BE session of the reporting month, so a rename
    -- (LTIM -> LTM) is read as of the period rather than as of today.
    SELECT s.as_of_month,
           (SELECT max(p.as_of_date) FROM nidp.prices_eod p
             WHERE p.series IN ('EQ','BE')
               AND p.as_of_date <= (s.as_of_month + INTERVAL '1 month - 1 day')::date) AS px_date
      FROM (SELECT DISTINCT as_of_month FROM nidp.v_mf_stock_shares_monthly) s
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
    -- The company's own filing, as of the latest quarter that had ENDED by the reporting month.
    SELECT DISTINCT ON (s.symbol, m.as_of_month)
           s.symbol, m.as_of_month, s.period_end, s.mf_pct, s.total_shares, s.source,
           s.total_shares * s.mf_pct / 100.0 AS expected_mf_shares
      FROM (SELECT DISTINCT as_of_month FROM nidp.v_mf_stock_shares_monthly) m
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
       sh.expected_mf_shares,
       sh.mf_pct                                                   AS disclosed_mf_pct,
       sh.total_shares                                             AS disclosed_total_shares,
       sh.period_end                                               AS disclosure_period_end,
       sh.source                                                   AS disclosure_source,
       round(h.mf_shares / nullif(sh.expected_mf_shares, 0), 4)     AS coverage_ratio,
       round(100.0 * h.mf_shares / nullif(sh.expected_mf_shares, 0), 2) AS coverage_pct,
       round(h.naive_mf_shares / nullif(sh.expected_mf_shares, 0), 4) AS naive_ratio,
       -- Why the ratio is or is not computable. Never fill a gap with a number.
       CASE WHEN sy.symbol IS NULL                 THEN 'isin_not_listed_eq_be'
            WHEN sh.expected_mf_shares IS NULL     THEN 'company_discloses_no_mf_pct_or_total_shares'
            WHEN h.mf_shares > sh.expected_mf_shares * 1.05 THEN 'measured_exceeds_disclosed'
            ELSE 'measured' END                                    AS coverage_basis,
       h.known_from,
       h.known_from_basis
  FROM nidp.v_mf_stock_shares_monthly h
  LEFT JOIN sym sy ON sy.isin = h.security_isin AND sy.as_of_month = h.as_of_month
  LEFT JOIN shp sh ON sh.symbol = sy.symbol     AND sh.as_of_month = h.as_of_month;

COMMENT ON VIEW nidp.v_mf_stock_coverage IS
  'Measured MF-holdings coverage per stock-month: canonical shares / (total_shares x mf_pct) from '
  'the company''s own shareholding filing. Nifty 500 2026-09 median 0.573 (naive 2.075). '
  'coverage_ratio is NULL where the filing does not disclose both inputs — coverage_basis says '
  'which case applies. A ratio near 1 is NOT expected and must not be engineered: we index 11 of '
  'the 56 AMCs in nidp.mf_amc_master.';

-- ── 7. Dedupe audit: the defect's size, per month, as a standing measurement ────────────────
CREATE OR REPLACE VIEW nidp.v_mf_holdings_dedupe_audit AS
WITH k AS (
    SELECT as_of_month, leg_class, security_isin, quantity
      FROM nidp.v_mf_holdings_keyed
),
c AS (
    SELECT as_of_month, count(*) AS canonical_rows, sum(shares) AS canonical_shares,
           count(*) FILTER (WHERE qty_variants > 1) AS groups_qty_conflict,
           count(*) FILTER (WHERE scheme_unresolved) AS groups_scheme_unresolved
      FROM nidp.v_mf_holdings_canonical GROUP BY 1
)
SELECT c.as_of_month,
       count(*)                                                            AS source_rows,
       count(*) FILTER (WHERE k.leg_class = 'equity_cash'
                          AND k.security_isin IS NOT NULL AND k.security_isin <> '') AS equity_rows,
       count(*) FILTER (WHERE k.leg_class = 'derivative')                   AS derivative_rows,
       count(*) FILTER (WHERE k.leg_class = 'no_quantity')                  AS no_quantity_rows,
       count(*) FILTER (WHERE k.security_isin IS NULL OR k.security_isin = '') AS no_isin_rows,
       c.canonical_rows,
       round(count(*) FILTER (WHERE k.leg_class = 'equity_cash'
                                AND k.security_isin IS NOT NULL AND k.security_isin <> '')::numeric
             / nullif(c.canonical_rows, 0), 3)                              AS duplication_factor,
       c.groups_qty_conflict,
       round(100.0 * c.groups_qty_conflict / nullif(c.canonical_rows, 0), 3) AS pct_qty_conflict,
       c.groups_scheme_unresolved,
       sum(k.quantity) FILTER (WHERE k.leg_class = 'equity_cash')           AS naive_equity_shares,
       c.canonical_shares
  FROM k
  JOIN c ON c.as_of_month = k.as_of_month
 GROUP BY c.as_of_month, c.canonical_rows, c.groups_qty_conflict, c.groups_scheme_unresolved,
          c.canonical_shares;

COMMENT ON VIEW nidp.v_mf_holdings_dedupe_audit IS
  'Per reporting month: how much of nidp.mf_holdings_monthly is plan-variant duplication '
  '(duplication_factor, 3.7-4.3x through 2025-09..2026-09), how much is derivative legs, and how '
  'often the variants disagree (pct_qty_conflict, 0.094% in 2026-09). A watchdog: a jump in '
  'pct_qty_conflict means the canonical key has stopped fitting the source names.';
