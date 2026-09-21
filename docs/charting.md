# Nivesh AI — Integrated Charting, Pattern Detection & Historical Validation PRD

**Document Version:** 1.0  
**Product:** Nivesh AI / Nivesh Copilot  
**Scope:** Interactive charting, technical/fundamental indicators, automated chart-pattern detection, confirmation, market/sector context, and historical validation.  
**Out of Scope:** Live trading terminal, broker order execution, and autonomous trading.

---

## 1. Executive Summary

Nivesh AI will provide a research-first charting and pattern-intelligence workspace. Users will be able to:

1. View interactive OHLCV charts.
2. Add technical and fundamental indicators.
3. Draw and save manual chart annotations.
4. Detect objectively defined chart patterns.
5. Evaluate pattern geometry, price, volume, volatility, market, and sector confirmation.
6. View pattern invalidation and expiry conditions.
7. Compare detected patterns with historical outcomes.
8. Run reproducible research and backtests without look-ahead bias.
9. Understand why a pattern was classified as forming, confirmed, failed, or invalidated.

The charting layer is responsible for rendering. The Nivesh pattern engine is responsible for detection and validation.

---

## 2. Product Principles

### 2.1 Explainability

Every pattern must expose:

- Pattern type.
- Formation period.
- Required pivots.
- Support/resistance or trendline values.
- Confirmation conditions.
- Failed conditions.
- Invalidation level.
- Expiry conditions.
- Data timestamp.
- Algorithm and configuration version.

### 2.2 Point-in-time integrity

A pattern at timestamp `t` may use only information available at or before timestamp `t`.

The engine must not use:

- Future candles to confirm historical signals.
- Future highs or lows.
- Future corporate announcements.
- Restated financial values unavailable at the time.
- Future market or sector information.
- Future outcomes during detection.

### 2.3 Separation of concerns

The system must separate:

1. Chart rendering.
2. Indicator calculation.
3. Pattern detection.
4. Pattern confirmation.
5. Market and sector context.
6. Historical outcome evaluation.

### 2.4 Research before promotion

A pattern must not become a production selection filter merely because it looks visually accurate. It must first pass deterministic tests, point-in-time audits, and out-of-sample evaluation.

---

## 3. Goals

### 3.1 Functional goals

- Provide professional interactive charts.
- Support multiple timeframes.
- Support manual drawing tools.
- Display technical, fundamental, market, and sector indicators.
- Detect P0/P1/P2 chart patterns.
- Provide rule-level confirmation.
- Display pattern overlays directly on charts.
- Support historical replay and backtesting.
- Track false breakouts and invalidations.
- Support pattern configuration profiles.
- Provide data-quality warnings.
- Preserve reproducible research runs.

### 3.2 Non-goals

- Live order placement.
- Broker integration.
- Autonomous trading.
- Guaranteed predictions.
- Automatic optimization against the locked test period.
- Use of post-event mover lists as model inputs.
- Unexplainable black-box pattern labels.

---

## 4. Users

### 4.1 Individual investor

Needs simple visual explanations, indicators, and risk/context information.

### 4.2 Positional trader

Needs breakout, retest, trend, volatility, and sector-context analysis.

### 4.3 Researcher

Needs reproducible detection, backtesting, ground-truth comparison, and failure analysis.

### 4.4 Advisor or professional user

Future needs include watchlists, research notes, saved configurations, and client-specific workspaces.

---

## 5. Product Modes

### 5.1 Research Mode

- Historical data.
- Pattern detection.
- Parameter testing.
- Historical outcome analysis.
- No live signal delivery.

### 5.2 Historical Replay Mode

- Move through candles sequentially.
- Show only information available at each historical timestamp.
- Reproduce pattern status transitions.
- Compare original detection with later outcomes.

### 5.3 Monitoring Mode

- Process newly completed candles.
- Update forming and confirmed patterns.
- Generate alerts.
- Flag stale or incomplete data.

---

## 6. Technical Architecture

```text
React Chart Workspace
        |
        | REST / WebSocket
        v
FastAPI API Layer
        |
        +------------------+
        |                  |
        v                  v
Chart Data Service   Pattern Detection Service
        |                  |
        +---------+--------+
                  |
                  v
Indicator and Context Layer
OHLCV | Volume | Fundamentals | Market | Sector | Events
                  |
                  v
Research and Validation Layer
PIT Checks | Backtest | Outcome Labels | Audit Logs
                  |
                  v
Storage
PostgreSQL | Timeseries Storage | Redis | Object Storage
```

### 6.1 Proposed stack

| Layer | Technology |
|---|---|
| Frontend | React 18, Tailwind CSS, Shadcn/UI |
| Chart library | TradingView Lightweight Charts, subject to licensing and capability review |
| Backend | Python FastAPI |
| Indicators | Existing Nivesh indicator utilities |
| Pattern engine | Python, NumPy, Pandas, SciPy where appropriate |
| Database | PostgreSQL |
| Cache | Redis |
| Real-time updates | WebSocket or Server-Sent Events |
| Research artifacts | Versioned files and database records |

Lightweight Charts supports custom plugins, drawing tools, annotations, custom series, and primitives. It does not provide market data or built-in indicators, so Nivesh must supply validated data and indicator calculations. See the official documentation: https://tradingview.github.io/lightweight-charts/docs/plugins/intro

---

## 7. Charting Requirements

### 7.1 Chart types

P0:

- Candlestick.
- OHLC bars.
- Line chart.
- Area chart.
- Volume bars.
- Synchronized crosshair.
- Zoom and pan.
- Date-range selection.
- Responsive layout.
- Full-screen chart.

P1:

- Heikin Ashi.
- Renko.
- Volume profile.
- Anchored VWAP.
- Session segmentation.
- Multi-chart comparison.

### 7.2 Timeframes

P0:

- Daily.
- Weekly.
- Monthly.

P1:

- 5-minute.
- 15-minute.
- 30-minute.
- 1-hour.

P2:

- 1-minute.
- 3-minute.
- Other custom intervals.

The UI must distinguish completed candles from incomplete candles. Incomplete candles must not trigger confirmation unless a specific strategy explicitly allows intrabar confirmation.

### 7.3 Manual drawing tools

P0:

- Trendline.
- Horizontal line.
- Ray.
- Rectangle.
- Support/resistance zone.
- Fibonacci retracement.
- Price measurement.
- Text annotation.
- Vertical date marker.
- Manual target and invalidation lines.

P1:

- Parallel channel.
- Pitchfork.
- Risk/reward box.
- Volume profile range.
- Custom pattern annotation.

Each drawing must store:

```json
{
  "drawing_id": "uuid",
  "user_id": "uuid",
  "symbol": "instrument_id",
  "timeframe": "1D",
  "drawing_type": "TRENDLINE",
  "anchor_points": [],
  "style": {},
  "created_at": "timestamp",
  "updated_at": "timestamp"
}
```

Manual drawings must be visually distinguishable from system-generated pattern overlays.

---

## 8. Indicator Framework

### 8.1 Trend indicators

- SMA 20, 50, 100, 200.
- EMA 9, 20, 50.
- VWAP.
- ADX and directional indicators.
- Supertrend, subject to validation.
- Parabolic SAR, optional.

### 8.2 Momentum indicators

- RSI 14.
- RSI moving average.
- MACD 12/26/9.
- Stochastic oscillator.
- Rate of change.
- Momentum.

### 8.3 Volatility indicators

- ATR 14.
- Bollinger Bands.
- Bollinger Band width.
- Historical volatility.
- Volatility percentile.
- Gap percentage.
- Range-to-ATR ratio.

### 8.4 Volume indicators

- Volume moving average.
- Relative volume.
- Volume oscillator.
- OBV.
- Accumulation/distribution.
- Buy/sell volume only where source data supports it.

### 8.5 Market and sector sensitivity

- Stock return versus benchmark.
- Stock return versus sector index.
- Beta.
- Correlation.
- Relative strength ratio.
- Sector rank.
- Market breadth.
- Sector breadth.
- Market and sector volatility.
- Market and sector trend state.

### 8.6 Fundamental indicators

Where point-in-time availability is certified:

- Revenue growth.
- Profit growth.
- EPS growth.
- ROE.
- ROCE.
- Debt-to-equity.
- Operating margin.
- Free cash flow.
- Valuation ratios.
- Promoter holding and pledge.
- FII/DII ownership changes.
- Earnings consistency.
- Corporate actions.
- Auditor or regulatory events.

Fundamental values must carry their publication timestamp, source, as-of period, and point-in-time validation status.

### 8.7 Indicator contract

Each indicator must define:

```text
indicator_id
indicator_name
parameters
input_fields
output_fields
warmup_period
calculation_version
point_in_time_validated
missing_data_policy
```

---

## 9. Data Quality and Point-in-Time Controls

### 9.1 OHLCV validation

Reject or flag records where:

```text
high < max(open, close)
low > min(open, close)
high < low
open <= 0
close <= 0
volume < 0
```

Also detect:

- Missing candles.
- Duplicate timestamps.
- Out-of-order bars.
- Abnormal gaps.
- Corporate-action discontinuities.
- Incomplete sessions.
- Incorrect symbol mapping.
- Stale data.
- Suspicious volume values.

### 9.2 Data status

Every chart and pattern result must have one of:

```text
VALID
PARTIAL
STALE
INVALID
PIT_UNVERIFIED
BLOCKED
```

A pattern cannot be promoted to confirmed when required data is invalid, incomplete, or point-in-time unverified.

---

## 10. Pattern Engine

### 10.1 Processing pipeline

```text
OHLCV Ingestion
      |
Candle Validation
      |
Swing Point Detection
      |
Trendline and Boundary Calculation
      |
Pattern Candidate Generation
      |
Pattern Geometry Validation
      |
Breakout / Breakdown Detection
      |
Volume and Volatility Checks
      |
Market and Sector Context
      |
Pattern Status and Explanation
```

### 10.2 Common initial parameters

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

These values are initial research defaults and must not be treated as optimized parameters.

---

## 11. Pattern Lifecycle

```text
CANDIDATE
   |
FORMING
   |
GEOMETRY_VALID
   |
BREAKOUT_ATTEMPT
   |
PRICE_CONFIRMED
   |
VOLUME_CONFIRMED
   |
CONTEXT_VALIDATED
   |
RESEARCH_ELIGIBLE
```

Alternative states:

```text
FAILED
INVALIDATED
EXPIRED
DATA_BLOCKED
UNRESOLVED
```

The engine must store separate booleans or statuses for:

- Geometry.
- Price.
- Volume.
- Volatility.
- Market context.
- Sector context.
- Data quality.

A single opaque confidence score is insufficient.

---

## 12. Universal Confirmation Rules

### 12.1 Geometry confirmation

Check:

- Required pivots exist.
- Pivots are sufficiently separated.
- Pattern length is valid.
- Trendlines meet slope requirements.
- Boundaries are stable.
- Pattern is not expired.
- No structural invalidation occurred.

### 12.2 Breakout buffer

```text
Upper Breakout Threshold
= Resistance + Breakout Buffer

Lower Breakdown Threshold
= Support - Breakout Buffer

Breakout Buffer
= ATR × Configured ATR Multiplier
```

### 12.3 Price confirmation

Bullish:

```text
Close[t] > Breakout Level
```

Bearish:

```text
Close[t] < Breakdown Level
```

A wick-only breach is `BREAKOUT_ATTEMPT`, not confirmation.

### 12.4 Volume confirmation

```text
Relative Volume
= Current Completed Candle Volume
  / Average Volume of Prior N Completed Candles
```

Suggested classifications:

| Relative volume | Classification |
|---:|---|
| < 0.80 | Weak |
| 0.80–1.20 | Normal |
| 1.20–1.50 | Supporting |
| >= 1.50 | Strong |

### 12.5 Follow-through

A stronger confirmation state may require:

- The next candle does not close back inside the pattern.
- Price holds above resistance or below support.
- No immediate reversal.
- No gap invalidation.
- Volume and volatility remain within configured bounds.

Retest confirmation must be optional because requiring a retest can miss breakouts that continue without one.

---

## 13. Pattern-Specific Rules

### 13.1 Higher High / Higher Low

Bullish formation:

- At least two confirmed higher highs.
- At least two confirmed higher lows.
- Each meaningful low is above the prior meaningful low.
- Latest meaningful high breaks the previous meaningful high for continuation confirmation.

Bearish formation:

- At least two lower lows.
- At least two lower highs.
- Latest meaningful low breaks the previous meaningful low.

Invalidation:

- Close beyond the relevant invalidation swing.
- New structure contradicts the current trend.
- Insufficient confirmed pivots.

### 13.2 Support and Resistance

Detection:

1. Identify confirmed swing highs and lows.
2. Cluster nearby prices using ATR-normalized distance.
3. Require a minimum number of touches.
4. Calculate strength using touches, recency, rejection, volume, and time near the level.

Confirmation:

```text
Bullish:
Close > Resistance + Buffer

Bearish:
Close < Support - Buffer
```

The UI must distinguish wick breach, intrabar breach, closing breach, follow-through, and failure.

### 13.3 Rectangle Consolidation

Formation:

- Minimum 15 candles.
- At least two resistance touches.
- At least two support touches.
- Flat or near-flat boundaries.
- At least 70% of closes inside the zone.
- Minimum range relative to ATR.
- No unresolved data gaps.

Confirmation:

```text
Bullish:
Close > Resistance + 0.25 × ATR

Bearish:
Close < Support - 0.25 × ATR
```

Invalidation:

- Opposite boundary closes.
- Pattern exceeds maximum age.
- Boundary is broken and reclaimed without follow-through.

### 13.4 Ascending Triangle

Formation:

- At least two resistance pivots near a common level.
- At least two rising support pivots.
- Resistance is relatively flat.
- Support pivots generally rise.
- Trendlines converge.
- Minimum formation length is met.

Confirmation:

```text
Close > Horizontal Resistance + Buffer
```

Additional evidence:

- Relative volume >= 1.20.
- Breakout candle closes in the upper 60% of its range.
- Next candle does not close back below resistance.

Invalidation:

- Close below the most recent rising support.
- Close back inside the triangle within the failure window.
- Pattern reaches the apex without a valid breakout.

### 13.5 Descending Triangle

Formation:

- At least two support pivots near a common level.
- At least two declining resistance pivots.
- Support is relatively flat.
- Trendlines converge.

Confirmation:

```text
Close < Horizontal Support - Buffer
```

Invalidation:

- Close above descending resistance.
- Breakdown is not sustained.
- Pattern exceeds maximum age.

### 13.6 Double Bottom

Formation:

- First trough.
- Intervening recovery peak.
- Second trough.
- Troughs are within configurable ATR or percentage tolerance.
- Meaningful recovery exists between troughs.
- Neckline is defined by the recovery peak.

Initial research assumptions:

```text
abs(T2 - T1) <= 1.0 × ATR
Minimum trough separation = 5 bars
```

Confirmation:

```text
Close > Neckline + Buffer
```

Invalidation:

- Close below the second trough.
- Neckline breakout fails.
- Pattern expires.

### 13.7 Double Top

Formation:

- First peak.
- Intervening trough.
- Second peak.
- Peaks are within configurable tolerance.
- Meaningful decline exists between peaks.
- Neckline is the intervening trough.

Confirmation:

```text
Close < Neckline - Buffer
```

Invalidation:

- Close above the second peak.
- Failed neckline breakdown.
- Pattern expires.

### 13.8 Bull Flag and Bear Flag

Formation:

- Strong directional impulse.
- Countertrend or sideways consolidation.
- Controlled retracement.
- Reduced or stable consolidation volume.
- Consolidation duration is limited.

Bull flag confirmation:

```text
Close > Upper Flag Boundary + Buffer
```

Bear flag confirmation:

```text
Close < Lower Flag Boundary - Buffer
```

Invalidation:

- Excessive retracement.
- Opposite-direction breakout.
- Excessive duration.
- Insufficient preceding impulse.

### 13.9 Breakout and Retest

Initial breakout:

- Valid boundary exists.
- Closing price crosses boundary plus buffer.
- Breakout timestamp and price are stored.

Bullish retest:

- Price returns toward former resistance.
- Retest does not close below invalidation.
- A subsequent candle closes above the retest confirmation level.

Bearish retest:

- Price returns toward former support.
- Retest does not close above invalidation.
- A subsequent candle closes below the retest confirmation level.

States:

```text
BREAKOUT_CONFIRMED
RETEST_PENDING
RETEST_SUCCESSFUL
RETEST_FAILED
BREAKOUT_FAILED
```

### 13.10 Wedges

Rising wedge:

- Rising support and resistance.
- Support slope is greater than resistance slope.
- Trendlines converge.
- Breakdown confirms the bearish interpretation.

Falling wedge:

- Falling support and resistance.
- Resistance slope is more negative than support slope.
- Trendlines converge.
- Breakout confirms the bullish interpretation.

### 13.11 Head and Shoulders

Formation:

- Left shoulder.
- Head above left shoulder.
- Right shoulder near or below left shoulder.
- Two troughs define the neckline.
- Shoulder and head geometry meet configurable tolerances.

Confirmation:

```text
Close < Neckline - Buffer
```

Inverse head and shoulders uses the opposite structure and confirms above the neckline.

### 13.12 Cup and Handle

Later-phase pattern.

Cup:

- Prior upward trend.
- Rounded decline.
- Rounded recovery.
- Similar left and right rim levels.
- Controlled cup depth and duration.

Handle:

- Shorter consolidation.
- Handle remains within configured depth.
- Volume generally contracts.
- Breakout occurs above rim resistance.

Confirmation:

```text
Close > Rim Resistance + Buffer
```

---

## 14. Candlestick Pattern Module

Candlestick patterns must be maintained separately from structural chart patterns.

Initial patterns:

- Bullish engulfing.
- Bearish engulfing.
- Hammer.
- Shooting star.
- Morning star.
- Evening star.
- Inside bar.
- Outside bar.
- Pin bar.

Use relative candle sizing:

```text
Body = abs(Close - Open)
Range = High - Low

Large Body:
Body > Average Body

Wide Range:
Range > 1.4 × Average Range
```

Each candlestick rule must specify:

- Required preceding candles.
- Body and wick ratios.
- Gap conditions.
- Trend context.
- Confirmation candle rules.
- Invalidation conditions.
- Version.

---

## 15. Market and Sector Context

### 15.1 Market context

Calculate:

- Benchmark return over 1, 5, 20, and 60 sessions.
- Benchmark position relative to SMA20, SMA50, and SMA200.
- Benchmark RSI and ADX.
- Market volatility.
- Market breadth.
- Market regime.
- Gap and opening conditions.

### 15.2 Sector context

Calculate:

- Sector return over 1, 5, 20, and 60 sessions.
- Sector relative strength.
- Sector trend.
- Sector volatility.
- Stock return minus sector return.
- Sector breadth where available.

### 15.3 Context status

```text
POSITIVE
NEUTRAL
NEGATIVE
MIXED
UNAVAILABLE
```

Market and sector context must not override a failed pattern geometry or invalid data.

---

## 16. Pattern Quality Model

Store independent component values:

```text
geometry_quality
price_confirmation_quality
volume_quality
volatility_quality
market_alignment
sector_alignment
relative_strength
liquidity_quality
data_quality
```

A composite score may be introduced only after component behavior is understood.

The score must include:

- Calculation version.
- Component values.
- Weights.
- Thresholds.
- Missing values.
- Eligibility decision.
- Reason codes.

A score must not be described as a probability without calibration and validation.

---

## 17. False Breakout and Failure Rules

### 17.1 Bullish failure

A bullish breakout fails when, within the configured failure window:

```text
Close < Prior Resistance - Failure Buffer
```

or:

- Price returns inside the pattern.
- Invalidation level is breached.
- Gap-through invalidation occurs.
- Required data becomes invalid.

### 17.2 Bearish failure

```text
Close > Prior Support + Failure Buffer
```

### 17.3 Failure classifications

```text
FALSE_BREAKOUT
FAILED_RETEST
LOW_VOLUME_FAILURE
GAP_FAILURE
MARKET_REVERSAL
SECTOR_REVERSAL
DATA_FAILURE
UNRESOLVED
```

Failure classification must be based on observed conditions, not eventual profit or loss.

---

## 18. Historical Validation Framework

### 18.1 Objective

Measure whether patterns have useful historical behavior after:

- Costs.
- Slippage.
- Entry timing.
- Holding period.
- Stop and target policy.
- Market conditions.
- Sector conditions.
- Liquidity restrictions.

### 18.2 Outcome labels

```text
hit_high_5
hit_high_10
hit_close_5
hit_close_10
hit_target_before_stop
stop_before_target
maximum_favorable_excursion
maximum_adverse_excursion
net_positive_after_costs
```

Evaluate at:

- 1 session.
- 3 sessions.
- 5 sessions.
- Configurable longer horizons.

### 18.3 Required comparison groups

- Pattern strategy.
- Random selection from the same eligible universe.
- Buy-at-next-open baseline.
- Market benchmark.
- Sector benchmark.
- No-cost version.
- Cost-adjusted version.
- Alternative entry methods.
- Alternative stop/target methods.

### 18.4 Required metrics

- Pattern frequency.
- Detection precision.
- Confirmation-to-breakout conversion.
- False-breakout rate.
- Target-before-stop rate.
- Average net return.
- Median net return.
- Drawdown.
- Profit factor.
- Exposure-adjusted return.
- Outcome by market regime.
- Outcome by sector.
- Outcome by liquidity.
- Outcome by volatility bucket.
- Outcome by relative-volume bucket.

### 18.5 Ground-truth comparison

Actual stocks that subsequently moved by 5% or 10% may be used for post-event evaluation only.

The comparison must include:

- Model-eligible stocks.
- Actual movers.
- Selected stocks.
- Missed movers.
- False selections.
- Exclusion reasons.
- Data-quality reasons.
- Rank and score.
- Pattern status at decision time.

---

## 19. Historical Replay

Historical replay must:

1. Load a sealed or versioned dataset.
2. Move through candles in chronological order.
3. Recalculate indicators only using available history.
4. Detect patterns at each timestamp.
5. Record status changes.
6. Prevent future candle access.
7. Store the exact configuration and data version.
8. Compare the signal with subsequent realized outcomes only after detection is finalized.

Replay should support:

- Pause.
- Step forward one candle.
- Step forward one session.
- Show detected pivots.
- Show confirmation timestamp.
- Show later outcome separately.
- Export the event timeline.

---

## 20. UI Requirements

### 20.1 Main workspace

- Symbol search.
- Watchlist.
- Timeframe selector.
- Chart type selector.
- Indicator selector.
- Drawing toolbar.
- Pattern visibility controls.
- Market and sector context panel.
- Pattern details panel.
- Historical outcome panel.
- Data-quality status.

### 20.2 Pattern overlay

Display:

- Formation boundary.
- Pivot points.
- Support and resistance.
- Trendlines.
- Breakout threshold.
- Invalidation level.
- Retest zone.
- Projected target, if available.
- Confirmation candle marker.
- Failure marker.
- Pattern age.

Use different visual styling for:

- Manual drawings.
- Forming patterns.
- Confirmed patterns.
- Failed patterns.
- Invalidated patterns.
- Historical annotations.

### 20.3 Pattern details card

Required fields:

```text
pattern_type
direction
status
formation_start
formation_end
support
resistance
breakout_level
invalidation_level
ATR
relative_volume
market_alignment
sector_alignment
point_in_time_validated
pattern_version
```

The panel must show passed and failed rules individually.

### 20.4 Indicator panel

Users must be able to:

- Add indicators.
- Remove indicators.
- Change parameters.
- Reorder panes.
- Save indicator templates.
- Reset to defaults.
- Display calculation metadata.
- Show missing-data warnings.

### 20.5 Research panel

Provide:

- Pattern sample size.
- Historical hit rates.
- Average and median returns.
- False-breakout rate.
- MFE and MAE.
- Outcome by timeframe.
- Outcome by market regime.
- Outcome by sector.
- Outcome by liquidity.
- Configuration version.
- Data version.
- Backtest status.

---

## 21. Configuration Management

Users may create profiles containing:

- Timeframe.
- Swing parameters.
- ATR period.
- Breakout buffer.
- Volume thresholds.
- Confirmation window.
- Retest window.
- Pattern types enabled.
- Market and sector filters.
- Data-quality rules.
- Outcome horizon.
- Entry reference for research.

Every run must save:

```text
configuration_id
configuration_hash
pattern_engine_version
indicator_version
dataset_version
created_at
created_by
```

Configurations used in locked tests must be immutable.

---

## 22. API Requirements

### 22.1 Chart data

```http
GET /research/chart/{symbol}/ohlcv
GET /research/chart/{symbol}/indicators
GET /research/chart/{symbol}/market-context
GET /research/chart/{symbol}/sector-context
```

### 22.2 Drawings

```http
POST   /research/drawings
GET    /research/drawings
PATCH  /research/drawings/{drawing_id}
DELETE /research/drawings/{drawing_id}
```

### 22.3 Pattern detection

```http
POST /research/patterns/detect
GET  /research/patterns/{pattern_id}
GET  /research/patterns?symbol={symbol}&timeframe={timeframe}
POST /research/patterns/{pattern_id}/evaluate-confirmation
GET  /research/patterns/{pattern_id}/history
```

### 22.4 Historical validation

```http
POST /research/patterns/backtest
GET  /research/patterns/backtest/{run_id}
GET  /research/patterns/backtest/{run_id}/outcomes
GET  /research/patterns/backtest/{run_id}/false-breakouts
GET  /research/patterns/backtest/{run_id}/regime-analysis
GET  /research/patterns/backtest/{run_id}/sector-analysis
```

### 22.5 Replay

```http
POST /research/replay
GET  /research/replay/{replay_id}
GET  /research/replay/{replay_id}/events
```

---

## 23. Data Model

### 23.1 Pattern record

```text
pattern_id
instrument_id
symbol
exchange
timeframe
pattern_type
direction
status
formation_start
formation_end
pivot_points
boundary_parameters
support_level
resistance_level
breakout_level
invalidation_level
atr
relative_volume
market_context
sector_context
data_quality_status
point_in_time_validated
pattern_engine_version
configuration_id
created_at
updated_at
```

### 23.2 Pattern event record

```text
event_id
pattern_id
event_type
event_timestamp
observed_values
rule_id
rule_result
data_version
created_at
```

### 23.3 Outcome record

```text
pattern_id
entry_reference
horizon
maximum_favorable_excursion
maximum_adverse_excursion
highest_price
lowest_price
close_return
target_before_stop
stop_before_target
net_return_after_costs
outcome_version
```

---

## 24. Testing Strategy

### 24.1 Unit tests

- Swing point detection.
- Trendline fitting.
- Boundary calculation.
- ATR buffer.
- Volume baseline.
- Pattern geometry.
- Breakout confirmation.
- Retest detection.
- Invalidation.
- Expiry.
- Corporate-action handling.
- Missing-bar handling.
- Symbol mapping.

### 24.2 Deliberate failure fixtures

Test:

- Wick-only breakout.
- Low-volume breakout.
- Close back inside pattern.
- False retest.
- Gap-through invalidation.
- Duplicate candle.
- Missing candle.
- Look-ahead swing detection.
- Future volume contamination.
- Incorrect trendline slope.
- Incorrect symbol mapping.
- Incomplete current candle.
- Corporate-action discontinuity.

### 24.3 Research acceptance criteria

A pattern implementation is accepted only when:

- Detection is reproducible.
- No future information is used.
- Geometry tests pass.
- Data-quality tests pass.
- Status transitions are deterministic.
- Outcomes are measured after costs.
- Results are compared with baseline strategies.
- Results are segmented by regime, sector, liquidity, and volatility.
- Configuration is frozen before locked testing.
- Raw OHLCV audits are available.
- Deliberate bug tests pass.

---

## 25. Security and Auditability

- Enforce user-level access to saved drawings and research runs.
- Store configuration and dataset hashes.
- Record all pattern status transitions.
- Do not expose sensitive account information to AI models.
- Keep broker credentials and personal financial data outside pattern prompts.
- Maintain immutable research artifacts for locked tests.
- Log data-source and timestamp provenance.
- Mark unverified data explicitly.

---

## 26. Performance Requirements

### P0

- Initial chart render within an acceptable interactive target under normal data volume.
- Smooth zoom and pan for typical historical ranges.
- Incremental updates for newly completed candles.
- Pattern detection should run asynchronously for large universes.
- Avoid recalculating unchanged historical indicators unnecessarily.

### P1

- Cached indicator results.
- Cached pattern candidates.
- Batch pattern detection.
- Background research jobs.
- Progress tracking.
- Cancelable long-running backtests.

The exact latency targets should be benchmarked using the actual deployment environment and expected universe size.

---

## 27. Observability

Track:

- Data ingestion success/failure.
- Stale data rate.
- Pattern detection duration.
- Indicator calculation duration.
- Pattern counts by status.
- Data-quality blocks.
- False-breakout counts.
- API error rate.
- Cache hit ratio.
- Replay reproducibility.
- Configuration version usage.

Every error must include a structured reason code.

---

## 28. Delivery Roadmap

### Phase 1 — Charting foundation

- OHLCV chart.
- Volume.
- Timeframes.
- Crosshair.
- Zoom and pan.
- Manual trendline and horizontal line.
- Basic indicator framework.
- Data-quality display.

### Phase 2 — P0 pattern detection

- Swing structure.
- Support/resistance.
- Rectangle consolidation.
- Breakout and breakdown.
- Breakout/retest.
- ATR and relative-volume confirmation.
- Pattern overlays.

### Phase 3 — Context integration

- Market trend.
- Sector trend.
- Relative strength.
- Market/sector volatility.
- Context panel.
- Pattern event history.

### Phase 4 — Historical validation

- Replay engine.
- Pattern outcome labels.
- Ground-truth comparison.
- False-breakout analysis.
- Baseline comparison.
- Configuration and dataset hashes.

### Phase 5 — P1/P2 patterns

- Ascending and descending triangles.
- Double tops and bottoms.
- Flags.
- Wedges.
- Head and shoulders.
- Cup and handle.
- Multi-timeframe analysis.

---

## 29. Initial Release Acceptance Criteria

The initial release is accepted when:

1. Users can view validated OHLCV charts.
2. Users can add and save core drawings.
3. Users can add and configure supported indicators.
4. P0 patterns are detected using deterministic rules.
5. Pattern overlays match backend pattern records.
6. The UI displays all confirmation conditions.
7. Pattern status transitions are reproducible.
8. No future data is used in detection.
9. Data-quality and PIT status are visible.
10. Historical replay prevents look-ahead bias.
11. Backtests include costs and baseline comparisons.
12. Pattern results are segmented by market and sector context.
13. All research runs preserve configuration and dataset versions.
14. No pattern is presented as a guaranteed outcome.

---

## 30. Recommended Initial Configuration

Profile name:

`PATTERN_CONFIRMATION_V1_RESEARCH`

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

This configuration is a research baseline. It must be evaluated and frozen before any locked test. It must not be treated as an optimized trading strategy.

### 30.1 Geometry predicate definitions (approved by owner 2026-09-21)

§12 and §13 use several terms without defining them. The following definitional forms were approved and are part of
`PATTERN_CONFIRMATION_V1_RESEARCH`. All are ATR-normalised so they are scale-free across symbols. Full rationale:
`.claude/workspace/charting-pattern-engine/ni2-geometry-predicates.md`.

| Term (PRD location) | Definition |
|---|---|
| Flat / rising / falling boundary (§12.1, §13.3) | `boundary_drift_atr = abs(slope) * L / ATR`; flat if <= 0.50; rising/falling if >= 0.75 in that direction |
| Converging trendlines (§13.4, §13.5, §13.10) | `gap_at_last_bar / gap_at_first_bar <= 0.70` |
| Touch and level (§13.2) | confirmed pivots within 0.35 ATR of the level; >= 3 touches for a standalone level, >= 2 per pattern boundary; touches >= 3 bars apart |
| Level strength (§13.2) | `0.30*touch + 0.20*recency + 0.20*rejection + 0.15*volume + 0.15*time`, each component in [0,1] and stored separately; descriptive, not a probability |
| Minimum rectangle range (§13.3) | `1.50 <= (resistance - support) / ATR <= 8.00` |
| Failure buffer (§17.1, §17.2) | `0.25 * ATR` (equal to the breakout buffer, so states cannot overlap), within 5 bars of confirmation |
| Follow-through bounds (§12.5) | `ATR_confirm / ATR_baseline <= 2.00` and `1.00 <= relative_volume <= 4.00` |
| Stable boundary (§12.1) | refit on first 70% of window shifts the level by <= 0.30 ATR, and touch residual std <= 0.25 ATR |
| Relative-volume bands (§12.4) | half-open: Weak < 0.80 <= Normal < 1.20 <= Supporting < 1.50 <= Strong |

```yaml
flat_boundary_max_drift_atr: 0.50
sloped_boundary_min_drift_atr: 0.75
convergence_max_ratio: 0.70
level_cluster_width_atr: 0.35
level_min_touches: 3
pattern_boundary_min_touches: 2
touch_min_separation_bars: 3
strength_touch_saturation: 5
strength_recency_halflife_bars: 60
strength_time_fraction: 0.25
strength_weights: [0.30, 0.20, 0.20, 0.15, 0.15]
rectangle_min_range_atr: 1.50
rectangle_max_range_atr: 8.00
failure_buffer_atr: 0.25
failure_window_bars: 5
followthrough_max_atr_expansion: 2.00
followthrough_min_rel_volume: 1.00
followthrough_max_rel_volume: 4.00
stability_refit_fraction: 0.70
boundary_stability_max_shift_atr: 0.30
boundary_max_residual_atr: 0.25
relative_volume_band_convention: half_open_lower_inclusive
```

These are research defaults, frozen before any locked test and never tuned against the test period.

---

## 31. Final Product Positioning

Nivesh AI's differentiator is not simply drawing chart patterns. It is the combination of:

1. High-quality chart rendering.
2. Explainable pattern geometry.
3. Technical and fundamental context.
4. Market and sector sensitivity.
5. Point-in-time-safe detection.
6. Historical replay.
7. Outcome-based validation.
8. Transparent failure and data-quality reporting.

The first implementation should prioritize a small number of deterministic patterns and a complete validation workflow over a large collection of unvalidated pattern labels.


---

## 32. Multi-Provider Integration: Kite API + Trendlyne MCP + NIDP

### 32.1 Objective

Nivesh AI shall support **both Kite Connect API and Trendlyne MCP Server** as complementary data providers. The system must not assume that either provider independently supplies every dataset required for charting, technical analysis, fundamental analysis, pattern detection, historical replay, or point-in-time validation.

The integration must separate:

1. **Market-price and candle acquisition** — primarily Kite Connect API.
2. **Fundamental, ownership, technical-summary, corporate-event and document enrichment** — primarily Trendlyne MCP.
3. **Exchange-grounded validation** — NSE/BSE filings, exchange records, and controlled reference datasets where required.
4. **Derived analytics** — calculated by Nivesh AI using versioned and testable utilities.
5. **Research and validation** — executed only against certified, versioned datasets.

### 32.2 Provider responsibility matrix

| Data or capability | Kite Connect API | Trendlyne MCP | Nivesh AI responsibility |
|---|---|---|---|
| Instrument master | Primary | Entity search/resolution | Version mappings and detect symbol changes |
| Historical OHLCV | Primary | EOD price data / parameter access | Store candles, validate integrity and coverage |
| Intraday candles | Primary, subject to entitlement and availability | Not assumed | Collect, timestamp and certify availability |
| Live quotes | Primary | Depends on plan/tool availability | Record retrieval time and stale-data status |
| Volume and OI | OHLCV/OI where supported | Price/volume parameters | Validate source fields and applicability |
| Technical indicators | Raw inputs | Technical indicators and summaries | Recalculate critical indicators independently |
| Financial statements | Not provided as a core function | Primary enrichment source | Store publication time, period, source and PIT status |
| Financial ratios | Not provided as a core function | Primary enrichment source | Validate definitions, units and calculation versions |
| Analyst estimates | Not provided as a core function | Supported where available | Mark as non-ground-truth and timestamp availability |
| Shareholding | Not provided as a core function | Primary enrichment source | Validate against exchange disclosures where needed |
| Insider/SAST/deal data | Not provided as a core function | Primary enrichment source | Store event time, publication time and source provenance |
| Corporate events | Not provided as a dedicated source | Supported corporate-event view | Cross-check material events with NSE/BSE records |
| News and announcements | Not provided as a core function | Supported news/document search | Store source, publication time and retrieval time |
| Annual reports and presentations | Not provided as a core function | Document search | Preserve document identity and extraction provenance |
| Sector and industry classification | Limited/indirect | Entity and market metadata where available | Maintain versioned classification reference |
| Market and sector context | Raw instruments only | Some technical/market data | Calculate benchmark, sector and breadth features |
| Historical point-in-time fundamentals | Not assumed | Not certified by default | Block training use until PIT semantics are certified |
| Historical replay | Raw candle source | Enrichment source only | Enforce chronological availability and no look-ahead |
| Pattern detection | Raw candle input | Supporting indicators/context | Run deterministic Nivesh pattern engine |
| Backtest outcomes | Raw candle input | Context/enrichment input | Calculate outcomes after costs and slippage |

Trendlyne's published MCP documentation describes entity search, overview/technical/news/corporate-event views, multi-stock parameter retrieval, ownership/deal disclosures and document search. It also identifies exclusions such as US market data, mutual fund data, F&O data and Forecaster data. These capabilities and exclusions must be checked against the subscribed plan and the live MCP tool schema before implementation.

### 32.3 Integration architecture

```text
                         React Chart Workspace
                                  |
                             FastAPI API
                                  |
                    Provider Orchestration Layer
                    /             |              \
                   /              |               \
          Kite Adapter     Trendlyne Adapter    Exchange Adapter
          (REST/API)          (MCP client)       (NSE/BSE)
                   \              |               /
                    \             |              /
                     Provider Normalization Layer
                                  |
                       Data Quality + Lineage
                                  |
                    Canonical Research Data Model
                    /       |        |         \
               OHLCV   Fundamentals Ownership  Events
                    \       |        |         /
                     Feature and Context Layer
                                  |
                  Pattern Detection + Validation
                                  |
                   Replay, Outcomes and Reporting
```

### 32.4 Adapter contracts

Each provider adapter must expose a normalized contract and must not leak provider-specific response formats into downstream analytics.

```text
ProviderAdapter
  provider_id
  provider_version
  request_id
  requested_at
  response_received_at
  source_timestamp
  availability_timestamp
  instrument_identifier
  raw_payload_reference
  normalized_records
  data_quality_status
  error_code
  retryable
```

Required adapters:

- `KiteMarketDataAdapter`
- `TrendlyneResearchAdapter`
- `ExchangeValidationAdapter`
- `ProviderReconciliationService`

The adapters must be independently testable and must reuse existing Nivesh ingestion, caching, mapping and validation utilities wherever available.

### 32.5 Kite Connect API requirements

The Kite adapter shall support:

- Daily historical candles.
- Supported intraday candle intervals.
- Instrument-master ingestion and versioning.
- LTP, OHLC and quote snapshots where required.
- WebSocket streaming only when explicitly needed by the monitoring mode.
- Optional open-interest retrieval where supported.
- Chunked historical retrieval for large date ranges.
- Rate-limit handling, retries and backoff.
- Session authentication through a backend-only flow.
- Secure handling of API keys, API secrets and daily access tokens.

Kite API access tokens must never be exposed in browser code, logs, prompts or client-side storage. The API adapter must run server-side, and all requests must record the provider response status and retrieval timestamp.

The adapter must explicitly record whether a price series is:

- Raw or adjusted.
- EOD or intraday.
- Complete or partial.
- Exchange-session complete or missing sessions.
- Corporate-action reconciled or unreconciled.

### 32.6 Trendlyne MCP requirements

The Trendlyne adapter shall support, subject to the subscribed plan and available MCP tool schemas:

- Entity search and identifier resolution.
- Overview and technical summaries.
- Structured parameter retrieval for multiple stocks.
- Financial statements and ratios.
- Price and volume parameters.
- Shareholding and ownership data.
- Insider, SAST, bulk and block deal disclosures.
- Corporate events.
- News, annual reports, quarterly results, earnings calls and investor presentations.

The adapter must not assume that a Trendlyne response is historical point-in-time safe merely because it contains a historical period or an old value. For every field intended for research or model training, store:

```text
field_name
value
as_of_period
publication_timestamp
availability_timestamp
retrieval_timestamp
source_identifier
provider_response_id
calculation_definition
point_in_time_validated
validation_status
```

Trendlyne data must be marked `PIT_UNVERIFIED` by default for historical model training until the exact historical availability semantics are independently demonstrated through the Nivesh PIT audit process.

### 32.7 Source-selection policy

The system shall use the following default source-selection policy:

1. Use Kite for the canonical market-candle series when the required interval and history are available.
2. Use Trendlyne for enrichment, financials, ownership, technical summaries, events and documents.
3. Use NSE/BSE or other approved exchange evidence for public-availability verification, material corporate events and disputed values.
4. Never silently substitute one provider for another when definitions, timestamps or adjustment policies differ.
5. Preserve both the original provider record and the normalized canonical record.
6. If providers disagree, retain the disagreement as a reconciliation finding rather than overwriting one value.

### 32.8 Reconciliation rules

Provider reconciliation must compare, where applicable:

- Instrument identifier and exchange.
- Trading symbol and ISIN mapping.
- Candle timestamp and trading session.
- Open, high, low and close.
- Volume and open interest.
- Corporate-action adjustment status.
- Financial period and publication date.
- Shareholding period and disclosure date.
- Event date, publication date and retrieval date.

Possible reconciliation outcomes:

```text
MATCHED
MATCHED_WITH_TOLERANCE
MISSING_FROM_KITE
MISSING_FROM_TRENDLYNE
TIMESTAMP_MISMATCH
DEFINITION_MISMATCH
ADJUSTMENT_MISMATCH
IDENTIFIER_MISMATCH
VALUE_MISMATCH
PIT_UNVERIFIED
BLOCKED
```

Tolerance-based matching must be configured per field and documented. It must not be used to conceal material discrepancies.

### 32.9 Point-in-time and research-use controls

A feature is eligible for historical research only when:

- The value was available at or before the decision timestamp.
- The source publication timestamp is known or conservatively bounded.
- The as-of period is clearly distinguished from publication time.
- The provider's revision behavior is understood or the feature is excluded.
- The instrument mapping is valid for the historical date.
- The data-quality status is not `INVALID`, `BLOCKED` or `PIT_UNVERIFIED`.
- The exact dataset and configuration versions are recorded.

The following statuses must be supported:

```text
PIT_VALIDATED
PIT_PARTIAL
PIT_UNVERIFIED
PIT_FAILED
DATA_BLOCKED
```

A current Trendlyne value must not be backfilled into an earlier historical decision point without evidence that the value was publicly available at that time.

### 32.10 Canonical data model additions

Add or confirm the following fields in canonical tables:

```text
provider_id
provider_record_id
provider_version
source_url_or_tool
source_timestamp
publication_timestamp
availability_timestamp
retrieval_timestamp
raw_payload_reference
normalization_version
adjustment_status
reconciliation_status
point_in_time_validated
pit_validation_method
data_quality_status
```

Recommended provider metadata tables:

- `data_providers`
- `provider_credentials_metadata`
- `provider_requests`
- `provider_responses`
- `provider_field_mappings`
- `provider_reconciliation_runs`
- `provider_reconciliation_findings`
- `pit_validation_results`

Credential tables must store secret references or encrypted secret material only; never store plaintext credentials in research records.

### 32.11 Failure handling

The system must distinguish between:

- Provider unavailable.
- Authentication expired.
- Rate limit reached.
- Tool schema changed.
- Empty response.
- Partial response.
- Invalid provider payload.
- Identifier not resolved.
- Data outside provider coverage.
- PIT validation failure.
- Cross-provider disagreement.

No empty response may be silently interpreted as zero, unchanged, unavailable historically, or a valid negative result.

For partial provider failure, the system must:

1. Mark affected records as partial or blocked.
2. Preserve the failed request and reason code.
3. Avoid silently mixing incompatible sources.
4. Retry only when the failure is classified as retryable.
5. Surface the limitation in the UI and research report.

### 32.12 UI requirements for source transparency

The chart and research UI must display:

- Data provider used for each dataset.
- Last successful retrieval timestamp.
- Source timestamp and availability timestamp where applicable.
- Raw versus adjusted price status.
- Data-quality status.
- PIT validation status.
- Provider disagreement warnings.
- Missing data and coverage limitations.
- Whether a value is directly sourced or Nivesh-derived.
- Calculation and normalization version.

A user must be able to open a provenance panel for a candle, indicator, fundamental value, ownership record, event or pattern confirmation rule.

### 32.13 API endpoints

```http
GET  /research/providers
GET  /research/providers/health
POST /research/providers/kite/sync-instruments
POST /research/providers/kite/fetch-candles
POST /research/providers/trendlyne/search-entity
POST /research/providers/trendlyne/fetch-parameters
POST /research/providers/trendlyne/fetch-events
POST /research/providers/trendlyne/search-documents
POST /research/providers/reconcile
GET  /research/providers/reconcile/{run_id}
GET  /research/provenance/{record_type}/{record_id}
POST /research/pit-validation/run
GET  /research/pit-validation/{run_id}
```

These endpoints are research/data-service endpoints only. They must not place live orders or create an implicit trading-execution dependency.

### 32.14 Testing requirements

Provider integration tests must include:

- Kite authentication expiry.
- Kite rate limiting.
- Historical request chunking.
- Missing trading sessions.
- Duplicate candles.
- Incorrect OHLC values.
- Corporate-action discontinuity.
- Trendlyne empty tool response.
- Trendlyne schema or field-definition change.
- Trendlyne identifier ambiguity.
- Historical value with unknown publication timestamp.
- Conflicting Kite and Trendlyne prices.
- Conflicting financial-period definitions.
- Partial provider outage.
- Retry exhaustion.
- PIT violation caused by a future publication timestamp.
- Accidental use of current Trendlyne data in historical replay.

Every deliberate failure fixture must produce a deterministic reason code and must prevent invalid data from reaching confirmed pattern status or locked research evaluation.

### 32.15 Acceptance criteria

The dual-provider integration is accepted only when:

1. Kite and Trendlyne adapters have isolated, versioned contracts.
2. Provider-specific payloads are normalized into canonical schemas.
3. Every record contains source and retrieval provenance.
4. Instrument and ISIN mappings are versioned.
5. Provider disagreements are retained and visible.
6. Trendlyne historical data is not treated as PIT validated by default.
7. Kite candle integrity checks pass before indicator calculation.
8. Raw and adjusted price policies are explicit.
9. Failed and partial responses cannot silently become valid records.
10. Historical replay blocks future information from both providers.
11. All research runs preserve provider versions, dataset versions and configuration hashes.
12. Credential secrets never reach the browser, logs or AI prompts.
13. Test fixtures cover authentication, rate limits, empty responses, schema changes and PIT failures.
14. The system can operate in a Kite-only degraded mode for price-based charting when Trendlyne is unavailable.
15. The system can display Trendlyne enrichment as unavailable or unverified without breaking the charting workspace.

### 32.16 Implementation sequence

**Phase A — Provider foundations**

- Create adapter interfaces.
- Implement Kite instrument and historical candle ingestion.
- Implement Trendlyne entity search and structured enrichment calls.
- Add provider request/response logging without secrets.
- Add canonical normalization and provenance fields.

**Phase B — Data certification**

- Add OHLCV validation.
- Add provider reconciliation.
- Add instrument and ISIN mapping checks.
- Add corporate-action and adjustment-status handling.
- Add PIT validation and quarantine rules.

**Phase C — Analytics integration**

- Connect certified Kite candles to indicators and pattern detection.
- Connect certified Trendlyne fields to context and fundamental panels.
- Add source-aware pattern explanations.
- Add data-quality and provenance UI.

**Phase D — Historical research**

- Enable replay with provider-specific availability cutoffs.
- Validate all enrichment features for PIT safety.
- Run baseline and pattern outcome comparisons.
- Freeze provider, dataset and configuration versions before locked testing.

### 32.17 Licensing and commercial controls

Before production or multi-user deployment:

- Verify Kite Connect licensing and permitted data use.
- Verify Trendlyne MCP subscription scope, call limits and redistribution restrictions.
- Confirm whether data may be stored, cached, displayed to end users or used in derived commercial products.
- Maintain provider-specific usage counters and budget alerts.
- Prevent unapproved redistribution of raw provider data.
- Obtain legal/compliance review before exposing stock-specific signals or recommendations to external users.

The system must treat provider licensing and data entitlement as product constraints, not merely infrastructure configuration.
---

## 33. NIDP as the Historical Fundamental & Technical Source

### 33.1 Objective

Trendlyne MCP is an **enrichment** provider, not a history provider. Its documented exclusions and
its observed behaviour make it unsuitable as the sole source for historical research:

- It exposes **no as-of parameter** and serves **latest revisions** (Nivesh PIT audit, Day-0).
- It is **EOD only**, capped at 10 stocks x 50 parameters per call.
- Its data is **internal-use only**; redistribution is prohibited.

Therefore: **where a fundamental or technical historical series is required for research and is not
available from Trendlyne — or is available but not point-in-time safe — the system shall source it
from NIDP**, the project's own ingestion platform, and not fabricate, interpolate or backfill it
from a current Trendlyne value.

NIDP becomes the **third provider** in the §32 architecture, alongside Kite (candles) and
Trendlyne (enrichment).

### 33.2 Extended provider responsibility matrix

This table extends §32.2. Where the two disagree, this table governs for historical research use.

| Data or capability | Kite Connect | Trendlyne MCP | **NIDP** | Nivesh AI responsibility |
|---|---|---|---|---|
| Historical daily OHLCV | Primary (research use) | EOD parameters | `nidp.prices_eod` (NSE bhavcopy) | Choose per display-licensing status; record which was used |
| Historical technical features | Raw inputs only | Current technical summary | **Primary** — `nidp.stock_features_daily` | Recalculate any indicator that gates a pattern rule |
| Derived daily scores | Not provided | Not provided | `nidp.v3_stock_scores_daily` | Treat as a Nivesh-derived artifact, versioned |
| Delivery percentage | Not provided | Limited | **Primary** — `stock_features_daily` | Confirm coverage before use; absent from `prices_eod` |
| Quarterly financials history | Not provided | Current + some history, no as-of | **Primary** — `nidp.nse_financials_quarterly` | Use filing/broadcast timestamps, not period-end, for PIT |
| Shareholding / pledge history | Not provided | Current view | **Primary** — NIDP shareholding tables | Basis mismatch and blank-vs-zero traps apply |
| Corporate announcements | Not provided | Supported view | **Primary** — NIDP announcements feed | Announcement feed is the discovery spine for documents |
| Sector classification | Limited | Metadata where available | **Primary** — `nidp.sector_master` | Maintain versioned classification reference |
| Index / benchmark history | Instruments only | Limited | `nidp.index_eod` | Confirm the table is a table, not a view, before relying on it |
| Point-in-time semantics | Candle timestamp is the event | **Not certified — `PIT_UNVERIFIED` by default** | Filing/broadcast timestamps where captured | Certify per feature; never assume |

### 33.3 Source-selection policy addition

§32.7 is extended with the following rules, which apply **before** the existing rules 1-6:

1. For a **historical technical or fundamental series required by research**, prefer **NIDP** when
   the required field exists there with an availability timestamp.
2. Use **Trendlyne** for that series only when NIDP does not carry the field, and then mark the
   resulting feature `PIT_UNVERIFIED` and exclude it from any locked test until certified.
3. Never mix an NIDP historical series with a Trendlyne current value in the same feature column.
   If both are needed, keep them as two columns with separate provenance.
4. When NIDP and Trendlyne disagree on a value, retain the disagreement as a reconciliation
   finding (§32.8). Do not overwrite either.

### 33.4 Known NIDP constraints the architecture must respect

These are measured properties of the platform, not assumptions. Each is a real limit on what
research can claim:

- **Results ingestion lag.** Quarterly results land a **median 36 days after filing**; only ~3.7%
  arrive within one day. Any fundamental feature must use the availability timestamp, never the
  period-end date.
- **Announcement feed cadence.** Feeds run **Mon-Fri only**, so Saturday filings are invisible
  until Monday. Detection timestamps must account for this.
- **Document corpus depth.** The document corpus spans a limited window because documents are
  discovered *from* announcements; depth, not parser quality, is the binding constraint.
- **Equity analytics ceilings.** Known limits include truncated price history in some feature
  tables, delivery data absent from `prices_eod`, and some mislabelled 1-year metrics.
- **View drift.** Some NIDP objects are views on production where the repo declares tables.
  Confirm the object type before writing or relying on uniqueness.

Each constraint above must be surfaced in the research report (§18) and in the provenance panel
(§32.12), not silently absorbed.

> **UNVERIFIED:** the row counts, table names and coverage figures in §33.2 are taken from prior
> project findings and the repo's own documentation. They have **not** been re-queried against a
> live NIDP database in the session that produced this section. Any implementation step that
> depends on a specific table's shape must verify it against the running system first.

---

## 34. Early Pattern Formation, Readiness & Validation

### 34.1 Objective

Nivesh AI must detect patterns **while they are forming**, not only after the breakout has
occurred. By the time a breakout is confirmed under §12, the move that the pattern was supposed to
anticipate has already begun.

This module adds a pre-breakout detection capability with its own lifecycle, its own scores and its
own validation framework. It does **not** replace §11; it precedes it.

The first implementation targets **triangles, rectangles, flags and cup-and-handle** formations.

### 34.2 Relationship to the §11 lifecycle

§11 defines the post-breakout chain `CANDIDATE -> ... -> RESEARCH_ELIGIBLE`. This module inserts
four earlier stages in front of it. The two must reconcile as follows:

```text
Stage 1  EARLY_FORMATION     ]
Stage 2  PATTERN_DEVELOPING  ]  this module (pre-trigger)
Stage 3  BREAKOUT_READINESS  ]
                |
Stage 4  CONFIRMATION  ----> maps onto §11 BREAKOUT_ATTEMPT / PRICE_CONFIRMED onward
```

Stage 1-3 detections are **not** eligible for §11's `RESEARCH_ELIGIBLE` state and must never be
reported as confirmed patterns. They are a separate population with a separate base rate, and the
validation in §34.6 must keep them separate.

### 34.3 Pattern lifecycle

**Stage 1 — Early Formation.** Detect emerging support/resistance, compression, higher lows,
lower highs and improving structure.

**Stage 2 — Pattern Developing.** Measure pattern quality, boundary stability, volume behaviour
and volatility contraction.

**Stage 3 — Breakout Readiness.** Price approaches the trigger level, range compresses, and
momentum or volume begins changing.

**Stage 4 — Confirmation.** Breakout or breakdown is evaluated using closing price, volume,
volatility and follow-through, per §12.

A pattern may exit at any stage to `INVALIDATED`, `EXPIRED` or `UNRESOLVED`. The engine must be
able to report that a pattern was **incomplete, invalidated, or never confirmed** — these are
first-class outcomes, not missing data.

### 34.4 Early indicators to capture

| Indicator | What it detects |
|---|---|
| Range compression | Declining high-low range and ATR relative to historical values |
| Bollinger Band Width | Volatility contraction before a potential expansion |
| Higher lows / lower highs | Emerging ascending or descending structure |
| Support/resistance stability | Repeated reactions near a price zone |
| Distance to breakout level | How close price is to the pattern trigger |
| Volume contraction | Reduced participation during consolidation |
| Volume accumulation | Gradual increase in volume before a move |
| Relative strength | Stock performance compared with Nifty and its sector |
| Momentum slope | Change in RSI, MACD histogram and rate of change |
| ATR expansion risk | Whether volatility is beginning to expand prematurely |
| Failed breakout attempts | Repeated rejection near the boundary |
| Market / sector alignment | Whether broader context supports or conflicts with the structure |

Volatility contraction followed by expansion is a commonly studied characteristic of chart
formation. It must be treated as a **testable signal, not a guaranteed breakout predictor**.

### 34.5 Early Pattern Score

The score measures **pattern development quality**, not whether a breakout already happened.

| Component | Illustrative weight |
|---|---:|
| Structural quality | 25% |
| Volatility compression | 20% |
| Distance to trigger | 15% |
| Volume behaviour | 15% |
| Momentum and relative strength | 15% |
| Market and sector context | 10% |

These are **illustrative starting weights**. They must be validated through a pre-registered
historical test and must not be assumed optimal. Per §16, the weights, thresholds, component
values and calculation version must all be stored with any score.

The system must display **four separate values** and must not combine them into one opaque score:

```text
formation_score      How well the structure is developing
readiness_score      How close the pattern is to a possible resolution
confirmation_score   Strength of evidence after the boundary is crossed
failure_risk         Evidence of invalidation, rejection or structural deterioration
```

### 34.6 Pattern-specific early signals

**Ascending triangle.** Resistance tested multiple times; successive lows become higher; the range
between highs and lows contracts; price approaches resistance; volume contracts during formation.
Breakout confirmation is evaluated separately.

**Cup and handle.** Rounded decline and recovery; recovery approaches prior resistance; handle
forms with limited downside; handle range and volume contract; readiness increases near the rim.
Breakout and follow-through are validated independently.

**Bull flag.** Strong preceding price movement; short consolidation against or sideways to the
prior trend; reduced range and volume; price remains within defined flag boundaries. Breakout
direction and volume are assessed after the trigger.

These are **formation hypotheses**, not predictions.

### 34.7 Historical validation framework

For every early signal, record:

```text
symbol
pattern_type
detection_timestamp
formation_stage
formation_score
readiness_score
trigger_level
invalidation_level
features_available_at_detection
breakout_within_1_session
breakout_within_3_sessions
breakout_within_5_sessions
maximum_favorable_excursion
maximum_adverse_excursion
false_breakout
pattern_completed
data_quality_status
```

**Required controls:**

- Use only data available at the detection timestamp.
- Never use future breakout information in the early score.
- Test detection at multiple maturities: **20%, 40%, 60%, 80%** of formation, using the two definitions in §34.7.1.
- Compare early detection against a simple baseline.
- Measure false positives, missed patterns, time-to-breakout and post-detection returns.
- Validate separately across market regimes, sectors and liquidity groups.
- Keep confirmed breakouts separate from early-stage candidates.

**Additional controls required by this project's prior findings.** This repo has already measured
that its technical features call *movement* at AUC 0.724 but *direction* at ~0.50. A readiness
score that anticipates a *move* is therefore plausible; one that anticipates a *direction* is not,
on current evidence. The validation must consequently:

- Report a **movement metric** (realised absolute move, ATR-normalised) alongside every
  direction/P&L metric, so that a null direction result is still informative.
- Include a **volatility-matched control** in the comparison groups of §18.3 — compression
  selects low-volatility names, and a naive control will not separate the pattern from the
  volatility effect.
- Treat "the early score predicts movement but not direction" as an **expected and publishable**
  outcome, not a failure of the module.

### 34.7.1 Formation maturity without look-ahead (approved by owner 2026-09-21)

"Percent of formation" requires the pattern's final length, which is only known after the pattern ends. Computing a
maturity checkpoint from it would leak the future into every score recorded there. Two definitions are therefore used,
and they are never merged:

1. **Live definition** (engine, UI stage badge, any real-time use):
   `maturity = min(bars_since_first_detection / minimum_pattern_length, 1.0)`, or the §34.3 stage label plus fixed bar
   offsets after first detection. It never references the unknown end of the pattern.
2. **Offline retrospective definition** (§34.7 validation study only): for a pattern that has already completed, the
   checkpoint bar is `t_ck = t_start + round(f * (t_end - t_start))` for f in {0.2, 0.4, 0.6, 0.8}. `t_end` may choose
   **which bar** becomes the example; it must never influence **the value recorded there**. Every score at `t_ck` is
   recomputed by the live detector on data physically truncated at `t_ck`.

The offline study samples only patterns that completed, so it is conditioned on survival. It must always be reported
next to the live-definition study, which includes patterns that later failed or expired.

**Required test:** mutate every bar after `t_ck`, including `t_end` itself, and recompute. The stored score must not
change. No field derived from `t_end` (such as final length or bars-to-breakout) may appear in a checkpoint score.

### 34.8 UI requirements

The chart must show:

- Emerging pattern boundary lines, visually distinct from confirmed patterns (§20.2).
- Formation stage badge.
- Trigger and invalidation levels.
- Historical instances of the same pattern on the same symbol.
- Score history over time.
- The "first detected" timestamp.
- Reasons for score changes.
- Similar completed patterns and their outcomes.
- A timeline showing when each signal became available.

The last item is a point-in-time control surfaced in the UI: a user must be able to see that no
displayed signal post-dates the detection timestamp.

### 34.9 Acceptance criteria for this module

1. Stage 1-3 detections are stored and reported separately from §11 confirmed patterns.
2. No early score consumes any value dated after its `detection_timestamp`.
3. All four scores are stored and displayed independently; no single composite replaces them.
4. Detection is reproducible from the stored configuration and dataset versions.
5. The four maturity checkpoints (20/40/60/80%) are each evaluated.
6. Results are reported against a baseline **and** a volatility-matched control.
7. Movement and direction outcomes are reported separately.
8. Incomplete, invalidated and never-confirmed patterns are reported, not dropped.
9. The weights in §34.5 are frozen in a pre-registration before any locked test.
