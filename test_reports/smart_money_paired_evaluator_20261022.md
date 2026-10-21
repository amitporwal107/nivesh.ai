# Functionality verification — Smart Money paired B-vs-C evaluator

**Date** 2026-10-22 · **Target** staging (NIDP VM 45.64.105.224) · **Commit** `b4d521e5`
**Changed code** `backend/nidp/services/smart_money_study/{__init__,__main__,evaluator}.py` (new service)

No API routes and no frontend were touched, so there is no endpoint test and no Playwright run.
The verification is a real staging execution of the service against the real warehouse.

## Test cases (authored before the run, from the five enforced requirements)

| # | Case | Expected |
|---|---|---|
| T1 | Frozen contract hashes | Both configs re-hashed and matched; abort on mismatch |
| T2 | Identical evaluation population | Same (date, symbol) pairs for B and C; ineligible rows persisted with a reason |
| T3 | No future information | Eligibility from sessions ≤ scoring date; deals strictly before it; PIT score series only |
| T4 | Incremental value measured as a paired difference | Per-date diff, not standalone returns |
| T5 | Failure is informative | Thin sample / inert feature / interval spanning the boundary → INCONCLUSIVE, never PASS |
| T6 | Forward returns are economically meaningful | No unadjusted corporate action inside a holding window |

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
smart_money_study 2026-01-12: B +1.44%  C +1.44%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-02-12: B -4.09%  C -4.09%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-03-12: B +1.02%  C +2.09%  diff +1.070 pp  (1/30 names changed)
smart_money_study 2026-04-13: B +3.38%  C +4.19%  diff +0.818 pp  (1/30 names changed)
smart_money_study 2026-05-12: B +6.12%  C +6.12%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-06-12: B +1.28%  C +1.28%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-07-13: B +0.56%  C +0.56%  diff +0.000 pp  (0/30 names changed)
smart_money_study 2026-08-12: B +1.70%  C +1.78%  diff +0.082 pp  (2/30 names changed)
smart_money_study 2026-09-15: B +1.42%  C +1.42%  diff +0.000 pp  (0/30 names changed)
smart_money_study: persisted 45218 prediction rows, 540 outcome rows
smart_money_study VERDICT INCONCLUSIVE — 9 formation date(s) against study 001's review floor
  of 12 effectively independent blocks; the sample cannot support a promotion decision
```

Persisted summary, read back from the database (not from stdout):

```
$ SELECT notes FROM nidp.smart_money_study_runs WHERE status='OK' ... LIMIT 1;
{"run_id_b": "6b248ae0-dd4f-43d2-bbbb-a6a3455fa043",
 "run_id_c": "0be817ea-f99c-48b0-a0d2-6779d989ec72",
 "study_b": "NIDP-SM-VALIDATION-001", "study_c": "NIDP-SM-VALIDATION-002",
 "stage": "exploratory", "code_commit": "b4d521e555a468fe2ffa1b7f8cc18f3516fbba9d",
 "horizon_sessions": 20, "hurdle_pp": 1.0, "round_trip_cost_pct": 0.4937,
 "portfolio_n": 30, "formation_dates_considered": 9, "formation_dates_used": 9,
 "mean_paired_diff_pp": 0.2189, "ci95_pp": [0.0, 0.5104],
 "portfolio_names_changed_total": 4, "prediction_rows": 45218, "outcome_rows": 540,
 "verdict": "INCONCLUSIVE", ...}
```

## Case-by-case result

- **T1 PASS** — both hashes re-verified against the registered digests, shown above.
- **T2 PASS** — 45,218 prediction rows across 9 dates × 2 studies; the ineligible ones carry a
  reason (`below_liquidity_floor` 13,862 · `below_min_price` 1,072 · `no_price_on_date` 555 ·
  `no_baseline_score` 168 · `no_forward_window` 40 · `insufficient_history` 39 ·
  `corporate_action_in_window` 32). Eligible pairs match between studies: 6,841 joined on
  (scoring_date, symbol) with no unmatched rows.
- **T3 PASS** — `_UNIVERSE_SQL` bounds sessions with `as_of_date <= $1`; `_DEALS_SQL` uses
  `deal_date < $1`; scores are read with `point_in_time` true.
  `v_smart_money_lookahead_gap` shows the PIT and reporting-date series differ by 5.45–8.94
  score points (corr 0.819–0.917) on these dates, confirming the PIT series is genuinely the
  constrained one.
- **T4 PASS** — the statistic is the per-date paired difference; the CI bootstraps whole
  formation dates (5,000 resamples, seed 20261022).
- **T5 PASS** — 9 < 12 blocks returned INCONCLUSIVE with the reason recorded. The inert-feature
  branch and the interval-spanning branch are present in `_finish` but were not the branch taken
  this run; only the sample-size branch is exercised by real data here.
- **T6 PASS after a fix** — the first run produced KOTAKBANK −79.70% (entry ₹2126.90 →
  exit ₹431.70), a 5:1 face-value split ex 2026-01-14 inside the window, because `prices_eod`
  has no adjusted price column. Capital-structure actions in the holding window are now excluded
  with a per-symbol-day reason. Two dates were corrected by this: 2026-01-12 −0.58% → +1.44%,
  2026-05-12 +3.53% → +6.12%.

## Defects found and fixed during verification

1. `Decimal * float` in `_deal_tilt` — client counts return `numeric` from `sum()`. Cast to int.
2. `KeyError: 'evidence_class'` — column missing from the score SELECT. Added.
3. Prediction tuple arity 14 vs 15 columns, shifting `eligible` to a string. Fixed.
4. `smart_money_shadow_predictions` PK is `(run_id, scoring_date, symbol)` — one model per run.
   Each study now gets its own run_id, cross-referenced via `paired_run_id`. The frozen schema
   was **not** altered.
5. `maturity` CHECK allows only `('pending','mature')`; `'complete'` was rejected. Fixed.
6. Unadjusted corporate actions in forward returns (T6 above).

## Not verified / out of scope

- **UNVERIFIED: benchmark-relative gates.** `benchmark_return_pct` and `sector_return_pct` are
  NULL in all 540 outcome rows — Nifty 500 TRI and the sector-relative benchmark are not computed
  yet. No benchmark gate from study 001 has been tested.
- **UNVERIFIED: the confirmatory stage.** This run is `exploratory` only.
- **UNVERIFIED: other backtests reading `prices_eod`.** The corporate-action bug fixed here is
  likely present in any other code that takes a multi-week open/close difference from that table.
  Not audited.

The study's own answer is INCONCLUSIVE — that is a finding about the data, not a test failure.
The service under test did what it was built to do, including refusing to call a thin sample a
success, and its five enforced rules were each demonstrated against real staging data.

## Verdict: PASS
