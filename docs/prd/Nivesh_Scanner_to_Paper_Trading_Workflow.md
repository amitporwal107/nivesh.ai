# Nivesh AI --- Scanner-to-Paper Trading Workflow

**Workflow Specification**

  -----------------------------------------------------------------------
  Attribute                           Details
  ----------------------------------- -----------------------------------
  Product                             Nivesh AI / Nivesh Copilot

  Module                              Trading Intelligence & Paper
                                      Trading

  Version                             1.0

  Related document                    Scanner-to-Paper Trading, Capital
                                      Allocation & Risk Management PRD

  Initial mode                        Paper trading

  Market                              Indian equities and derivatives
  -----------------------------------------------------------------------

------------------------------------------------------------------------

# 1. Purpose

This document defines the end-to-end operational workflow through which
Nivesh converts scanner signals into validated opportunities, approved
paper orders, managed positions and measurable trading outcomes.

The workflow must be deterministic, auditable and risk-controlled.

The system must distinguish the following entities:

1.  **Scanner signal:** An observation produced by a scanner.
2.  **Consolidated opportunity:** A group of related signals
    representing one potential setup.
3.  **Trade proposal:** A strategy plan with entry, stop-loss, targets
    and expiry.
4.  **Risk decision:** The independent decision to approve, reduce,
    conditionally approve or reject the proposal.
5.  **Paper order:** A simulated instruction to enter or exit a
    position.
6.  **Position:** The quantity actually filled in the paper account.
7.  **Trade outcome:** The final realized result and its performance
    attribution.

A scanner event must never directly create a position without passing
through the required workflow.

# 2. End-to-End Workflow Overview

``` mermaid
flowchart TD
    A[Market Data Ingestion] --> B[Scanner Execution]
    B --> C[Scanner Signal Event]
    C --> D[Normalize and Validate Signal]
    D --> E{Valid and Fresh?}
    E -- No --> X[Reject or Expire Signal]
    E -- Yes --> F[Deduplicate and Consolidate]
    F --> G[Create or Update Opportunity]
    G --> H[Opportunity Validation]
    H --> I{Setup Qualified?}
    I -- No --> W[Watchlist or Reject]
    I -- Yes --> J[Generate Trade Proposal]
    J --> K[Calculate Entry, Stop and Targets]
    K --> L[Position Sizing]
    L --> M[Capital Allocation]
    M --> N[Portfolio Risk Validation]
    N --> O{Risk Approved?}
    O -- No --> R[Reject, Reduce or Block]
    O -- Yes --> P{Approval Mode}
    P -- User Approval --> Q[Await User Decision]
    P -- Automatic Paper --> S[Create Paper Order]
    Q --> T{User Approves?}
    T -- No --> U[Rejected or Expired]
    T -- Yes --> S
    S --> V[Execution Simulation]
    V --> Y{Any Fill?}
    Y -- No --> Z[Pending, Cancelled or Expired]
    Y -- Yes --> AA[Create or Update Position]
    AA --> AB[Continuous Position Monitoring]
    AB --> AC{Exit Condition?}
    AC -- No --> AB
    AC -- Yes --> AD[Simulate Exit]
    AD --> AE[Close Position and Reconcile Ledger]
    AE --> AF[Trade Analytics]
    AF --> AG[Scanner and Strategy Attribution]
```

# 3. Workflow Actors and Responsibilities

  -----------------------------------------------------------------------
  Actor/service                       Responsibility
  ----------------------------------- -----------------------------------
  Market Data Engine                  Supplies prices, OHLCV, quotes,
                                      indices and derivatives data

  Scanner Engine                      Detects configured technical,
                                      fundamental and derivatives
                                      conditions

  Signal Consumer                     Receives scanner events and ensures
                                      idempotent processing

  Signal Normalizer                   Validates and standardizes event
                                      payloads

  Signal Consolidator                 Groups related signals for the same
                                      instrument and setup

  Opportunity Engine                  Creates and updates trade
                                      opportunities

  Opportunity Validator               Evaluates market, technical,
                                      liquidity and derivatives
                                      confirmation

  Strategy Engine                     Defines entry, stop-loss, target
                                      and expiry rules

  Position Sizing Engine              Calculates quantity based on
                                      permitted risk

  Capital Allocation Engine           Determines available capital and
                                      allocation

  Risk Engine                         Approves, reduces, blocks or
                                      rejects the proposed trade

  Paper Order Manager                 Creates and manages simulated
                                      orders

  Execution Simulator                 Simulates fills, slippage, spread
                                      and costs

  Position Manager                    Maintains open positions and
                                      lifecycle

  Portfolio Monitor                   Calculates aggregate exposure and
                                      account risk

  Notification Engine                 Sends alerts and user notifications

  Analytics Engine                    Measures signal and trade outcomes

  User                                Reviews, approves, rejects or
                                      modifies permitted proposals

  Administrator                       Configures account policies and
                                      operational controls
  -----------------------------------------------------------------------

# 4. Workflow 1 --- Market Data and Scanner Signal Generation

## 4.1 Trigger

A market data update arrives or a scanner's configured evaluation
schedule is reached.

## 4.2 Processing steps

1.  Receive market data from the configured source.
2.  Validate instrument mapping and exchange.
3.  Validate timestamp and data freshness.
4.  Update the relevant market data store.
5.  Execute eligible scanners.
6.  Evaluate scanner-specific conditions.
7.  Generate a scanner event when conditions are satisfied.
8.  Persist the original event.
9.  Publish the event to the signal event stream.

## 4.3 Example

A stock crosses its 52-week high with relative volume greater than its
configured threshold.

The breakout scanner emits:

-   Instrument: ABC Ltd.
-   Direction: Bullish.
-   Signal type: 52-week breakout.
-   Detection price: ₹500.
-   Scanner score: 78.
-   Timeframe: Daily.
-   Detection timestamp: Exchange event time.

The event is stored as an immutable scanner observation.

## 4.4 Validation checks

Reject or quarantine the event when:

-   Instrument mapping is missing.
-   Symbol or exchange is invalid.
-   Required price data is missing.
-   Timestamp is invalid.
-   The event is a duplicate.
-   The event is outside the configured trading session, where session
    restrictions apply.
-   Critical input data is stale.

## 4.5 Output

`SCANNER_SIGNAL_RECEIVED`

The original scanner event must be preserved even if subsequent
processing rejects it.

# 5. Workflow 2 --- Signal Normalization and Consolidation

## 5.1 Objective

Identify when multiple scanner signals describe the same underlying
opportunity.

## 5.2 Processing steps

1.  Read the scanner event.
2.  Normalize symbol, exchange, instrument and direction.
3.  Map scanner type to a standard signal category.
4.  Identify the strategy family and timeframe.
5.  Search for an existing compatible opportunity.
6.  Evaluate the consolidation window.
7.  Attach the signal to the existing opportunity or create a new
    opportunity.
8.  Preserve the original signal ID, scanner ID, timestamp and score.
9.  Recalculate supporting confirmation metrics.

## 5.3 Consolidation example

  Scanner                Signal                       Score
  ---------------------- -------------------------- -------
  Multiyear breakout     Price breakout                  82
  High-volume breakout   Volume confirmation             78
  Delivery + volume      Delivery confirmation           75
  Fresh long buildup     Derivatives confirmation        73

Output:

-   One consolidated bullish opportunity.
-   Four linked source signals.
-   Four independent scanner observations.
-   One opportunity ID.

Do not add the four scanner scores together.

## 5.4 Consolidation rules

A signal can be attached to an existing opportunity when:

-   Instrument and exchange match.
-   Direction is compatible.
-   Strategy family is compatible.
-   Signal timestamps fall within the configured consolidation window.
-   The existing opportunity has not expired or been invalidated.

Opposing signals must be retained as conflicting evidence, not silently
discarded.

## 5.5 Output states

-   `SIGNAL_NORMALIZED`
-   `SIGNAL_ATTACHED_TO_OPPORTUNITY`
-   `OPPORTUNITY_CREATED`
-   `SIGNAL_CONFLICT_DETECTED`
-   `SIGNAL_REJECTED`
-   `SIGNAL_EXPIRED`

# 6. Workflow 3 --- Opportunity Validation

## 6.1 Objective

Determine whether the consolidated signals form a sufficiently complete
and valid trading setup.

## 6.2 Validation sequence

### Step 1 --- Market regime validation

Evaluate:

-   Nifty direction.
-   Bank Nifty direction.
-   Market breadth.
-   Sector trend.
-   India VIX.
-   Volatility regime.
-   Market trend classification.

### Step 2 --- Instrument trend validation

Evaluate:

-   Price relative to EMA20, EMA50 and EMA200.
-   RSI and ADX.
-   MACD or configured momentum indicators.
-   Relative strength.
-   ATR%.
-   Swing structure.
-   Support and resistance.
-   Recent gap and price behavior.

### Step 3 --- Volume and participation validation

Evaluate:

-   Relative volume.
-   Delivery quantity and percentage.
-   Volume expansion.
-   Liquidity.
-   Bid-ask spread.
-   Unusual volume conditions.

### Step 4 --- Derivatives validation

For eligible F&O instruments, evaluate:

-   Futures price and OI changes.
-   Long buildup, short buildup, short covering or long unwinding
    classification.
-   Put-call ratio.
-   ATM IV and IV percentile.
-   Option chain liquidity.
-   Greeks.
-   Expected move.
-   Expiry proximity.

### Step 5 --- Opportunity quality assessment

Calculate an explainable opportunity score using configured and
versioned criteria.

The opportunity score is not a probability of profit.

## 6.3 Validation decisions

  -----------------------------------------------------------------------
  Decision                            Next action
  ----------------------------------- -----------------------------------
  QUALIFIED                           Generate trade proposal

  CONDITIONAL                         Wait for trigger or confirmation

  WATCHLIST                           Continue monitoring without order

  REJECTED                            Close opportunity with reason

  EXPIRED                             Mark opportunity expired

  DATA_INSUFFICIENT                   Wait for valid data or reject
                                      according to policy
  -----------------------------------------------------------------------

## 6.4 Example

A breakout is detected, but:

-   Relative volume is weak.
-   The sector index is declining.
-   Price is close to a major resistance zone.

The system may classify the setup as `CONDITIONAL` or `WATCHLIST`,
rather than creating an immediate trade.

## 6.5 Required validation record

Store:

-   Opportunity ID.
-   Validation timestamp.
-   Market data snapshot reference.
-   Technical metrics.
-   Liquidity metrics.
-   Derivatives metrics.
-   Opportunity score and version.
-   Decision.
-   Reason codes.
-   Expiry or revalidation time.

# 7. Workflow 4 --- Trade Proposal Generation

## 7.1 Trigger

An opportunity becomes `QUALIFIED` or reaches a configured conditional
entry trigger.

## 7.2 Processing steps

1.  Identify the applicable strategy template.
2.  Determine trade direction.
3.  Determine timeframe and expected holding period.
4.  Generate entry condition.
5.  Calculate stop-loss.
6.  Calculate target 1 and target 2.
7.  Define trailing and time-based exit rules.
8.  Define opportunity expiry.
9.  Calculate reward/risk.
10. Store the proposed strategy plan.

## 7.3 Entry types

-   Immediate marketable entry.
-   Breakout confirmation entry.
-   Pullback entry.
-   Retest entry.
-   Limit entry.
-   Conditional stop entry.

## 7.4 Exit rules

Every proposal must define at least one price-based invalidation and an
exit policy.

Possible exit conditions:

-   Initial stop-loss.
-   Target 1.
-   Target 2.
-   Trailing stop.
-   Daily close below a technical level.
-   Time-based exit.
-   Fundamental or event invalidation.
-   Strategy-specific exit.

## 7.5 Proposal example

*Illustrative values.*

  Attribute                                           Proposed value
  ------------------------ -----------------------------------------
  Instrument                                                 ABC Ltd
  Direction                                                     Long
  Entry trigger                                                 ₹505
  Stop-loss                                                     ₹485
  Target 1                                                      ₹545
  Target 2                                                      ₹585
  Initial risk per share                                         ₹20
  Reward/risk to T1                                              2:1
  Reward/risk to T2                                              4:1
  Validity                   Until configured expiry or invalidation

Output: `TRADE_PROPOSAL_CREATED`

# 8. Workflow 5 --- Position Sizing

## 8.1 Objective

Calculate the maximum quantity that can be taken without exceeding the
trade's allowed risk.

## 8.2 Processing steps

1.  Retrieve account equity.
2.  Retrieve strategy-specific risk percentage.
3.  Calculate permitted risk amount.
4.  Calculate entry-to-stop distance.
5.  Estimate transaction costs.
6.  Calculate preliminary quantity.
7.  Apply lot-size rounding for F&O.
8.  Apply liquidity constraints.
9.  Apply maximum instrument exposure.
10. Apply available capital constraints.
11. Return final quantity and risk metrics.

## 8.3 Equity position sizing

\[ AllowedRisk = AccountEquity `\times `{=tex}RiskPercentage \]

\[ RiskPerShare = \|Entry - StopLoss\| + EstimatedCostPerShare \]

\[ Quantity =
`\left`{=tex}`\lfloor `{=tex}`\frac{AllowedRisk}{RiskPerShare}`{=tex}
`\right`{=tex}`\rfloor`{=tex} \]

Then:

\[ CapitalRequired = Quantity `\times `{=tex}Entry \]

The final quantity must be reduced if capital, liquidity or portfolio
exposure limits are exceeded.

## 8.4 Example

-   Account equity: ₹10,00,000.
-   Allowed risk: 0.5%.
-   Entry: ₹500.
-   Stop-loss: ₹480.
-   Estimated cost per share: ₹0.50.

Allowed risk = ₹5,000.

Quantity = floor(5,000 / 20.50) = 243 shares.

Estimated capital = ₹1,21,500.

## 8.5 Output

`POSITION_SIZE_CALCULATED`

Store the calculation inputs, result and formula version.

# 9. Workflow 6 --- Capital Allocation

## 9.1 Objective

Determine whether sufficient capital and risk budget are available for
the proposed position.

## 9.2 Processing steps

1.  Retrieve account equity and cash.
2.  Calculate deployed capital.
3.  Calculate capital reserved by pending orders.
4.  Calculate available capital.
5.  Calculate current planned open risk.
6.  Calculate stressed open risk.
7.  Calculate strategy allocation utilization.
8.  Calculate sector and instrument exposure.
9.  Calculate correlation concentration.
10. Determine permitted allocation.
11. Return approval, reduced allocation or rejection recommendation.

## 9.3 Allocation constraints

-   Account capital limit.
-   Available cash.
-   Reserved pending-order capital.
-   Maximum strategy allocation.
-   Maximum instrument exposure.
-   Maximum sector exposure.
-   Maximum portfolio open risk.
-   Maximum position count.
-   Liquidity constraints.
-   F&O margin availability.
-   F&O maximum strategy loss.

## 9.4 Example

An opportunity requires ₹1,21,500 capital and ₹4,981.50 planned risk.

However, the account has only ₹80,000 available capital.

The allocation engine must:

-   Reduce quantity if a valid smaller position remains possible; or
-   Reject the proposal if minimum quantity or liquidity constraints
    make the trade unsuitable.

It must not silently exceed available capital.

Output: `ALLOCATION_APPROVED`, `ALLOCATION_REDUCED` or
`ALLOCATION_REJECTED`.

# 10. Workflow 7 --- Portfolio Risk Validation

## 10.1 Objective

Perform the final risk check before any paper order is created.

## 10.2 Risk validation sequence

1.  Validate position-level planned risk.
2.  Validate stressed position loss.
3.  Validate total open planned risk.
4.  Validate stressed portfolio loss.
5.  Validate daily and weekly loss limits.
6.  Validate account drawdown.
7.  Validate stock and sector concentration.
8.  Validate correlation exposure.
9.  Validate strategy allocation.
10. Validate F&O Greeks and maximum loss, where applicable.
11. Validate data freshness.
12. Produce the final decision.

## 10.3 Decision matrix

  Condition                          Decision
  ---------------------------------- ----------------------------
  All checks pass                    APPROVE
  Position too large but reducible   APPROVE_REDUCED
  Entry condition not yet met        CONDITIONAL_APPROVAL
  Hard exposure limit breached       REJECT
  Daily loss limit breached          BLOCK
  Drawdown halt reached              HALT_ACCOUNT
  Critical data unavailable          BLOCK or DATA_INSUFFICIENT
  F&O maximum loss exceeds policy    REJECT

## 10.4 Risk decision record

Store:

-   Risk decision ID.
-   Account ID.
-   Opportunity ID.
-   Proposed quantity.
-   Approved quantity.
-   Planned risk.
-   Stressed risk.
-   Portfolio risk before trade.
-   Portfolio risk after trade.
-   Exposure before and after.
-   Policy version.
-   Reason codes.
-   Calculation timestamp.

The Risk Engine has final authority. No user approval or AI
recommendation may bypass a hard risk limit.

# 11. Workflow 8 --- User Approval or Automatic Paper Trading

## 11.1 Operating modes

### Mode A --- Approval-based paper trading

1.  Risk engine approves the proposal.
2.  UI displays the trade proposal.
3.  User reviews supporting signals and risk.
4.  User approves or rejects.
5.  Approval creates a paper order.
6.  Rejection records the reason and closes the proposal.

### Mode B --- Automatic paper trading

1.  Risk engine approves the proposal.
2.  Account configuration permits automatic paper trading.
3.  Paper order manager creates the order.
4.  Execution simulator processes the order.

### Mode C --- Signal tracking

1.  Opportunity is qualified.
2.  No order is created.
3.  The system records hypothetical entry and subsequent market
    outcomes.
4.  Signal performance analytics measure the result.

## 11.2 Approval expiry

An approval request must expire when:

-   Entry trigger is no longer valid.
-   Price moves outside permitted entry range.
-   Opportunity expires.
-   Risk policy changes materially.
-   Market data becomes stale.
-   Account enters restricted or halted state.

The user must not be able to approve an expired proposal without fresh
validation.

# 12. Workflow 9 --- Paper Order Creation and Execution

## 12.1 Order creation

The Paper Order Manager receives an approved proposal and creates an
order containing:

-   Account ID.
-   Opportunity ID.
-   Strategy ID.
-   Instrument.
-   Side.
-   Order type.
-   Quantity.
-   Limit or trigger price.
-   Time-in-force.
-   Risk decision reference.
-   Idempotency key.

## 12.2 Execution simulation

1.  Validate market session.
2.  Retrieve the relevant quote or bar.
3.  Check executable bid/ask.
4.  Check available liquidity.
5.  Apply configured slippage model.
6.  Apply partial-fill rules.
7.  Apply transaction costs.
8.  Record fills.
9.  Update remaining order quantity.
10. Update account ledger.
11. Create or update the position.

## 12.3 Execution rules

-   Do not fill all orders at LTP by default.
-   Buy marketable orders should reference ask-side execution.
-   Sell marketable orders should reference bid-side execution.
-   Limit orders must not fill unless the configured price and liquidity
    conditions are met.
-   Partial fills must be supported.
-   Unfilled orders must remain pending, expire or be cancelled
    according to their time-in-force.
-   A duplicate order request must not create duplicate orders.

## 12.4 Order states

``` text
CREATED
  |
VALIDATED
  |
PENDING
  |------> PARTIALLY_FILLED
  |             |
  |             +----> FILLED
  |
  +------> FILLED
  |
  +------> CANCELLED
  |
  +------> EXPIRED
  |
  +------> REJECTED
```

## 12.5 Position creation

A position is created only when at least one fill is recorded.

The position quantity must equal the sum of open fills less exits.

Output: `POSITION_OPENED` or `POSITION_INCREASED`.

# 13. Workflow 10 --- Open Position Monitoring

## 13.1 Monitoring triggers

Monitor positions when:

-   A new market quote arrives.
-   A new bar closes.
-   A stop or target condition is evaluated.
-   A relevant market or sector index changes.
-   An options-chain or Greeks update arrives.
-   A corporate action or material event is detected.
-   A user requests a position modification.

## 13.2 Monitoring calculations

For every position calculate:

-   Current executable value.
-   Unrealized P&L.
-   Realized P&L.
-   Current stop distance.
-   Target distance.
-   Initial risk.
-   Remaining planned risk.
-   Current R multiple.
-   Holding duration.
-   Liquidity.
-   Market and sector context.
-   Stressed loss.

For options positions additionally calculate:

-   Net Delta.
-   Net Gamma.
-   Net Theta.
-   Net Vega.
-   Strategy maximum loss.
-   Margin utilization.
-   Scenario P&L.

## 13.3 Position alerts

-   Stop-loss approaching.
-   Stop-loss triggered.
-   Target 1 reached.
-   Target 2 reached.
-   Trailing stop updated.
-   Risk limit warning.
-   Data stale.
-   Liquidity deteriorating.
-   F&O Greek exposure changed.
-   Expiry approaching.

## 13.4 Stop and target handling

When a stop or target condition is triggered:

1.  Confirm the trigger using the configured price source and trigger
    semantics.
2.  Create an exit order.
3.  Simulate execution using executable prices and liquidity.
4.  Record fills.
5.  Update remaining position quantity.
6.  Recalculate account equity and risk.
7.  Notify the user.
8.  Preserve the original stop and target plan for analysis.

A stop trigger must not be treated as a guaranteed fill at the stop
price.

# 14. Workflow 11 --- Position Modification

## 14.1 Supported modifications

-   Increase quantity.
-   Reduce quantity.
-   Change stop-loss.
-   Change target.
-   Enable trailing stop.
-   Disable trailing stop.
-   Change exit rule.
-   Close position.

## 14.2 Modification workflow

1.  Receive modification request.
2.  Identify whether it increases or reduces risk.
3.  Validate the new parameters.
4.  Recalculate position and portfolio risk.
5.  Re-run risk controls for risk-increasing changes.
6.  Approve or reject the modification.
7.  Apply the change.
8.  Record old and new values.
9.  Notify the user.

Risk-reducing actions should remain available during a trading halt,
subject to operational and market constraints.

## 14.3 Audit record

Every modification must capture:

-   Position ID.
-   Previous value.
-   New value.
-   Requesting user or service.
-   Timestamp.
-   Reason.
-   Risk decision.
-   Market data reference.

# 15. Workflow 12 --- F&O Multi-Leg Paper Trading

## 15.1 Proposal creation

1.  Identify the underlying.
2.  Select strategy template.
3.  Select expiry.
4.  Select strikes and option types.
5.  Retrieve quotes and Greeks.
6.  Calculate net debit or credit.
7.  Calculate maximum profit and maximum loss.
8.  Calculate breakeven.
9.  Calculate margin.
10. Calculate net Greeks.
11. Run scenario analysis.
12. Submit to portfolio risk validation.

## 15.2 Leg execution

For each leg:

-   Create an individual order.
-   Track its fill state.
-   Update net strategy quantity.
-   Recalculate residual exposure.
-   Detect unhedged or partially hedged states.
-   Apply configured legging-risk controls.

If one leg fills and another does not:

1.  Mark the strategy `PARTIALLY_FILLED`.
2.  Recalculate current worst-case exposure.
3.  Block additional risk-increasing activity where necessary.
4.  Apply the configured hedge, retry or unwind policy.
5.  Alert the user.
6.  Preserve all leg-level events.

## 15.3 F&O monitoring

Monitor:

-   Underlying price.
-   Option bid/ask.
-   OI and OI change.
-   IV. 
-   Greeks.
-   Net strategy P&L.
-   Maximum loss.
-   Margin.
-   Expiry.
-   Scenario loss.

The risk engine must use strategy-level maximum loss for defined-risk
strategies, not margin as a substitute for risk.

# 16. Workflow 13 --- Exit and Trade Closure

## 16.1 Exit triggers

A position may close because of:

-   Stop-loss.
-   Target.
-   Trailing stop.
-   Time-based exit.
-   Technical invalidation.
-   Strategy invalidation.
-   User-requested exit.
-   Account-level risk action.
-   Expiry or contract lifecycle event.

## 16.2 Closure steps

1.  Create exit order.
2.  Simulate exit execution.
3.  Record all exit fills.
4.  Calculate remaining quantity.
5.  Mark position closed when quantity reaches zero.
6.  Calculate realized P&L.
7.  Apply transaction costs.
8.  Update cash ledger.
9.  Update account equity.
10. Release reserved capital and risk.
11. Store exit reason.
12. Create completed trade record.
13. Trigger performance analytics.

## 16.3 Net realized P&L

For a long equity position:

\[ NetRealizedPnL = ExitProceeds - EntryCost - TransactionCosts \]

For multiple fills, use the account's configured cost-basis method
consistently and document it.

For F&O, calculate realized P&L across all legs and fills, including
costs.

# 17. Workflow 14 --- Signal and Trade Outcome Analytics

Signal performance and trade performance must be measured separately.

## 17.1 Signal outcome tracking

For each original signal, preserve:

-   Detection timestamp.
-   Detection price.
-   Scanner score.
-   Scanner version.
-   Opportunity association.
-   Forward returns.
-   MFE.
-   MAE.
-   T+1, T+5, T+10 and T+20 outcomes.
-   Target and stop observations under a defined hypothetical rule.

This measures whether the scanner identified a useful market event.

## 17.2 Trade outcome tracking

For each completed trade, preserve:

-   Actual simulated entry fills.
-   Actual simulated exit fills.
-   Quantity.
-   Costs.
-   Slippage.
-   Planned risk.
-   Realized P&L.
-   R multiple.
-   Holding duration.
-   MFE and MAE.
-   Exit reason.
-   Strategy version.
-   Risk policy version.

This measures whether the trade implementation made money.

## 17.3 Analytics workflow

1.  Close the trade.
2.  Reconcile all fills and ledger entries.
3.  Calculate net P&L.
4.  Calculate R multiple.
5.  Calculate MFE and MAE.
6.  Attribute the trade to its source signals.
7.  Update scanner statistics.
8.  Update opportunity statistics.
9.  Update strategy statistics.
10. Update market-regime statistics.
11. Refresh reports and dashboards.

Do not update a scanner's performance based only on whether a
corresponding paper trade won or lost.

# 18. Workflow 15 --- Dynamic Capital and Risk Allocation

## 18.1 Recalculation triggers

Recalculate allocation when:

-   A new opportunity is qualified.
-   A position is opened or closed.
-   A pending order reserves or releases capital.
-   Account equity changes materially.
-   A risk limit changes.
-   Sector or correlation exposure changes.
-   A strategy is restricted or certified.
-   A market regime changes.

## 18.2 Allocation sequence

1.  Read current account equity.
2.  Read available cash.
3.  Read deployed and reserved capital.
4.  Calculate available risk budget.
5.  Rank eligible opportunities.
6.  Calculate each opportunity's proposed quantity and risk.
7.  Estimate portfolio impact.
8.  Apply sector and correlation constraints.
9.  Apply strategy allocation limits.
10. Generate allocation recommendation.
11. Submit the recommendation to the Risk Engine.
12. Store the allocation decision.

## 18.3 Performance-based scaling

Risk may be increased only after a strategy meets configured evidence
requirements.

Evaluate:

-   Minimum sample size.
-   Net expectancy.
-   Profit factor.
-   Drawdown.
-   Out-of-sample results.
-   Walk-forward stability.
-   Market-regime coverage.
-   Execution-cost sensitivity.

A recent winning streak alone must not increase risk.

# 19. Workflow 16 --- Daily Risk Controls and Kill Switch

## 19.1 Continuous checks

Monitor:

-   Daily net P&L.
-   Weekly net P&L.
-   Peak-to-current drawdown.
-   Total planned open risk.
-   Stressed portfolio risk.
-   Sector concentration.
-   Correlation exposure.
-   Margin utilization.
-   Data-provider health.
-   Execution simulator health.

## 19.2 Risk breach workflow

``` mermaid
flowchart TD
    A[Risk Monitor Event] --> B[Recalculate Account Risk]
    B --> C{Limit Breached?}
    C -- No --> D[Continue Monitoring]
    C -- Yes --> E[Classify Breach]
    E --> F[Block New Entries]
    F --> G[Block Risk-Increasing Changes]
    G --> H[Notify User and Record Event]
    H --> I{Emergency Exit Required?}
    I -- No --> J[Restricted Account State]
    I -- Yes --> K[Create Risk-Reducing Exit Instructions]
    K --> L[Execute Permitted Paper Exits]
    L --> J
```

## 19.3 Kill switch behavior

When activated:

-   Block new paper entries.
-   Block risk-increasing modifications.
-   Cancel eligible pending entry orders.
-   Continue permitted risk-reducing exits.
-   Continue market data and position monitoring.
-   Record the activation reason.
-   Notify authorized users.

The kill switch must have clear states:

-   `ACTIVE`
-   `TRIGGERED`
-   `RESTRICTED`
-   `RESET_PENDING`
-   `DISABLED`

Reset must require the configured authorization process.

# 20. Workflow 17 --- Data Failure and Recovery

## 20.1 Failure conditions

-   Market data feed unavailable.
-   Stale quotes.
-   Missing options chain.
-   Invalid instrument mapping.
-   Scanner event bus unavailable.
-   Database unavailable.
-   Paper execution service unavailable.
-   WebSocket disconnection.
-   Duplicate or out-of-order events.

## 20.2 Failure handling

  -----------------------------------------------------------------------
  Failure                             Required behavior
  ----------------------------------- -----------------------------------
  Stale critical quote                Block new entry or use explicitly
                                      approved fallback

  Missing options chain               Block new F&O opportunity approval

  Scanner event bus outage            Persist events for replay

  Duplicate event                     Ignore using idempotency key

  Out-of-order event                  Apply event-time and version checks

  Database outage                     Do not acknowledge unpersisted
                                      financial state changes

  Execution service outage            Keep order in recoverable state; do
                                      not invent fills

  WebSocket outage                    Reconnect and reload authoritative
                                      server state
  -----------------------------------------------------------------------

## 20.3 Recovery sequence

1.  Restore service connectivity.
2.  Identify unprocessed events.
3.  Replay using idempotency keys.
4.  Reconcile orders, fills and positions.
5.  Recalculate account ledger.
6.  Recalculate risk.
7.  Verify there are no duplicate positions.
8.  Resume normal processing only after reconciliation succeeds.

# 21. State Machines

## 21.1 Opportunity state machine

``` text
CREATED
  |
VALIDATING
  |------> WATCHLIST
  |------> REJECTED
  |------> EXPIRED
  |
QUALIFIED
  |
PROPOSAL_GENERATED
  |
AWAITING_RISK
  |------> BLOCKED_BY_RISK
  |------> REJECTED
  |
RISK_APPROVED
  |
AWAITING_USER_APPROVAL (approval mode only)
  |------> USER_REJECTED
  |------> APPROVAL_EXPIRED
  |
READY_FOR_ORDER
  |
ORDER_CREATED
```

## 21.2 Order state machine

``` text
CREATED
  |
VALIDATED
  |
PENDING
  |------> PARTIALLY_FILLED
  |             |
  |             +----> FILLED
  |
  +------> FILLED
  +------> CANCELLED
  +------> EXPIRED
  +------> REJECTED
```

## 21.3 Position state machine

``` text
OPEN
 |
MONITORING
 |
PARTIALLY_EXITED
 |
MONITORING
 |
CLOSING
 |
CLOSED
```

Additional states:

-   `RISK_RESTRICTED`
-   `EXIT_PENDING`
-   `EXECUTION_EXCEPTION`
-   `RECONCILIATION_REQUIRED`

# 22. Event and Notification Contract

Use an event-driven architecture. Each event should include a common
envelope.

``` json
{
  "event_id": "uuid",
  "event_type": "OPPORTUNITY_QUALIFIED",
  "event_version": 1,
  "occurred_at": "2026-11-05T09:30:00Z",
  "ingested_at": "2026-11-05T09:30:01Z",
  "correlation_id": "uuid",
  "account_id": "uuid",
  "instrument_id": "uuid",
  "source_service": "opportunity-engine",
  "idempotency_key": "stable-unique-key",
  "payload": {}
}
```

Recommended event types:

-   `SCANNER_SIGNAL_RECEIVED`
-   `SCANNER_SIGNAL_NORMALIZED`
-   `OPPORTUNITY_CREATED`
-   `OPPORTUNITY_UPDATED`
-   `OPPORTUNITY_QUALIFIED`
-   `OPPORTUNITY_REJECTED`
-   `TRADE_PROPOSAL_CREATED`
-   `POSITION_SIZE_CALCULATED`
-   `ALLOCATION_APPROVED`
-   `RISK_APPROVED`
-   `RISK_REJECTED`
-   `PAPER_ORDER_CREATED`
-   `PAPER_ORDER_PARTIALLY_FILLED`
-   `PAPER_ORDER_FILLED`
-   `PAPER_ORDER_CANCELLED`
-   `POSITION_OPENED`
-   `POSITION_MODIFIED`
-   `STOP_TRIGGERED`
-   `TARGET_TRIGGERED`
-   `POSITION_CLOSED`
-   `RISK_LIMIT_BREACHED`
-   `KILL_SWITCH_TRIGGERED`
-   `TRADE_ANALYTICS_COMPLETED`

# 23. User Interaction Workflow

## 23.1 Opportunity review

The user opens a qualified opportunity and sees:

1.  Original scanner signals.
2.  Consolidated signal explanation.
3.  Market and sector context.
4.  Technical confirmation.
5.  Derivatives confirmation, if relevant.
6.  Proposed entry, stop and targets.
7.  Suggested quantity.
8.  Capital required.
9.  Planned and stressed risk.
10. Portfolio impact.
11. Risk decision and reason codes.

Available actions:

-   Approve paper trade.
-   Reject opportunity.
-   Add to watchlist.
-   Request revalidation.

## 23.2 Open position review

The user opens a position and sees:

1.  Entry and fill details.
2.  Current P&L.
3.  Chart with entry, stop and target levels.
4.  Current risk.
5.  Remaining risk budget.
6.  Sector and portfolio exposure.
7.  Position event timeline.
8.  Strategy rationale.

Available actions:

-   Modify stop.
-   Modify target.
-   Reduce position.
-   Exit position.
-   View risk analysis.
-   View supporting scanner signals.

Every action must be validated and recorded.

# 24. Operational Schedule

  -----------------------------------------------------------------------
  Process                             Suggested trigger
  ----------------------------------- -----------------------------------
  Market data ingestion               Continuous during supported
                                      sessions

  Intraday scanner execution          Scanner-specific schedule or data
                                      event

  Signal consolidation                On every normalized signal

  Opportunity validation              On creation and configured
                                      revalidation events

  Risk validation                     Before every new or risk-increasing
                                      order

  Position monitoring                 Quote/bar and relevant event
                                      updates

  Portfolio risk snapshot             Event-driven plus periodic
                                      reconciliation

  Signal outcome tracking             T+1, T+5, T+10 and T+20

  Daily portfolio snapshot            End of trading session

  Strategy analytics                  After trade closure and scheduled
                                      batch

  Data reconciliation                 At startup, recovery and end of day
  -----------------------------------------------------------------------

# 25. Workflow Acceptance Criteria

The workflow is accepted when:

1.  Every scanner event is persisted with its original identity and
    timestamp.
2.  Duplicate delivery does not create duplicate opportunities or
    orders.
3.  Multiple compatible signals consolidate without losing source
    attribution.
4.  Conflicting signals are retained and surfaced.
5.  No trade proposal is created without a valid entry and invalidation
    plan.
6.  Position sizing includes costs and applicable lot-size rules.
7.  Allocation checks available and reserved capital.
8.  Risk validation occurs before order creation.
9.  The risk engine can veto any proposal.
10. User approval cannot override hard risk limits.
11. Paper fills use the configured execution model.
12. Partial fills correctly update orders, positions and ledger.
13. Position P&L reconciles to fills and costs.
14. Risk-increasing modifications are revalidated.
15. Risk-reducing actions remain available during account restrictions.
16. F&O legging risk is detected and handled.
17. Kill switch blocks new entries and risk-increasing changes.
18. Data failures do not create fabricated fills or prices.
19. Service recovery does not duplicate financial events.
20. Signal performance and trade performance remain separate.
21. All decisions can be reconstructed from stored inputs and versioned
    policies.
22. All account and portfolio limits are configurable and auditable.

# 26. Recommended Build Sequence

  -----------------------------------------------------------------------
  Priority                Workflow                Reason
  ----------------------- ----------------------- -----------------------
  P0                      Signal ingestion and    Establish reliable
                          normalization           scanner event flow

  P0                      Consolidation and       Prevent duplicate
                          opportunity creation    opportunities

  P0                      Opportunity validation  Convert signals into
                          and trade proposal      structured setups

  P0                      Position sizing and     Enforce risk before
                          deterministic risk      order creation

  P0                      Paper orders, fills and Establish correct
                          ledger                  simulated accounting

  P0                      Position monitoring and Complete the trading
                          exits                   lifecycle

  P1                      Portfolio allocation    Improve portfolio-level
                          and correlation         risk management

  P1                      F&O multi-leg workflow  Add
                                                  derivatives-specific
                                                  controls

  P1                      Trade journal and       Measure strategy
                          analytics               outcomes

  P2                      Optimization and        Introduce only after
                          dynamic allocation      sufficient evidence

  P2                      Advanced AI             Improve usability
                          explanations and        without bypassing
                          research                controls
  -----------------------------------------------------------------------

# 27. Final Operating Principle

The Nivesh workflow must follow this order:

**Detect → Normalize → Consolidate → Validate → Propose → Size →
Allocate → Risk Approve → Execute → Monitor → Exit → Reconcile →
Learn.**

No downstream component may silently bypass an upstream control.

The Opportunity Engine determines whether a setup is worth considering.
The Capital Allocation Engine determines how much capital may be
assigned. The Risk Engine decides whether the proposed exposure is
permitted. The Paper Execution Engine records what could realistically
have been filled. The Analytics Engine determines whether the process
demonstrates repeatable evidence of an edge.

This separation is essential for a reliable, explainable and auditable
paper-trading platform.
