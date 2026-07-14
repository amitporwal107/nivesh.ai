# Pillar 2 — Technical Analysis & Quant/Stat Models

**Grounding first:** the repo already implements returns, risk, indicators, and backtests.
Read the implementation before quoting a formula or a number:
`backend/services/copilot_tools/backtest.py` (CAGR/XIRR), `goal_engine.py` (FV, SIP, Monte-Carlo),
`backend/nidp/services/technical_indicator_engine/calculator.py`,
`backend/services/copilot_tools/technical.py`, `backend/services/positional_engine/`,
`backend/services/v3_scoring.py`. Annualization conventions (252 vs 365, simple vs log
returns, TR vs price) are decisions the code makes — **use the code's convention and state it**,
don't assume. Pull the price/NAV series via DaaS; check it's corporate-action-adjusted
(`price_adjuster/`, migration `026_nidp_price_adjustments.sql`).

## Returns & the statistics of performance

- **Simple return** rₜ = Pₜ/Pₜ₋₁ − 1; **log return** = ln(Pₜ/Pₜ₋₁) (additive across time).
  **Total return** includes dividends/reinvestment — backtests here use a **total-return
  series** (see `backtest.py`); price-only understates equity/MF performance.
- **CAGR** = (End/Begin)^(1/years) − 1 — only valid for a single lump flow over the window.
- **XIRR** — the money-weighted IRR for irregular cash flows (SIPs, top-ups, redemptions);
  solves Σ CFᵢ/(1+r)^(dᵢ/365) = 0. `backtest.py` uses **XIRR for SIP** and **CAGR for lump
  sum** — quoting CAGR on a SIP is a classic error; don't.
- **Rolling returns** — distribution of returns over every window of length N (e.g. 3y rolling),
  far more honest than point-to-point; MF rolling returns: `095_mf_rolling_returns.sql`.
- **Time- vs money-weighted** — TWRR judges the manager, XIRR judges the investor's actual
  outcome. Say which the question wants.

## Risk & risk-adjusted metrics (formula ↔ use)

- **Volatility** σ = stdev of periodic returns, annualized (×√252 daily / ×√12 monthly — check
  the code's basis). **Downside deviation** = σ of only sub-target returns.
- **Sharpe** = (Rp − Rf)/σp. **Sortino** = (Rp − Rf)/downside deviation (penalises only bad vol).
- **Beta** = Cov(Rp,Rm)/Var(Rm) (regression slope vs benchmark). **Alpha** = Rp − [Rf + β(Rm−Rf)]
  (CAPM/Jensen). **R²** = fit quality of that regression (how benchmark-explained the fund is).
- **Treynor** = (Rp − Rf)/β. **Tracking error** = σ of (Rp − Rm). **Information ratio** =
  (Rp − Rm)/tracking error. MF wiring: `094_mf_analytics_gaps_r2_te_ir.sql`, `096_mf_active_share.sql`.
- **Max drawdown** = max peak-to-trough decline; **Calmar** = CAGR/|MDD|. **VaR/CVaR** — see
  `copilot_tools/risk.py` / `nodes/risk.py`. Always pick **Rf** and the **benchmark** explicitly
  (`routes/benchmarks.py`), and state the window — these metrics are meaningless without them.

## Indicator families (definition + failure mode)

Read `technical_indicator_engine/calculator.py` for the repo's exact lookbacks/params.

- **Trend:** SMA/EMA and crossovers; **MACD** = EMA₁₂ − EMA₂₆, signal EMA₉; **ADX** (trend
  *strength*, not direction). Failure: whipsaws in range-bound markets.
- **Momentum:** **RSI** = 100 − 100/(1+RS), RS = avg gain/avg loss over N (default 14);
  Stochastic; ROC. Failure: stays "overbought" in strong trends — overbought ≠ sell.
- **Volatility:** **Bollinger Bands** = SMA ± k·σ; **ATR** (range-based vol, good for stops).
- **Volume/participation:** OBV, and **delivery %** (India-specific, feed `delivery/`) —
  price move on high delivery is higher-conviction than on intraday churn.
- **Accumulation/positional:** `technical_indicator_engine/accumulation.py`,
  `positional_engine/accumulation_detector.py`, `conviction.py`, `sector_strength.py`.

Rules of the craft: indicators **confirm**, they don't predict; combine one from each family
(trend + momentum + volume) rather than stacking three momentum oscillators; timeframe must
match the horizon; a signal is a probability, not a promise.

## Backtesting without fooling yourself

The engines: `copilot_tools/backtest.py` (copilot), `strategy_engine/backtest.py` +
`backtest_sql.py` (strategy lab), `positional_engine/backtest.py`. When you design or read a
backtest, check for the classic biases:
- **Look-ahead bias** — using data not yet known at the decision point (restated fundamentals,
  same-day close). **Survivorship bias** — universe must include delisted/merged names.
- **Corporate-action adjustment** — splits/bonus/dividends (`price_adjuster/`). Unadjusted
  series fabricate crashes/gaps.
- **Costs** — brokerage, STT, slippage, MF expense ratio & exit load; gross backtests overstate.
- **Overfitting** — too many tuned params on one window. Prefer out-of-sample / walk-forward and
  **rolling** rather than a single lucky path.
- **Regime** — a 3-year window that is all bull tells you little; state the regime and drawdowns,
  not just the CAGR. (Note the repo's stock history depth constraint on backtests.)

## Scoring & strategy stack (real anchors)
`v3_scoring.py` + `v3_weights.py` + `v3_explainer.py` (explainable composite),
`v3_scores_engine/service.py`, `nav_analytics_sweep.py` (`v3_scored_at`);
`strategy_engine/` DSL + `templates/*.json` (momentum, mean-reversion, accumulation);
`stock_scorer_nidp.py`, `sector_scoring/`, `bank_scoring/`. Read weights before explaining a score.

## Definition of Done for a technical/quant call
Formula shown and matched to the code (annualization/return-basis/benchmark/Rf/window all
stated); series pulled this turn, corporate-action-adjusted and TR where relevant; feed
freshness checked; risk reported alongside return (never a bare CAGR); backtest caveats
(look-ahead, survivorship, costs, regime, history depth) named; no fabricated series or number.
