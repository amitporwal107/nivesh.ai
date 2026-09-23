> **Filed in the repository on 2026-09-23 at the owner's request, for tracking.** The body below is the owner's
> document as received, verbatim. It was reviewed against the plan and the code on 2026-09-22 and the outcome is
> recorded in `docs/charting.md` §38.19 Amendment E, which governs wherever this document and the amendment differ.
>
> Positions from §38.19 that apply to this document:
>
> - **Sequence (§38.19.3, position 1).** Live signals are step 7, after the six §38.18 detection steps and after
>   study plan v2 reports. Only Phase 1 (§36: the signal contract, schema, versioning, timestamp semantics, and the
>   lifecycle mapping below) may be written now; Phases 2–6 start after v2 reports. The first live version is
>   end-of-day daily signals from the batch replay. The 15-minute and 1-hour timeframes (§17), the WebSocket/SSE
>   events (§30) and the latency targets (§31) need an intraday ingestion loop, per-bar detector runs and a push
>   channel that do not exist; they are gated on track F (daily data), track K (§38.16) and the D-2 export, and stay
>   owner-only (decision #10).
> - **Score (§38.19.4, position 2).** The seven component bars in §12 stay; the single 0–100 headline number goes.
>   Retest quality and risk/reward are removed from any live weighting. Any composite is a research object:
>   pre-registered in a later study version, tested, then shown.
> - **Setup (position 3).** Entry, stop and targets (§13) are owner-only until the SEBI RA/IA question (NI-1a) is
>   answered. The §4 "future advisor/MFD users" are out of scope until then. Setup values come from the frozen
>   definitions, computed by the same code as the study: stop = the NI-3 Layer-1 structural stop widened to at least
>   0.75 × ATR(14); targets = the v2 set (+2 / +3 / +5 / +10 % and 1 / 1.5 / 2 / 3 R). The ₹1,256 / ₹1,218 / ₹1,300 /
>   ₹1,320 example in this document is not derived from them and is illustrative.
> - **Lifecycle (position 4).** The research state names (NI-3 §1.2) are canonical. This document carries the
>   mapping as frozen:
>
>   | This PRD | Research (NI-3 §1.2) | Note |
>   |---|---|---|
>   | WATCH | FORMING | |
>   | READY | EARLY_SIGNAL | 1% readiness band, NI-3 S9 |
>   | TRIGGERED | BREAKOUT_CANDIDATE | close beyond the live level by 0.5% |
>   | CONFIRMED | CONFIRMED_BREAKOUT | plus breakout-bar volume ≥ 1.5× |
>   | INVALIDATED | INVALIDATED or FAILED_BREAKOUT | two distinct research states; they must not be merged |
>   | NOT_TRIGGERED, INCONCLUSIVE | as #110 | research states |
>   | RETEST, CONTINUATION | events on the row | not states |
>
> - **Pattern coverage.** The 16 NI-3 v1.0 types (`docs/ai_research/CHARTING_NI3_PREDICATES_V1.md`, fingerprint
>   `de86626c…`) supersede the §7 list of 14 (it lacks inverse head & shoulders and the two pennants, and folds
>   wedges and channels together).
> - **Volume (§11).** Confirmed as already decided (#109, #110): live families 1.0–4.0× follow-through bar; new
>   families ≥ 1.5× breakout bar; the raw ratio is always stored.
> - **Illustrative numbers.** Every research or performance figure in the examples is illustrative; no study has
>   run. The negative and empty state (what the research-context block shows when v2 reports no information beyond
>   volatility) is a required design.
> - **What lines up already (§38.19.6).** The §8 P-1 table equals NI-3 §2; §6.2 READY at 1% equals NI-3 S9;
>   §22–§24 versioning, fingerprint and no look-ahead match NI-3 §1.1 and v2 §8; the §23 study plan v2 is drafted
>   (`docs/ai_research/CHARTING_PREREGISTRATION_V2.md`).

# PRD — Live Trading Alerts & Signals Engine

**Product:** Nivesh Charting / Technical Research Platform  
**Document type:** Product Requirements Document  
**Version:** 1.0  
**Date:** 2026-09-22  
**Status:** Proposed

---

## 1. Purpose

Add a real-time **Trading Alerts & Signals Engine** on top of the existing charting, technical-indicator, chart-pattern detection, confirmation, and historical-validation framework.

The system must convert live market observations into clear, explainable signal states:

> **WATCH → READY → TRIGGERED → CONFIRMED → RETEST → CONTINUATION / INVALIDATED**

The objective is to provide timely and understandable alerts without changing the frozen research definitions or allowing live signals to contaminate historical validation.

This PRD covers **signal generation, lifecycle management, alerting, chart presentation, signal payloads, and auditability**.

---

## 2. Product Principles

1. **Detection ≠ confirmation ≠ trade setup.**
2. Pattern geometry and research rules remain independently testable.
3. Live alerts must use the same frozen pattern definitions as the charting engine.
4. Every signal must be explainable.
5. Every signal must have a timestamp and version.
6. The system must never use future information.
7. Live alerts must not modify research records.
8. Historical validation must remain reproducible.
9. Avoid alert spam by aggregating related technical events into one signal.
10. The user must be able to see exactly why a signal changed state.

---

## 3. Scope

### 3.1 In scope

- Live pattern monitoring
- Pattern lifecycle state machine
- Technical-indicator confirmation
- Volume confirmation
- Trend confirmation
- Relative-strength confirmation
- Breakout / breakdown detection
- Retest detection
- Invalidation detection
- Entry / stop / target calculations
- Explainable signal scoring
- Dashboard alerts
- Push/browser alerts
- Chart overlays
- Signal history
- Signal audit trail
- 15-minute and 1-hour live monitoring
- Daily positional signals
- Signal versioning
- Duplicate-alert suppression

### 3.2 Out of scope

- Broker order execution
- Automatic trade execution
- Portfolio allocation
- Position sizing as an execution function
- Optimization of frozen research parameters based on live results
- Changing frozen v1 study definitions
- Replacing the existing charting library
- Unapproved AI-generated trading decisions

---

# 4. Users

### Primary user

A technical-analysis user monitoring selected stocks for positional opportunities.

### Secondary users

- Researcher validating technical patterns
- Developer/QA validating signal behavior
- Future advisor/MFD users

---

# 5. Signal Lifecycle

Every live pattern must have a deterministic lifecycle.

```text
                    ┌───────────┐
                    │   WATCH   │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │   READY   │
                    └─────┬─────┘
                          │
                          ▼
                   ┌────────────┐
                   │  TRIGGERED │
                   └──────┬─────┘
                          │
                          ▼
                   ┌────────────┐
                   │ CONFIRMED  │
                   └──────┬─────┘
                          │
                     ┌────┴────┐
                     ▼         ▼
                 RETEST   CONTINUATION
                     │
                     ▼
                 INVALIDATED
```

Additional terminal states:

- `NOT_TRIGGERED`
- `INCONCLUSIVE`

These states are consistent with the existing pattern research framework.

---

# 6. Signal States

## 6.1 WATCH

Pattern structure exists but price is not yet close enough to the trigger.

Example:

```text
Ascending Triangle
Resistance: ₹1,250
Current: ₹1,190
Status: WATCH
```

Requirements:

- Pattern must satisfy the detector's structural rules.
- Pattern must not be invalidated.
- No breakout notification should be generated.

---

## 6.2 READY

Price is approaching the trigger level.

Default proximity:

```text
distance_to_trigger <= configured_ready_threshold
```

The existing pattern work proposes a 1% "ready" proximity for ascending triangles. Pattern-specific configuration must remain versioned.

Example:

```text
READY — Ascending Triangle

Current: ₹1,238
Trigger: ₹1,250
Distance: 0.96%
Volume: 1.3×
Trend: Bullish
```

The READY state is an early-warning signal, not a confirmed breakout.

---

## 6.3 TRIGGERED

The defined breakout/breakdown condition has occurred.

The trigger must use the frozen pattern-specific breakout rule.

A triggered event must record:

- Trigger price
- Trigger timestamp
- Trigger bar
- Pattern ID
- Pattern version
- Breakout direction
- Volume ratio
- Relevant indicator values

---

## 6.4 CONFIRMED

A triggered event has satisfied the required confirmation conditions.

Confirmation may include:

- Breakout condition
- Volume condition
- Trend alignment
- Relative strength
- Required candle behavior
- Retest behavior where applicable
- Risk/reward requirement

Confirmation rules must be explicit and versioned.

---

## 6.5 RETEST

Price returns toward the breakout level after a confirmed breakout.

The system should record:

- Retest price
- Retest depth
- Number of retest attempts
- Retest volume
- Bars from breakout to retest
- Whether price held the breakout level

Retest data belongs in the **research record**, not the production pattern result.

---

## 6.6 CONTINUATION

Price moves away from the breakout level while maintaining the defined setup conditions.

This state is informational and should not generate repeated alerts for every bar.

---

## 6.7 INVALIDATED

The pattern or setup no longer satisfies its invalidation condition.

Examples:

- Price closes beyond structural invalidation level.
- Breakout fails according to pattern-specific rules.
- Pattern geometry breaks.
- Stop/invalidation level is breached.

The system must generate one invalidation event per signal lifecycle.

---

## 6.8 NOT_TRIGGERED

The pattern expired without triggering.

Examples:

- Pattern structure expired.
- Maximum pattern duration reached.
- Price never crossed the trigger.

---

## 6.9 INCONCLUSIVE

The system could not reliably assess the outcome because of:

- Missing market data
- Data-quality failure
- Market/session anomaly
- Insufficient bars

It must never be silently treated as success or failure.

---

# 7. Pattern Coverage

Initial live support:

1. Existing support/resistance
2. Rectangle
3. Higher-high / higher-low
4. Ascending triangle
5. Descending triangle
6. Symmetrical triangle
7. Double bottom
8. Double top
9. Head & shoulders
10. Bull flag
11. Bear flag
12. Cup & handle
13. Wedges
14. Channels

Pattern availability depends on the approved NI-3 implementation.

---

# 8. P-1 Geometry Integration

The live engine shall use the P-1 shared geometry method for:

- Triangles
- Wedges
- Channels

P-1:

1. Select the last 5–6 alternating swing points.
2. Fit a line through highs.
3. Fit a line through lows.
4. Verify price remains inside the structure using the existing ATR tolerance.
5. Verify lines do not cross during the valid structure.
6. Classify shape using upper/lower slopes.

Shape classification:

| Upper line | Lower line | Shape |
|---|---|---|
| Flat | Rising | Ascending triangle |
| Falling | Flat | Descending triangle |
| Falling | Rising | Symmetrical triangle |
| Rising, steeper | Rising | Rising wedge |
| Falling | Falling, steeper | Falling wedge |
| Rising, parallel | Rising, parallel | Ascending channel |
| Falling, parallel | Falling, parallel | Descending channel |

The existing percentage rules remain responsible for applicable flatness, breakout, and volume requirements.

---

# 9. Pattern Detection vs Signal Engine

The architecture must separate:

```text
Pattern Detector
      ↓
Pattern Record
      ↓
Signal Evaluator
      ↓
Signal State Machine
      ↓
Alert Aggregator
      ↓
User Notification
```

The pattern detector answers:

> "What structure exists?"

The signal engine answers:

> "What state is this structure currently in?"

The alert engine answers:

> "Does the user need to be notified now?"

---

# 10. Technical Confirmation Layer

The confirmation engine may consume:

- ATR
- ADX
- RSI
- EMA relationships
- Moving-average slope
- Volume ratio
- Relative strength
- Breakout distance
- Candle body %
- Close position
- Retest depth
- Retest volume

Only indicators explicitly enabled for a signal version may affect confirmation.

Each signal must preserve the indicator values used at decision time.

---

# 11. Volume Confirmation

Existing and new pattern rules must remain distinct unless formally changed through a new research version.

### Existing patterns

Current frozen behavior:

> Follow-through bar volume between **1.0× and 4.0×** 20-day average volume.

The weak/normal/supporting/strong bands are labels and do not change the pass/fail rule.

### New patterns

Current NI-3 proposal:

> Breakout bar volume **≥ 1.5×** 20-day average volume.

The system must record the raw volume ratio regardless of pass/fail.

---

# 12. Signal Components

> **Amended 2026-09-23 (owner decision) per §38.19 Amendment E position 2.** This section previously
> specified an explainable 0–100 signal score with a seven-component weighting that summed to 100%.
> **The single headline number is removed**, and **retest quality and risk/reward are removed from any
> live weighting**. The components themselves stay. Any composite of them is a research object: it must
> be pre-registered in a later study version, tested, and only then shown. The original text is
> preserved in git history.

The system exposes **components, not a headline number**. Each component is shown on its own, with its
own value, so a reader can see what is strong and what is weak rather than a single figure that hides it.

Live components:

| Component | Shown | In live weighting |
|---|---|---|
| Pattern quality | yes | — |
| Breakout quality | yes | — |
| Volume confirmation | yes | — |
| Trend alignment | yes | — |
| Relative strength | yes | — |
| Retest quality | yes, as a row event | **no** (Amendment E) |
| Risk/reward | owner-only until NI-1a | **no** (Amendment E) |

There is no total, because there is no composite to total. Components are descriptive and must never be
presented as a probability of success.

Example:

```text
CONFIRMED_BREAKOUT

Pattern       18/20
Breakout      19/20
Volume        14/15
Trend         13/15
Relative      8/10
```

Component definitions must be configuration-versioned and must not be tuned against the evaluation
dataset. The contract that freezes this is `research/charting/signal_contract.py`
(`SIGNAL_FIELDS["score_components"]`; there is deliberately no `score` field).

---

# 13. Trade Setup Information

A confirmed signal may display:

```text
Entry
Stop
Target 1
Target 2
Risk per share
Reward/Risk
Invalidation level
```

These are **informational research/setup outputs**, not broker orders.

Example:

```text
CONFIRMED BREAKOUT

Entry       ₹1,256
Stop        ₹1,218
Target 1    ₹1,300
Target 2    ₹1,320

Risk/share  ₹38
R:R         1 : 1.68
```

Every calculation must be reproducible from the stored signal record.

---

# 14. Alert Types

## 14.1 Pattern Alert

```text
WATCH — CG Power
Ascending Triangle detected
Resistance ₹1,250
```

## 14.2 Ready Alert

```text
READY — CG Power
Price ₹1,238
Breakout ₹1,250
Distance 0.96%
```

## 14.3 Breakout Alert

```text
TRIGGERED — CG Power
Breakout ₹1,256
Volume 1.7×
```

## 14.4 Confirmation Alert

```text
CONFIRMED — CG Power
Ascending Triangle
₹1,256
Volume 1.7×
Stop ₹1,218
Target ₹1,320
```

## 14.5 Retest Alert

```text
RETEST — CG Power
Breakout level ₹1,256 being tested
Retest volume 0.8×
```

## 14.6 Failure Alert

```text
INVALIDATED — CG Power
Breakout failed
Price closed below ₹1,218
```

---

# 15. Alert Aggregation

The system must avoid notification spam.

Multiple technical events occurring on the same bar/session must be combined into one alert.

Example:

```text
RSI crossed 50
ADX increased
EMA crossed
Volume increased
Pattern broke out
```

must produce:

```text
CONFIRMED BREAKOUT
```

rather than five separate notifications.

---

# 16. Alert Deduplication

Each alert must have:

```text
alert_id
signal_id
pattern_id
symbol
timeframe
state
event_timestamp
alert_version
```

Duplicate alerts are suppressed using:

```text
symbol + timeframe + pattern_id + state + event_bar
```

A new alert is generated only when the lifecycle enters a new meaningful state.

---

# 17. Timeframes

Initial live monitoring:

### 15-minute

Use for:

- Early setup detection
- Breakout detection
- Volume confirmation
- Retest monitoring

### 1-hour

Use for:

- Structural confirmation
- Trend confirmation
- Higher-timeframe pattern context

### Daily

Use for:

- Positional pattern signals
- Research-grade pattern detection
- Historical comparability

Every alert must explicitly display its timeframe.

---

# 18. Live Signal Example

```text
┌─────────────────────────────────────┐
│ 🟢 CONFIRMED BREAKOUT               │
│                                     │
│ CG Power                            │
│ Ascending Triangle                  │
│ 15-minute                           │
│                                     │
│ Entry       ₹1,256                  │
│ Stop        ₹1,218                  │
│ Target 1    ₹1,300                  │
│ Target 2    ₹1,320                  │
│ R:R         1 : 1.68                │
│                                     │
│ Volume      1.7×                    │
│ Trend       Bullish                 │
│ ADX         27                      │
│ RSI         64                      │
│                                     │
│ Why confirmed?                      │
│ ✓ Pattern valid                     │
│ ✓ Breakout confirmed                │
│ ✓ Volume confirmed                  │
│ ✓ Trend aligned                    │
└─────────────────────────────────────┘
```

---

# 19. Chart Overlay

When a signal exists, the chart must show:

- Pattern geometry
- Trigger line
- Entry
- Stop/invalidation
- Target 1
- Target 2
- Breakout marker
- Retest marker
- Signal state
- Relevant volume information

For P-1 patterns, the displayed lines must be the same fitted lines used by the detector.

No manually approximated geometry.

---

# 20. Signal Detail View

Selecting a signal opens:

### Summary

- Symbol
- Pattern
- Timeframe
- State
- Current price
- Trigger

### Evidence

- Pattern geometry
- Trend
- Volume
- Relative strength
- Indicators
- Candle characteristics

### Setup

- Entry
- Stop
- Targets
- Risk/reward

### Lifecycle

```text
10:15 WATCH
11:00 READY
11:30 TRIGGERED
11:45 CONFIRMED
13:15 RETEST
14:00 CONTINUATION
```

### Research context

- Historical comparable count
- Historical success rate, where available
- Expected move, where available
- Invalidation behavior

Historical statistics must be clearly labelled as research results and must not be presented as guarantees.

---

# 21. Data Model

## 21.1 Pattern Record

```text
pattern_id
symbol
timeframe
pattern_type
pattern_version
detector_fingerprint

start_timestamp
end_timestamp
detection_timestamp

geometry
trigger_level
invalidation_level

pattern_state
```

## 21.2 Signal Record

```text
signal_id
pattern_id
symbol
timeframe

signal_version
indicator_version
pattern_version

state
direction

event_timestamp
data_timestamp
generated_timestamp

trigger_price
entry_price
stop_price
target_1
target_2

atr
adx
rsi
volume_ratio
relative_strength

signal_score

score_components

invalidation_condition
```

## 21.3 Alert Record

```text
alert_id
signal_id
alert_type
alert_state

created_at
delivered_at

channel
delivery_status

deduplication_key
```

---

# 22. Versioning

Every signal must contain:

```text
pattern_version
signal_version
indicator_version
strategy_version
detector_fingerprint
```

If any signal-generation rule changes, increment the appropriate version.

Never modify historical signal records in place.

---

# 23. Research Integrity

The live signal system must not modify:

- Frozen v1 study plan
- Frozen detector configuration
- Sealed research period
- Historical research records

The new pattern research must use a separate **study-plan v2**.

Study-plan v2 must define:

- New pattern types
- Swing sizes
- Entry
- Stops
- Targets
- Costs
- Control groups
- Holding periods
- Number of combinations
- Detector fingerprint

Every tested combination must be reported.

---

# 24. No Look-Ahead Bias

Live signals must only use data available at signal generation time.

Forbidden:

- Current day's final low when generating an earlier intraday signal
- Future volume
- Future candle close
- Future swing confirmation
- Future corporate announcements
- Any derived field calculated using future bars

The signal engine must record the exact data timestamp used for every decision.

---

# 25. Market Data Requirements

The live engine requires:

- OHLCV
- Timestamp
- Trading session status
- Corporate action adjustments where applicable
- Symbol mapping
- Timeframe aggregation

Data quality failures must generate `INCONCLUSIVE` rather than silently creating a signal.

---

# 26. Signal Processing

Recommended pipeline:

```text
Market Data
    ↓
Bar Validation
    ↓
Indicator Calculation
    ↓
Swing Detection
    ↓
Pattern Detection
    ↓
Pattern State
    ↓
Trigger Evaluation
    ↓
Confirmation Evaluation
    ↓
Signal State Machine
    ↓
Risk/Reward Calculation
    ↓
Alert Aggregation
    ↓
Notification
    ↓
Audit Record
```

---

# 27. Alert Channels

Initial:

1. In-app dashboard
2. Browser notification
3. Sound notification, optional

Future:

4. Email
5. Mobile push
6. Telegram/WhatsApp, subject to integration and permissions

Users must be able to configure which states generate notifications.

---

# 28. User Alert Preferences

Configurable per user:

```text
Symbols
Timeframes
Pattern types

WATCH alerts
READY alerts
TRIGGERED alerts
CONFIRMED alerts
RETEST alerts
INVALIDATED alerts

Minimum volume ratio

Quiet hours
Maximum alerts per hour
```

Default configuration should prioritize **READY, CONFIRMED, and INVALIDATED** alerts to minimize noise.

---

# 29. Alert Priority

| State | Priority |
|---|---|
| WATCH | Low |
| READY | Medium |
| TRIGGERED | High |
| CONFIRMED | Critical |
| RETEST | Medium |
| CONTINUATION | Low |
| INVALIDATED | High |

Priority is a notification priority, not an assessment of investment quality.

---

# 30. API Requirements

### GET `/signals`

Filters:

```text
symbol
timeframe
pattern
state
from
to
```

### GET `/signals/{signal_id}`

Returns complete signal and lifecycle.

### GET `/alerts`

Returns user alerts.

### POST `/alerts/preferences`

Updates notification preferences.

### WebSocket / SSE

Live signal events:

```json
{
  "event": "SIGNAL_STATE_CHANGED",
  "signal_id": "SIG-123",
  "symbol": "CGPOWER",
  "timeframe": "15m",
  "state": "CONFIRMED",
  "timestamp": "2026-09-22T11:45:00+05:30"
}
```

---

# 31. Performance Requirements

Target:

- Market-data-to-signal latency: < 5 seconds after bar availability
- Alert generation: < 2 seconds after signal state transition
- Dashboard update: < 3 seconds
- Duplicate alert rate: 0
- Missed valid event rate: monitored and reported

For end-of-bar signals, the system must not publish the signal before the required bar is complete.

---

# 32. Failure Handling

If market data is delayed:

```text
DATA_DELAYED
```

If data is missing:

```text
INCONCLUSIVE
```

If indicator calculation fails:

```text
SIGNAL_UNAVAILABLE
```

If notification delivery fails:

```text
DELIVERY_FAILED
```

The underlying signal record must remain intact.

---

# 33. Observability

Track:

- Signals generated
- Signals by pattern
- Signals by timeframe
- State transitions
- Alert delivery latency
- Alert delivery failures
- Duplicate suppression
- Data latency
- Data gaps
- Indicator calculation failures
- Pattern detection failures

Metrics should be available for operational monitoring.

---

# 34. QA Requirements

Test:

### Pattern tests

- Correct geometry
- Correct trigger
- Correct invalidation
- Correct lifecycle

### Signal tests

- WATCH → READY
- READY → TRIGGERED
- TRIGGERED → CONFIRMED
- CONFIRMED → RETEST
- CONFIRMED → INVALIDATED
- Expiry → NOT_TRIGGERED
- Data failure → INCONCLUSIVE

### Bias tests

Verify no future bars are used.

### Alert tests

- Deduplication
- Multiple simultaneous conditions
- User preferences
- Notification retry
- Session boundaries

### Regression tests

Frozen pattern behavior must remain unchanged when alert functionality is deployed.

---

# 35. Acceptance Criteria

The release is acceptable when:

- [ ] A detected pattern can enter WATCH.
- [ ] Price proximity correctly generates READY.
- [ ] Breakout correctly generates TRIGGERED.
- [ ] Confirmation conditions correctly generate CONFIRMED.
- [ ] Retest is detected and recorded.
- [ ] Invalidations are detected.
- [ ] NOT_TRIGGERED and INCONCLUSIVE are represented.
- [ ] Every state transition has a timestamp.
- [ ] Every signal contains pattern/indicator versions.
- [ ] Duplicate alerts are suppressed.
- [ ] Chart overlays match detector geometry.
- [ ] Entry/stop/target calculations are reproducible.
- [ ] Live processing uses no future information.
- [ ] Existing frozen research rules are unchanged.
- [ ] Study-plan v1 remains untouched.
- [ ] New pattern research is versioned as v2.
- [ ] Signal lifecycle is visible to the user.
- [ ] Alert preferences work correctly.
- [ ] Data failures do not produce false signals.

---

# 36. Implementation Phases

## Phase 1 — Signal Contract

Define and freeze:

- Signal states
- State transitions
- Signal schema
- Alert schema
- Versioning
- Timestamp semantics

## Phase 2 — Core Signal Engine

Implement:

- Pattern → signal adapter
- Trigger detection
- Confirmation
- Invalidation
- State machine

## Phase 3 — Alert Engine

Implement:

- Alert aggregation
- Deduplication
- Dashboard notifications
- Browser notifications
- User preferences

## Phase 4 — Chart Integration

Implement:

- Pattern geometry
- Trigger
- Entry
- Stop
- Targets
- Retest
- State markers

## Phase 5 — Research Integration

Implement:

- Signal lifecycle logging
- Research enrichment
- Historical comparable lookup
- Study-plan v2 compatibility

## Phase 6 — QA / Validation

Run:

- Unit tests
- Historical replay
- No-look-ahead tests
- Live paper simulation
- Alert reliability tests

---

# 37. Recommended Initial Release

The first production release should deliberately stay narrow:

### Timeframes

- 15-minute
- 1-hour
- Daily

### States

- WATCH
- READY
- TRIGGERED
- CONFIRMED
- RETEST
- INVALIDATED
- NOT_TRIGGERED
- INCONCLUSIVE

### Alerts

Prioritize:

1. READY
2. CONFIRMED
3. INVALIDATED

### Patterns

Start with:

- Existing frozen patterns
- P-1 triangles/wedges/channels
- P-2 flags/pennants

Then add the remaining NI-3 patterns after their rules are frozen.

---

# 38. Key Design Decision

The live system should **not** be a separate technical-analysis brain.

It should be a real-time execution layer over the same deterministic pattern and indicator framework:

```text
                 FROZEN RULES
                      │
          ┌───────────┴───────────┐
          │                       │
     HISTORICAL              LIVE MARKET
       ENGINE                    ENGINE
          │                       │
          ▼                       ▼
      RESEARCH                 SIGNAL
      RESULTS                 LIFECYCLE
                                  │
                                  ▼
                              ALERTS
```

This preserves the most important property of the platform:

> **The thing that is validated historically is the thing that generates the live signal.**

---

# 39. Success Metrics

The first release should not be judged only by number of alerts.

Track:

- Alert latency
- Missed signal rate
- Duplicate alert rate
- Data-quality failure rate
- State-transition correctness
- Percentage of alerts with complete explanation
- Historical/live rule consistency
- User alert engagement
- False-alert rate
- Signal lifecycle completeness

Trading performance metrics should be evaluated separately through the frozen research framework rather than tuned directly through live-alert engagement.

---

# 40. Final Product Definition

The completed system should allow a user to open a chart and immediately understand:

1. **What pattern is forming?**
2. **How close is it to triggering?**
3. **What exactly triggers it?**
4. **Has it triggered?**
5. **Has it been confirmed?**
6. **What evidence confirms it?**
7. **Where is the invalidation level?**
8. **What are the setup entry/target levels?**
9. **Is there a retest?**
10. **Has the setup failed?**
11. **What historical research supports the setup?**
12. **Exactly when did the signal become available?**

The user should never need to infer these facts from multiple indicators or manually inspect several screens.

The end result is:

> **Pattern → Evidence → Signal → Alert → Lifecycle → Research validation**

with every stage deterministic, explainable, timestamped, and versioned.
