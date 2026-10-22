# Functionality verification — Smart Money paired B-vs-C evaluator

**Date** 2026-10-22 · **Target** staging (NIDP VM 45.64.105.224) · **Commit** `b4d521e5`
**Changed code** `backend/nidp/services/smart_money_study/{__init__,__main__,evaluator}.py` (new service)

No API routes and no frontend were touched, so there is no endpoint test and no Playwright run.
The verification is a real staging execution of the service against the real warehouse.

> Rerun after switching forward returns from raw `nidp.prices_eod` opens to
> `nidp.prices_eod_adjusted.adj_open`. The earlier corporate-action *exclusion* workaround has
> been removed; T6 is now verified at the source. Run ids below are the new ones.

## Test cases (authored before the run, from the five enforced requirements)

| # | Case | Expected |
|---|---|---|
| T1 | Frozen contract hashes | Both configs re-hashed and matched; abort on mismatch |
| T2 | Identical evaluation population | Same (date, symbol) pairs for B and C; ineligible rows persisted with a reason |
| T3 | No future information | Eligibility from sessions ≤ scoring date; deals strictly before it; PIT score series only |
| T4 | Incremental value measured as a paired difference | Per-date diff, not standalone returns |
| T5 | Failure is informative | Thin sample / inert feature / interval spanning the boundary → INCONCLUSIVE, never PASS |
| T6 | Forward returns are economically meaningful | Corporate actions inside a holding window priced off an adjusted series, not discarded |

## Real staging output

Command:
```
cd /opt/nidp/tl-run/backend && \
  /opt/nidp-staging/venv/bin/python -m nidp.services.smart_money_study --stage exploratory
```

```
NIDP-SM-VALIDATION-001: contract verified, hash 6bcd0fe4d048b8cd...
NIDP-SM-VALIDATION-002: contract verified, hash 1a4b7d6f20a55494...
smart_money_study: formation date 2025-12-12 excluded — no_baseline_scores
smart_money_study: formation date 2026-04-12 excluded — no_baseline_scores
smart_money_study: formation date 2026-07-12 excluded — no_baseline_scores
smart_money_study: formation date 2026-09-12 excluded — no_baseline_scores
smart_money_study: formation date 2026-10-12 excluded — only_6_sessions_forward
smart_money_study: formation date 2026-10-21 excluded — only_0_sessions_forward
smart_money_study: 9 formation date(s); horizon 20d; hurdle +1.00 pp; round-trip cost 0.4937%
smart_money_study 2026-01-12: B +2.13%  C +2.13%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-02-12: B -4.09%  C -4.09%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-03-12: B +1.02%  C +2.09%  diff +1.070 pp  (1/30 names changed)
smart_money_study 2026-04-13: B +3.38%  C +4.19%  diff +0.818 pp  (1/30 names changed)
smart_money_study 2026-05-12: B +5.16%  C +5.16%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-06-12: B +1.28%  C +1.28%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-07-13: B +0.56%  C +0.56%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-08-12: B +1.70%  C +1.78%  diff +0.082 pp  (2/30 names changed)
smart_money_study 2026-09-15: B +1.42%  C +1.42%  diff +0.000 pp  (0/30 names changed)
smart_money_study: persisted 45218 prediction rows, 540 outcome rows
smart_money_study VERDICT INCONCLUSIVE — 9 formation date(s) against study 001's review floor of
12 effectively independent blocks; the sample cannot support a promotion decision
```
```json
{ "run_id_b": "4faf3eaa-2b3f-4bbc-af4b-2fca627830bf",
  "run_id_c": "9c0eb9f6-be16-41e9-bbcd-b83ba7e0f82f",
  "horizon_sessions": 20, "hurdle_pp": 1.0, "round_trip_cost_pct": 0.4937,
  "portfolio_n": 30, "formation_dates_considered": 9, "formation_dates_used": 9,
  "mean_paired_diff_pp": 0.2189, "ci95_pp": [0.0, 0.5104],
  "portfolio_names_changed_total": 4, "prediction_rows": 45218, "outcome_rows": 540,
  "verdict": "INCONCLUSIVE", ... }
```

Summary read back **from the database**, not from stdout:
```
      study_id        | verdict       | mean_diff_pp | ci95_pp        | dates | cost
----------------------+---------------+--------------+----------------+-------+-------
NIDP-SM-VALIDATION-001| INCONCLUSIVE  | 0.2189       | [0.0, 0.5104]  | 9     | 0.4937
NIDP-SM-VALIDATION-002| INCONCLUSIVE  | 0.2189       | [0.0, 0.5104]  | 9     | 0.4937
```

## Case-by-case result

- **T1 PASS** — both hashes re-verified against the registered digests, shown above.
- **T2 PASS** — 45,218 prediction rows across 9 dates × 2 studies; the ineligible ones carry a
  reason (`below_liquidity_floor` 13,862 · `below_min_price` 1,072 · `no_price_on_date` 555 ·
  `no_baseline_score` 168 · `no_forward_window` 40 · `insufficient_history` 39). Eligible pairs
  match between studies exactly — measured, not assumed:
  ```
   b_eligible | c_eligible | joined | only_in_b | only_in_c
  ------------+------------+--------+-----------+-----------
         6873 |       6873 |   6873 |         0 |         0
  ```
- **T3 PASS** — `_UNIVERSE_SQL` bounds sessions with `as_of_date <= $1`; `_DEALS_SQL` uses
  `deal_date < $1`; scores are read with `point_in_time` true.
  `v_smart_money_lookahead_gap` on these nine dates shows the PIT and reporting-date series differ
  by **6.72–8.20** score points (corr **0.831–0.875**), confirming the PIT series is genuinely the
  constrained one.
- **T4 PASS** — the statistic is the per-date paired difference; the CI bootstraps whole
  formation dates (5,000 resamples, seed 20261022).
- **T5 PASS** — 9 < 12 blocks returned INCONCLUSIVE with the reason recorded. The inert-feature
  branch and the interval-spanning branch are present in `_finish` but were not the branch taken
  this run; only the sample-size branch is exercised by real data here.
- **T6 PASS** — forward returns now read `prices_eod_adjusted.adj_open`. Verified on the stored
  outcomes:
  ```
   rows_checked | match_adj_open | match_raw_open | discriminating_rows
  --------------+----------------+----------------+---------------------
            270 |            270 |            266 |                   4

     symbol   | entry_date | entry_price |  adj_open  | raw_open  | last_event_type
  ------------+------------+-------------+------------+-----------+-----------------
   ANANDRATHI | 2026-01-13 |   1564.9000 | 1564.90    | 3129.8000 | DIVIDEND
   KOTAKBANK  | 2026-01-13 |    425.3800 |  425.38    | 2126.9000 | SPLIT
   ANANDRATHI | 2026-03-13 |   1534.0000 | 1534.00    | 3068.0000 | DIVIDEND
   ANANDRATHI | 2026-05-13 |   1756.1000 | 1756.10    | 3512.2000 | DIVIDEND

   rows_total | artefact_rows (<= -50%) | worst_pct | best_pct
  ------------+-------------------------+-----------+----------
          540 |                       0 |    -26.30 |    39.38
  ```
  All 270 entry prices track the adjusted series; on the 4 rows where adjusted and raw disagree
  the adjusted value was stored. KOTAKBANK 2026-01-12 reads **+1.49%** (₹425.38 → ₹431.70) where
  the raw series gave −79.70%. No outcome row carries a corporate-action artefact signature.

## Defects found and fixed during verification

1. `Decimal * float` in `_deal_tilt` — client counts return `numeric` from `sum()`. Cast to int.
2. `KeyError: 'evidence_class'` — column missing from the score SELECT. Added.
3. Prediction tuple arity 14 vs 15 columns, shifting `eligible` to a string. Fixed.
4. `smart_money_shadow_predictions` PK is `(run_id, scoring_date, symbol)` — one model per run.
   Each study now gets its own run_id; the persisted summary on **both** rows carries
   `run_id_b` and `run_id_c`, so either row identifies the pair. The frozen schema was **not**
   altered.
5. `maturity` CHECK allows only `('pending','mature')`; `'complete'` was rejected. Fixed.
6. **Unadjusted corporate actions in forward returns.** First fixed by *excluding* affected
   symbol-days; that was the wrong fix, because `prices_eod_adjusted` already carries a corrected
   series. Now fixed at the source (T6). `prices_eod` is retained only for the trading calendar.
7. `NameError: _DEALS_SQL` — the patch that removed the exclusion workaround over-deleted and took
   the adjacent `_DEALS_SQL` constant with it. Restored; caught by the run failing, not by review.

## Not verified / out of scope

- **UNVERIFIED: benchmark-relative gates.** `benchmark_return_pct` and `sector_return_pct` are
  NULL in all 540 outcome rows (confirmed by query: `benchmark_populated 0`, `sector_populated 0`)
  — Nifty 500 TRI and the sector-relative benchmark are not computed yet. No benchmark gate from
  study 001 has been tested.
- **UNVERIFIED: the confirmatory stage.** This run is `exploratory` only.
- **UNVERIFIED: other backtests reading `prices_eod`.** The corporate-action bug is fixed in this
  service and nowhere else. Any other code taking a multi-week open/close difference from that
  table has it. Not audited.
- **Logged, not fixed:** the three ANANDRATHI adjustment rows above carry
  `last_event_type = 'DIVIDEND'` with an adjustment factor of exactly 2.0. The factor is right;
  the event label is almost certainly wrong. Returns here are unaffected, but anything filtering
  on `last_event_type` would misclassify these rows.

The study's own answer is INCONCLUSIVE — that is a finding about the data, not a test failure.
The service under test did what it was built to do, including refusing to call a thin sample a
success, and its five enforced rules were each demonstrated against real staging data.

## Verdict: PASS
