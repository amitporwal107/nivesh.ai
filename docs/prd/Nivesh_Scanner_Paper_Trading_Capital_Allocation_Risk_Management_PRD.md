# Nivesh AI --- Scanner-to-Paper Trading, Capital Allocation & Risk Management Platform

**Product Requirements Document (PRD)**

  -----------------------------------------------------------------------
  Document attribute                  Details
  ----------------------------------- -----------------------------------
  Product                             Nivesh AI / Nivesh Copilot

  Module                              Trading Intelligence & Paper
                                      Trading

  Submodules                          Opportunity Engine, Capital
                                      Allocation, Risk Management, Paper
                                      Execution, Portfolio Analytics

  Version                             1.0

  Status                              Product specification

  Target market                       Indian equity and derivatives
                                      markets

  Initial execution mode              Paper trading

  Future execution mode               Broker-connected live trading,
                                      subject to separate authorization
                                      and compliance controls
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 1. Executive Summary

Nivesh requires an intelligent trading portfolio management platform
that converts real-time scanner signals into structured, risk-assessed
paper trading opportunities.

The platform must not automatically convert every scanner signal into a
trade. It must evaluate setup quality, validate underlying market
conditions, calculate entry and exit levels, assess portfolio exposure,
determine position size, and allocate capital according to predefined
risk policies.

The system should continuously monitor open positions and dynamically
calculate:

-   Available capital and deployed capital.
-   Position-level risk.
-   Portfolio-level risk.
-   Sector and correlation exposure.
-   Stop-loss and target levels.
-   Equity and F&O Greeks.
-   Real-time unrealized and realized P&L.
-   Strategy and scanner performance.
-   Drawdown and risk utilization.
-   Capital allocation efficiency.

The objective is to create a disciplined, measurable and explainable
trading environment before considering live execution.

## 1.1 Product vision

Build an intelligent trading portfolio manager that answers five
questions:

1.  **What should we trade?** --- Opportunity Intelligence.
2.  **Should we take the trade?** --- Opportunity Validation.
3.  **How much should we allocate?** --- Capital Allocation.
4.  **What can go wrong?** --- Risk Management.
5.  **Is the strategy actually working?** --- Performance Analytics.

## 1.2 Core design principle

A scanner signal is not a trade. A trade opportunity is not
automatically an approved position. An approved position is not
necessarily an executable order.

The platform must enforce these distinctions throughout its lifecycle.

# 2. Business Objectives

## 2.1 Primary objectives

  -----------------------------------------------------------------------
  Objective                           Expected outcome
  ----------------------------------- -----------------------------------
  Signal conversion                   Convert relevant scanner signals
                                      into actionable opportunities

  Signal consolidation                Prevent duplicate positions from
                                      multiple scanners

  Opportunity validation              Validate trend, volume, price
                                      structure and derivatives
                                      confirmation

  Position sizing                     Calculate quantity using predefined
                                      risk limits

  Capital allocation                  Allocate virtual capital across
                                      eligible opportunities

  Portfolio protection                Enforce position, sector, strategy
                                      and account-level risk limits

  Paper execution                     Simulate realistic order execution
                                      and position management

  Performance measurement             Evaluate actual forward outcomes
                                      and strategy expectancy

  Explainability                      Explain every approval, rejection,
                                      allocation and risk decision
  -----------------------------------------------------------------------

## 2.2 Success metrics

Measure:

-   Percentage of scanner signals converted into qualified
    opportunities.
-   Percentage of qualified opportunities approved by the risk engine.
-   Percentage of approved opportunities successfully entered.
-   Signal-to-entry delay.
-   Slippage between proposed and simulated execution.
-   Win rate.
-   Average winning trade and average losing trade.
-   Expectancy per trade.
-   Profit factor.
-   Maximum drawdown.
-   Return on allocated capital.
-   Return on risk capital.
-   Risk-adjusted returns.
-   Strategy-wise and scanner-wise performance.
-   Percentage of trades violating intended risk limits.
-   Percentage of trades with complete entry, stop-loss and exit data.

**Important:** The scanner score (0--100) is a signal-strength score. It
must not be represented as a probability of profit unless a separate,
statistically validated probability model is developed.

# 3. Scope

## 3.1 In scope --- Phase 1

1.  Scanner signal ingestion.
2.  Signal normalization and deduplication.
3.  Opportunity generation.
4.  Opportunity qualification and validation.
5.  Equity and F&O opportunity support.
6.  Position sizing.
7.  Capital allocation.
8.  Portfolio-level risk management.
9.  Paper order generation and execution.
10. Open position monitoring.
11. Stop-loss and target management.
12. Real-time P&L.
13. Portfolio exposure monitoring.
14. Trade journal and event history.
15. Performance analytics.
16. Risk alerts and kill switch.
17. Configurable paper trading accounts and risk policies.

## 3.2 Out of scope --- Initial release

-   Unrestricted live order execution.
-   Unsupervised AI modification of account risk limits.
-   Guaranteed profit or return prediction.
-   Automatic allocation based solely on scanner scores.
-   Unvalidated machine-learning probability estimates.
-   Complex multi-account institutional execution.
-   Tax filing and tax optimization.
-   Broker reconciliation as a mandatory Phase 1 dependency.

# 4. User Personas

  -----------------------------------------------------------------------
  Persona                             Requirements
  ----------------------------------- -----------------------------------
  Retail trader                       Simple paper trading, position
                                      sizing and risk visibility

  Positional trader                   Swing opportunities, ATR stops,
                                      targets and portfolio risk

  Intraday trader                     Fast signal qualification,
                                      liquidity checks and intraday
                                      limits

  F&O trader                          Options Greeks, spread risk, margin
                                      and expiry management

  Research analyst                    Scanner performance, setup
                                      validation and strategy comparison

  Portfolio manager                   Capital allocation, diversification
                                      and risk-adjusted performance

  Administrator                       Risk policies, account limits,
                                      permissions and audit logs
  -----------------------------------------------------------------------

# 5. Product Architecture

## 5.1 High-level architecture

``` text
                 MARKET DATA SOURCES
                         |
       NSE / BSE / Broker / Options Chain / F&O
                         |
                  MARKET DATA ENGINE
                         |
                   SCANNER ENGINE
                         |
                 SCANNER EVENT BUS
                         |
              SIGNAL NORMALIZATION
                         |
             SIGNAL CONSOLIDATION
                         |
                OPPORTUNITY ENGINE
                         |
               OPPORTUNITY VALIDATOR
                         |
                 STRATEGY ENGINE
                         |
              CAPITAL ALLOCATION ENGINE
                         |
                  RISK ENGINE
                         |
              PAPER ORDER MANAGEMENT
                         |
                EXECUTION SIMULATOR
                         |
                 POSITION MANAGER
                         |
             PORTFOLIO RISK MONITOR
                         |
               PERFORMANCE ANALYTICS
                         |
                    NIVESh UI
```

## 5.2 Core services

  -----------------------------------------------------------------------
  Service                             Responsibility
  ----------------------------------- -----------------------------------
  Scanner Event Consumer              Receives scanner events

  Signal Normalizer                   Standardizes scanner output

  Signal Consolidator                 Combines related signals for the
                                      same instrument

  Opportunity Engine                  Creates structured trade
                                      opportunities

  Opportunity Validator               Checks market and technical
                                      confirmation

  Strategy Engine                     Generates entry, stop and target
                                      rules

  Position Sizing Engine              Calculates appropriate quantity

  Capital Allocation Engine           Allocates virtual capital

  Risk Engine                         Enforces all risk constraints

  Paper Order Manager                 Creates virtual orders

  Execution Simulator                 Simulates fills, costs and slippage

  Position Manager                    Tracks open and closed positions

  Portfolio Monitor                   Calculates portfolio-level
                                      exposures

  F&O Risk Engine                     Calculates Greeks and
                                      strategy-level risk

  Performance Engine                  Calculates performance and strategy
                                      statistics

  Notification Engine                 Sends alerts

  Audit Service                       Maintains complete decision history
  -----------------------------------------------------------------------

# 6. Scanner Signal Management

## 6.1 Existing scanner integration

The platform must accept signals from enabled scanner categories:

-   Breakout scanners.
-   Momentum scanners.
-   Volume expansion scanners.
-   Chart pattern scanners.
-   Multi-timeframe technical scanners.
-   F&O positioning scanners.
-   Fundamental scanners.
-   Falling-stock scanners.
-   Intraday movement scanners.

## 6.2 Standard scanner event

Every scanner must publish a normalized event.

  Field                Description
  -------------------- -----------------------------------
  signal_id            Unique signal identifier
  scanner_id           Source scanner
  scanner_name         Scanner display name
  instrument_id        Internal instrument identifier
  symbol               Trading symbol
  exchange             NSE/BSE
  segment              Equity/Futures/Options
  direction            Bullish/Bearish/Neutral
  timeframe            5m, 15m, 1D, 1W etc.
  detected_at          Original signal timestamp
  detected_price       Price at detection
  scanner_score        Existing scanner score
  score_version        Scanner scoring version
  signal_type          Breakout, reversal, momentum etc.
  supporting_metrics   Scanner-specific observations
  market_regime        Market regime at detection
  expiry_at            Signal expiry, where applicable

## 6.3 Signal normalization

Signals from different scanners must be standardized into a common
format.

For example, a 52-week breakout, high-volume breakout, multiyear
breakout and price-above-moving-average signal may all refer to the same
instrument and direction.

The platform must consolidate these into one opportunity rather than
creating four separate positions.

## 6.4 Signal consolidation rules

A consolidation key should consider:

-   Instrument.
-   Exchange.
-   Direction.
-   Strategy family.
-   Relevant time window.

Different strategy families must remain identifiable.

Example:

  Scanner                Signal                      Direction
  ---------------------- --------------------------- -----------
  Multiyear breakout     Breakout                    Bullish
  High-volume breakout   Volume confirmation         Bullish
  Delivery + volume      Accumulation confirmation   Bullish
  Fresh long buildup     Derivatives confirmation    Bullish

Result: one bullish opportunity with four supporting signals.

The system must preserve all original signal IDs and timestamps.

## 6.5 Signal score versus opportunity score

Three distinct metrics must be maintained.

  -----------------------------------------------------------------------
  Metric                              Purpose
  ----------------------------------- -----------------------------------
  Scanner score                       Strength of the individual scanner
                                      signal

  Opportunity score                   Quality of the consolidated trade
                                      setup

  Outcome probability                 Statistically calibrated likelihood
                                      of a defined outcome
  -----------------------------------------------------------------------

These metrics must never be conflated.

The opportunity score can consider:

-   Number of independent confirmations.
-   Trend alignment.
-   Relative volume.
-   Delivery participation.
-   Price structure.
-   Market breadth.
-   Sector strength.
-   F&O positioning.
-   Liquidity.
-   Volatility suitability.

A scanner score of 85 does not mean an 85% probability of success.

# 7. Opportunity Intelligence Engine

## 7.1 Objective

Convert normalized scanner signals into complete trade opportunities.

Every opportunity must contain:

-   Instrument.
-   Direction.
-   Strategy.
-   Time horizon.
-   Entry trigger.
-   Entry price or entry range.
-   Stop-loss.
-   Target 1.
-   Target 2.
-   Expiry or time-based exit.
-   Risk/reward.
-   Liquidity assessment.
-   Supporting evidence.
-   Invalidation conditions.
-   Opportunity score.
-   Validation status.

## 7.2 Opportunity categories

  Category                  Examples
  ------------------------- ----------------------------------------------
  Breakout                  Multiyear breakout, 52-week breakout
  Reversal                  Triple bottom, oversold reversal
  Momentum continuation     Strong stocks, RSI momentum
  Volume expansion          High relative volume, unusual volume
  Derivatives positioning   Long buildup, short covering
  Fundamental repricing     Strong results, EPS growth, valuation
  Breakdown                 Moving average breakdown, large-cap weakness

## 7.3 Opportunity validation

### A. Market validation

-   Nifty trend.
-   Bank Nifty trend.
-   Market breadth.
-   Sectoral index direction.
-   India VIX.
-   Global market context, where available.
-   Market regime.

### B. Stock validation

-   Price versus EMA20, EMA50 and EMA200.
-   RSI.
-   MACD.
-   ADX.
-   ATR%.
-   Relative strength.
-   Relative volume.
-   Delivery percentage.
-   Support and resistance.
-   Recent swing highs and lows.

### C. Derivatives validation

For F&O instruments:

-   Futures price.
-   Futures open interest.
-   Change in open interest.
-   Price and OI relationship.
-   Put-call ratio.
-   ATM implied volatility.
-   IV percentile/rank, where available.
-   Expected move.
-   Max pain as contextual information.
-   Option chain liquidity.
-   Bid-ask spread.
-   Delta.
-   Gamma.
-   Theta.
-   Vega.
-   Expiry proximity.

### D. Risk validation

-   Entry-to-stop distance.
-   Expected reward.
-   Liquidity.
-   Gap risk.
-   Volatility.
-   Existing portfolio exposure.
-   Sector concentration.
-   Correlation with existing positions.

## 7.4 Validation outcome

  Status            Meaning
  ----------------- ------------------------------------------------
  QUALIFIED         Meets opportunity criteria
  CONDITIONAL       Meets criteria after a specified trigger
  WATCHLIST         Interesting but not ready
  REJECTED          Fails validation
  EXPIRED           Signal no longer valid
  BLOCKED_BY_RISK   Setup valid but portfolio risk prohibits entry

## 7.5 Opportunity example

*Illustrative example only.*

  Attribute                                 Value
  ---------------- ------------------------------
  Instrument                              ABC Ltd
  Signal sources     Breakout + Volume + Delivery
  Direction                               Bullish
  Current price                              ₹500
  Entry trigger                              ₹505
  Stop-loss                                  ₹485
  Target 1                                   ₹545
  Target 2                                   ₹585
  Risk per share                              ₹20
  Reward to T1                                ₹40
  Reward to T2                                ₹80
  R:R to T1                                   2:1
  R:R to T2                                   4:1

The opportunity is passed to the position sizing and risk engines. It is
not automatically approved.

# 8. Capital Allocation Engine

## 8.1 Objective

Allocate available virtual capital across eligible opportunities while
maintaining predefined portfolio risk limits.

The engine must distinguish:

1.  Account equity.
2.  Available capital.
3.  Deployed capital.
4.  Capital reserved for pending orders.
5.  Planned stop-loss risk.
6.  Stressed portfolio risk.
7.  Margin requirement.
8.  Available risk budget.

Capital allocation must not be based only on the opportunity score.

## 8.2 Account equity calculation

\[ Account Equity = Cash + Realized P&L + Unrealized P&L \]

For a paper account, maintain an auditable cash ledger and position
valuation ledger.

## 8.3 Risk budget

\[ Risk Budget = Account Equity `\times `{=tex}Risk Percentage \]

Example:

-   Account equity: ₹10,00,000.
-   Risk percentage: 0.5%.

\[ Risk Budget = ₹10,00,000 `\times 0.005`{=tex} = ₹5,000 \]

This is the maximum planned loss for that position under its defined
stop assumptions, before any gap or execution uncertainty.

## 8.4 Position sizing

For a long equity position:

\[ Risk Per Share = Entry - StopLoss \]

\[ Quantity = `\left`{=tex}`\lfloor`{=tex}
`\frac{Allowed\ Risk}{Risk\ Per\ Share + Estimated\ Cost\ Per\ Share}`{=tex}
`\right`{=tex}`\rfloor`{=tex} \]

Example:

-   Account equity: ₹10,00,000.
-   Risk budget: ₹5,000.
-   Entry: ₹500.
-   Stop-loss: ₹480.
-   Estimated costs per share: ₹0.50.

\[ Quantity = `\left`{=tex}`\lfloor `{=tex}`\frac{5000}{20.50}`{=tex}
`\right`{=tex}`\rfloor `{=tex}= 243 \]

Approximate capital deployed:

\[ 243 `\times 500`{=tex} = ₹1,21,500 \]

Planned risk, including estimated costs, is approximately ₹4,981.50.

The actual quantity must also satisfy liquidity, exposure and
available-capital constraints.

## 8.5 ATR-based stop-loss

\[ ATR Stop = Entry - (ATR `\times `{=tex}Multiplier) \]

For long positions:

\[ StopLoss = Entry - (2 `\times `{=tex}ATR) \]

For short positions:

\[ StopLoss = Entry + (2 `\times `{=tex}ATR) \]

The ATR multiplier must be strategy-configurable.

Support:

-   ATR-based stop.
-   Swing-low/high stop.
-   Percentage stop.
-   Structure-based stop.
-   Strategy-defined stop.

A stop must not be moved further away merely to accommodate a larger
position.

## 8.6 Initial account allocation policy

Provide configurable allocation buckets.

Example starting configuration:

  Segment                 Allocation
  --------------------- ------------
  Equity positional              45%
  Equity intraday                25%
  F&O strategies                 20%
  Unallocated reserve            10%

These are configurable simulation defaults, not investment
recommendations or empirically optimized allocations.

The platform should support fixed, dynamic, strategy-specific,
market-regime, risk-parity and user-defined allocation.

## 8.7 Opportunity ranking

The allocation engine should consider:

-   Opportunity score.
-   Expected reward/risk.
-   Estimated expectancy.
-   Historical strategy performance.
-   Liquidity.
-   Volatility.
-   Sector concentration.
-   Correlation.
-   Current open risk.
-   Available capital.
-   Market regime.

The system must not simply allocate the largest capital to the highest
scanner score.

## 8.8 Allocation optimization

An illustrative objective:

\[ `\max`{=tex}\_w `\left`{=tex}( ExpectedReturn(w) -
`\lambda `{=tex}`\times `{=tex}PortfolioRisk(w) `\right`{=tex}) \]

Subject to:

-   Total allocated capital within account limits.
-   Maximum instrument exposure.
-   Maximum sector exposure.
-   Maximum open risk.
-   Minimum liquidity requirements.
-   Strategy allocation limits.
-   F&O margin and maximum-loss constraints.

Optimization output must be subject to the deterministic risk engine.
The optimizer cannot override hard risk limits.

# 9. Risk Management Engine

## 9.1 Objective

The Risk Engine is the final authority on whether a trade can be opened,
increased, modified or continued.

It must be independent of the Opportunity Engine and Capital Allocation
Engine.

A valid opportunity can still be rejected by the Risk Engine.

## 9.2 Position-level risk

Calculate:

-   Entry price.
-   Stop-loss price.
-   Risk per share or contract.
-   Quantity.
-   Gross exposure.
-   Planned loss.
-   Target profit.
-   Risk/reward.
-   Estimated costs.
-   Gap-risk estimate.
-   Stressed loss.

### Planned risk

\[ PlannedRisk = Quantity `\times `{=tex}(Entry - StopLoss) \]

For short positions, reverse the price difference.

### Stressed risk

Calculate a separate stressed loss incorporating assumptions for:

-   Gap beyond stop.
-   Slippage.
-   Bid-ask spread.
-   Reduced liquidity.
-   Volatility expansion.
-   Correlated positions moving together.

A stop-loss is not a guarantee of the maximum realized loss.

## 9.3 Portfolio open risk

\[ PortfolioOpenRisk = `\sum`{=tex}\_{i=1}\^{n} PositionRisk_i \]

The system should also calculate:

-   Gross exposure.
-   Net exposure.
-   Sector exposure.
-   Strategy exposure.
-   Correlation-adjusted exposure.
-   Stressed portfolio loss.
-   F&O maximum loss.
-   Margin utilization.

## 9.4 Risk limits

Initial example configuration:

  Risk control                        Illustrative default
  --------------------------------- ----------------------
  Positional trade risk                    0.50% of equity
  Intraday trade risk                                0.35%
  F&O strategy risk                                  0.35%
  Maximum single trade risk                          0.75%
  Maximum total open planned risk                    3.00%
  Daily loss limit                                   1.50%
  Weekly loss limit                                  3.00%
  Drawdown warning                                   4.00%
  Restricted trading threshold                       4.00%
  Trading halt threshold                             6.00%
  Maximum single-stock exposure                     15.00%
  Maximum positions                                     10

All values must be configurable by account and strategy. These are
starting simulation parameters and must be validated using historical
and forward paper-trading results.

## 9.5 Daily loss limit

\[ DailyLoss = RealizedLoss + UnrealizedLoss \]

Include fees and other costs in net P&L and loss-limit calculations.

When the configured limit is breached:

-   Block new positions.
-   Block risk-increasing orders.
-   Permit risk-reducing exits.
-   Generate an alert.
-   Record the breach.
-   Require an authorized reset or next-session policy.

## 9.6 Drawdown calculation

\[ Drawdown = `\frac{PeakEquity - CurrentEquity}{PeakEquity}`{=tex}
`\times 100`{=tex} \]

Example:

-   Peak equity: ₹10,50,000.
-   Current equity: ₹10,00,000.
-   Drawdown: 4.76%.

The risk engine should reduce permitted risk as drawdown increases.

## 9.7 Drawdown-based risk reduction

Illustrative policy:

  Drawdown   Risk policy
  ---------- ------------------------
  0--2%      Normal configured risk
  2--4%      Reduce new trade risk
  4--6%      Restricted mode
  Above 6%   Halt new entries

Exact thresholds must be configurable and tested.

## 9.8 Correlation risk

The system must identify highly correlated positions.

Example: HDFC Bank, ICICI Bank, Axis Bank and SBI are four different
stocks, but their risk may be concentrated in the banking sector.

Calculate:

-   Pairwise return correlation.
-   Sector exposure.
-   Sector-level planned risk.
-   Sector-level stressed risk.
-   Portfolio covariance.
-   Marginal risk contribution.

Historical correlation must use point-in-time price data and an
explicitly configured observation window.

## 9.9 Risk engine decisions

  Decision               Meaning
  ---------------------- -------------------------------------------------
  APPROVE                All required controls passed
  APPROVE_REDUCED        Approve with lower quantity
  CONDITIONAL_APPROVAL   Wait for a specified price or condition
  REJECT                 Hard rule failed
  BLOCKED                Account or portfolio risk limit breached
  EXIT_REQUIRED          Existing position requires risk-reducing action
  HALT_ACCOUNT           Trading halted by account policy

Every decision must include machine-readable reason codes and
human-readable explanations.

# 10. F&O Risk Management

F&O must have a dedicated strategy-level risk engine.

## 10.1 Supported strategy types

Initial templates:

-   Long Call.
-   Long Put.
-   Bull Call Spread.
-   Bear Put Spread.
-   Bear Call Spread.
-   Bull Put Spread.
-   Covered Call.
-   Protective Put.
-   Call Ratio Spread.
-   Put Ratio Spread.

Additional multi-leg strategies can be added later.

## 10.2 Required data

-   Underlying spot price.
-   Futures price.
-   Strike.
-   Expiry.
-   Option type.
-   Bid and ask.
-   LTP.
-   Volume.
-   Open interest.
-   OI change.
-   Implied volatility.
-   Delta.
-   Gamma.
-   Theta.
-   Vega.
-   Contract lot size.
-   Margin requirement.

## 10.3 Strategy-level risk

For defined-risk spreads, calculate:

-   Maximum profit.
-   Maximum loss.
-   Breakeven points.
-   Net debit or credit.
-   Margin requirement.
-   Net Delta.
-   Net Gamma.
-   Net Theta.
-   Net Vega.
-   Expiry payoff.
-   Scenario P&L.

The risk engine must use strategy-level maximum loss, not margin, as the
primary loss-risk measure for defined-risk strategies.

For naked or theoretically unlimited-risk positions, apply stricter
policies and require explicit account authorization. Such strategies
should be disabled by default in the initial release.

## 10.4 Greeks

\[ NetDelta = `\sum`{=tex}\_i Delta_i `\times `{=tex}Quantity_i
`\times `{=tex}LotSize_i \]

\[ NetGamma = `\sum`{=tex}\_i Gamma_i `\times `{=tex}Quantity_i
`\times `{=tex}LotSize_i \]

\[ NetTheta = `\sum`{=tex}\_i Theta_i `\times `{=tex}Quantity_i
`\times `{=tex}LotSize_i \]

\[ NetVega = `\sum`{=tex}\_i Vega_i `\times `{=tex}Quantity_i
`\times `{=tex}LotSize_i \]

The implementation must document Greek units, contract multipliers,
quote conventions and sign conventions.

## 10.5 Scenario analysis

Support:

-   Underlying +1%, +2%, +3%.
-   Underlying −1%, −2%, −3%.
-   IV +5 and +10 volatility points.
-   IV −5 and −10 volatility points.
-   One trading day of theta decay.
-   Two trading days of theta decay.
-   Combined spot and volatility shock.
-   Expiry payoff.

These are scenario assumptions, not forecasts.

## 10.6 F&O position restrictions

-   Reject contracts with insufficient liquidity.
-   Apply bid-ask spread limits.
-   Apply expiry proximity restrictions.
-   Validate lot size.
-   Validate margin availability.
-   Validate maximum strategy loss.
-   Prevent unintended naked legs.
-   Monitor partial fills and legging risk.
-   Require a defined exit plan.

# 11. Paper Trading Engine

## 11.1 Objective

Create realistic simulated positions from approved opportunities.

The system must support three operating modes:

  -----------------------------------------------------------------------
  Mode                                Description
  ----------------------------------- -----------------------------------
  Automatic paper trading             Approved opportunities
                                      automatically generate simulated
                                      orders

  Approval-based paper trading        User approves each opportunity
                                      before order creation

  Signal tracking                     Tracks opportunities without
                                      creating positions
  -----------------------------------------------------------------------

## 11.2 Order types

-   Market.
-   Limit.
-   Stop-loss.
-   Stop-loss market.
-   Target limit.
-   Multi-leg strategy orders.

Only order types supported by the selected simulation model should be
enabled.

## 11.3 Execution simulation

The simulator must not assume every order fills at LTP.

It should account for:

-   Bid-ask spread.
-   Available liquidity.
-   Order type.
-   Price movement.
-   Slippage.
-   Partial fills.
-   Market gaps.
-   Trading session.
-   Transaction costs.
-   Exchange and broker charges, where modeled.

For a buy marketable order, use executable ask-side pricing and modeled
slippage. For a sell marketable order, use executable bid-side pricing
and modeled slippage.

Historical backtests must not use information that was unavailable at
the simulated decision time.

## 11.4 Position lifecycle

``` text
SIGNAL_RECEIVED
      |
SIGNAL_NORMALIZED
      |
SIGNAL_CONSOLIDATED
      |
OPPORTUNITY_CREATED
      |
OPPORTUNITY_VALIDATED
      |
RISK_CHECK
      |
   APPROVED?
    /    \
  NO      YES
  |        |
REJECTED  ORDER_CREATED
           |
       ORDER_PENDING
           |
       ORDER_FILLED
           |
       POSITION_OPEN
           |
     POSITION_MONITORING
           |
     PARTIAL_EXIT / MODIFY
           |
      POSITION_CLOSED
           |
      TRADE_ANALYTICS
```

Other supported terminal states:

-   EXPIRED.
-   CANCELLED.
-   BLOCKED_BY_RISK.
-   REJECTED.
-   EXECUTION_FAILED.

## 11.5 Position monitoring

For each open position, continuously monitor:

-   LTP and executable bid/ask.
-   Unrealized P&L.
-   Realized P&L.
-   Stop-loss distance.
-   Target distance.
-   Planned risk remaining.
-   Current R multiple.
-   Time in position.
-   Volume and liquidity.
-   Market and sector trend.
-   Relevant F&O data.
-   Greeks for options positions.

## 11.6 Stop-loss and target management

Support:

-   Fixed stop-loss.
-   ATR trailing stop.
-   Swing-based trailing stop.
-   Breakeven stop.
-   Target 1 partial exit.
-   Target 2 exit.
-   Time-based exit.
-   Technical invalidation exit.

Every modification must record:

-   Previous value.
-   New value.
-   Timestamp.
-   Reason.
-   Initiating user or service.
-   Related market data.

Risk-increasing modifications must pass through the Risk Engine again.

# 12. Portfolio Dashboard

## 12.1 Overview screen

Display:

-   Account equity.
-   Available cash.
-   Deployed capital.
-   Reserved capital.
-   Unrealized P&L.
-   Realized P&L.
-   Total open planned risk.
-   Stressed portfolio risk.
-   Daily P&L.
-   Drawdown.
-   Active positions.
-   Pending orders.
-   Risk-limit utilization.

## 12.2 Open positions

  Column             Description
  ------------------ ----------------------------------------
  Instrument         Stock or F&O strategy
  Direction          Long/Short
  Strategy           Setup type
  Entry price        Average fill
  LTP                Latest available price
  Quantity           Open quantity
  Invested capital   Deployed amount
  Stop-loss          Current SL
  Target             Next target
  Unrealized P&L     Live simulated P&L
  Planned risk       Risk at current stop
  R multiple         Current return divided by initial risk
  Greeks             For F&O
  Status             Position lifecycle status

## 12.3 Capital allocation view

Display capital allocation by:

-   Asset class.
-   Strategy.
-   Sector.
-   Instrument.
-   Time horizon.
-   Risk contribution.

Use both capital utilization and risk utilization. A small capital
allocation can still carry large risk.

## 12.4 Risk dashboard

Show:

-   Total open risk.
-   Available risk budget.
-   Daily loss utilization.
-   Weekly loss utilization.
-   Drawdown.
-   Sector concentration.
-   Correlation concentration.
-   F&O Greeks.
-   Margin utilization.
-   Stressed portfolio loss.
-   Active risk warnings.

## 12.5 Scanner opportunity dashboard

Show:

-   New scanner signals.
-   Consolidated opportunities.
-   Supporting scanner signals.
-   Opportunity score.
-   Validation status.
-   Proposed entry.
-   Stop-loss.
-   Targets.
-   Risk/reward.
-   Suggested quantity.
-   Proposed capital.
-   Planned risk.
-   Risk engine decision.
-   Rejection reason.

## 12.6 Trade journal

Each trade must include:

-   Original scanner signals.
-   Original signal timestamps and scores.
-   Opportunity validation.
-   Allocation decision.
-   Risk decision.
-   Entry and exit fills.
-   Stop-loss and target changes.
-   P&L.
-   MFE and MAE.
-   Strategy.
-   Market regime.
-   Exit reason.
-   User notes.
-   Complete event history.

# 13. Performance Analytics

## 13.1 Signal performance

Measure the predictive value of scanner signals independently of
trading.

Required metrics:

-   T+1 return.
-   T+5 return.
-   T+10 return.
-   T+20 return.
-   Maximum favorable excursion.
-   Maximum adverse excursion.
-   Target hit rate.
-   Stop-loss hit rate.
-   Signal fade rate.
-   Signal coverage.
-   Performance by scanner.
-   Performance by scanner combination.
-   Performance by market regime.

## 13.2 Trade performance

Measure actual paper-trading results.

Required metrics:

-   Number of trades.
-   Win rate.
-   Average win.
-   Average loss.
-   Expectancy.
-   Profit factor.
-   Net P&L.
-   Return on capital.
-   Return on risk capital.
-   Maximum drawdown.
-   Sharpe ratio.
-   Sortino ratio.
-   Average holding period.
-   Slippage.
-   Transaction costs.
-   MFE and MAE.

## 13.3 Expectancy

\[ Expectancy = (WinRate `\times `{=tex}AverageWin) - (LossRate
`\times `{=tex}AverageLoss) \]

Include costs in realized net outcomes.

## 13.4 Profit factor

\[ ProfitFactor = `\frac{GrossProfit}{|GrossLoss|}`{=tex} \]

## 13.5 Return on risk capital

\[ ReturnOnRiskCapital =
`\frac{NetProfit}{TotalInitialRiskAllocated}`{=tex} \]

Define the aggregation period and denominator consistently before
comparing strategies.

## 13.6 Scanner and strategy attribution

The analytics engine must identify:

-   Best-performing scanners.
-   Worst-performing scanners.
-   Best scanner combinations.
-   Best strategy families.
-   Best market regimes.
-   Best holding periods.
-   Best exit methods.
-   Strategies with high drawdown.
-   Strategies with insufficient sample size.

Do not rank strategies solely by win rate.

## 13.7 Minimum evidence policy

A strategy should not receive increased risk merely because of a small
number of winning trades.

The system must show:

-   Sample size.
-   Confidence intervals where feasible.
-   In-sample results.
-   Out-of-sample results.
-   Walk-forward results.
-   Market regime coverage.
-   Cost sensitivity.
-   Drawdown distribution.

A configurable minimum evidence requirement should be enforced before
any strategy's risk allocation is increased.

# 14. Data Requirements

## 14.1 Data source inventory

  -----------------------------------------------------------------------
  Data                    Primary use             Required frequency
  ----------------------- ----------------------- -----------------------
  Scanner signals         Opportunity discovery   Event-driven

  Equity LTP and quotes   Position monitoring     Real-time or best
                                                  available

  OHLCV                   Technical validation    1m/5m/15m/daily

  ATR and indicators      Stops and validation    On bar updates

  Market indices          Market regime           Real-time or periodic

  Sector indices          Sector strength         Real-time or periodic

  Delivery data           Accumulation            Daily
                          confirmation            

  Futures OI              Positioning analysis    Intraday/daily

  Options chain           F&O validation          Real-time or periodic

  Greeks and IV           F&O risk                Recalculated on market
                                                  updates

  Fundamentals            Fundamental validation  On publication/update

  Shareholding            Ownership analysis      Quarterly

  Corporate actions       Price and position      Event-driven
                          adjustments             

  Account ledger          Equity and available    Event-driven
                          capital                 

  Orders and fills        Paper execution         Event-driven
  -----------------------------------------------------------------------

## 14.2 Existing Nivesh data integration

Integrate with existing data assets where available:

-   `stock_features_daily`.
-   Scanner signal/event records.
-   Equity OHLCV data.
-   Delivery quantity and percentage.
-   F&O bhavcopy.
-   Futures OI history.
-   Options chain snapshots.
-   Options Greeks and IV.
-   Shareholding history.
-   Corporate announcements.
-   Fundamental and financial results.

The platform must maintain source, timestamp, freshness and quality
metadata.

## 14.3 Point-in-time data requirement

Every signal, opportunity, risk decision and trade must retain the data
available at the time of the decision.

Historical research must not use future data.

Store:

-   Event timestamp.
-   Market data timestamp.
-   Ingestion timestamp.
-   Calculation timestamp.
-   Data source.
-   Feature version.
-   Scanner version.
-   Strategy version.
-   Risk policy version.

This is mandatory for credible backtesting and performance attribution.

# 15. Mathematical and Quantitative Libraries

Use established numerical libraries for research and optimization, while
keeping critical production risk rules deterministic and independently
testable.

  Library          Role
  ---------------- ------------------------------------------------
  NumPy            Numerical calculations
  Pandas           Time-series and portfolio data
  SciPy            Statistics and numerical optimization
  TA-Lib           Technical indicators
  Riskfolio-Lib    Risk parity, CVaR and portfolio risk analysis
  PyPortfolioOpt   Portfolio optimization and allocation research
  CVXPY            Constrained optimization
  QuantStats       Historical performance analytics
  VectorBT         Strategy research and backtesting
  QuantLib         Options pricing and quantitative finance

## 15.1 Recommended implementation strategy

**Production calculations**

Implement and test deterministic business rules in Nivesh's own Python
services:

-   Position sizing.
-   Stop-loss calculations.
-   Risk limits.
-   Exposure calculations.
-   F&O maximum-loss checks.
-   Margin checks.
-   P&L calculations.
-   Order and position state transitions.

**Research and optimization**

Use quantitative libraries for:

-   Risk parity.
-   Portfolio optimization.
-   CVaR.
-   Historical strategy testing.
-   Performance analysis.
-   Statistical validation.
-   Options valuation research.

Do not run a complex portfolio optimizer on every market tick.
Recalculate when a material event occurs or on a configured schedule.

All quantitative library outputs must be validated against independent
reference calculations and known test cases before production use.

# 16. Database Design

Use PostgreSQL as the system of record.

## 16.1 Account and configuration tables

### `paper_trading_accounts`

  Field             Type
  ----------------- -----------
  id                UUID
  user_id           UUID
  account_name      VARCHAR
  initial_capital   NUMERIC
  current_cash      NUMERIC
  current_equity    NUMERIC
  account_mode      VARCHAR
  status            VARCHAR
  created_at        TIMESTAMP

### `risk_account_config`

  Field                     Type
  ------------------------- -----------
  id                        UUID
  account_id                UUID
  max_trade_risk_pct        NUMERIC
  max_open_risk_pct         NUMERIC
  daily_loss_limit_pct      NUMERIC
  weekly_loss_limit_pct     NUMERIC
  max_drawdown_pct          NUMERIC
  max_positions             INTEGER
  max_stock_exposure_pct    NUMERIC
  max_sector_exposure_pct   NUMERIC
  allow_equity              BOOLEAN
  allow_intraday            BOOLEAN
  allow_fo                  BOOLEAN
  config_version            INTEGER
  updated_at                TIMESTAMP

## 16.2 Scanner and opportunity tables

-   `scanner_signal_events`: immutable scanner events.
-   `scanner_signal_sources`: all original signals contributing to a
    consolidated opportunity.
-   `opportunities`: consolidated opportunities.
-   `opportunity_validations`: validation results and reason codes.
-   `opportunity_metrics`: technical, liquidity, market and derivatives
    metrics.
-   `opportunity_strategy_plans`: proposed entry, stop, targets, expiry
    and strategy rules.

## 16.3 Allocation and risk tables

-   `risk_allocation_decisions`: proposed and approved allocations.
-   `position_risk_metrics`: position-level risk calculations.
-   `portfolio_exposure_snapshots`: portfolio-level exposure snapshots.
-   `portfolio_stress_results`: scenario and stress-test outcomes.
-   `risk_events`: every risk warning, rejection, breach and override
    attempt.
-   `risk_policy_versions`: versioned risk policies.

## 16.4 Paper trading tables

-   `paper_orders`: simulated orders.
-   `paper_order_fills`: individual simulated fills.
-   `paper_positions`: current open positions.
-   `paper_position_events`: position changes and lifecycle events.
-   `paper_trades`: completed trade records.
-   `paper_trade_legs`: multi-leg F&O trade components.
-   `paper_account_ledger`: cash movements, charges and realized P&L
    entries.
-   `paper_position_snapshots`: historical position and P&L snapshots.

## 16.5 Analytics tables

-   `scanner_performance_metrics`: scanner-level forward outcomes.
-   `strategy_performance_metrics`: strategy-level trading performance.
-   `trade_outcome_observations`: signal and opportunity outcome
    observations.
-   `portfolio_performance_snapshots`: daily portfolio performance.
-   `strategy_allocation_history`: historical strategy risk and capital
    allocations.

## 16.6 Database principles

-   Use UUID primary keys.
-   Store money and prices using appropriate NUMERIC precision.
-   Store timestamps in UTC and preserve exchange-local trading date.
-   Maintain immutable event history.
-   Version strategies, scanners and risk policies.
-   Use unique idempotency keys for incoming events.
-   Use transactional updates for order, fill and position accounting.
-   Index account, instrument, status and timestamp fields.
-   Partition high-volume event and snapshot tables by time where
    required.

# 17. API Requirements

Use FastAPI with versioned REST endpoints and WebSocket channels.

## 17.1 Account APIs

``` http
GET    /api/v1/paper/accounts
POST   /api/v1/paper/accounts
GET    /api/v1/paper/accounts/{account_id}
PUT    /api/v1/paper/accounts/{account_id}/config
GET    /api/v1/paper/accounts/{account_id}/ledger
```

## 17.2 Scanner and opportunity APIs

``` http
GET    /api/v1/scanner/signals
GET    /api/v1/scanner/signals/{signal_id}
GET    /api/v1/opportunities
GET    /api/v1/opportunities/{opportunity_id}
POST   /api/v1/opportunities/{opportunity_id}/validate
POST   /api/v1/opportunities/{opportunity_id}/approve
POST   /api/v1/opportunities/{opportunity_id}/reject
```

## 17.3 Allocation and risk APIs

``` http
POST   /api/v1/risk/calculate-position-size
POST   /api/v1/risk/validate-trade
GET    /api/v1/risk/account/{account_id}
GET    /api/v1/risk/exposures/{account_id}
GET    /api/v1/risk/stress-test/{account_id}
GET    /api/v1/allocation/recommendations/{account_id}
POST   /api/v1/allocation/recalculate/{account_id}
```

## 17.4 Paper trading APIs

``` http
POST   /api/v1/paper/orders
GET    /api/v1/paper/orders
GET    /api/v1/paper/orders/{order_id}
POST   /api/v1/paper/orders/{order_id}/cancel

GET    /api/v1/paper/positions
GET    /api/v1/paper/positions/{position_id}
POST   /api/v1/paper/positions/{position_id}/modify
POST   /api/v1/paper/positions/{position_id}/exit

GET    /api/v1/paper/trades
GET    /api/v1/paper/trades/{trade_id}
```

## 17.5 Analytics APIs

``` http
GET /api/v1/analytics/portfolio
GET /api/v1/analytics/strategies
GET /api/v1/analytics/scanners
GET /api/v1/analytics/opportunities
GET /api/v1/analytics/drawdown
GET /api/v1/analytics/expectancy
GET /api/v1/analytics/trade-journal
```

## 17.6 WebSocket channels

``` text
/ws/v1/paper/dashboard/{account_id}
/ws/v1/paper/positions/{account_id}
/ws/v1/paper/orders/{account_id}
/ws/v1/risk/{account_id}
/ws/v1/opportunities
```

WebSocket messages should be event-driven. Do not broadcast full account
snapshots on every tick when only one position has changed.

# 18. Core Business Rules

1.  No opportunity can become a position without a valid strategy plan.
2.  Every strategy plan must contain an entry condition, stop-loss, exit
    condition and expiry.
3.  Every proposed trade must pass position-level risk checks.
4.  Every approved trade must pass portfolio-level risk checks.
5.  The risk engine can reject an opportunity even when the opportunity
    engine approves it.
6.  No duplicate positions should be created for the same consolidated
    opportunity unless explicitly permitted by a strategy rule.
7.  A signal's original score and timestamp must never be overwritten.
8.  Scanner scores must not be interpreted as success probabilities.
9.  All order fills must be recorded separately from order requests.
10. Partial fills must update position quantity and remaining order
    quantity correctly.
11. Risk-increasing position modifications must be revalidated.
12. Risk-reducing actions must remain available when new entries are
    blocked.
13. The kill switch must block new entries and risk-increasing orders.
14. The kill switch must not prevent permitted exits.
15. All account, strategy and risk configurations must be versioned.
16. Historical analytics must use point-in-time data.
17. F&O risk must use strategy-level maximum loss and portfolio Greeks,
    not margin alone.
18. Missing or stale critical market data must cause the relevant trade
    to be blocked or placed into a clearly defined restricted state.
19. A stop-loss trigger does not guarantee execution at the stop price.
20. All calculations must retain their inputs, outputs and calculation
    versions for audit.

# 19. User Experience and Screen Requirements

## 19.1 Main navigation

``` text
Trading
 ├── Overview
 ├── Scanner Opportunities
 ├── Paper Trading
 │    ├── Open Positions
 │    ├── Pending Orders
 │    ├── Closed Trades
 │    └── Trade Journal
 ├── Capital Allocation
 ├── Risk Management
 │    ├── Portfolio Risk
 │    ├── Sector Exposure
 │    ├── Correlation Risk
 │    ├── F&O Risk
 │    └── Stress Testing
 ├── Strategy Analytics
 ├── Scanner Analytics
 └── Configuration
```

## 19.2 Screen 1 --- Trading Overview

Display:

-   Account equity.
-   Available capital.
-   Capital deployed.
-   Open risk.
-   Daily P&L.
-   Active opportunities.
-   Open positions.
-   Pending orders.
-   Portfolio drawdown.
-   Risk warnings.

## 19.3 Screen 2 --- Scanner Opportunities

Display a live opportunity table with:

-   Symbol.
-   Scanner sources.
-   Direction.
-   Opportunity score.
-   Current price.
-   Entry trigger.
-   Stop-loss.
-   Targets.
-   R:R.
-   Suggested quantity.
-   Required capital.
-   Planned risk.
-   Validation result.
-   Risk decision.

Allow the user to inspect supporting signals and validation evidence
before approval.

## 19.4 Screen 3 --- Capital Allocation

Display:

-   Account capital.
-   Available risk budget.
-   Capital allocation by strategy.
-   Capital allocation by asset class.
-   Risk allocation by strategy.
-   Sector exposure.
-   Unallocated reserve.
-   Recommended allocation changes.

The screen must clearly distinguish capital allocation from risk
allocation.

## 19.5 Screen 4 --- Portfolio Risk

Display:

-   Total open planned risk.
-   Stressed portfolio risk.
-   Daily and weekly loss utilization.
-   Drawdown.
-   Sector concentration.
-   Correlation matrix.
-   F&O Greeks.
-   Margin utilization.
-   Stressed portfolio loss.

## 19.6 Screen 5 --- Real-Time Paper P&L

Display:

-   Open positions.
-   Live simulated P&L.
-   Position charts.
-   Entry, stop-loss and target levels.
-   Position event markers.
-   Portfolio consolidated P&L chart.
-   Realized versus unrealized P&L.
-   Strategy-wise P&L.

## 19.7 Screen 6 --- Strategy Analytics

Display:

-   Win rate.
-   Expectancy.
-   Profit factor.
-   Drawdown.
-   Sharpe and Sortino.
-   Average holding period.
-   Scanner attribution.
-   Opportunity-to-trade conversion.
-   Performance by market regime.

# 20. Alerts and Notifications

  Alert                   Trigger
  ----------------------- ----------------------------------------------------
  New opportunity         Qualified opportunity created
  Trade approved          Risk engine approves
  Trade rejected          Risk validation fails
  Order filled            Simulated execution occurs
  Partial fill            Only part of the order executes
  Stop-loss approaching   Configured proximity threshold reached
  Target reached          Target condition met
  Risk limit warning      Account approaches a limit
  Daily loss breach       Daily loss limit reached
  Drawdown warning        Configured drawdown reached
  Data stale              Critical market data becomes stale
  Kill switch activated   Trading halt activated
  F&O risk change         Greeks or maximum loss cross configured thresholds

Alerts should support in-app notifications initially. Other notification
channels can be added later.

# 21. Security, Governance and Audit

## 21.1 Access control

-   Role-based access control.
-   Account-level tenant isolation.
-   User-specific paper accounts.
-   Administrator permissions.
-   Separate strategy configuration permissions.
-   Separate risk-policy permissions.

## 21.2 Auditability

Record:

-   Who created a trade proposal.
-   Which scanner signals contributed.
-   Which strategy version was used.
-   Which risk policy was applied.
-   Why a trade was approved or rejected.
-   Which prices and market data were used.
-   What order was created.
-   What fills occurred.
-   Every stop-loss and target modification.
-   Who activated or deactivated a kill switch.

## 21.3 AI governance

AI may:

-   Summarize opportunities.
-   Explain validation results.
-   Explain risk decisions.
-   Identify anomalies.
-   Recommend research questions.
-   Compare strategy performance.

AI must not bypass deterministic risk controls.

AI-generated trade proposals must be clearly identified as proposals,
with source evidence and timestamped inputs.

The risk engine must be deterministic, versioned and independently
testable.

# 22. Non-Functional Requirements

  -----------------------------------------------------------------------
  Category                            Requirement
  ----------------------------------- -----------------------------------
  Reliability                         Event processing must be idempotent

  Data integrity                      Orders, fills and ledger updates
                                      must be transactionally consistent

  Scalability                         Support thousands of scanner events
                                      per trading session

  Latency                             Configurable event-to-decision
                                      latency measurement

  Availability                        Graceful handling of data-provider
                                      outages

  Observability                       Structured logs, metrics and traces

  Security                            Authentication, authorization and
                                      tenant isolation

  Audit                               Immutable event and decision
                                      history

  Recovery                            Reprocess events safely after
                                      service restart

  Performance                         Avoid unnecessary recalculation on
                                      every tick

  Accuracy                            All risk and P&L calculations must
                                      be covered by automated tests
  -----------------------------------------------------------------------

Performance targets should be finalized after measuring the existing
market-data pipeline and expected event throughput. A proposed initial
target is to process normal scanner events and complete deterministic
qualification/risk checks within a few seconds, excluding external
data-provider delays.

# 23. Testing and Validation

## 23.1 Unit testing

Test:

-   Position sizing.
-   ATR stop calculation.
-   Risk/reward.
-   P&L.
-   Capital allocation.
-   Sector exposure.
-   Correlation.
-   Drawdown.
-   F&O payoff.
-   Greeks aggregation.
-   Margin validation.
-   Risk limit enforcement.

## 23.2 Integration testing

Test:

-   Scanner event ingestion.
-   Signal deduplication.
-   Opportunity creation.
-   Risk validation.
-   Paper order creation.
-   Simulated fills.
-   Position updates.
-   Ledger reconciliation.
-   WebSocket updates.

## 23.3 Scenario testing

Mandatory scenarios:

1.  Multiple scanners identify the same stock.
2.  An opportunity passes validation but breaches portfolio risk.
3.  An order receives a partial fill.
4.  A stock gaps below its stop-loss.
5.  A market data provider stops responding.
6.  Two correlated positions trigger simultaneously.
7.  A daily loss limit is breached.
8.  An F&O spread has one leg filled before the other.
9.  A target is reached while the stop is being modified.
10. A service restarts while positions are open.
11. A duplicate scanner event is delivered.
12. An expired signal is received late.
13. A position is manually exited.
14. A kill switch is activated while orders are pending.

## 23.4 Backtesting

Before allowing strategy-based risk allocation to increase:

-   Use point-in-time data.
-   Include realistic transaction costs.
-   Include slippage.
-   Include liquidity constraints.
-   Include expiry and corporate-action handling.
-   Avoid look-ahead and survivorship bias.
-   Use walk-forward testing.
-   Maintain out-of-sample evaluation.

## 23.5 Paper-trading certification

A strategy should only qualify for higher risk allocation after meeting
configurable evidence criteria, such as:

-   Minimum completed trades.
-   Positive net expectancy.
-   Acceptable profit factor.
-   Acceptable drawdown.
-   Out-of-sample validation.
-   Performance across more than one market regime.
-   Stable execution assumptions.
-   No critical risk-control failures.

The actual numerical thresholds should be defined per strategy and
validated rather than assumed universal.

# 24. Implementation Roadmap

## Phase 1 --- Foundation and Signal Integration

**Deliverables**

-   Paper account creation.
-   Scanner event ingestion.
-   Signal normalization.
-   Signal consolidation.
-   Opportunity records.
-   Signal history.
-   Initial opportunity dashboard.

**Exit criteria**

-   Scanner events are processed idempotently.
-   Original signal IDs and timestamps are retained.
-   Duplicate signals are consolidated correctly.
-   No paper orders are created at this stage.

## Phase 2 --- Opportunity and Risk Engine

**Deliverables**

-   Opportunity validation.
-   Entry, stop and target generation.
-   Position sizing.
-   Capital allocation.
-   Account risk policies.
-   Sector and correlation controls.
-   Risk decision explanations.

**Exit criteria**

-   All proposed trades receive a complete risk decision.
-   Invalid or oversized trades are blocked.
-   Risk decisions are reproducible from stored inputs.

## Phase 3 --- Paper Trading

**Deliverables**

-   Paper order manager.
-   Execution simulator.
-   Fill management.
-   Position lifecycle.
-   Stop-loss and target management.
-   Cash ledger.
-   Real-time P&L.

**Exit criteria**

-   Order, fill, position and ledger records reconcile.
-   Partial fills work correctly.
-   Restart and duplicate-event tests pass.
-   Simulated costs and slippage are recorded.

## Phase 4 --- F&O and Portfolio Risk

**Deliverables**

-   Options chain integration.
-   Greeks.
-   Multi-leg strategy support.
-   Maximum-loss calculation.
-   Scenario analysis.
-   Portfolio-level Greeks.
-   F&O risk dashboard.

**Exit criteria**

-   Strategy payoff and maximum-loss calculations match independent test
    cases.
-   Multi-leg lifecycle and partial-fill handling work correctly.
-   Portfolio-level F&O risk is available.

## Phase 5 --- Analytics and Research

**Deliverables**

-   Scanner performance analytics.
-   Opportunity outcome tracking.
-   Strategy expectancy.
-   Performance attribution.
-   Drawdown analytics.
-   Risk-adjusted performance.
-   Scanner combination research.

**Exit criteria**

-   Signal outcomes and actual trade outcomes are reported separately.
-   Performance results include costs.
-   Historical reports are reproducible.
-   Point-in-time data validation passes.

## Phase 6 --- Advanced Allocation and Governance

**Deliverables**

-   Risk parity research.
-   Constrained allocation optimization.
-   Regime-aware allocation.
-   Dynamic risk budgets.
-   Strategy allocation recommendations.
-   Advanced audit and governance.
-   Live execution readiness assessment.

**Exit criteria**

-   Optimization recommendations cannot override hard risk controls.
-   Allocation changes are versioned and auditable.
-   Strategy certification requirements are enforced.

# 25. MVP Acceptance Criteria

The first production-quality paper trading release is acceptable when:

1.  The system consumes all enabled scanner events.
2.  Duplicate signals are consolidated.
3.  Each opportunity has a complete strategy plan.
4.  Every proposed position has calculated quantity and planned risk.
5.  Capital allocation respects account limits.
6.  Portfolio risk is calculated before order creation.
7.  Risk decisions contain clear reason codes.
8.  Paper orders support the configured order types.
9.  Simulated fills account for executable prices and costs.
10. Positions update correctly after partial fills.
11. P&L is calculated from the fill ledger.
12. Stop-loss and targets are monitored.
13. Risk-increasing modifications are revalidated.
14. The kill switch blocks new entries.
15. Risk-reducing exits remain possible.
16. All position and risk events are auditable.
17. Scanner performance and trade performance are reported separately.
18. Historical calculations are point-in-time reproducible.
19. The system survives service restart without duplicate positions or
    ledger corruption.
20. The UI clearly distinguishes available capital, deployed capital,
    planned risk and stressed risk.

# 26. Recommended Initial Configuration

The following is an example paper-trading configuration for testing. It
is not a recommended live-investment allocation.

  Parameter                                                 Initial test value
  --------------------------------- ------------------------------------------
  Virtual capital                                                   ₹10,00,000
  Maximum positional risk                                                0.50%
  Maximum intraday risk                                                  0.35%
  Maximum F&O strategy risk                                              0.35%
  Maximum total planned open risk                                        3.00%
  Maximum daily loss                                                     1.50%
  Maximum weekly loss                                                    3.00%
  Maximum drawdown before halt                                           6.00%
  Maximum concurrent positions                                              10
  Minimum R:R for standard setups                                          1:2
  Unallocated reserve                                                      10%
  Default position sizing                                           Risk-based
  Default stop method                 Strategy-specific ATR or structure-based
  Execution mode                                                         Paper
  Approval mode                                        User approval initially

All values should be editable through a versioned risk configuration
interface.

# 27. Key Product Decisions

### Decision 1 --- Separate signal scoring from probability

The existing scanner score measures signal strength. It must not be used
as a direct estimate of trade success probability.

### Decision 2 --- Consolidate before allocating capital

One instrument appearing in multiple scanners should normally produce
one consolidated opportunity, not multiple independent positions.

### Decision 3 --- Risk engine has final authority

The Opportunity Engine and Capital Allocation Engine may propose trades
and allocations. The Risk Engine has the final veto.

### Decision 4 --- Maintain separate signal and trade outcomes

A scanner may identify a correct market direction while the simulated
trade loses because of entry timing or execution. Both outcomes must be
measured independently.

### Decision 5 --- Simulate execution realistically

The system must model bid/ask, liquidity, slippage, partial fills and
costs. Filling every order at LTP would produce misleading results.

### Decision 6 --- Keep capital and risk separate

Capital deployed, capital reserved, margin used and planned loss are
different measures. They must not be combined into one metric.

### Decision 7 --- Optimize only after sufficient evidence

Dynamic allocation and risk scaling should depend on validated strategy
expectancy, drawdown and out-of-sample results---not a few recent
profitable trades.

### Decision 8 --- Preserve full decision history

Every opportunity, approval, rejection, allocation, order, fill and risk
modification must be explainable and reproducible.

# 28. Final Product Outcome

The completed Nivesh module should function as a disciplined trading
intelligence and portfolio management system.

It will transform the existing scanner infrastructure into a structured
workflow:

1.  Discover market opportunities.
2.  Consolidate related signals.
3.  Validate the underlying setup.
4.  Generate a trade strategy.
5.  Calculate appropriate position size.
6.  Allocate available capital.
7.  Enforce portfolio-level risk.
8.  Simulate realistic execution.
9.  Monitor positions continuously.
10. Measure actual performance.
11. Learn which scanner combinations and strategies demonstrate
    repeatable evidence of an edge.

The long-term objective is to establish a reliable, auditable
paper-trading framework that can serve as the foundation for any future
broker-connected execution capability.

**The guiding principle: Nivesh should optimize for risk-adjusted,
evidence-backed trading decisions---not the maximum number of trades or
the maximum capital deployed.**
