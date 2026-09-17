# Short-term mean reversion E1–E5 — development results (2026-09-17)

Rules: PREREGISTRATION.md (sha256 5673ba1d…, committed with the code in f1523a0e before any run). Script:
backtest_mean_reversion.py --segment development. Outputs: mr_development_result.json, mr_development_trades.csv.gz.

## Verdict: no variant passed development (0 of 5), so the 2026 holdout was NOT run and stays unused

Development segment: signal days 2024-10-24 → 2025-12-23 (T+5 ≤ 2025-12-31), point-in-time top-1,000, ADV20 ≥ Rs 5 crore,
entry at the T+1 open, exit at the T+5 close, 0.25% round-trip cost. 248,388 eligible stock-days; 3,495 removed for a
material negative results print in T-4..T; 244,893 remain. `--segment holdout` was then invoked once to confirm the guard:
it refused ("no variant passed development") and wrote no lock file.

| Variant | Trades | Mean net (5 sessions) | 95% CI | vs any stock-day (−0.43%) | Same-stock edge | Matched edge (95% CI) | Failed criteria |
|---|---:|---:|---|---:|---:|---|---|
| E1 3-day dip + stabilisation | 1,546 | −0.32% | −1.28 … +0.77 | +0.12 pt | +0.06 pt | +0.24 pt (−0.06 … +0.57) | 2, 3, 5, 6, 7, 8 |
| E2 5-day dip + stabilisation | 995 | +0.01% | −0.87 … +0.95 | +0.45 pt | +0.39 pt | **+0.40 pt (+0.01 … +0.78)** | 3, 7, 8 |
| E3 dip + RSI2 turn-up | 203 | +0.20% | −1.87 … +2.14 | +0.63 pt | +0.59 pt | −0.59 pt (−1.20 … +0.27) | 3, 5, 6, 7 |
| E4 dip + strength vs sector | 1,859 | +0.09% | −0.66 … +0.89 | +0.52 pt | +0.31 pt | +0.29 pt (−0.01 … +0.61) | 3, 5, 6, 7, 8 |
| E5 dip + reversal candle | 271 | −1.48% | −2.51 … −0.07 | −1.04 pt | −1.13 pt | −0.14 pt (−0.95 … +0.61) | 2, 3, 4, 5, 6, 7, 8 |

Criteria: 1 ≥ 200 trades · 2 mean > 0 · 3 CI lower > 0 · 4 beats any-stock-day and same-stock · 5 positive in both halves
(split 2025-05-31) · 6 matched edge with CI lower > 0 · 7 no dependence (≤ 10% of trades in one symbol; still positive without
the top sector and without the top 5 dates) · 8 still positive after an extra 0.20% slippage.

## What the numbers say

- Nothing here is an entry signal. Every variant's own 95% interval spans zero or sits below it; none survives removing its
  five best dates (E1 −0.99%, E2 −0.54%, E3 −1.55%, E4 −0.52%, E5 −2.19%), so the small positive means rest on a few days.
- The development period was a falling tape for this universe: any eligible stock-day lost −0.43% over 5 sessions after cost
  (95% CI −0.78 … −0.10). Dips E1–E4 lost less than that or broke even — a relative effect, not an absolute one.
- E2 (five-day dip, still above SMA20, close off the low, quiet volume) is the only variant whose matched edge clears zero:
  +0.40 points per trade against same-day stocks of the same sector, turnover band and volatility (CI +0.01 … +0.78), and it
  was positive in both halves (+0.02%, +0.01%). It still fails on its absolute CI, the top-5-dates check and slippage. Under
  the registered rule it is "not validated", and this result must not be used to tune a variant on the same data.
- Adding a reversal candle (E5) made results clearly worse (−1.48%, win rate 37%). RSI2 turn-up (E3) is too rare (203) and
  its matched edge is negative.
- For E1–E4 the shorter holds are worse than 5 sessions (e.g. E2: −0.24% at 1 session, −0.15% at 3, +0.01% at 5); E5 gets worse
  the longer it is held (−0.97%, −1.01%, −1.48%).
- Negative-catalyst dips were rare in the tradable set (E1 16, E2 19, E3 1, E4 19, E5 5 trades) — too few to read.

Other reported statistics (per variant, in mr_development_result.json): median, win rate, profit factor (E1 0.88, E2 1.01,
E3 1.08, E4 1.04, E5 0.55), return volatility (~6.5–7.0% per trade), mean MFE5 (+4.7 … +5.6%) and MAE5 (−4.8 … −5.8%), by
market-cap bucket (current), sector and turnover band. "Maximum drawdown" is the registered definition — the cumulative sum of
per-date mean 5-session returns — which adds overlapping holding periods, so it is not a portfolio equity curve.

## Data checks

- Two sampled trades (PARAGMILK E1 2024-11-14, SHRIRAMPPS E2 2025-06-03) re-derived from raw bhavcopy rows: SMA20, r3, r5, CLV,
  RVOL, T+1 open, T+5 close and net all match the output file.
- The module's 13 tests cover every variant on synthetic shapes, the cooldown, statistics, bootstrap, matched fallback,
  dependence, the verdict and the one-time holdout lock.

## Status for the owner

The 2026 holdout (2026-01-01 → 2026-09) remains unused by this experiment. Any follow-up — for example a relative-return
(matched) hypothesis suggested by E2 — is a new hypothesis formed on development data: it would need its own pre-registration
before touching the holdout, and the caveat that the dip idea itself came from 2024–26 exploratory analysis still applies.
