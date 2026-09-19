# Nivesh.ai — Early Signal, 5%/10% Move Probability & Exit Intelligence

**Version:** 1.1  
**Date:** 2026-09-19  
**Status:** Proposed — research-first, manual paper trading only  
**Sources:** Kite Connect OHLCV, NSE/bhavcopy reference data, Trendlyne MCP enrichment

## 1. Executive summary

Nivesh.ai will detect potential stock-movement candidates, create an early watchlist, confirm entries objectively, define risk before entry, provide exit intelligence, and record manual execution outcomes. It will estimate separate probabilities for +5% and +10% moves over fixed horizons, while prioritising net expectancy after costs, liquidity, capacity, and execution realism.

This is not an automated trading system. Signals are research information for manual use and must never be presented as guaranteed outcomes.

## 2. Objectives

- Build certified Kite OHLCV and Trendlyne-enrichment pipelines.
- Prevent look-ahead bias, survivorship errors, bad joins, and invalid labels.
- Detect early watchlist candidates and objective entry triggers.
- Calculate P(+5%), P(+10%), target-before-stop, stop-before-target, and neither outcomes.
- Measure gross and net expectancy after realistic costs and slippage.
- Support shadow and paper validation before any production candidate.
- Preserve immutable signal, feature, rule, and outcome history.

### Non-objectives

- Automated order placement.
- Guaranteed predictions.
- Public redistribution of vendor data.
- Automatic retraining from paper results.
- Historical use of current Trendlyne values unless point-in-time validity is established.

## 3. Product principles

1. Economics decide; movement accuracy alone is insufficient.
2. Every feature must be available at or before the prediction timestamp.
3. All rules, features, signals, and outcomes are versioned and immutable.
4. Manual latency, missed entries, attention limits, and achievable fills are modelled.
5. Discovery, validation, paper, and production stages remain separate.
6. The system fails closed when a data-quality blocker exists.
7. No result is selected after inspecting outcomes because it looks best.
8. Personal use and vendor licensing restrictions apply until reviewed.

## 4. Users and scope

### Initial user

The owner/operator of Nivesh.ai, manually executing or paper-trading positions.

### Initial universe

- NSE equity series (`EQ`) only.
- Minimum 20-day traded value of ₹5 crore unless separately preregistered.
- Versioned symbol mapping between Kite, Trendlyne, exchange, and ISIN.
- Historical universe and survivorship limitations explicitly reported.

## 5. Data sources

### Kite Connect

Primary source for daily, minute, and five-minute OHLCV, intraday price paths, volume, turnover, and local technical calculations. Kite-adjusted prices are used for returns and indicators. Raw reference prices are used for rupee-level filters such as circuit bands where required. The final intraday bar is not automatically treated as the official close.

### NSE/bhavcopy or certified reference data

Used for official open/close validation, raw prices, circuit bands, corporate actions, and historical-universe recovery where feasible. The phantom-prone research panel must not be used for gaps or paths without Kite validation.

### Trendlyne MCP

Potential enrichment source for financial ratios, financial statements, earnings growth, valuation, ownership, promoter pledge, insider trades, events, and other parameters. Trendlyne data must carry provenance and availability metadata. Historical values are not automatically point-in-time values.

Until availability and revision semantics are certified, Trendlyne features are excluded from historical training or explicitly labelled non-point-in-time research data.

## 6. Core workflow

```text
Ingest → certify data → generate features → discover candidates
→ early watchlist → trigger approaching → entry confirmed
→ manual position → exit intelligence → outcome capture
→ evaluation → research registry
```

### Signal lifecycle

`DISCOVERED → WATCHLIST → TRIGGER_APPROACHING → ENTRY_CONFIRMED → POSITION_OPEN → TARGET_REACHED / STOPPED / TIME_EXIT / INVALIDATED → CLOSED_AND_ANALYSED`

Every transition is timestamped and immutable.

## 7. Initial hypothesis families

### H-A — Liquid gap-down, open to close

- Gap-down at least 3% versus adjusted previous close.
- EQ only; 20-day traded value at least ₹5 crore.
- Lower-circuit-open exclusion uses only information available at the open.
- Entry at official open; exit at official close.
- Exploratory until sealed validation passes.

### H-B — Gap-down with early confirmation

- Same gap and liquidity conditions as H-A.
- At 09:45, the completed 09:40 candle close is no more than 0.5% below the open.
- Price is above cumulative VWAP from completed bars.
- Entry at the 09:45 bar open.
- Stop and target use the actual entry price.
- Candidate hypothesis, not a validated strategy.

### Future families

- Controlled pullback with five-minute confirmation.
- Accumulation plus range expansion, blocked by delivery-data quality.
- Event/catalyst reaction, blocked by historical announcement coverage.
- Gap-up continuation, optional and separately registered.

Every hypothesis requires an exact rule, one primary endpoint, cost model, universe, sample floor, abandon conditions, secondary metrics, and registry entry before sealed outcomes are reviewed.

## 8. Labels

Maintain separate labels for:

- Next-session high reaching +5% or +10%.
- High reaching +5% or +10% within five sessions.
- Downside reaching −3%, −5%, or −10%.
- Target-before-stop.
- Stop-before-target.
- Neither target nor stop within the horizon.
- Time-exit return.
- Unresolved due to missing or insufficient intraday data.

If target and stop are both touched in one bar, apply the registered conservative rule. The current framework counts both-touched bars as stop outcomes. Never choose event ordering after inspecting results.

## 9. Feature engineering

### Kite-derived features

- 1D, 3D, 5D, and 20D returns.
- Gap percentage, ATR, ATR percentage, Bollinger width.
- Range expansion, relative volume, volume, turnover.
- VWAP distance, intraday high/low timing.
- MFE, MAE, breakout distance, support/resistance distance.
- Market and sector relative strength.
- EMA20/50/200, ADX, RSI, ROC, MACD histogram.

### Trendlyne enrichment

Only after timestamp and revision semantics are validated:

- ROE, ROCE, debt-to-equity.
- Revenue and profit growth.
- Valuation metrics.
- Promoter, FII, and DII holdings.
- Promoter pledge and insider activity.
- Corporate events, earnings, and guidance.

Each feature stores `feature_name`, `value`, `source`, `source_timestamp`, `available_at`, `retrieved_at`, `feature_version`, `revision_id`, and `point_in_time_validated`.

## 10. Data-quality gates

### Completeness

Validate trading sessions, missing daily and intraday candles, expected 75 five-minute bars, duplicate records, missing volume, symbol coverage, range, freshness, and partial candles.

### OHLCV consistency

```text
high >= max(open, close)
low <= min(open, close)
high >= low
open > 0
close > 0
```

Flag suspicious records for investigation rather than silently deleting them.

### Cross-source joins

Automated tests must check symbol/date keys, raw and adjusted factors, first intraday open versus daily open, intraday high/low versus daily high/low, official close versus final intraday bar, and absence of future-session substitutions.

### Corporate actions

Track splits, bonuses, dividends, rights issues, mergers, demergers, and symbol changes. Preserve raw and adjusted prices with adjustment metadata.

### Lower-circuit logic

The circuit filter must use the band known at the open, opening price, first completed bar low, source, tolerance, evaluation timestamp, auction flag, missing-bar status, and rule version. The final day low must never decide whether an opening filter passed.

### Trendlyne checks

Validate identifiers, units, missing-versus-zero values, period end, publication/availability timestamps, revisions, quarter-end versus disclosure date, and current-versus-historical representation.

**BLOCKER:** look-ahead, invalid timestamp, corrupted OHLC, future join, or unverified label logic. A blocker prevents study execution or publication.

## 11. Cost and execution model

Include brokerage, STT, exchange charges, SEBI fee, stamp duty, GST, spread, liquidity-dependent slippage, manual latency, and gap-through-stop execution.

Initial sensitivity:

- Charges assumption: 0.10%, to be reconciled against contract notes.
- Round-trip slippage: 0.20%–0.40% by liquidity bucket.
- Two-times-cost sensitivity.

Report optimistic, base, and stress scenarios with gross return, costs, net return, dispersion, drawdown, concentration, liquidity splits, and capacity impact.

## 12. Capacity and alert policy

Before outcome review, freeze:

- Maximum confirmed alerts per day.
- Maximum positions per session.
- Capital and symbol exposure limits.
- Sector exposure limits.
- Selection order when alerts exceed capacity.
- Simultaneous-signal handling.
- Missed-signal recording.

Diagnostic caps may include 5, 10, 20, 50, and uncapped. The primary result must use a preregistered cap and selection rule; uncapped results are not the primary result.

## 13. Signal requirements

Every signal must include:

- Signal ID, pattern ID, and version.
- Symbol, exchange, series, and detection timestamp.
- State, entry reference, entry zone, trigger, and invalidation.
- Stop, targets, and horizon.
- P(+5%), P(+10%), P(target first), P(stop first), and P(neither), when validated.
- Expected gross/net return.
- Regime, sector, liquidity bucket, drivers, risks, freshness, sample size, calibration status.
- Feature snapshot ID, cost-model version, and rule version.

Corrections create a new version; original signals remain preserved.

## 14. Entry and exit intelligence

### Entry

Record trigger timestamp, completed candle, next executable bar, simulated/manual entry price, slippage, delay, missed status, and invalidation reason.

### Exit

Show target proximity, stop proximity, thesis deterioration, time-stop condition, event risk, gap-through-stop risk, MFE, MAE, exit-alert timestamp, manual action timestamp, and recommended-versus-actual exit difference.

## 15. Modelling

### Baselines

- Naive base-rate model.
- Logistic regression.
- Rule-based benchmark.
- Kite-only feature model.

### Challengers

- HistGradientBoosting.
- Market-day clustered statistical models.
- Forward-filtered regime challenger.
- Calibrated probability models.

Evaluate net expectancy after costs, drawdown, calibration, yearly and regime stability, liquidity, sector concentration, capacity, unresolved rate, and incremental lift over the baseline. AUC and accuracy are diagnostic only.

## 16. Research design

Recommended split:

- Discovery: 2024–2026.
- Validation: 2021–2022.
- Final test: 2023-01 through 2024-07.

Sealed slices are single-use per hypothesis family. Register the hypothesis, universe, entry/exit, confirmation time, primary endpoint, cost model, liquidity, capacity, sample floor, abandon conditions, and secondary metrics before reading outcomes.

Report per-trade and per-session statistics, whole-day resampling or clustered inference, top-session contribution, year/regime splits, and outlier dependence.

## 17. Track 1 — ten-day manual signal loop

### Objective

Prove operational reliability, not statistical edge.

### Scope

- EQ only.
- 20-day traded value ≥ ₹5 crore.
- Gap-down ≥ 3%.
- Lower-circuit-open exclusion.
- H-A open entry and H-B 09:45 confirmation.
- Fixed stop/target and after-close outcome calculation.
- HTML report plus CSV and JSON artifacts.
- No automated execution or probability claims.

### Delivery plan

| Days | Deliverable |
|---|---|
| 1 | Freeze scope and versions |
| 2–3 | Evening watchlist job |
| 3–4 | Append-only signal ledger |
| 4–5 | After-close outcome job |
| 5–6 | Dry run on certified five-minute symbols |
| 6–10 | Daily report and 20–30 paper sessions |

Operational metrics include generation time, candidates, confirmations, lead time, missed entries, response time, duplicate alerts, failed jobs, freshness, unresolved outcomes, operator time, manual fill difference, and exit-alert latency.

## 18. Track 2 — sealed validation

The sealed test cannot begin until lower-circuit logic is rerun and frozen, data joins pass, H-A and H-B definitions are preregistered, costs and capacity are fixed, sample and abandon conditions are recorded, and Trendlyne features are excluded or point-in-time certified.

Run H-A and H-B once on 2021–2022. Produce the complete report. Run the 2023–2024 final test only if Stage 2 requirements are met.

## 19. Reports and dashboard

### Daily HTML report

- Data-quality status and market regime.
- Watchlist, trigger-approaching and confirmed signals.
- Open positions and target/stop proximity.
- Signal age, freshness, sample size, calibration status.
- Three drivers, three risks, unresolved outcomes.
- Operational, cost, and capacity summaries.

### Research report

- Registered hypothesis and rule version.
- Data range, universe, certification and cost model.
- Primary endpoint, sample size, confidence intervals, clustered inference.
- Liquidity, capacity, regime and concentration analysis.
- Sensitivity, limitations, and registry status.

## 20. Data model

Core tables:

- `market_candles`
- `instrument_master`
- `instrument_mapping`
- `corporate_actions`
- `data_manifests`
- `data_quality_runs`
- `fundamental_snapshots`
- `ownership_snapshots`
- `event_snapshots`
- `feature_snapshots`
- `signal_definitions`
- `signal_versions`
- `signal_state_transitions`
- `signal_alerts`
- `entry_trigger_events`
- `trade_plans`
- `manual_trade_records`
- `exit_alerts`
- `paper_trade_outcomes`
- `signal_evaluation_runs`
- `alert_quality_daily`
- `research_registry`

All tables should include run ID, source, source timestamp, availability timestamp, retrieval timestamp, version fields, and data-quality status where applicable.

## 21. Jobs and APIs

Required jobs:

- Kite daily and intraday ingestion.
- Trendlyne enrichment.
- Symbol and corporate-action validation.
- Feature and label generation.
- Watchlist and trigger evaluation.
- Outcome calculation.
- Data-quality certification.
- Research evaluation and report generation.
- Backup, retention, and monitoring.

Jobs must be idempotent, resumable, auditable, retry-limited, and explicit about partial failures.

## 22. Security, licensing and compliance

- Store Kite credentials securely; never expose tokens in UI or logs.
- Rotate secrets without interrupting active pulls.
- Review Kite and Trendlyne terms before automation or redistribution.
- Keep initial use personal and research-only.
- Obtain legal review before sharing stock-specific entry, stop, or target signals.
- Encrypt sensitive data in transit and at rest.
- Maintain access and change audit logs.

## 23. Monitoring

### Data

Ingestion freshness, missing sessions, missing symbols, API failures, response anomalies, duplicates, mapping failures, point-in-time violations, disk usage, and stale datasets.

### Model

Feature drift, prediction distribution, calibration drift, net expectancy, drawdown, liquidity mix, sector concentration, alert volume, unresolved outcomes, and manual execution gap.

Research and production must be separated. The app VM must have a centrally configured free-space gate of at least 6 GB before deployment, or a revised threshold approved and documented consistently. Prefer separate research compute and storage.

## 24. Acceptance criteria

### Data

- No duplicate primary candles.
- OHLC checks pass.
- Trading-calendar coverage is reported.
- Missing bars and partial sessions are labelled.
- Cross-source joins pass automated tests.
- Corporate-action policy is documented.
- Symbol mapping is versioned.
- Point-in-time status exists for enriched features.
- Future-session joins are blocked.
- Lower-circuit filters use decision-time data.

### Research

- Hypotheses are registered before sealed review.
- One primary endpoint is frozen.
- Costs and capacity are preregistered.
- Session clustering and liquidity splits are reported.
- Unresolved outcomes are retained.
- Multiple testing is logged.
- Discovery, validation, and final test are separated.

### Signal engine

- Signals and transitions are immutable.
- Feature snapshots are preserved.
- Entry, stop and target use actual entry price.
- Manual delay, slippage, missed entries and exits are recorded.
- Freshness, sample size and calibration are visible.

### Operations

- Daily report produces HTML, CSV and JSON.
- Failed jobs alert the operator.
- Disk guard, backups, retention and rollback are active.
- Research workloads cannot destabilize production.

## 25. Roadmap

### Phase 0 — integrity

Freeze definitions; rerun lower-circuit A/B/C variants; implement manifests, joins, OHLCV tests, raw/adjusted price policy, H-A/H-B definitions, costs, and capacity.

### Phase 1 — data foundation

Complete Kite backfill, build certified stock-day data, labels, cost engine, symbol mapping, and corporate-action handling.

### Phase 2 — sealed validation

Preregister H-A/H-B, run 2021–2022 once, and run the final slice only if validation passes.

### Phase 3 — operational loop

Build watchlist, immutable ledger, confirmation workflow, after-close outcomes, and daily reports.

### Phase 4 — discovery engine

Establish Kite-only baseline, then test relative strength, five-minute/VWAP confirmation, logistic models, gradient boosting, and regimes. Add Trendlyne only after point-in-time certification.

### Phase 5 — shadow and paper

Run shadow signals, manual paper execution, missed-opportunity analysis, calibration, risk, and capacity monitoring.

### Phase 6 — production candidate

Require final-test success, realistic execution, paper validation, monitoring, security review, licensing review, legal review, and rollback.

## 26. Final promotion rules

A pattern is not promoted because it has a high hit rate, AUC, gross return, thin-name performance, uncapped capacity, or a result that disappears under 2x costs.

Promotion requires:

1. Valid data and no look-ahead.
2. Positive out-of-sample net expectancy after costs.
3. Reliable calibration if probabilities are shown.
4. Stability across time and regimes.
5. Realistic liquidity, capacity, and execution.
6. Transparent limitations and monitoring.
7. Successful shadow and paper validation.

## 27. Immediate next actions

1. Complete the lower-circuit A/B/C integrity rerun.
2. Freeze H-A primary variant before sealed outcome review.
3. Freeze H-B timing and VWAP definition.
4. Set daily alert and position capacity.
5. Reconcile charges against a contract note.
6. Complete the Kite backfill and data manifest.
7. Implement automated join and OHLCV tests.
8. Keep Trendlyne features out of historical training until point-in-time semantics are certified.
9. Build Track 1 watchlist, ledger, and outcome jobs.
10. Separate research resources from the production-shared app VM.

**End of PRD**


---

# 32. Paper Trading Specification — Revised

## 32.1 Purpose

The paper-trading system is designed to validate the complete manual trading workflow before any live capital is considered. It must measure both:

1. **Strategy behaviour:** signal quality, target/stop outcomes, expectancy and risk.
2. **Operational behaviour:** alert timeliness, manual response, missed entries, execution differences and workload.

Paper trading is not proof of live profitability. It is a controlled validation environment with explicit assumptions and complete auditability.

## 32.2 Paper Trading Modes

The system shall support four modes:

### Mode A — Historical replay

Uses historical Kite candles and certified reference data.

Purpose:

- Validate deterministic rules.
- Test labels and target/stop handling.
- Compare alternative rule versions.
- Measure historical strategy characteristics.

Restrictions:

- No current Trendlyne values may be used as historical point-in-time data.
- All historical features must have validated availability timestamps or be excluded.
- Replay must use the same signal and label engine as forward paper trading.

### Mode B — Shadow mode

Generates signals without creating simulated positions automatically.

Purpose:

- Validate watchlist generation.
- Measure alert lead time.
- Capture whether the operator would have acted.
- Test duplicate alerts, stale signals and operational failures.

### Mode C — Manual paper trading

The system generates a trade plan, but the operator records whether and at what price the simulated trade was accepted.

Purpose:

- Measure realistic manual execution.
- Capture decision delay and missed signals.
- Compare planned entry with operator-entered entry.
- Validate stop and target alerts.

### Mode D — Strict mechanical paper benchmark

A deterministic benchmark executes the registered rule without operator discretion.

Purpose:

- Provide a reproducible reference.
- Separate strategy performance from human execution effects.
- Compare mechanical and manual outcomes.

The manual result must never be substituted for the mechanical benchmark, and neither should be presented as live performance.

## 32.3 Paper Trading Eligibility

A signal may enter paper trading only when:

- The data-quality run has passed all mandatory gates.
- The signal definition and version are registered.
- The feature snapshot is stored.
- The entry, stop, target and time horizon are defined.
- The cost model is assigned.
- The signal has not expired.
- The symbol satisfies the registered liquidity and instrument rules.
- The signal is not based on future information.
- The maximum daily alert and position capacity has not been exceeded.

Signals failing any blocker must be marked `REJECTED_DATA_QUALITY` or `INVALIDATED`, with a reason.

## 32.4 Paper Trading Account Configuration

Every paper account must have a versioned configuration:

```text
paper_account_id
starting_capital
base_currency
maximum_daily_loss
maximum_total_exposure
maximum_positions
maximum_position_value
maximum_symbol_exposure
maximum_sector_exposure
maximum_new_entries_per_day
margin_policy
short_selling_policy
cost_model_version
slippage_model_version
capacity_policy_version
created_at
```

Recommended initial policy:

- No leverage.
- Long-only unless separately registered.
- Fixed maximum number of open positions.
- Fixed maximum capital per position.
- No averaging down.
- No discretionary target or stop movement unless the rule explicitly permits it.
- Unused cash and reserved capital must be tracked.

These are initial configuration recommendations, not assumptions to be silently applied to historical research.

## 32.5 Position Sizing

The paper engine shall support two separately reported sizing methods.

### Method 1 — Fixed capital allocation

```text
position_value = min(
    configured_position_value,
    available_cash,
    remaining_daily_capacity
)
```

### Method 2 — Risk-based sizing

```text
risk_per_share = abs(entry_price - stop_price)

position_quantity =
    floor(max_risk_amount / risk_per_share)
```

Position sizing must also respect:

- Maximum position value.
- Minimum tradable quantity.
- Liquidity limit.
- Maximum percentage of average traded value.
- Available cash.
- Existing exposure.
- Sector and portfolio concentration.

The report must show the number of signals rejected or reduced because of capacity or capital limits.

## 32.6 Entry Simulation

Each paper entry must store:

- Signal timestamp.
- Trigger timestamp.
- Decision timestamp.
- Planned entry price.
- Simulated fill price.
- Operator-entered price, if applicable.
- Quantity.
- Entry slippage.
- Entry delay in seconds or minutes.
- Candle used for confirmation.
- Whether the entry was missed.
- Miss reason.
- Data freshness at entry.
- Entry rule version.

### Entry price policy

The system must distinguish:

1. **Reference entry:** price defined by the strategy.
2. **Executable entry:** first price available after the trigger under the registered rule.
3. **Manual entry:** price entered by the operator.
4. **Conservative simulated fill:** executable price adjusted for slippage and delay.

A signal must not use a future high, future low or later candle to improve the simulated entry.

## 32.7 Exit Simulation

Each paper position must support:

- Stop-loss exit.
- Target exit.
- Time exit.
- Manual exit.
- Invalidated thesis exit, only if explicitly registered.
- Gap-through-stop handling.
- End-of-session exit.
- Partial exit, only if enabled by the strategy version.

The exit record must include:

```text
position_id
exit_reason
planned_exit_price
simulated_exit_price
manual_exit_price
exit_timestamp
exit_candle_timestamp
slippage
charges
gross_pnl
net_pnl
mfe
mae
rule_version
cost_model_version
```

### Same-candle stop and target

If the same candle touches both stop and target:

- Apply the conservative registered rule.
- For the initial benchmark, classify the result as stop-first.
- If the order cannot be established and the rule allows it, mark the outcome unresolved.
- Never choose the result after inspecting which outcome is more favourable.

### Gap-through-stop

If the opening price is beyond the stop:

- Record the stop as breached.
- Use the defined executable price or opening price according to the registered policy.
- Report gap-through-stop frequency separately.
- Do not assume execution at the stop price.

## 32.8 Manual Execution Capture

The operator must be able to record:

- Accepted or rejected signal.
- Actual entry time.
- Actual entry price.
- Quantity.
- Reason for not entering.
- Actual exit time.
- Actual exit price.
- Reason for exit.
- Whether the alert was seen.
- Whether the alert arrived too late.
- Any execution or liquidity issue.

The system must distinguish:

```text
strategy_result
mechanical_paper_result
manual_paper_result
```

This separation allows the team to measure the effect of human execution and operational constraints.

## 32.9 Alert Specification

Alerts shall be generated for:

- New watchlist candidate.
- Trigger approaching.
- Entry confirmed.
- Entry invalidated.
- Stop proximity.
- Target proximity.
- Stop triggered.
- Target triggered.
- Time-stop approaching.
- Data stale or unavailable.
- Signal expired.
- Daily capacity reached.
- Duplicate or conflicting signal.

Each alert must include:

- Alert ID.
- Signal ID.
- Alert type.
- Created timestamp.
- Intended delivery timestamp.
- Actual delivery timestamp, where measurable.
- Acknowledgement timestamp.
- Acknowledgement status.
- Alert version.
- Data freshness.
- Delivery error, if any.

Required metrics:

- Alert latency.
- Acknowledgement latency.
- Missed-alert percentage.
- Duplicate-alert count.
- False-alert burden.
- Alerts per session.
- Alerts per hour.
- Operator response time.

## 32.10 Signal Expiry and State Rules

Each signal must have an explicit expiry policy.

Examples:

- Watchlist signal expires at market open if no trigger condition remains valid.
- Intraday trigger expires at the end of the registered session.
- Entry confirmation expires after the configured entry window.
- A position cannot be opened from an expired signal.
- A stopped or target-reached position cannot return to `POSITION_OPEN`.
- Corrections must create a new signal version, not overwrite history.

Invalidation reasons must be coded, not stored only as free text.

## 32.11 Paper Trading Ledger

The ledger shall be append-only.

Required entities:

- Signal.
- Signal state transition.
- Alert.
- Trade plan.
- Paper order.
- Paper fill.
- Paper position.
- Exit event.
- Cost event.
- Manual action.
- Data-quality event.
- Exception and correction event.

Every record must include:

- Unique ID.
- Event timestamp.
- Ingestion timestamp.
- Source.
- Run ID.
- Rule version.
- Data version.
- Actor or process.
- Previous state, where relevant.
- New state, where relevant.

Corrections must be represented as compensating events or new versions.

## 32.12 Paper Trading Metrics

### Strategy metrics

- Number of signals.
- Number of accepted signals.
- Number of rejected signals.
- Number of paper positions.
- Gross return.
- Net return.
- Net expectancy.
- Median return.
- Win rate.
- Average gain.
- Average loss.
- Profit factor.
- Maximum drawdown.
- Daily loss distribution.
- Consecutive losses.
- MFE and MAE.
- Target-before-stop rate.
- Stop-before-target rate.
- Time-exit rate.
- Gap-through-stop rate.
- Unresolved outcome rate.

### Operational metrics

- Watchlist generation duration.
- Alert latency.
- Manual acknowledgement latency.
- Manual entry delay.
- Missed-entry rate.
- Manual execution gap.
- Exit-alert latency.
- Duplicate alerts.
- Failed jobs.
- Stale-data incidents.
- Operator time per session.
- Maximum simultaneous decisions.
- Signals rejected due to capacity.

### Segmentation

Report metrics by:

- Hypothesis and version.
- Prediction time.
- Market regime.
- Sector.
- Market capitalization.
- Liquidity bucket.
- Gap-size bucket.
- Volatility bucket.
- Probability bucket, only after calibration.
- Entry delay.
- Holding period.
- Session.
- Month and year.

## 32.13 Paper Trading Evaluation Windows

The initial operational program shall use:

### Dry run

- 3–5 sessions.
- No simulated capital.
- Validate data, alerts, timestamps and state transitions.

### Operational paper period

- Minimum 20 sessions.
- Prefer 30 sessions for workflow evaluation.
- Evaluate alert reliability and operator workload.
- Do not claim that this establishes strategy edge.

### Strategy validation period

- Longer, preregistered period.
- Separate validation and final test.
- Use the same frozen rule, cost and capacity policies.
- Do not stop early because results are favourable or unfavourable unless the preregistered stop rule is triggered.

## 32.14 Paper Trading Stop Conditions

Pause the paper engine when:

- Any look-ahead violation is detected.
- The data-quality gate fails.
- The signal rule changes without a new version.
- The cost model is missing.
- The daily loss or exposure limit is exceeded.
- Stale data exceeds the registered threshold.
- Duplicate state transitions corrupt the ledger.
- A vendor outage makes price or feature data unreliable.
- Manual execution records cannot be reconciled.
- The operator workload exceeds the registered capacity.

A pause must preserve the ledger and create an incident record.

## 32.15 Paper Trading Acceptance Criteria

The paper-trading release is accepted only when:

- [ ] Historical replay is deterministic for the same input and versions.
- [ ] Every signal has an immutable feature snapshot.
- [ ] Entry and exit prices follow the registered rules.
- [ ] Stop/target ambiguity is handled conservatively.
- [ ] Gap-through-stop events are recorded.
- [ ] Manual and mechanical outcomes are separated.
- [ ] Alerts have measurable creation and delivery timestamps.
- [ ] Missed and rejected signals have coded reasons.
- [ ] Capacity limits are enforced.
- [ ] Stale data blocks affected signals.
- [ ] All costs are recorded by version.
- [ ] The ledger is append-only.
- [ ] Corrections preserve the original event history.
- [ ] Daily reports reconcile signals, positions, cash and P&L.
- [ ] No paper result is presented as live trading performance.

## 32.16 Revised Track 1 Deliverable

Track 1 shall deliver:

1. Evening watchlist generation.
2. Morning trigger evaluation.
3. H-A open-entry benchmark.
4. H-B 09:45 confirmation benchmark.
5. Mechanical paper ledger.
6. Manual decision and execution capture.
7. Exit and outcome engine.
8. Daily HTML report.
9. CSV and JSON audit artifacts.
10. Data-quality and operational incident report.

The Track 1 success criterion is **operational reliability and complete evidence capture**, not a positive return over a short sample.

## 32.17 Revised Track 2 Deliverable

Track 2 shall deliver:

1. Frozen H-A and H-B definitions.
2. Lower-circuit A/B/C diagnostic comparison.
3. Capacity-capped and uncapped diagnostic results.
4. Cost sensitivity scenarios.
5. Per-trade and per-session statistics.
6. Historical and point-in-time data certification.
7. Sealed validation report.
8. Final test report, only if validation gates pass.
9. Research registry update.
10. Explicit promotion or failure decision based on preregistered criteria.

---

# 33. Revised Product Decisions

The following decisions are mandatory before sealed validation:

1. Select the primary H-A variant before reviewing the sealed outcome.
2. Freeze the lower-circuit definition and timestamp semantics.
3. Freeze the H-B VWAP and completed-candle definition.
4. Freeze position capacity and signal selection order.
5. Freeze optimistic, base and stress cost models.
6. Define the maximum number of concurrent paper positions.
7. Define manual entry and exit delay assumptions.
8. Define unresolved-data handling.
9. Define the minimum paper-trading operational period.
10. Define the exact promotion and abandonment criteria.

No rule, cost, capacity or label definition may be changed after reviewing a sealed result without creating a new registered research version.

---

# 34. Implementation Priority Update

## P0 — Mandatory before paper trading

- Data-quality gates.
- Lower-circuit correction.
- Timestamp and timezone normalization.
- Immutable signal ledger.
- Entry/exit label engine.
- Cost model.
- Capacity policy.
- Manual execution capture.
- Stale-data blocking.

## P1 — Required for Track 1

- Watchlist job.
- Trigger evaluation.
- Alert event log.
- Paper position ledger.
- Outcome job.
- Daily report.
- CSV/JSON audit export.
- Operational metrics.

## P2 — Required for Track 2

- Sealed-run registry.
- Historical universe controls.
- Capacity analysis.
- Cost sensitivity.
- Clustered session-level inference.
- Trendlyne point-in-time certification.
- Final test reporting.

## P3 — Later enhancements

- Probability calibration.
- Model challengers.
- Regime-aware thresholds.
- Advanced exit intelligence.
- Portfolio-level allocation.
- Additional hypothesis families.

---

# 35. Final Paper Trading Principle

The paper-trading system must answer two separate questions:

1. **Would the registered strategy have produced a viable result under realistic historical assumptions?**
2. **Could the operator reliably detect, execute and manage the signals under real workflow constraints?**

A strategy passes only when both questions have sufficient evidence. A high historical return without operational feasibility, or reliable alerts without positive net expectancy, is insufficient for promotion.
