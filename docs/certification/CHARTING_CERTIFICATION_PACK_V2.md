> **Filed in the repository on 2026-09-23 at the owner's request.** The body below is the owner's
> document as received, verbatim, from
> `nivesh_charting_pattern_signal_certification_pack_v2 (1).zip`. Its companion
> `certification_manifest.json` is filed alongside as `certification_manifest.json`.
>
> **Checked against the code on 2026-09-23** (`docs/certification/COVERAGE_ASSESSMENT.md`):
>
> - The manifest's registry counts (3 enabled / 16 specified-disabled / 19 total) match
>   `research/charting/pattern_registry.py` exactly.
> - All six `critical_blockers` match the gaps recorded independently in `docs/charting.md` §39.10.
> - The volume rules match the frozen split (#109, #110): 1.00–4.00× follow-through for the three
>   frozen families, ≥ 1.50× breakout bar for the sixteen new ones, reference average excluding the
>   breakout bar (`research/charting/series.py: avg_volume`), raw ratio stored on failure.
> - §5's scope correction is right: `HH_HL` is one family covering both directions
>   (`patterns.py: _hh_hl_patterns` sets `direction` BULLISH/BEARISH); there is no separate LH/LL
>   family and none should be added.
>
> Where this pack and `docs/charting.md` §39 differ, §39 governs, and the difference is recorded in
> the coverage assessment rather than resolved by editing this file.

# Nivesh AI — Charting, Pattern Detection & Signal-Indicator Certification Pack v2.0

**Source of truth:** `charting.md` — Integrated Charting, Pattern Detection & Historical Validation PRD, including §38 and the owner specification in §39 dated 2026-09-23.

**Scope of this pack:** chart rendering, indicator calculation/display, pattern detection, pattern lifecycle, breakout/volume/context confirmation, signal-event integrity, historical replay, and research validation.

**Explicitly excluded from this pack:** broker order execution, paper-trading implementation, autonomous trading, portfolio construction, position sizing, and live trading execution.

---

## 1. Certification objective

The certification goal is not to prove that a pattern is profitable.

It is to prove that Nivesh:

1. renders the correct chart data;
2. calculates/serves indicators from the approved catalogue;
3. detects only registered patterns;
4. detects patterns deterministically;
5. never uses future information;
6. preserves the frozen family-specific rules;
7. separates pattern geometry from confirmation/context indicators;
8. maps pattern lifecycle states consistently;
9. stores explainable evidence rather than an opaque headline score;
10. produces reproducible research/replay results;
11. prevents unsupported patterns from generating alerts;
12. preserves provider, dataset, configuration, and calculation provenance.

The PRD explicitly separates chart rendering, indicator calculation, pattern detection, confirmation, market/sector context, and historical outcome evaluation. fileciteturn0file0L58-L67

---

# 2. Certification architecture

```text
                    CHART WORKSPACE
                         |
                 validated OHLCV
                         |
                 Indicator Service
                         |
          +--------------+--------------+
          |                             |
   Geometry Indicators          Confirmation Indicators
          |                             |
          v                             v
   PATTERN DETECTOR              SIGNAL EVALUATOR
          |                             |
          |                      volume / RSI / ADX /
          |                      EMA / MACD / RS /
          |                      market / sector
          v                             |
   PATTERN LIFECYCLE <------------------+
          |
          v
    ALERTABLE EVENT
          |
          v
   HISTORICAL REPLAY
          |
          v
   OUTCOME / RESEARCH
```

The architectural invariant is:

> A pattern detector may determine whether the historical price structure satisfies its formal definition. It must not decide whether the pattern is profitable, high-probability, tradeable, or worth alerting on.

The PRD defines the pipeline as OHLCV → validation → pivots → structure → candidate → geometry → minimum evidence → lifecycle → detection. fileciteturn0file0L3360-L3399

---

# 3. Certification status model

Use these statuses:

```text
NOT_IMPLEMENTED
IMPLEMENTED
UNIT_CERTIFIED
PIT_CERTIFIED
HISTORICALLY_VALIDATED
ALERT_ELIGIBLE
BLOCKED
```

`ALERT_ELIGIBLE` is not the same as `PROFITABLE`.

A pattern can be technically certified while historical validation finds no useful edge.

---

# 4. Current pattern registry

The PRD's §39 registry is the single source of truth for pattern families that may be detected/alerted.

## Currently enabled

| Family | Detector | Geometry | Volume | v1 |
|---|---|---|---|---|
| Support / resistance | `SR-v1` | own | follow-through 1.0–4.0× | **ENABLED** |
| Rectangle | `RECT-v1` | own | follow-through 1.0–4.0× | **ENABLED** |
| Higher highs / higher lows | `STRUCTURE-v1` | own | follow-through 1.0–4.0× | **ENABLED** |

## Specified but disabled

| Family | Detector | Geometry | Volume | v1 |
|---|---|---|---|---|
| Ascending triangle | `TRI-ASC-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Descending triangle | `TRI-DESC-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Symmetrical triangle | `TRI-SYM-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Rising wedge | `WEDGE-R-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Falling wedge | `WEDGE-F-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Ascending channel | `CHANNEL-ASC-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Descending channel | `CHANNEL-DESC-v1` | P-1 | breakout bar ≥1.5× | DISABLED |
| Bull flag | `FLAG-BULL-v1` | P-2 | breakout bar ≥1.5× | DISABLED |
| Bear flag | `FLAG-BEAR-v1` | P-2 | breakout bar ≥1.5× | DISABLED |
| Bull pennant | `PENNANT-BULL-v1` | P-2 | breakout bar ≥1.5× | DISABLED |
| Bear pennant | `PENNANT-BEAR-v1` | P-2 | breakout bar ≥1.5× | DISABLED |
| Double bottom | `DB-v1` | own | breakout bar ≥1.5× | DISABLED |
| Double top | `DT-v1` | own | breakout bar ≥1.5× | DISABLED |
| Head & shoulders | `HS-v1` | own | breakout bar ≥1.5× | DISABLED |
| Inverse head & shoulders | `IHS-v1` | own | breakout bar ≥1.5× | DISABLED |
| Cup & handle | `CAH-v1` | own | breakout bar ≥1.5× | DISABLED |

**Certification rule:** unsupported/disabled patterns must never produce production alerts.

The registry requires registration, enabled detector version, required OHLCV availability, and a determinable lifecycle without look-ahead before a family is alertable. fileciteturn0file0L3446-L3461

---

# 5. Important scope correction

Do **not** add `LH/LL` as a separate registry family merely because it appeared in an earlier draft or test package.

The authoritative §39 registry contains:

- HH/HL
- but not a separate LH/LL family.

Similarly, do not silently add other textbook patterns that are not in the registry.

The registry, not the fixture count or an external charting website, controls production detector coverage.

---

# 6. Pattern detector classes

The PRD establishes three indicator classes.

## Class A — Pattern geometry

These define whether the pattern exists.

Examples:

- swing high/low
- ATR-normalised tolerance
- trendline slope
- convergence
- parallelism
- pivot relationships
- price similarity
- duration

**Class A may create or invalidate the pattern.**

## Class B — Breakout confirmation

Examples:

- close beyond trigger
- volume / relative volume
- breakout magnitude
- ATR-normalised breakout distance
- retest

**Class B does not create the pattern.**

It determines whether an already detected structure has broken/confirmed.

## Class C — Context confirmation

Examples:

- ADX
- RSI
- EMA
- MACD
- relative strength
- market trend
- sector trend

**Class C is evidence consumed by the signal evaluator.**

It must not be embedded into a pattern-definition predicate.

This distinction is explicitly required by §39.7. fileciteturn0file0L3503-L3524

---

# 7. Indicator certification matrix

## 7.1 Class A — geometry

| Pattern family | Swing | ATR | Slope | Convergence | Parallelism |
|---|---:|---:|---:|---:|---:|
| Support / resistance | Required | Required | — | — | — |
| Rectangle | Required | Required | Required | — | — |
| HH / HL | Required | Required | — | — | — |
| Ascending triangle | Required | Required | Required | Required | — |
| Descending triangle | Required | Required | Required | Required | — |
| Symmetrical triangle | Required | Required | Required | Required | — |
| Rising wedge | Required | Required | Required | Required | — |
| Falling wedge | Required | Required | Required | Required | — |
| Ascending channel | Required | Required | Required | — | Required |
| Descending channel | Required | Required | Required | — | Required |
| Bull flag | Required | Required | Required | — | Required |
| Bear flag | Required | Required | Required | — | Required |
| Bull pennant | Required | Required | Required | Required | — |
| Bear pennant | Required | Required | Required | Required | — |
| Double bottom | Required | Required | — | — | — |
| Double top | Required | Required | — | — | — |
| Head & shoulders | Required | Required | Neckline | — | — |
| Inverse H&S | Required | Required | Neckline | — | — |
| Cup & handle | Required | Required | — | — | — |

The PRD explicitly states that similarity tolerances for peaks, troughs, shoulders and rims are also geometry. fileciteturn0file0L3526-L3573

---

# 8. Class B — breakout and volume

## Frozen P0 families

For:

- Support/resistance
- Rectangle
- HH/HL

the current regime is:

```text
PRICE:
close beyond level ± 0.25 × ATR
        |
        v
PRICE_CONFIRMED

VOLUME:
follow-through relative volume 1.00–4.00×
        |
        v
VOLUME_CONFIRMED
```

The baseline configuration says `require_volume_confirmation: false`, so volume does not gate `PRICE_CONFIRMED` for these frozen families.

## New families

For the sixteen disabled families:

```text
BREAKOUT_CANDIDATE
        |
        +-- breakout bar volume >= 1.5 × 20-session average
        |
        v
CONFIRMED_BREAKOUT
```

The raw volume ratio must always be stored.

The PRD explicitly says the volume rule is a registry property and must not be converted into one global rule. fileciteturn0file0L3575-L3593

---

# 9. Class C signal indicators

These are **proposed context evidence**, not frozen pattern predicates.

| Family | RSI | ADX | EMA stack | RS vs index | RS vs sector | MACD |
|---|---|---|---|---|---|---|
| S/R | Optional | Optional | Optional | Optional | Optional | Optional |
| Rectangle | Optional | Recommended* | Optional | Optional | Optional | Optional |
| HH/HL | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Ascending triangle | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Descending triangle | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Symmetrical triangle | Optional | Recommended* | Optional | Optional | Optional | Optional |
| Rising wedge | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| Falling wedge | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| Ascending channel | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Descending channel | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Bull flag | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Bear flag | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Bull pennant | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Bear pennant | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |
| Double bottom | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| Double top | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| H&S | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| Inverse H&S | Recommended | Recommended* | Optional | Recommended | Optional | Recommended |
| Cup & handle | Optional | Recommended* | Recommended | Recommended | Recommended* | Optional |

`*` The PRD marks ADX and stock-vs-sector RS as unavailable today; these recommendations are proposed scope, not certified live inputs.

**Hard rule:** no Class C indicator may become `Required` without a separately pre-registered detector/signal specification.

The PRD explicitly says none of these Class C cells is frozen. fileciteturn0file0L3595-L3636

---

# 10. Indicator catalogue certification

The chart indicator catalogue must certify:

- indicator ID
- indicator name
- category
- preset ID
- parameters
- default pane
- output fields
- calculation version
- warmup period
- point-in-time validation status
- missing-data policy

The chart workspace uses **controlled presets**, not arbitrary browser parameters.

The current initial catalogue includes the existing eight series plus:

```text
SMA 10/20/50/100/200
EMA 10/20/50/100/200
RSI 7/14/21
Bollinger 20×2
MACD 12/26/9
ATR 14
```

The catalogue is versioned and hashed with the snapshot. fileciteturn0file0L2636-L2667

---

# 11. Indicator test certification

Every indicator preset must pass:

### Calculation

- known-value fixture
- parameter fixture
- warmup fixture
- missing-input fixture
- boundary fixture
- repeated calculation determinism

### Point-in-time

At bar `t`, the indicator may use only data available through `t`.

### API/UI parity

```text
API indicator value
        =
chart crosshair value
        =
Data View value
```

The chart acceptance criteria explicitly require indicator values at the crosshair to match the API/Data view for the same date. fileciteturn0file0L2811-L2829

### Versioning

Changing calculation logic requires a new calculation version/catalogue version.

---

# 12. Pivot certification

Every pivot stores:

```text
pivot_index
pivot_date
confirmed_index
confirmed_date
```

The key invariant is:

```text
confirmed_index <= event_bar
```

For a pivot needing `right_bars` future bars:

```text
pivot_confirmed_at
=
pivot_bar + right_bars
```

Historical replay must slice data before detection rather than detect on the complete dataset and filter afterward.

This is explicitly implemented through `swings_as_of()` in the PRD. fileciteturn0file0L3428-L3444

### Tests

```text
PIV-001 normal high
PIV-002 normal low
PIV-003 equal high
PIV-004 equal low
PIV-005 tie handling
PIV-006 insufficient future bars
PIV-007 replay as-of correctness
PIV-008 future-bar mutation
PIV-009 deterministic repeat
```

---

# 13. Data-quality certification

Detection must stop when required geometry cannot be trusted.

Critical rejection cases:

```text
missing OHLC
high < max(open, close)
low > min(open, close)
high < low
duplicate timestamps
material chronological disorder
insufficient history
```

The failure must propagate through:

```text
validation reason code
        ↓
data status
        ↓
DATA_BLOCKED
        ↓
research INCONCLUSIVE
```

It must not silently become “no pattern”.

The PRD explicitly distinguishes the reason code, data status, lifecycle state and research state. fileciteturn0file0L3401-L3426

---

# 14. Pattern lifecycle certification

The frozen research lifecycle is:

```text
FORMING
    ↓
EARLY_SIGNAL
    ↓
BREAKOUT_CANDIDATE
    ↓
CONFIRMED_BREAKOUT
```

with terminal/alternative states including:

```text
INVALIDATED
FAILED_BREAKOUT
NOT_TRIGGERED
INCONCLUSIVE
```

Signal-facing names map as:

| Signal vocabulary | Research state |
|---|---|
| WATCH | FORMING |
| READY | EARLY_SIGNAL |
| TRIGGERED | BREAKOUT_CANDIDATE |
| CONFIRMED | CONFIRMED_BREAKOUT |
| INVALIDATED | INVALIDATED / FAILED_BREAKOUT |
| NOT_TRIGGERED | NOT_TRIGGERED |
| INCONCLUSIVE | INCONCLUSIVE |

`RETEST` and `CONTINUATION` are events, not states.

This mapping is explicitly frozen in the PRD amendment. fileciteturn0file0L3296-L3309

---

# 15. READY certification

READY corresponds to the NI-3 readiness band.

Baseline:

```text
within 1% of the live trigger level
```

READY means:

```text
EARLY_SIGNAL
```

It does **not** mean:

- breakout
- confirmation
- probability
- tradeability
- profitability

The PRD explicitly identifies READY at 1% as the NI-3 S9 mapping. fileciteturn0file0L3300-L3304

---

# 16. Breakout certification

For each pattern, test independently:

1. No boundary breach.
2. Wick-only breach.
3. Intrabar breach.
4. Close beyond threshold.
5. Exact threshold.
6. Just below threshold.
7. Just above threshold.
8. High volume/no breakout.
9. Breakout/low volume.
10. Confirmed breakout.
11. Failed breakout.

For frozen P0:

```text
threshold = level ± 0.25 × ATR
```

For the sixteen new families:

```text
breakout candidate = level(t) × (1 ± 0.5%)
```

Do not merge these rules.

---

# 17. Volume certification

### Frozen P0

Test:

```text
RVOL < 1.00
RVOL = 1.00
RVOL between 1.00 and 4.00
RVOL = 4.00
RVOL > 4.00
```

### New families

Test:

```text
RVOL < 1.50
RVOL = 1.50
RVOL > 1.50
```

The reference average must exclude the breakout bar.

The raw ratio must be stored even when confirmation fails.

### Critical negative test

```text
HIGH VOLUME
+
NO PRICE BREAKOUT
=
NO BREAKOUT
```

---

# 18. Pattern evidence certification

Do not certify a pattern using a single score.

Store factual evidence such as:

```json
{
  "touches": 4,
  "pivot_count": 7,
  "duration_bars": 38,
  "boundary_error_pct": 0.72,
  "convergence_ratio": 0.61,
  "volume_contraction_pct": 28.4
}
```

The PRD explicitly rejects an unexplained headline quality/confidence score and requires evidence rather than opaque scoring. fileciteturn0file0L3664-L3687

---

# 19. Detector output certification

The existing pattern schema remains the contract.

The detector must preserve the common record and additionally expose:

```text
detector_version
config_version
config_fingerprint
flatness_test
first_known_date
reason_code
scale
```

Indicator values must follow the indicator contract.

### Detector MUST NOT emit

```text
headline score
confidence/probability
entry price
target price
tradability verdict
recommended stop
alert-worthiness flag
position quantity
R-multiple
historical hit rate
comparables
```

These belong downstream or to research.

This boundary is explicitly defined by §39.12. fileciteturn0file0L3689-L3725

---

# 20. No-lookahead certification

This is a **release blocker**.

## Test NLA-001 — sequential replay

Process one completed candle at a time.

At timestamp `t`:

```text
available_data <= t
```

## Test NLA-002 — future price mutation

Modify candles after `t`.

Pattern result at `t` must not change.

## Test NLA-003 — future volume mutation

Modify future volume.

Earlier confirmation must not change.

## Test NLA-004 — future pivot mutation

Modify bars after pivot confirmation.

Previously known pivot must remain unchanged.

## Test NLA-005 — batch vs sequential

```text
batch replay result
=
sequential replay result
```

## Test NLA-006 — incomplete candle

Current incomplete candle must not feed confirmation.

The PRD explicitly requires incomplete candles not to trigger confirmation. fileciteturn0file0L227-L244

---

# 21. Determinism certification

Same:

```text
OHLCV
+
detector version
+
indicator version
+
configuration
+
dataset
```

must produce the same:

```text
pattern IDs
states
pivots
levels
events
evidence
indicator values
reason codes
```

No:

- LLM judgement
- randomness
- sampling
- current-clock dependency
- network dependency
- provider response ordering dependency

The PRD explicitly requires deterministic detection and prohibits model judgement/LLM in the detection path. fileciteturn0file0L3360-L3375

---

# 22. Chart rendering certification

### P0

Test:

- candles
- OHLC
- line
- area
- volume
- synchronized crosshair
- zoom/pan
- range selection
- responsive layout
- full-screen
- manual core drawings
- indicator panes

### Pattern overlay

Test:

- pattern appears automatically
- only its own formation dates are drawn
- pivots align with API
- levels align with API
- click selects pattern
- other patterns dim
- view zooms to pattern
- details card shows rules and timeline
- manual drawings remain visually distinct
- forming/confirmed/failed/invalidated styles differ
- empty pattern state lists families checked

These are explicit W0/W1 acceptance requirements. fileciteturn0file0L2847-L2862

---

# 23. Chart/indicator provenance certification

Every displayed indicator must be traceable to:

```text
provider/data source
dataset version
calculation version
preset ID
catalogue version
timestamp
PIT status
missing-data policy
```

The chart must expose provenance and data status.

The PRD requires source/as-of status to remain visible and the provenance drawer/Data view to remain accessible. fileciteturn0file0L2613-L2616

---

# 24. Market and sector context certification

These are **signal/context inputs**, not pattern-definition inputs.

## Market

Test:

- benchmark return
- benchmark SMA20/50/200 position
- benchmark RSI/ADX
- market volatility
- breadth
- market regime
- gap/open conditions

## Sector

Test:

- sector return
- sector relative strength
- sector trend
- sector volatility
- stock minus sector return
- sector breadth

Context states:

```text
POSITIVE
NEUTRAL
NEGATIVE
MIXED
UNAVAILABLE
```

A context indicator cannot override failed geometry or invalid data.

---

# 25. Relative-strength certification

Current status:

```text
Stock vs NIFTY 500:
AVAILABLE

Stock vs sector:
NOT AVAILABLE / NOT SERVED
```

The current implementation has NIFTY 500 relative strength but not stock-vs-sector relative strength.

Therefore:

```text
RS_vs_index
    -> can be tested

RS_vs_sector
    -> BLOCKED until implemented
```

Do not fake sector relative strength from another metric.

---

# 26. ADX certification

Current status:

```text
ADX(14)
not served in the chart indicator catalogue
```

It exists privately in the regime implementation but is not currently served as a chart indicator.

Therefore:

```text
ADX-dependent signal evidence
=
BLOCKED until catalogue/service support exists
```

Do not silently substitute another trend indicator.

---

# 27. Fitted geometry prerequisites

The following are mandatory before P-1/P-2 families can be certified:

1. `trendline_value_at(pivots, t)`
2. convergence caller
3. parallelism metric

Current limitations identified in the PRD:

- slope exists but lacks intercept/fitted-line object;
- convergence helper exists but has no production caller;
- parallelism is not implemented.

Therefore P-1/P-2 pattern certification is blocked until these primitives exist.

The PRD explicitly identifies these as prerequisites. fileciteturn0file0L3638-L3662

---

# 28. Flatness convention certification

Do **not** harmonize all families.

## P0 families

Use ATR-normalised convention:

```text
boundary_drift_atr
=
abs(slope) × L / ATR

flat <= 0.50
sloped >= 0.75
```

## New families

Use the percentage convention defined by the frozen NI-3 source.

Every detector must record:

```text
flatness_test = ATR_DRIFT | PCT_DRIFT
```

This prevents a silent change to the frozen detector definition.

---

# 29. Configuration certification

The baseline research configuration contains:

```yaml
timeframe: 1D
swing_left_bars: 3
swing_right_bars: 3
atr_period: 14
volume_baseline_bars: 20
minimum_pattern_length: 15
maximum_pattern_length: 120
breakout_buffer_atr: 0.25
relative_volume_supporting: 1.20
relative_volume_strong: 1.50
confirmation_window_bars: 3
retest_window_bars: 5
require_close_confirmation: true
require_volume_confirmation: false
require_market_alignment: false
require_sector_alignment: false
allow_intrabar_confirmation: false
point_in_time_validation_required: true
```

These are research defaults, not optimized trading parameters.

Every run must preserve:

```text
configuration_id
configuration_hash
pattern_engine_version
indicator_version
dataset_version
created_at
created_by
```

---

# 30. Pattern certification test matrix

For **every enabled detector**:

### Geometry

```text
PAT-GEO-001 positive fixture
PAT-GEO-002 minimum evidence
PAT-GEO-003 boundary tolerance
PAT-GEO-004 pivot relationship
PAT-GEO-005 duration
PAT-GEO-006 invalid geometry
```

### Lifecycle

```text
PAT-LIFE-001 forming
PAT-LIFE-002 ready
PAT-LIFE-003 breakout
PAT-LIFE-004 confirmed
PAT-LIFE-005 invalidated
PAT-LIFE-006 failed
PAT-LIFE-007 expired
PAT-LIFE-008 data blocked
```

### Breakout

```text
PAT-BRK-001 wick only
PAT-BRK-002 exact threshold
PAT-BRK-003 below threshold
PAT-BRK-004 above threshold
PAT-BRK-005 failed breakout
```

### Volume

```text
PAT-VOL-001 below threshold
PAT-VOL-002 exact threshold
PAT-VOL-003 above threshold
PAT-VOL-004 high volume without breakout
PAT-VOL-005 follow-through
```

### Look-ahead

```text
PAT-NLA-001 future mutation
PAT-NLA-002 pivot confirmation
PAT-NLA-003 batch/sequential equivalence
PAT-NLA-004 incomplete candle
```

---

# 31. Signal-indicator certification

The signal evaluator must consume:

```text
Pattern
+
Pattern lifecycle
+
Breakout status
+
Volume evidence
+
Volatility evidence
+
RS evidence
+
Market context
+
Sector context
+
Data quality
```

It must NOT consume:

```text
future outcome
future mover list
future high/low
post-event fundamentals
post-event ownership
future market regime
```

The output should remain component evidence, not an opaque 0–100 score.

The PRD explicitly removed the headline score and retains component evidence. fileciteturn0file0L3270-L3278

---

# 32. Signal event contract

A signal event should reference the certified pattern rather than recreate it.

Minimum:

```text
event_id
pattern_id
symbol
timeframe
pattern_type
research_state
event_type
event_timestamp
observed_values
rule_id
rule_result
detector_version
indicator_version
configuration_hash
data_version
PIT_status
reason_code
```

Signal events should describe observed facts.

Example:

```text
ASCENDING_TRIANGLE
BREAKOUT_CANDIDATE
close crossed the registered breakout threshold
RVOL20 = 1.63
RS_vs_NIFTY500 = positive
market_context = positive
```

Do not turn this into:

```text
BUY
80% probability
target ₹X
```

inside the detector.

---

# 33. Alert eligibility certification

An event is alertable only when:

```text
registered pattern
+
enabled detector version
+
required data available
+
lifecycle determinable without look-ahead
+
signal contract satisfied
```

Unsupported/disabled families must fail closed.

`pattern_registry.assert_alertable()` is explicitly identified as the enforcement mechanism.

---

# 34. Historical replay certification

Replay must:

1. move chronologically;
2. expose only bars available at the cursor;
3. recalculate indicators using available history;
4. preserve pattern state as of the cursor;
5. never display final geometry before it existed;
6. preserve configuration/data fingerprints;
7. separately evaluate later outcomes.

The PRD requires replay bars after the cursor never to be sent to the chart and requires pattern overlays to reflect only the state known at the cursor. fileciteturn0file0L2739-L2747

---

# 35. Historical validation certification

Historical validation is separate from detector certification.

Measure:

```text
pattern frequency
detection precision
confirmation-to-breakout conversion
false-breakout rate
outcomes by horizon
MFE
MAE
market regime
sector
liquidity
volatility
relative-volume bucket
```

Compare against:

```text
random eligible universe
buy-at-next-open baseline
market benchmark
sector benchmark
cost-adjusted version
```

Never tune the detector against the locked test period.

---

# 36. Research integrity gates

### Gate R1

Configuration frozen.

### Gate R2

Dataset frozen.

### Gate R3

Detector fingerprint recorded.

### Gate R4

Indicator calculation versions recorded.

### Gate R5

PIT audit passes.

### Gate R6

Sequential replay equals batch replay.

### Gate R7

No future mutation changes earlier results.

### Gate R8

Historical outcome calculation occurs only after detection timestamp.

### Gate R9

Results are reproducible from stored artifacts.

---

# 37. Certification gates

A detector is certified only if:

| Gate | Required |
|---|---|
| Registry | PASS |
| Common schema | PASS |
| Data validation | PASS |
| Pivot tests | PASS |
| Geometry tests | PASS |
| Negative tests | PASS |
| Lifecycle tests | PASS |
| Breakout tests | PASS |
| Volume tests | PASS |
| No-lookahead | PASS |
| Determinism | PASS |
| Dedupe | PASS |
| Provenance | PASS |
| Configuration hash | PASS |
| Historical replay | PASS |

**Any critical failure blocks certification.**

---

# 38. Current project readiness from this PRD

## Ready / existing foundation

```text
Chart OHLCV rendering
Indicator service/catalogue
Swing detection
ATR
Relative volume
RSI
EMA
MACD
P0 pattern families:
  - S/R
  - Rectangle
  - HH/HL
Pattern overlays
Chart provenance
Historical replay framework
Data-quality framework
Configuration/versioning
```

## Blocked / incomplete for full pattern coverage

```text
Fitted trendline with intercept
trendline_value_at()
production convergence caller
parallelism
P-1 detectors
P-2 detectors
ADX chart service
stock-vs-sector relative strength
full Class C signal layer
```

The PRD explicitly states that P-1/P-2 cannot be built until the fitted-line primitives exist and that ADX/sector relative strength are not currently served. fileciteturn0file0L3643-L3662

---

# 39. Recommended implementation order

## Wave 0 — certify existing

```text
S/R
Rectangle
HH/HL
ATR
RVOL20
RSI
EMA
MACD
Chart overlays
Replay
No-lookahead
```

## Wave 1 — geometry primitives

```text
fitted line + intercept
trendline_value_at()
convergence caller
parallelism
```

## Wave 2 — P-1

```text
ascending triangle
descending triangle
symmetrical triangle
rising wedge
falling wedge
ascending channel
descending channel
```

## Wave 3 — P-2

```text
bull flag
bear flag
bull pennant
bear pennant
```

## Wave 4 — independent reversal/continuation families

```text
double bottom
double top
head & shoulders
inverse head & shoulders
cup & handle
```

## Wave 5 — signal context

```text
ADX
stock-vs-index RS
stock-vs-sector RS
market context
sector context
```

## Wave 6 — historical validation

```text
sealed dataset
PIT audit
pattern replay
signal replay
outcome evaluation
baseline comparison
```

---

# 40. Definition of Done

The charting/pattern/signal-indicator layer is complete when:

```text
CHART
  ✓ validated OHLCV
  ✓ crosshair
  ✓ indicator panes
  ✓ drawing overlays
  ✓ provenance

INDICATORS
  ✓ controlled catalogue
  ✓ versioned presets
  ✓ deterministic calculation
  ✓ PIT-safe replay

PATTERNS
  ✓ registry
  ✓ deterministic detectors
  ✓ shared pivot engine
  ✓ geometry evidence
  ✓ lifecycle
  ✓ breakout
  ✓ invalidation
  ✓ expiration
  ✓ no look-ahead

SIGNAL CONTEXT
  ✓ volume
  ✓ volatility
  ✓ RSI/EMA/MACD evidence
  ✓ market context
  ✓ sector context when available
  ✓ explicit unavailable states

RESEARCH
  ✓ historical replay
  ✓ configuration fingerprint
  ✓ dataset fingerprint
  ✓ PIT validation
  ✓ outcome separation
  ✓ reproducibility

ALERTS
  ✓ only registered + enabled + validated patterns
  ✓ factual event payload
  ✓ no opaque detector score
  ✓ no unsupported pattern alerts
```

---

# 41. Final architectural invariant

```text
                 OHLCV
                   |
             Data Validation
                   |
             Pivot / Swing
                   |
          Pattern Geometry
                   |
          Pattern Lifecycle
                   |
        +----------+----------+
        |                     |
   Breakout/Volume       Context Indicators
        |                RSI / EMA / MACD
        |                ADX / RS / Market
        |                Sector
        +----------+----------+
                   |
             SIGNAL EVENT
                   |
             HISTORICAL
               REPLAY
                   |
               OUTCOME
```

The detector answers:

> **Does the formal price structure exist?**

The confirmation layer answers:

> **What observed evidence accompanies the structure/breakout?**

The signal evaluator answers:

> **Does the event satisfy the separately defined signal contract?**

Historical validation answers:

> **What happened afterward, under a frozen and point-in-time-safe experiment?**

These must remain separate.

---

## Certification rule

**Do not certify a pattern because it looks correct on a chart.**

Certify it only when:

```text
formal definition
+
deterministic implementation
+
positive fixtures
+
negative fixtures
+
boundary fixtures
+
lifecycle tests
+
breakout tests
+
volume tests
+
no-lookahead tests
+
historical replay
+
reproducibility
```

all pass.

That is the certification standard for the charting, pattern, and signal-indicator layer.
