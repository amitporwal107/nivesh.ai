# Functionality Verification Report — Smart Money study return-integrity & completeness

- **Branch:** feat/provider-foundations
- **Date:** 2026-10-22
- **Author:** Claude (DOMAIN_EXPERT_ANALYST + FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging NIDP warehouse `nidp_staging` @ 45.64.105.224
- **Changed areas:** backend services: yes (`smart_money_study/evaluator.py` only) · frontend src: no
- **Test cases:** `test_reports/study_integrity_TESTCASES.md` (authored before implementation)
- **Frozen contracts:** UNCHANGED — `sha256sum` identical at session start and end, `git status` clean:
  ```
  9d3cde48a31b79e98d3509db41bd6ba2f80e40c25f180d1696e5a27f25984369  backend/nidp/studies/NIDP-SM-VALIDATION-001.json
  8b2ba2a855bd10837d7e9a4aa2732c8a38d026d61c815c10452ace6383075678  backend/nidp/studies/NIDP-SM-VALIDATION-002.json
  ```

## Summary

Four changes to `evaluator.py`: a per-symbol unexplained-move assertion that classifies every
`>=35%` in-window session and fails closed; entry/exit price, cost and paired-population gates;
`benchmark_return_pct` populated from the Nifty 500 price index (labelled a proxy) with
`sector_return_pct` left NULL and marked explicitly unavailable; and a rerun of the **unchanged**
frozen protocol writing a new run pair.

**The verdict did not move and was not supposed to.** Mean paired difference **+0.2189 pp**, 95%
date-block CI **[0.0000, +0.5104] pp**, against the unchanged **+1.00 pp** hurdle, on **9**
formation dates versus the preregistered floor of 12 → **INCONCLUSIVE**. Identical to the previous
run to six decimal places on every date. Study C remains in shadow mode.

The assertion excluded exactly two symbol-days, both ranked far outside the top 30 (VEDL 233,
TRIVENI 429), which is why the headline is unchanged. That is the honest result, not a null finding
I engineered: had VEDL's demerger landed in a window where it ranked 23 — as it did on 2026-01-12 —
a `-64.90%` artefact would have entered a portfolio return.

## Test Cases

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-1 | VEDL 2026-04-30 detected, `ca_adjustment_mismatch` | excluded | **PASS** |
| TC-2 | POLICYBZR 2026-09-24 intraday crash | KEPT | **PASS** |
| TC-3 | TATAMOTORS 2025-10-14, no CA row | fails closed | **PASS** |
| TC-4 | Reversal next session | excluded | **PASS** |
| TC-5 | Step spanning >1 session | excluded | **PASS** |
| TC-6 | `<35%` move | no detection | **PASS** |
| TC-7 | Recorded via existing `ineligible_reason` | prefixed reason | **PASS** |
| TC-8 | Exclusion symmetric across B and C | 0 differences | **PASS** |
| TC-9 | Counts in run summary | `integrity` block | **PASS** |
| TC-10 | Prices positive and equal `adj_open` | 100% | **PASS** |
| TC-11 | Window spans exactly 20 real sessions | 20/20 | **PASS** |
| TC-12 | Cost = contract total AND consistent with components | delta 6e-6 | **PASS** |
| TC-13 | Cost identical for B and C | 1 distinct value | **PASS** |
| TC-14 | B/C evaluation population identical | symmetric diff 0 | **PASS** |
| TC-15 | No `prices_eod_adjusted` join fan-out | 0 dup groups | **PASS** |
| TC-16 | `benchmark_return_pct` populated and correct | 540/540, cross-checked | **PASS** |
| TC-17 | Benchmark labelled a PROXY | `is_proxy: true` | **PASS** |
| TC-18 | `sector_return_pct` NULL + marked unavailable | 0/540, reason stored | **PASS** |
| TC-19 | Contracts re-hash; tampering aborts | both verified, abort raised | **PASS** |
| TC-20 | Existing audit trail untouched | 3/3 digests identical | **PASS** |
| TC-21 | Hurdle/floor/estimator unchanged | INCONCLUSIVE at n=9 | **PASS** |
| TC-22 | pytest no worse than 51/1281/5 | 51 failed, 1292 passed | **PASS** |

## Unit tests (staging container)

`docker exec -w /app/backend nidp-daas-api-staging sh -c "python -m pytest nidp/tests/services/test_study_move_integrity.py -v -p no:cacheprovider"`

```
============================= test session starts ==============================
platform linux -- Python 3.11.17, pytest-9.1.1, pluggy-1.6.0 -- /usr/local/bin/python
rootdir: /app/backend
plugins: anyio-4.15.1
collecting ... collected 11 items

nidp/tests/services/test_study_move_integrity.py::test_vedl_demerger_the_adjuster_never_applied_is_excluded PASSED [  9%]
nidp/tests/services/test_study_move_integrity.py::test_policybzr_intraday_crash_is_a_genuine_observation_and_is_kept PASSED [ 18%]
nidp/tests/services/test_study_move_integrity.py::test_unrecorded_corporate_action_fails_closed PASSED [ 27%]
nidp/tests/services/test_study_move_integrity.py::test_bad_print_that_reverses_next_session_is_excluded PASSED [ 36%]
nidp/tests/services/test_study_move_integrity.py::test_reversal_is_not_declared_on_a_mild_bounce PASSED [ 45%]
nidp/tests/services/test_study_move_integrity.py::test_gap_spanning_step_is_not_called_a_single_session_move PASSED [ 54%]
nidp/tests/services/test_study_move_integrity.py::test_an_up_move_is_screened_too PASSED [ 63%]
nidp/tests/services/test_study_move_integrity.py::test_no_disposition_falls_through_silently PASSED [ 72%]
nidp/tests/services/test_study_move_integrity.py::test_intraday_boundary_is_the_documented_fraction PASSED [ 81%]
nidp/tests/services/test_study_move_integrity.py::test_threshold_is_the_preregistered_35_pct PASSED [ 90%]
nidp/tests/services/test_study_move_integrity.py::test_frozen_cost_total_is_checked_against_its_own_components PASSED [100%]

============================== 11 passed in 0.06s ==============================
```

### Regression against the deployed baseline

`docker exec -w /app/backend nidp-daas-api-staging sh -c "python -m pytest nidp/tests -q -p no:cacheprovider"`

Before my files were deployed (baseline):
```
51 failed, 1281 passed, 5 skipped, 23 warnings in 10.45s
```
After:
```
51 failed, 1292 passed, 5 skipped, 23 warnings in 10.59s
```
Failures unchanged at 51; passes up by exactly the 11 tests added. **No regression.**

## Task 1 — unexplained-move assertion: what it found on the real run

**52 detections** across the 9 holding windows, **1 kept**, **51 excluded**, every one recorded with
its disposition in the run summary.

```
    "dispositions": {
        "genuine_market_move": 1,
        "trading_gap_discontinuity": 32,
        "unexplained_gap_undetermined": 2,
        "ca_adjustment_mismatch:RIGHTS": 2,
        "ca_adjustment_mismatch:BUYBACK": 1,
        "ca_adjustment_mismatch:DEMERGER": 3,
        "ca_adjustment_mismatch:DIVIDEND": 9,
        "ca_adjustment_mismatch:BONUS,SPLIT": 1,
        "ca_adjustment_mismatch:BONUS,DIVIDEND": 1
    },
    "threshold_pct": 35.0,
    "picked_contaminated": 0,
    "excluded_symbol_days": 2,
    "benchmark_missing_dates": [],
    "price_assertion_failures": []
```

The notable dispositions in full:

```
     sd     |    sym     | move_date  | spanned | move_pct | gap_pct |    ca    |           disposition           | kept
------------+------------+------------+---------+----------+---------+----------+---------------------------------+-------
 2026-01-12 | BIOFILCHEM | 2026-02-02 | 1       | 43.98    | 33.29   |          | unexplained_gap_undetermined    | false
 2026-01-12 | UFBL       | 2026-02-02 | 1       | 39.36    | 21.41   |          | unexplained_gap_undetermined    | false
 2026-04-13 | VEDL       | 2026-04-30 | 1       | -64.9    | -62.58  | DEMERGER | ca_adjustment_mismatch:DEMERGER | false
 2026-07-13 | TRIVENI    | 2026-08-05 | 11      | -50.1    | -45.92  | DEMERGER | ca_adjustment_mismatch:DEMERGER | false
 2026-09-15 | INDIAGLYCO | 2026-09-17 | 11      | -77.63   | -77.03  | DEMERGER | ca_adjustment_mismatch:DEMERGER | false
 2026-09-15 | POLICYBZR  | 2026-09-24 | 1       | -36.0    | -10.0   |          | genuine_market_move             | true
```

### VEDL — the reference case

Detected on the 2026-04-13 window (entry 2026-04-15, exit 2026-05-13), which contains its
2026-04-30 demerger. The real rows:

```
   symbol   | as_of_date | raw_open  | raw_high  |  raw_low  | raw_close | raw_volume |  adj_close  |    adjf
 VEDL       | 2026-04-29 |  745.0000 |  780.0000 |  732.2000 |  773.6000 |   54738724 |  773.600000 | 1.00000000
 VEDL       | 2026-04-30 |  289.5000 |  292.0000 |  268.7000 |  271.5500 |   73870853 |  271.550000 | 1.00000000
```

A `DEMERGER` row exists in `nidp.corporate_actions` with `ex_date = 2026-04-30`, yet
`cumulative_adj_factor` is still `1.0` and the full `-64.90%` survives into `adj_close` — the
adjuster never applied it. Disposition `ca_adjustment_mismatch:DEMERGER`, **excluded**.
`last_event_type` reads `DIVIDEND` with `last_event_ex_date = 2026-10-14` on this symbol, which is
why the classifier does not rely on that column.

**Confirmed calendar luck, with the ranks to prove it.** VEDL was picked on **2026-01-12 at
tilted_rank 23 of 30** in both studies, and its stored outcome there is `631.10 -> 695.00`,
`+9.63%` net — a clean window that ends 2026-02-11, before the demerger. On 2026-04-13, the date
whose window *does* contain 2026-04-30, it ranked **233 (B) / 231 (C)**. Nothing in the protocol
prevented the opposite ordering.

### Why the exclusion is applied pre-ranking, to the whole eligible universe

The brief asks for "every picked symbol". Screening only picked symbols would let a disposition
drop a name from B's portfolio and not C's, breaking the pairing that requirement 1 exists to
protect. A disposition depends on `(date, symbol)` alone, so it is computed for the eligible
universe before ranking and fed into the **existing** `ineligible_reason` mechanism — no parallel
table. That is strictly stronger than the requirement and symmetric by construction:

```
        study_id        | scoring_date | symbol  | eligible |                ineligible_reason
 NIDP-SM-VALIDATION-001 | 2026-04-13   | VEDL    | f        | unexplained_move:ca_adjustment_mismatch:DEMERGER
 NIDP-SM-VALIDATION-002 | 2026-04-13   | VEDL    | f        | unexplained_move:ca_adjustment_mismatch:DEMERGER
 NIDP-SM-VALIDATION-001 | 2026-07-13   | TRIVENI | f        | unexplained_move:ca_adjustment_mismatch:DEMERGER
 NIDP-SM-VALIDATION-002 | 2026-07-13   | TRIVENI | f        | unexplained_move:ca_adjustment_mismatch:DEMERGER
```

Only these two detections fell on symbols that were otherwise eligible; the other 50 were already
excluded by the liquidity rule. `picked_contaminated: 0` — no contaminated window reached a
portfolio, before or after the change.

### Genuine moves are kept, not deleted

The discriminator was measured on real rows before it was written: a re-pricing arrives overnight
(VEDL opened `-62.58%` into a `-64.90%` session) while a genuine crash opens near the prior close
and travels intraday (POLICYBZR 2026-09-24 opened `-10.00%` into a `-36.00%` session, on 11x
volume, with no corporate-action row). POLICYBZR is classified `genuine_market_move` and **kept**.

### One finding worth flagging

A naive `lag()` over a symbol's own rows reports a suspended stock's resumption gap as a
one-session crash. **32 of 52** detections span more than one market session (ABANSENT's "-45.25%
session" is a 3-month gap). Taking sessions from the `prices_eod` calendar is what separates the
2 real contaminations from the 50 artefacts of sparse trading.

## Task 2 — price, cost and pairing validation

```
        study_id        | rows | entry_is_adj_open | exit_is_adj_open | non_positive | distinct_costs |   cost   | wrong_horizon
 NIDP-SM-VALIDATION-001 |  270 |               270 |              270 |            0 |              1 | 0.493700 |             0
 NIDP-SM-VALIDATION-002 |  270 |               270 |              270 |            0 |              1 | 0.493700 |             0
```

Window span against the real calendar — 20 sessions on every date, both ends real sessions:

```
 scoring_date | entry_date | exit_date  | sessions_spanned | entry_is_session | exit_is_session
 2026-01-12   | 2026-01-13 | 2026-02-11 |               20 |                1 |               1
 2026-02-12   | 2026-02-13 | 2026-03-13 |               20 |                1 |               1
 2026-03-12   | 2026-03-13 | 2026-04-15 |               20 |                1 |               1
 2026-04-13   | 2026-04-15 | 2026-05-13 |               20 |                1 |               1
 2026-05-12   | 2026-05-13 | 2026-06-10 |               20 |                1 |               1
 2026-06-12   | 2026-06-15 | 2026-07-13 |               20 |                1 |               1
 2026-07-13   | 2026-07-14 | 2026-08-10 |               20 |                1 |               1
 2026-08-12   | 2026-08-13 | 2026-09-09 |               20 |                1 |               1
 2026-09-15   | 2026-09-16 | 2026-10-14 |               20 |                1 |               1
```

No join fan-out risk (`prices_eod_adjusted` PK is `(symbol, as_of_date, source)`):
```
 dup_symbol_date_groups
                      0
```

**Cost — 0.4937 confirmed against the contract, and against the contract's own schedule.**
`NIDP-SM-VALIDATION-001.cost_model.round_trip_total_pct` is `0.4937`. Reading that total alone
would not notice if it had been edited away from the components it summarises, so it is now
recomputed from `per_side_pct` + 18% GST on the taxable components + buy-only stamp duty:

```
smart_money_study: cost schedule 0.4937% round trip, consistent with its components (0.493706%)
round_trip_cost_pct from frozen contract = 0.4937
TAMPER CHECK: aborted as required -> NIDP-SM-VALIDATION-001: stored config does not match its preregistered hash (recomputed 6bcd0fe
```

**B and C are measured on an identical evaluation population — asserted, not assumed.** Checked
both in-process on the rows being written and independently in SQL on the stored rows:

```
    "paired_population": {
        "identical": true,
        "in_b_not_c": 0,
        "in_c_not_b": 0,
        "b_symbol_days": 22609,
        "c_symbol_days": 22609,
        "eligibility_or_reason_disagreements": 0
    }
```

SQL cross-check on the stored predictions (new run): `in_b_not_c 0, in_c_not_b 0, disagree 0,
b_rows 22609`. On the *previous* run the same check also returns 0/0/0/0 across 22,609 rows with
`baseline_mismatch 0`, so **the pairing was valid before this change as well** — reported either
way, as asked. The paired estimate is valid.

The two portfolios do differ in membership by 4 slots across 270, which is the experiment, not an
asymmetry: the evaluated population is identical and only the ranking differs.

## Task 3 — benchmark populated; sector explicitly unavailable

**Benchmark: POPULATED.** 540/540 rows, 9 distinct values, cross-checked against an independent
recomputation from `nidp.index_eod`:

```
 scoring_date | stored_bench | recomputed | match
 2026-01-12   |       0.8670 |     0.8670 | t
 2026-02-12   |      -7.1878 |    -7.1878 | t
 2026-03-12   |       3.4172 |     3.4172 | t
 2026-04-13   |      -0.9544 |    -0.9544 | t
 2026-05-12   |       0.3806 |     0.3806 | t
 2026-06-12   |       1.0411 |     1.0411 | t
 2026-07-13   |       2.1411 |     2.1411 | t
 2026-08-12   |      -2.7996 |    -2.7996 | t
 2026-09-15   |      -1.9979 |    -1.9979 | t
```

`Nifty 500`, open-to-open over the identical window, 190 rows in the study range with zero null
opens, present on all 9 entry and all 9 exit sessions. **Labelled a PROXY**: no total-return series
exists in this warehouse — re-verified this session, the only `*TR*` index names are
`Nifty 50 Futures TR Index`, `Nifty50 TR 1x Inverse` and `Nifty50 TR 2x Leverage`, all Nifty-50
derivatives, not a Nifty 500 TRI. The price index understates the benchmark by the dividend yield
(~0.1 pp over 20 sessions). This matches `NIDP-SM-VALIDATION-001.benchmark.primary_implemented`,
which already contracted this deviation.

**Sector: LEFT NULL, marked UNAVAILABLE.** 0/540. It cannot be computed point-in-time:

- `nidp.index_constituents` has **4 snapshots, all 2026-10-12 .. 2026-10-22** — after every
  formation date. Resolving `industry` as of each scoring date returns NULL for **274 of 274**
  pick symbol-days.
- `nidp.sector_master` carries `sector_resolved_at` in the same October window
  (2026-10-12 .. 2026-10-21) and is sparse: only **91/123** picked symbols have a `sector`,
  **84/123** an `industry`.
- The 21+ sector indices have open prices, but mapping a symbol to one still needs a
  point-in-time sector label, and several start mid-2026 (`Nifty Capital Goods` from 2026-06-15),
  so they do not cover the early windows.

Labelling January–September windows from an October snapshot would inject exactly the look-ahead
and survivorship bias that 001's own `universe_rule.note` rejects, and requirement 2 forbids. A
wrong sector benchmark is worse than an absent one, so the column is NULL and the run summary
carries `"status": "UNAVAILABLE"` with this reason. **No sector-relative conclusion is available
from this run.** (`DUMMYHEG`, the Nifty 500 placeholder with 0 price rows, is moot as a result; it
has no price row to join and never enters a return.)

## Task 4 — rerun of the unchanged frozen protocol

New run pair, written alongside the existing audit trail:

```
                run_id                |        study_id        |    stage    | status |            started_at
 43a0e16c-d381-420b-8cf1-084caea77b8c | NIDP-SM-VALIDATION-001 | exploratory | OK     | 2026-10-22 09:07:36.166599+05:30
 a4d964f7-3ae9-48de-8b88-1f17da517925 | NIDP-SM-VALIDATION-002 | exploratory | OK     | 2026-10-22 09:07:36.173067+05:30
```

Configuration hashes, re-verified before any data read:
```
NIDP-SM-VALIDATION-001: contract verified, hash 6bcd0fe4d048b8cd...
NIDP-SM-VALIDATION-001: prereg_sha256=6bcd0fe4d048b8cd018d68c85ad4b1751146cfca6b4b0ce17b6018a93d0e024b
  horizon=20 hurdle_pp=1.000
NIDP-SM-VALIDATION-002: contract verified, hash 1a4b7d6f20a55494...
NIDP-SM-VALIDATION-002: prereg_sha256=1a4b7d6f20a55494ee53c6b3394d4121435c019d13a90a962157e11c6e777838
  horizon=20 hurdle_pp=1.000
```

### Per-date paired differences, new run vs previous run

```
    date    | new_elig | old_elig |  b_net  |  c_net  | new_diff_pp | old_diff_pp | names_chg
 2026-01-12 |      650 |      650 |  2.1285 |  2.1285 |    0.000000 |    0.000000 | 0
 2026-02-12 |      704 |      704 | -4.0916 | -4.0916 |    0.000000 |    0.000000 | 0
 2026-03-12 |      681 |      681 |  1.0193 |  2.0895 |    1.070160 |    1.070160 | 1
 2026-04-13 |      783 |      784 |  3.3758 |  4.1936 |    0.817729 |    0.817729 | 1
 2026-05-12 |      797 |      797 |  5.1645 |  5.1645 |    0.000000 |    0.000000 | 0
 2026-06-12 |      801 |      801 |  1.2815 |  1.2815 |    0.000000 |    0.000000 | 0
 2026-07-13 |      826 |      827 |  0.5619 |  0.5619 |    0.000000 |    0.000000 | 0
 2026-08-12 |      798 |      798 |  1.6978 |  1.7802 |    0.082406 |    0.082406 | 2
 2026-09-15 |      831 |      831 |  1.4181 |  1.4181 |    0.000000 |    0.000000 | 0
```

The eligible count falls by exactly 1 on 2026-04-13 (VEDL) and 1 on 2026-07-13 (TRIVENI) and is
unchanged elsewhere. Both sat around rank 230/429, so no top-30 slot changed and every paired
difference is identical to six decimals. Six of the nine differences remain exactly zero: the deal
feature crosses the top-30 boundary only 4 times in 270 slots.

### Verdict

```
    "verdict": "INCONCLUSIVE",
    "verdict_reason": "9 formation date(s) against study 001's review floor of 12 effectively independent blocks; the sample cannot support a promotion decision",
    "mean_paired_diff_pp": 0.2189,
    "ci95_pp": [0.0, 0.5104],
    "hurdle_pp": 1.0,
    "round_trip_cost_pct": 0.4937,
    "horizon_sessions": 20,
    "portfolio_n": 30,
    "formation_dates_considered": 9,
    "formation_dates_used": 9,
    "portfolio_names_changed_total": 4,
    "outcome_rows": 540,
    "prediction_rows": 45218
```

**INCONCLUSIVE — unchanged, and correct.** +0.2189 pp against a +1.00 pp hurdle on 9 of a required
12 dates. The hurdle, the estimator, the horizon, the formation dates and both frozen
configurations are untouched. Study C stays in shadow mode.

### Existing audit trail not overwritten

Digests taken before the rerun and recomputed after, byte-identical:

```
           t           | rows  |              digest
 outcomes              |   540 | 3bcb7f2395b8638a920371cae608ccfc
 predictions           | 45218 | 5bee3f62c0d62dbe42c5473231b222e4
 runs(pre-existing 16) |    16 | 066aa6e5098e5d13f1c0a03f3862dd07
```

Before the rerun the table held 1,620 outcome rows across 6 runs with `benchmark_return_pct` and
`sector_return_pct` populated on 0 — matching the brief. The rerun **added** 540 rows and 2 runs.

## Inputs required from user

- none

## UNVERIFIED / caveats

1. **UNVERIFIED: the `code_commit` on the new run does not pin the code that produced it.** It
   records `72a9243c6dce323c3e586be45fd6daf8f584baaf`, which is `git rev-parse HEAD` in
   `/opt/nidp/dev-repo/nivesh.ai` (branch `dev`). My change is deliberately uncommitted per
   instruction, so the recorded commit predates it. The *config* hashes are exact; the code hash is
   not. Committing the evaluator would close this.
2. **Deployed copies left on the NIDP VM.** `evaluator.py` was streamed to
   `/opt/nidp/tl-run/backend/...` (service entry point) and
   `/opt/nidp/dev-repo/nivesh.ai/backend/...` (bind-mounted into `nidp-daas-api-staging` for
   pytest), plus the new test file into dev-repo. md5 `759e0479...` matches the working tree on all
   three. `dev-repo` was a clean checkout of `dev` before this, so **another session will see it
   dirty** — flagging rather than reverting, because reverting would make the evidence above
   non-reproducible.
3. **UNVERIFIED: the `unexplained_gap_undetermined` pair are not individually adjudicated.**
   BIOFILCHEM (+43.98%, gap 33.29) and UFBL (+39.36%, gap 21.41) both sit just past the 50%
   intraday boundary and were already ineligible on liquidity, so neither affects any result. I did
   not establish what actually happened to them; they are excluded by design, which is the
   fail-closed outcome, not a conclusion about the companies.
4. **The brief's "19 symbols" figure did not reproduce at that exact value.** Measured this
   session: 39 detections / 38 symbols on the adjusted series unrestricted by calendar adjacency,
   and 93 consecutive-session falls `>=35%` with `cumulative_adj_factor = 1.0` on raw
   `prices_eod` (`series IN ('EQ','BE')`) across full history. My detector is a superset of any of
   these readings, which is the safe direction, but I could not reconcile to 19 and did not try to
   force it.
5. **Scope of the fix.** Only this evaluator is hardened. Per commit `000336e5`'s own note, other
   backtests in this repo that take a multi-week open/close difference from `prices_eod` remain
   unaudited, and the underlying price adjuster is still incomplete — this change detects its
   failures rather than fixing them. 17 of 52 detections are corporate actions the adjuster did not
   apply, including 9 labelled `DIVIDEND`, which is a data-quality backlog item, not a study
   finding.

## Verdict: PASS
