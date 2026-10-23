# Functionality Verification Report — ScanX MF-holdings canonical coverage extension

- **Branch:** `feat/mf-holdings-scanx-coverage` (migration 184), rebased (cherry-picked) onto current `dev` @ `74a20627`
- **Date:** 2026-10-23
- **Author:** Claude (orchestrator), independently re-verifying a subagent's work after rebase
- **Environment:** staging (`nidp_staging` real warehouse for data checks; `nivesh-staging-app-backend` container for pytest)
- **Changed areas:** backend services/migrations only — no routes, no frontend

## Summary

Extends MF-holdings coverage from 11 AMCs (`nidp.mf_holdings_monthly`, AdvisorKhoj-sourced) to 51 AMCs by
additively wiring in `nidp.scanx_mf_holdings` (already ingested, migrations 179/180, never previously used)
for the ~40 AMCs the AMC-file side does not cover. Purely additive: `nidp.v_mf_holdings_canonical`,
`nidp.mf_holdings_deltas`, and `nidp.smart_money_scores_daily.coverage_pct` are untouched. New views only:
`nidp.v_scanx_amc_id`, `nidp.v_mf_holdings_canonical_scanx`, `nidp.v_mf_holdings_canonical_ext`,
`nidp.v_mf_stock_shares_monthly_ext`, `nidp.v_mf_stock_coverage_ext`, plus `nidp.base_scheme_name()`.

Migration 184 applied to the real `nidp_staging` warehouse this session (via `nidp.schema_migrations`,
applied_at `2026-10-23 21:39:51+05:30`) and independently verified against live data, not just the
subagent's self-report.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| V-1 | DB | ScanX AMC-name → `amc_id` mapping | data | 51 names, 0 unmatched, 0 collisions | PASS (reproduced independently) |
| V-2 | DB | Coverage before (11 AMCs, Nifty 500, Sept 2026, n=408) | data | median 0.5598 / mean 0.5340 | PASS (reproduced to 4dp) |
| V-3 | DB | Coverage after (51 AMCs, same cohort) | data | median 0.9473 / mean 0.9181, 405/408 ≤1.05x | PASS (reproduced to 4dp) |
| V-4 | DB | Names exceeding 1.05x | data | DRREDDY 1.1389, ICICIBANK 1.0848, ASHOKLEY 1.0666 | PASS (exact match) |
| V-5 | DB | Sundaram Finance (`INE660A01013`) real Trendlyne deltas | data | 7/8 exact matches via `scanx_mf_holdings` | PASS (verified directly from raw table before migration existed) |
| V-6 | unit | Reconciliation + new ScanX coverage test suite | unit | no regressions | PASS |
| V-7 | DB | Migration 184 applied to real warehouse, idempotent record | data | row in `nidp.schema_migrations` | PASS |

## API / Endpoint Tests

Not applicable — no new routes in this change (data-layer only, per the task's explicit scope; wiring into
`mf_holdings_deltas`/`smart_money_scores_daily`/any router is deliberately out of scope and documented in the
migration's own trailing comment as follow-up work).

## Data Correctness (staging, real queries this session)

```
-- V-1
total_scanx_amcs=51, mapped_rows=51, distinct_amc_names_mapped=51, collisions=0

-- V-2 (before, existing v_mf_stock_coverage, Nifty 500 n=408, 2026-09)
n=408 median=0.55975 mean=0.53396519607843137255 within_1.05=408

-- V-3 (after, replicated v_mf_stock_coverage_ext logic inline, same cohort)
n=408 median=0.9472833206384703 mean=0.91812879045894013652 within_1.05=405

-- V-4
DRREDDY 1.1389 | ICICIBANK 1.0848 | ASHOKLEY 1.0666

-- post-apply, live view sanity
nidp.v_mf_holdings_canonical_ext (2026-09-01): 98,146 rows across 51 amc_id groups (non-zero, sane per-AMC counts)
nidp.v_mf_stock_coverage_ext avg (all months, unrestricted): 0.9271 — consistent with the scoped 0.9181
```

## pytest (combined, this exact rebased code)

```
$ docker exec nivesh-staging-app-backend python -m pytest \
    nidp/tests/services/test_mf_holdings_scanx_coverage.py \
    nidp/tests/services/test_mf_holdings_reconciliation.py \
    nidp/tests/services/test_daas_smart_money.py -q
........................................................................ [ 85%]
............                                                             [100%]
84 passed, 1 warning in 2.06s
```

## Known caveat (not a blocker, flagged for follow-up)

`nidp.v_mf_holdings_canonical_ext` is slow at full, unscoped scale — a plain `count(*)` with no month
filter timed out past 120s. The `amc_id NOT IN (SELECT DISTINCT amc_id FROM nidp.v_mf_holdings_canonical)`
exclusion isn't scoped by month and re-scans the full 11-AMC history per query. Not a correctness issue —
every query in this report that scoped to a single month/cohort ran fast — but should be addressed
(e.g. materializing the amc exclusion set, or indexing) before anything wires this view into a live
endpoint.

## Verdict: PASS
