# Functionality Verification Report — Recover beta_asymmetry.py into the repo

Date: 2026-09-30 · Branch: `feat/baselines-beta-asymmetry` · Base: `origin/dev` @ 73472552

## Why

`research/charting/baselines/beta_asymmetry.py` existed **only on the study box** and was absent
from `dev` — the exact position `evaluate.py` was in before it disappeared entirely and had to be
rebuilt from its call sites (#192). This recovers it before the same thing happens twice.

Audit after this lands: all seven modules in `baselines/` are on `dev`. Nothing else is box-only.

## What the module does

Fits beta twice — once on up-market days, once on down-market days — because one regression cannot
separate a stock that captures upside and shrugs off drawdowns from one that does the reverse.
Both score ~1.05 on a single regression.

## Tests added

The module's own comment cites `test_a_window_across_the_sealed_gap_is_unavailable` by name. That
test had been lost with the rest, so it is reinstated, along with nine others:

| test | pins |
|---|---|
| `conventional_beta_cannot_separate_two_opposite_stocks_but_the_split_can` | the claim the feature exists for — if this fails, the feature is unnecessary |
| `the_window_never_includes_the_signal_bar` | point-in-time: a 50x spike ON the signal bar must not move the estimate |
| `a_window_across_the_sealed_gap_is_unavailable` | the 2022-12-30 → 2024-08-01 index jump |
| `a_clean_window_applied_across_the_gap_is_also_refused` | the subtler case: 60 clean pre-gap rows applied 19 months later |
| `an_ordinary_holiday_gap_is_still_allowed` | the staleness guard must not reject everything |
| `a_leg_with_too_few_observations_gives_none_not_a_two_point_line` | MIN_LEG_OBS; pooled beta still estimable |
| `a_date_the_stock_did_not_trade_is_dropped_not_zero_filled` | no fabricated zeros |
| `rows_before_the_first_full_window_are_unavailable` | — |
| `feature_names_cover_every_window_and_measure` | 10 features |
| `every_record_carries_every_key_even_when_unavailable` | a missing key and a None read differently downstream |

## Real output

```
$ PYTHONPATH=. pytest research/charting/tests/test_beta_asymmetry.py -q
  10 passed in 0.09s

$ PYTHONPATH=. pytest research/charting/tests/ -q
  1498 passed, 2 warnings in 338.24s (0:05:38)
```

One fixture defect found and fixed while writing these: a constant ±1% index move leaves every x
inside a leg identical, so the regression has no variance and the slope is legitimately undefined.
That reads as a module bug and is really a degenerate fixture — the helpers now vary magnitude
within each leg.

## Verdict: PASS
