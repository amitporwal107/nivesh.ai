# Test Cases — Smart Money study return-integrity & completeness hardening

- **Branch:** feat/provider-foundations
- **Date authored:** 2026-10-22 (BEFORE implementation, per `.claude/VERIFICATION_PROTOCOL.md`)
- **Author:** Claude (DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **File under change:** `backend/nidp/services/smart_money_study/evaluator.py`
- **Frozen, MUST NOT change:** `backend/nidp/studies/NIDP-SM-VALIDATION-001.json`, `...-002.json`
- **Environment:** staging NIDP warehouse (`nidp_staging` on 45.64.105.224)

## Scope

Four tasks: (1) per-symbol unexplained-move assertion that fails closed, (2) entry/exit
price + cost + paired-population validation, (3) benchmark / sector-relative returns
populated or explicitly marked unavailable, (4) rerun the **unchanged** frozen protocol
and report. Study C stays in shadow mode. The verdict is whatever the evidence says.

## Design under test

Disposition ladder for a detected `>=35%` single-step move in the ADJUSTED series inside
`entry_date..exit_date` inclusive. Detection basis is `nidp.prices_eod_adjusted.adj_close`
on **calendar-adjacent** observations, so "single session" means one market session, not
"the symbol's previous surviving row".

| disposition | evidence rule | result |
|---|---|---|
| `ca_adjustment_mismatch` | a `nidp.corporate_actions` row has `ex_date` in `(prev_date, move_date]` yet the adjusted series still jumps | EXCLUDE |
| `data_error_reversal` | next session reverses >= 60% of the move | EXCLUDE |
| `trading_gap_discontinuity` | the step spans more than one market session (symbol did not trade) | EXCLUDE |
| `genuine_market_move` | consecutive session, no CA row, no reversal, and the overnight open gap is <= 50% of the move, i.e. the move was travelled **intraday** | **KEEP** |
| `unexplained_gap_undetermined` | anything else — a clean overnight ratio gap with no corroborating action row | EXCLUDE (fail closed) |

Rationale for the `genuine` test, measured on real rows before coding: a capital-structure
event prices in overnight (VEDL open gap `-62.58%` of a `-64.90%` move), whereas a genuine
crash opens near the prior close and travels intraday (POLICYBZR open gap `-10.00%` of a
`-36.00%` move).

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Task 1 | VEDL 2026-04-30 (`DEMERGER` row present, `cumulative_adj_factor=1.0`, adjusted series still `-64.90%`) is detected inside the 2026-04-13 window | unit | detected; disposition `ca_adjustment_mismatch`; `keep=False` | PASS |
| TC-2 | Task 1 | POLICYBZR 2026-09-24 `-36.00%` intraday crash, no CA row | unit | disposition `genuine_market_move`; `keep=True` — a valid observation, NOT dropped | PASS |
| TC-3 | Task 1 | TATAMOTORS 2025-10-14 `-40.15%` overnight gap, NO corporate-action row | unit | disposition `unexplained_gap_undetermined`; `keep=False` (fails closed, not silently kept) | PASS |
| TC-4 | Task 1 | A move whose next session reverses it (bad print) | unit | disposition `data_error_reversal`; `keep=False` | PASS |
| TC-5 | Task 1 | A step spanning >1 market session (suspended symbol, e.g. TRIVENI 2026-08-05 spanning 11) | unit | disposition `trading_gap_discontinuity`; `keep=False` | PASS |
| TC-6 | Task 1 | A `<35%` move | unit | no detection at all | PASS |
| TC-7 | Task 1 | Detections are recorded, never silently dropped: every excluded symbol-day lands in `smart_money_shadow_predictions.ineligible_reason` using the EXISTING mechanism (no parallel table) | api | reason string prefixed `unexplained_move:<disposition>` | PASS |
| TC-8 | Task 1 | The exclusion is applied symmetrically, pre-ranking, so it can never make B and C differ | api | identical ineligible set for both studies | PASS |
| TC-9 | Task 1 | Counts surfaced in the run summary | api | `integrity` block with per-disposition counts | PASS |
| TC-10 | Task 2 | Every stored entry/exit price is `> 0` and equals `nidp.prices_eod_adjusted.adj_open` on that date | data | 100% match, 0 non-positive | PASS |
| TC-11 | Task 2 | `entry_date`/`exit_date` are real market sessions and the window spans exactly `horizon_sessions` (20) | data | 20 for all dates | PASS |
| TC-12 | Task 2 | `round_trip_cost_pct` equals the frozen contract's `cost_model.round_trip_total_pct` (0.4937) AND that total is internally consistent with the contract's own per-side components + GST + buy-only stamp duty | unit | abs delta <= 1e-4 | PASS |
| TC-13 | Task 2 | The cost is applied identically to B and C | data | one distinct `cost_pct` across both studies | PASS |
| TC-14 | Task 2 | B and C share an **identical** evaluation population (same dates, same symbols, same eligibility, same reasons) — asymmetry would invalidate the paired estimate | data | symmetric difference 0; eligibility disagreement 0 | PASS |
| TC-15 | Task 2 | `prices_eod_adjusted` join cannot fan out (PK is `(symbol, as_of_date, source)`) | data | 0 duplicate `(symbol, as_of_date)` groups | PASS |
| TC-16 | Task 3 | `benchmark_return_pct` populated from a real index series over the same open-to-open window | data | 100% of outcome rows non-NULL | PASS |
| TC-17 | Task 3 | No true broad-market TRI exists, so the benchmark is labelled a PROXY in the run summary and the report | unit | `benchmark_is_proxy=True` + named deviation | PASS |
| TC-18 | Task 3 | `sector_return_pct` cannot be computed point-in-time (`index_constituents` has 4 snapshots, all Oct-2026; `sector_master.sector_resolved_at` is Oct-2026) → left NULL and marked explicitly unavailable, NOT back-filled with a look-ahead label | data | 100% NULL + `sector_relative: "unavailable"` with reason | PASS |
| TC-19 | Task 4 | The frozen contracts re-hash equal to their preregistered digests; a tampered contract aborts | unit | both hashes verified; `StudyContractError` on mismatch | PASS |
| TC-20 | Task 4 | The rerun writes a NEW run pair and does not overwrite or alter the existing audit trail (runs `4faf3eaa…` / `9c0eb9f6…`) | data | prior rows byte-identical after the rerun | PASS |
| TC-21 | Task 4 | Verdict is driven by evidence only: hurdle still `+1.00` pp, floor still 12 dates, estimator unchanged | unit | `INCONCLUSIVE` while n=9 < 12 | PASS |
| TC-22 | Regression | `nidp/tests` suite no worse than the deployed baseline of 51 failed / 1281 passed / 5 skipped | unit | failures <= 51 | PASS |

## Non-goals / explicitly out of scope

- Promoting study C out of shadow mode (forbidden).
- Changing the hurdle, the estimator, the formation dates or the frozen configs.
- Touching any file outside `evaluator.py` + these two report files.

## Verdict: PASS
<!-- Evidence lives in test_reports/study_integrity_20261022.md — all 22 cases green there. -->
