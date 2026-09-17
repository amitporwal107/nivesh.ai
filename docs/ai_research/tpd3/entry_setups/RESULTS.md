# Entry setups A–D — results against the pre-registered rule (2026-09-17)

Rules: PREREGISTRATION.md (written before any code ran) + its addendum. Code: backend/nidp/services/tpd_model/entry_setups.py
(10 tests) and backtest_entry_setups.py. Outputs: entry_setups_result.json, trades.csv.gz (sha256 in result_hashes.txt).
Exploratory checks run after the verdicts: exploratory_sensitivity.py / .json (not decisive).

## Verdict: no setup is a validated entry signal (0 of 8)

Signal days 2024-10-24 → 2026-09-08, point-in-time top-1,000, 0.25% round-trip cost, bracket exits within 5 sessions.

| Setup · trade | Trades | Mean net | 95% CI | Baseline mean | Half 1 | Half 2 | Verdict |
|---|---:|---:|---|---:|---:|---:|---|
| A Breakout · 5% | 190 | −0.65% | −0.97 … −0.32 | −0.54% | −0.94% | −0.50% | not validated |
| A Breakout · 10% | 1,601 | −0.74% | −0.99 … −0.48 | −0.61% | −0.62% | −0.81% | not validated |
| B Pullback · 5% | 1,636 | −0.56% | −0.74 … −0.37 | −0.54% | −0.65% | −0.51% | not validated |
| B Pullback · 10% | 6,862 | −0.61% | −0.79 … −0.44 | −0.61% | −0.74% | −0.53% | not validated |
| C Results momentum · 5% | 3 | −0.73% | — | −0.54% | | | not validated (n) |
| C Results momentum · 10% | 61 | −1.20% | −2.15 … −0.25 | −0.61% | −1.92% | −0.77% | not validated |
| D Volatility expansion · 5% | 9 | −2.21% | — | −0.54% | | | not validated (n) |
| D Volatility expansion · 10% | 85 | −1.43% | −2.21 … −0.59 | −0.61% | −2.24% | −1.06% | not validated |

Every setup fails "mean > 0", "CI lower > 0", "beats baseline" and both halves; C and D also fail n ≥ 200.

## Where the edge goes missing (exploratory, after the verdicts)

- Not the intraday ordering: assuming the target is hit before the stop whenever both are inside one bar, every setup is still negative.
- Not the costs: gross of costs every setup is still negative (A −0.40/−0.49%, B −0.31/−0.36%, C −0.48/−0.95%, D −1.96/−1.18%).
- Not the stops: holding every filled setup to the T+5 close with no stop or target, the 5-session return net of cost is
  A −0.67%, B −0.52%, C −0.75%, D −1.03%, against −0.34% for every eligible stock-day. The setups pick *worse* than average days.
- The odds of the move do not rise either (no R/R filter, within 5 sessions): P(+5%) A 28.2%, B 29.2%, C 29.0%, D 26.7% vs
  30.3% for all eligible stock-days; P(+10%) 7.8% / 8.9% / 9.7% / 8.2% vs 9.3%. One exception within 1 session: C (results
  momentum) reaches +5% the next day 12.5% of the time vs 5.8% (176 cases), but gives it back by T+5.
- The R/R ≥ 2 filter conflicts with the 5% target: a 5% target with R/R ≥ 2 needs a stop within 2.5%, which keeps only
  low-volatility stocks, and those rarely move 5% (baseline P(+5%, 5d) falls from 30.3% to 6.4% once the filter applies).

## Quality scores

- Entry Quality Score does not rank outcomes. 5% trades by EQS quintile (low → high): mean net −0.52, −0.55, −0.72, −0.47,
  −0.62%; P(+5%, 5d) falls from 20.4% to 10.3% as EQS rises (it rewards compression, liquidity and trend, which lower volatility).
- The v4 model probability ranks the odds of the move but not the profit. Setup trades Jan–Aug 2025 by model quintile:
  P(+5%, 5d) 6.6% → 31.1% (5% trades), yet mean net −0.93% → −0.46%, negative in every quintile. TOS behaves the same.
- Setup E (RS + accumulation) does not help: A 10% with E −0.73% vs without −0.74%; B 5% −0.73% vs −0.49%.
- By market cap (current bucket) and sector: no bucket with ≥ 100 trades is positive.

## Data notes

- First signal day is 2024-10-24, not the registered 2024-09-02: the point-in-time universe needs 100 bars and the panel starts
  2024-05-31. Yahoo has no Nifty bar for the 2026-02-01 Budget session (996 universe rows excluded).
- 1,018 stock-days dropped for corporate-action windows; 8,881 in-scope rows have an action older than T-1 inside the look-back
  (unadjusted history, as registered).
- Four sampled trades (SAILIFE A, ASIANPAINT B, BEL C, BHARATFORG D) were re-derived by hand from the raw bhavcopy rows: highs,
  RVOL, CLV, fills, stops and exits all match. The vectorised simulation matches the tested scalar functions on 6,000 trades.

## Owner decision (2026-09-17 ~12:10 IST, decisions-log.md)

All four setups are REJECTED as entry signals; no parameter tweaking to rescue them. Page: A and B "Setup detected — not
validated", C and D "Research only; insufficient sample", shown only in a Diagnostics section (no per-stock tags, no buy
signals, entry prices, trade cards, conviction badges, targets/stops, or ranking of one failed setup over another). The Entry
Quality Score is retired. The code stays as negative evidence (backend/nidp/services/tpd_model/entry_setups.py, research only).

## Reproducing
`cd backend && PYTHONPATH=. <research venv python> docs/ai_research/tpd3/entry_setups/backtest_entry_setups.py` with the
forward home at /app/research/tpd3_forward (panel, sectors, ETFs, financials, corporate actions) and the v4 walk-forward
predictions at .claude/workspace/ten-percent-days-3/evidence/early_window/v4/. trades.csv.gz holds every simulated trade.
