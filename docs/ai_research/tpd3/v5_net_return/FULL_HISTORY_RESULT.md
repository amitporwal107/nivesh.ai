# v5 net-return model — FULL-HISTORY WALK-FORWARD (511 sessions)
Run 2026-09-18 against PREREGISTRATION.md (committed dbc66fa8, before any training). Criteria unchanged.

## Why this rerun exists
The first walk-forward used 63 sessions. The owner pointed out that NIDP holds years of bhavcopy, which was
correct and which I had missed: I built the panel from nidp.stock_features_daily (starts 2025-05-26) and,
when checking price depth, queried only source='NSE_BHAVCOPY' (starts 2025-01-01). A second source,
NSE_SEC_BHAVDATA, covers 2024-05-31..2024-12-31 with full OHLC and 88% delivery. The two join seamlessly
(RELIANCE 2024-12-31 close 1215.45 -> 2025-01-01 open 1214.85).

Panel rebuilt from raw prices: 767,241 stock-days, 511 sessions, 2024-08-28..2026-09-17, liquid names only
(20-session median turnover >= Rs 1 cr). Walk-forward: 6-month minimum training, monthly refit, 20 test months.

## Result — FAIL on the pre-registered primary
    test sessions       402        (minimum 60) OK
    mean net per trade  -0.1944%
    95% CI              [-0.4203, +0.0315]
    all eligible        -0.4072%   -> edge +0.2128 pp
    sessions positive   44.5%
    +5% hit rate        24.73% vs universe 8.27%  (3.0x concentration)
    2025: 226 sessions, -0.1139%   2026: 176 sessions, -0.2979%

    VERDICT: FAIL — mean net is not positive; the 95% interval includes zero.

The 8x larger sample HALVED the loss (-0.373% on 63 sessions -> -0.194% on 402) and the interval now almost
excludes zero. It is still a fail, and the direction of the point estimate is still negative.

## What the larger sample newly reveals
1. THE EDGE vs the eligible universe IS statistically significant: +0.2128 pp per session, t = 2.31,
   95% CI [+0.032, +0.394], beating the market on 51.7% of sessions. On 63 sessions this was +0.061pp and
   indistinguishable from noise. Selection skill is real; it is just smaller than the cost of trading.

2. IT IS MOSTLY LEVERAGE, NOT SKILL. Regressing selection return on market return:
       selection = 1.480 x market + 0.4084
   The picks carry beta 1.48. In the best market quartile they beat the market by +0.84pp (t = 4.28); in the
   worst quartile they LOSE by -0.15pp. That asymmetry is what high beta does, not what skill does.
   A beta-matched benchmark (market x 1.48) would have returned -0.6028%; the model returned -0.1944%,
   leaving alpha +0.4084% per session (t = 4.58). So some genuine alpha survives the beta adjustment — but
   the model still loses money in absolute terms, because 1.48x a negative intraday drift is a large hole to
   climb out of.

3. THE INTRADAY DRIFT IS STRUCTURAL, NOT A ONE-QUARTER ARTEFACT. Across 26 months the overnight gap is
   POSITIVE in 25 and the intraday move NEGATIVE in 21. This was the single biggest doubt about the earlier
   finding (one rising quarter); it is now settled across two years and both directions.

4. THE MODEL'S WORST DECILE MOVES MOST. Decile 0 has a 12.44% +5% hit rate vs 10.94% for decile 9 and 8.27%
   for the universe. The model has learned that the biggest movers are the biggest losers after costs —
   which is the correct lesson for a net-return target, and the exact opposite of what a mover-model learns.

## Deviations from pre-registration (documented, not discretionary)
- r250 (1-year return) dropped: needs 250 bars, null in the first training window (history starts 2024-08-28).
- deliv20 dropped from the primary run: coverage is 100% in 2024, ~0% from Mar-2025 to Apr-2026, 100% again
  from Jun-2026. Training across that discontinuity would teach the model the data regime, not the market.

## Conclusion
v5 is NOT promoted. The engine is unchanged. But the conclusion is now materially better evidenced and more
precise than the 63-session version:
  - selection skill EXISTS and is statistically significant (+0.21pp/session, t = 2.31)
  - most of it is beta 1.48, not stock-picking
  - a real alpha of +0.41%/session survives the beta adjustment (t = 4.58)
  - none of it overcomes a -0.24% average intraday drift plus 0.25% costs at daily frequency
The binding constraint remains the holding period and the cost, not the model.
