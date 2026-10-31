# Nivesh AI Lab — Phase-wise Success Criteria

**Audience:** Product Owner, Engineering, QA, Quant Research
**Purpose:** Define objective completion criteria, acceptance tests, release gates, and required evidence for Phases 0–4.
**Status:** Set by the product owner on 2026-10-27. These criteria are the acceptance standard for the plan in
`docs/NIVESH_AI_LAB_GUIDELINES_GAP_STUDY.md` (§6 phases, §9 decisions). A phase is reported complete only against this file.

> **Numbering note.** The sub-sections below (0.1–0.4) are *criteria groups*. They differ from the study's *work items*
> 0.1–0.9. The mapping:
>
> | Criteria group | Study work items |
> |---|---|
> | 0.1 Historical market data | 0.8 (price history and its repair), adjusted prices (was 4.2) |
> | 0.2 Simulated fills and P&L | 0.2 (P&L from the fill), 0.3 (entry rules, no impossible fills), costs in sizing (part of 1.3) |
> | 0.3 Paper-trade and F&O defects | 0.1 (F&O request), 0.4 (kill switch), 0.5 (duplicates), 0.6 (futures validator), 0.9 (reconciliation) |
> | 0.4 Scheduled jobs and release gate | 0.7 (exit job), IV-history backfill and job (was 4.4) |

---

## Phase 0 — Paper-Trading Integrity

### Objective
Ensure historical market data, simulated fills, trade accounting, and scanner inputs are trustworthy before extending risk
controls or evaluating strategy performance.

### 0.1 Historical market data

**Success criteria**

- [ ] The 14 identified copied NSE holiday sessions are removed or corrected through a documented, auditable data repair.
- [ ] The genuine 21–22 October 2026 sessions are restored from an authoritative source and validated against source records.
- [ ] No trading session is silently populated using the previous session's prices.
- [ ] The scanner consumes adjusted prices where appropriate, with documented split and bonus handling.
- [ ] The 91 identified stocks with corporate actions are reviewed, and affected features and indicators are recomputed.
- [ ] Downstream features, signals, and backtest inputs are regenerated from the corrected data.
- [ ] Data quality checks identify missing sessions, duplicate bars, stale prices, invalid OHLC values, and unexpected
      zero-volume records.

**Acceptance tests**

1. Verify all identified holiday and missing-session cases.
2. Compare sampled adjusted prices with the authoritative source.
3. Recompute indicators for affected instruments and verify consistency with the corrected input.
4. Rerun the scanner and record how candidate rankings and signals change.
5. Confirm that rerunning the repair does not create duplicate records or further alter already-correct data.

**Evidence required:** Data-quality report, affected-symbol count, before/after records, corporate-action validation, and
scanner rerun summary.

### 0.2 Simulated fills and P&L

**Success criteria**

- [ ] Paper entries use a documented fill model that respects the applicable market data and order assumptions.
- [ ] The FEDERALBNK example is corrected: the recorded entry must not be accepted at ₹316.89 if the applicable market data
      and fill rules do not support that price.
- [ ] Closed-trade P&L is calculated from actual simulated fills, not planned entry and exit prices.
- [ ] Brokerage, taxes, spread, and slippage are accounted for consistently in net P&L and risk reporting.
- [ ] Gap-through-stop behaviour uses a realistic fill assumption instead of assuming every stop fills at its trigger price.
- [ ] Partial fills, rejected orders, and unavailable prices have defined behaviour.
- [ ] Trade, fill, position, and cash-ledger records reconcile.

**Acceptance tests**

- Reproduce the FEDERALBNK discrepancy and verify the corrected result under the documented fill model.
- Reproduce the gapped-trade example and verify that P&L uses the simulated fill.
- Reproduce Example A and verify that the cost-inclusive risk estimate does not silently exceed the configured risk budget.
- Verify that a closed trade's realized P&L matches the sum of its fills and recorded costs, subject to the documented
  accounting conventions.
- Verify that cash and positions reconcile after entry, partial exit, full exit, and trade cancellation.

**Evidence required:** Deterministic test results, sample fill ledger, cost breakdown, and before/after P&L reconciliation.

### 0.3 Paper-trade and F&O defects

**Success criteria**

- [ ] An active kill switch blocks new paper-trade entries regardless of whether the F&O risk-gate feature flag is enabled.
- [ ] Duplicate submissions of the same logical trade cannot create duplicate trades or duplicate risk reservations.
- [ ] F&O idea-to-paper-trade requests work end-to-end against the actual backend.
- [ ] Tests exercise real request validation and backend responses; mocked responses alone cannot satisfy acceptance.
- [ ] Existing duplicate trades are reviewed and reconciled without deleting audit history.
- [ ] The open ICICIBANK trade with missing reserved funds and the closed NIFTY spread with missing cash-ledger impact are
      reconciled.
- [ ] Every correction is traceable to its original record and has a documented reason.

**Acceptance tests**

- Submit the same trade request twice and verify exactly one logical trade is created.
- Submit a trade with the kill switch active under both F&O gate configurations and verify rejection.
- Exercise valid and invalid F&O paper-trade requests through the real backend.
- Reconcile paper equity, available cash, reserved funds, open positions, and closed-trade P&L before and after corrections.

### 0.4 Scheduled jobs and release gate

**Success criteria**

- [ ] The evening exit job is installed on staging and its schedule is verified.
- [ ] The IV-history backfill completes with validated coverage and no unintended duplicate records.
- [ ] The IV-history job is installed only after the initial backfill is validated.
- [ ] Each job has logging, failure visibility, safe retries, and duplicate-run protection.
- [ ] Staging changes have a pre-change snapshot, post-change validation, and rollback instructions.

**Phase 0 exit gate**

Phase 0 is complete only when all identified critical data, fill, accounting, kill-switch, duplicate-submission, and F&O
request defects have passing regression tests. The staging data repairs and required job installations must also be
verified.

**Release blocker:** Any unresolved defect that can materially misstate a trade's price, P&L, available capital, or
eligibility.

---

## Phase 1 — Universal Risk Enforcement

### Objective
Ensure every entry path uses one shared risk policy and that a trade cannot bypass required checks.

### 1.1 Shared risk service

**Success criteria**

- [ ] Strategy Builder, watchlists, Top 10 candidates, F&O ideas, desk paper trades, and any other supported entry path use
      the same risk-policy implementation.
- [ ] The AI Trader governor's applicable controls are reused or consolidated into that shared service.
- [ ] Risk decisions return a structured result: approved or rejected, with reason codes and the relevant inputs.
- [ ] Risk limits are evaluated at entry time using current account and portfolio state.
- [ ] A missing or stale required risk input causes a safe rejection.
- [ ] The F&O risk gate cannot be bypassed through an alternate API or UI path.

**Acceptance tests**

- Attempt an entry through every supported entry path with the same deliberately failing risk condition.
- Verify that every path rejects the trade for the expected reason.
- Repeat with valid inputs and verify consistent risk decisions.
- Test unauthenticated, unauthorized, malformed, stale-data, and unavailable-service scenarios.

### 1.2 Account equity and risk limits

**Success criteria**

- [ ] Each paper account has an explicit, auditable equity basis.
- [ ] Risk profiles can be configured per account, with a record of who changed them and when.
- [ ] The system distinguishes per-trade risk, total open risk, market exposure, sector exposure, daily loss, weekly loss, and
      drawdown.
- [ ] Limit definitions specify their calculation basis, reset boundary, and behaviour when breached.
- [ ] Risk calculations include estimated costs and a documented gap/slippage stress estimate.
- [ ] Position sizing respects quantity increments and F&O lot sizes.
- [ ] A trade is rejected if the minimum valid quantity exceeds its permitted risk budget.

**Initial proposed research defaults** — subject to product-owner approval and controlled validation:

| Control | Initial value |
|---|---:|
| Risk per trade | 0.5% of paper equity |
| Total open risk | 3% of paper equity |
| Position exposure | 10% of paper equity |
| Sector exposure | 25% of paper equity |
| Daily loss halt | 2% of start-of-day equity |
| Weekly loss halt | 4% of start-of-week equity |
| Drawdown halt | 10% from configured equity peak |
| Minimum planned reward:risk | 1.5 after estimated costs where feasible |

These are configurable starting limits, not validated optimal values. Their definitions and operational behaviour must be
documented before implementation.

### 1.3 Atomic reservation and portfolio risk

**Success criteria**

- [ ] Risk capacity is reserved atomically before an entry is accepted.
- [ ] Concurrent entry requests cannot consume the same available risk capacity.
- [ ] Rejected, cancelled, and failed entries release reservations correctly.
- [ ] Partial fills and partial exits update reservations consistently.
- [ ] Portfolio checks include open risk, sector concentration, and correlated exposure where the required data is available.
- [ ] Risk reporting distinguishes stop-based risk from stressed loss under adverse gaps.
- [ ] Kill-switch activation blocks new entries and follows a separately documented policy for existing positions.

**Acceptance tests**

- Submit concurrent entries whose combined risk exceeds the limit; verify that the accepted total remains within the limit.
- Simulate retries, duplicate requests, partial fills, cancellation, and process restart.
- Verify that no reservation is leaked or counted twice.
- Test daily loss, weekly loss, drawdown, sector cap, exposure cap, and total open-risk breaches independently and in
  combination.

### Phase 1 exit gate

All supported entry paths must pass the same mandatory risk checks. Reservation logic must be safe under concurrency, and risk
decisions must be auditable.

**Release blocker:** Any entry path that can bypass the governor, any duplicate reservation, or any accepted trade whose
required risk data is missing.

---

## Phase 2 — Canonical Trade Plan, Lifecycle, and Exits

### Objective
Create one consistent trade representation and manage each accepted paper trade through an auditable lifecycle, from entry
to final exit.

### 2.1 Canonical trade plan

**Success criteria**

- [ ] A single canonical plan contains strategy, instrument, timeframe, entry trigger, stop, stop method, targets, quantity,
      risk, costs, invalidation, and exit policy.
- [ ] The Strategy Builder, watchlists, Top 10, F&O views, and paper-trade workflow consume the same plan values.
- [ ] A plan records the data timestamp, rule version, and creation time.
- [ ] Changes to a plan after approval are versioned and revalidated.
- [ ] The system distinguishes a proposed plan from an approved, triggered, open, or closed trade.

### 2.2 Unified trade lifecycle

**Required lifecycle**

`NO_SETUP → WAIT_FOR_CONFIRMATION → TRADE_ELIGIBLE → ENTRY_TRIGGERED → POSITION_OPEN → EXIT_PENDING → CLOSED`

`REJECTED` is a terminal state for a candidate or plan that fails eligibility or risk validation.

**Success criteria**

- [ ] Candidate, plan, risk decision, position, and fills are linked through stable identifiers.
- [ ] Each state transition records timestamp, reason, source, and rule version.
- [ ] Invalid transitions are rejected.
- [ ] Repeated events cannot create duplicate positions or exits.
- [ ] Restart and replay preserve lifecycle consistency.
- [ ] Failed exits are retried safely and surfaced operationally.
- [ ] Closed trades have a final exit reason and reconciled P&L.

### 2.3 Paper-trade exits

**Success criteria**

- [ ] Stop-loss, target, and time exits work in the paper-trading engine.
- [ ] ATR trailing and EMA20 trend exits are available as labelled, versioned research options.
- [ ] ATR trailing and EMA20 exits remain opt-in until validated against corrected data and fills.
- [ ] Trailing stops cannot loosen after being established.
- [ ] Stop, target, time, and trend exits use documented evaluation timing and fill assumptions.
- [ ] Exit processing is idempotent and safe under duplicate events and restarts.
- [ ] The evening exit job is monitored, and missed or failed runs are detectable.
- [ ] The system records whether an exit occurred because of a stop, target, time limit, trend rule, manual action, or risk
      control.

**Acceptance tests**

- Exercise every exit type using deterministic price sequences.
- Test gaps through stops, price jumps through targets, and conflicting exit conditions.
- Test duplicate exit events, delayed data, job failure, restart, and recovery.
- Verify that realized P&L uses actual simulated fills and recorded costs.
- Confirm that opt-in exit rules do not affect trades when disabled.

### Phase 2 exit gate

A paper trade must be traceable from candidate to closure, with correct accounting, defined exits, reliable recovery, and no
duplicate trade or exit processing.

**Release blocker:** A position that can remain unmanaged because an exit job or lifecycle transition silently failed.

---

## Phase 3 — Decision Cards and User Experience

### Objective
Present consistent, explainable, actionable trade plans across the product without implying certainty or bypassing risk
controls.

### 3.1 Required decision-card fields

**Success criteria**

Every eligible candidate card shows, where applicable:

- [ ] Instrument, strategy, timeframe, and status.
- [ ] Entry trigger, indicative entry price, and order assumptions.
- [ ] Stop price, stop method, and invalidation rationale.
- [ ] Target levels expressed in R multiples.
- [ ] Quantity or lots and the sizing basis.
- [ ] Planned rupee risk and percentage of account equity.
- [ ] Estimated costs and relevant gap/slippage risk.
- [ ] Market regime, trend, relative strength, momentum, volume, and price-structure evidence.
- [ ] Relevant event, liquidity, concentration, and correlation warnings.
- [ ] Exit plan, including stop, target, time, and any enabled trailing/trend rules.
- [ ] Data timestamp, rule version, and an explanation of rejection where applicable.

Unavailable fields must be explicitly labelled unavailable; they must not be fabricated or silently omitted if essential to
the decision.

### 3.2 Consistency across views

**Success criteria**

- [ ] Strategy Builder, Top 10, watchlists, and F&O candidate views use the same canonical plan.
- [ ] Displayed entry, stop, targets, quantity, and risk match the underlying approved plan.
- [ ] A change to the plan is reflected consistently in all views.
- [ ] F&O rows clearly distinguish provisional levels from risk-approved plans.
- [ ] A paper-trade action is enabled only when the underlying request and risk validation are supported.
- [ ] Disabled actions explain why the user cannot proceed.
- [ ] Risk and uncertainty are visible without requiring the user to infer them from a confidence score.

### 3.3 UI acceptance tests

- [ ] Verify required fields for cash, futures, and options plans.
- [ ] Verify empty, stale, rejected, provisional, and approved states.
- [ ] Verify that no UI displays values that differ from the canonical plan.
- [ ] Verify that the F&O stopgap cannot bypass Phase 1 risk controls.
- [ ] Verify usability at the supported desktop and mobile layouts.
- [ ] Verify that changing a plan or risk profile refreshes the displayed values and approval status.

### Phase 3 exit gate

All applicable candidate views show a consistent, explainable plan, and every action is consistent with the backend's current
eligibility and risk decision.

**Release blocker:** A displayed trade plan that materially differs from the plan used for sizing or risk approval.

---

## Phase 4 — Research and Strategy Validation

### Objective
Ensure scanner, indicator, entry, stop, target, and exit changes are evaluated with corrected historical data, realistic
execution assumptions, and reproducible out-of-sample tests.

### 4.1 Deterministic tests

**Success criteria**

- [ ] Examples A–H are encoded as automated tests.
- [ ] Tests cover entry, stop, target, quantity, lot rounding, cost-inclusive risk, gap fills, and risk-budget rejection.
- [ ] Edge cases cover missing prices, invalid stops, zero or stale ATR, partial fills, and minimum-lot constraints.
- [ ] Tests run in CI and fail when a regression changes expected results without an intentional update.

### 4.2 Backtest integrity and metrics

**Success criteria**

- [ ] Backtests use corrected historical prices and point-in-time features.
- [ ] Look-ahead and survivorship bias are addressed.
- [ ] Costs, spread, slippage, gaps, and order assumptions are documented and applied consistently.
- [ ] Results include net expectancy, win rate, average win/loss, profit factor, maximum drawdown, and suitable
      risk-adjusted metrics.
- [ ] Exposure, turnover, slippage sensitivity, and rejected-signal coverage are reported.
- [ ] Backtests use a documented holdout and walk-forward evaluation process.
- [ ] Results are reproducible from versioned data, configuration, code, and rule definitions.

### 4.3 Scanner weights and new indicators

**Success criteria**

- [ ] Current scanner weights remain the baseline.
- [ ] Proposed weights, ADX/+DI/−DI usage, and stock-level relative-strength features are evaluated as controlled research
      variants.
- [ ] The study design and primary evaluation metric are recorded before results are examined.
- [ ] Baseline and candidate variants use the same eligible universe, time periods, cost model, and evaluation protocol.
- [ ] Results are evaluated out of sample and across different market regimes.
- [ ] A proposed change is accepted only if the improvement is robust, economically meaningful after costs, and not explained
      by data leakage or a small number of trades.
- [ ] Negative or inconclusive findings are retained in the research record.

### 4.4 Intraday and bearish strategies

**Success criteria**

- [ ] Intraday strategies remain out of scope until historical minute-bar coverage and quality are verified.
- [ ] Any later intraday evaluation models session boundaries, timestamps, realistic fills, and slippage.
- [ ] Bearish cash setups are not enabled as cash shorts.
- [ ] Defined-risk options strategies are evaluated using complete multi-leg payoff and liquidity assumptions.
- [ ] Futures-short strategies remain gated until the risk model correctly handles futures exposure and adverse-loss
      scenarios.

### Phase 4 exit gate

A strategy or scoring change can be promoted only when the corrected-data study is reproducible, out-of-sample, net of
realistic costs, and demonstrates a robust improvement against the baseline.

**Release blocker:** A strategy change justified only by in-sample results, indicator intuition, or uncorrected historical
data.

---

## Cross-phase definition of done

Every phase must also satisfy these engineering requirements:

1. **Traceability:** Acceptance criteria map to code changes and automated tests.
2. **Observability:** Failures, rejected actions, scheduled-job errors, and reconciliation differences are visible.
3. **Auditability:** Material decisions and changes have timestamps, reasons, and version identifiers.
4. **Recovery:** Retries and restarts do not duplicate trades, cash movements, reservations, or exits.
5. **Configuration safety:** Feature flags and risk profiles have explicit defaults, permissions, and change history.
6. **Release safety:** Staging validation is documented, rollback is available, and paper-trading fixes do not silently
   enable live execution.
7. **Evidence-based sign-off:** Engineering and QA provide test results; the product owner accepts the phase against the
   documented criteria.

## Final release rule

A phase is complete only when all mandatory criteria pass, supporting evidence is attached, and no critical defect remains
open. A deferred feature must be explicitly documented as deferred rather than marked complete.

**Priority order:** Phase 0 integrity → Phase 1 universal risk → Phase 2 lifecycle and exits → Phase 3 decision cards.
Phase 4 research runs in parallel, but strategy conclusions must wait for trustworthy inputs and realistic fills.
