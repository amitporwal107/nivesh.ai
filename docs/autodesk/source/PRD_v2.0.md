# Nivesh.ai Autonomous Trading Desk
## Integrated Product Requirements Document (PRD)

**Version:** 2.0  
**Date:** 5 November 2026  
**Product:** Nivesh.ai  
**Module:** Autonomous Trading Desk  
**Market:** India — NSE/BSE equity cash, equity/index futures and options  
**Status:** Unified product baseline for architecture, design, simulation, implementation and certification

---

## Document Navigation

- **Part I — Autonomous Trading Desk:** Sections 1–27 cover the operating model, agents, orchestration, lifecycle, capital, policy, execution, data, UX, APIs, security and core platform requirements.
- **Part II — Trading Desk Simulator:** Sections 28–37 define the simulator as a first-class product subsystem, including simulation modes, market realism, agent coordination, end-to-end trading-day workflows, scenarios, dashboard, data model, APIs and acceptance criteria.
- **Part III — Delivery and certification:** The implementation roadmap and acceptance requirements in Sections 21–23 apply to both the production desk and simulator. Simulator certification is a mandatory gate before controlled live execution.

The simulator requirements are integrated with the production desk requirements: they reuse the same strategy, risk, approval, lifecycle and execution contracts, while enforcing isolated simulation state and a hard prohibition on live broker routing.

---

## 1. Executive Summary

Nivesh Autonomous Trading Desk is a multi-agent AI-powered trading platform designed to operate like a professional trading organisation. It coordinates specialised agents and deterministic services to discover opportunities, generate strategies, assess risk, allocate capital, authorize trades, execute orders, manage open positions, reconcile activity and evaluate performance.

The platform automates the complete trading workflow:

**Market Intelligence → Opportunity Discovery → Strategy Generation → Risk Assessment → Capital Allocation → Authorization → Execution → Position Management → Exit → Reconciliation → Performance Analysis**

The five primary AI agents are:

1. **AI Trader — Opportunity Hunter**
2. **Trading Assistant — Strategist and Trader Interface**
3. **Risk & Operations Agent — Risk Guardian**
4. **Middle Office Supervisor — Independent Controller**
5. **Tech Support & Reliability Agent — Infrastructure Guardian**

The deterministic operating backbone consists of:

- Desk Orchestrator
- Policy and Authorization Services
- Capital Allocation and Risk Engine
- Trade Lifecycle Manager
- Unified Execution Gateway
- Position, P&L and Allocation Ledgers
- Reconciliation and Audit Services

**Core principle:** AI discovers, analyses and recommends. Deterministic services validate and control. Authorized execution adapters place orders. The Trade Lifecycle Manager manages confirmed positions according to the approved plan and risk policy.

The platform must continue protecting open positions if the LLM provider, agent runtime, conversational interface or a non-critical application component becomes unavailable.

A full **Trading Desk Simulator** is a mandatory core capability of this product, not a separate testing utility. It must reproduce complete trading sessions, realistic market and execution events, all five agents' task coordination, risk decisions, approvals, lifecycle management, operational failures and final reconciliation. Historical replay, accelerated replay, scenario simulation and live shadow mode are specified in Part II of this PRD. Autonomous paper trading and controlled live execution must be gated by simulator-based validation and certification.

### Unified product structure

- **Part I — Autonomous Trading Desk:** Product scope, agent workforce, orchestration, risk, capital, lifecycle, execution, data, user experience, APIs, security and platform requirements.
- **Part II — Trading Desk Simulator:** Simulation modes, market and execution realism, agent coordination, complete trading-day workflow, scenario library, simulator UI, data model, APIs and certification.
- **Part III — Delivery and acceptance:** Implementation roadmap, release gates, acceptance criteria and open decisions.

---

## 2. Product Vision and Objectives

### 2.1 Vision

Build an autonomous trading organisation where a trader defines objectives, capital and risk appetite, and Nivesh coordinates specialised agents to research, plan, execute and manage trades within explicit authorization boundaries.

### 2.2 Business objectives

| Objective | Expected outcome |
|---|---|
| Trading automation | Reduce manual coordination across the trading workflow |
| Opportunity discovery | Systematically identify and rank market opportunities |
| Strategy intelligence | Generate explainable, testable trade plans |
| Risk protection | Enforce trade, strategy and portfolio-level limits |
| Capital efficiency | Allocate capital according to risk, margin and availability |
| Execution discipline | Reduce execution and operational errors |
| Position management | Automate authorized stop, target, trailing and exit rules |
| Transparency | Record every material recommendation and decision |
| Scalability | Support multiple tenants, accounts and strategies |

### 2.3 Success metrics

Measure operational quality and trading performance independently.

| Metric | Definition |
|---|---|
| Signal coverage | Eligible market opportunities evaluated / eligible opportunities |
| Signal precision | Signals meeting a defined outcome / evaluated signals |
| Strategy expectancy | Average net outcome per trade, after costs |
| Risk compliance | Trades within policy / total trades |
| Execution accuracy | Difference between intended and actual execution |
| Reconciliation success | Positions reconciled / positions requiring reconciliation |
| Lifecycle reliability | Correctly processed lifecycle events / total lifecycle events |
| Duplicate order rate | Duplicate orders attributable to the platform |
| Agent reliability | Successful agent tasks / total agent tasks |
| Recovery time | Time to restore a failed workflow or service |
| P&L accuracy | Difference between internal and authoritative execution records |
| Policy violation rate | Unauthorized or out-of-policy actions; target zero |

Do not use returns alone to measure agent quality. Include drawdown, risk-adjusted returns, execution costs, slippage and policy adherence. Do not present backtested or modelled performance as guaranteed future performance.

---

## 3. Scope

### 3.1 In scope

- Multi-agent trading workforce and agent registry
- Central desk orchestration and durable workflows
- Market intelligence and opportunity scanning
- AI-assisted strategy generation
- Equity cash, futures, index options and stock options
- Single-leg and multi-leg options strategies
- Technical, fundamental and derivatives analysis
- Capital allocation and portfolio risk management
- Approval and authorization workflows
- Full Trading Desk Simulator: historical replay, accelerated replay, scenario simulation and live shadow
- Realistic paper trading and execution simulation
- Broker connectivity and controlled live execution
- Agent coordination simulation and workflow replay
- Simulator-based strategy, agent, policy and release certification
- Automated trade lifecycle management
- Real-time P&L and portfolio exposure
- Multi-leg position and leg-level management
- Trade journal and performance analytics
- Agent fleet and infrastructure monitoring
- Multi-tenant architecture
- Security, audit and compliance controls

### 3.2 Out of scope for initial releases

- Unrestricted AI-generated live trading
- Autonomous changes to account risk limits
- Capital transfers or withdrawals
- Unapproved averaging, martingale or loss-recovery schemes
- Autonomous leverage expansion
- Strategy deployment without testing and certification
- Guarantee of profit, prediction accuracy or execution price
- Direct exchange membership or clearing infrastructure

### 3.3 Supported instruments

| Segment | Initial support |
|---|---|
| NSE equity cash | Yes |
| NSE stock futures | Yes |
| NSE index futures | Yes |
| NSE stock options | Yes |
| NSE index options | Yes |
| BSE cash and derivatives | Adapter-dependent, phased |
| ETFs | Yes, subject to data and broker support |
| Currency/commodity derivatives | Future scope |

Instrument eligibility, lot sizes, expiry calendars, tick sizes, price bands and trading sessions must come from versioned exchange/broker reference data, not hard-coded assumptions.

---

## 4. User Personas

| Persona | Primary needs |
|---|---|
| Retail trader | Simple interface, explainable suggestions and controlled automation |
| Active F&O trader | Greeks, OI, payoff, margin and multi-leg execution |
| Positional trader | Trend, entry/exit, holding period and trailing stop |
| Professional trader | Multiple strategies, allocation and portfolio risk |
| Proprietary trading desk | Multiple accounts, strategy-level controls and audit |
| Middle office operator | Approvals, exceptions and reconciliation |
| System administrator | Agent monitoring, broker connectivity and infrastructure health |

---

## 5. Operating Modes and Permissions

The production desk must support four operating modes. The separate simulator provides four simulation modes; simulation modes never grant permission to place live broker orders.

### Production operating modes

| Mode | Behaviour | Order destination |
|---|---|---|
| Research | Analyse markets and generate recommendations | No order |
| Assisted | Generate plans; user approves actions | Approved paper or live adapter |
| Autonomous Paper | Automatically manage simulated trades within policy | Paper engine only |
| Autonomous Live | Execute pre-authorized actions within strict policy | Broker adapter |

### Simulation modes

| Mode | Behaviour | Order destination |
|---|---|---|
| Historical Replay | Replay point-in-time historical sessions | Isolated simulator |
| Accelerated Replay | Replay historical sessions at configurable speed | Isolated simulator |
| Scenario Simulation | Inject market, execution and operational events | Isolated simulator |
| Live Shadow | Analyse live market data and track hypothetical orders | No broker order capability |

The simulator's execution boundary must technically prevent simulated and shadow orders from reaching live broker adapters. See Part II for full requirements.

### 5.1 Configuration hierarchy

Operating mode and limits can be configured at:

- Tenant level
- Trading account level
- Strategy level
- Instrument/segment level
- Individual trade level

The effective policy is the most restrictive applicable policy. A lower-level setting cannot weaken a higher-level hard restriction.

### 5.2 Mode separation

- Paper accounts must never route to a live broker adapter.
- Live mode requires explicit account-owner authorization.
- A mode change must be audited and must not silently migrate open positions.
- Live activation requires completed certification, broker permission checks and required compliance approvals.
- If mode, account or authorization context is ambiguous, execution must fail closed.

---

## 6. Agent Workforce — Functional Requirements

### 6.1 Agent 1: AI Trader — Opportunity Hunter

**Mission:** Identify, evaluate and rank trading opportunities across the eligible market universe.

#### Functional requirements

| ID | Requirement | Priority |
|---|---|---|
| AT-001 | Scan configured equity universes | P0 |
| AT-002 | Scan F&O-eligible stocks | P0 |
| AT-003 | Analyse Nifty and Bank Nifty | P0 |
| AT-004 | Detect breakouts and breakdowns | P0 |
| AT-005 | Identify long buildup and short buildup | P0 |
| AT-006 | Identify short covering and long unwinding | P0 |
| AT-007 | Detect abnormal volume and delivery | P1 |
| AT-008 | Analyse sector rotation | P1 |
| AT-009 | Analyse FII/DII and smart-money signals | P1 |
| AT-010 | Detect unusual options activity | P0 |
| AT-011 | Rank signals using versioned scoring rules | P0 |
| AT-012 | Maintain historical signal performance | P0 |
| AT-013 | Detect and suppress duplicate signals | P0 |
| AT-014 | Track missed opportunities and scanner coverage | P1 |
| AT-015 | Publish structured signal events | P0 |

#### Market coverage

- Nifty 50, Nifty 100, Nifty 200 and Nifty 500
- Configurable liquid equity universe
- F&O stock universe
- Nifty, Bank Nifty and supported indices
- Sectoral indices
- Futures and options contracts
- User-defined watchlists

#### Signal categories

- Trend continuation
- Breakout and breakdown
- Momentum expansion
- Reversal
- Relative-strength leadership
- Long buildup
- Short buildup
- Short covering
- Long unwinding
- Unusual volume/delivery
- Options positioning and volatility opportunities

#### Signal scoring

A configurable 0–100 scoring framework may use:

| Dimension | Illustrative weight |
|---|---:|
| Trend confirmation | 20 |
| Momentum | 15 |
| Volume and delivery | 15 |
| Relative strength | 10 |
| Market structure | 10 |
| Derivatives confirmation | 15 |
| Market regime | 10 |
| Liquidity | 5 |
| **Total** | **100** |

Weights must be configurable, versioned and validated using point-in-time historical data. Missing data must not silently count as positive evidence. A score is not a probability.

#### Signal output schema

```json
{
  "signal_id": "SIG-10251",
  "tenant_id": "TENANT-01",
  "instrument": "RELIANCE",
  "exchange": "NSE",
  "segment": "CASH",
  "direction": "BULLISH",
  "timeframe": "POSITIONAL",
  "signal_score": 82,
  "calibrated_probability": null,
  "entry_zone": {"low": 1490, "high": 1505},
  "invalidation_price": 1460,
  "targets": [1560, 1600],
  "evidence": [
    "TREND_CONFIRMATION",
    "VOLUME_EXPANSION",
    "OI_CONFIRMATION"
  ],
  "data_as_of": "2026-11-05T09:30:00+05:30",
  "model_version": "signal-v1",
  "rule_version": "rules-v1",
  "expires_at": "2026-11-05T15:20:00+05:30"
}
```

The example is illustrative. Production timestamps and values must be sourced from actual system data.

### 6.2 Agent 2: Trading Assistant — Strategist

**Mission:** Convert opportunities and user objectives into structured, explainable trade plans.

#### Functional requirements

- Understand natural-language trading objectives.
- Collect missing capital, risk and holding-period constraints.
- Analyse cash, futures and options alternatives.
- Generate single-leg and multi-leg strategies.
- Compare expected payoff and risk/reward.
- Select expiry and strikes using approved reference data.
- Evaluate Greeks and implied volatility.
- Calculate maximum profit, maximum loss and breakeven.
- Estimate expected move and margin.
- Evaluate liquidity and execution feasibility.
- Recommend entry, stop, targets and exit rules.
- Generate position-sizing proposals.
- Explain why a strategy was selected.
- Create immutable, versioned trade plans.
- Propose amendments when conditions change.

#### Strategy templates

**Equity and futures**

- Long equity
- Short equity, where permitted
- Long futures
- Short futures

**Options**

- Long call
- Long put
- Bull call spread
- Bear put spread
- Bull put spread
- Bear call spread
- Covered call
- Cash-secured put
- Protective put
- Collar
- Iron condor
- Iron butterfly
- Calendar spread
- Diagonal spread

Support up to four legs in the initial strategy builder, with an extensible leg model.

#### Trade Plan mandatory fields

1. Trade thesis and rationale
2. Signal and market context
3. Account and instrument
4. Strategy type
5. Leg-level contract details
6. Entry conditions and order constraints
7. Stop-loss/invalidation conditions
8. Target and partial-exit conditions
9. Maximum loss and profit where defined
10. Breakeven
11. Expected payoff and assumptions
12. Capital and margin requirement
13. Greeks and volatility assumptions
14. Liquidity assessment
15. Holding period and expiry constraints
16. Exit and emergency rules
17. Risk warnings
18. Plan expiry
19. Plan version and model/rule provenance

### 6.3 Agent 3: Risk & Operations — Risk Guardian

**Mission:** Independently validate proposed trades and continuously assess financial and operational risk.

#### Functional requirements

- Calculate trade-level risk.
- Validate capital allocation.
- Validate aggregate portfolio exposure.
- Calculate sector concentration.
- Calculate correlation and directional exposure.
- Calculate options Greeks and stress scenarios.
- Validate margin and available funds.
- Monitor daily loss limits and portfolio drawdown.
- Check liquidity and market impact assumptions.
- Validate expiry and settlement rules.
- Validate market-data freshness.
- Detect risk breaches and recommend risk reduction.
- Block prohibited actions.
- Produce explainable risk reports.

#### Equity risk formulas

For a long position:

`Risk = (Entry Price - Stop Price) × Quantity`

For a short position:

`Risk = (Stop Price - Entry Price) × Quantity`

Illustrative quantity sizing:

`Quantity = floor(Risk Budget / Risk Per Share)`

Final quantity must also respect capital, lot size, liquidity, concentration, margin and policy limits. Include estimated brokerage, taxes, fees, slippage and gap risk in risk estimates where feasible.

#### Options and multi-leg risk

- Calculate combined strategy payoff, not isolated leg risk alone.
- Model expiry payoff and scenario P&L.
- Include premiums, lot sizes, fees and realistic fill assumptions.
- Calculate Delta, Gamma, Theta and Vega at strategy and leg level.
- Stress underlying price, implied volatility, time decay and liquidity.
- Identify undefined or theoretically unlimited loss.
- Apply explicit limits to naked or partially hedged exposure.
- Recalculate risk when one leg fills, is rejected or is externally modified.

#### Portfolio risk measures

- Gross and net exposure
- Open risk and risk-to-stop
- Realized and unrealized P&L
- Sector concentration
- Correlation-adjusted exposure
- Portfolio beta
- Delta, Gamma, Theta and Vega
- Margin utilization and buffer
- Daily loss and peak-to-trough drawdown
- Stress loss under configured scenarios

#### Guardrail hierarchy

1. Trade-level limit
2. Strategy-level limit
3. Instrument-level limit
4. Sector/concentration limit
5. Account-level daily loss limit
6. Portfolio drawdown limit
7. Tenant-level restrictions

A breach of a hard limit cannot be overridden by an AI agent. Emergency risk-reducing actions must follow a separately approved policy.

### 6.4 Agent 4: Middle Office Supervisor

**Mission:** Provide independent authorization, policy enforcement and operational oversight.

#### Functional requirements

- Review proposed trade plans.
- Verify risk assessment completion.
- Validate approval requirements.
- Validate execution mode and account.
- Validate strategy eligibility.
- Check authorization scope and expiry.
- Verify capital reservation.
- Review exceptions and deviations.
- Record approval/rejection reasons.
- Monitor policy violations.
- Escalate material risk events.
- Maintain immutable audit references.

#### Decision statuses

| Status | Meaning |
|---|---|
| APPROVED | Mandatory checks passed and authority is sufficient |
| REJECTED | One or more mandatory rules failed |
| NEEDS_HUMAN_APPROVAL | Additional authorization required |
| NEEDS_REVISION | Plan must be corrected and resubmitted |
| SUSPENDED | Trading activity temporarily blocked |

An approval must be bound to the exact plan version, account, quantity, strategy, execution mode and permitted action scope. An approval for one version must not authorize a materially changed version.

### 6.5 Agent 5: Tech Support & Reliability

**Mission:** Maintain availability and integrity of trading infrastructure.

#### Functional requirements

- Monitor exchange and vendor data feeds.
- Monitor broker API and WebSocket connectivity.
- Monitor order acknowledgements and execution latency.
- Monitor databases, Redis and message queues.
- Monitor ingestion and scheduled jobs.
- Detect stale or missing market data.
- Detect missing broker callbacks.
- Monitor failed workflows and dead-letter queues.
- Initiate approved safe recovery procedures.
- Escalate unresolved incidents.
- Maintain incident history and recovery evidence.

The agent may restart approved non-trading processes. It cannot alter trading policies, create orders or disable protective controls.

---

## 7. Desk Orchestrator

The Desk Orchestrator is the central workflow coordinator. It is a deterministic workflow service, not an unrestricted LLM agent.

### Responsibilities

- Register and manage agents.
- Assign work and maintain dependencies.
- Persist workflow state.
- Manage timeouts and bounded retries.
- Publish and consume events.
- Enforce agent permissions.
- Maintain correlation and causation IDs.
- Prevent duplicate workflow execution.
- Support recovery after service restart.
- Manage human approval pauses.
- Maintain task and decision history.

### 7.1 Trade proposal workflow

| Step | Agent/service | Input | Output |
|---|---|---|---|
| 1 | AI Trader | Market data | Signal |
| 2 | Trading Assistant | Signal and user constraints | Trade proposal |
| 3 | Risk & Ops | Proposal and portfolio state | Risk report |
| 4 | Trading Assistant | Risk report | Revised plan, if necessary |
| 5 | Middle Office | Validated plan | Authorization decision |
| 6 | Capital Allocator | Authorized plan | Capital reservation |
| 7 | Execution Controller | Authorized plan and reservation | Execution intent |
| 8 | Execution Adapter | Execution intent | Order/fill events |
| 9 | Lifecycle Manager | Confirmed fills | Active position |
| 10 | Risk & Ops | Position and market state | Risk events |
| 11 | Lifecycle Manager | Events and approved policy | Position action |
| 12 | Reconciliation | Broker/paper state | Reconciled position |
| 13 | Trade Journal | Final trade record | Performance record |

The workflow must support rejection, bounded retries, human approval, partial fills, failed execution, cancellation and reconciliation exceptions.

---

## 8. Trade Lifecycle Manager

### 8.1 Purpose

The Trade Lifecycle Manager (TLM) owns the operational lifecycle of every confirmed position. It is a persistent deterministic service, not a conversational AI agent.

It manages a position against the approved trade plan and current risk policy. It must not independently create a new thesis or increase exposure.

### 8.2 Lifecycle states

- DRAFT
- APPROVED
- READY_TO_EXECUTE
- ORDER_SUBMITTED
- PARTIALLY_FILLED
- FILLED
- ACTIVE_POSITION
- RISK_MANAGEMENT
- PARTIAL_EXIT
- EXIT_PENDING
- CLOSED
- RECONCILIATION_REQUIRED
- SETTLED
- ARCHIVED
- REJECTED
- CANCELLED
- EXPIRED
- SUSPENDED
- RISK_BREACH
- EXECUTION_ERROR

State transitions must be explicit, validated and persisted. A submitted order is not a filled position. A position is closed only after confirmed fills and reconciliation establish zero remaining quantity.

### 8.3 Activation

Activate TLM only after receiving confirmed fill events. For partial fills, create or update the position with actual filled quantity and average fill price. Do not assume requested quantity equals filled quantity.

On activation:

1. Validate account, tenant and execution mode.
2. Load exact approved plan version.
3. Load authorization scope.
4. Register actual fills.
5. Reserve/adjust capital and risk ledger.
6. Establish protective order state.
7. Start market and risk subscriptions.
8. Publish POSITION_ACTIVATED.
9. Start periodic reconciliation.

### 8.4 Continuous monitoring

Monitor:

- Last traded price and timestamp
- Average entry price
- Filled and remaining quantity
- Unrealized and realized P&L
- Stop and target levels
- Trailing-stop state
- Capital and margin
- Strategy invalidation conditions
- Market regime and volatility
- OI and options chain where relevant
- Greeks at strategy and leg level
- Expiry and holding-period constraints
- Broker order and position state
- Data freshness and connectivity

Use event-driven processing for price, order, fill and risk events. Scheduled checks are supplementary, not a replacement for execution-critical event handling.

### 8.5 Action policy

| Condition | Candidate action | Authority |
|---|---|---|
| Stop triggered | Exit remaining quantity | Pre-authorized policy |
| Target 1 reached | Book configured partial quantity | Pre-authorized policy |
| Target 2 reached | Exit configured remaining quantity | Pre-authorized policy |
| Favourable move | Tighten trailing stop | Pre-authorized formula |
| Thesis invalidated | Recommend exit/review | Approval per policy |
| OI structure changes | Reassess strategy | Usually recommendation |
| Volatility shock | Recalculate risk and stress | Automatic risk control |
| Daily loss limit | Block new risk and apply policy | Automatic |
| Portfolio drawdown limit | Suspend new trading and escalate | Automatic suspension |
| Manual exit | Submit controlled exit | User-authorized |

The manager may reduce risk within pre-authorized limits. It must not widen the original stop, increase quantity, increase leverage or otherwise increase approved downside risk without fresh authorization.

### 8.6 Partial fills and partial exits

- Track requested, filled, cancelled and remaining quantity separately.
- Maintain fill-level average price.
- Recalculate risk after every fill.
- Reconcile protective orders with remaining position quantity.
- Prevent duplicate partial exits.
- Do not assume a target order has filled because the market touched the target.
- Handle gaps, rejected orders and insufficient liquidity.
- For multi-leg strategies, manage strategy-level and leg-level states.

### 8.7 Trade plan amendments

Every amendment must include:

- Original plan version
- Proposed new version
- Reason and evidence
- Changed fields
- Risk impact before and after
- Capital impact
- Proposer identity/agent
- Required approver
- Approval decision
- Effective time

The original approved plan remains immutable. A new version becomes effective only after the required approval.

### 8.8 Recovery

On restart, TLM must recover active positions, orders, protective instructions, pending actions and last processed event offsets from durable state. It must reconcile with the paper engine or broker before resuming actions. It must not blindly replay an order command.

---

## 9. Capital Allocation Engine

### 9.1 Objectives

- Allocate capital within user-defined risk appetite.
- Avoid over-allocation and duplicate reservations.
- Consider margin, liquidity and concentration.
- Reserve capital before order submission.
- Adjust reservations to actual fills.
- Release capital only after confirmed exits and reconciliation.
- Prevent concurrent strategies from spending the same available funds.

### 9.2 Capital model

Maintain separate measures:

- Net liquidation/equity value
- Available cash/funds
- Used margin
- Reserved capital
- Deployed notional
- Available buying power
- Open risk
- Realized and unrealized P&L
- Pending order commitment

Do not treat deployed notional, margin and maximum loss as interchangeable.

### 9.3 Allocation controls

Support configurable limits for:

- Maximum capital deployment
- Maximum risk per trade
- Maximum aggregate open risk
- Maximum allocation per strategy
- Maximum allocation per instrument
- Maximum sector exposure
- Maximum correlated exposure
- Maximum margin utilization
- Minimum margin buffer
- Maximum daily loss
- Maximum portfolio drawdown

### 9.4 Atomic reservation

Capital reservation must be transactional and concurrency-safe. Two simultaneous trade proposals must not reserve the same available capital. Reservation must have an expiry and release policy. After fills, convert the reservation to actual deployed/used capital and update risk.

### 9.5 Allocation algorithms

Initial release should support deterministic methods:

- Fixed amount
- Fixed percentage of account equity
- Fixed risk per trade
- Volatility-adjusted risk budget
- Maximum-risk constrained sizing
- Equal-risk allocation across approved strategies

Advanced portfolio optimizers may be introduced later, but must not bypass hard limits. Any optimizer output is a proposal until validated by the policy engine.

---

## 10. Policy and Authorization Control Plane

### 10.1 Policy model

Policies must be versioned and scoped to tenant, account, strategy, segment and execution mode.

Policy fields include:

- Allowed instruments and strategies
- Allowed trading sessions
- Maximum order quantity/notional
- Maximum trade risk
- Maximum daily loss
- Maximum open risk
- Maximum margin utilization
- Sector and concentration limits
- Allowed order types
- Price collars and slippage limits
- Allowed autonomous actions
- Human approval thresholds
- Expiry and overnight-holding rules
- Emergency exit permissions

### 10.2 Authorization model

Use role-based access control plus scoped action permissions. Suggested roles:

- Tenant Owner
- Account Owner
- Trader
- Risk Officer
- Middle Office Approver
- Operations Administrator
- Read-only Auditor
- Platform Administrator

Authorization must be checked at execution time, not only at plan approval time.

### 10.3 Approval binding

An approval token/record must bind:

- Tenant and account
- Trade ID and plan version
- Instrument and strategy
- Maximum quantity and notional
- Maximum permitted risk
- Execution mode
- Allowed action types
- Expiration time
- Approver and approval evidence

A changed plan, expired approval, changed account mode or changed risk policy requires revalidation.

### 10.4 Emergency controls

Provide separate controls:

- Stop new entries
- Suspend autonomous strategy generation
- Suspend automated modifications
- Cancel eligible pending entry orders
- Suspend a strategy
- Suspend an account
- Activate controlled risk-reducing exits
- Disable a broker adapter

A kill switch must not blindly cancel protective stop orders and leave open positions unprotected. Emergency actions must be designed per broker capability and position state.

---

## 11. Unified Execution Gateway

### 11.1 Architecture

The lifecycle manager and orchestrator call a common execution interface. They do not call broker-specific APIs directly.

Adapters:

- Paper Trading Adapter
- Broker Adapter interface
- Individual broker implementations

### 11.2 Common interface

```python
class ExecutionAdapter:
    async def place_order(self, order, idempotency_key): ...
    async def modify_order(self, order_id, changes, idempotency_key): ...
    async def cancel_order(self, order_id, idempotency_key): ...
    async def get_order_status(self, order_id): ...
    async def get_positions(self, account_id): ...
    async def get_funds(self, account_id): ...
    async def get_fills(self, order_id): ...
    async def get_margin(self, account_id): ...
    async def health_check(self): ...
```

The interface is illustrative; implementation must account for each broker's actual API semantics, rate limits, authentication and supported order types.

### 11.3 Order lifecycle

- CREATED
- VALIDATED
- SUBMITTED
- ACKNOWLEDGED
- OPEN
- PARTIALLY_FILLED
- FILLED
- MODIFY_PENDING
- CANCEL_PENDING
- CANCELLED
- REJECTED
- EXPIRED
- UNKNOWN / RECONCILIATION_REQUIRED

An unknown broker response must not be treated as a failed order and retried blindly. Query broker state using the broker order reference and reconcile before any retry.

### 11.4 Execution controls

Before every order:

1. Authenticate tenant, account and caller.
2. Verify execution mode.
3. Verify current approval and plan version.
4. Verify trade state and remaining quantity.
5. Validate available funds and margin.
6. Validate risk and concentration limits.
7. Validate instrument and market status.
8. Validate quantity, lot size, tick size and price bands.
9. Validate price collar and slippage constraints.
10. Check idempotency key and duplicate intent.
11. Persist execution intent.
12. Submit order and process broker response.
13. Reconcile order and fill events.

### 11.5 Paper trading realism

The paper engine must support:

- Bid/ask spread
- Market and limit order behaviour
- Partial fills
- Queue/volume-aware fill assumptions where data permits
- Slippage
- Latency
- Rejections
- Cancellations and modifications
- Brokerage, taxes and transaction charges
- Margin and collateral simulation
- Expiry and settlement handling
- Gap and illiquidity scenarios

Paper fills must be labelled simulated and must never be presented as broker-confirmed fills.

---

## 12. Trade Journal, P&L and Performance Intelligence

### 12.1 Trade journal

Capture the complete chain:

Signal → Proposal → Plan versions → Risk assessments → Approvals → Orders → Fills → Position events → Amendments → Exits → Reconciliation → Final P&L.

### 12.2 P&L requirements

Show separately:

- Gross realized P&L
- Gross unrealized P&L
- Brokerage and statutory charges
- Other fees
- Slippage estimate/actual where measurable
- Net realized P&L
- Net unrealized P&L
- Strategy-level P&L
- Account-level P&L
- Daily and cumulative P&L

For live accounts, broker-confirmed fills and applicable broker statements are authoritative for execution. The internal ledger must reconcile differences and retain the source.

### 12.3 Performance analytics

- Win rate
- Average win and average loss
- Expectancy
- Profit factor
- Maximum drawdown
- Risk/reward realized
- Return on allocated capital
- Return on risk
- Holding period
- MAE and MFE
- Slippage
- Charges as percentage of gross profit
- Strategy and instrument breakdown
- Signal-to-trade conversion
- Missed/expired signal analysis
- Plan adherence score

### 12.4 Learning loop

Performance research may recommend changes to scoring, strategy parameters or allocation methods. It must not directly change live production rules. Changes require versioning, historical validation, out-of-sample testing, paper certification and explicit deployment authorization.

---

## 13. Agent Communication and Event Architecture

### 13.1 Communication principles

- Structured messages, not free-form chat, are authoritative.
- Every event has tenant, account where applicable, correlation ID, causation ID, event ID and timestamp.
- Events are versioned.
- Consumers are idempotent.
- Sensitive tenant data is not broadcast to unrelated agents or tenants.
- Agent messages and tool calls are auditable.
- Agent output is untrusted until validated by deterministic services.

### 13.2 Core event catalogue

**Market and signal**
- MARKET_DATA_UPDATED
- MARKET_DATA_STALE
- SIGNAL_DETECTED
- SIGNAL_UPDATED
- SIGNAL_EXPIRED

**Strategy and approval**
- TRADE_PLAN_CREATED
- TRADE_PLAN_REVISED
- RISK_ASSESSMENT_COMPLETED
- CAPITAL_RESERVED
- APPROVAL_REQUESTED
- APPROVAL_GRANTED
- APPROVAL_REJECTED
- APPROVAL_EXPIRED

**Execution**
- EXECUTION_INTENT_CREATED
- ORDER_SUBMITTED
- ORDER_ACKNOWLEDGED
- ORDER_PARTIALLY_FILLED
- ORDER_FILLED
- ORDER_REJECTED
- ORDER_CANCELLED
- ORDER_UNKNOWN

**Lifecycle**
- POSITION_ACTIVATED
- STOP_TRIGGERED
- TARGET_TRIGGERED
- TRAILING_STOP_UPDATED
- PARTIAL_EXIT_REQUESTED
- POSITION_EXIT_REQUESTED
- POSITION_CLOSED
- POSITION_SUSPENDED
- RISK_LIMIT_BREACHED

**Operations**
- BROKER_DISCONNECTED
- BROKER_RECONNECTED
- RECONCILIATION_MISMATCH
- AGENT_UNHEALTHY
- WORKFLOW_FAILED
- RECOVERY_STARTED
- RECOVERY_COMPLETED

### 13.3 Delivery semantics

Assume at-least-once event delivery. Consumers must be idempotent. Use transactional outbox/inbox patterns where needed. Do not assume exactly-once delivery across brokers, queues and databases. Order submission must have a durable intent, idempotency key and reconciliation procedure.

---

## 14. Data Requirements and Integrations

### 14.1 Market data

Required data:

- OHLCV and intraday bars
- Tick/quote data where licensed and available
- Bid/ask and market depth where available
- Corporate actions
- Index constituents and weights
- Sectoral indices
- Futures prices and OI
- Options chain and OI
- IV and Greeks
- Delivery quantity and percentage
- FII/DII data
- Corporate announcements and results
- Instrument master, lot size and expiry calendar

### 14.2 Data quality controls

Every data record used for a decision should have:

- Source
- Exchange/vendor timestamp
- Ingestion timestamp
- Instrument identifier
- Data version/schema
- Freshness status
- Validation status

Block new risk-increasing orders when mandatory data is stale, inconsistent or unavailable. Existing positions must continue under their approved protective policy using available trusted data and broker-side protective orders where supported.

### 14.3 Broker integration

Broker adapter requirements:

- Secure authentication and token lifecycle
- Account and funds retrieval
- Order placement, modification and cancellation
- Order book and trade book
- Positions and holdings
- Margin calculation
- WebSocket order updates
- Rate-limit handling
- Reconnection and token expiry handling
- Broker instrument mapping
- Reconciliation
- Broker API capability registry

Broker support is adapter-specific. Do not assume identical semantics across brokers.

---

## 15. User Experience and Screens

The Autonomous Trading Desk is a dedicated Nivesh V5 module, not merely a chatbot.

### 15.1 Main navigation

1. Desk Overview
2. Agent Command Centre
3. Market Intelligence
4. Opportunity Scanner
5. Strategy Workbench
6. Approval Queue
7. Active Trade Management
8. Real-Time P&L
9. Capital & Risk
10. Trade Journal
11. Agent Fleet
12. System Reliability
13. Policies & Permissions

### 15.2 Desk Overview

Display:

- Current operating mode
- Market session status
- Agents healthy / degraded / offline
- Active paper and live trades separately
- Pending approvals
- Open orders
- Capital deployed and available
- Open risk and margin utilization
- Realized and unrealized P&L
- Critical exceptions
- Broker and data-feed status
- Recent agent activity

### 15.3 Agent Command Centre

For each agent show:

- Status
- Current task
- Last heartbeat
- Task queue depth
- Last successful execution
- Recent decisions
- Errors and retries
- Permissions and tool access
- Model and prompt/config version
- Human escalation requirements

Agent statuses: IDLE, BUSY, SCALING, DEGRADED, MAINTENANCE, QUARANTINED, OFFLINE.

### 15.4 Market Intelligence

- Index and sector overview
- Market breadth
- Top gainers and losers
- Relative strength
- Smart-money indicators
- FII/DII flows
- Futures buildup
- Options market summary
- Volatility regime
- News and event calendar
- Data freshness indicators

### 15.5 Opportunity Scanner

- Live ranked signals
- Score and calibrated probability separately
- Direction and timeframe
- Signal evidence
- Entry and invalidation
- Targets
- Liquidity
- OI/volume confirmation
- Signal age and expiry
- Strategy generation action
- Signal history

### 15.6 Strategy Workbench

- Plain-English strategy builder
- Strategy templates
- Leg builder
- Payoff graph
- Greeks
- Breakeven
- Max profit/loss
- Margin estimate
- Risk/reward
- Scenario analysis
- Backtest results and assumptions
- Plan version comparison
- Submit for risk validation

### 15.7 Approval Queue

- Proposed trade
- Strategy and rationale
- Capital allocation
- Risk report
- Portfolio impact
- Execution mode
- Required approvals
- Policy checks
- Approve, reject or request revision
- Approval expiry
- Audit history

### 15.8 Active Trade Management

For every trade:

- Trade and plan ID/version
- Instrument and strategy
- Execution mode
- Entry and average fill
- Current price
- Filled and remaining quantities
- Open orders
- Stop-loss and targets
- Trailing-stop status
- Realized/unrealized P&L
- Remaining risk
- Capital and margin
- Greeks and OI context for derivatives
- Lifecycle state
- Last risk evaluation
- Recommended action
- Approval status
- Event timeline

Support consolidated charts across positions and individual charts with entry, fills, stop, targets and exit markers. Distinguish actual fills from theoretical trigger prices.

### 15.9 Real-Time P&L

- Account and portfolio consolidated P&L
- Paper/live separation and optional combined view
- Position-level P&L
- Strategy-level P&L
- Intraday P&L chart
- Charges and slippage
- Realized/unrealized split
- Margin and available funds
- Trade lifecycle markers
- Data freshness and reconciliation state

### 15.10 Middle Office Dashboard

- Tenant/account overview
- Agent health
- Active trades
- Pending approvals
- Risk breaches
- Capital utilization
- Broker connectivity
- Reconciliation exceptions
- Recent activity
- Full workflow replay
- Audit search

### 15.11 Interaction design

Use a mobile-first, low-cognitive-load design. Prioritise critical risks and actions without hiding details. Every automated action should show what happened, why it happened, which policy authorized it and what position quantity was affected.

---

## 16. Database Schema

Use PostgreSQL as the transactional system of record. Suggested logical tables:

### 16.1 Tenancy and configuration

- tenants
- users
- roles
- permissions
- user_role_assignments
- trading_accounts
- account_connections
- execution_modes
- risk_policies
- risk_policy_versions
- strategy_templates
- agent_registry
- agent_permissions

### 16.2 Signals and strategy plans

- market_signals
- signal_evidence
- signal_scores
- strategy_proposals
- trade_plans
- trade_plan_versions
- trade_plan_legs
- trade_plan_conditions
- trade_plan_amendments

### 16.3 Risk and capital

- risk_assessments
- risk_snapshots
- portfolio_risk_snapshots
- capital_allocations
- capital_reservations
- capital_ledger_entries
- margin_snapshots
- exposure_snapshots

### 16.4 Approval and execution

- approval_requests
- approval_decisions
- authorization_grants
- execution_intents
- trade_orders
- trade_fills
- broker_order_mappings
- broker_positions_snapshots
- execution_reconciliation

### 16.5 Lifecycle and journal

- trade_positions
- trade_position_legs
- trade_lifecycle_states
- trade_lifecycle_events
- trade_action_proposals
- trade_action_approvals
- trade_exit_records
- trade_journal_entries
- trade_performance_metrics

### 16.6 Agent operations and audit

- agent_tasks
- agent_task_events
- agent_messages
- workflow_instances
- workflow_steps
- outbox_events
- inbox_events
- audit_logs
- system_incidents
- health_checks
- model_versions
- prompt_versions

### 16.7 Key data rules

- Every tenant-owned row must carry tenant_id.
- Use account_id where account-level segregation applies.
- Enforce tenant-scoped access in application services and PostgreSQL row-level security where appropriate.
- Use immutable/versioned records for plans, policies and approvals.
- Store timestamps in UTC; render in Asia/Kolkata for Indian trading users.
- Store exchange timestamps and ingestion timestamps separately.
- Use decimal/numeric types for money, prices and quantities where precision matters; do not use binary floating-point for ledger values.
- Keep raw broker responses with appropriate redaction and retention controls.
- Define indexes, partitioning and retention by query volume and regulatory requirements.

---

## 17. API Contracts

All endpoints require authentication, tenant scoping, authorization and request validation. Use versioned APIs and idempotency keys for mutating execution requests.

### 17.1 Desk and agent APIs

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/desk/status` | Desk health and mode |
| POST | `/api/v1/desk/workflows` | Start a desk workflow |
| GET | `/api/v1/desk/workflows/{id}` | Workflow state |
| POST | `/api/v1/agents/{id}/tasks` | Assign permitted task |
| GET | `/api/v1/agents` | Agent registry and health |
| GET | `/api/v1/agents/{id}/activity` | Agent activity |

### 17.2 Signals and strategies

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/signals` | Search signals |
| GET | `/api/v1/signals/{id}` | Signal detail |
| POST | `/api/v1/strategies/generate` | Generate proposal |
| POST | `/api/v1/trade-plans` | Create plan |
| GET | `/api/v1/trade-plans/{id}` | Retrieve plan |
| POST | `/api/v1/trade-plans/{id}/validate` | Run validation |
| POST | `/api/v1/trade-plans/{id}/amendments` | Propose amendment |

### 17.3 Risk, allocation and approvals

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/risk/assessments` | Assess trade risk |
| GET | `/api/v1/risk/portfolio/{account_id}` | Portfolio risk |
| POST | `/api/v1/capital/reservations` | Reserve capital |
| POST | `/api/v1/approvals` | Request approval |
| POST | `/api/v1/approvals/{id}/decision` | Record approval decision |

### 17.4 Execution and lifecycle

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/execution/intents` | Create validated execution intent |
| GET | `/api/v1/execution/orders/{id}` | Order status |
| POST | `/api/v1/execution/orders/{id}/cancel` | Cancel order |
| POST | `/api/v1/lifecycle/activate` | Activate after confirmed fill |
| GET | `/api/v1/lifecycle/{trade_id}` | Current lifecycle |
| GET | `/api/v1/lifecycle/{trade_id}/events` | Lifecycle event history |
| POST | `/api/v1/lifecycle/{trade_id}/evaluate` | Evaluate current state |
| POST | `/api/v1/lifecycle/{trade_id}/suspend` | Suspend management |
| POST | `/api/v1/lifecycle/{trade_id}/close` | Initiate controlled closure |
| POST | `/api/v1/reconciliation/run` | Start reconciliation |

### 17.5 API execution response example

```json
{
  "execution_intent_id": "EXE-1001",
  "trade_id": "NIDP-1025",
  "plan_version": 3,
  "account_id": "ACC-001",
  "execution_mode": "PAPER",
  "status": "ACCEPTED",
  "authorization_id": "AUTH-5001",
  "idempotency_key": "trade-1025-entry-v3",
  "created_at": "2026-11-05T09:35:00Z"
}
```

This is an illustrative contract, not an actual execution response.

---

## 18. Security, Multi-Tenancy and Compliance

### 18.1 Tenant isolation

- Strict tenant and account data separation.
- Tenant-scoped API authorization.
- Row-level security where applicable.
- Isolated agent context and memory.
- No cross-tenant message or retrieval access.
- Tenant-specific encryption and secrets controls where required.
- Separate broker credentials per account.
- Tenant-aware audit and reporting.

### 18.2 Secrets and credentials

- Never place broker tokens in prompts, agent memory or logs.
- Use a managed secrets vault.
- Encrypt credentials in transit and at rest.
- Rotate credentials and support revocation.
- Apply least-privilege access.
- Redact tokens and personal information from logs.

### 18.3 Audit

Record:

- User actions
- Agent recommendations
- Model and prompt versions
- Tool invocations
- Risk calculations and policy versions
- Approval decisions
- Execution intents
- Broker requests and responses
- Fills and modifications
- Lifecycle transitions
- Reconciliation results
- Administrative changes

Audit records must be tamper-evident, access-controlled and retained according to applicable legal and regulatory requirements.

### 18.4 Regulatory workstream

Before live launch, obtain qualified legal/compliance review for the actual business model, users, distribution and execution arrangements. Assess applicability of SEBI requirements, investment adviser/research analyst rules, algorithmic trading requirements and exchange/broker procedures, data licensing, privacy obligations, cybersecurity and record retention. Product disclaimers do not replace required registration, authorization or compliance.

The platform must support configurable restrictions, disclosures, consent, suitability/appropriateness workflows where applicable, complaint handling and required recordkeeping. Do not assume that calling a feature AI-assisted or user-authorized removes regulatory obligations.

---

## 19. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Availability | Define tiered SLOs for UI, market data, lifecycle and execution components |
| Latency | Measure market-event-to-decision and decision-to-order latency; set targets per strategy |
| Durability | No loss of accepted execution intents, fills or critical lifecycle events |
| Consistency | Transactional ledger and idempotent event processing |
| Recovery | Recover workflows and reconcile external state after restart |
| Scalability | Horizontal scaling for scanners, agents and event consumers |
| Security | Encryption, least privilege, secrets management and audit |
| Observability | Metrics, logs, traces and event correlation |
| Explainability | Every decision linked to inputs, rules, versions and evidence |
| Maintainability | Versioned contracts, modular services and automated tests |
| Accessibility | Responsive, keyboard-accessible dashboard |
| Time handling | UTC persistence and exchange-local session calendars |

Execution and risk-control services require stricter reliability targets than conversational or research components. Set measurable service-level objectives during technical design and validate them under load and fault injection.

---

## 20. Failure Handling and Resilience

### 20.1 Required scenarios

| Failure | Required behaviour |
|---|---|
| LLM provider unavailable | Stop new AI-dependent proposals; existing deterministic lifecycle continues |
| Agent timeout | Bounded retry or escalation; no duplicate side effects |
| Market data stale | Block new risk-increasing orders; alert and follow existing-position safety policy |
| Broker disconnected | Mark state uncertain, reconnect and reconcile; do not blindly resubmit |
| Order acknowledgement missing | Query broker by known references and reconcile |
| Partial fill | Update actual quantity and risk; manage residual order |
| Protective order rejected | Critical alert; execute pre-authorized fallback or escalate |
| Database unavailable | Do not accept new execution intents; preserve external protection and recover safely |
| Queue unavailable | Use durable outbox and backpressure; do not lose critical events |
| Reconciliation mismatch | Freeze affected risk-increasing actions and investigate |
| Agent compromised/unhealthy | Quarantine agent permissions and continue safe deterministic controls |
| Clock/data mismatch | Reject invalid event ordering and reconcile timestamps |

### 20.2 Fail-safe principles

- Fail closed for new risk-increasing actions.
- Do not assume an unknown order failed.
- Do not cancel protective orders indiscriminately.
- Preserve broker-side protection where supported.
- Reconcile external broker state before resuming.
- Escalate unresolved exposure.
- Maintain an operator-visible incident timeline.

---

## 21. Testing and Certification

### 21.1 Unit testing

- Risk formulas
- Quantity sizing
- Capital reservation
- Policy decisions
- State transitions
- Idempotency
- P&L and charges
- Greeks and payoff calculations
- Expiry and lot-size logic

### 21.2 Integration testing

- Agent-to-orchestrator contracts
- Event delivery and retries
- Database transactions
- Paper adapter
- Broker sandbox/mock adapter
- Approval service
- Reconciliation service
- WebSocket events

### 21.3 Historical replay

Replay point-in-time market data and preserve:

- Original data timestamps
- Signal/model versions
- Strategy decisions
- Risk calculations
- Execution assumptions
- Transaction costs
- Corporate actions
- Expiry rules

Prevent look-ahead bias and survivorship bias. Separate development, validation and sealed test periods.

### 21.4 Paper certification

A strategy must satisfy predefined criteria before live eligibility:

- Minimum sample size
- Out-of-sample evaluation
- Positive or otherwise explicitly justified net expectancy
- Drawdown within approved limits
- Stress and gap testing
- Execution-cost sensitivity
- Stable results across relevant market regimes
- No unresolved critical software defects
- Reconciliation correctness
- Risk-policy compliance
- Human sign-off

Thresholds must be defined by strategy class and risk appetite; do not use one universal sample-size or return threshold for all strategies.

### 21.5 Fault injection

Test:

- Broker disconnect during entry
- Broker disconnect during exit
- Duplicate callbacks
- Delayed fills
- Partial multi-leg fills
- Rejected protective orders
- Market-data outage
- Database failover
- Queue backlog
- Agent crash
- LLM timeout
- Clock skew
- Reconciliation mismatch
- Kill-switch activation

### 21.6 Live certification gate

Live trading must remain disabled until:

1. Broker adapter is certified.
2. Authorization and account binding are tested.
3. Policy engine is independently validated.
4. Lifecycle recovery is proven.
5. Reconciliation passes.
6. Emergency controls are tested.
7. Regulatory and compliance review is complete.
8. Account owner explicitly enables live permissions.

---

## 22. Implementation Roadmap

### Phase 0 — Foundation

- Finalise product policies and operating model.
- Define event contracts and schemas.
- Establish tenant/account model.
- Create agent registry and permission framework.
- Create instrument master and data-quality contracts.
- Define risk-policy versioning.

**Exit criteria:** Architecture decisions, threat model, schemas and policy contracts approved.

### Phase 1 — Agent Orchestration and Research

- Desk Orchestrator
- Agent registry and task management
- AI Trader scanner
- Trading Assistant strategy generation
- Shared trade context
- Event bus and audit
- Research-only UI
- Simulator foundation: isolated simulation IDs, clock, event timeline and agent task trace

**Exit criteria:** Agents collaborate on a signal-to-proposal workflow with traceable outputs and no order execution; a simulation run can be created and replayed at workflow level.

### Phase 2 — Risk, Approval and Paper Execution

- Risk Engine
- Capital Allocator
- Policy and Authorization
- Middle Office dashboard
- Paper Execution Adapter
- Order and fill ledger
- Basic Trade Journal
- Historical and accelerated replay
- Realistic fill, slippage, latency and fee assumptions

**Exit criteria:** A validated and approved proposal can be executed in an isolated simulation with correct capital reservation, simulated fills and audit trail.

### Phase 3 — Autonomous Lifecycle and Full Trading-Day Simulation

- Trade Lifecycle Manager
- Real-time position monitoring
- Stop, target and trailing policies
- Partial exits
- Multi-leg position management
- Real-time P&L
- Paper reconciliation
- Agent activity timeline and handoff trace
- Scenario injection and fault simulation
- Pause, resume, checkpoint and deterministic replay
- Simulation reports and run comparison

**Exit criteria:** All five agents coordinate through a complete simulated trading day; positions are autonomously managed from confirmed entry to reconciled closure, including injected failures and risk events.

### Phase 4 — Broker Connectivity, Live Shadow and Controlled Live

- Broker adapters
- Live account permissioning
- Broker order and fill reconciliation
- Live kill switch and emergency policies
- Live market-data shadow mode
- Compare shadow decisions with subsequent market outcomes
- Operational certification
- Compliance sign-off

**Exit criteria:** Live shadow and broker adapter tests pass; limited, explicitly authorized live trading passes strategy, execution, safety, recovery and compliance certification.

### Phase 5 — Optimisation and Scale

- Advanced portfolio allocation
- Correlation-aware risk budgets
- Strategy portfolio management
- Advanced event and anomaly detection
- Multi-account desk operations
- Performance-based strategy research
- Additional broker and market integrations

---

## 23. MVP Acceptance Criteria

The MVP is complete when all the following are demonstrated:

1. The AI Trader detects and publishes a valid, timestamped signal.
2. Trading Assistant creates a structured strategy plan.
3. Risk & Ops independently validates the plan.
4. Capital is reserved atomically.
5. Middle Office records an approval tied to the exact plan version.
6. The execution gateway routes only to the configured paper adapter.
7. The paper engine produces realistic order and fill events.
8. The lifecycle manager activates only from confirmed fills.
9. Stop-loss, target and trailing policies work according to the approved plan.
10. Partial fills and partial exits update remaining quantity correctly.
11. The risk engine recalculates exposure after each material event.
12. Duplicate events cannot create duplicate orders.
13. The system recovers from a restart and reconciles state.
14. The final P&L includes configured costs.
15. The trade journal contains the full decision and execution history.
16. The Middle Office dashboard can replay the workflow.
17. A tenant cannot access another tenant's data.
18. The system blocks any action that lacks valid authorization.
19. An LLM outage does not disable deterministic management of existing positions.
20. A historical session can be replayed without future-data leakage.
21. All five agents complete their required tasks and handoffs in a simulated trading-day workflow.
22. Scenario injections cover market gaps, volatility shocks, partial fills, order rejections, stale data and service failures.
23. Simulation records are technically isolated from live account records and cannot route to a live broker.
24. Simulation can be paused, resumed, checkpointed and replayed with traceable event ordering.
25. Agent, model, prompt, policy and execution-profile versions are recorded for every run.
26. Simulation results disclose data coverage, fill assumptions and other limitations.
27. All critical simulator and platform fault-injection tests pass.

---

## 24. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| AI hallucination | Structured output validation and deterministic policy checks |
| Overfitted strategies | Point-in-time testing, sealed samples and paper certification |
| False signal confidence | Calibrate probability separately from score |
| Duplicate orders | Idempotency, durable intent and reconciliation |
| Broker API inconsistency | Broker-specific adapters and capability registry |
| Partial multi-leg execution | Leg-level state and emergency exposure policy |
| Stale data | Freshness gates and source timestamps |
| Capital over-allocation | Atomic reservations and transactional ledger |
| Agent permission escalation | Least privilege and server-side authorization |
| LLM outage | Independent deterministic lifecycle |
| Incorrect P&L | Fill-based ledger and broker reconciliation |
| Tenant leakage | Tenant isolation, RLS and access tests |
| Regulatory non-compliance | Pre-launch legal/compliance review and configurable controls |

---

## 25. Key Architectural Decisions

| Decision | Recommendation |
|---|---|
| Agent orchestration | LangGraph or custom orchestrator for agent reasoning; durable workflow engine for execution workflows |
| Agent runtime | Python and FastAPI |
| Durable workflows | Temporal or equivalent |
| Event messaging | RabbitMQ initially; Kafka for higher-volume streams |
| Transactional database | PostgreSQL |
| Cache | Redis |
| Quantitative analytics | NumPy, Pandas, SciPy |
| Options analytics | QuantLib-Python plus independently validated calculations |
| Frontend | React 18, Tailwind, Shadcn/UI, Recharts |
| Monitoring | Prometheus, Grafana, OpenTelemetry |
| Execution | Unified adapter interface |
| Risk enforcement | Deterministic, independently testable service |
| Lifecycle | Persistent event-driven service |
| Audit | Append-only, tamper-evident records |

Avoid introducing unnecessary microservices in the first release. Start with modular services and separate components according to throughput, reliability and deployment requirements.

---

## 26. Open Product Decisions

These require explicit approval before implementation:

1. Which brokers are supported in the first live release?
2. Which user/account types can enable autonomous live trading?
3. What are the default account-level and strategy-level risk limits?
4. Which order types are permitted for entries and emergency exits?
5. Which market-data providers are licensed for each data category?
6. What is the exact approval hierarchy for retail, HNI and institutional accounts?
7. What are the strategy-specific certification thresholds?
8. What are the retention and audit requirements for each customer category?
9. Which F&O strategies are enabled in the first release?
10. Which actions may run autonomously and which require human approval?

These values should be configuration-driven, not embedded in application code.

---

## 27. Final Product Definition

**Nivesh Autonomous Trading Desk** is an AI-assisted, policy-controlled trading operation that coordinates a specialised agent workforce to discover, evaluate, execute and manage trading strategies.

Its operating model has three distinct layers:

### Intelligence Layer
- AI Trader
- Trading Assistant
- Risk & Operations Agent
- Middle Office Supervisor
- Tech Support & Reliability Agent

### Deterministic Control Layer
- Desk Orchestrator
- Policy and Authorization Engine
- Capital Allocation Engine
- Portfolio Risk Engine
- Trade Lifecycle Manager
- Execution Gateway
- Reconciliation and Ledger

### Simulation, Execution and Data Layer
- Trading Desk Simulator
- Historical Replay and Scenario Engine
- Paper Trading Engine
- Broker Adapters
- Market Data Infrastructure
- Trade and P&L Ledger
- Event Bus
- Audit and Observability

**Ultimate objective:** A trader defines the trading objective, available capital and acceptable risk. Nivesh coordinates the workforce, executes authorized workflows, continuously manages open positions and provides complete visibility into every decision and outcome.

**The platform must always preserve the separation between recommendation, authorization and execution.**

---

# 28. Trading Desk Simulator — Full Trading-Day Simulation

## 28.1 Product requirement

The Nivesh Trading Desk Simulator is a first-class platform subsystem that simulates a complete trading organisation operating through a market session. It must simulate market conditions, agent collaboration, decisions, approvals, order execution, position management, operational failures and end-of-day reconciliation.

The simulator is not merely a mock order generator. It must reproduce the lifecycle and coordination behaviour of the production trading desk as closely as the available data and simulation assumptions allow.

The simulator must answer:

- Did the AI Trader discover the opportunity using only information available at that point in time?
- Did the Trading Assistant construct a valid strategy from the signal and user constraints?
- Did Risk & Operations independently validate the trade and portfolio impact?
- Did Middle Office apply the correct approval policy?
- Did the Execution Gateway and Paper Engine handle order states realistically?
- Did the Trade Lifecycle Manager take ownership after confirmed fills?
- Did all agents respond correctly as market conditions changed?
- Did the desk recover from delayed data, rejected orders, partial fills and service failures?
- Did the final ledger, P&L and broker/paper positions reconcile?

## 28.2 Simulator objectives

1. Validate end-to-end agent collaboration before live deployment.
2. Reproduce realistic trading sessions using historical market data.
3. Test strategies and lifecycle rules without risking capital.
4. Validate risk, capital allocation and approval policies.
5. Test multi-leg options execution and partial-fill handling.
6. Test recovery, idempotency, reconciliation and kill-switch behaviour.
7. Measure agent decision quality and coordination efficiency.
8. Compare different agent, prompt, model and policy versions under identical conditions.
9. Produce a replayable audit record of every event and decision.
10. Certify strategies and platform releases before controlled live use.

## 28.3 Simulation modes

The simulator must support four distinct modes.

| Mode | Description | Market input | Execution |
|---|---|---|---|
| Historical Replay | Replay a recorded market session | Point-in-time historical data | Simulated |
| Accelerated Replay | Replay a historical session faster than wall-clock time | Point-in-time historical data | Simulated |
| Scenario Simulation | Inject controlled market and operational events | Historical baseline plus scenario overrides | Simulated |
| Live Shadow | Observe live market data and generate decisions without sending orders | Live licensed market data | Shadow only |

### A. Historical Replay

- Select date, exchange, instrument universe and session.
- Replay events in original chronological order.
- Preserve the original market timestamps.
- Make data available to agents only when it would have been available in the original session.
- Reconstruct market state, signals, strategies, orders and fills.
- Support replay of a single instrument, portfolio, strategy or complete desk.
- Record missing data and limitations.

### B. Accelerated Replay

- Support configurable playback speeds, such as 2x, 5x, 10x and event-driven maximum speed.
- Maintain causal event ordering.
- Do not skip critical price, order, fill, stop or risk events.
- Allow pause, resume, step-forward and restart.
- Preserve deterministic reproducibility for the same inputs and versions.

### C. Scenario Simulation

Allow an operator to inject scenarios such as:

- Sudden index gap up or gap down.
- Sharp intraday reversal.
- Volatility expansion or volatility crush.
- Abnormal OI buildup or unwinding.
- Liquidity deterioration and wider bid/ask spreads.
- Price gaps through stop-loss.
- Circuit/price-band restrictions.
- Partial fills and rejected orders.
- Broker disconnection.
- Stale or delayed market data.
- Duplicate or out-of-order callbacks.
- Queue backlog and agent timeout.
- One leg of an options spread fills while another is rejected.
- Sudden margin increase.
- Daily loss or portfolio drawdown breach.

Scenario overrides must be clearly labelled. Results from altered scenarios must not be represented as historical market results.

### D. Live Shadow

- Subscribe to approved live market data.
- Run scanners and agent workflows.
- Generate trade plans, risk reports and hypothetical execution intents.
- Do not submit orders to a broker or mutate live positions.
- Compare simulated decisions with actual subsequent market events.
- Label all positions and P&L as hypothetical.
- Enforce a technical boundary that makes broker order submission impossible from this mode.

## 28.4 Simulation clock and event time

The simulator must have a controllable clock independent of the host system clock.

Clock requirements:

- Support exchange-local session calendars and holidays.
- Persist all event times in UTC.
- Preserve exchange/vendor event timestamps separately from ingestion timestamps.
- Support pause, resume, seek and speed changes.
- Maintain event ordering and causality.
- Support scheduled market events and expiry events.
- Prevent future data from being exposed to agents during historical replay.
- Support deterministic random seeds for stochastic execution assumptions.

Each event should include:

```json
{
  "simulation_id": "SIM-20261105-001",
  "simulation_time": "2026-11-05T09:35:00+05:30",
  "event_time_utc": "2026-11-05T04:05:00Z",
  "ingestion_time_utc": "2026-11-05T04:05:00Z",
  "sequence_number": 10501,
  "event_type": "MARKET_TICK",
  "source": "HISTORICAL_REPLAY",
  "data_version": "market-data-v1"
}
```

The values are illustrative.

## 28.5 Realistic market simulation

The market simulator must model or replay:

- Last traded price
- Best bid and ask
- Bid/ask spread
- Traded volume
- Available depth, when sourced
- Intraday volatility
- Price gaps
- Trading halts and price bands
- Futures basis and OI
- Options chain and IV
- Expiry and time decay
- Liquidity changes
- Corporate actions and contract adjustments where applicable

Historical replay should use recorded market data. If tick/depth data is unavailable, the simulator must disclose the approximation used. OHLC bars alone cannot establish the exact order in which a stop and target were touched inside a bar.

## 28.6 Realistic paper execution engine

The paper engine must model order lifecycle and execution quality rather than filling every order at the requested price.

### Order types

- Market
- Limit
- Stop-loss market, subject to supported simulation semantics
- Stop-loss limit
- Supported broker-specific variants, when modelled

### Execution behaviour

- Bid/ask-aware fills
- Slippage
- Configurable latency
- Partial fills
- Queue-position assumptions
- Available-volume constraints
- Rejections
- Price collars and price bands
- Cancellations and modifications
- Order acknowledgement delays
- Broker callback delays
- Fees, brokerage, taxes and charges
- Margin and collateral simulation
- Expiry and settlement handling

Every fill must record:

- Requested price
- Fill price
- Requested quantity
- Filled quantity
- Remaining quantity
- Market bid/ask at decision and fill time, if available
- Simulated latency
- Slippage
- Fee assumptions
- Fill model version
- Simulation ID

The simulator must distinguish between observed historical liquidity and assumed liquidity. It must not claim queue-level realism when only OHLCV data is available.

---

# 29. Agent Coordination Simulator

## 29.1 Coordination objective

The simulator must validate that all bots operate as a coordinated workforce with explicit task ownership, handoffs, deadlines, dependencies, shared trade context and bounded authority.

Agents must not simply emit independent chat messages. Each agent must receive a structured task, use permitted tools, return a typed result and either complete, reject or escalate the task.

## 29.2 Agent task lifecycle

Every agent task follows:

`CREATED → ASSIGNED → ACCEPTED → RUNNING → RESULT_READY → VALIDATED → COMPLETED`

Exception states:

- REJECTED
- BLOCKED
- TIMED_OUT
- RETRY_PENDING
- FAILED
- ESCALATED
- CANCELLED

Each task must record:

- Task ID
- Simulation ID
- Workflow ID
- Tenant and account context
- Trade/signal ID, where applicable
- Assigned agent
- Requesting agent/service
- Input references
- Required output schema
- Deadline
- Retry policy
- Tool permissions
- Result reference
- Validation result
- Token/model cost where available
- Start and completion times

## 29.3 Standard agent handoff contract

```json
{
  "task_id": "TASK-5001",
  "simulation_id": "SIM-001",
  "workflow_id": "WF-1001",
  "from": "AI_TRADER",
  "to": "TRADING_ASSISTANT",
  "task_type": "GENERATE_STRATEGY",
  "entity_id": "SIGNAL-1001",
  "input_refs": [
    "signal://SIGNAL-1001",
    "market-snapshot://SNAP-2001"
  ],
  "constraints": {
    "execution_mode": "PAPER",
    "max_capital": 150000,
    "max_risk": 4000,
    "allowed_instruments": ["CASH", "OPTIONS"]
  },
  "deadline": "2026-11-05T09:32:00+05:30",
  "required_output_schema": "trade-plan-v1"
}
```

A receiving agent must acknowledge, reject or escalate the task. It must not silently ignore a task.

## 29.4 Shared context and memory

All participating agents must use a consistent, versioned trade context.

Shared context includes:

- Original signal and evidence
- Approved strategy plan and version
- Account and execution mode
- Capital reservation
- Risk policy version
- Current position and fills
- Current market snapshot
- Previous approvals and decisions
- Outstanding tasks and exceptions
- Current lifecycle state

Agents receive only the data required for their role. Shared context is not unrestricted shared memory. Tenant and account boundaries apply to every read and write.

## 29.5 Agent collaboration rules

1. AI Trader owns opportunity discovery, not execution.
2. Trading Assistant owns strategy proposal, not risk approval.
3. Risk & Operations independently validates risk and operations.
4. Middle Office applies authorization policy and records decisions.
5. Execution Gateway accepts only validated, authorized intents.
6. Trade Lifecycle Manager owns confirmed positions and approved lifecycle actions.
7. Tech Support monitors platform reliability and cannot create trading instructions.
8. No agent may change its own permissions or the risk policy.
9. Every handoff must reference the same workflow and relevant entity IDs.
10. Every agent output must pass schema and policy validation before downstream use.

## 29.6 Disagreement and challenge protocol

The system must support structured disagreement.

Examples:

- AI Trader proposes bullish exposure.
- Trading Assistant identifies a lower-risk alternative.
- Risk & Operations identifies excessive sector concentration.
- Trading Assistant revises the proposal.
- Middle Office rejects an expired or incorrectly scoped approval.
- Lifecycle Manager refuses an unauthorized stop-loss widening request.

A disagreement must result in one of:

- Revised proposal
- Rejected proposal
- Escalation to user
- No-trade decision

The orchestrator must never resolve a hard-policy disagreement by majority vote. Deterministic policy and authorization rules take precedence.

## 29.7 Agent performance measures

Measure agents independently and as a team:

| Metric | Meaning |
|---|---|
| Task completion rate | Completed tasks / assigned tasks |
| Task latency | Time from assignment to valid result |
| Schema validity | Outputs passing schema validation |
| Handoff success | Accepted downstream handoffs |
| Rework rate | Tasks returned for correction |
| Escalation rate | Tasks requiring human intervention |
| Tool failure rate | Failed tool invocations |
| Decision consistency | Same inputs and versions produce consistent outputs where determinism is expected |
| Policy violation attempts | Out-of-scope actions proposed or attempted |
| Collaboration completeness | Required agents completed their workflow responsibilities |

Do not reward an agent simply for generating more trades or more messages.

---

# 30. Complete Simulated Trading-Day Workflow

The simulator must run the following end-to-end sequence.

## 30.1 Pre-market preparation

**08:00–09:15 IST — illustrative session schedule**

1. Tech Support performs infrastructure checks.
2. Market data services validate feeds, reference data and instrument masters.
3. AI Trader analyses overnight market context and scheduled events.
4. AI Trader prepares index, sector and stock watchlists.
5. Trading Assistant summarises opportunities and strategy candidates.
6. Risk & Operations loads account capital, open positions and risk limits.
7. Middle Office verifies account mode and policy availability.
8. Desk Orchestrator publishes PREMARKET_READY or PREMARKET_BLOCKED.

If required market data, broker connectivity or policy services are unhealthy, the desk must not silently proceed to new risk-increasing execution.

## 30.2 Market open and opportunity discovery

1. Simulator clock reaches the exchange session open.
2. Market events are published in chronological order.
3. AI Trader scans the eligible universe.
4. Signals are scored and deduplicated.
5. Signal evidence and data timestamps are stored.
6. Trading Assistant receives eligible signals.
7. Strategy candidates are generated.
8. Candidate plans are ranked using risk-adjusted criteria.
9. Expired or stale proposals are discarded.

## 30.3 Strategy validation and approval

1. Trading Assistant submits a structured plan.
2. Risk & Operations calculates position sizing, capital, margin and portfolio impact.
3. If risk fails, it returns specific violations.
4. Trading Assistant may revise within the original constraints.
5. Risk & Operations reassesses the revised version.
6. Middle Office checks approval scope and policy.
7. The user or authorized autonomous policy approves, rejects or requests revision.
8. Capital Allocator reserves funds atomically.
9. Execution intent is created only after all required checks pass.

## 30.4 Execution and position activation

1. Execution Gateway validates authorization again.
2. Paper adapter receives the order.
3. Simulator models acknowledgement, latency and fill behaviour.
4. Fill events are published.
5. Position ledger records actual simulated fills.
6. Capital and risk reservations are adjusted.
7. Lifecycle Manager activates the position.
8. Protective order state is verified.
9. All agents receive the appropriate position event.

## 30.5 Intraday lifecycle management

On each relevant market or execution event:

1. Market simulator publishes updated state.
2. Lifecycle Manager updates position valuation.
3. Risk & Operations recalculates risk and portfolio exposure.
4. Strategy monitor evaluates original thesis and invalidation conditions.
5. Target and stop rules are evaluated.
6. Lifecycle Manager determines whether an action is permitted.
7. Policy engine validates the action.
8. Execution Gateway processes authorized order instructions.
9. Fill and rejection events update the ledger.
10. Middle Office receives material exceptions.
11. Trading Assistant explains material changes to the trader.
12. Agent activity timeline records all decisions.

The cycle continues until the position is closed or the simulation ends with a clearly identified open-position state.

## 30.6 End-of-day

1. Stop new entries at the configured cutoff.
2. Continue managing open positions.
3. Apply strategy-specific carry-forward and expiry rules.
4. Cancel eligible pending entry orders.
5. Reconcile all fills, orders, positions and funds.
6. Calculate realized and unrealized P&L and charges.
7. Release capital only when supported by confirmed state.
8. Close or explicitly carry forward positions according to policy.
9. Generate agent performance and coordination reports.
10. Generate daily desk report and archive simulation.

A market-session close must not automatically imply that every position is closed.

---

# 31. End-to-End Simulation Scenarios

The simulator must include a scenario library.

| ID | Scenario | Expected behaviour |
|---|---|---|
| SIM-001 | Normal bullish day | Discover, approve, execute and manage bullish trades |
| SIM-002 | Normal bearish day | Discover and validate bearish setups |
| SIM-003 | Sideways market | Avoid low-quality trades where policy requires |
| SIM-004 | Sudden gap down | Recalculate risk and execute approved protective actions |
| SIM-005 | Volatility spike | Recalculate option Greeks and stress exposure |
| SIM-006 | Target reached | Execute configured partial booking |
| SIM-007 | Stop-loss gap-through | Model adverse fill and residual risk |
| SIM-008 | Partial entry fill | Manage actual filled quantity only |
| SIM-009 | Partial exit fill | Recalculate remaining exposure |
| SIM-010 | One option leg rejected | Detect unhedged exposure and apply emergency policy |
| SIM-011 | Broker disconnect | Stop unsafe new orders, recover and reconcile |
| SIM-012 | Stale market data | Block new risk-increasing orders |
| SIM-013 | Duplicate order callback | Process idempotently |
| SIM-014 | AI Trader timeout | Retry/escalate without blocking existing lifecycle |
| SIM-015 | Risk limit breached | Block additional risk and apply escalation policy |
| SIM-016 | Middle Office rejection | Prevent execution |
| SIM-017 | Capital reservation conflict | Permit only valid atomic reservation |
| SIM-018 | Kill switch | Stop permitted activity without removing necessary protection |
| SIM-019 | Manual broker modification | Detect and reconcile external change |
| SIM-020 | End-of-day open position | Apply carry-forward or exit policy and reconcile |

Each scenario must have preconditions, event timeline, expected agent tasks, expected state transitions, expected orders, expected risk outcome and pass/fail assertions.

---

# 32. Simulation Dashboard and Operator Controls

Add a dedicated **Trading Desk Simulator** workspace.

## 32.1 Simulation setup

Allow the operator to configure:

- Simulation name and description
- Historical date or date range
- Market universe
- Trading account or isolated virtual account
- Starting capital
- Risk policy version
- Strategy templates
- Agent versions and configurations
- Model and prompt versions
- Execution assumptions
- Brokerage and charges
- Slippage and latency
- Playback speed
- Scenario injections
- Random seed

## 32.2 Simulation controls

- Start
- Pause
- Resume
- Stop
- Restart
- Step one event
- Step one workflow
- Change playback speed
- Inject scenario
- Export results
- Replay from checkpoint

Stopping a simulation must safely stop its virtual execution and preserve the last consistent state. It must never affect live accounts.

## 32.3 Simulation dashboard

Show:

- Simulation clock and session progress
- Market status and current market snapshot
- Agent health and current task
- Inter-agent communication timeline
- Workflow dependency graph
- Signals generated and rejected
- Strategy proposals and revisions
- Risk checks and approvals
- Capital allocation
- Orders, fills and rejections
- Active positions
- Stops, targets and trailing updates
- P&L and portfolio risk
- Exceptions and recovery actions
- Final reconciliation status

## 32.4 Agent conversation and decision trace

For every agent task, provide:

- Requesting agent
- Receiving agent
- Task input references
- Structured output
- Evidence references
- Tool calls and results
- Validation result
- Time taken
- Retry count
- Downstream handoff
- Final decision

Do not expose hidden chain-of-thought. Display concise decision explanations, structured evidence, policy checks and recorded outputs instead.

## 32.5 Simulation comparison

Allow side-by-side comparison of:

- Agent/model version A versus B
- Risk policy A versus B
- Strategy configuration A versus B
- Execution assumptions A versus B

Use identical market inputs and random seeds where applicable. Show differences in trades, net P&L, drawdown, exposure, slippage, rejected proposals, execution failures and policy violations.

---

# 33. Simulation Data Model

Add these tables to the existing schema.

| Table | Purpose |
|---|---|
| simulations | Simulation configuration and status |
| simulation_runs | Individual run and version |
| simulation_clock_events | Clock and playback state |
| simulation_market_events | Market event references |
| simulation_scenarios | Scenario definitions |
| simulation_scenario_injections | Injected event timeline |
| simulation_execution_profiles | Fill, slippage and latency assumptions |
| simulation_agent_versions | Agent/model/prompt versions |
| simulation_workflows | Workflow instances in simulation |
| simulation_agent_tasks | Assigned agent tasks |
| simulation_agent_handoffs | Agent-to-agent task handoffs |
| simulation_decisions | Structured agent decisions |
| simulation_checkpoints | Replay and recovery checkpoints |
| simulation_assertions | Expected behaviour and test assertions |
| simulation_results | Aggregate run results |
| simulation_comparisons | Run-to-run comparisons |

All simulated trade, order, fill and position records must carry a simulation_id and an explicit simulated-source marker. Enforce database and service-level separation from live account records.

---

# 34. Simulator APIs

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/simulations` | Create simulation |
| GET | `/api/v1/simulations` | List simulations |
| GET | `/api/v1/simulations/{id}` | Simulation details |
| POST | `/api/v1/simulations/{id}/start` | Start |
| POST | `/api/v1/simulations/{id}/pause` | Pause |
| POST | `/api/v1/simulations/{id}/resume` | Resume |
| POST | `/api/v1/simulations/{id}/stop` | Stop safely |
| POST | `/api/v1/simulations/{id}/restart` | Restart from defined checkpoint |
| POST | `/api/v1/simulations/{id}/step` | Advance one event/workflow |
| POST | `/api/v1/simulations/{id}/speed` | Change playback speed |
| POST | `/api/v1/simulations/{id}/scenarios` | Inject scenario |
| GET | `/api/v1/simulations/{id}/agents` | Agent state |
| GET | `/api/v1/simulations/{id}/timeline` | Event timeline |
| GET | `/api/v1/simulations/{id}/workflows` | Workflow list |
| GET | `/api/v1/simulations/{id}/results` | Run results |
| POST | `/api/v1/simulations/compare` | Compare runs |

All mutating simulator endpoints must be idempotent where appropriate and must validate simulation ownership and state.

---

# 35. Simulation Acceptance Criteria

A release is not considered simulator-ready until the following are demonstrated:

1. A complete historical trading session can be replayed.
2. No agent can access future market data during replay.
3. All five agents receive and complete their required workflow tasks.
4. Every handoff is correlated to the same simulation and workflow.
5. Agent disagreement follows the defined challenge/escalation protocol.
6. Risk checks occur before every risk-increasing execution.
7. Middle Office rejection prevents execution.
8. Capital reservations prevent concurrent over-allocation.
9. The paper engine models partial fills, slippage and rejection.
10. Lifecycle activation occurs only after confirmed fills.
11. Partial exits update remaining quantity and risk correctly.
12. Multi-leg partial execution triggers leg-level risk handling.
13. Duplicate and out-of-order callbacks do not create duplicate actions.
14. Broker disconnect scenarios recover and reconcile correctly.
15. Market-data staleness blocks new risk-increasing trades.
16. A hard risk breach blocks additional risk.
17. Existing-position protection continues through LLM and agent outages.
18. A simulation can be paused, resumed and replayed.
19. Identical deterministic runs produce identical results under the same inputs and versions.
20. All simulated records are isolated from live account data.
21. Every material decision is traceable to evidence, policy and agent output.
22. Final orders, fills, positions, capital and P&L reconcile.
23. Simulation results clearly disclose assumptions and limitations.
24. No simulated order can reach a live broker adapter.

---

# 36. Simulator Release Roadmap

## Simulator Phase S1 — Workflow Simulation

- Agent task contracts
- Agent registry
- Orchestrator
- Structured handoffs
- Shared trade context
- Simulated market snapshots
- No-order signal-to-approval workflow

**Exit:** All agents complete a traceable strategy proposal and approval workflow.

## Simulator Phase S2 — Full Paper Execution

- Historical replay clock
- Paper order engine
- Fill, slippage and cost simulation
- Capital reservation
- Lifecycle activation
- Stop and target management

**Exit:** Full paper trade from discovery to confirmed closure.

## Simulator Phase S3 — Multi-Agent Trading-Day Simulation

- All five agents operating together
- Continuous market events
- Position monitoring
- Intraday strategy reassessment
- Multi-leg options
- Scenario injection
- Agent timeline and workflow visualisation

**Exit:** A complete simulated trading day with multiple strategies and positions, including exceptions.

## Simulator Phase S4 — Reliability and Certification

- Fault injection
- Agent timeouts and failures
- Broker outage simulation
- Recovery and reconciliation
- Deterministic replay
- Model/policy comparisons
- Strategy certification report

**Exit:** All critical safety, recovery and reconciliation assertions pass.

## Simulator Phase S5 — Live Shadow and Controlled Live Readiness

- Live market data shadow mode
- Hypothetical order and position tracking
- Actual market outcome comparison
- Broker adapter certification
- Operational and compliance sign-off

**Exit:** Approved controlled-live readiness. Shadow mode itself must remain technically unable to send broker orders.

---

# 37. Final Product Requirement

The Nivesh Trading Desk Simulator must demonstrate that the complete AI trading organisation can function as a coordinated, accountable and recoverable system.

It must simulate more than profitable and unprofitable trades. It must simulate:

- Agents doing their jobs
- Agents challenging each other's recommendations
- Workflows waiting for approvals
- Capital being reserved and released
- Orders being partially filled or rejected
- Positions changing as the market evolves
- Risk policies blocking unsafe actions
- Lifecycle managers protecting open positions
- Technical failures and recovery
- Final reconciliation and performance evaluation

**Definition of done:** Given a selected historical trading session, starting capital, configured risk policies, agent versions and execution assumptions, Nivesh can run an end-to-end simulated trading day, reproduce every material agent interaction and trading event, and produce an auditable final report showing what each agent did, why it did it, what the simulated market and execution engine did, and whether the desk complied with its approved policies.

The simulator is the mandatory proving ground for autonomous paper trading and the certification gate before any controlled live execution.
