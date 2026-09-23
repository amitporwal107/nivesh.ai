> **Filed in the repository on 2026-09-23 at the owner's request, for tracking.** The body below is the owner's
> document as received, verbatim. It was reviewed against the plan and the code on 2026-09-22 and the outcome is
> recorded in `docs/charting.md` §38.19 Amendment E, which governs wherever this document and the amendment differ.
>
> Positions from §38.19 that apply to this document:
>
> - **Sequence (§38.19.3, position 1).** Paper trading is step 8, after live signals (step 7) and after study plan
>   v2 reports. Signal-only mode (§7.3, "what would have happened if this signal had been traded") is the research
>   question and ships first; it is the forward run. Auto-paper mode, manual tickets and the dashboard follow.
> - **One execution kernel (§38.19.4, position 5).** The paper engine extends the existing TPD paper engine
>   (`backend/nidp/services/tpd_model/paper/` on `feat/paper-trade-engine`, `/api/paper-trades`) rather than
>   building a second one, and reuses `research/costs/` (statutory and broker rules, four slippage scenarios, the
>   liquidity bucket, sensitivity tables), `research/charting/events/outcomes.py` (entry at the next open) and
>   `research/charting/events/stops.py` (gap fills at the open, and AMBIGUOUS when the stop and the target are
>   inside one bar — `first_exit_event == "AMBIGUOUS"`, `exit_price` None; corrected 2026-09-23, it was
>   attributed to `outcomes.py`). The §13 cost engine and §17–§21
>   fills, stops, ledger and replay describe these. This document lacks the AMBIGUOUS rule; without it paper results
>   would not reconcile with v2 on the same events. Paper results must reconcile row for row with v2.
> - **Phase 1 (§61).** Daily, long-only, owner-only and fixed quantity.
> - **Setup and ticket (position 3).** Entry, stop, targets, quantity and capital at risk (§15, §16, §37) are
>   visible only behind the owner allowlist until the SEBI RA/IA question (NI-1a) is answered. Setup values come from
>   the frozen definitions (stop = the NI-3 Layer-1 structural stop widened to at least 0.75 × ATR(14); targets = the
>   v2 set); the ₹1,256 / ₹1,218 / ₹1,300 / ₹1,320 example is illustrative.
> - **Score (position 2).** `signal_score` (§16, §23, §28) is components only; there is no headline 0–100 number.
> - **Lifecycle (position 4).** The research state names are canonical (mapping in the filing header of
>   `docs/prd/live_trading_alerts_signals_prd.md` and in §38.19.4). INVALIDATED and FAILED_BREAKOUT stay distinct.
> - **Illustrative numbers.** Every P&L, win-rate, expectancy and per-pattern figure in the examples (§24, §28,
>   §39, §57, §66) is illustrative; no study has run. Every real study to date found no edge, and the negative and
>   empty state of the §40 research-comparison block is a required design.
> - **What lines up already (§38.19.6).** Principle 12, §41 and §65 (paper results never tune frozen rules; pattern,
>   signal and trade are three separate truths) match #110; §34 gap handling matches v1 §5; the disclaimers match
>   §2.1.

# PRD — Nivesh Paper Trading & Signal Validation Engine

**Product:** Nivesh Charting / Technical Signal Platform  
**Document:** Product Requirements Document  
**Version:** 1.0  
**Date:** 2026-09-22  
**Status:** Proposed

---

## 1. Executive Summary

Nivesh Paper Trading is a simulated trading environment that sits between the **live signal engine** and eventual real-world trading.

It must allow the system to:

1. Detect a technical pattern.
2. Generate a live signal.
3. Define entry, stop, target and risk/reward.
4. Create a simulated trade either automatically or after user approval.
5. Track the position using market data.
6. Apply realistic transaction costs and configurable slippage.
7. Exit on stop, target, invalidation or manual close.
8. Record the complete signal-to-trade lifecycle.
9. Measure gross and net performance.
10. Compare paper-trade outcomes with historical research.

The objective is not merely to maintain a virtual brokerage balance. The primary objective is to answer:

> **"If I followed this exact Nivesh signal, what would the outcome have been after realistic costs and execution assumptions?"**

---

# 2. Product Principles

1. **Signal and paper trade are separate objects.**
2. Every paper trade must reference the signal that created it.
3. The original signal must never be modified after trade creation.
4. All executions must use only information available at the time.
5. Transaction costs must be included in net P&L.
6. Slippage must be configurable.
7. Paper trading must never place real broker orders.
8. Manual and automatic paper-trade modes must both be supported.
9. Every simulated execution must be auditable.
10. Historical research and live paper trading must remain separate datasets.
11. Strategy, pattern and signal versions must be preserved.
12. Paper results must not be used to tune frozen research parameters without creating a new research version.

---

# 3. Goals

## 3.1 Primary Goals

- Validate live technical signals in a controlled environment.
- Measure real-time signal-to-trade performance.
- Track entry, stop, target and exit behavior.
- Calculate gross and net P&L.
- Model realistic transaction costs.
- Model configurable slippage.
- Track win/loss, expectancy, drawdown and risk-adjusted performance.
- Provide a trading journal automatically generated from signals.
- Allow historical replay and paper-trade comparison.
- Preserve complete auditability.

## 3.2 Secondary Goals

- Allow users to manually paper trade any chart setup.
- Allow users to accept/reject system-generated signals.
- Support multiple paper accounts.
- Support configurable capital and risk settings.
- Support future broker integration without redesigning the core trade model.

---

# 4. Non-Goals

The first release will NOT:

- Execute real broker orders.
- Transfer money.
- Guarantee order fills.
- Claim that paper performance equals live performance.
- Optimize signal parameters automatically.
- Change historical research rules based on paper results.
- Automatically recommend portfolio-level allocation.
- Provide unrestricted leverage.
- Hide transaction costs.

---

# 5. Relationship With Existing Nivesh Architecture

The paper-trading layer sits after the live signal engine.

```text
MARKET DATA
     │
     ▼
INDICATORS
     │
     ▼
PATTERN ENGINE
     │
     ▼
SIGNAL ENGINE
     │
     ├──────────────► LIVE ALERT
     │
     ▼
PAPER TRADE
     │
     ▼
SIMULATED EXECUTION
     │
     ▼
POSITION
     │
     ├── STOP
     ├── TARGET
     ├── INVALIDATION
     └── MANUAL EXIT
     │
     ▼
TRADE RESULT
     │
     ▼
PERFORMANCE ANALYTICS
```

The historical research engine remains independent:

```text
Historical Data
      ↓
Frozen Detector
      ↓
Study Plan
      ↓
Historical Validation
```

Paper trading must not mutate historical research records.

---

# 6. Core User Journey

## 6.1 System-generated paper trade

```text
Pattern detected
       ↓
WATCH
       ↓
READY
       ↓
BREAKOUT
       ↓
CONFIRMED
       ↓
Entry / Stop / Target generated
       ↓
Paper Trade Candidate
       ↓
User accepts OR auto-paper mode
       ↓
Simulated Fill
       ↓
Open Position
       ↓
Stop / Target / Exit
       ↓
Closed Trade
       ↓
Net P&L
       ↓
Performance Analytics
```

## 6.2 Manual paper trade

```text
Chart
 ↓
User selects Paper Trade
 ↓
Entry / Quantity / Stop / Target
 ↓
Cost calculation
 ↓
Simulated order
 ↓
Position
 ↓
Exit
 ↓
Trade journal
```

---

# 7. Paper Trading Modes

## 7.1 Manual Mode

The user must explicitly approve a paper trade.

Example:

```text
CONFIRMED BREAKOUT

CGPOWER
15-minute

Entry: ₹1,256
Stop: ₹1,218
Target: ₹1,320

[ PAPER TRADE ]
```

User clicks **Paper Trade**.

---

## 7.2 Auto Paper Mode

When a configured signal reaches `CONFIRMED`, Nivesh automatically creates a simulated trade.

The user must configure:

- Capital
- Risk per trade
- Maximum concurrent trades
- Maximum daily loss
- Quantity calculation
- Cost model
- Slippage model
- Entry policy

---

## 7.3 Signal-Only Mode

No simulated trade is created.

The system records the signal and later calculates:

> "What would have happened if this signal had been traded?"

This mode is important for unbiased signal evaluation.

---

# 8. Paper Account

Each user may have one or more paper accounts.

Account fields:

```text
account_id
user_id
account_name
base_currency
initial_cash
available_cash
equity
realized_pnl
unrealized_pnl
total_costs
margin_used
created_at
updated_at
status
```

Example:

```text
Account
----------------------------
Initial Capital     ₹10,00,000
Available Cash      ₹8,75,000
Open Position Value ₹1,20,000
Realized P&L        ₹12,400
Unrealized P&L      ₹8,600
Costs               ₹2,150
Equity              ₹9,96,850
```

---

# 9. Supported Instruments

Initial release:

- NSE equities
- ETFs where supported by market data

Future:

- Index instruments
- Futures
- Options
- Mutual funds
- Other exchanges

Instrument eligibility must be controlled by the market-data layer.

---

# 10. Order Types

Initial release:

### Market

Simulated execution at the defined market execution price.

### Limit

Order fills only when the configured fill condition is satisfied.

### Stop

Order becomes executable when the stop trigger is reached.

### Stop-limit

Optional after the initial release.

---

# 11. Entry Execution

Every paper trade must record:

```text
signal_price
requested_price
execution_price
execution_timestamp
execution_bar
execution_method
slippage
```

The distinction is important.

Example:

```text
Signal price:       ₹1,256
Requested entry:    ₹1,256
Simulated fill:     ₹1,258
Slippage:           ₹2
```

The system must never silently replace the signal price with the actual simulated fill.

---

# 12. Slippage Model

Slippage must be configurable.

## 12.1 Fixed amount

```text
₹0.50/share
```

## 12.2 Percentage

```text
0.10%
```

## 12.3 ATR-based

```text
0.05 × ATR
```

## 12.4 Market/liquidity model

Future enhancement using:

- Volume
- Spread
- Average traded value
- Order size
- Volatility

Every paper trade must store the exact slippage model used.

---

# 13. Transaction Cost Engine

The system must calculate:

```text
Entry Value
+ Entry Brokerage
+ Entry STT
+ Entry Exchange Charges
+ Entry SEBI Charges
+ Entry GST
+ Entry Stamp Duty
+ Entry Slippage
+
Exit Value
+ Exit Brokerage
+ Exit STT
+ Exit Exchange Charges
+ Exit SEBI Charges
+ Exit GST
+ Exit Stamp Duty
+ Exit Slippage
--------------------------------
Total Transaction Cost
```

The actual applicable charge configuration must be versioned by:

```text
market
instrument
transaction_type
broker/profile
date
cost_model_version
```

The system must not hard-code a single universal cost assumption.

---

# 14. P&L Calculation

## 14.1 Gross P&L

For a long position:

```text
Gross P&L =
(exit_price - entry_price) × quantity
```

For a short position:

```text
Gross P&L =
(entry_price - exit_price) × quantity
```

## 14.2 Net P&L

```text
Net P&L =
Gross P&L
- Total transaction costs
- Slippage
```

Where slippage is either embedded in execution prices or separately modeled, but never double-counted.

---

# 15. Position Sizing

Paper trading must support two modes.

## 15.1 Fixed Quantity

Example:

```text
Quantity = 100 shares
```

## 15.2 Risk-Based Quantity

Example:

```text
Capital: ₹10,00,000
Risk/trade: 1%
Maximum risk: ₹10,000

Entry: ₹1,256
Stop: ₹1,218

Risk/share = ₹38

Quantity =
₹10,000 / ₹38
= 263 shares
```

Actual quantity must respect:

- Lot size where applicable
- Available capital
- Maximum position value
- Maximum portfolio exposure

---

# 16. Trade Setup

Every system-generated trade must contain:

```text
symbol
pattern
timeframe
direction

entry
stop
target_1
target_2

risk_per_share
position_size
capital_at_risk
reward_risk_ratio

signal_components
signal_id
pattern_id
strategy_version
```

> **Amended 2026-09-23 (owner decision) per §38.19 Amendment E position 2.** This field was
> `signal_score` (a 0–100 number) in §16, §23 and §28. The headline number is removed; the row
> carries **components only**. Any composite of them is a research object — pre-registered in a
> later study version, tested, then shown. Frozen in `research/charting/signal_contract.py`,
> which has `score_components` and deliberately no `score` field. Original text is in git history.

Example:

```text
CGPOWER
Ascending Triangle
15m
LONG

Entry:       ₹1,256
Stop:        ₹1,218
Target 1:    ₹1,300
Target 2:    ₹1,320

Risk/share:  ₹38
Quantity:    263
Risk:        ₹9,994
R:R Target2: 1 : 1.68
```

---

# 17. Position Lifecycle

```text
CREATED
   ↓
PENDING
   ↓
FILLED
   ↓
OPEN
   ↓
 ┌─────────────┬──────────────┬───────────────┐
 ▼             ▼              ▼
TARGET       STOP          INVALIDATED
 ▼             ▼              ▼
CLOSED       CLOSED         CLOSED
   └─────────────┬──────────────┘
                 ▼
             COMPLETED
```

Additional state:

```text
CANCELLED
```

for orders that never execute.

---

# 18. Exit Conditions

A position can close because of:

1. Stop loss
2. Target 1
3. Target 2
4. Pattern invalidation
5. Signal failure
6. Time-based exit
7. Manual user exit
8. End-of-study/session rule
9. Data/session handling rule

The exact exit reason must be recorded.

---

# 19. Multiple Targets

The system must support partial exits.

Example:

```text
Position: 200 shares

Target 1: ₹1,300
Exit 100 shares

Target 2: ₹1,320
Exit remaining 100 shares
```

The trade record must preserve every fill separately.

---

# 20. Stop Management

Initial release:

- Fixed stop
- Pattern invalidation stop
- ATR-based stop

Future:

- Break-even stop
- Trailing stop
- Swing-low/high stop
- Volatility-adjusted trailing stop

Stop changes must be recorded as events.

```text
STOP_CHANGED
old_stop
new_stop
timestamp
reason
```

---

# 21. Paper Trade Ledger

Every transaction must create an immutable ledger event.

Example:

```text
TRADE_CREATED
ORDER_SUBMITTED
ORDER_FILLED
STOP_UPDATED
TARGET_REACHED
PARTIAL_EXIT
POSITION_CLOSED
```

Each event:

```text
event_id
trade_id
event_type
timestamp
price
quantity
cost
source
metadata
```

This allows complete reconstruction of the trade.

---

# 22. Signal-to-Trade Link

A paper trade must reference the originating signal.

```text
Signal
SIG-20260922-00123
       │
       ▼
Paper Trade
TRD-20260922-00451
```

The system must preserve:

```text
signal_id
pattern_id
signal_version
pattern_version
indicator_version
strategy_version
detector_fingerprint
```

This is mandatory for research integrity.

---

# 23. Snapshot at Trade Creation

When a paper trade is created, store the complete signal snapshot.

Example:

```text
Pattern:
Ascending Triangle

Trigger:
₹1,256

Volume:
1.7×

ADX:
27

RSI:
64

Trend:
Bullish

Signal components:
Pattern 18/20 · Breakout 19/20 · Volume 14/15 · Trend 13/15 · Relative 8/10

Entry:
₹1,256

Stop:
₹1,218

Target:
₹1,320
```

Later changes to indicators must not alter the historical snapshot.

---

# 24. Dashboard

The paper-trading dashboard should contain:

### Account summary

```text
Capital
Equity
Available cash
Open P&L
Realized P&L
Costs
Drawdown
```

### Open positions

```text
Symbol
Pattern
Direction
Entry
Current
Stop
Target
Qty
P&L
P&L %
```

### Pending orders

```text
Symbol
Order
Price
Quantity
Status
```

### Closed trades

```text
Symbol
Pattern
Entry
Exit
Gross P&L
Costs
Net P&L
Return
Holding period
Exit reason
```

---

# 25. Chart Integration

When a paper position is open, display:

```text
TARGET ─────────────────────

CURRENT PRICE
       │
ENTRY ──────────────────────

       │
       │
STOP ───────────────────────
```

Also display:

- Pattern geometry
- Signal marker
- Entry marker
- Stop
- Target
- Retest
- Exit marker

The chart must distinguish:

- Signal-generated trades
- Manually created paper trades

---

# 26. Paper Trade Card

Example:

```text
┌─────────────────────────────────┐
│ 🟢 PAPER POSITION               │
│                                 │
│ CGPOWER                         │
│ Ascending Triangle • 15m        │
│                                 │
│ Entry       ₹1,256              │
│ Current     ₹1,274              │
│ Stop        ₹1,218              │
│ Target      ₹1,320              │
│                                 │
│ Qty         263                 │
│ Risk        ₹9,994              │
│                                 │
│ Gross P&L   +₹4,734             │
│ Costs       -₹312               │
│ Net P&L     +₹4,422             │
│                                 │
│ [ Close ] [ View Signal ]       │
└─────────────────────────────────┘
```

---

# 27. Performance Analytics

The system must calculate:

## Basic

- Total trades
- Winning trades
- Losing trades
- Win rate
- Gross P&L
- Net P&L
- Average trade
- Average winner
- Average loser

## Risk

- Maximum drawdown
- Average drawdown
- Risk per trade
- Profit factor
- Expectancy
- Sharpe ratio where sufficient data exists
- Sortino ratio where sufficient data exists

## Execution

- Average slippage
- Average transaction cost
- Fill rate
- Time to fill
- Partial-fill rate

---

# 28. Signal Performance

Performance must be broken down by:

- Pattern
- Timeframe
- Signal state
- Signal score bucket
- Direction
- Sector
- Market regime
- Entry type
- Stop type
- Target
- Holding period

Example:

```text
Ascending Triangle
-------------------------
Signals          128
Paper trades      96
Wins              54
Losses            42
Win rate         56.3%
Gross P&L       +₹82,400
Costs            -₹9,800
Net P&L         +₹72,600
```

These statistics must not be interpreted as guaranteed future performance.

---

# 29. Signal vs Paper Trade Analysis

This is a critical feature.

For every signal, record both:

### What the signal predicted

```text
Entry
Stop
Target
Expected move
Signal score
```

### What actually happened

```text
Maximum favorable excursion
Maximum adverse excursion
Actual exit
Actual return
Time to target
Time to stop
```

This allows analysis of signals even when the user did not take the paper trade.

---

# 30. MAE / MFE

For every signal/trade calculate:

### Maximum Adverse Excursion

Worst movement against the position before exit.

### Maximum Favorable Excursion

Best movement in favor of the position before exit.

Example:

```text
Entry: ₹1,256

MFE: +7.1%
MAE: -1.8%
Exit: +4.3%
```

These metrics help determine whether stops and targets are appropriately positioned.

---

# 31. Holding Period

Track:

```text
bars_held
minutes_held
sessions_held
```

Support:

- Intraday
- Multi-session
- Positional

The timeframe must always be stored separately from holding period.

---

# 32. Time-Based Exit

A paper-trade strategy may define:

```text
Maximum holding period = 5 sessions
```

When reached:

```text
TIME_EXIT
```

The exit must be recorded separately from stop and target exits.

---

# 33. Market Session Handling

The engine must understand:

- Market open
- Market close
- Trading holidays
- Weekend
- Pre-market where applicable
- Post-market where applicable
- Circuit conditions

No simulated execution should occur during a non-trading period unless explicitly supported by the instrument.

---

# 34. Gap Handling

The system must explicitly handle gaps.

Example:

```text
Previous close: ₹1,250
Stop: ₹1,218
Next open: ₹1,190
```

The simulated stop must not automatically assume execution at ₹1,218 if the configured execution model says a gap causes a worse fill.

The trade should record:

```text
Expected stop: ₹1,218
Actual simulated exit: ₹1,190
Gap slippage: ₹28
```

This is important for realistic validation.

---

# 35. Liquidity Controls

Optional trade eligibility filters:

- Minimum traded value
- Minimum volume
- Maximum position as % of volume
- Maximum position as % of average traded value
- Maximum simulated slippage

A paper trade should be marked `REJECTED` rather than silently filled when liquidity rules prohibit the trade.

---

# 36. Capital Controls

Paper account settings:

```text
Initial capital
Maximum capital per trade
Maximum risk per trade
Maximum open positions
Maximum sector exposure
Maximum daily loss
Maximum portfolio drawdown
Maximum leverage
```

When a rule is violated:

```text
PAPER_TRADE_REJECTED
```

with a clear reason.

---

# 37. Risk-Based Example

Assume:

```text
Capital: ₹10,00,000
Risk/trade: 1%
Maximum risk: ₹10,000

Entry: ₹1,256
Stop: ₹1,218

Risk/share: ₹38
```

Quantity:

```text
₹10,000 / ₹38
= 263 shares
```

Maximum position:

```text
₹1,256 × 263
= ₹3,30,328
```

The system must then verify the account's maximum position and capital constraints.

---

# 38. Cost Example

Assume:

```text
Gross profit:       ₹5,000
Brokerage:          ₹100
Exchange charges:    ₹25
STT:                 ₹80
GST:                 ₹22
SEBI/other:           ₹5
Slippage:            ₹150
--------------------------------
Net P&L:           ₹4,618
```

The exact rates must come from the active cost model rather than being permanently embedded in application logic.

---

# 39. Paper Trading Journal

Every completed trade automatically creates a journal entry.

Example:

```text
CGPOWER

Pattern:
Ascending Triangle

Signal:
CONFIRMED

Entry:
₹1,256

Exit:
₹1,312

Result:
+4.46%

Gross P&L:
+₹14,728

Costs:
-₹512

Net:
+₹14,216

Holding:
2 sessions

Exit:
Target 1

Signal components:
Pattern 18/20 · Breakout 19/20 · Volume 14/15 · Trend 13/15 · Relative 8/10
```

The user may add notes:

```text
User note:
"Breakout had strong volume but market was weak."
```

---

# 40. Comparison With Historical Research

For each paper trade, show:

```text
LIVE PAPER TRADE
        │
        ▼
Historical Comparable Set
        │
        ├── Sample size
        ├── Success rate
        ├── Median move
        ├── Median holding period
        ├── Drawdown
        └── Cost-adjusted return
```

The historical statistics must be clearly separated from the individual live outcome.

---

# 41. Research Integrity

Paper-trading results must never be used to silently modify:

- Frozen detector rules
- Frozen pattern thresholds
- Study-plan v1
- Sealed research period
- Historical datasets

If paper results lead to a rule change:

```text
New strategy version
New signal version
New detector fingerprint if applicable
New research study
```

must be created.

---

# 42. No Look-Ahead Bias

The paper engine must use only information available at the simulated timestamp.

Forbidden:

- Future high/low when determining an earlier fill
- Future volume
- Future candle close
- Future pattern confirmation
- Future corporate event
- Future indicator values
- End-of-day information for an intraday decision

Historical replay must use the same timestamp discipline.

---

# 43. Paper Trading Replay

The system should support historical replay.

Example:

```text
Replay date:
2025-06-10

Start:
09:15

End:
15:30

Initial capital:
₹10,00,000
```

The engine processes bars sequentially as if the future did not exist.

This allows:

> "What would the live signal engine have done on this historical day?"

---

# 44. Replay Modes

### Fast replay

Process one bar at a time automatically.

### Step replay

User advances one bar at a time.

### Signal replay

Pause whenever a signal appears.

### Trade replay

Pause when a paper-trade entry/exit occurs.

---

# 45. Paper Trading vs Backtesting

The system must clearly distinguish:

### Backtest

Known historical dataset, systematic evaluation of predefined rules.

### Historical replay

Historical data processed sequentially using live-like logic.

### Paper trading

Current/live market simulation with no real capital.

### Live trading

Real broker execution.

These must never be mixed in reporting.

---

# 46. Database Model

Suggested entities:

```text
paper_accounts
paper_orders
paper_order_fills
paper_positions
paper_trades
paper_trade_events
paper_signal_snapshots
paper_cost_models
paper_execution_models
paper_performance_snapshots
paper_journal_entries
```

---

# 47. Paper Account Schema

```text
paper_accounts
-------------------------
id
user_id
name
currency
initial_cash
available_cash
equity
realized_pnl
unrealized_pnl
total_costs
status
created_at
updated_at
```

---

# 48. Paper Order Schema

```text
paper_orders
-------------------------
id
account_id
signal_id
symbol
side
order_type
quantity
requested_price
stop_price
limit_price
status
created_at
updated_at
```

---

# 49. Paper Trade Schema

```text
paper_trades
-------------------------
id
account_id
signal_id
pattern_id

symbol
timeframe
side

entry_price
exit_price

quantity

stop_price
target_1
target_2

gross_pnl
transaction_cost
slippage
net_pnl

entry_timestamp
exit_timestamp

holding_period
exit_reason

pattern_version
signal_version
strategy_version
detector_fingerprint

created_at
updated_at
```

---

# 50. Trade Event Schema

```text
paper_trade_events
-------------------------
id
trade_id
event_type
timestamp

price
quantity
cost

old_value
new_value

reason
metadata
```

---

# 51. APIs

## Accounts

```http
GET /paper/accounts
POST /paper/accounts
GET /paper/accounts/{id}
PATCH /paper/accounts/{id}
```

## Orders

```http
POST /paper/orders
GET /paper/orders
GET /paper/orders/{id}
DELETE /paper/orders/{id}
```

## Positions

```http
GET /paper/positions
GET /paper/positions/{id}
POST /paper/positions/{id}/close
```

## Trades

```http
GET /paper/trades
GET /paper/trades/{id}
```

## Performance

```http
GET /paper/performance
GET /paper/performance/by-pattern
GET /paper/performance/by-timeframe
GET /paper/performance/by-signal-score
```

## Replay

```http
POST /paper/replay
GET /paper/replay/{id}
POST /paper/replay/{id}/step
```

---

# 52. Real-Time Events

Use WebSocket or SSE for:

```text
PAPER_ORDER_CREATED
PAPER_ORDER_FILLED
PAPER_POSITION_OPENED
PAPER_POSITION_UPDATED
PAPER_STOP_HIT
PAPER_TARGET_HIT
PAPER_POSITION_CLOSED
PAPER_SIGNAL_UPDATED
```

Example:

```json
{
  "event": "PAPER_POSITION_UPDATED",
  "trade_id": "TRD-001",
  "symbol": "CGPOWER",
  "price": 1274,
  "unrealized_pnl": 4734,
  "timestamp": "2026-09-22T11:45:00+05:30"
}
```

---

# 53. User Controls

The user must be able to:

- Create paper account
- Set initial capital
- Configure risk
- Select cost model
- Select slippage model
- Enable/disable auto paper trading
- Accept/reject signals
- Manually create trades
- Modify pending orders
- Modify stops where permitted
- Close positions
- Reset account
- Export trade history

---

# 54. Reset Account

Reset must be explicit.

Options:

```text
Reset balance only
Reset all positions and orders
Full account reset
```

A reset must not delete historical research records.

Prefer archiving the old paper account rather than destroying its audit history.

---

# 55. Export

Support CSV/Excel export containing:

```text
Trade ID
Signal ID
Symbol
Pattern
Timeframe
Direction

Entry
Exit
Quantity

Gross P&L
Costs
Slippage
Net P&L

Holding period
Exit reason

Signal score
Pattern version
Signal version
Strategy version
```

---

# 56. Alerts

Paper trading must integrate with the live signal alert system.

Examples:

### Entry

> PAPER TRADE OPENED — CGPOWER  
> Ascending Triangle  
> Entry ₹1,256

### Stop

> PAPER TRADE STOPPED — CGPOWER  
> Exit ₹1,218  
> Net P&L: -₹10,xxx

### Target

> PAPER TARGET HIT — CGPOWER  
> Target 1 ₹1,300  
> Partial exit completed

### Completion

> PAPER TRADE CLOSED — CGPOWER  
> Net P&L +₹14,216  
> Holding period 2 sessions

---

# 57. Performance Dashboard

Recommended sections:

## Account

```text
Equity
Available Cash
Open P&L
Realized P&L
Drawdown
```

## Trading

```text
Trades
Win Rate
Profit Factor
Expectancy
Average Win
Average Loss
```

## Signal quality

```text
Signals
Trades Taken
Signal → Trade Conversion
Signal Win Rate
```

## Pattern performance

```text
Ascending Triangle
Double Bottom
Bull Flag
Cup & Handle
...
```

## Cost analysis

```text
Gross P&L
Transaction Costs
Slippage
Net P&L
```

---

# 58. Signal Conversion Metrics

Track:

```text
Total signals
READY signals
CONFIRMED signals
Paper trades created
Paper trades accepted
Paper trades rejected
Paper trades completed
```

This answers:

> "How many technically valid signals actually become trades?"

---

# 59. Trade Quality Metrics

For every pattern:

```text
Signal count
Trade count
Win rate
Average return
Median return
Average MFE
Average MAE
Average holding period
Profit factor
Maximum drawdown
Net return after costs
```

---

# 60. Paper Trading Acceptance Criteria

The first release is acceptable when:

- [ ] A user can create a paper account.
- [ ] A confirmed signal can create a paper trade.
- [ ] Manual paper trades work.
- [ ] Auto-paper mode works.
- [ ] Market/limit/stop orders work according to defined simulation rules.
- [ ] Entry price is recorded separately from signal price.
- [ ] Slippage is modeled.
- [ ] Transaction costs are modeled.
- [ ] Gross and net P&L are calculated.
- [ ] Stops close positions correctly.
- [ ] Targets close positions correctly.
- [ ] Partial exits work.
- [ ] Gaps are handled explicitly.
- [ ] Trade events are immutable/auditable.
- [ ] Signal snapshots are preserved.
- [ ] Pattern/signal/strategy versions are preserved.
- [ ] Paper positions appear on the chart.
- [ ] Dashboard shows open and closed trades.
- [ ] Performance metrics are calculated.
- [ ] Historical replay does not use future data.
- [ ] Paper results remain separate from historical research.
- [ ] Account reset does not destroy audit history.

---

# 61. Phase 1 — MVP

Build:

- One paper account
- NSE equities
- Long positions
- Manual + confirmed-signal paper trades
- Market orders
- Fixed quantity
- Entry / stop / target
- Basic slippage
- Transaction cost engine
- Open positions
- Closed trades
- Net P&L
- Chart overlay
- Trade journal
- Signal snapshot

---

# 62. Phase 2

Add:

- Risk-based position sizing
- Limit orders
- Stop orders
- Multiple targets
- Partial exits
- Auto-paper mode
- Multiple paper accounts
- Advanced performance analytics
- MAE/MFE
- Historical replay

---

# 63. Phase 3

Add:

- Liquidity-aware execution
- Dynamic slippage
- Advanced gap model
- Intraday execution simulation
- Market regime analysis
- Signal-score analysis
- Pattern-level research dashboards
- More instruments

---

# 64. Phase 4 — Broker Readiness

Design the execution abstraction so that:

```text
PaperExecutionProvider
        │
        ├── Market simulation
        └── Limit simulation

RealBrokerExecutionProvider
        │
        ├── Broker A
        ├── Broker B
        └── Broker C
```

The paper engine must not depend directly on broker-specific code.

This allows future broker integration without changing:

- Signal engine
- Risk engine
- Trade model
- Performance analytics
- Chart UI

---

# 65. Critical Research Safeguard

The paper engine must preserve three independent truths:

### 1. What the system detected

```text
PATTERN
```

### 2. What the system signaled

```text
SIGNAL
```

### 3. What the simulated trade did

```text
PAPER TRADE
```

Never overwrite one with another.

For example:

```text
Pattern:
Ascending Triangle ✓

Signal:
Confirmed breakout ✓

Paper trade:
Stopped out ✕

```

This is a valid outcome and must remain visible.

---

# 66. Example End-to-End Scenario

Assume:

```text
Symbol: CGPOWER
Timeframe: 15m

Pattern:
Ascending Triangle

Resistance:
₹1,250

Signal:
CONFIRMED

Trigger:
₹1,256

Volume:
1.7×

Entry:
₹1,256

Stop:
₹1,218

Target:
₹1,320
```

Risk-based account:

```text
Capital: ₹10,00,000
Risk: 1%

Maximum risk:
₹10,000

Risk/share:
₹38

Quantity:
263
```

Price subsequently moves:

```text
₹1,256 → ₹1,274 → ₹1,300 → ₹1,320
```

Target 1 could close part of the position and Target 2 close the remainder.

The system records:

```text
Signal generated
Paper trade created
Entry filled
Price updated
Target 1 reached
Partial exit
Target 2 reached
Final exit
Costs calculated
Net P&L calculated
Trade journal created
```

The historical research system remains untouched.

---

# 67. Key Product Decision

Nivesh should not simply copy the concept of a virtual brokerage account.

The central product should be:

> **Signal-driven paper trading.**

TradingView-style paper trading answers:

> "Can I simulate placing a trade?"

Nivesh paper trading should additionally answer:

> "What happened when I followed this exact technical signal, under these exact entry, stop, target, cost and execution assumptions?"

That distinction is the core value of the Nivesh implementation.

---

# 68. Final Architecture

```text
                       MARKET DATA
                            │
              ┌─────────────┴─────────────┐
              │                           │
              ▼                           ▼
       HISTORICAL ENGINE             LIVE ENGINE
              │                           │
              ▼                           ▼
        PATTERN DETECTOR             PATTERN DETECTOR
              │                           │
              ▼                           ▼
        RESEARCH STUDY               SIGNAL ENGINE
                                          │
                                          ▼
                                     LIVE ALERT
                                          │
                                          ▼
                                  PAPER TRADE ENGINE
                                          │
                         ┌────────────────┼────────────────┐
                         │                │                │
                         ▼                ▼                ▼
                       ENTRY            STOP            TARGET
                         │                │                │
                         └────────────────┼────────────────┘
                                          ▼
                                   EXECUTION MODEL
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                         COST ENGINE             SLIPPAGE
                              │                       │
                              └───────────┬───────────┘
                                          ▼
                                      NET P&L
                                          │
                                          ▼
                                  PERFORMANCE ENGINE
                                          │
                         ┌────────────────┼────────────────┐
                         ▼                ▼                ▼
                      ACCOUNT          SIGNAL           PATTERN
                    PERFORMANCE      PERFORMANCE       PERFORMANCE
```

---

# 69. Definition of Done

The Paper Trading Engine is considered production-ready when a user can:

1. Receive a live Nivesh signal.
2. Understand exactly why it triggered.
3. See entry, stop and target.
4. Accept the signal as a paper trade.
5. Have the system simulate execution.
6. See the position live on the chart.
7. See realistic costs and slippage.
8. Receive stop/target/exit alerts.
9. Review the completed trade.
10. See gross and net P&L.
11. See MAE/MFE and holding period.
12. Trace the trade back to the original signal.
13. Compare the result with historical research.
14. Replay the signal historically without look-ahead bias.
15. Verify which pattern, signal and strategy version generated the trade.

The resulting workflow is:

**Pattern → Signal → Alert → Paper Entry → Simulated Execution → Position → Exit → Net P&L → Performance → Research Feedback**

with complete versioning and auditability at every stage.
