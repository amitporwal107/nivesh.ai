# Test Cases (authored UP FRONT) — MF Holdings History + Delta Layer

- **Branch:** feat/provider-foundations
- **Date authored:** 2026-10-22 (before implementation)
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Scope:** MF disclosure/holdings *data* gap — 13-month backfill, per-AMC coverage
  tracking with catch-up retry, and the §20/§25 month-over-month delta layer.
  Out of scope this pass: scoring model (§21), scanner API (§24), UI (§23).

## Requirement trace

| Doc section | Requirement | Covered by |
|---|---|---|
| §4 / §20.1 | shares_delta, shares_pct_change (only when prior > 0), weight_delta_pp | TC-5, TC-6, TC-7 |
| §20.1 | `new_position` / `potential_exit` validated against **file coverage** | TC-8, TC-9 |
| §20.2 | breadth counts; group by AMC so one AMC is not "independent confirmation" | TC-10, TC-11 |
| §22 | freshness / coverage observability (which AMC-month is missing) | TC-3, TC-4 |
| §26.2 | two or more reporting periods reconcilable by stable scheme + ISIN keys | TC-2, TC-5 |
| §26.3 | share-count change computed separately from market-value change | TC-6 |
| §26.4 | new/exit validated against missing files and identifier changes | TC-8, TC-9 |
| §26.8 | missing/stale data lowers confidence, never silently treated as zero | TC-9, TC-12 |

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | migration | Apply migration 159 twice | api/idempotency | Second run is a no-op; `mf_holdings_coverage`, `mf_holdings_deltas`, `v_mf_accumulation_breadth` exist | PENDING |
| TC-2 | backfill | Run 13-month backfill (2025-09..2026-09) for the AdvisorKhoj AMCs | api | `mf_holdings_monthly` holds ≥ 12 distinct `as_of_month` values, each with > 0 rows | PENDING |
| TC-3 | coverage | Each attempted (amc_id, as_of_month) writes a coverage row | api | One row per attempted pair; `status` ∈ (OK, EMPTY, ERROR); `rows_written` matches holdings count | PENDING |
| TC-4 | coverage | Re-run backfill with `--only-missing` after a successful pass | api/idempotency | Pairs already OK are skipped (no refetch); run completes without rewriting them | PENDING |
| TC-5 | deltas | Compute deltas for a month pair where both months have the scheme | unit+api | `shares_delta = current_shares - previous_shares` exactly, for a hand-checked scheme/ISIN | PENDING |
| TC-6 | deltas | A holding whose market value rose but share count did not | edge | `shares_delta = 0` and `change_class='unchanged'` despite higher `market_value_inr` (§26.3) | PENDING |
| TC-7 | deltas | Prior shares = 0 or NULL | edge | `shares_pct_change` IS NULL (never divide by zero), `shares_delta` still populated | PENDING |
| TC-8 | deltas | ISIN absent in M-1 **but** the scheme was ingested in M-1 | edge | `change_class='new'`, `validation_status='validated'` | PENDING |
| TC-9 | deltas | ISIN absent in M-1 **and** the scheme had no M-1 file at all | failure | `change_class='unknown'`, `validation_status='coverage_gap'` — NOT reported as a new position (§26.4/§26.8) | PENDING |
| TC-10 | breadth | Breadth view for a widely held ISIN | api | `schemes_increasing` + `schemes_reducing` + `schemes_unchanged` equals the scheme count for that ISIN/month | PENDING |
| TC-11 | breadth | Breadth where all increasing schemes belong to one AMC | edge | `amcs_increasing = 1` and `single_amc_signal = true` so the UI cannot call it independent confirmation (§20.2) | PENDING |
| TC-12 | data trust | Holdings rows with NULL ISIN | edge | Excluded from deltas/breadth (cannot be reconciled to an instrument), and counted in a reported exclusion figure rather than dropped silently | PENDING |
| TC-13 | regression | Existing daily `mf_holdings` run still works unchanged | api | Running the service with no args targets last month and writes coverage rows | PENDING |

## Evidence requirements
- Real SQL output from `nidp_staging` (via `~/.config/nivesh/nidp-psql.sh`) for every DB claim.
- Real stdout from the backfill run on the NIDP VM for TC-2/TC-3/TC-4.
- TC-5..TC-9 verified by a query that recomputes the expectation independently and compares,
  not by eyeballing a few rows.

## Verdict: BLOCKED (authored before implementation; no runs yet)
