# v5 net-return model — WALK-FORWARD RESULT: FAIL
Run 2026-09-18 against PREREGISTRATION.md (committed dbc66fa8 BEFORE any training). Criteria unchanged.

## Result
Walk-forward, monthly refit, 2025. 91,056 stock-days, 63 test sessions, 3 test months (Jun/Jul/Aug).

    sessions                 63            (pre-registration required >= 60) OK
    mean net per trade       -0.3728%
    95% CI                   [-0.7515, +0.0059]
    all eligible stocks      -0.4342%      -> edge +0.0614 pp
    sessions positive        39.7%
    net at 0.50% costs       -0.6228%
    net at 1.00% costs       -1.1228%
    correlation pred/actual  0.0586

    VERDICT: FAIL — mean net is not positive; 95% interval includes zero.

## What the model did achieve
Deciles of predicted net return are ordered and monotone at the extremes:
    decile 0 (worst): -0.672%   ... decile 9 (best): -0.330%
    top-minus-bottom spread: 0.341 pp — clears the 0.25pp cost bar, so the ABANDON RULE is NOT triggered.
It also concentrates movement sharply: selections touched +5% 14.92% of the time vs 6.05% for the universe
(2.5x), confirming again that these features predict movement well.

It ranks correctly along a ladder where every rung is below zero. Its best decile still loses 0.330%.
Edge vs the eligible universe is +0.061pp — real in sign, far too small to cover 0.25% costs.

## Deviations from pre-registration (both documented, neither discretionary)
1. TEST WINDOW: 63 sessions across Jun-Aug 2025, not the full Jan-Aug. nidp.prices_eod starts 2025-01-01 and
   the features need a 60-bar warm-up, so Jan/Feb are unusable and Mar had only 4,298 rows (too few to train).
   The 63 sessions still clear the pre-registered 60-session minimum.
2. FEATURES: deliv_pct and deliv20 dropped — delivery % is NULL in 0 of 61,712 training rows for 2025 (the
   known delivery-to-prices_eod gap). Every other pre-registered feature was used. This removes a feature that
   showed a 1.41x lift on the 2026 sample, so the 2025 test is mildly conservative.

## Consistency with the 2026 hold-out
The same model on 2026 data (31 sessions, Aug-Sep) gave mean net -0.376%, CI [-1.083, +0.330], edge +0.21pp,
decile spread 0.685pp. Two independent periods, same answer: correct ranking, negative level, no tradeable edge.

## Conclusion
v5 is NOT promoted. It is not wired into the paper engine and no rules were changed on the strength of it.
The abandon rule was not triggered (the decile spread clears costs), so the ranking itself is worth keeping as
a research signal — but it must not be presented as a strategy.

Across nine signals and two independent periods, every candidate predicted movement and none survived costs
when entered at the official open. The binding constraint is not model quality; it is that the move is priced
overnight, before the entry price exists.
