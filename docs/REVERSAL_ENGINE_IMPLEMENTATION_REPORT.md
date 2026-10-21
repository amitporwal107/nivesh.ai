# Reversal engine — implementation report (2026-10-20, branch feat/reversal-engine, NOT merged, NOT deployed)

Status: IN PROGRESS. Built and tested locally; staging endpoint tests not run (see test_reports/OVERRIDE_reversal_engine.md).
Scope: research / paper trading only; no order execution anywhere.

## Built
- backend/services/positional_engine/reversal_rules.py (reversal-rules.v1): 252-session distance, 6 stabilization signals, gates, 6-part rule-based score (weights 20/25/15/20/10/10, untuned), unknowns left out and coverage reported, hypothetical levels.
- reversal_service.py + GET /api/positional/reversal-candidates (near_pct 5-25, default 15; view candidates|all).
- DaaS GET /v1/features/reversal-snapshot (adjusted bars, Nifty 500, sector rotation, fundamentals, announcements).
- UI: Scanner "Reversal candidates" → ReversalPanel (10/15/20 %, sector context, fundamentals, catalyst, invalidation, exclusions).
- reversal_backtest.py + scripts/run_reversal_backtest.py; results in docs/reversal_backtest/report_20261020.json.

## Measured backtest (adjusted run; 15 %; base costs 0.25 % + 0.10 % round trip once = 0.35 %; excess = net minus same-day universe mean gross)
| Variant | h5 | h10 | h20 |
|---|---|---|---|
| near low only | −0.36 [−0.54,−0.18] | −0.55 [−0.80,−0.29] | −0.96 [−1.35,−0.58] |
| technical reversal | −0.36 [−0.57,−0.16] | −0.64 [−0.95,−0.34] | −1.15 [−1.61,−0.70] |
| sector + technical | −0.28 [−0.52,0.01] | −0.56 [−0.91,−0.18] | −1.19 [−1.84,−0.59] |
| trigger/confirmed | −0.56 [−1.09,0.00] | −0.80 [−1.68,0.21] | −1.88 [−2.89,−0.80] |
| momentum (benchmark) | −0.45 [−0.62,−0.26] | −0.13 [−0.43,0.19] | −0.05 [−0.43,0.33] |
Out of sample 2026-07-14..2026-10-19, h10: technical reversal −1.33 [−1.92,−0.66] (n=252); sector+technical −0.90; momentum +0.40 [−0.32,1.11] (n=577).
Higher-cost case (0.60 %): technical reversal h10 net −0.44, excess −0.89. Thresholds 10 % and 20 % give the same sign.
Failed breakout: only 4 confirmed events in 16 months (2 of 4 failed within 5 sessions): too few to conclude anything.

CONCLUSION: no evidence the strategy beats the universe after costs; sector rotation and a stricter trigger did not help. Not profitable, not production-validated.

## Data limits and assumptions
- ~16 months of signals (first 2025-06-05, 340 sessions), not 5 years: warehouse prices start 2025-10-01; research-VM NSE files start 2024-05-31. One market cycle.
- No point-in-time Nifty 500/1000 membership: universe = point-in-time top 500 by 60-session traded value, 20-session floor 10 Cr. Nifty 1000 robustness test NOT run. Industry tags are today's (not PIT); only 763 of 2,315 symbols have one.
- Adjusted for splits/bonuses from the NSE corporate-action file (264 actions, 240 applied, 16 inconsistent with price); dividends and rights NOT adjusted; 260 unexplained one-session breaks >25 % cut series into segments (228 follow a data gap).
- No point-in-time fundamentals or catalysts: the full 6-part score and fundamental-quality groups were NOT backtested (technical + sector only).
- Hit rates use intraday highs (optimistic); universe baseline hit rates not computed; entry at next open without gap/circuit modelling; many variants/thresholds tried (multiple comparisons).
- Staging fundamentals sparse (cash flow table empty, growth often missing) so the live fundamental part is often Unknown.

## Failures found and fixed
- First run used exchange prev_close to detect splits: invalid (ADANIPOWER etc. unadjusted); replaced by the action file.
- Catalyst read impact_score as a number; real values are low/medium/high.
- Failed-breakout metric counted trigger-ready stocks (93 %): restricted to confirmed.
- Malformed snapshot rows raised IndexError (500); now 502.
