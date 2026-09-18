# Success criteria for NIDP trading-pattern models

**Owner specification, 2026-09-19.** Standing policy for every pattern and model in the Pattern Discovery Engine.
A model is **not** successful because it predicts movement accurately. The criterion is a **repeatable,
risk-adjusted edge after transaction costs, with realistic execution.**

## The five production gates (owner's priority)
1. **No look-ahead bias and correct trade simulation.**
2. **Positive out-of-sample net expectancy after costs.**
3. **Reliable probability calibration.**
4. **Stability across time and market regimes.**
5. **Transparent risk, liquidity and sample-size reporting.**

**Failing gate 1 or 2 means the model must not be presented as a validated trading-opportunity model**, however good
its movement metrics look. Gates are not a score: no metric compensates for a critical failure (a high Sharpe does not
excuse look-ahead).

## Lifecycle — three stages, each a gate
| Stage | Requirements |
|---|---|
| **1. Research candidate** | Statistically testable definition · no look-ahead · sufficient sample · positive or promising evidence against a baseline |
| **2. Validation candidate** | Walk-forward out-of-sample testing · positive net expectancy after costs · calibrated probabilities · performance documented across regimes · no collapse under reasonable parameter changes |
| **3. Production candidate** | Untouched final test period · realistic execution · risk and liquidity filters · monitoring and drift detection · paper trading or limited deployment before wider use |

## The six dimensions
**1. Predictive performance** — always against a simple baseline. ROC-AUC (ranking; better than baseline and stable
out of sample), PR-AUC (compare with the positive-class rate), precision (must meet the minimum trade-quality bar),
recall (with precision), Brier score, **calibration** (required before any probability is shown to users: a 60%
target-before-stop prediction should succeed ~60% of the time across large groups). No universal pass mark such as
"80% accuracy" — thresholds depend on event frequency, costs and strategy economics.

**2. Trading performance (most important).**
`EV = (P_win × AvgWin) − (P_loss × AvgLoss) − Costs` (costs = brokerage, taxes, slippage). Must be positive **out of
sample**. Report net return, profit factor, maximum drawdown, Sharpe, Sortino, expectancy per trade, turnover,
capacity/liquidity. A high win rate can still lose money.

**3. Statistical validity.** Untouched out-of-sample period · walk-forward · confidence intervals on win rate,
expectancy and returns · bootstrap or permutation tests · multiple-testing control across all patterns, features,
thresholds and parameter combinations. A pattern that works in one short period is **unconfirmed**.

**4. Stability.** Split by regime (bull/bear/sideways/high-vol), year and rolling window, sector, liquidity, market
cap, pattern intensity (e.g. gap −3/−5/−8%) and holding period (1/3/5/10 days). Not every regime must be profitable:
identify where it works, where it fails, and when to disable it.

**5. Execution realism.** Slippage, brokerage and statutory charges, bid-ask spread, liquidity and impact, partial
fills, gap-through-stop, intraday high/low ordering, halts and missing prices, entry timing and next-bar execution.
A candle touching both target and stop must never be resolved in the favourable direction — use intraday data or a
conservative rule.

**6. Business and operational.** Explainability (main factors shown), data-quality detection, reproducibility (model
and feature versions stored), monitoring (probability drift vs realised outcomes), latency, safety controls (liquidity
and risk exclusions), user transparency (uncertainty and historical sample size shown).

## Required report for a pattern (gap-down recovery example)
Number of events · target hit rate · stop hit rate · target-before-stop from correct intraday ordering · average and
**median** net return after costs and slippage · maximum drawdown · confidence intervals · regime performance ·
out-of-sample results. A positive average intraday return alone is not success: the execution strategy and the
target/stop outcomes must be defined and measured.

## Storage
`pattern_validation_results`: pattern_id, pattern_version, data_snapshot_id, train_period, validation_period,
test_period, sample_count, positive_rate, precision, brier_score, calibration_error, avg_net_return, median_net_return,
profit_factor, max_drawdown, sharpe_ratio, target_before_stop_rate, confidence_interval, transaction_cost_assumption,
slippage_assumption, market_regime, validation_status — **plus complete trade-level results** (aggregates alone cannot
be audited).

---

## Implementation notes (Claude, from this week's evidence)
- **Compute Sharpe, drawdown and profit factor on per-session portfolio returns, not per-trade.** Gap-down events
  cluster: five market-wide days hold 36% of rows, so trade-level statistics overstate independence.
- **Every extra split, intensity level or holding period is another test** — each is logged in the registry's
  multiple-testing count (`REGISTRY_SEED.md`).
- **Gate 1 includes the data pipeline, not just the model.** Tonight's three errors (wrong-session backfill, phantom
  gaps, adjustment mismatch) were all look-ahead-grade failures that no model metric would have revealed; the join
  checks in `gapdown/INTRADAY_SOURCE_EVALUATION.md` (Addenda 5–6) are part of gate 1.
- **Capacity:** the paper engine already flags a position larger than 1% of first-session turnover
  (`CAPACITY_FRAC = 0.01`); reuse it.
- **Existing trade-level files** satisfy the "retain trade-level results" rule for the gap-down work:
  `/app/research/tpd3_panel/g1_sleeve_kite_gaps.pkl`, and the grid/timing outputs under
  `/app/research/kite_history/gapdown_minute_v2/`.

## Where current candidates stand (2026-09-19 04:15 IST)
| Pattern | Stage reached | Gate status |
|---|---|---|
| G1 gap-down close-only (Kite real gaps) | **Stage 1 — research candidate** | Gate 1 ✅ (entry at the open, exit at the close, gap known at 09:15; data joins validated). Gate 2 ⏳ — positive only on the explored 2024–26 data (+0.8909%/session, t 5.80); the untouched 2021..2024-07 period is not yet tested. Gate 3 n/a (rule, no probabilities). Gate 4 partial (positive 2024/25/26; market-day concentration unresolved). Gate 5 partial (costs flat 0.25%; no slippage or impact model; survivorship from Kite's current-names list). |
| G1 pre-registered target/stop grid | Not yet evaluable | Both earlier runs retracted; correct run pending on validated minute bars. |
| v4 movement model, v5 net-return model, owner setups A–D, hourly signal, single-feature lifts | **Failed Stage 1 or 2** | Movement without positive net expectancy; must not be presented as trading-opportunity models. |
