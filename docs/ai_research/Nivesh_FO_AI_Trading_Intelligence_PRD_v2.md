# Nivesh F&O AI Trading Intelligence, Agent, Backtesting, Risk Management & Certification Platform

**Product Requirements Document (PRD)**  
**Version:** 2.0  
**Status:** Comprehensive product and engineering specification  
**Product:** Nivesh.ai / Nivesh Copilot (NIDP)  
**Trading modes:** Paper and Live

---

## 1. Executive Summary

Nivesh F&O AI Trading Intelligence is an explainable, risk-controlled platform for researching, constructing, ranking, validating, paper trading, and—only after rigorous certification—executing Futures & Options (F&O) strategies.

The platform combines:
- Market intelligence from futures, options-chain, open interest (OI), volume, volatility, and Greeks.
- An AI strategy agent that interprets context and proposes structured strategies.
- Deterministic pricing, payoff, margin, Greeks, and risk services.
- Event-driven historical backtesting and walk-forward validation.
- Paper, shadow, and restricted live execution workflows.
- An independent Risk Control Center and enforceable certification system.

**Core principle:** AI may interpret context and propose strategies. Deterministic services calculate, validate, authorize, and execute. The AI must never bypass risk controls or certify itself.

### 1.1 Product principles
1. Risk controls are independent of the AI agent.
2. No order is sent without deterministic validation and authorization.
3. Paper and live modes use separate ledgers, permissions, and execution adapters.
4. Research must use point-in-time data and realistic costs.
5. No-lookahead integrity and out-of-sample (OOS) evidence are mandatory.
6. “No trade” is a valid and desirable agent decision.
7. Live access is earned through explicit, versioned certification.
8. All consequential actions are auditable and reproducible.

---

## 2. Background and Problem Statement

F&O strategies are sensitive to market regime, volatility, expiry, liquidity, execution quality, and changing Greeks. An AI model can produce plausible but invalid strategies, misread OI, use stale quotes, underestimate margin, or recommend trades that cannot be filled at modeled prices.

The platform must overcome:
- Incomplete or non-point-in-time historical options data.
- Look-ahead and survivorship bias.
- Misleading backtests that omit bid/ask spreads, slippage, fees, partial fills, or legging risk.
- AI hallucination or malformed strategy definitions.
- OI ambiguity and unreliable directional inference.
- Dynamic IV and Greek exposure, especially near expiry.
- Overfitting and weak evidence that AI improves on deterministic baselines.
- Non-atomic multi-leg execution and broker/API failures.
- Unsafe autonomous behavior, overtrading, or policy drift.
- Gaps between paper fills and live fills.

The product should convert these risks into explicit system controls, tests, metrics, and release gates.

---

## 3. Goals and Non-Goals

### 3.1 Goals
- Provide explainable market and derivatives intelligence.
- Support editable multi-leg option strategies and futures strategies.
- Display payoff, max profit/loss, breakevens, capital, margin, and Greeks.
- Rank candidate strategies using transparent, validated criteria.
- Backtest strategies with event-driven, point-in-time data.
- Operate separate paper and live workflows.
- Provide portfolio-level and trade-level risk management.
- Certify the agent and all relevant execution components before live use.
- Keep full audit records and support replay of decisions.

### 3.2 Non-goals
- Treating an LLM as the source of truth for pricing, Greeks, margin, or risk.
- Allowing AI to invent broker capabilities or instrument metadata.
- Guaranteeing profits or predicting market moves with certainty.
- Enabling unrestricted autonomous live trading at initial launch.
- Replacing broker/exchange risk controls.
- Presenting a backtest as proof of future profitability.

---

## 4. Users and Roles

| Role | Responsibilities |
|---|---|
| Retail investor / trader | Explore strategies, review explanations, paper trade, request eligible live trades |
| Advanced trader | Customize legs, Greeks, scenarios, and risk limits |
| Research analyst | Define hypotheses, run backtests, compare variants, inspect evidence |
| Risk manager | Configure limits, approve policies, monitor exposures, stop trading |
| Administrator | Manage users, brokers, permissions, certification, audit, and releases |
| AI agent | Interpret context and produce structured strategy candidates; cannot authorize its own actions |

Role-based access control (RBAC) must restrict configuration, approvals, live execution, and certification functions.

---

## 5. System Architecture and Authority Boundaries

### 5.1 High-level flow

```text
Market Data & Instrument Master
        ↓
Data Quality / Freshness / Point-in-Time Validation
        ↓
Market Intelligence (Futures, OI, Greeks, IV, Expiry, Regime)
        ↓
AI Strategy Agent → Structured Candidate Proposal
        ↓
Strategy Schema Validator
        ↓
Deterministic Pricing / Payoff / Greeks / Margin / Scenario Engine
        ↓
Independent Risk Engine + Certification/Authorization
        ↓
Paper Simulator OR Live OMS / Broker Adapter
        ↓
Order, Fill, Position, P&L, Reconciliation, Audit
        ↓
Monitoring / Alerts / Replay / Research Evaluation
```

### 5.2 Separation of responsibilities
- **AI agent:** Contextual interpretation, candidate generation, strategy explanation, candidate ranking support.
- **Strategy service:** Validates strategy structure and instrument eligibility.
- **Pricing service:** Computes theoretical values, payoff, breakevens, and Greeks using approved methods.
- **Margin service:** Estimates required capital and broker/exchange margin using available authoritative data.
- **Risk engine:** Independently authorizes or rejects every order and relevant state transition.
- **OMS:** Manages order lifecycle, idempotency, partial fills, retries, and reconciliation.
- **Certification service:** Enforces approved model, strategy, policy, broker, account, and adapter versions.
- **Audit service:** Stores immutable evidence for decisions and actions.

The LLM cannot directly call a broker order endpoint or change risk limits.

---

## 6. Market Intelligence

### 6.1 Market regime
Identify and display the current context, including:
- Trend, range, volatility expansion/contraction, and event-driven conditions.
- Underlying price relative to relevant moving averages and trend measures.
- Realized volatility and implied volatility regime.
- Liquidity and spread quality.
- Sector/index context where relevant.

Regime labels must be explainable and versioned. They are features, not guarantees.

### 6.2 Futures intelligence
Track:
- Futures price versus spot and basis.
- Futures volume and OI changes.
- Price/OI combinations as candidate long build-up, short build-up, short covering, and long unwinding signals.
- Basis changes across expiries.
- Roll activity and expiry proximity.
- Intraday and daily changes, not only end-of-day snapshots.

OI labels must be treated as interpretations, not definitive participant intent. Show the underlying price change, OI change, time window, and confidence.

### 6.3 Options-chain intelligence
For each expiry and strike, retain and display:
- Call/put bid, ask, LTP, volume, OI, and OI change.
- IV and available Greeks.
- Spread width, quote age, liquidity indicators, and lot size.
- Strike distance from underlying and moneyness.
- Expiry date and days/time to expiry.

Track changes over multiple windows (intraday, daily, and multi-session) with timestamped snapshots. Avoid inferring a reliable signal from one isolated OI snapshot.

### 6.4 Expiry and term structure
- Analyze near, next, and far monthly expiries (three-month term structure where listed and data is available).
- Track changes in OI, IV, skew, basis, and Greeks through the month.
- Increase monitoring granularity during expiry week and on event days.
- Do not assume that OI build-up is always stronger or more informative near expiry; validate empirically.
- Clearly distinguish weekly and monthly expiries and any special expiry schedules.

### 6.5 Greeks and volatility intelligence
Use broker-provided Greeks when available, with data provenance and timestamps. Validate plausibility and compute fallback values only using approved models and documented assumptions.

Support:
- Delta, Gamma, Theta, Vega, and Rho where relevant.
- IV level, term structure, skew, and changes.
- Portfolio and strategy Greeks, including net and leg-level exposure.
- Scenario shocks to underlying price, IV, and time.
- Expiry-specific gamma and theta risk.

Greeks are estimates and can change rapidly. Show the source, timestamp, and whether a value is broker-provided or calculated.

---

## 7. AI Strategy Agent

### 7.1 Responsibilities
The agent may:
- Summarize market context and evidence.
- Propose a strategy from the approved strategy library.
- Select candidate expiries, strikes, and legs from valid instruments.
- Explain the thesis, risks, invalidation conditions, and expected behavior.
- Rank candidates using approved signals and constraints.
- Recommend no trade when evidence is weak or data quality is inadequate.

### 7.2 Prohibited actions
The agent must not:
- Submit or modify live orders directly.
- Override or weaken risk policies.
- Invent quotes, Greeks, margin, liquidity, or broker capabilities.
- Treat OI interpretation as certainty.
- Modify its own production model or strategy permissions.
- Mark itself certified or bypass required approvals.
- Continue when required data is stale, missing, or contradictory.

### 7.3 Structured proposal schema
Every candidate should contain at minimum:

```json
{
  "proposal_id": "unique-id",
  "underlying": "instrument-id",
  "strategy_template": "approved-template-id",
  "market_view": "bullish|bearish|neutral|volatility-expansion|volatility-contraction",
  "thesis": "plain-language explanation",
  "legs": [
    {
      "instrument_id": "valid-contract-id",
      "side": "BUY|SELL",
      "quantity": 0,
      "order_type": "LIMIT|other-approved-type",
      "limit_price": null
    }
  ],
  "expiry": "YYYY-MM-DD",
  "expected_holding_period": "defined horizon",
  "invalidation_conditions": [],
  "risk_summary": {},
  "evidence": [],
  "confidence": 0.0,
  "model_version": "version",
  "strategy_version": "version",
  "data_snapshot_id": "snapshot-id"
}
```

The schema is illustrative. The production schema must be strictly typed, versioned, and validated. Missing fields, invalid contracts, inconsistent legs, or unsupported order types must reject the proposal.

### 7.4 No-trade behavior
The agent should explicitly return `NO_TRADE` when:
- Data is stale or incomplete.
- No candidate meets minimum expected value or risk constraints.
- Liquidity is inadequate.
- Risk budget is exhausted.
- The market regime is outside the strategy’s certified domain.
- Confidence or evidence is below the approved threshold.

---

## 8. Strategy Library and Builder

### 8.1 Strategy templates
Provide approved templates such as:
- Long call / long put.
- Covered call and protective put.
- Bull call spread and bear put spread.
- Bull put spread and bear call spread.
- Long/short straddle and strangle, subject to risk permissions.
- Iron condor and iron butterfly.
- Calendar and diagonal spreads.
- Futures with defined-risk hedges.
- Additional strategies only after independent validation and certification.

Template permissions must be controlled by user role, account, market, instrument, and trading mode.

### 8.2 Strategy builder
Users can:
- Open an option chain.
- Add, remove, and modify legs.
- Change expiry, strike, side, quantity, and supported order type.
- View payoff and risk metrics update immediately.
- Compare strategy variants.
- Save a draft without submitting an order.

### 8.3 Required payoff and capital outputs
Display:
- Payoff graph at expiry.
- Scenario P&L before expiry where supported.
- Maximum profit and maximum loss, or clearly state when either is theoretically unlimited.
- Breakeven points.
- Net debit/credit.
- Leg-level and net Greeks.
- Estimated margin and total capital required.
- Fees, taxes, and estimated slippage.
- Margin buffer and available funds after the proposed trade.
- Assumptions, data timestamp, and calculation source.

Do not label an estimate as guaranteed broker margin. Recheck with broker/exchange margin data before live authorization.

---

## 9. Strategy Ranking

### 9.1 Ranking dimensions
Candidate ranking may consider:
- Market regime fit.
- Directional or volatility thesis fit.
- OI and futures evidence.
- IV level, skew, and term structure.
- Greeks and scenario risk.
- Expected return after costs.
- Liquidity, spread, quote age, and fill probability.
- Margin efficiency and capital usage.
- Portfolio fit, correlation, and existing exposure.
- Expiry and event risk.
- Historical evidence within the candidate’s certified domain.

### 9.2 Ranking safeguards
- Do not let a single proxy such as ATR, IV, or OI dominate without evidence.
- Normalize features and record transformations.
- Track feature contribution and drift.
- Compare against deterministic rule-based baselines.
- Evaluate incremental value with walk-forward and OOS tests.
- Use a “no suitable candidate” outcome instead of forcing a ranking.
- Keep model score separate from risk authorization.

---

## 10. Historical Backtesting and Research Integrity

### 10.1 Data requirements
Historical data should include, where available:
- Timestamped option-chain snapshots.
- Bid/ask and quote sizes, not only LTP.
- OI, OI change, volume, IV, and Greeks.
- Underlying and futures prices, basis, and volume/OI.
- Historical instrument master, expiry calendar, lot size, strike increments, and contract changes.
- Corporate actions and relevant event timestamps.
- Brokerage, exchange fees, taxes, and other costs.

Daily snapshots are insufficient for robust intraday strategy simulation. Document coverage gaps and do not silently fill unavailable data.

### 10.2 Point-in-time controls
- Every feature must be available at the simulated decision timestamp.
- No future prices, future OI, revised data, or post-event information may leak into a decision.
- Use historical instrument masters and expiry schedules.
- Handle survivorship and delisted/expired instruments where relevant.
- Record dataset version, source, and snapshot timestamps.
- Prevent label leakage across training and evaluation windows.

### 10.3 Event-driven replay
The backtester must:
1. Load a point-in-time market state.
2. Generate the strategy decision using only available information.
3. Validate the proposal.
4. Simulate order submission and realistic fills.
5. Update positions, Greeks, margin, P&L, and risk.
6. Apply exits, stops, adjustments, expiry settlement, and assignment rules where applicable.
7. Record every event for reproducibility.

### 10.4 Execution simulation
Model:
- Bid/ask-aware fills.
- Slippage and market impact assumptions.
- Fees, brokerage, taxes, and exchange charges.
- Partial fills, rejected orders, stale quotes, and order latency.
- Multi-leg execution and legging risk.
- Conservative fill assumptions and sensitivity analysis.
- Liquidity/volume constraints.
- Broker-specific order rules where known.

Do not assume all legs fill atomically unless the venue/broker explicitly supports that behavior.

### 10.5 Evaluation metrics
At minimum:
- Net P&L and return after costs.
- Maximum drawdown and drawdown duration.
- Win rate, average win/loss, profit factor, expectancy.
- Sharpe and Sortino where statistically appropriate.
- Tail loss / expected shortfall.
- Exposure, margin usage, and capital efficiency.
- Turnover, fill rate, slippage, and rejected orders.
- Performance by regime, expiry, time of day, and strategy family.
- Number of trades and confidence intervals.

### 10.6 Validation protocol
- Preregister hypothesis, universe, features, entry/exit, costs, and metrics.
- Use chronological train/validation/test splits.
- Use walk-forward evaluation.
- Keep a sealed final OOS set.
- Compare AI selection against deterministic strategy baselines on identical data and constraints.
- Perform ablation studies to measure the contribution of AI, OI, Greeks, and other features.
- Report uncertainty and sample size.
- Reject promotion if OOS evidence is negative, insufficient, or not reproducible.

A profitable backtest is not by itself evidence of live readiness.

---

## 11. Paper Trading

### 11.1 Modes
- **Diagnostic paper:** Used to inspect logic and UI; may use simplified assumptions, must be labeled.
- **Conservative paper:** Uses bid/ask, slippage, latency, partial fills, costs, and broker-like restrictions.
- **Shadow mode:** Agent makes decisions against live market data but does not submit orders; compare hypothetical outcomes and decisions.
- **Live mode:** Real orders, enabled only for certified contexts.

Paper and live must use separate account state, ledger, order IDs, permissions, and data labeling.

### 11.2 Paper requirements
- Simulate order lifecycle and realistic fill rules.
- Track unrealized and realized P&L, margin, Greeks, and risk limits.
- Support pause, resume, stop, and session reset controls.
- Record market data snapshot and strategy/model versions.
- Compare expected versus simulated fill price and slippage.
- Do not allow diagnostic paper results to satisfy live certification unless explicitly approved by policy.

---

## 12. Live Trading and Order Management System (OMS)

### 12.1 Order lifecycle
Support explicit states such as:
`CREATED → VALIDATED → AUTHORIZED → SUBMITTED → ACKNOWLEDGED → PARTIALLY_FILLED → FILLED`

Also support:
`REJECTED`, `CANCEL_PENDING`, `CANCELLED`, `EXPIRED`, `UNKNOWN`, and `RECONCILIATION_REQUIRED`.

### 12.2 OMS requirements
- Idempotency keys to prevent duplicate submissions.
- Broker order and trade ID mapping.
- Retry policies that distinguish safe retries from possible duplicate orders.
- Timeout and unknown-state reconciliation.
- Partial fill and remaining-leg handling.
- Cancel/replace safety.
- Broker position and funds reconciliation.
- Clear handling of market closure, exchange rejection, and API outages.
- Full audit trail of every state transition.

### 12.3 Multi-leg execution
- Define permitted execution sequence and maximum legging exposure.
- Monitor partial fills and hedge immediately where policy requires.
- Establish timeouts and recovery actions.
- Define abort, flatten, hedge, and manual intervention paths.
- Never assume a multi-leg order is atomic.
- Risk engine must evaluate interim exposure, not only the intended final spread.

---

## 13. Independent Risk Management and Risk Control Center

### 13.1 Risk engine
The risk engine must be a separate, deterministic service. It must govern every order path, including UI, API, agent, scheduled jobs, and recovery workflows.

It must not rely on an LLM prompt or UI-only checks.

### 13.2 Pre-trade checks
For every proposal/order:
- Validate account, broker, instrument, expiry, lot size, and trading mode.
- Validate market data freshness and liquidity.
- Compute max loss, payoff, margin, and scenario exposures.
- Check order quantity, notional, premium, and capital limits.
- Check portfolio-level and correlated exposure.
- Check net Greeks and stress scenarios.
- Check daily loss, drawdown, and margin utilization.
- Confirm strategy and agent certification for the exact context.
- Require explicit user authorization when policy says so.
- Reject if any required check is unavailable or fails.

### 13.3 Hard and soft limits
Examples of configurable limits:
- Maximum loss per trade.
- Maximum open risk and portfolio loss.
- Daily realized/unrealized loss threshold.
- Maximum drawdown threshold.
- Maximum margin utilization and minimum free-funds buffer.
- Maximum position size and order size.
- Maximum net delta/gamma/vega/theta.
- Maximum number of open strategies.
- Expiry-day and event-risk restrictions.
- Per-underlying and per-sector concentration.
- Maximum allowed slippage and spread width.

Thresholds must be account- and user-configurable only within administrator-approved ranges. Defaults must be conservative and clearly identified as policy choices, not universal advice.

### 13.4 Kill switch and circuit breakers
- Kill switch must be accessible from every live trading screen.
- Backend must enforce it; frontend state alone is insufficient.
- Stop new orders immediately.
- Cancel eligible open orders.
- Apply configured position action: hold, hedge, or flatten, subject to explicit policy.
- Prevent automatic restart without authorized reset.
- Persist trigger reason, timestamp, actor, affected account, and actions.
- Test the kill switch through fault injection and production-safe drills.

### 13.5 Risk Control Center UI
Must show:
- Paper/live mode and account.
- Agent/strategy certification state.
- Current P&L and drawdown.
- Margin used, free funds, and utilization.
- Position and portfolio Greeks.
- Open orders, partial fills, and reconciliation issues.
- Risk limits with used/remaining values.
- Alerts and breached controls.
- Kill switch and trading pause.
- Audit timeline and recent decisions.

---

## 14. AI Agent Certification Framework

### 14.1 Certification objective
Certification is an evidence-backed authorization to operate a specific agent/model version, strategy set, instrument universe, broker, account type, policy, and execution adapter in a defined mode.

Certification is not a badge or an assertion by the agent. It is a backend-enforced release control.

### 14.2 Certification domains
| Domain | Purpose |
|---|---|
| D1 Data integrity | Completeness, freshness, timestamps, point-in-time integrity |
| D2 Research integrity | No lookahead, reproducibility, valid OOS protocol |
| D3 Strategy validity | Leg structure, payoff, expiry, contract eligibility |
| D4 AI behavior | Schema compliance, grounded explanations, safe no-trade behavior |
| D5 Pricing and Greeks | Calculation correctness, provenance, scenario consistency |
| D6 Risk enforcement | All paths governed; limits and kill switch work |
| D7 Execution reliability | OMS states, idempotency, partial fills, reconciliation |
| D8 Paper performance | Sufficient conservative paper/shadow evidence |
| D9 Security and permissions | RBAC, secrets, approvals, account boundaries |
| D10 Operations | Monitoring, incident response, rollback, audit retention |

### 14.3 Certification assertions
#### Data assertions
- Every decision references a timestamped data snapshot.
- Stale or missing critical data blocks new orders.
- Historical features are point-in-time correct.
- Contract metadata is valid for the decision date.
- Data source and calculation provenance are retained.

#### Research assertions
- Backtest is reproducible from immutable dataset and code/model versions.
- No future data is used.
- Costs and execution assumptions are documented.
- OOS and walk-forward results are present.
- Baselines and ablations are included.
- Insufficient sample size prevents promotion.

#### Strategy assertions
- All legs map to valid contracts.
- Strategy structure matches the approved template or approved custom definition.
- Payoff, breakevens, max loss, margin, and Greeks are calculated independently.
- Unsupported or unbounded risk is explicitly identified and policy-approved.
- Order quantities and lot multiples are valid.

#### AI assertions
- Output conforms to the versioned schema.
- Every material claim is grounded in available evidence.
- Invalid or unsupported strategies are rejected.
- Agent correctly returns no-trade under unsafe conditions.
- Prompt injection and malicious market-data text do not alter permissions.
- Agent cannot invoke prohibited execution or policy tools.

#### Risk assertions
- All entry, modify, cancel, recovery, and scheduled paths are risk-governed.
- Max drawdown and loss thresholds are actually evaluated by backend logic.
- Kill switch is reachable and enforced.
- Risk checks fail closed when dependencies are unavailable.
- Every rejection and authorization is auditable.

#### Execution assertions
- Duplicate requests do not create duplicate orders.
- Partial fills and legging exposure are handled safely.
- Unknown broker state triggers reconciliation, not blind resubmission.
- Position and funds reconciliation is performed.
- Recovery actions respect current risk policy and kill-switch state.

### 14.4 Fault-injection tests
Test at minimum:
- Stale or missing quotes.
- Broker API timeout after order submission.
- Duplicate callbacks and duplicate order requests.
- Partial fill on one leg.
- Broker rejection on a later leg.
- Market-data disconnect.
- Risk service unavailable.
- Database or audit write failure.
- Kill switch during an open order.
- Margin increase or funds shortfall.
- Model output malformed or contradictory.
- Incorrect instrument metadata.
- Restart while an order is in an unknown state.

### 14.5 Paper certification
Paper certification requires:
- A defined minimum number of sessions and trades appropriate to the strategy.
- Conservative execution simulation.
- No unresolved critical safety defects.
- Acceptable risk-limit behavior.
- Reproducible decisions and audit records.
- Performance evaluated after costs, with uncertainty reported.
- Evidence across relevant market regimes where possible.

Do not use an arbitrary short paper run as proof of robustness. Minimum sample size and observation period must be preregistered per strategy class.

### 14.6 Certification statuses
- `NOT_CERTIFIED`
- `RESEARCH_CERTIFIED`
- `PAPER_CERTIFIED`
- `SHADOW_CERTIFIED`
- `RESTRICTED_LIVE_CERTIFIED`
- `SUSPENDED`
- `RETIRED`

Status transitions require authorized approvals and stored evidence. Critical incidents, model changes, data-source changes, risk-policy changes, or adapter changes may trigger suspension or recertification.

### 14.7 Certification record
Persist:
- Agent/model and prompt versions.
- Strategy and strategy-template versions.
- Instrument universe and expiry scope.
- Broker, account, and execution adapter.
- Risk policy version.
- Dataset and backtest run IDs.
- Paper/shadow run IDs.
- Test suite results and fault-injection evidence.
- Approvers, timestamps, scope, restrictions, expiry date, and revocation reason.

At order time, backend authorization must verify the certification record matches the exact context. Any mismatch must reject the order.

---

## 15. User Experience and Screens

### 15.1 Core screens
1. Market Intelligence Dashboard.
2. Futures & OI Intelligence.
3. Options Chain.
4. Strategy Builder and Payoff Analyzer.
5. AI Strategy Proposals and Ranking.
6. Historical Replay Lab.
7. Paper Trading Desk.
8. Shadow Mode Monitor.
9. Live Trading Desk.
10. Risk Control Center.
11. Agent Certification Center.
12. Audit and Decision Replay.
13. Broker and Account Settings.

### 15.2 UX requirements
- Mobile-first, minimal, low cognitive load.
- Distinguish paper, shadow, and live with persistent labels.
- Show data freshness and source near values.
- Explain why a strategy was proposed and why it was rejected.
- Make max loss, margin, and capital requirements prominent before approval.
- Never hide risk warnings behind secondary interactions.
- Confirmation flows must summarize legs, quantity, price assumptions, capital, max loss, and account.
- Kill switch must be visible and accessible in live mode.
- Use accessible colors, labels, keyboard support, and responsive layouts.

---

## 16. APIs and Service Contracts

Representative APIs (final paths and schemas to be defined during technical design):
- `GET /market/regime`
- `GET /market/futures-intelligence`
- `GET /market/options-chain`
- `POST /strategies/validate`
- `POST /strategies/payoff`
- `POST /strategies/scenarios`
- `POST /ai/proposals`
- `POST /research/backtests`
- `GET /research/backtests/{run_id}`
- `POST /paper/sessions`
- `POST /shadow/sessions`
- `POST /orders/authorize`
- `POST /orders`
- `POST /risk/kill-switch`
- `GET /risk/status`
- `POST /certification/evaluate`
- `GET /certification/{certification_id}`
- `GET /audit/decisions/{decision_id}`

All endpoints must authenticate, authorize, validate schema, enforce idempotency where applicable, and produce audit events for consequential actions.

---

## 17. Logical Data Model

Recommended logical entities:
- `market_data_snapshot`
- `instrument_master_version`
- `options_chain_snapshot`
- `futures_snapshot`
- `market_regime_snapshot`
- `strategy_template`
- `strategy_definition`
- `strategy_proposal`
- `strategy_leg`
- `pricing_result`
- `greeks_snapshot`
- `scenario_result`
- `margin_estimate`
- `backtest_run`
- `backtest_event`
- `backtest_trade`
- `paper_session`
- `paper_order`
- `paper_fill`
- `shadow_decision`
- `live_order`
- `live_fill`
- `position_snapshot`
- `risk_policy`
- `risk_decision`
- `risk_event`
- `kill_switch_event`
- `agent_version`
- `model_version`
- `certification_record`
- `certification_test_result`
- `broker_account`
- `broker_adapter_version`
- `audit_event`
- `incident_record`

Every decision/order should reference the relevant data snapshot, model, strategy, risk policy, certification, and execution adapter versions.

---

## 18. Security, Reliability, and Non-Functional Requirements

### Security
- Encrypt secrets and sensitive data at rest and in transit.
- Use managed secret storage; never expose broker credentials to the LLM.
- Enforce least privilege and RBAC.
- Separate paper and live credentials and account contexts.
- Require strong authentication and step-up confirmation for sensitive live actions.
- Maintain immutable audit records.
- Protect against prompt injection from external data and documents.

### Reliability
- Idempotent order submission and safe reconciliation.
- Fail closed on critical risk/data dependency failures.
- Durable event and audit storage.
- Monitoring, alerting, and incident procedures.
- Backup, recovery, and tested rollback.
- Defined service-level objectives for market data, risk authorization, and OMS.

### Performance
- Options-chain updates should be responsive while preserving freshness metadata.
- Payoff and scenario calculations should update interactively.
- Risk authorization should be low-latency without skipping required checks.
- Backtests may run asynchronously with progress and reproducible run identifiers.

### Observability
Track:
- Data freshness, gaps, and source errors.
- Agent proposal/rejection rates and no-trade frequency.
- Risk rejections and limit breaches.
- OMS latency, order state duration, and reconciliation gaps.
- Paper/live slippage and fill-rate differences.
- Model/feature drift and performance degradation.
- Kill-switch activations and incidents.

---

## 19. Acceptance Criteria

The platform is not ready for live use unless all relevant criteria pass.

### Market data and research
- [ ] Critical data is timestamped and provenance is retained.
- [ ] Stale or incomplete data blocks affected decisions.
- [ ] Historical instrument metadata is point-in-time correct.
- [ ] Backtest replay is deterministic and reproducible.
- [ ] Lookahead and leakage tests pass.
- [ ] Costs, spreads, slippage, and partial fills are modeled.
- [ ] OOS and walk-forward evaluation are available.
- [ ] Baseline and ablation comparisons are included.

### Strategy and AI
- [ ] Every proposal conforms to the structured schema.
- [ ] Invalid legs, contracts, and quantities are rejected.
- [ ] Payoff, max loss/profit, breakevens, Greeks, and margin are independently calculated.
- [ ] AI can return no-trade.
- [ ] AI cannot execute directly or change policy.
- [ ] Explanations are traceable to evidence.

### Risk and execution
- [ ] Risk engine governs every order path.
- [ ] Drawdown, loss, margin, exposure, and quantity limits are enforced.
- [ ] Kill switch is accessible and backend-enforced.
- [ ] Duplicate submissions are prevented.
- [ ] Partial fills, timeouts, and unknown broker states are safely reconciled.
- [ ] Multi-leg interim risk is controlled.
- [ ] Audit trail captures decisions, approvals, and order state changes.

### Certification
- [ ] Certification is scoped and versioned.
- [ ] Paper/shadow evidence meets preregistered criteria.
- [ ] Critical fault-injection tests pass.
- [ ] Live authorization checks certification on the backend.
- [ ] Any relevant version/scope mismatch blocks execution.
- [ ] Suspension and revocation are tested.

---

## 20. Implementation Roadmap

### Phase 0 — Safety and data foundations
- Instrument master and data quality framework.
- Timestamped options-chain and futures snapshots.
- Risk engine service and common authorization contract.
- Audit/event model.
- Fix all critical risk-path coverage gaps.

### Phase 1 — Strategy research and builder
- Strategy templates and leg schema.
- Options chain and editable builder.
- Deterministic payoff, Greeks, scenario, and margin services.
- Market intelligence dashboard.

### Phase 2 — Historical Replay Lab
- Event-driven backtester.
- Realistic fills and cost model.
- Point-in-time and leakage tests.
- Walk-forward, OOS, baseline, and ablation reports.

### Phase 3 — Paper and shadow
- Conservative paper OMS.
- Shadow decisions on live data.
- Paper certification workflow.
- Expected-versus-observed execution diagnostics.

### Phase 4 — Certification and restricted live
- Certification center and evidence records.
- Broker adapter hardening and reconciliation.
- Risk Control Center.
- Restricted live rollout with user confirmation and strict limits.

### Phase 5 — Controlled expansion
- Broaden strategy families and instruments only with evidence.
- Carefully evaluate automation levels.
- Add monitoring for drift, incidents, and recertification.
- Increase autonomy only after demonstrated reliability and explicit governance.

---

## 21. Live Readiness Gate

Before any agent can place a live order, all of the following must be true:

1. The model/agent version is certified for the intended use.
2. The strategy template and version are certified.
3. The underlying, contract, and expiry are within the certified universe.
4. The broker, account, and execution adapter are certified.
5. The current risk policy is active and matches the certification.
6. Market data is fresh and complete enough for the decision.
7. Deterministic pricing, payoff, Greeks, and margin checks pass.
8. Portfolio-level risk checks pass.
9. Required user authorization is present.
10. OMS and reconciliation services are healthy.
11. Kill switch is inactive and available.
12. All evidence and the authorization decision are persisted.

If any condition fails, the order must be rejected or held for authorized review. There is no AI override.

---

## 22. Final Product Positioning

Nivesh should be positioned as an **AI-assisted, evidence-driven F&O intelligence and trading platform**, not as an unrestricted autonomous trading bot.

The differentiator is not merely that AI can suggest a strategy. It is that Nivesh combines:
- Explainable market intelligence.
- Structured and validated strategy proposals.
- Deterministic pricing and risk.
- Realistic historical replay.
- Separate paper, shadow, and live modes.
- Independent risk controls.
- Evidence-backed agent certification.
- Auditable, controlled execution.

The platform earns live capability through evidence, testing, and authorization—not through model confidence alone.
