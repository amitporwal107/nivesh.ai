-- 165: MF holdings coverage ledger + month-over-month holdings deltas + accumulation breadth.
--
-- WHY THIS EXISTS
-- nidp.mf_holdings_monthly held exactly ONE month (2026-09-01) when this was written, so not a
-- single holdings delta was computable — and a delta is the whole point of the Smart Money
-- feature (its §20.1 share-count change, §20.2 breadth, §26.2-4 acceptance criteria). Two things
-- were missing and both are created here:
--
--   1. mf_holdings_coverage — a per-(amc, month) ledger of what was actually ingested.
--      The old daily service recorded only a month-level job_log row with "missing=10/14", which
--      cannot say WHICH AMC-month is absent, so nothing could heal a gap and nothing downstream
--      could tell "this AMC reported no holdings" from "we never fetched this AMC". That
--      distinction is load-bearing: without it a scheme missing from month M-1 looks identical to
--      a scheme that sold out, and we would publish a fabricated "new position" (§26.4, §26.8).
--
--   2. mf_holdings_deltas — the §25 `institutional_holding_deltas` grain, named with this repo's
--      mf_ prefix and keyed the way the holdings table actually is (scheme_code × ISIN × month)
--      rather than the doc's generic reporting_entity_id.
--
-- COVERAGE-AWARE CHANGE CLASSIFICATION (the part that keeps us honest)
-- `new` and `possible_exit` are only ever claimed when we can PROVE the comparison month was
-- ingested for that scheme. The proof used is scheme-level presence: if scheme S has any row in
-- month M-1 then S's disclosure file was fetched and parsed that month, so an ISIN absent from it
-- genuinely left the portfolio. If S has no row in M-1 at all, the absence is OUR gap, and the
-- row is classified 'unknown' / 'coverage_gap' — never 'new'.
--
-- ISIN is required for a delta row: a holding we cannot reconcile to an instrument cannot be
-- attributed to a stock (§26.2). Those rows are excluded here and counted by the refresh service
-- so the exclusion is reported rather than silent (§26.8).
--
-- Idempotent: safe to re-run.

-- ── 1. Coverage ledger ──────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS nidp.mf_holdings_coverage (
    amc_id          TEXT        NOT NULL,   -- adapter key, e.g. 'icici_pru' (NOT the AMFI code)
    as_of_month     DATE        NOT NULL,   -- first-of-month; the portfolio's reporting month
    status          TEXT        NOT NULL,   -- see CHECK below
    rows_written    INTEGER     NOT NULL DEFAULT 0,
    schemes_written INTEGER     NOT NULL DEFAULT 0,
    source_url      TEXT,                   -- the official AMC file we actually parsed
    attempts        INTEGER     NOT NULL DEFAULT 1,
    first_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error      TEXT,
    PRIMARY KEY (amc_id, as_of_month),
    -- OK      — rows parsed and written for this AMC-month.
    -- EMPTY   — the fetch worked but produced no rows. Usually the third-party index had not yet
    --           listed the month (AdvisorKhoj lags the SEBI M+10 deadline), so this is RETRYABLE
    --           and is exactly what the catch-up pass re-attempts.
    -- ERROR   — the adapter raised. Also retryable; last_error says why.
    CONSTRAINT mf_holdings_coverage_status_chk CHECK (status IN ('OK', 'EMPTY', 'ERROR'))
);

CREATE INDEX IF NOT EXISTS idx_mf_hold_cov_month  ON nidp.mf_holdings_coverage (as_of_month);
CREATE INDEX IF NOT EXISTS idx_mf_hold_cov_status ON nidp.mf_holdings_coverage (status)
    WHERE status <> 'OK';

COMMENT ON TABLE nidp.mf_holdings_coverage IS
  'Per-(amc, month) ingestion ledger for nidp.mf_holdings_monthly. Drives catch-up retry and '
  'lets the delta layer tell a real portfolio exit from a gap in our own collection.';

-- ── 2. Month-over-month deltas (§20.1 / §25 institutional_holding_deltas) ───────────────────
CREATE TABLE IF NOT EXISTS nidp.mf_holdings_deltas (
    scheme_code         TEXT        NOT NULL,
    security_isin       TEXT        NOT NULL,
    current_month       DATE        NOT NULL,
    -- The month actually compared against — not M-1 by assumption, since an AMC can skip a
    -- month and a backfill may still be filling in. NULL means there was no earlier
    -- observation of this scheme to compare with (always paired with 'coverage_gap').
    previous_month      DATE,
    security_name       TEXT,
    previous_shares     NUMERIC,
    current_shares      NUMERIC,
    shares_delta        NUMERIC,                -- current - previous; share COUNT only, never value
    shares_pct_change   NUMERIC,                -- NULL unless previous_shares > 0 (§20.1)
    previous_weight_pct NUMERIC(7,4),
    current_weight_pct  NUMERIC(7,4),
    weight_delta_pp     NUMERIC(8,4),           -- percentage POINTS, not a ratio
    -- Market values are carried so a consumer can show value change, but they are deliberately
    -- NOT an input to change_class: a value rise with flat shares is price, not accumulation.
    previous_market_value_inr NUMERIC,
    current_market_value_inr  NUMERIC,
    change_class        TEXT        NOT NULL,
    validation_status   TEXT        NOT NULL,
    source_references   TEXT[],
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scheme_code, security_isin, current_month),
    CONSTRAINT mf_holdings_deltas_class_chk CHECK (change_class IN
        ('increase', 'decrease', 'new', 'possible_exit', 'unchanged', 'unknown')),
    -- validated   — both months' files for this scheme were ingested; the change is real.
    -- coverage_gap — the comparison month is missing for this scheme; direction is unknowable.
    CONSTRAINT mf_holdings_deltas_validation_chk CHECK (validation_status IN
        ('validated', 'coverage_gap')),
    -- A coverage gap must never masquerade as a directional finding.
    CONSTRAINT mf_holdings_deltas_gap_is_unknown_chk CHECK (
        validation_status <> 'coverage_gap' OR change_class = 'unknown'),
    -- A validated change must name the month it was measured against; a gap must not pretend to.
    CONSTRAINT mf_holdings_deltas_prev_month_chk CHECK (
        (validation_status = 'validated' AND previous_month IS NOT NULL)
     OR (validation_status = 'coverage_gap' AND previous_month IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_mf_hold_delta_isin_month
    ON nidp.mf_holdings_deltas (security_isin, current_month);
CREATE INDEX IF NOT EXISTS idx_mf_hold_delta_month_class
    ON nidp.mf_holdings_deltas (current_month, change_class);

COMMENT ON TABLE nidp.mf_holdings_deltas IS
  'Scheme × ISIN × month holdings change (§20.1). Share-count change only; market value is '
  'carried for display but never classifies the change. change_class is ''unknown'' whenever the '
  'comparison month was not ingested for that scheme.';

-- ── 3. Accumulation breadth / concentration (§20.2) ────────────────────────────────────────
-- Counts are reported as RAW SCHEME COUNTS plus a distinct-AMC count, because schemes inside one
-- AMC are not independent evidence (§20.2). single_amc_signal / single_scheme_signal exist so the
-- UI can say "one fund house" instead of implying broad institutional confirmation.
-- Rows classified 'unknown' are excluded from the directional counts and surfaced separately as
-- schemes_unknown, so a thin-coverage month reads as thin rather than as neutral.
CREATE OR REPLACE VIEW nidp.v_mf_accumulation_breadth AS
WITH d AS (
    SELECT dl.security_isin,
           dl.current_month,
           dl.scheme_code,
           dl.change_class,
           dl.shares_delta,
           -- Schemes absent from the master, or with a blank amc_id, are attributed to a distinct
           -- synthetic bucket per scheme so they can never collapse into one another and understate
           -- the AMC count. 31 of 674 schemes were unattributed when this view was written.
           coalesce(nullif(sm.amc_id, ''), 'unattributed:' || dl.scheme_code) AS amc_id
      FROM nidp.mf_holdings_deltas dl
      LEFT JOIN nidp.mf_scheme_master sm ON sm.scheme_code = dl.scheme_code
)
SELECT security_isin,
       current_month,
       count(*)                                                        AS schemes_total,
       count(*) FILTER (WHERE change_class IN ('increase', 'new'))      AS schemes_increasing,
       count(*) FILTER (WHERE change_class IN ('decrease', 'possible_exit')) AS schemes_reducing,
       count(*) FILTER (WHERE change_class = 'unchanged')               AS schemes_unchanged,
       count(*) FILTER (WHERE change_class = 'new')                     AS schemes_new,
       count(*) FILTER (WHERE change_class = 'possible_exit')           AS schemes_exited,
       count(*) FILTER (WHERE change_class = 'unknown')                 AS schemes_unknown,
       count(DISTINCT amc_id) FILTER (WHERE change_class IN ('increase', 'new'))      AS amcs_increasing,
       count(DISTINCT amc_id) FILTER (WHERE change_class IN ('decrease', 'possible_exit')) AS amcs_reducing,
       -- Net share change across schemes with a known direction. Excludes 'unknown' rows, whose
       -- shares_delta is meaningless.
       sum(shares_delta) FILTER (WHERE change_class <> 'unknown')       AS net_shares_delta,
       (count(DISTINCT amc_id) FILTER (WHERE change_class IN ('increase', 'new')) <= 1)
           AS single_amc_signal,
       (count(*) FILTER (WHERE change_class IN ('increase', 'new')) <= 1)
           AS single_scheme_signal
  FROM d
 GROUP BY security_isin, current_month;

COMMENT ON VIEW nidp.v_mf_accumulation_breadth IS
  'Per ISIN-month breadth of disclosed MF holdings changes (§20.2). Scheme counts are RAW counts; '
  'amcs_increasing is the independent-holder count. single_amc_signal/single_scheme_signal flag a '
  'concentrated signal that must not be presented as broad institutional confirmation.';
