# Nivesh F&O AI Trading Intelligence, Agent, Backtesting, Risk Management & Certification Platform

**Product Requirements Document (PRD)**  
**Version:** 2.1  
**Status:** Comprehensive product and engineering specification, with implementation status and build plan (§23–27)  
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

---

## 23. F&O Lab Implementation Status and Gap Analysis

**Assessment date:** 2026-10-24  
**Baseline reviewed:** `docs/ai_research/Nivesh_FO_AI_Trading_Intelligence_PRD_v2.md` (879 lines)  
**Code baseline:** `origin/dev` at `307c2994` (merge of PR #332, 2026-10-24)  
**Execution direction:** live strategy execution will use the **Kite Connect API** when it is built (product decision, 2026-10-24).  
**Evidence:** `docs/AI_TRADING_BOT_PRD_GAP_ANALYSIS.md` holds the section-by-section analysis, file and line citations, and the checks that were run:
- backend tests: 1,701 passed and 10 failed across 49 files
- Playwright on mocked APIs: 513 passed, 32 failed, 16 skipped
- typecheck: 0 errors
- read-only staging warehouse and Mongo counts

Treat this section as a code and data assessment, not a deployment certification.

This section separates the target-state requirements in Sections 1–22 from what the F&O Lab implements today. It claims nothing beyond the evidence in the gap analysis.

### 23.1 Status definitions

- **Met / present:** A documented implementation exists for the requirement, subject to any noted verification limits.
- **Partial:** Some supporting implementation exists, but important requirements or coverage remain absent.
- **Missing:** The requirement is not implemented in the reviewed scope.
- **Absent by design:** The product deliberately has no such capability today; this is not automatically a defect, but it remains a future requirement if the product moves toward that mode.

### 23.2 PRD-to-F&O-Lab scorecard

| PRD section | Capability | Assessment | Main gap / qualification |
|---|---|---|---|
| §5 | Architecture and authority boundaries | Partial | Pricing and payoff are deterministic and no LLM sits in a decision path. There is no schema-validator, authorization or certification service. |
| §6.1 | Market regime | Partial | A versioned five-regime rule (India VIX, Nifty trend vs breadth, 50-session average). Realized-vs-implied, liquidity/spread and event regimes, and transition history, are missing. |
| §6.2 | Futures intelligence | Partial | Four end-of-day build-up labels, with OI summed over all expiries. A 5-minute intraday futures series is coded but recorded nothing on staging. Confidence, basis term structure and roll tracking are missing. |
| §6.3 | Options-chain intelligence | Partial | End-of-day OI, volume, PCR, max pain, walls and Black-76 Greeks. Stored bid/ask, quote age, spread and intraday snapshots are missing. |
| §6.4 | Expiry / term structure | Partial | Weekly/monthly selector and expected move. IV, OI and basis term structure, and tracking through the month, are missing. |
| §6.5 | Greeks and volatility | Partial | Calculated Black-76 Greeks at a fixed 5.75% rate. Provenance, IV history, skew, stored snapshots and portfolio Greeks are missing. |
| §7 | AI strategy agent | Missing | No F&O agent loop and no versioned proposal contract. The copilot narrates F&O data as free text. |
| §8 | Strategy library and builder | Partial — strongest area | Two builders: the Desk builder (server payoff) and the Options Lab (browser payoff with a model chance of profit). Calendars, diagonals and undefined-risk structures are rejected. The payoff is not net of charges, and the Desk screen contradicts itself on margin. |
| §9 | Strategy ranking | Partial | Two rule-based rankings that record each input's contribution. Research found no skill beyond OI-only, price-only or random picks. Costs, liquidity, portfolio fit, drift and walk-forward evidence are missing. |
| §10 | Backtesting and research integrity | Partial for futures signals; missing for options | Pre-registered, point-in-time futures-signal studies. No event-driven multi-leg options backtester and no realistic fill model. |
| §11 | Paper / shadow trading | Partial | Immutable F&O paper structures, but diagnostic and end-of-day only. Closing a structure never releases its reserved capital. F&O shadow mode is missing. |
| §12 | Live OMS | Absent by design | No order code. Kite Connect is the chosen live adapter, and today's Kite integration is read-only. |
| §13 | Independent risk engine / Risk Control Center | Partial for AI-trader cash; missing for F&O | The governor covers AI-trader cash only and fails open on unknown inputs. The kill switch is backend-enforced, but it has no UI and is self-reset. There is no Risk Control Center. |
| §14 | Certification | Missing | No agent or strategy certification, no order-time enforcement and no fault-injection suite. Equity stage gates exist to reuse. |
| §15 | UX / screens | Partial | Trust lines, paper labels and the SEBI note exist. Replay, shadow, live, certification and risk-centre screens are missing. |
| §16 | APIs | Partial | Equivalents exist for the chain, payoff, risk status and kill switch. The other target routes are not implemented. |
| §17 | Data model | Partial | Of 35 entities: 2 exist, 15 are partial, 18 are missing. There is no snapshot linkage, no Greeks or intraday chain store, and no agent or certification records. |
| §18 | Security / reliability / observability | Partial | Broker tokens are encrypted. Further security and operations findings were reported to the owner separately (see P0.6). The data-quality rollup is blind for the F&O feed. |
| §21 | Live readiness gate | Missing | No order path exists, so none of the 12 readiness conditions can be enforced on an order. Some inputs exist: kill switch, margin calculator, deterministic payoff and Greeks. |

### 23.3 Current implementation details and known limitations

#### Market data and intelligence

`nidp.fno_bhavcopy` holds end-of-day NSE F&O data: 261 sessions from 2025-10-01 through 2026-10-23, 10,298,812 rows (queried on 2026-10-24). Its rows carry prices, OI, change in OI, volume and the daily lot size, but no bid/ask, IV, Greeks, quote time or quality flag. Existing `routes/fno.py` endpoints cover expiries, chain, futures, positioning history, build-up and candidate scans, the forward test, and margin.

Known gaps:
- **Regime:** `desk-regime-v1` combines India VIX ≥ 20, Nifty trend vs breadth, and the close against the 50-session average. It does not include a realized-vs-implied regime, a liquidity/spread regime, event conditions, or stored transition history.
- **Futures:** the build-up labels take the price change from the nearest expiry but sum OI over all expiries. Signals have no confidence or conflicting-evidence field, and there is no basis-across-expiries or roll tracking. A 5-minute intraday snapshot of near-month futures is coded but recorded no documents on staging in the week checked.
- **Options chain:** coverage includes OI, change in OI, volume, PCR, max pain, walls and calculated Greeks per strike. It lacks stored bid/ask, quote age, spread width and intraday snapshots. Option contracts are not on the live Kite feed. Two live option reads exist, and neither is stored:
  - up to 40 named legs by REST, per screen request, with no bid/ask
  - opt-in bid/ask for the plan engine's preferred legs, through the user's own ICICI Direct session
- **Expiry:** weekly/monthly expiry selection and expected move exist; term structure and within-month IV, OI and basis tracking do not.
- **Greeks and IV:** Greeks use Black-76 with IV solved by bisection and a fixed 5.75% risk-free rate. There is no broker-Greek provenance flag, no IV history (so no IV rank or percentile), no skew, no stored Greeks snapshot, and no portfolio-level Greeks. Per-leg Greeks are computed but not shown in the Desk builder.
- **Freshness:** the DaaS F&O routes, scans and margin serve the latest date without a freshness check. Only the plan engine blocks stale data.

#### AI strategy agent

There is no F&O AI agent loop and no structured proposal schema with `model_version` and `data_snapshot_id`. The AI Trader is a cash-equity, long-only DSL.

The copilot chat already narrates F&O positioning and the user's broker F&O positions. It does this as free text, with no tool calling, and it writes nothing to paper trades, plans or risk controls.

The deterministic candidate generation, selection, evidence ledger and `plan` / `wait` / `no_trade` / `insufficient_data` statuses are useful foundations. They are not an F&O agent, and they do not yet create an agent-certification target.

#### Strategy builder, payoff, and margin

Existing components:
- Server engine: templates in `strategy_plan/templates.py`; exact expiry payoff, breakevens and max P/L in `payoff.py` (`payoff-v1`); pre-expiry Black-76 repricing in `pre_expiry.py`.
- Desk builder (`FnoBuilder.tsx`): renders server output.
- Options Lab (`OptionsLab.tsx`): computes payoff, net Greeks and a risk-neutral chance of profit in the browser (`screens/trading/payoff.ts`, `odds.ts`). The chance of profit uses one volatility with no skew and is labelled a model estimate.
- Broker margin and charges: `POST /api/fno/margin` uses Zerodha's `basket_order_margins` (`services/fno_margin.py`). It returns margin plus brokerage, STT, exchange, SEBI, stamp duty and GST.

Known gaps:
- The payoff includes only slippage and flat brokerage. It is not net of the broker charges.
- The margin route needs the platform's daily Kite login and returns 503 without it.
- There is no margin buffer or free-funds view.
- The server engine has no probability of profit.
- The payoff payload always returns `margin: None` with “No margin source exists in this system” (`strategy_plan/engine.py`). The Desk screen shows that next to the working broker-margin strip.
- Calendar and diagonal spreads are rejected (mixed expiries), and so are short straddles, short strangles and naked shorts (undefined risk). Covered call and protective put are accepted by the engine but not offered in the Desk builder, which has option legs only.
- The Desk builder's “Record as paper trade” button is disabled with stale text. F&O paper trades are recorded from the plan actions instead.

#### Ranking and research

Existing ranking:
- `regime_fit.py` ranks priced structures by regime fit (direction 40, volatility 30, breadth 15, positioning 15). It explicitly says it is not a performance ranking, and it has no minimum fit score.
- `fno_candidates` v2 uses OI 30%, price 20%, volume 15%, options 15%, delivery 10% and technicals 10%, and records each input's contribution. Its thresholds are labelled `research_setting_not_validated`.
- Research compared the production ranking with OI-only, price-only and random picks and found no ordering skill. No threshold survived validation and test.

Missing ranking evidence and inputs:
- Expected return after costs.
- Liquidity and fill probability.
- Portfolio fit and correlated exposure.
- Drift tracking.
- A live baseline comparison and walk-forward evidence.

Research foundations worth retaining:
- Pre-registration documentation.
- Discovery/validation/test splits.
- Point-in-time test that injects poisoned future rows.
- Permutation tests.
- Frozen baseline hash.
- Honest reporting statuses such as `research_result`, `inconclusive`, and `not_supported`.

Backtesting today covers futures signals only. It uses cash prices as a proxy for the future, with basis and roll not modelled, and a flat assumed 0.15% round-trip cost. The following are all missing:
- a multi-leg options backtester
- bid/ask or intraday data
- a versioned instrument master and roll model (daily lot sizes are stored)
- fill, partial-fill and latency simulation
- a sealed final options OOS set
- walk-forward evaluation
- an AI-versus-baseline ablation

The Stage B3 options/Greeks study is pre-registered, but no code implements it.

#### Paper, shadow, live, and risk

Paper foundations:
- F&O paper structures are stored in `desk_paper_trades` with `kind: "strategy"` (`desk_strategy_trades.py`, `desk-paper-v3`). They hold immutable legs and an `entry_record_hash` over client-supplied versions, with lifecycle events and intrinsic-value settlement.
- `services/paper_account.py` reserves capital-at-risk, explicitly not exchange margin.

Paper gaps and defects:
- F&O entries are taken at the typed prices, all legs at once, and marked end-of-day. This is diagnostic paper, not conservative paper.
- No market snapshot is stored.
- There are no pause, resume or reset sessions, no duplicate protection, and no F&O shadow mode.
- Closing an F&O structure never releases its paper-account reservation, so its capital stays blocked and its P&L never reaches cash.
- F&O exits run only when someone opens the paper-trade list; the evening job skips them.
- `services/fno_forward` is coded, but its nightly job is not installed and its collection does not exist on staging.

Live execution is absent by design. There are no order-placement methods, OMS state machine, idempotency, broker order/trade mapping, reconciliation or multi-leg sequencing. The Kite integration covers the ticker, the NFO instrument list and the basket-margin calculator, and it is read-only. Broker adapters read holdings and positions only.

Risk foundations:
- `risk_governor.py` is deterministic and imports no strategy or AI code.
- `risk_controls.py` has a backend-enforced, per-user kill switch and halt, with a reason required in both directions.
- The `risk_control_audit` and `risk_decisions` logs are append-only by convention.

Risk gaps:
- The governor runs only on AI-trader signals and confirmations. It is long-only cash-equity logic and fails open when an input is unknown.
- It has no net Greeks, margin utilization, lot/quantity validation, expiry-day rules, correlation, or stress checks. Its limits are a constant, and the event rule is never fed.
- F&O paper trades and journal fills are not governed.
- While any F&O structure is open, drawdown is unknown, so the drawdown halt cannot fire.
- The kill switch blocks new paper risk on three paths but does not cancel orders or manage open positions. Journal ENTRY fills bypass it. The same user resets it. No screen calls `/api/risk/*`.
- `RiskDesk.tsx` is a one-stock sizing panel, not a Risk Control Center.

#### Certification, APIs, data model, and operations

Certification:
- `nidp/shared/certification.py` certifies data-lake dates only.
- There is no agent or strategy status lifecycle, certification record, backend order-time enforcement, fault-injection suite, or preregistered paper sample-size policy.
- The AI Trader's stage ladder (draft → backtested → paper → assisted → retired), its sealed holdout and its calibration reporting are reusable building blocks from equities.

UX:
- Five F&O views exist: build-up, candidates, NIFTY/BANKNIFTY, chain/analyse, and paper strategies. A trust line on module cards states source, as-of, mode and maker.
- Missing: Historical Replay Lab, Shadow Monitor, Live Desk, Certification Center and Risk Control Center. The audit screen states that no run records exist to replay, and no screen shows a kill switch.
- Persistent mode labels are not yet required by existing execution behavior, but become mandatory before multiple modes are exposed.

APIs:
- Target PRD routes such as `/strategies/validate`, `/ai/proposals`, `/research/backtests`, `/orders/authorize`, `/certification/*` and `/audit/decisions/*` are not implemented.
- Existing equivalents: `/api/fno/*`, `/api/desk/strategy/payoff|plan|ideas|top|plans`, `GET /api/risk/status`, `PUT /api/risk/kill-switch` and `GET /api/risk/decisions`.

Data model:
- Of the 35 target logical entities in §17, 2 exist (`broker_account`, `kill_switch_event`), 15 are partial and 18 are missing.
- Daily chain and futures rows in `nidp.fno_bhavcopy` partly cover `options_chain_snapshot` and `futures_snapshot` at end-of-day granularity.
- `risk_decisions` partly covers `risk_decision`.
- `greeks_snapshot`, intraday chain snapshots, `data_snapshot_id` linkage, `strategy_proposal`, durable F&O `backtest_run`, `agent_version` and `certification_record` do not exist.

Operations and security:
- Broker tokens are AES-256-GCM encrypted.
- Findings on secret storage, backup coverage, LLM input handling and endpoint authentication were reported to the owner separately, because the repository is public. They are tracked as P0.6.
- The data-quality rollup reads `NONE` for the F&O feed. Sessions that failed a BLOCK row-count rule are still served.

### 23.4 Verification and scope caveats

The assessment explicitly states:
- Detail comes from code, documents and `test_reports/OVERRIDE_*.md`, read by the author and by review agents. The gap analysis marks which claims the author re-checked against a clean `origin/dev` tree.
- **Backend tests:** 1,701 passed and 10 failed. The failures are 8 tests that need `pytest-asyncio` and 2 stale paper-simulation tests.
- **Playwright** (mocked APIs, so UI behaviour, not live data): 513 passed, 32 failed, 16 skipped. Of the failures, 31 are a strategy-graphs spec that needs a test-only build flag set by a script that is not in the repo (with the flag it passes), and 1 is a date-dependent assertion.
- **Typecheck:** 0 errors.
- **Not reproduced by tests:** the paper-reservation, drawdown-halt and journal-fill findings come from reading code.
- **Not checked:** whether staging runs exactly `origin/dev`, and why the intraday futures series is empty.
- **Policy decisions:** certification sample sizes and risk-limit ranges cannot be determined by code inspection alone.

**Engineering rule:** Do not convert a code-existence claim into a “working,” “deployed,” or “certified” claim without a reproducible test, staging evidence, and/or operational evidence appropriate to the claim.

### 23.5 Strengths to preserve

1. Pre-registration discipline and honest “no validated edge” reporting.
2. Point-in-time tests with poisoned future rows and first-write-wins forward-test records.
3. `NO_TRADE`-style outcomes and explicit labels for unvalidated thresholds.
4. Separation between deterministic governor / kill switch and strategy or AI code; read-only broker adapters; a copilot that cannot call tools.
5. Deterministic pricing, payoff, and broker margin and charges calculation.
6. Research evidence artifacts, frozen baseline hashes, and experiment identifiers.
7. Trust lines that state the source, freshness and maker of displayed figures.

---

## 24. Implementation Backlog and Dependency-Ordered Build Plan

The target PRD is not a declaration that all capabilities already exist. Build and release in dependency order. Do not begin live execution merely because the UI or agent proposal flow is complete.

### 24.1 Priority definitions

- **P0 — Foundational blocker:** Required for trustworthy F&O research, paper operation, or any future order authorization. No downstream feature should claim readiness while its P0 dependencies are open.
- **P1 — Research/product completeness:** Needed for meaningful strategy comparison, capital transparency, and conservative paper validation.
- **P2 — Advanced capability:** Add only after foundational correctness and evidence gates pass.
- **P3 — Live execution / regulated rollout:** Last; requires regulatory review, broker readiness, certification, and explicit operational approval.

### 24.2 P0 — Data, durable evidence, and F&O risk foundations

#### P0.1 Intraday options market-data collection
**Build**
- Establish supported feed/provider coverage for option contracts, not only underlying/futures.
- Persist timestamped chain snapshots with bid, ask, available sizes, LTP, volume, OI, OI change, IV, and Greeks where supplied.
- Store quote timestamps and calculate quote age and spread width.
- Record data source, instrument identifier, exchange timestamp, ingest timestamp, and quality flags.
- Monitor missing contracts, delayed updates, feed outages, and coverage.
- Find out why the coded 5-minute intraday futures series records nothing on staging, and fix it.

**Acceptance criteria**
- [ ] A documented coverage matrix identifies supported underlyings, expiries, strikes, session hours, and historical depth.
- [ ] Snapshot schema preserves source and timestamps without overwriting historical observations.
- [ ] Stale, crossed, malformed, or missing quotes are flagged.
- [ ] Data-quality dashboards and alert thresholds are operational.
- [ ] A replayable sample session can be reconstructed from stored snapshots.

#### P0.2 IV history and volatility features
**Build**
- Persist IV observations by contract and timestamp.
- Add IV rank/percentile only when sufficient history and a documented lookback are available.
- Add skew and expiry term-structure measures.
- Version the calculation methodology and rate/dividend assumptions.
- Store whether Greeks are broker-provided or calculated, including method and input snapshot.

**Acceptance criteria**
- [ ] IV history coverage and minimum lookback are visible.
- [ ] IV rank/percentile are unavailable—not fabricated—when history is insufficient.
- [ ] Greek and IV calculations are reproducible from saved inputs.
- [ ] Fixed assumptions such as the 5.75% risk-free rate are explicit, configurable/versioned, and not silently treated as current market truth.

#### P0.3 Snapshot and decision evidence store
**Build**
- Introduce durable records for `data_snapshot_id`, strategy proposals, pricing results, risk decisions, and audit events.
- Link every proposal, backtest, paper decision, and later order to immutable versions of market data, instrument master, model, strategy, risk policy, and code/config.
- Keep report files as artifacts, but store queryable run metadata and status in the database.

**Acceptance criteria**
- [ ] A decision can be reconstructed from its identifiers without relying on mutable “latest” records.
- [ ] Snapshot and decision references are mandatory in downstream F&O workflows.
- [ ] Missing evidence linkage blocks promotion and any future live authorization.
- [ ] Audit writes have defined durability and failure behavior.

#### P0.4 F&O-aware deterministic risk engine
**Build**
- Extend or replace the equity-only governor with F&O-aware checks.
- Evaluate contract validity, lot multiples, strategy max loss, margin, margin buffer, portfolio Greeks, stress scenarios, expiry/event restrictions, concentration, and interim multi-leg exposure.
- Ensure every entry, modification, recovery, and future execution path calls the same authoritative risk contract — including F&O paper trades, journal fills and plan saves, which are ungoverned today.
- Fail closed if critical data or risk dependencies are unavailable (the current governor skips rules whose inputs are unknown).
- Make drawdown computable while F&O structures are open.
- Put the kill switch on screen, require elevated authorization to reset it, and gate journal ENTRY fills with it.

**Acceptance criteria**
- [ ] F&O proposals and paper orders are evaluated by the F&O risk engine.
- [ ] Limits are versioned and have explicit used/remaining values.
- [ ] Risk decisions record inputs, checks, outcome, reason codes, and policy version.
- [ ] Tests prove all known order/ticket paths are governed.
- [ ] The existing kill switch is accurately documented as blocking new actions only until broader position/order actions exist.
- [ ] No claim is made that it cancels, hedges, or flattens positions unless those functions are implemented and tested.

#### P0.5 Repair known contradictions, defects and data aggregation flaws
**Build**
- Correct futures OI aggregation to be expiry-aware; expose per-expiry evidence.
- Align the strategy-plan margin output with the margin calculator. The plan payload still reports “No margin source exists”.
- Release the paper-account reservation, and credit the net P&L, when an F&O paper structure closes.
- Run F&O paper exits in the evening job, not only when the paper-trade list is opened.
- Fix the stale “Record as paper trade” text and the stale “no futures subscribed” docstrings.
- Clarify paper capital-at-risk versus exchange/broker margin.
- Audit data-lake certification versus strategy/agent certification naming to prevent semantic confusion.
- Make readers of `nidp.fno_bhavcopy` respect validation results, and fix the data-quality rollup that reads `NONE`.

**Acceptance criteria**
- [ ] Tests cover OI aggregation across multiple expiries.
- [ ] A test proves that closing an F&O paper structure returns its reservation and books its P&L.
- [ ] UI/API messaging matches actual margin source availability.
- [ ] Users can distinguish estimated capital-at-risk, estimated margin, and broker-confirmed margin.
- [ ] Documentation and code contracts agree.

#### P0.6 Security and operational fixes found in the assessment
**Build**
- Close the security and operations findings reported privately with this assessment. They cover endpoint authentication, secrets at rest, backup coverage and LLM input handling.
- Make Kite Connect the only route to a trading platform.

**Acceptance criteria**
- [ ] No unauthenticated route can reach a trading platform.
- [ ] Secrets are encrypted at rest, and their key custody is documented.
- [ ] Backups cover every datastore, and a restore has been tested.
- [ ] External text reaching an LLM prompt is delimited and tested against injection cases.

### 24.3 P1 — Strategy-builder and ranking completeness

#### P1.1 Complete costs and payoff outputs
**Build**
- Add STT, exchange charges, applicable taxes/fees, brokerage, and slippage using versioned fee schedules. The broker calculator already returns these charges; net them into the payoff.
- Add POP to the server engine only with a documented probability model and assumptions. Reconcile it with the Options Lab's client-side chance of profit.
- Add margin buffer, available funds, and capital-after-trade views.
- Decide whether calendars and diagonals are wanted. Offer covered calls and protective puts in the Desk builder, and test each supported template.
- Show per-leg Greeks, which the backend already computes.

**Acceptance criteria**
- [ ] Net payoff and P&L include all applicable configured costs.
- [ ] Fee schedule and assumptions are timestamped/versioned.
- [ ] POP is labelled as a model estimate, not a certainty, and is omitted if assumptions/data are insufficient.
- [ ] Margin output identifies source, timestamp, availability, and fallback behavior.

#### P1.2 Portfolio Greeks and scenario risk
**Build**
- Aggregate leg-level Greeks to strategy and portfolio levels.
- Provide underlying, IV, and time shocks.
- Include expiry and near-expiry risk displays.
- Flag missing or stale Greek inputs.

**Acceptance criteria**
- [ ] Portfolio Greeks reconcile to constituent positions.
- [ ] Scenario calculations are deterministic and versioned.
- [ ] UI displays the assumptions and freshness of scenario inputs.

#### P1.3 Ranking research contract
**Build**
- Add expected return after costs, liquidity/fill probability, portfolio fit, and concentration features only when data supports them.
- Register hypotheses, feature definitions, thresholds, model versions, and evaluation windows.
- Compare against deterministic baselines and run walk-forward / OOS tests.
- Track feature contribution, drift, coverage, and score distributions.

**Acceptance criteria**
- [ ] Ranking is not described as predictive/performance ranking without evidence.
- [ ] Candidate thresholds remain labelled unvalidated until approved through research.
- [ ] Ranking evidence includes baseline, ablation, sample size, costs, and OOS results.
- [ ] The system can return no suitable candidate.

### 24.4 P2 — Options replay lab and conservative paper

#### P2.1 Event-driven multi-leg options backtester
**Build**
- Start with the preregistered Stage B3 options/Greeks study.
- Add historical instrument master, expiry/lot-size changes, and settlement/roll logic.
- Replay decisions against timestamped chain data.
- Model bid/ask, latency, slippage, partial fills, fees, and multi-leg execution/legging risk.
- Support walk-forward, sealed OOS, baseline, and AI-versus-rule ablations.

**Acceptance criteria**
- [ ] Backtests are deterministic from stored data and versioned configuration.
- [ ] Poisoned-future-data and leakage tests pass.
- [ ] Each simulated fill references an eligible quote and fill rule.
- [ ] Costs and fill assumptions are inspectable and sensitivity-tested.
- [ ] Expiry, settlement, and contract lifecycle cases have tests.
- [ ] Reports distinguish research results from validated/promotion-eligible evidence.

#### P2.2 Conservative paper execution
**Build**
- Upgrade EOD/diagnostic paper to quote-aware simulation.
- Add fill rules, latency, partial fills, rejected orders, spread/slippage, and margin-aware accounting.
- Store signal version and data snapshot.
- Add session pause/resume/stop/reset controls and clear mode labels.
- Add duplicate protection to paper-trade creation.
- Install and observe the F&O forward-test scheduled job.
- Add F&O shadow decisions without order submission.

**Acceptance criteria**
- [ ] Diagnostic paper is visibly distinguished from conservative paper.
- [ ] Paper records include model/strategy versions and market snapshot IDs.
- [ ] Forward-test job is scheduled, monitored, and produces durable records.
- [ ] Shadow mode cannot submit orders.
- [ ] Paper certification sample size and duration are preregistered per strategy class.

### 24.5 P3 — Certification, OMS, and restricted live

#### P3.1 Certification service
**Build**
- Implement certification statuses and scope.
- Store evidence, approvers, versions, limits, expiry, suspension, and revocation.
- Evaluate data, research, strategy, AI, risk, execution, security, and operational assertions.
- Require exact context matching at authorization time.

**Acceptance criteria**
- [ ] Certification is backend-enforced and cannot be granted by the AI.
- [ ] Any version/scope mismatch rejects authorization.
- [ ] Suspension/revocation immediately blocks new authorized orders.
- [ ] Fault-injection results and approvals are retained.

#### P3.2 OMS and broker order adapters (Kite Connect)
**Target adapter:** live strategy execution will use the Kite Connect API (product decision, 2026-10-24). Today's Kite integration is read-only by construction: the ticker, the NFO instrument list and the basket-margin calculator. Orders must run in the user's own Kite session, not in the platform session used for data and margins.

**Build**
- Only after data, risk, paper, and certification gates are satisfied.
- Implement order lifecycle state machine, idempotency, broker ID mapping, timeout handling, reconciliation, and safe retries.
- Map the lifecycle to Kite order statuses and order updates. Use our own idempotency keys plus Kite's order tag for correlation. Reconcile orders, trades, positions and funds.
- Design multi-leg execution with interim exposure controls and explicit abort/recovery paths.
- Maintain separate paper/live account state and credentials.

**Acceptance criteria**
- [ ] Duplicate requests cannot create duplicate orders.
- [ ] Unknown broker state triggers reconciliation, not blind retry.
- [ ] Partial fills and failed later legs have tested recovery paths.
- [ ] All actions are risk-authorized and auditable.
- [ ] Live execution is disabled by default and requires explicit account/user authorization.

#### P3.3 Regulatory and broker readiness
**Required before implementation of live order placement**
- Obtain domain-expert and legal/compliance review of applicable SEBI/exchange retail algo-trading rules, broker empanelment, algo registration, and broker-specific requirements.
- For Kite Connect, confirm Zerodha's requirements for a platform that places orders on users' behalf: order identification or tagging, any static-IP requirement for order APIs, order-rate limits, and session rules.
- Validate supported order types, multi-leg capabilities, API constraints, and broker terms.
- Document compliance conclusions and required product controls.

**Acceptance criteria**
- [ ] Regulatory review is documented and approved by the responsible authority.
- [ ] Broker and adapter requirements are documented.
- [ ] No live order path is enabled while compliance or broker prerequisites remain unresolved.

---

## 25. Release Gates and Exit Criteria

### Gate A — Data foundation complete
Required before trustworthy options research:
- Intraday option-chain data and coverage documented.
- IV history and provenance available.
- Historical instrument metadata and timestamps preserved.
- Snapshot/decision IDs persisted.
- Data-quality monitoring and stale-data behavior tested.

### Gate B — Research-ready
Required before promoting strategy/ranking claims:
- Event-driven options backtester implemented.
- Point-in-time and leakage tests pass.
- Costs, spreads, and execution assumptions are modeled.
- Walk-forward and sealed OOS evidence exists.
- Baselines and ablations are reported.
- Research outcomes are reproducible and preregistered.

### Gate C — Conservative-paper-ready
Required before calling paper evidence meaningful for live readiness:
- Conservative fill simulator implemented.
- Paper and shadow mode boundaries enforced.
- Risk engine evaluates F&O paper actions.
- Data snapshot and version linkage is complete.
- Forward-test job runs and records outcomes.
- Sample size and evaluation period are preregistered.

### Gate D — Restricted-live candidate
Required before any restricted live pilot:
- F&O risk engine governs every relevant path.
- Risk Control Center and backend kill switch behavior are tested.
- Certification service is implemented and backend enforced.
- OMS, reconciliation, idempotency, and multi-leg recovery pass fault-injection tests.
- Security and regulatory/broker reviews are complete.
- Live readiness gate in §21 passes for the exact context.
- Authorized human approval is recorded.

**A gate may not be waived by the AI agent.** Any exception must be an explicit, documented governance decision and must not bypass legal, exchange, broker, or safety requirements.

---

## 26. Consolidated Engineering Priority List

| Priority | Work item | Depends on | Why it matters |
|---|---|---|---|
| P0 | Intraday option-chain capture with bid/ask and timestamps | Provider/feed selection | Enables credible options intelligence, replay, and conservative paper |
| P0 | IV history, skew/term structure, Greek provenance | P0 data capture | Enables volatility context and reproducible analytics |
| P0 | Snapshot / proposal / risk-decision / audit store | Data schema and service design | Provides evidence lineage for research, paper, and certification |
| P0 | F&O-aware, fail-closed risk engine and all-path enforcement; kill switch in the UI | Instrument and risk inputs | Prevents unsafe F&O actions and establishes future authorization contract |
| P0 | Fix expiry-aggregated OI, the margin contradiction, the F&O paper reservation and exit defects | Existing F&O services | Removes known logic, accounting and UX defects |
| P0 | Close the privately reported security and operations findings (P0.6) | Security and operations | Protects credentials, records and the execution boundary |
| P1 | Full fee model, POP assumptions, margin buffer, free-funds view | Pricing and margin services | Makes strategy economics and capital more transparent |
| P1 | Portfolio Greeks and stress scenarios | Greek snapshots and position data | Provides portfolio-level risk context |
| P1 | Ranking evidence, baselines, OOS, drift tracking | Reliable historical data | Avoids presenting unvalidated scores as predictive |
| P2 | Event-driven multi-leg options backtester | P0 data and snapshots | Establishes evidence for options strategies |
| P2 | Conservative paper and F&O shadow mode | Backtester, risk engine | Tests decision and execution behavior without live capital |
| P3 | Certification service and test evidence | Research, risk, paper gates | Enforces safe, scoped promotion |
| P3 | Kite Connect order adapter, OMS, reconciliation | Certification and compliance | Enables live execution only after readiness |
| P3 | Restricted live rollout | All prior gates | Controlled production deployment |

---

## 27. Final Implementation Interpretation

The current F&O Lab should be treated as a **research and strategy-construction foundation**, not a certified AI trading agent or live execution platform.

The assessment identifies meaningful existing components:
- deterministic payoff and pricing, and a broker margin and charges calculator
- selected F&O screens with trust lines
- paper trade records
- risk-governor and kill-switch foundations
- audit fragments
- research-integrity practices

It also identifies blocking gaps:
- market-data depth and options replay
- F&O-aware risk and durable decision lineage
- agent behavior, conservative paper and certification
- the OMS
- security items that should be fixed independently of the roadmap

The recommended build order is therefore:

1. **Make the data trustworthy and point-in-time.**
2. **Persist snapshots, decisions, and evidence.**
3. **Make F&O risk deterministic and enforce it on every applicable path.**
4. **Complete strategy economics and portfolio risk outputs.**
5. **Build the options replay engine and prove research integrity.**
6. **Run conservative paper and shadow workflows with preregistered evidence.**
7. **Certify specific agent/strategy/context versions.**
8. **Only then build the Kite Connect order adapter and consider restricted live execution, subject to regulatory and broker review.**

Until these gates are met, the platform should continue to support research and paper workflows while keeping live order placement disabled.
