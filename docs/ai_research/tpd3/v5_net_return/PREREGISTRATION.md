# v5 "net return" model — PRE-REGISTRATION
Written 2026-09-18, BEFORE any model was trained or any result seen. Owner decisions the same day:
target = net return after costs; fundamentals backfilled from Yahoo; pre-registered walk-forward validation.

## Why a new target
v4 predicts P(session high >= +5% above prev close). It succeeds at that and still loses money:
2025 replay, 165 sessions, 825 selections — picks touch +5% 3.7x more often than average, net -0.43%/trade,
edge vs every eligible stock -0.03% [-0.40, +0.33]. Movement != profit.

Feature study on 177,534 stock-days (2026-06-01..09-16, evidence/net_return_study/FINDINGS.md) found the same
wall in the data itself: EVERY quintile of EVERY feature has a negative open-to-close net return. Cause is
structural — over the period the average overnight gap was +0.307% while the average intraday move was
-0.239%, and only 40.5% of stock-days closed above their open. The strongest movement predictor found
(locked near an upper circuit band yesterday: 20.93% hit rate, 6.86x lift) gaps +3.64% overnight and returns
-0.89% net.

## What v5 predicts
TARGET: y = (exit_price / entry_price) - 1 - cost, where
  entry_price = official NSE open of session T+1 (the paper engine's rule, a price actually obtainable)
  exit_price  = official NSE close of session T+1  (headline horizon; EOD-3/EOD-5 fitted as separate heads)
  cost        = 0.25% round trip (sensitivities at 0.50% and 1.00% reported, never used for fitting)
Regression on net return, NOT classification of a move. Model output is an expected net return per stock-day.

## Features
v4's 84 inputs (MODEL_COLUMNS_V4) plus, where point-in-time-safe:
  return_60d_pct, return_252d_pct, dist_200dma_pct, sma20/50/200 relations, volatility_1y_pct, beta_1y.
Yahoo fundamentals (nidp.yahoo_fundamentals) are fetched AS OF 2026-09-18 and are NOT point-in-time. They may
be used ONLY for present-day scoring, never to label or train on past sessions. Training fundamentals stay
NIDP's point-in-time ones. This is a hard rule: violating it leaks the future into the past.

## Success criteria — fixed now, not after
PRIMARY: mean net return per selected trade over the held-out walk-forward, top-5 selection per session.
  PASS   : mean net > 0 AND the 95% Newey-West interval (lag = horizon-1) excludes 0 AND >= 60 counted sessions
  FAIL   : otherwise. A negative or zero-straddling interval is a FAIL and will be reported as such.
SECONDARY (all reported whatever the primary says):
  - net return vs the same-session average of every eligible stock (the A_ALL benchmark)
  - net at 0.50% and 1.00% costs
  - hit rate of the +5% move (to compare against v4 directly)
  - decile calibration of predicted vs realised net return
ABANDON RULE: if the primary fails AND the top decile of predicted net return does not beat the bottom decile
by more than costs, v5 is recorded as "no edge found" and NOT promoted. No retuning to rescue it, no changing
the target after seeing results. A documented negative result is the deliverable in that case.

## Validation
Walk-forward on 2025 (Jan-Aug), monthly refit, identical folds to v4's early window so the two are comparable.
2026 data is NOT touched until the 2025 result is written down. No feature selection or hyperparameter choice
may use the held-out period.

## Honest prior
On the evidence above, the most likely outcome is FAIL: the intraday drift is negative, costs are 0.25%, and
no feature tested showed a quintile spread larger than 0.28pp. v5 exists to test that properly, not to
manufacture a positive.
