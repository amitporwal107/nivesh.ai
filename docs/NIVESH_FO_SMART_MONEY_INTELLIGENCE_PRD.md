# Nivesh F&O Smart Money Intelligence & Strategy Engine

## Product Requirements Document (PRD)

**Version:** 1.0\
**Status:** Product and research specification\
**Scope:** Indian equity derivatives, including stock futures/options,
NIFTY, and BANKNIFTY\
**Primary principle:** Signals and strategy recommendations must be
explainable, risk-aware, and validated out of sample before production
promotion.

------------------------------------------------------------------------

## 1. Executive Summary

Build a research-backed intelligence system that classifies futures
open-interest (OI) activity into four standard market regimes, ranks the
strongest opportunities, and evaluates suitable defined-risk strategies.
The system should analyze:

-   Individual F&O stocks, with up to five candidates in each buildup
    category.
-   NIFTY and BANKNIFTY as separate index-intelligence workspaces.
-   Cash-market price, volume, delivery data, technical structure,
    fundamentals, corporate events, and options-chain context.
-   The user's existing positions, so alerts can distinguish between a
    new opportunity and a risk-management action.

The product is an analytical decision-support system. It must not treat
OI alone as proof of direction, institutional activity, or a profitable
trade. Thresholds and scoring weights in this document are research
hypotheses until validated against point-in-time historical data.

## 2. Goals and Non-Goals

### Goals

1.  Detect and classify futures price/OI regimes reliably.
2.  Rank up to five eligible stock candidates per regime.
3.  Generate independent NIFTY and BANKNIFTY analysis and strategy
    candidates.
4.  Combine derivatives data with cash/delivery, technical, fundamental,
    and event context.
5.  Compare strategy structures on expected payoff, risk, liquidity,
    capital, Greeks, and modeled costs.
6.  Surface portfolio-aware actions: investigate, reduce, hedge, exit
    review, or consider a new trade.
7.  Provide reproducible threshold research, backtests, paper trading,
    and promotion gates.

### Non-goals

-   Automatic live order placement or broker execution.
-   Treating a signal as a guaranteed forecast.
-   Inferring institutional intent solely from bulk/block trades,
    delivery percentage, or OI.
-   Promoting a threshold or model solely because it performs well
    in-sample.

## 3. Users and Core Workflows

### Personas

-   Active F&O trader seeking structured, explainable opportunities.
-   Positional trader seeking multi-session setups.
-   Investor holding an underlying stock who needs derivatives-based
    risk alerts.
-   Research analyst validating thresholds and strategy performance.
-   Risk manager monitoring exposure, drawdown, concentration, and hedge
    effectiveness.

### Main workflow

1.  Ingest and validate market data.
2.  Classify each eligible contract's price/OI regime.
3.  Apply research-approved thresholds and eligibility filters.
4.  Rank candidates separately by signal strength, tradeability, and
    strategy quality.
5.  Enrich candidates with cash-market, technical, fundamental, event,
    and options context.
6.  Generate and compare strategy candidates.
7.  Check portfolio exposure and risk.
8.  Publish explainable alerts and track outcomes through paper trading.

## 4. Market Regime Classification

For a futures contract over a defined observation interval:

  -----------------------------------------------------------------------
  Price change      OI change         Classification    Typical
                                                        interpretation
  ----------------- ----------------- ----------------- -----------------
  Positive          Positive          Long Build-up     New positions are
                                                        being added as
                                                        price rises

  Negative          Positive          Short Build-up    New positions are
                                                        being added as
                                                        price falls

  Positive          Negative          Short Covering    Positions are
                                                        being reduced as
                                                        price rises

  Negative          Negative          Long Unwinding    Positions are
                                                        being reduced as
                                                        price falls
  -----------------------------------------------------------------------

These labels are descriptive, not certainty claims. Futures price and OI
must be evaluated with volume, basis, liquidity, contract expiry, and
broader market context.

### Core calculations

-   `price_change_pct = (current_price / reference_price - 1) * 100`
-   `oi_change_pct = (current_oi / reference_oi - 1) * 100`
-   `relative_volume = current_volume / comparable_average_volume`
-   `basis = futures_price - spot_price`
-   `basis_pct = basis / spot_price * 100`
-   `oi_percentile = percentile_rank(current_oi_or_oi_change, historical_reference_window)`

Reference intervals must be configurable and consistent. Intraday and
end-of-day signals must not be mixed without explicit labels.

## 5. Candidate Universe and Eligibility

### Stock universe

Include current and historically eligible NSE F&O stocks. The historical
universe must account for contract additions/removals, expiry changes,
lot-size changes, symbol changes, and delisted securities where
relevant.

### Index universe

Analyze NIFTY and BANKNIFTY independently. Do not combine their signals
or assume the same thresholds apply.

### Eligibility checks

-   Valid instrument/contract mapping and timestamp.
-   Sufficient liquidity and market depth.
-   Acceptable bid-ask spread and traded volume.
-   Valid price and OI observations with no unexplained gaps.
-   Exclude stale, malformed, or anomalous data.
-   Handle expiry day, rollovers, and near-expiry contracts explicitly.
-   Avoid candidates whose strategy legs cannot be filled realistically.
-   Keep an auditable reason for every excluded instrument.

## 6. Threshold Research Framework

No threshold is production-approved by default. Candidate thresholds
must be empirically evaluated.

### Initial research grid

  -----------------------------------------------------------------------
  Feature                             Candidate values
  ----------------------------------- -----------------------------------
  Absolute price change               0.10%, 0.20%, 0.30%, 0.50%, 0.75%,
                                      1.00%, 1.50%, 2.00%

  OI change                           1%, 2%, 3%, 5%, 8%, 10%, 15%, 20%

  Relative volume                     1.0, 1.2, 1.5, 2.0

  OI percentile                       50, 60, 70, 80, 90

  Outcome horizon                     1, 3, 5, 10, 20 sessions
  -----------------------------------------------------------------------

Treat stock, NIFTY, and BANKNIFTY thresholds as separate experiments
unless evidence supports pooling.

### Validation requirements

-   Point-in-time data only; no look-ahead or survivorship bias.
-   Use historical constituent and contract universes.
-   Split by time: training/research, validation, and untouched
    out-of-sample test.
-   Use walk-forward evaluation and record every tested configuration.
-   Include brokerage, exchange charges, taxes, spread, slippage,
    impact, and realistic fills.
-   Compare against relevant baselines, including buy-and-hold/benchmark
    and simple price-only rules.
-   Report results by regime, instrument, volatility environment, and
    horizon.
-   Measure stability across periods and sensitivity to threshold
    perturbations.
-   Do not promote a threshold without positive out-of-sample evidence
    and documented approval.

## 7. Ranking and Scoring

Keep three distinct scores:

1.  **Signal Strength:** evidence for the observed buildup regime.
2.  **Tradeability:** liquidity, spread, depth, and execution
    feasibility.
3.  **Strategy Quality:** risk-adjusted, cost-adjusted suitability of a
    specific strategy.

Do not collapse these into one opaque score.

### Illustrative starting weights --- research hypotheses only

#### Stock signal score

  Input                                Initial weight
  ---------------------------------- ----------------
  Futures OI signal                               30%
  Futures price behavior                          20%
  Volume / relative volume                        15%
  Options-chain confirmation                      15%
  Cash-market and delivery context                10%
  Technical structure                             10%

#### Index signal score

  Input                           Initial weight
  ----------------------------- ----------------
  Index futures OI                           25%
  Index price behavior                       15%
  Options OI structure                       20%
  Option premium / IV context                10%
  Market breadth                             15%
  Constituent contribution                   10%
  Technical structure                         5%

Weights are configurable, versioned, and not considered validated until
tested. Missing features must be handled explicitly; do not silently
redistribute weights in ways that change score meaning.

## 8. Cash-Market, Delivery, Technical, and Fundamental Context

### Cash and delivery

Capture:

-   Cash price change, traded quantity, and relative volume.
-   Delivery quantity and delivery percentage, where published.
-   Delivery metrics compared with their historical averages.
-   Bulk/block deal records with source, publication time, and caveats.
-   Cash/futures divergence and basis behavior.

Delivery statistics are generally published with a delay and must be
timestamped by availability. Delivery or bulk/block activity is not, by
itself, proof of institutional accumulation or distribution.

### Technical analysis

Provide, where data supports it:

-   EMA 20, 50, and 200; price relative to each.
-   RSI, MACD, ROC (including ROC5).
-   VWAP and anchored VWAP where applicable.
-   ATR and ATR percentage.
-   Relative strength versus NIFTY 500 and sector benchmark.
-   Support/resistance, prior day/week high-low, gaps, and volume
    profile.
-   Trend, breakout, pullback, and reversal context with confirmation
    status.

### Fundamental and event context

Include:

-   Valuation: P/E, P/B, EV/EBITDA where meaningful.
-   Quality: ROE, ROCE, margins, earnings growth, cash flow.
-   Balance sheet: debt, leverage, liquidity.
-   Ownership: promoter pledge and FII/DII trends, with source and as-of
    date.
-   Corporate events: results, announcements, actions, regulatory
    developments.

Fundamental quality is a separate lens from short-term direction. A weak
fundamental profile must not automatically negate a tactical signal, but
should affect suitability, risk, and explanation.

## 9. Options-Chain Intelligence

For stock options, NIFTY, and BANKNIFTY, capture:

-   Strike-wise call/put OI and change in OI.
-   Volume, bid/ask, last traded price, and premium change.
-   Implied volatility, IV change, and skew where available.
-   Greeks, with model and timestamp documented.
-   Put-call ratio with a clearly defined scope (volume or OI; strike
    range; expiry).
-   ATM straddle price and implied expected move.
-   Concentrated OI levels, often described as call/put walls.
-   Max pain, shown as a descriptive calculation---not a price forecast.

OI alone cannot establish whether a position is a fresh directional bet,
hedge, spread, or market-maker inventory. Interpret OI alongside premium
movement, IV, liquidity, expiry, and price action.

## 10. NIFTY and BANKNIFTY Intelligence

Each index gets a dedicated dashboard and independent signal/ranking
process.

### Required context

-   Index futures price, OI, OI change, volume, basis, and expiry.
-   Options-chain OI and OI change by strike.
-   ATM IV, IV term structure, skew, and ATM straddle-implied move.
-   PCR with precise definition.
-   Call/put concentration levels and max pain (descriptive only).
-   India VIX context where relevant.
-   Advance/decline breadth and sector participation.
-   Constituent contribution and concentration of index movement.
-   EMA, RSI, ATR, support/resistance, and prior-session levels.

### Index strategy candidates

Evaluate only strategies that pass liquidity, risk, and cost checks.
Possible structures include:

-   Directional: long call/put, bull call spread, bear put spread.
-   Credit spreads: bull put spread, bear call spread.
-   Range/volatility structures: defined-risk iron condor, where
    appropriate.

Strategy generation must account for expiry, volatility regime, event
risk, capital, max loss, payoff, Greeks, and liquidity. Do not recommend
a structure simply because the signal category has a bullish or bearish
label.

## 11. Strategy Evaluation and Recommendation

For each strategy candidate, calculate and display:

-   Structure, legs, expiry, strikes, quantities, and lot size.
-   Estimated entry debit/credit and breakeven(s).
-   Maximum profit and maximum loss.
-   Required capital/margin and capital at risk.
-   Reward-to-risk and payoff at relevant scenarios.
-   Delta, gamma, theta, vega, and IV sensitivity.
-   Probability-of-profit estimate, including method and limitations.
-   Liquidity/spread assessment and modeled transaction costs.
-   Scenario analysis for spot movement, time decay, and IV change.
-   Exit/adjustment criteria and invalidation conditions.

Default to defined-risk strategies. Any strategy with potentially
unlimited loss requires explicit risk disclosure and a separate
authorization policy. Expected returns and POP are estimates, not
guarantees.

## 12. Portfolio-Aware Smart Trader Alerts

Alerts must account for existing holdings and exposure. Categories:

-   New opportunity.
-   Existing-position conflict.
-   Risk reduction / position-size review.
-   Hedge candidate.
-   Exit or thesis-invalidation review.
-   Reversal watch.
-   No-trade / insufficient evidence.

Example: If a user holds a stock and a short-buildup signal appears,
explain the signal, its confidence and limitations, and potential
choices such as reviewing exposure, reducing size, or evaluating a
hedge. Do not automatically prescribe buying a put; compare hedge cost,
expiry, strike, Greeks, and portfolio risk.

Alerts should include: trigger, evidence, conflicting evidence, data
timestamp, horizon, confidence/score breakdown, relevant position, risk
implications, suggested next step, and a clear "not an order" status.

## 13. User Interface Requirements

### Screen 1 --- F&O Intelligence Dashboard

-   Market regime overview.
-   Four buildup categories with up to five ranked stock candidates
    each.
-   Filters for date, horizon, liquidity, sector, and confidence.
-   Candidate cards showing price/OI changes, RVOL, score components,
    and freshness.
-   Watchlist and alert controls.

### Screen 2 --- Candidate Detail

-   Price and OI chart with event markers.
-   Cash/delivery, technical, fundamental, and event panels.
-   Options-chain interpretation.
-   Signal evidence and counter-evidence.
-   Strategy comparison, risk/payoff, and scenario analysis.
-   Research status and validation coverage.

### Screen 3 --- NIFTY / BANKNIFTY

-   Separate index workspaces.
-   Futures and options structure.
-   Breadth and constituent contribution.
-   Implied move, IV, PCR, strike concentrations.
-   Strategy candidates and defined-risk payoff views.

### Screen 4 --- Threshold Research Workbench

-   Configure threshold grid and outcome horizons.
-   Select universe, period, benchmark, and costs.
-   Run reproducible experiments.
-   Display in-sample, validation, and out-of-sample metrics separately.
-   Compare threshold sensitivity and baselines.
-   Record experiment ID, code/data versions, and promotion decision.

### Screen 5 --- Position Intelligence / Risk Center

-   Existing position exposure and signal conflicts.
-   Hedge alternatives and cost comparison.
-   Concentration, correlation, max loss, and drawdown.
-   Alert history and user decisions.
-   Audit trail.

Design principles: mobile-first, low cognitive load, clear risk
hierarchy, explainability, accessible tables/charts, and no live
execution controls in this scope.

## 14. Data Model --- Proposed Entities

-   `fo_contract_master`
-   `fo_price_oi_snapshot`
-   `fo_options_chain_snapshot`
-   `fo_signal`
-   `fo_signal_rank`
-   `fo_threshold_config`
-   `fo_research_experiment`
-   `fo_research_result`
-   `cash_market_snapshot`
-   `delivery_snapshot`
-   `technical_feature_snapshot`
-   `fundamental_snapshot`
-   `corporate_event`
-   `index_market_snapshot`
-   `strategy_candidate`
-   `strategy_leg`
-   `portfolio_position_snapshot`
-   `risk_alert`
-   `paper_trade`
-   `strategy_evaluation`
-   `audit_event`

Every record should carry instrument identifiers, exchange, contract
expiry where applicable, event timestamp, ingestion timestamp, source,
and data/version lineage. Research artifacts must be reproducible.

## 15. API Surface --- Proposed

-   `GET /api/v1/fo/signals`
-   `GET /api/v1/fo/candidates/{symbol}`
-   `POST /api/v1/fo/strategies/generate`
-   `GET /api/v1/fo/index-intelligence/{index}`
-   `POST /api/v1/fo/index-strategies/generate`
-   `POST /api/v1/fo/research/experiments`
-   `GET /api/v1/fo/research/experiments/{experiment_id}`
-   `POST /api/v1/fo/research/experiments/{experiment_id}/evaluate`
-   `POST /api/v1/fo/research/experiments/{experiment_id}/promote`
-   `GET /api/v1/fo/position-alerts`
-   `POST /api/v1/fo/paper-trades`
-   `GET /api/v1/fo/paper-trades/performance`

API payloads must expose timestamps, source freshness, score version,
threshold version, and explicit caveats for unavailable features.

## 16. Architecture

Suggested logical components:

1.  Market-data adapters and source health monitoring.
2.  Contract master and symbol/expiry normalization.
3.  Time-series storage for prices, OI, options, and derived features.
4.  Feature calculation and regime classification service.
5.  Candidate ranking service.
6.  Cash/delivery, technical, fundamental, and event enrichment.
7.  Strategy construction and payoff/risk engine.
8.  Portfolio exposure and alert service.
9.  Research/backtest/paper-trade engine.
10. API and mobile-first React UI.
11. Audit, monitoring, and data-quality layer.

Use versioned, reproducible jobs. Separate research results from
production signal state. Record data gaps and never silently substitute
stale observations.

## 17. Backtesting and Paper Trading

### Backtest requirements

-   Use point-in-time observations and realistic entry/exit timing.
-   Avoid same-bar execution assumptions that cannot be achieved.
-   Model spread, slippage, market impact, brokerage, STT, exchange
    fees, GST, stamp duty, and other applicable costs.
-   Handle expiry, rollovers, lot sizes, corporate actions, and contract
    changes.
-   Track signal-to-entry delay and missed fills.
-   Report performance by regime, horizon, volatility, instrument, and
    market period.
-   Compare with benchmarks and simple baselines.
-   Preserve all tested variants to account for multiple-testing risk.

### Metrics

-   Precision@5 and recall of qualifying moves.
-   Net expectancy, average win/loss, profit factor.
-   Sharpe/Sortino where appropriate.
-   Maximum drawdown and recovery time.
-   Turnover, costs, slippage, and fill rate.
-   Performance stability and out-of-sample degradation.
-   Hedge effectiveness and portfolio drawdown reduction.
-   Alert relevance and false-positive rate.

### Paper trading

-   Use versioned signals and immutable market snapshots.
-   Simulate realistic fills and costs.
-   Track each strategy from signal to exit.
-   Do not promote based on a short or selectively chosen run.
-   Require pre-registered evaluation windows and documented promotion
    gates.

## 18. Risk Controls and Governance

-   No live order placement in this PRD.
-   Defined-risk strategies preferred.
-   Maximum risk per trade, portfolio drawdown, concentration, and
    correlated exposure must be configurable.
-   NIFTY, BANKNIFTY, and constituent-stock exposure must be treated as
    correlated.
-   Include expiry, gap, event, volatility, liquidity, and
    assignment/exercise risks where relevant.
-   Provide a kill switch for signal publication and strategy
    generation.
-   Maintain an audit trail for data, model, threshold, alert, and user
    decision.
-   Require human review for threshold/model promotion.
-   Show "insufficient data" or "no trade" when quality gates fail.

## 19. Non-Functional Requirements

-   Market-data freshness and source health visible to users.
-   Idempotent ingestion and recovery from failed jobs.
-   Monitoring for missing, stale, duplicated, or anomalous data.
-   Secure access control and encryption for portfolio data.
-   Explainable, versioned outputs.
-   Responsive UI and accessible visualizations.
-   APIs should return clear error and data-quality states.
-   Performance targets must be finalized based on source SLAs and
    expected universe size.

## 20. Acceptance Criteria

### Signal classification

-   Every eligible contract is assigned one of the four classifications
    or "neutral/insufficient data."
-   Classification inputs, interval, and timestamps are visible.
-   Unit tests cover sign combinations, missing data, zero OI, and
    boundary conditions.

### Candidate ranking

-   Up to five candidates per category are returned after eligibility
    filters.
-   Signal strength, tradeability, and strategy quality remain distinct.
-   Every candidate includes supporting and contradicting evidence.
-   No stale or invalid candidate is silently included.

### NIFTY and BANKNIFTY

-   Each index has an independent signal and options analysis.
-   Options OI, IV, expected move, breadth, and constituent context are
    shown when available.
-   Strategy candidates include payoff, max loss, costs, Greeks, and
    risk notes.

### Research and promotion

-   Threshold experiments are reproducible and versioned.
-   Train/validation/out-of-sample results are separated.
-   Costs and realistic execution assumptions are included.
-   No threshold is marked production-approved without positive
    out-of-sample evidence and recorded approval.

### Portfolio intelligence

-   Alerts correctly identify relevant held positions and exposure
    conflicts.
-   Hedge alternatives show hedge cost and residual risk.
-   Alerts do not trigger automatic orders.
-   User actions and alert history are auditable.

## 21. Phased Delivery

### Phase 1 --- Data and Research Foundation

-   Contract master, market data, OI and price snapshots.
-   Data-quality checks and four-regime classification.
-   Threshold Research Workbench.
-   Reproducible historical evaluation and cost model.

**Exit gate:** validated data lineage and an out-of-sample research
report; no unsupported production thresholds.

### Phase 2 --- Candidate Intelligence

-   Top-five candidate rankings per category.
-   Cash/delivery, technical, fundamental, and event enrichment.
-   Candidate detail and explainability UI.

### Phase 3 --- Index Intelligence

-   NIFTY and BANKNIFTY workspaces.
-   Options-chain structure, breadth, constituent contribution.
-   Index-specific strategy comparison.

### Phase 4 --- Portfolio-Aware Risk

-   Position import and exposure mapping.
-   Hedge and risk-reduction alerts.
-   Risk Center and audit trail.

### Phase 5 --- Paper Trading and Controlled Release

-   Strategy paper trading.
-   Pre-registered evaluation.
-   Feature-flagged release after risk/research approval.

## 22. Product Decision

Build the data and research foundation first. The initial deliverable
should be a reproducible threshold-validation report and versioned
research configuration---not a dashboard that presents unvalidated
percentage thresholds as facts. Only evidence-backed signals should
progress to candidate ranking, strategy recommendations, and controlled
rollout.
