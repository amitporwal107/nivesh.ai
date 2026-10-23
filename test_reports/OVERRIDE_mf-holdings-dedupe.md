# OVERRIDE — MF holdings canonical dedupe (migrations 182/183 + deltas service)

REASON: this session has **READ-ONLY** access to the nidp_staging warehouse, so the two migrations
cannot be applied there and `nidp.mf_holdings_deltas` cannot be rewritten. Three of the 22
authored test cases (TC-18, TC-19 stored-row half, TC-20) therefore cannot be verified as WRITTEN
DATA on staging, and the report's verdict is BLOCKED rather than PASS.

What WAS verified, with real output in `test_reports/mf_holdings_dedupe_20261023.md`:

- Every view body in migration 182 was executed against real staging data, read-only, as a CTE
  chain generated mechanically from the migration file (no SQL retyped). All staging numbers in
  the report come from those runs: duplication 4.089x (2026-09; 3.687–4.312x across 13 months),
  measured coverage median 0.560 over 408 Nifty 500 names, HAL 25,923,551 vs 44,941,680 disclosed.
- The delta service's new SQL was executed read-only with its INSERT replaced by an aggregate over
  the same relation: 41,217 canonical rows / 665 funds for 2026-09, constant-panel net
  -2,024,089,172 against +2,706,537,881 with the panel guard removed and +28,935,385,865 pre-dedupe.
- Both migrations were applied TWICE to a throwaway local Postgres 16 over stub tables seeded with
  real staging rows: idempotent, and the restatement trigger, the panel-entry constraint, the
  coverage_pct relabel and the canonical grain all behave as specified.
- The CI reconciliation test passes with no database: 93 tests green, including a parity check
  that the Python rule reproduces the SQL view's staging numbers to the share.

To clear this override, on the NIDP VM:

    python -m nidp.cli migrate
    python -m nidp.services.mf_holdings_deltas --all
    python -m nidp.services.smart_money_scores        # refills coverage_pct with measured values

then re-run the report's staging queries against the real views rather than the CTE harness.
