-- 177: count FUNDS, not plan variants, in accumulation breadth.
--
-- THE DEFECT
-- One fund's disclosure is expanded to every plan-variant scheme_code it owns (Regular/Direct x
-- Growth/IDCW), each carrying an IDENTICAL quantity. Counting scheme_codes therefore counts the
-- same investment decision many times. Measured 2026-10-22 on 2026-09 data:
--   * inflation varies by AMC: Tata 13.0x, Nippon 7.2x, Axis 4.0x, SBI 3.8x, ICICI 3.6x, Kotak 3.4x
--   * the scanner's breadth column overstates by 2.5-3.4x (HDFCBANK 330 "schemes" -> 110 funds)
--   * summing shares across scheme_codes made our SEVEN-AMC total ~2x the whole industry's:
--       HDFCBANK ours 8,133,866,106 vs vendor all-AMC 4,092,646,306 (1.99x)
--       DRREDDY  ours   337,153,097 vs vendor           130,566,814 (2.58x)
--     which is arithmetically impossible and is what exposed this.
--
-- Worse than the magnitude is the BIAS: because inflation differs per AMC, raw scheme counts
-- systematically favour fund houses that run more plan variants. That is the precise failure the
-- requirement warns against — "avoid overstating independent confirmation".
--
-- THE KEY
-- Plan variants of one fund are exact copies, so (amc_id, previous_shares, current_shares)
-- identifies the underlying decision within an ISIN-month. Verified: collapses HDFCBANK's 1,077
-- scheme_code rows to 259 fund blocks (4.16x), matching the independently measured 4.3x.
-- Share quantities are large and fund-specific, so a collision between two genuinely different
-- funds holding an identical count is vanishingly unlikely; where it happened it would merge two
-- funds into one, i.e. UNDER-state breadth, which is the safe direction.
--
-- amcs_* counts were always correct (distinct AMC) and are unchanged.
--
-- Idempotent: safe to re-run.

-- Dropped rather than replaced: the column list changes (schemes_* -> funds_*) and
-- CREATE OR REPLACE VIEW cannot rename columns. Renaming is deliberate — a consumer still
-- asking for schemes_increasing should fail loudly rather than silently read a different
-- quantity than it was written against.
DROP VIEW IF EXISTS nidp.v_mf_accumulation_breadth;

CREATE VIEW nidp.v_mf_accumulation_breadth AS
WITH d AS (
    SELECT dl.security_isin,
           dl.current_month,
           dl.scheme_code,
           dl.change_class,
           dl.shares_delta,
           dl.previous_shares,
           dl.current_shares,
           coalesce(nullif(sm.amc_id, ''), 'unattributed:' || dl.scheme_code) AS amc_id
      FROM nidp.mf_holdings_deltas dl
      LEFT JOIN nidp.mf_scheme_master sm ON sm.scheme_code = dl.scheme_code
)
SELECT security_isin,
       current_month,
       -- FUND counts: plan variants of one fund collapse to a single decision.
       count(DISTINCT (amc_id, previous_shares, current_shares))                       AS funds_total,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class IN ('increase', 'new'))                          AS funds_increasing,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class IN ('decrease', 'possible_exit'))                AS funds_reducing,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class = 'unchanged')                                   AS funds_unchanged,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class = 'new')                                         AS funds_new,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class = 'possible_exit')                               AS funds_exited,
       count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class = 'unknown')                                     AS funds_unknown,
       -- Raw scheme-code counts retained ONLY so the inflation stays visible and auditable.
       -- Never display these as "schemes increasing".
       count(*) FILTER (WHERE change_class IN ('increase', 'new'))                      AS raw_scheme_rows_increasing,
       count(DISTINCT amc_id) FILTER (WHERE change_class IN ('increase', 'new'))        AS amcs_increasing,
       count(DISTINCT amc_id) FILTER (WHERE change_class IN ('decrease', 'possible_exit')) AS amcs_reducing,
       -- Net share change, de-duplicated: sum one representative row per fund block.
       (SELECT sum(x.shares_delta) FROM (
           SELECT DISTINCT ON (amc_id, previous_shares, current_shares)
                  amc_id, previous_shares, current_shares, shares_delta
             FROM d i
            WHERE i.security_isin = d.security_isin AND i.current_month = d.current_month
              AND i.change_class <> 'unknown'
            ORDER BY amc_id, previous_shares, current_shares
        ) x)                                                                            AS net_shares_delta,
       (count(DISTINCT amc_id) FILTER (WHERE change_class IN ('increase', 'new')) <= 1)  AS single_amc_signal,
       (count(DISTINCT (amc_id, previous_shares, current_shares))
           FILTER (WHERE change_class IN ('increase', 'new')) <= 1)                      AS single_fund_signal
  FROM d
 GROUP BY security_isin, current_month;

COMMENT ON VIEW nidp.v_mf_accumulation_breadth IS
  'Per ISIN-month breadth of disclosed MF holdings changes, counting FUNDS (plan variants '
  'collapsed) rather than scheme codes, which overstated breadth by 2.5-3.4x and biased it toward '
  'AMCs running more plan variants. raw_scheme_rows_increasing is kept only to keep that '
  'inflation visible; do not display it. amcs_increasing is the independent-holder count.';
