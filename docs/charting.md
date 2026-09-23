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

---

## 35. Amendment A — Pattern Intelligence & Validation (2026-09-22)

Source: the owner's "Technical Chart Pattern Intelligence & Validation Engine" PRD, kept verbatim at
`.claude/workspace/charting-pattern-engine/prd-pattern-intelligence-v1.md` (cited below as N§). A gap review
(`review-prd-pattern-intelligence.md`) found about 70% of it already specified in §1-§34. This section adopts the remainder
and resolves every conflict. **Owner decisions (2026-09-22):** fold it in as an amendment, not a separate PRD; the frozen
ATR-based rules of §30.1 stand wherever N§ differs; the market benchmark is NIFTY 500; outcomes are computed through the
§36 cost engine (net), not gross-only.

### 35.1 Conflict resolutions

| Topic | N§ proposal | Resolution |
|---|---|---|
| Touch tolerance | 1.0% of price | **§30.1 stands:** 0.35 × ATR. |
| Breakout confirmation | Close > level, distance ≥ 0.25% | **§30.1 stands:** close beyond level ± 0.25 × ATR (equal to the failure buffer, so states cannot overlap). The percentage distance is stored as a descriptive field only. |
| Relative-volume bands | five bands with double-counted edges | **§30.1 stands:** four half-open bands. |
| Swing separation | 5 bars | The §30.1 touch separation (3 bars) stands; a 5-bar separation applies only where a pattern rule states it (e.g. §13.6 troughs). |
| Minimum formation bars | 20 | 15 stands (unchanged §10.2 / §30 default). |
| Swing tie rule | earliest bar of a plateau | Latest bar wins (built, tested); now recorded in CONFIG so it is covered by the configuration hash. |
| State names | FORMING … TARGET_REACHED | §11 names stand (live on staging). TARGET_REACHED is an outcome and lives in the outcome record, not the lifecycle. |
| Benchmark | NIFTY 50 | **NIFTY 500**, now a CONFIG key. NIFTY 50 is fetched as a secondary series. |
| Historical store | SQL tables | Immutable hashed run artifacts (§21) until a queryable store is separately approved. |
| Composite score | allowed for sorting | Deferred until the event dataset exists (§16; N§35's own closing rule). |
| Expected move | three estimates per signal | Deferred; owner-only wording decision pending (no "target price" language). |

### 35.2 Adopted additions
- **Relative strength** (N§11): RS5/RS20/RS50/RS100 = stock return minus NIFTY 500 return over the window; stored per pattern event.
- **Market regime** (N§12): BULL / BEAR / SIDEWAYS from NIFTY 500 vs its SMA200 and the SMA200 slope; India VIX and universe breadth
  recorded as context fields. Values that would need data from the sealed window are UNAVAILABLE.
- **Trend context** (N§10): SMA20/50/200, EMA20/50, ADX, slopes, a 0/1/2 trend state; raw metrics always retained.
- **Breakout candle quality** (N§8): body % and close location stored as descriptive fields (not confirmation gates until validated).
- **Retest quality** (N§13): penetration depth, attempts, retest relative volume, bars to retest and to continuation — descriptive.
- **Historical event dataset** (N§14-§16, §23): one row per pattern instance at its confirmation bar; forward returns at 1/3/5/10/20
  sessions, MFE/MAE, bars to +2/+5/+10/+15%; success reported per target, horizon and condition with sample size, and
  "insufficient_n" below a pre-registered minimum.
- **Versioning** (N§24): each signal carries signal_timestamp, data_cutoff_timestamp, strategy/feature versions, config hash.

### 35.3 Data sources for the additions
Daily NIFTY 50, NIFTY 500, INDIA VIX (and sector indices where available) from Kite Connect, stored with a SHA-256 manifest.
Market breadth (advance/decline, % above SMA50/SMA200, new highs/lows) is derived from the project's own universe of Kite daily
bars, because no breadth feed exists. **No bar dated 2023-01-01..2024-07-31 is fetched or stored for research use.**

### 35.4 Research-integrity fixes adopted with this amendment
1. A sealed-window guard on every research entry point (replay, movement, event generation) — display may use that history;
   research evaluation may not.
2. `retest_window_bars` is wired into the retest rule (it was hashed but unused).
3. HH_HL confirmation uses the same ATR breakout buffer as the other families.
4. The benchmark name and the swing tie rule are CONFIG keys, covered by the configuration hash.
5. `relative_volume_band` labels the follow-through volume rule; `convergence_ratio` is reserved for triangle/wedge detectors.

### 35.5 Deferred (explicit)
New pattern families beyond §13's P0 set (triangles, double/triple tops and bottoms, flags/pennants, wedges, H&S, cup & handle,
rounding, VCP) each need owner-approved definitional forms and a pre-registration amendment before code. Walk-forward windows,
intraday timeframes, a SQL store and a composite score are out of this amendment.

### 35.6 Build status (2026-09-22)
- **Built (research code, `research/charting/`):** the event dataset (`events/`: one row per confirmed pattern, entry at the next
  session's open with close-of-signal-bar as a labelled alternative, outcomes at 1/3/5/10/20 sessions, MFE/MAE, bars to
  +2/+5/+10/+15%, cost blocks through §36 under all four slippage scenarios and the liquidity-bucket model, versioning fields,
  random-selection and buy-at-next-open control hooks); relative strength, market regime, trend context, India VIX and breadth
  (`regime.py`, with its own `FEATURE_CONFIG` hash); breakout candle quality and retest quality as descriptive pattern fields.
- **Not yet run for results:** no outcome statistics are computed until the pre-registration is frozen by the owner.
- **Open owner decisions:** (1) the SMA slope lookback (20 bars, the only existing convention) and SIDEWAYS as "neither BULL
  nor BEAR" with no numeric band; (2) the `hit_high_N` / `hit_close_N` reading (+N% high within N sessions / close return ≥ N%
  at N sessions); (3) target/stop outcome labels wait on the stop/target policy (§35.1, expected move deferred); (4) BEARISH
  signals: cost blocks are long round trips, and short-side costs are not modelled because an overnight cash-market short is not
  possible — decide whether bearish patterns are studied gross only, as "avoid" signals, or through another instrument.

---

## 36. Amendment B — Transaction cost, slippage & tax layer (2026-09-22)

Source: the owner's "Transaction Cost, Slippage & Tax-Aware Net Return Engine" PRD, kept verbatim at
`.claude/workspace/charting-pattern-engine/prd-transaction-cost-tax-v1.md`. It replaces the §18.1 cost placeholder and is the cost
model for pattern validation (owner decision 2026-09-22), so outcomes no longer wait on the paper-trade branch.

### 36.1 Two return series, never mixed
- **Net trading return (primary strategy measure):** gross − entry/exit slippage − brokerage − STT − exchange transaction charges
  − SEBI charges − GST − stamp duty (and DP charge where the rule set includes it).
- **Investor after-tax return (separate layer):** net trading P&L − capital-gains tax from a configurable tax profile. Capital-gains
  tax is never a transaction cost.

### 36.2 Rules are data, date-effective and versioned
Every charge resolves from a versioned rule set by each leg's own trade date, exchange, segment and instrument type; every rate
carries a source and effective dates, and any rate that cannot be verified is marked unverified rather than assumed. The existing
`zerodha-equity-v1` model is reproduced exactly as one rule set, so earlier simulations stay comparable. Tax rules (STCG/LTCG by
holding period and date, cess, surcharge, loss set-off assumptions) are separate, immutable rule versions.

### 36.3 Slippage and liquidity
Fixed %, fixed bps, volume-dependent, ATR-based and liquidity-bucket models; inputs are only values known at the signal time.
Sensitivity scenarios: optimistic 0.05%, base 0.15%, conservative 0.30%, stress 0.50%. Position value / ADV is recorded per event.

### 36.4 Reporting rule
Every pattern statistic is reported gross **and** net of costs with the cost breakdown and sample size (e.g. gross hit rate, net hit
rate after costs, median gross and net return, average cost, average slippage, net expectancy). Consistent with §2.4 and decision
#4, a negative net result is a valid research outcome.

### 36.5 Conventions settled in review (implementation: `research/costs/`)
- Charges are computed on the theoretical fill values, with slippage a separate P&L line (the PRD's own worked example:
  ₹481.07 costs, ₹600 slippage, ₹8,918.93 net). Capital gain uses the slipped fills, i.e. the consideration actually paid and received.
- STT is not a deductible transfer expense (Section 48 proviso); brokerage is the default deductible expense, configurable.
- Long-term means held for more than 12 months, counted calendar-exactly from the buy date.
- The Section 112A exemption is an annual allowance shared across trades: the caller passes the unused amount for the year
  (default 0), never the full threshold per trade.
- Surcharge on Section 111A/112A gains is the income-slab rate capped at 15% (cap in force since FY2019-20).
- A rate with no value raises an error rather than pricing zero; a rate taken from a secondary source is used but listed in the
  trade's `unverified_rates_used`.

---

## 37. Amendment C — Owner decision baseline for validation (2026-09-22)

Owner decisions given in chat on 2026-09-22 ("final baseline I would freeze"). They settle the open items in §35.6 and are the
baseline for the pre-registered study. Where the owner's message was internally inconsistent, the resolution is stated.

### 37.1 Trend classification
- Window: 20 sessions. `slope_pct_per_day = regression_slope(close, 20) / mean(close, 20) × 100` (ordinary least squares on
  the last 20 closes against session index).
- STRONG_BULL: slope ≥ +0.30 %/day and ADX(14) ≥ 25 · BULL: slope ≥ +0.15 %/day and ADX(14) ≥ 20 ·
  BEAR: slope ≤ −0.15 %/day and ADX(14) ≥ 20 · STRONG_BEAR: slope ≤ −0.30 %/day and ADX(14) ≥ 25 · SIDEWAYS: otherwise.
- **Resolution (owner-confirmed, baseline v1.1):** SIDEWAYS when ADX(14) < 20 OR the slope is within ±0.15 %/day; BULL/BEAR need
  both the slope direction and enough ADX, so sideways takes precedence over weak directional signals.
- Applied to each stock and to NIFTY 500. The §35.2 NIFTY 500 vs SMA200 regime is kept alongside, with a 20-session slope window.

### 37.2 Outcome definitions (replaces the single "hit" labels)
- Per target: `target_hit`, `stop_hit`, `both_hit`, `neither_hit`, `target_hit_session`, `stop_hit_session`, `first_exit_event`.
  If the target and the stop are both touched inside the same daily bar (no intraday data), the outcome is `AMBIGUOUS` — never
  assumed either way.
- MFE, MAE, net return and holding period are separate fields, never merged into a hit label.
- Research targets: +2%, +3%, +5%, +10% from entry, plus R-multiple targets 1R, 1.5R, 2R, 3R (R = entry − initial stop).
- Returns are reported gross and net (§36).

### 37.3 Stop policy
- Layer 1 — pattern invalidation (structural stop): breakout families use `broken level − failure_buffer_atr × ATR`
  (§30.1's frozen failure buffer); double bottom below the second trough; cup & handle below the handle low; triangle at the
  opposite boundary; HH/HL at the invalidation swing.
- Layer 2 — minimum distance: the stop is at least 0.75 × ATR(14) below entry (widened, never tightened).
- A bar that opens beyond the stop fills at the open (gap), not at the stop price.

### 37.4 Bearish patterns
Detected, displayed and validated, but `tradability = INFORMATIONAL` and `action = AVOID_NEW_LONG` for the cash-only long
portfolio. No fictitious overnight short trade is priced (§36 cost blocks are long round trips).

### 37.5 Corporate actions and universe
- Demergers are a corporate-action regime break: `corporate_action_event = DEMERGER`, `pattern_regime_break = TRUE`. Sessions
  T−5..T+5 are excluded from ordinary validation; pre- and post-demerger histories are separate regimes, never spliced.
- The ETF exclusion comes from an ETF master (isin, symbol, name, issuer, underlying index, asset class, inception, listing,
  status, delisting) and a point-in-time universe snapshot per date. Today's list is never used to decide a 2021 universe.
- **Deferred by the owner (2026-09-22) — on the to-do list.** Until then the existing sealed ETF list stays the exclusion
  (known false positives such as BHARATFORG and DALBHARAT are disclosed in every report).

### 37.6 Pattern states
Research states FORMING → EARLY_SIGNAL → BREAKOUT_CANDIDATE → CONFIRMED_BREAKOUT → FAILED_BREAKOUT / COMPLETED.
**Resolution (owner-confirmed, baseline v1.1):** the §11 lifecycle names are live on staging, so these are a derived
`research_state` mapped from the §11 state and the §34 early stage, not a rename. An unconfirmed pattern is never called a
breakout.

**Research enrichment never mutates the production pattern result** (owner rule, 2026-09-22). The detector's pattern record,
lifecycle, API and Charts UI stay as they are; research fields (research_state, trend regime, confirmation measures, MFE/MAE,
target/stop labels, validation metrics) live in a separate enrichment record keyed by `pattern_id`.

### 37.7 New pattern families (definitions from the owner; parameters still to be pinned before code)
Ascending / descending / symmetrical triangle, double bottom / top, head & shoulders, bull / bear flag, cup & handle — with the
owner's rules (e.g. triangle: ≥2 resistance touches, ≥2 rising swing lows, resistance deviation ≤ 1.5%, breakout close >
resistance × 1.005, volume ≥ 1.5 × 20-day average; double bottom: troughs ≥ 10 sessions apart and within 3%, neckline = highest
reaction between troughs; flag: duration < impulse duration, retracement < 50% of impulse; cup & handle early setup: cup ≥ 80%
complete, handle forming, price within X% of resistance). **Resolution:** these percentage rules apply to the new families; the
§30.1 ATR rules stay for the P0 families (owner-confirmed, baseline v1.1). Where applicable the research record stores
`breakout_level`, `breakout_threshold_pct`, `breakout_threshold_atr` and `breakout_volume_ratio`, so validation can compare
how stable the percentage and ATR thresholds are across volatility regimes. Unstated
parameters (e.g. "contracting range", "shoulders approximately similar", "strong preceding impulse", the cup's X%) are pinned in
a predicate table for owner approval before any detector is coded, as NI-2 was.

### 37.8 Common pattern schema and licensing
- Every family converges on one record: pattern (name, family, direction, state), geometry (dates, breakout and invalidation
  levels, confidence), trend (regime, slope_20d, adx_14, relative strength), volume, confirmation components, historical
  validation (sample size, target/stop hit rates, MFE, MAE, median return and holding period, net return), tradability
  (long_actionable, short_actionable, informational_only).
- Licensing: display and redistribution follow each provider's terms. Raw market data, derived indicators, pattern detections and
  research analytics are kept separate, and every feed carries source and licence metadata. Redistribution rights are verified
  before any public or commercial display.

---

## 38. Amendment D — Professional chart workspace (2026-09-22)

Source: the owner's request on 2026-09-22, with two screenshots. The reference is a TradingView chart (POONAWALLA, 1-minute,
NSE) with a top toolbar, a left drawing rail, an in-chart legend, stacked indicator panes and a bottom range bar. The second
screenshot is the live Charts tab (ADANIENT, daily). The owner wants the Charts tab to work like the reference.

A gap review compared §1–§37 and the live build (PRs #134–#141, VERIFIED on staging) against the reference. Most of the
capabilities are already specified: chart types §7.1, timeframes §7.2, drawing tools §7.3, replay §19, workspace controls
§20.1 and the indicator panel §20.4. What is not specified is the workspace: how those controls are laid out and operated.
Some interaction features are also missing: the legend, pane controls, drawing modifiers, undo/redo, saved layouts, range
presets and indicator parameters. This section adds them and nothing else. Decision #3 (Lightweight Charts) stands. The
reference layout is built as Nivesh UI on Lightweight Charts (see D-1 in §38.14).

### 38.1 Reference vs current build

| Area | Reference (TradingView) | Current Charts tab | Specified before this amendment |
|---|---|---|---|
| Layout | top toolbar, left drawing rail, chart fills the window, bottom range bar | rows of buttons above a fixed 480 px chart; indicator and pattern cards on the right; drawing list below | no |
| Symbol | search, favourite, compare (+) | filter list of the 50 snapshot symbols | §20.1 search + watchlist; compare = §7.1 P1 |
| Timeframe | 1m … 1M menu | daily only; weekly/monthly disabled (spec G-6) | §7.2 |
| Chart type | candles, bars, line, area, Heikin Ashi … | candles only | §7.1 |
| Indicators | searchable dialog, any parameters, repeat instances, per-indicator style, RSI bands + its MA | 8 fixed series from the snapshot (atr_14, bollinger, ema_20, macd, relative_volume, rsi_14, sma_20, sma_50) as checkboxes | §20.4 in outline only; dialog, instances and bands not specified |
| Legend | OHLC + change at the crosshair, volume, each indicator's value, hide/settings/remove | none | no |
| Panes | move up/down, maximise, collapse, resize | panes appear, with no controls | §20.4 "reorder panes" only |
| Drawing | ~20 tools in a rail; magnet, lock, hide, remove all, ruler, zoom; undo/redo | trendline, horizontal line, select, delete | §7.3 lists the tools; modifiers, editing and undo/redo not specified |
| Navigation | 1D 5D 1M 3M 6M YTD 1Y 5Y All, go-to-date, log/%/auto scale, ADJ, clock | Fit, Full screen | §7.1 "date-range selection" only |
| Saved layouts | named layout ("Unnamed" + save) | none | no (§21 profiles are pattern configurations) |
| Replay | bar replay | none in the UI (the engine exists, §19) | §19 engine; no UI |
| Alerts | alert button | none | §5.3 "generate alerts", no spec |
| Theme | light | app theme (dark) | no |
| Data | 1-minute, live | Kite daily 2021-01-01..2026-09-18, frozen snapshot, 50 symbols, owner-only (decision #10) | §7.2, §32 |
| Trading | Buy/Sell with bid/ask | — | §3.2 non-goal |
| Scripted overlays | peer table with BUY ZONE / TREND / ACTION; user-script scanner pane | — | no |

### 38.2 Rules carried over unchanged

- Nivesh computes indicator values under the §8.7 contract and serves them from the API. The browser draws them but never
  calculates an indicator it displays (§2.3), so a parameter change always goes through the API.
- Manual drawings stay visually distinct from system pattern overlays (§7.3, §20.2).
- The status badge, provenance drawer and Data view that already exist stay one click away in the new layout (§32.12).
- No chart surface uses buy, sell, target-price or "action" wording (§3.2, §29 item 14). §37.4's `AVOID_NEW_LONG` is a
  research field, not a chart label.
- The "Charts by TradingView" attribution stays visible in the chart area (licence, TC-21).
- The Charts tab stays owner-only while it shows Kite-derived prices (decision #10).

### 38.3 Workspace layout (P0)

Desktop (≥ 1024 px wide):

1. **Top toolbar:** symbol button (opens search), timeframe menu, chart-type menu, Indicators, Compare (P1), Replay (P1),
   Alerts (P2), undo, redo, layout name with a save menu, full screen and chart settings. There is no chart theme
   control; the chart follows the app theme (D-6).
2. **Left drawing rail** (§38.6).
3. **Chart area:** fills the remaining height, with a minimum of 480 px. It holds the price pane and then the indicator
   panes, each with its own right price scale.
4. **In-chart legend** at the top left of each pane (§38.4).
5. **Bottom bar:** range presets, go-to-date, IST clock, ADJ toggle and log / % / auto scale (§38.7).
6. **Right sidebar:** collapsible, with tabs for Watchlist, Patterns (today's patterns panel), Levels, Drawings and
   Provenance. It opens on Patterns, and collapsing it gives the chart the full width.
7. **Data-status badge** (e.g. `PIT_UNVERIFIED`): sits in the legend next to the symbol and opens the provenance panel, as
   the reference's "D" (delayed data) marker does.

Below 1024 px, the drawing rail folds into a "Draw" menu and the sidebar becomes a bottom sheet. Toolbar items that do not
fit move into a "More" menu. The page never scrolls sideways.

### 38.4 Legend and crosshair (P0)

- The price-pane header shows symbol · timeframe · exchange · status badge. Then it shows O H L C and the change from the
  previous close (absolute and %) for the bar under the crosshair. When the pointer is off the chart, it shows the last
  bar. Values are coloured up/down.
- Volume is shown for the same bar.
- Each indicator has one row: its name and parameters (e.g. "RSI 14 close"), then its value(s) at the crosshair. Hovering a
  row shows hide, settings, remove and provenance controls.
- A toggle collapses the legend.
- All panes share one crosshair. The time-axis label shows the date on daily and longer bars, and date + time (IST) on
  intraday bars.
- The price pane has a last-price line with an axis label. Indicator panes show last-value labels.
- A bar that is not complete yet (the current week or month, or an intraday bar) is visibly marked and never feeds
  confirmation (§7.2).

### 38.5 Indicators dialog and panes

P0:

- **Dialog:** a searchable list grouped as trend / momentum / volatility / volume (§8.1–§8.4). A catalogue endpoint serves
  it. For each indicator the catalogue gives its id, name, category, its presets (fixed parameter sets), default pane,
  output fields and calculation version.
- **Instances:** the same indicator can be added more than once with different presets (e.g. SMA 20 and SMA 200). Each
  instance gets its own id.
- **Settings per instance:** preset choice, colour, line width and style, and visibility. Colour and style affect only the
  display, never the calculation. Reference bands appear where the indicator defines them (e.g. RSI 30/70 with shaded
  fill). A smoothing line of an indicator's output (the reference's yellow RSI moving average) is one more output field of
  the preset, not a browser calculation.
- **Panes:** a non-overlay indicator opens in its own pane. Each pane can be moved up or down, maximised and restored,
  collapsed or removed, and resized with a draggable divider. The saved layout keeps pane order and heights (§38.8).
- **Errors:** the API rejects a preset id that is not in the catalogue with a reason code (§27), and the dialog shows the
  reason.

P1: indicator templates, i.e. a named set of instances that can be applied to any symbol (§20.4).

**Presets only (D-3, decided 2026-09-22).** Users choose from a controlled preset catalogue and cannot enter arbitrary
parameters.

- **Versioning:** the catalogue is versioned and hashed with the snapshot, and every preset is precomputed at export. This
  fits the chart API, which only reads the snapshot and computes nothing (`backend/services/research_chart.py`, the Sim
  Lab rule).
- **Adding a preset:** means a new catalogue version and a re-export.
- **Reproducibility:** a chart view or research run cites preset ids and the catalogue version, so it can be reproduced
  exactly.
- **Initial catalogue:** the 8 series in today's snapshot, plus SMA and EMA 10/20/50/100/200, RSI 7/14/21, Bollinger
  20×2, MACD 12/26/9 and ATR 14.
- **Not planned:** free parameters and an on-demand compute endpoint.

### 38.6 Drawing rail

P0 covers the §7.3 P0 tools laid out in the rail, plus the interaction layer the reference has:

- **Tool groups:**
  - cursor: cross, dot, arrow
  - lines: trendline, ray, extended line, horizontal line, horizontal ray, vertical date marker
  - zones and shapes: rectangle, support/resistance zone
  - Fibonacci retracement
  - annotation: text
  - measure: price and date range
  - manual target and invalidation lines

  The rail shows the last-used tool in each group.
- **Editing:** select a drawing, drag an anchor, drag the whole drawing, set a per-drawing style (colour, width, dash),
  clone, delete. Styles are stored in the existing `style` field.
- **Modifiers:** magnet (snaps anchors to the nearest O/H/L/C), stay in drawing mode, lock all, hide all and remove all
  (asks for confirmation).
- **Undo/redo** (Ctrl+Z / Ctrl+Shift+Z) covers create, move, restyle and delete within the session. Each step is an API
  call. If a call fails, the change is rolled back and an error is shown. The server copy stays the source of truth.
- **Scope:** drawings are saved per symbol and timeframe (the schema already carries `timeframe`). Because anchors are
  dated, a drawing made on daily also shows on weekly and monthly. It shows on intraday bars only if the user turns that on.

P1: parallel channel, pitchfork, risk/reward box and Fibonacci extension (§7.3 P1).

Not planned: brush/free-hand drawing, emoji and icon stickers.

### 38.7 Timeframes, chart types and navigation

- **Weekly and monthly (P0, display only).** G-6 is split into two parts:
  - Pattern detection on weekly and monthly stays deferred, because a 120-bar maximum pattern cannot fit in 69 monthly
    bars.
  - Display does not have that limit. ADANIENT's 1,417 daily bars resample to 299 weekly and 69 monthly bars.

  Resampling happens at export and is hashed with the snapshot. Weeks are NSE sessions grouped by ISO week (Monday–Friday)
  and months are calendar months. Holidays are skipped, and the trailing bar is flagged incomplete. On weekly and monthly,
  the Patterns tab says "patterns run on daily bars only".
- **Chart types (P0):** candles, hollow candles, OHLC bars, line and area. P1 adds Heikin Ashi, labelled synthetic.
  Patterns and indicators never run on Heikin Ashi bars.
- **Range presets (P0):** 1M, 3M, 6M, YTD, 1Y, 5Y and All. 1D and 5D are added once intraday exists; until then they are
  disabled, with a tooltip giving the reason. Go-to-date and reset view (double-click the time axis) are also P0.
- **Price scale (P0):** auto, log and percent modes, set per pane.
- **ADJ toggle (P1):** switches between adjusted and raw prices. Kite daily bars are back-adjusted (the snapshot records
  `ADJUSTED_SPLITS_BONUS_ONLY`), so a raw series has to come from NSE bhavcopy (`nidp.prices_eod`). Until a raw series is
  exported, the toggle is disabled with that reason. The legend always shows the adjustment status (§32.12).
- **Clock:** IST, fixed and shown. There is no timezone picker.
- **Intraday (§7.2 P1, decided by the owner 2026-09-22, D-2):** 15-minute and 1-hour bars, owner-only, from an offline
  export (§38.14). Other intraday intervals, including 1-minute, stay P1/P2 as §7.2 lists them.

### 38.8 Saved layouts, watchlist, compare

- **Layouts (P0).** A named layout holds:
  - symbol, timeframe and chart type
  - indicator instances with their parameters and styles
  - pane order and heights
  - visible range and drawing visibility
  - sidebar state (the theme is not stored; it follows the app, D-6)

  Users can save, save as, rename, delete and reopen recent layouts. Layouts autosave after changes. A new chart is
  "Unnamed" until it is saved. Layouts are stored per user in the Mongo collection `research_chart_layouts`, scoped by
  user in the same way as `research_drawings`.
- **Watchlist (P1, §20.1).** Named lists of symbols in the sidebar. Each row shows the last close and day change from the
  same series as the chart, and a favourite toggle sits on the symbol button. The app has no user-editable watchlist
  today; the positional `/watchlist` route returns a system-generated list.
- **Compare (P1, §7.1 multi-chart comparison).** Overlays another symbol, or NIFTY 500, as a percent-change line from the
  first visible bar. The benchmark series already exists (`research/index_history`).
- **Multi-chart grid (P2).** 2 or 4 charts with a linked symbol, timeframe and crosshair.
- **Peer table (D-5, decided 2026-09-22).** A factual comparison of the symbol with its industry peers, shown in a
  sidebar tab. The contents and rules are in §38.14.

### 38.9 Replay, alerts, theme, keyboard

- **Bar replay (P1, the UI for §19).**
  - Controls: choose a start bar, then play, pause, step one bar, change speed, or exit.
  - Bars after the replay cursor are never sent to the chart.
  - Pattern overlays show only the state the §19 engine recorded at the cursor bar. They never show a pattern's final
    geometry before that geometry existed (§34.8 signal timeline).
  - Replay inherits the sealed-window guard (§35.4). A start whose frames touch 2023-01-01..2024-07-31 is refused, and the
    UI shows why.
- **Alerts (P2).**
  - Triggers: price crosses a level or a drawing, an indicator crosses a value, or a pattern changes state (§5.3).
  - Alerts are delivered in-app only.
  - They depend on Monitoring Mode (fresh data after every session), which does not exist yet.
  - Alert text states facts ("closed above 3,040.00") and never gives advice.
- **Theme (P0, D-6).** The chart follows the app's light/dark theme (`data-theme`, set in Settings) and has no theme
  setting of its own.
  - **Live switching:** when the app theme changes, an open chart re-themes without a reload. Today the chart reads its
    colours only once, when it loads (a documented v1 limitation in `charts/theme.ts`), so W1 has to change this.
  - **Colours:** chart colours come from the existing tokens, which keeps the two themes consistent.
- **Keyboard (P0).**
  - Shortcuts: Alt+T trendline, Alt+H horizontal line, Alt+F Fibonacci, Esc cancel, Delete removes the selection,
    Ctrl+Z / Ctrl+Shift+Z undo/redo, arrow keys pan.
  - The mouse wheel zooms and dragging pans.
  - Every toolbar and rail button has a tooltip and an aria label.
  - Data view stays available as the accessible table alternative.

### 38.10 Excluded, and why

- **Buy/Sell buttons, bid/ask, order tickets, broker connection:** §3.2 non-goals.
- **User-written scripts (Pine-style) and community indicators:** they bypass the §8.7 contract, provenance and
  explainability (§2.1). The reference's "Positional Trade Scanner" pane maps to Nivesh's own §34.8 score-history pane,
  not to a scripting feature.
- **Recommendation tables:** the reference's "NBFC Smart Dashboard" (BUY ZONE / TREND / ACTION: WAIT) is an investment
  recommendation and is blocked on the SEBI RA/IA question. The factual peer table (D-5) replaces it. It has no action
  column, no ranking and no score.
- **Live streaming to anyone except the owner:** Kite data may not be displayed to other users (decision #10). Streaming
  needs a display-licensed vendor first.
- **TradingView branding:** the layout follows common charting conventions. It uses no TradingView name, logo or look-alike
  marks beyond the required attribution.

### 38.11 API additions

```http
GET    /api/research/chart/indicators/catalog                            # presets + catalogue version
GET    /api/research/chart/{symbol}/ohlcv?timeframe=1D|1W|1M
GET    /api/research/chart/{symbol}/indicators?timeframe=…&presets=…       # presets only (D-3)
GET    /api/research/chart-layouts
POST   /api/research/chart-layouts
PATCH  /api/research/chart-layouts/{layout_id}
DELETE /api/research/chart-layouts/{layout_id}
GET|POST|PATCH|DELETE /api/research/watchlists[/{watchlist_id}]           # P1
GET    /api/research/chart/{symbol}/replay?start=…                        # P1, backed by §22.5
GET    /api/research/chart/{symbol}/peers                                 # D-5 peer table
```

Like the existing chart routes, all of these sit behind `require_feature("charting")`. The drawings API already supports
PATCH (§22.2), which is enough for editing and undo.

### 38.12 Delivery phases

| Phase | Scope | Backend | Depends on |
|---|---|---|---|
| W0 | patterns drawn on the chart automatically, click to select (§38.15) | none (uses fields the snapshot already has) | — |
| W1 | layout shell (§38.3), legend (§38.4), pane controls, chart-type menu, range presets, scale modes, live app-theme following, keyboard; drawing rail with the two existing tools plus editing, undo/redo, magnet, lock and hide | none | — |
| W2 | weekly/monthly display, indicator dialog with preset instances and bands, saved layouts | export resampling; preset catalogue; layouts API | W1 |
| W3 | remaining §7.3 P0 tools, watchlist, compare, bar-replay UI | watchlists API; replay export | W1–W2 |
| W4 | intraday 15-minute and 1-hour (D-2), factual peer table (D-5), raw ADJ series, alerts, multi-chart grid | intraday export; peer data (§33.3 sources); raw series | W2 timeframe path; alerts also need Monitoring Mode and track F |
| F (alongside W1–W3) | automated daily data (D-4): Kite when a session exists, NIDP as the fallback | provider abstraction on the §32.4 / §33 adapters (tracker CHART-T03, CHART-T04); scheduled ingestion and export; reconciliation; data served from outside the backend image | owner-approved build spec for the data location; a daily Kite session (§38.16, manual login until that is built) |

Each phase ships under `.claude/VERIFICATION_PROTOCOL.md`. Test cases are written first. Every changed screen is tested
with Playwright against staging, and every new endpoint gets API tests.

### 38.13 Acceptance criteria

W1–W3:

1. The chart area fills the window below the toolbar. The page does not scroll sideways at 1280×720 or at 390 px wide.
2. Moving the crosshair updates the legend's O H L C, change, volume and every indicator value to that bar, and the
   values match the Data view for the same date.
3. An indicator added twice with different presets draws two series. Each legend row names its preset, and the values
   match the API. A preset id that is not in the catalogue is rejected with a reason code.
4. Moving, maximising, collapsing and removing panes all work, and the pane order survives a reload through the saved
   layout.
5. Every drawing action can be undone and redone. A failed save rolls back and shows the error.
6. Magnet snaps an anchor to that bar's O/H/L/C. Lock blocks edits and hide hides drawings, and neither deletes anything.
7. Weekly bar values equal an independent resample of the daily bars. The trailing bar is marked incomplete, and the
   Patterns tab says patterns run on daily bars only.
8. Range presets set the visible range to the stated window. 1D and 5D are disabled and show the reason.
9. A saved layout restores symbol, timeframe, chart type, indicators, panes and range in a new session.
10. Replay never sends a bar after the cursor to the chart, which is checked by counting bars in the response. A start in
    the sealed window is refused.
11. The status badge, provenance drawer, Data view and attribution are present in both themes.
12. Changing the app theme in Settings re-themes an open chart without a reload.

Track F (D-4):

13. On a session with no Kite login, the chart gains that session's bar from NIDP, and the legend and provenance panel
    name NIDP as the provider of that bar.
14. If Kite and NIDP disagree on an overlapping session beyond the build-spec tolerance, nothing is spliced. The chart
    stays at its last good session with a STALE badge, and the disagreement is recorded as a reconciliation finding
    (§32.8).
15. A refresh changes none of the hashed inputs of the pre-registered study.

W4 peer table (D-5):

16. Every value shows its period, source and as-of date, and a missing value shows "—", never 0.
17. The table has no rank, score or action column, and its default order is market cap.

W0 pattern display (§38.15):

18. Opening a symbol draws every detected chart pattern with no click. The number drawn equals the API's count for the
    active filter, checked through a test hook, as `data-rendered-levels` is today.
19. Each pattern is drawn only across its own dates (formation start to its last event), never across the whole chart.
20. Clicking a pattern selects it, whether the click is on its shape on the chart or on its row in the list:
    - the other patterns dim
    - the view zooms to the pattern's window
    - the details card shows its §20.3 fields, rules and event timeline

    Esc, or a click on an empty part of the chart, clears the selection.
21. Forming, confirmed, failed and invalidated patterns look different from each other, and all of them look different
    from manual drawings.
22. A symbol with no chart patterns says so on the chart itself, and lists the families that were checked.
23. Each pattern shows a "Known" marker at a date on or after all of its pivots' confirmation dates.
24. Grouped S/R bands list every underlying record when clicked, and the number of records equals the API count.

### 38.14 Owner decisions (all decided 2026-09-22)

| Decision | Decision taken | Owner's rationale |
|---|---|---|
| D-1 Chart library | Keep Lightweight Charts | Avoids rebuilding existing pattern overlays and keeps indicator calculations server-side. Advanced Charts adds licensing uncertainty and browser-side indicator logic that conflicts with the architecture. |
| D-2 Intraday | Start with 15-min + 1-hour, 50 symbols | Good MVP boundary. It gives useful intraday context without creating a large data-ingestion/compute problem. Keep this user-only initially. |
| D-3 Indicator settings | Preset settings only | Best first implementation. Define a controlled preset catalogue rather than allowing arbitrary parameters. This also makes historical validation reproducible. |
| D-4 Data freshness | Move toward automated daily ingestion; use NIDP prices as the fallback | The current 2026-09-18 cutoff is a major weakness. Don't make daily Kite login a permanent dependency. Design the data provider behind an abstraction so Kite can be used when available and NIDP data can be the fallback. |
| D-5 Factual peer table | Yes | Useful as contextual evidence alongside technical signals. Keep it strictly factual (e.g. market cap, sector, revenue growth, margins, ROE/ROCE, valuation) without turning it into a subjective ranking. |
| D-6 Chart theme | Follow app theme | Better UX and avoids a separate chart-theme setting. Light/dark should switch automatically with the application theme. |

How each decision is applied:

**D-1 Library.** The workspace is built on Lightweight Charts (decision #3 stands). TradingView's Advanced Charts library
is not adopted.

**D-2 Intraday.** 15-minute and 1-hour bars for the snapshot universe (the 50 symbols), owner-only.

- **Source and path:** Kite intraday candles covering the last 60 completed sessions, exported offline with the chart
  snapshot and hashed with it. The chart API stays snapshot-only and never calls Kite.
- **Size:** 25 bars per session at 15 minutes (09:15 to 15:30 IST), and 7 at 1 hour if the hourly bars start at 09:15
  so the last one covers 15:15–15:30. The first export confirms that alignment. That is about 75,000 and 21,000 bars
  across the 50 symbols.
- **Access:** behind `require_feature("charting")`, because decision #10 still applies to Kite-derived prices.
- **Completed sessions only:** the export leaves out any session still in progress, so an intraday bar is never
  incomplete.
- **Kite session:** each export needs a fresh Kite session, i.e. the owner's login. Intraday data is as of the export
  date, and keeping it current is D-4.
- **Not affected:** patterns still run on daily bars only. Indicators on intraday bars are computed at export by the
  same series code, using the D-3 preset catalogue.
- **Close check:** the close of the last intraday bar is the last traded price, which can differ slightly from the
  official closing-auction close. The export records the difference for each session, and a test confirms each
  session's 09:15 open matches the daily open.
- **Presets:** 1D and 5D are enabled on intraday timeframes.
- **Still deferred:** 1-minute and the other §7.2 intervals. Showing intraday to users other than the owner still needs
  a display-licensed vendor.

**D-3 Indicator settings.** Presets only; see §38.5 for the catalogue, versioning and initial list.

**D-4 Data freshness (track F in §38.12).**
- **Goal:** refresh the chart's daily bars automatically after each session, without the daily Kite login ever becoming a
  hard dependency.
- **Daily routine (owner, 2026-09-22):** the owner logs in to Kite each trading day. Until the §38.16 admin page is
  built, this is the current manual flow. NIDP covers any day without a login.
- **Provider abstraction:** built on the §32.4 adapter contract and the §33 NIDP adapter (tracker CHART-T03, CHART-T04). A
  display-price policy picks Kite when a valid Kite session exists. Otherwise it takes the missing sessions from NIDP
  (`nidp.prices_eod_adjusted`).
- **Per-bar provenance:** every bar records its provider, and the legend and provenance panel show it (§32.12).
- **Splice rule:** before an NIDP bar is appended to a Kite history, the overlapping sessions are reconciled (§32.8). The
  tolerance is set in the build spec.
  - If the sources disagree beyond it (for example, a different adjustment basis after a corporate action), nothing is
    spliced. The chart stays at its last good session with a STALE badge.
  - When Kite is available again, its back-adjusted history replaces the fallback bars, and each replacement is logged.
- **Data location (needs design):** today the snapshot is committed into the backend image, so each refresh would be a
  commit plus a backend deploy. Daily deploys are not viable: each one uses about 7 GB of nivesh-app-vm disk, and
  backend deploys have restarted prod Mongo. The refreshed data must therefore be served from outside the image, with the
  same manifest and sha256 checks. Where it lives is decided in the track F build spec.
- **Limits:**
  - NIDP history starts on 2023-05-16, so NIDP fills recent sessions but does not replace the 2021+ Kite history.
  - NIDP price feeds run Monday–Friday and have had outages. A missing NIDP session also shows STALE.
  - Intraday (D-2) has no NIDP source. It stays Kite-only as of its last export and shows STALE once it is older than
    the last session.
- **Unchanged:**
  - The Charts tab stays owner-only while any bar comes from Kite (decision #10).
  - The refresh never touches the hashed inputs of the pre-registered study.

**D-5 Factual peer table (W4).**
- **Where:** a "Peers" tab in the chart sidebar, comparing the symbol with its industry peers.
- **Columns:**
  - company, sector/industry, market cap
  - revenue growth (YoY), operating and net margin, ROE, ROCE
  - valuation (P/E, P/B, EV/EBITDA)
- **Every value shows:**
  - its period (e.g. FY26, or TTM to Q1 FY27), source and as-of date
  - "Nivesh-derived" where Nivesh calculated it (§32.12)
  - for valuation multiples, the price date
  - "—" when missing, never 0
- **Sources** follow §33.3: NIDP first where the field exists with an availability timestamp; otherwise Trendlyne, marked
  `PIT_UNVERIFIED`. Trendlyne data is internal-only, so the table stays owner-only while any value comes from Trendlyne.
- **Peer set:** companies in the same industry group from one named classification source. The source is pinned in the
  build spec and shown in the table.
- **Strictly factual:** no rank, composite score, good/bad colouring, "cheap/expensive" labels or action column. The
  default order is market cap, and the user can sort by any column.
- **Current values only:** the values are current, not point-in-time, and the table says so. Research validation does not
  use it.

**D-6 Chart theme.** The chart follows the app theme and switches live; there is no chart theme setting and the layout does
not store one (§38.3, §38.8, §38.9).

### 38.15 Patterns on the chart (owner request, 2026-09-22)

The owner asked for detected patterns to appear on the chart automatically, and for a click on a pattern to select it.
The reference was a TradingView video ("Automated Technical Analysis: Tutorial", TradingView). The video itself could not
be viewed from this environment: only its title and channel were retrieved, and there was no transcript. So this section
is based on the request, not on the video's details.

**Today (live build).**
- **Hidden by default:** patterns are listed as text in a card at the bottom right, and each one starts hidden. The user
  has to tick it to see it on the chart.
- **Clicking does little:** clicking a row turns the overlay on, but does not zoom to the pattern or highlight it.
  Clicking the chart never selects a pattern.
- **Overlays are loose:** they are price lines that run across the whole chart, plus pivot arrows. They are not the
  pattern's shape over its own dates, which §20.2 asks for ("formation boundary").
- **Three families only:** the engine detects support/resistance, rectangle and higher-high/higher-low. In the live
  snapshot that is 388 S/R levels, 114 rectangles and 11 HH/HL structures across 50 symbols. 9 of the 50 symbols
  (including ADANIENT, BSE, ICICIBANK, LT and SBIN) have no chart pattern other than S/R levels, so their Patterns card
  reads "No chart patterns found."

**Recognition (unchanged by this section).**
- **Deterministic rules:** patterns are recognised by the §12–§13 rules with the frozen §30.1 ATR-based predicates.
  Swing pivots use 3 bars left and right, and each pivot has a `confirmed_date` after its right-hand bars, so no pivot is
  used before it could have been known.
- **Explainable:** every pattern carries its rules, events, levels and status, so the chart can explain why a pattern is
  drawn.
- **More families pending:** triangles, double tops and bottoms, head and shoulders, flags and cup & handle (§37.7) have a
  drafted predicate table (`ni3-new-family-predicates.md`, decisions-log #98). They need owner approval before any
  detector is coded. Until then, "all patterns" means the three live families.

**Display requirements (P0, phase W0).**
- **Automatic:** when a symbol opens, every detected chart pattern is drawn with no click needed. S/R levels stay a
  separate layer with their own toggle.
- **Shape, not lines:** each pattern is drawn over its own dates:
  - Rectangle: a box from formation start to formation end, between support and resistance.
  - HH/HL: a line joining its pivots.
  - Breakout and invalidation levels: short segments starting at formation end and ending at the confirmation or failure
    event.
  - Markers: at the pivot, confirmation, failure and invalidation dates.
- **Label:** each shape carries a small label with the pattern's name and status (e.g. "Rectangle · confirmed").
- **Status styling (§20.2):** confirmed patterns are solid, forming ones dashed and faded by stage, and failed and
  invalidated ones dotted and grey. Manual drawings keep their own distinct style.
- **Filters:** chips for All / Active (forming or confirmed) / Confirmed / Failed / Invalidated, and for each family.
  The default is All, and the chosen filter is saved with the layout.
- **Click to select,** from either a shape on the chart or a row in the sidebar list:
  - the pattern is highlighted and the others dim
  - the view zooms to its window (formation start to last event, with a margin)
  - the details card opens with its §20.3 fields, rules (each opening provenance) and an event timeline
  - where shapes overlap, the most recent pattern is selected first, and Previous/Next buttons step through the rest

  Esc, or a click on an empty part of the chart, clears the selection. Hovering a shape shows its name, status and dates.
- **Empty state on the chart:** a symbol without chart patterns says so on the chart, e.g. "No chart patterns detected —
  checked: support/resistance, rectangle, higher-high/higher-low".
- **"Known" marker** (from the open-source review, §38.17): a dotted vertical line at the bar where the pattern first
  became detectable, so the detection lag is visible and honest.
  - The export adds this date from the §19 replay engine's first detection (§34.8 "first detected" timestamp).
  - Until then, the marker uses the latest pivot `confirmed_date` and is labelled "pivots confirmed".
- **Near-duplicate grouping:** S/R levels within the §30.1 touch tolerance (0.35 × ATR) of each other are drawn as one
  band labelled with the count, which clears the clutter of about 8 levels per symbol. Clicking the band lists each
  record. The records themselves are unchanged (§29 item 5).
- **Nearest-level readout:** the legend names the S/R level or pattern boundary nearest to the last close, with its
  distance in ₹ and in ATR and its role (support or resistance). It is a fact, not a signal.
- **Accuracy:** the drawn shapes must match the backend records exactly (§29 item 5). The browser never recognises
  patterns itself.
- **Delivery:** frontend only. Everything above uses fields the snapshot already carries (`formation_start`,
  `formation_end`, `levels`, `pivots`, `events`, `status`, `stage`). The shapes are drawn by a chart primitive with hit
  testing, in the same way as the existing drawings primitive.

### 38.16 Daily Kite session — admin login (planned; manual until built)

Owner request, 2026-09-22: an admin endpoint and page for the daily Kite login, automated as far as possible, with the
owner entering the 2FA code. **Status: planned only.** The manual process continues until this is scheduled: print the
login URL, the owner logs in, then the request token is exchanged from a 0600 file through stdin.

**What may and may not be automated.**
- **Login must be manual:** Zerodha's documentation says an access token expires at 06:00 IST the next day. It ends earlier
  if it is invalidated through the API or by a master logout on Kite Web. On the Kite Connect developer forum, Zerodha
  staff state:
  - "It is mandatory by the exchange that a trader has to login manually at least once in a day. We don't recommend
    automating login."
  - On automated login: "this was never allowed to begin with. If you were doing it, you were in violation of the terms
    of use of the APIs."
- **So the Zerodha password and 2FA code are never typed into, stored by or relayed through Nivesh.** They are entered on
  Zerodha's own login page. A headless login (our server submitting user id, password and OTP to Zerodha) and storing
  the TOTP seed are both excluded. Besides breaking the API terms, they would make Nivesh the holder of credentials to a
  trading account.
- **Everything around that login is automated:** starting the login, catching the redirect, exchanging the token, storing
  it, health checks, reminders and fallback.
- **The API secret is not refreshed daily.** It is a fixed credential kept in GSM (`BROKER_ZERODHA_API_SECRET`).
  Regenerating it ends live sessions (observed 2026-09-19). It is rotated on the Kite developer console only if it leaks.
  Only the access token changes each day.

**Daily flow once built (about 20 seconds of the owner's time).**
1. On a trading day with no valid token, admins see a banner, and the owner gets a reminder (channel chosen in the build
   spec) with a link to the admin page.
2. The owner clicks "Log in to Kite". The backend creates a one-time state value, valid for 5 minutes and tied to the
   admin's session. The browser goes to `https://kite.zerodha.com/connect/login?v=3&api_key=…` with that state in the
   documented `redirect_params` parameter.
3. The owner enters their password and 2FA code on Zerodha's page.
4. Zerodha redirects to the registered URL, which already exists: `/v5/kite-callback` on staging. The page no longer
   displays the request token. It posts the token and the state to the backend.
5. The backend checks the state and exchanges the token with the checksum SHA-256(api_key + request_token + api_secret),
   reusing `generate_session` from `backend/services/brokers/zerodha.py`. It then calls `profile()` and requires the
   Zerodha user id to equal the configured owner id. It stores the access token encrypted, with `expires_at` = the next
   06:00 IST.
6. The page shows "Connected until 06:00 IST tomorrow". Consumers use the token from then on:
   - the track F daily export
   - the D-2 intraday export
   - research pulls

**Endpoints** (admin only, through `require_admin`; mutations also pass the existing CSRF origin check):

```http
GET    /api/admin/kite/status         # connected | expired | never; masked Zerodha id; obtained_at; expires_at; last check
POST   /api/admin/kite/login-start    # returns the Zerodha login URL with a one-time state
POST   /api/admin/kite/session        # {request_token, state} -> exchange, verify, store; never echoes a token
POST   /api/admin/kite/check          # calls profile() now; updates status
DELETE /api/admin/kite/session        # invalidates the session at Kite, deletes the stored token
```

**Admin page:** Settings → Admin → Data providers → Kite. It shows a status pill, expiry time, last health check, the
"Log in to Kite" and "Disconnect" buttons, and a login history built from the audit log.

**Storage ("application context").**
- **Recommended:** a GSM secret (e.g. `kite-access-token-staging`), written by the backend as a new version at each login.
  - The jobs on nidp-stack-vm already read GSM, so the token reaches them without a new network endpoint.
  - The backend's service account needs permission to add versions to that one secret only. That IAM grant is an owner
    action, and which service account staging runs as is UNVERIFIED.
- **Alternative:** a Mongo document encrypted with `services/pii_security.encrypt` (AES-256-GCM). But the jobs on
  nidp-stack-vm would then need an internal endpoint to fetch the token.
- **Not allowed:** the admin secrets registry (`helpers/secrets.py`), because it stores values in plain text.

**Safeguards.**
- The token never appears in an API response, log line, URL, error message or page.
- Every login and disconnect is written to the audit log with the admin user, the time and the masked Zerodha id, never
  the token.
- A state value that is missing, reused or expired is rejected, and nothing is stored.
- An hourly `profile()` check marks the session expired early if it was invalidated (master logout, secret change).
- With no valid token, the daily export falls back to NIDP (D-4). The intraday export skips that day and the chart shows
  STALE.
- The flow runs only on staging, where the redirect URL is registered.
- It uses the data Kite app (`BROKER_ZERODHA_*`), not the per-user broker-connect path (OpenAlgo).

**Acceptance criteria (when built).**
1. A non-admin gets 403 on every `/api/admin/kite/*` route.
2. A callback with a missing, reused or expired state is rejected, and nothing is stored.
3. After a real login, the status shows "connected", the Zerodha id matches the owner, and `expires_at` is the next 06:00
   IST.
4. A search of the API responses, backend logs and page HTML from the test run finds no token.
5. A consumer job on nidp-stack-vm reads the stored token and gets a successful `profile()` call.
6. Disconnect makes the next `profile()` call fail and removes the stored token.
7. With an expired token, the status changes to "expired" within one check interval, and the daily export uses the NIDP
   fallback.

**Prerequisites (owner):**
- choose the storage option and grant its IAM permission
- choose the reminder channel
- confirm the owner's Zerodha user id to check against
- confirm the Kite app's registered redirect URL is still `/v5/kite-callback` on staging

**Phase:** track K. It is a prerequisite for running track F and D-2 without an agent in the loop, and is not yet
scheduled.

### 38.17 Open-source pattern scripts — review (2026-09-22)

The owner asked for TradingView's open-source chart-pattern scripts to be read. The full review, with the method,
licence and relevance of each script, is `.claude/workspace/charting-pattern-engine/review-tradingview-open-source-patterns.md`.

**Scope of the reading.**
- **Covered:** the 5 pattern/structure scripts on the category page, plus Trendoscope's Auto Chart Patterns and Flags &
  Pennants.
- **Descriptions only:** the published descriptions were read, not the Pine source.

**What they confirm.** The good scripts use confirmed pivots only, decide every state on a closed bar, and appear "late
by design". They show forming patterns differently and grey out finished ones, and several use ATR-normalised
tolerances. Our §2.2, §11 and §30.1 already do all of this.

**Adopted for display (W0, in §38.15).** Three features: a "Known" marker at the bar where a pattern became detectable,
grouping of near-duplicate S/R levels into one band, and a readout of the nearest level.

**Detection proposals — each needs owner approval, and a pre-registration amendment before any research use.** The frozen
v1 study is not changed.
- **P-1 One trendline-pair classifier** for channels, wedges and triangles (Trendoscope's approach):
  - Take the last 5–6 alternating pivots.
  - Fit an upper line through the highs and a lower line through the lows.
  - Require every bar in the span to stay inside, within the §30.1 ATR tolerance, and the two lines not to cross.
  - Classify each line's slope as rising, falling or flat, and the pair as converging, diverging or parallel.

  One rule set gives about 13 named types, including channels and wedges that NI-3 does not cover. It would sit
  alongside or replace NI-3's separate triangle predicates. It conflicts with §37.7's percentage rules for triangles, so
  the owner has to choose.
- **P-2 Flags and pennants as an impulse followed by a P-1 consolidation:** a bull flag is an up impulse followed by a
  descending channel or falling wedge, and a bull pennant is an up impulse followed by a converging or ascending triangle.
  This would unify NI-3 §7–§8.
- **P-3 A second, longer pivot scale** (e.g. 8/8 next to 3/3), run as a separate layer. Each pattern records its scale.
  This finds the larger patterns the current single scale misses. It adds tests, so the pre-registration must count
  them.
- **P-4 Double top/bottom tolerance as a percentage of pattern height,** stored as a descriptive field next to §37.7's
  owner-set 3%-of-price rule. It does not replace that rule.
- **P-5 Automatic diagonal trendlines as a family** (MarketMaulers):
  - a rising support line needs two strictly higher lows and at least 3 touches within 0.25 × ATR
  - touches within 3 bars count once
  - no close through the line between its anchors
  - near-duplicate lines are dropped, and a line is retired after 20 bars far from price
  - outcomes are RETEST or FAILED BREAK

  Our S/R is horizontal only today.
- **P-6 Break by persistence** (3 consecutive closes beyond a level), as a research variant only. The frozen §30.1
  confirmation rules stay as they are.

**Not adopted.**
- Entry/stop/target zones.
- ✓/✗ "target hit" labels.
- Running hit-rate panels. A hit rate over the patterns on screen is not a validated result (§2.4, §36.4).
- Automatic pitchforks with trade levels. TradingView itself classes such scripts as "potentially misleading".
- Any lookahead.

**Licensing.** Only the Auction Foundry scripts state a licence (MPL-2.0). The others are "open-source" under TradingView's
House Rules, with the licence in the source header. Nivesh implements from its own written predicates and ports no Pine
code. If code were ever reused, the script's licence header is read first, and non-commercial licences are excluded.

### 38.18 Owner decisions on detection (2026-09-22)

The owner decided the open detection items, and they are recorded as given.

| Item | Decision |
|---|---|
| P-1 | **ACCEPT, hybrid.** P-1 geometry detects and names triangles, wedges and channels. The owner's percentage rules decide flatness, breakout and volume. |
| P-2 | **ACCEPT.** A flag or pennant is a strong pole followed by a P-1 shape. |
| P-3 | **ACCEPT.** A large-swing layer is added. It is shown on the charts first and used in research only in study v2. |
| P-4 | **ACCEPT.** The 3% double top/bottom tolerance stays. Tolerance relative to pattern height is stored as research metadata. |
| P-5 | **DEFER.** Sloping S/R comes later and reuses P-1 geometry. |
| P-6 | **ACCEPT.** The breakout definition is unchanged. Three consecutive closes beyond the level is recorded as research metadata. |
| Research states (#95) | **ACCEPT** `NOT_TRIGGERED`, for a pattern that was invalidated or expired before any breakout, and `INCONCLUSIVE`, for one that was data-blocked or unresolved. |
| Volume (#95, #109) | **ACCEPT: the definitions stay separate.** Today's 3 families keep the follow-through bar at 1.0–4.0× the 20-day average, and frozen v1 is not changed. The new families use the breakout bar at ≥ 1.5× the 20-day average. |
| Candle/retest metrics (#93) | **ACCEPT.** They move from the production pattern record into the research record. |
| Study plan | **ACCEPT.** A new v2 is written; frozen v1 is not modified. |
| Double top/bottom separation | **10 sessions** (the Amendment C position). |
| Head & shoulders stop | **Primary: above the right shoulder plus an ATR buffer. Secondary research variant: neckline plus buffer.** Both are always reported. |
| Cup & handle length | **Up to 260 sessions.** |

**Research principle (owner).** The order is freeze → detect → evaluate → report everything → interpret, and never
detect → optimise → retest → pick the best-looking result. No parameter is tuned after results are seen.

**Execution order (owner).**
1. Freeze these decisions.
2. Revise NI-3, tagging every parameter OWNER / PROPOSED / FROZEN.
3. Approve NI-3 and record its configuration fingerprint.
4. Write study plan v2, covering:
   - pattern types and swing sizes
   - entry, stops, targets and costs
   - control groups and holding periods
   - every combination tested
   - the detector fingerprint and the sealed period
5. Implement detection (P-1, P-2 and the remaining NI-3 families).
6. Build the drawings, generated from the detected geometry.

W0, the chart display of today's patterns, proceeds independently.

**Progress (2026-09-22).**
- **Steps 1–3 done.** The owner approved NI-3 r2, including the recommended answers to its five questions (inverse
  H&S added, so 16 types; expanding shapes out of v2; pennants = symmetrical triangles only; the large-swing layer also
  covers the live families; overlaps linked, never pooled).
- **Frozen files:**
  - `docs/ai_research/CHARTING_NI3_PREDICATES_V1.md`
  - `docs/ai_research/charting_ni3_config_v1.json`, fingerprint `de86626c6f15e5f2d41708e92f8b66367394eb1c8e52ed2534ecfd8e0ded44a8`
  - the live families at the large scale: config_hash `9b81eae7…`
- **Step 4 drafted:** `docs/ai_research/CHARTING_PREREGISTRATION_V2.md`, awaiting owner approval of its choices V-1 to
  V-5.

### 38.19 Amendment E — Live signals, paper trading and the redesign (review 2026-09-22)

The owner sent three documents and asked for a review against the plan and the code, then asked for this PRD to be
amended with the outcome. Nothing in §38.1–§38.18 is edited; this section records what the review found and the
positions taken. It applies to the three documents whenever they are filed or built from.

**38.19.1 What was reviewed.**
- The design "Charting View Redesign standalone" with four screens: 1A Chart, 2A Signals & Alerts, 4A Paper Trading,
  3A Field Dictionary.
- "PRD — Nivesh Paper Trading & Signal Validation Engine v1.0" (2026-09-22).
- "PRD — Live Trading Alerts & Signals Engine v1.0" (2026-09-22).
- Checked against: §2, §3.2, §11, §16, §20.3, §37 and §38 of this document; the frozen rulebook
  `docs/ai_research/CHARTING_NI3_PREDICATES_V1.md` (fingerprint `de86626c…`); study plan v1 (frozen) and v2 (draft);
  the code on `origin/dev` (`backend/routes/research_chart.py`, `research/charting/`, `research/costs/`,
  `backend/routes/paper_trades.py`); the TPD paper engine on its local branch; and the recorded study results.
- The three documents are referenced by title here. The two PRDs were filed verbatim on 2026-09-23 at
  `docs/prd/live_trading_alerts_signals_prd.md` and `docs/prd/nivesh_paper_trading_prd.md`, each with a filing header
  that carries the positions in 38.19.4–38.19.5 (owner request, 2026-09-23). The design remains referenced by title.

**38.19.2 What is adopted from the design.**
- The 1A chart screen is the target rendering of §38.3–§38.8: the single 56 px top bar with the symbol, live price,
  interval, chart type, indicators and compare; the 44 px vertical drawing rail; legend rows with per-indicator hide,
  settings and remove; the crosshair tooltip with O/H/L/C, volume and RSI; the S/R panel with price, type, strength,
  distance in ₹ and %, and HOLDING/BROKEN; stacked panes with drag handles and collapsed strips; the range selector on
  the time axis; the watchlist.
- It is a design-canvas mock, not Lightweight Charts. Rendering it is the W1–W3 work in §38.12.
- Corrections carried into W1:
  - Weekly and monthly are enabled for display (§38.7 resamples daily bars; ADANIENT gives 299 weekly and 69 monthly
    bars). The mock shows them disabled with "needs longer history"; only detection on those intervals stays deferred.
  - S/R levels are grouped into bands (§38.15). Live data averages about 8 levels per symbol; the mock shows 4 loose
    ones.
  - The §38.15 W0 items the mock omits are still required: the "Known" marker, click-on-chart selection, and the
    on-chart empty state that lists the families checked.
  - The source and as-of badge stays on every screen (§2.1). 1A keeps PIT_UNVERIFIED; 2A and 4A dropped it. The 2A
    fingerprint line "P-1 FITTED GEOMETRY · v2.1" is right and stays.
  - The mock's "Bull flag · UNCONFIRMED" and "3 detected" are illustrative: no flag detector exists.

**38.19.3 Sequence.** Live signals and paper trading are steps 7 and 8 after the six steps in §38.18.
- Both need detectors that do not exist. Study plan v2 §9 lists every capability as "not built", and the v1 study
  (three families, daily) has not run.
- The Signals PRD's Phase 1 (the signal contract and the lifecycle mapping in 38.19.4) may be written now. Its Phases
  2–6 and the paper engine start only after study v2 reports.
- The first live version is end-of-day daily signals from the existing batch replay, which is what v2 validates.
  Intraday and streaming are gated on track F (daily data), track K (§38.16) and the D-2 export, and stay owner-only
  (decision #10). Today the chart API is snapshot-only, daily data ends 2026-09-18, and there is no push channel for
  charting on `dev`; the Signals PRD's latency (§31), WebSocket events (§30) and three timeframes (§17) need an
  intraday ingestion loop, per-bar detector runs and a push channel that do not exist.

**38.19.4 Rules the documents must follow.**
- **Score: components only, no headline number.** The Signals PRD §12 and the 2A screen show a single 0–100 score
  with fixed weights. §11 says a single opaque confidence score is insufficient, and §16 allows a composite only after
  component behaviour is understood; the live Patterns panel already states that each score is never summed into one
  number. The evidence points the same way: the TPD composite score ordered trades the wrong way round (its top 5 sat
  at the 0.5th percentile of random). The seven component bars stay; the headline number goes. Any composite is a
  research object: pre-registered in a later study version, tested, then shown. Two components are removed from any
  live weighting: retest quality (moved to the research record by #93/#110) and risk/reward (circular against the
  fixed §37.2 targets).
- **Setup and ticket: owner-only until NI-1a.** Entry, stop, targets, quantity and capital at risk (2A "Trade setup",
  4A ticket, Signals PRD §13, Paper PRD §16) are visible only behind the owner allowlist until the SEBI RA/IA question
  (NI-1a) is answered (§3.2, §38.10, §37.4, and the TPD decision of 2026-09-17). The Signals PRD §4 "future
  advisor/MFD users" are out of scope until then, and are in any case not possible on Kite data (#10).
- **Setup values come from the frozen definitions,** computed by the same code as the study: stop = the NI-3 Layer-1
  structural stop widened to at least 0.75 × ATR(14); targets = the v2 set (+2 / +3 / +5 / +10% and 1 / 1.5 / 2 / 3 R).
  The design's example is not derived from them: a trigger of ₹1,256 on resistance ₹1,250 is +0.48%, under the 0.5%
  BREAKOUT_CANDIDATE threshold (it needs more than ₹1,256.25); the stop ₹1,218 (−3.0%) is not the Layer-1 stop; and
  the targets ₹1,300 and ₹1,320 (+3.5% and +5.1%) are not in the v2 set. The Signals PRD §13 claim that every value is
  reproducible from the stored record holds only when the frozen definitions are used.
- **Illustrative numbers are labelled.** Every research or performance figure in the design is illustrative, because
  no study has run: "41 comparable ascending-triangle breakouts, 58% reached Target 1", "96 trades, win 56.3%, net
  +₹72,600", "expectancy +₹756", the per-pattern roll-up. Each carries "ILLUSTRATIVE · NO STUDY HAS RUN". The design
  footer's "scores shown as the engine would emit them" is withdrawn: the engine emits no score and no comparables.
  The negative and empty state is a required design: what the research-context block and the pattern roll-up show
  when v2 reports no information beyond volatility. Every real study to date found no edge (TPD replay, the positional
  study, the simulation matrix), and technicals predicted movement but not direction.
- **One lifecycle vocabulary.** The Signals PRD introduces a third set of state names. The mapping is:

  | Signals PRD | Research (NI-3 §1.2) | Note |
  |---|---|---|
  | WATCH | FORMING | |
  | READY | EARLY_SIGNAL | 1% readiness band, NI-3 S9 |
  | TRIGGERED | BREAKOUT_CANDIDATE | close beyond the live level by 0.5% |
  | CONFIRMED | CONFIRMED_BREAKOUT | plus breakout-bar volume ≥ 1.5× |
  | INVALIDATED | INVALIDATED or FAILED_BREAKOUT | two distinct research states; they must not be merged |
  | NOT_TRIGGERED, INCONCLUSIVE | as #110 | research states |
  | RETEST, CONTINUATION | events on the row | not states |

  The Signals PRD adopts the research names, or carries this table as frozen. The validated thing must be the shown
  thing.
- **Pattern coverage** is the 16 NI-3 v1.0 types. The Signals PRD §7 list of 14 is superseded (it lacks inverse head
  & shoulders and the two pennants, and folds wedges and channels together).
- **Volume:** the Signals PRD §11 split (live families 1.0–4.0× follow-through; new families ≥ 1.5× breakout bar; raw
  ratio always stored) is confirmed as already decided (#109, #110).
- **One execution kernel.** The paper engine reuses `research/costs/` (statutory and broker rules, four slippage
  scenarios, the liquidity bucket, sensitivity tables) and `research/charting/events/outcomes.py` (entry at the next
  open, gap fills at the open, AMBIGUOUS when the stop and the target are inside one bar), and extends the existing TPD
  paper engine (`tpd_model/paper/`, `/api/paper-trades`) rather than building a second one. The Paper PRD §13 cost
  engine and §17–§21 fills, stops, ledger and replay describe these; the Paper PRD lacks the AMBIGUOUS rule, and without
  it paper results would not reconcile with v2 on the same events. Paper results must reconcile row for row with v2.
- **Paper Phase 1** is daily, long-only, owner-only and fixed quantity. Signal-only mode (what would have happened) is
  the research question and ships first.

**38.19.5 Positions recorded.** These were recommended in the review; the owner asked for the amendment, so they are
recorded as taken unless the owner changes them.
1. Sequence: after study v2, with only the Signals PRD Phase 1 written now.
2. Score: components only.
3. Setup and ticket: owner-only until NI-1a.
4. Lifecycle: the research state names, with the table above as the mapping.
5. Paper engine: extend the TPD paper engine on the shared outcomes and costs kernel.

**38.19.6 What lines up already** (so it is not re-litigated): the Signals PRD §8 P-1 table equals NI-3 §2; §6.2
READY at 1% equals NI-3 S9; §22–§24 versioning, fingerprint and no look-ahead match NI-3 §1.1 and v2 §8; §23's study
plan v2 is drafted. The Paper PRD's principle 12, §41 and §65 (paper results never tune frozen rules; pattern, signal
and trade are three separate truths) match #110; §7.3 signal-only mode is the research question; §34 gap handling
matches v1 §5. The 2A and 4A disclaimers ("simulated, no broker order", "not a guarantee") match §2.1.

---

## 39. Pattern detection rules and the indicator matrix (owner specification, 2026-09-23)

### 39.1 Why this section exists, and what it owns

§38.15 records that the engine detects three families. The Signals PRD §7 claimed fourteen and NI-3
specifies sixteen. Three independent lists had drifted apart, and every worked example in the 2A and
4A PRDs used an ascending triangle — a family with no detector. This section closes that by stating
the shared detection layer once, and by pointing at a single executable source of truth for which
families exist.

**This section owns** the layer that no other section owned: the detection principles, the common
pipeline, the pivot/look-ahead rule, the registry invariant, the three indicator classes and their
per-family matrices, the evidence-over-scores rule, the detector output contract, and the
architectural invariant.

**This section indexes, it does not restate.** Per-family predicates already have owners — §13 and
§30.1 for the P0 families, §37.7 and NI-3 v1.0 for the new ones. NI-3 is frozen, fingerprinted
`de86626c…`, and cannot be edited without minting v1.1; a rule copied out of it into here becomes a
second, unhashed copy that can drift. That is the failure this section exists to prevent, so it must
not commit it. Where a number appears below, it is a quotation with its source named.

### 39.2 Core detection principles

1. **No look-ahead.** A pattern may use only bars up to `event_bar`. Future bars must never influence
   detection, boundaries, pivots, breakout levels or confirmation.
2. **Deterministic.** Same OHLCV + same detector version + same configuration = identical result. No
   model judgement, no sampling, no LLM anywhere in the detection path.
3. **Versioned.** Every detection stores `pattern_type`, `detector_version`, `config_version`,
   `timeframe`, `event_bar`, `start_bar`, `end_bar`.
4. **OHLCV only for core geometry.** Geometry comes from price structure. Volume confirms a
   breakout; it never manufactures the pattern.
5. **Minimum evidence.** A pattern is never created from visual resemblance. Every family declares
   minimum bars, pivots, touches, structural relationships and geometric tolerance.
6. **No subjective language.** Rules such as "looks like", "strong trend", "clean breakout" or
   "obvious resistance" are not admissible as predicates.
7. **Pattern ≠ signal.** Detection identifies structure. Whether that structure produces an
   actionable event is decided downstream by the signal evaluator (§38.19, Signals PRD §9).

### 39.3 The common detection pipeline

Every detector follows the same stages, in this order:

```text
OHLCV
  ↓
Data validation
  ↓
Swing / pivot detection
  ↓
Structure extraction
  ↓
Candidate generation
  ↓
Geometric validation
  ↓
Minimum-evidence validation
  ↓
Pattern lifecycle
  ↓
Pattern detection
```

**Data validation — reject before detecting.** Detection does not run when any of these hold:

| Reject condition | Why |
|---|---|
| Any of O/H/L/C missing | no geometry is derivable |
| `high < max(open, close)` | bar is internally inconsistent |
| `low > min(open, close)` | bar is internally inconsistent |
| `high < low` | bar is internally inconsistent |
| duplicate timestamps | pivot indices become ambiguous |
| bars materially out of chronological order | the walk's ordering assumption breaks |
| insufficient historical bars | below `minimum_pattern_length` (§10.2) there is nothing to fit |

These rules are **already implemented** with frozen reason codes in
`research/charting/validate.py` (`RULE_IDS`, `HARD_INVALID_RULE_IDS`, `SOFT_RULE_IDS`), and the full
rule set is §9.1 — the table above is the subset that stops detection, not a replacement for it.
A detector cites those reason codes; it does not define its own.

A data-validation failure resolves through **three distinct vocabularies, which are not the same
field**: the reason code (`validate.py`) → the §9.2 data status → the §11 lifecycle state
`DATA_BLOCKED` → the research_state `INCONCLUSIVE` (NI-3 §1.2 maps `DATA_BLOCKED or UNRESOLVED` →
`INCONCLUSIVE`). It never resolves to a silent absence of a pattern, and never to a false negative
recorded as a true one.

Two reason codes the owner's list requires do not exist in `validate.py` today — "insufficient
history" and a missing-OHLC-field rule (it checks `NONPOSITIVE_PRICE` and `NEGATIVE_VOLUME`, not a
missing field). See §39.16.

### 39.4 Pivots and the look-ahead rule

All geometric families use one pivot engine. A pivot that requires `N` future bars to confirm is not
knowable until those bars have closed, so:

```text
pivot_confirmed_at = pivot_bar + right_bars
```

Every pivot therefore stores **both** the bar it occurred on and the bar it became knowable at. This
is the single most important control in the whole engine: without it, a backtest silently uses a
pivot the market had not yet revealed.

Implemented in `research/charting/swings.py` — `Pivot` carries `pivot_index`/`pivot_date` and
`confirmed_index`/`confirmed_date`, and `swings_as_of(bars, t)` slices the frame **before** detecting
rather than filtering afterwards, so `confirmed_index <= t` holds by construction. Window values
(`swing_left_bars`, `swing_right_bars`) and the tie rule are §10.2 / §30 and are not restated here.

### 39.5 The Pattern Registry — which families may be detected and alerted

`research/charting/pattern_registry.py` is the **single source of truth**. A family may produce a
production alert only when all four hold:

1. its detector is **registered**;
2. its detector version is **enabled** for the signal version;
3. the required OHLCV data is available;
4. its lifecycle state can be determined **without look-ahead**.

**Unsupported patterns MUST NOT generate alerts.** This is enforced in code, not by convention:
`pattern_registry.assert_alertable()` raises, and the signal contract's alert-identity function calls
it, so a disabled family cannot be given an alert key.

`enabled` means a detector exists, is frozen under the v1 configuration, and has historical
validation behind it. It does not mean a specification exists.

| Family | Detector | Geometry | Volume rule | v1 |
|---|---|---|---|---|
| Support / resistance | `SR-v1` | own | follow-through 1.0–4.0× | **ENABLED** |
| Rectangle | `RECT-v1` | own | follow-through 1.0–4.0× | **ENABLED** |
| Higher highs / higher lows | `STRUCTURE-v1` | own | follow-through 1.0–4.0× | **ENABLED** |
| Ascending triangle | `TRI-ASC-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Descending triangle | `TRI-DESC-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Symmetrical triangle | `TRI-SYM-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Rising wedge | `WEDGE-R-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Falling wedge | `WEDGE-F-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Ascending channel | `CHANNEL-ASC-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Descending channel | `CHANNEL-DESC-v1` | P-1 | breakout bar ≥ 1.5× | DISABLED |
| Bull flag | `FLAG-BULL-v1` | P-2 | breakout bar ≥ 1.5× | DISABLED |
| Bear flag | `FLAG-BEAR-v1` | P-2 | breakout bar ≥ 1.5× | DISABLED |
| Bull pennant | `PENNANT-BULL-v1` | P-2 | breakout bar ≥ 1.5× | DISABLED |
| Bear pennant | `PENNANT-BEAR-v1` | P-2 | breakout bar ≥ 1.5× | DISABLED |
| Double bottom | `DB-v1` | own | breakout bar ≥ 1.5× | DISABLED |
| Double top | `DT-v1` | own | breakout bar ≥ 1.5× | DISABLED |
| Head & shoulders | `HS-v1` | own | breakout bar ≥ 1.5× | DISABLED |
| Inverse head & shoulders | `IHS-v1` | own | breakout bar ≥ 1.5× | DISABLED |
| Cup & handle | `CAH-v1` | own | breakout bar ≥ 1.5× | DISABLED |

The volume rule is a **registry property, not a global**. The two rules must not be merged (#109,
#110): keeping the rule on the family is what stops the new-family threshold being applied to a
frozen family, which would silently change frozen v1 behaviour.

### 39.6 Where each family's predicates live

| Family group | Formation and geometry | Tolerances | Breakout / failure |
|---|---|---|---|
| Support/resistance, Rectangle, HH/HL | §13.1–§13.3 | §30.1 (ATR-normalised) | §12.2–§12.5, §17 |
| Triangles, wedges, channels | **NI-3 §2** (P-1 engine, G1–G13) | NI-3 §2 + §37.7 | NI-3 §1.3 |
| Flags, pennants | **NI-3 §3** (P-2, pole + shape, F1–F8) | NI-3 §3 | NI-3 §1.3 |
| Double bottom / top | **NI-3 §4 / §5** (B1–B5, P1–P5) | NI-3 §4/§5 | NI-3 §1.3 |
| Head & shoulders, inverse H&S | **NI-3 §6 / §6b** (H1–H5, I1–I5) | NI-3 §6/§6b | NI-3 §1.3 |
| Cup & handle | **NI-3 §7** (C1–C17) | NI-3 §7 | NI-3 §1.3 |
| Shared parameters for all new families | **NI-3 §1.7** (S1–S10) | — | — |

Lifecycle states and the `research_state` mapping are §11 and NI-3 §1.2; readiness is NI-3 S9 (1%).

### 39.7 The three indicator classes

The distinction that makes historical validation possible — and the one this section exists to fix —
is that **an indicator either defines a pattern or it does not**.

| Class | Role | May it create or destroy a pattern? |
|---|---|---|
| **A — Pattern geometry** | swing high/low, ATR-normalised tolerance, trendline slope, convergence, parallelism, pivot relationships, price similarity, duration | **Yes.** These *are* the definition. |
| **B — Breakout confirmation** | close beyond trigger, volume / relative volume, breakout magnitude, ATR-normalised breakout distance, retest | **No.** They decide whether a detected structure has broken, not whether it exists. |
| **C — Context confirmation** | ADX, RSI, EMA, MACD, relative strength, market and sector trend | **No.** Evidence only, consumed by the signal evaluator. |

> **An ascending triangle exists because of its price geometry. It does not stop being an ascending
> triangle because RSI is 48.**

A Class C indicator must never appear in a detection predicate. Making one a gate produces an
overfitted detector whose definition is "triangle + RSI + MACD + ADX + EMA + volume", and makes it
impossible to measure the incremental value of any single confirmation input.

**Class C is new, unfrozen scope.** NI-3 gates on ATR(14) and 20-session average volume and contains
no ADX, RSI, EMA, MACD or relative strength anywhere. The Class C layer below therefore cannot be
sourced from NI-3 and is not covered by fingerprint `de86626c…`; it requires its own pre-registration
before any of it is allowed to weight a signal.

### 39.8 Matrix 1 — Class A geometry indicators by family

✅ = required to detect the pattern. — = not used in detection.

| Family | Swing | ATR | Slope | Convergence | Parallelism |
|---|---|---|---|---|---|
| Support / resistance | ✅ | ✅ | — | — | — |
| Rectangle | ✅ | ✅ | ✅ | — | — |
| Higher highs / higher lows | ✅ | ✅ | — | — | — |
| Ascending triangle | ✅ | ✅ | ✅ | ✅ | — |
| Descending triangle | ✅ | ✅ | ✅ | ✅ | — |
| Symmetrical triangle | ✅ | ✅ | ✅ | ✅ | — |
| Rising wedge | ✅ | ✅ | ✅ | ✅ | — |
| Falling wedge | ✅ | ✅ | ✅ | ✅ | — |
| Ascending channel | ✅ | ✅ | ✅ | — | ✅ |
| Descending channel | ✅ | ✅ | ✅ | — | ✅ |
| Bull flag | ✅ | ✅ | ✅ | — | ✅ |
| Bear flag | ✅ | ✅ | ✅ | — | ✅ |
| Bull pennant | ✅ | ✅ | ✅ | ✅ | — |
| Bear pennant | ✅ | ✅ | ✅ | ✅ | — |
| Double bottom | ✅ | ✅ | — | — | — |
| Double top | ✅ | ✅ | — | — | — |
| Head & shoulders | ✅ | ✅ | ✅ | — | — |
| Inverse head & shoulders | ✅ | ✅ | ✅ | — | — |
| Cup & handle | ✅ | ✅ | — | — | — |

Notes on the columns:

- **Slope** for H&S and inverse H&S is the **neckline** slope only: NI-3 §6/§6b allow a sloping
  neckline whose live value comes from `trendline_value_at`. It is not a boundary-fitting slope.
- **Flags and pennants** additionally require an **impulse (pole) measure** — NI-3 §3 F1/F2. A
  downward channel is not a bull flag without the pole that precedes it.
- **Slope must be normalised**, not raw price-per-bar, or the same rule behaves differently across
  price levels — but the two family groups normalise **differently, and must not be harmonised**:
  the three frozen families use the ATR drift test `boundary_drift_atr = |slope| × L / ATR`
  (§30.1, `geometry.boundary_drift`, flat ≤ 0.50 / sloped ≥ 0.75); the P-1 families use NI-3 G4, a
  **percentage** — flat if the fitted value changes by ≤ 1.5% of its starting value, one threshold
  with no gap (§38.18: "the owner's percentage rules decide flatness"). Building the P-1 engine on
  the ATR rule produces a detector that cannot reproduce fingerprint `de86626c…`. Every detection
  therefore stores `flatness_test = ATR_DRIFT | PCT_DRIFT`.
- **Convergence and parallelism are one measurement, not two.** NI-3 §2 computes a single
  `w = width at the last pivot / width at the first pivot` and classifies it against three bands —
  converging (G5 ≤ 0.70), expanding (G6 ≥ 1.43), parallel (G7 0.85–1.15). The two columns above are
  a reading aid for which band a family must land in; a P-1 detector computes `w` once for every
  shape. Note also that a flag body may be a **converging** falling wedge as well as a parallel
  channel (NI-3 §3), so the flag rows are not parallel-only.
- Family-specific similarity tolerances (peak/trough similarity, shoulder similarity, rim
  similarity) are geometry too; their values live in NI-3 §4–§7 and are not repeated here.

### 39.9 Matrix 2 — Class B and C confirmation indicators by family

**Class B (volume) is a gate, not advice.** NI-3 §1.3 states it as an `iff`:

```text
CONFIRMED_BREAKOUT  iff  BREAKOUT_CANDIDATE and breakout-bar volume >= 1.5 x 20-session average
```

So volume is **Required for every one of the sixteen new families** — but "required" names a
different transition in each regime, which is why a single Required/Recommended column cannot carry
it. The regime, not this section, decides:

| Regime | Breakout price test | Volume rule, and the transition it gates | Failure test |
|---|---|---|---|
| The three frozen families | close beyond level ± 0.25 × ATR (§12.2, §12.3; a wick-only breach is `BREAKOUT_ATTEMPT`) → `PRICE_CONFIRMED` | follow-through bar relative volume 1.00–4.00× (§30.1) → `VOLUME_CONFIRMED`. It does **not** gate `PRICE_CONFIRMED` — §10.2 sets `require_volume_confirmation: false` | close back through the level ∓ 0.25 × ATR within 5 bars (§17, §30.1) |
| The sixteen new families | close beyond `level(t)` × (1 ± 0.5%) (NI-3 S5) → `BREAKOUT_CANDIDATE` | breakout-bar volume ≥ 1.5 × 20-session average (NI-3 S8) → `CONFIRMED_BREAKOUT` | close back through `level(t)` × (1 ∓ 0.5%) (S6) within 5 bars (S7) |

The per-family rule is read from `pattern_registry.volume_rule()`, never authored here. The raw ratio
is stored whether it passes or fails (#109, #110, NI-3 §1.6).

**Class C is evidence only, and none of it is frozen.** The shape rule below is checkable by eye and
by test:

> **No cell in a Class C column may ever read Required.** If one does, the pattern definition has
> changed and NI-3 must be re-minted at v1.1.

`C` = Recommended (stored as evidence, may weight a signal once pre-registered) · `O` = Optional ·
`†` = the input does not exist in code today (§39.10).

| Family | RSI(14) | ADX(14)† | EMA stack | RS vs index | RS vs sector† | MACD |
|---|---|---|---|---|---|---|
| Support / resistance | O | O† | O | O | O† | O |
| Rectangle | O | C† | O | O | O† | O |
| Higher highs / higher lows | O | C† | C | C | C† | O |
| Ascending triangle | O | C† | C | C | C† | O |
| Descending triangle | O | C† | C | C | C† | O |
| Symmetrical triangle | O | C† | O | O | O† | O |
| Rising wedge | C | C† | O | C | O† | C |
| Falling wedge | C | C† | O | C | O† | C |
| Ascending channel | O | C† | C | C | C† | O |
| Descending channel | O | C† | C | C | C† | O |
| Bull flag | O | C† | C | C | C† | O |
| Bear flag | O | C† | C | C | C† | O |
| Bull pennant | O | C† | C | C | C† | O |
| Bear pennant | O | C† | C | C | C† | O |
| Double bottom | C | C† | O | C | O† | C |
| Double top | C | C† | O | C | O† | C |
| Head & shoulders | C | C† | O | C | O† | C |
| Inverse head & shoulders | C | C† | O | C | O† | C |
| Cup & handle | O | C† | C | C | C† | O |

**Why these ratings, so they do not read as arbitrary.** Continuation families (triangles, channels,
flags, pennants, cup & handle, HH/HL) take trend-participation context — ADX, the EMA stack,
relative strength — as Recommended and momentum as Optional. Reversal families (wedges, double
top/bottom, H&S, inverse H&S) take momentum divergence — RSI, MACD — plus prior-trend strength as
Recommended, and the EMA stack as Optional. Range families (support/resistance, rectangle) take
nothing above Optional, except ADX on the rectangle where a low reading corroborates a genuine range.

**Every Class C cell above is PROPOSED on 2026-09-23. None is frozen**, none is covered by
fingerprint `de86626c…`, and none may weight a signal before its own pre-registration. Relative
strength is split into two columns because §8.5 and §34.4 both require the sector comparison and only
the index one exists.

### 39.10 Availability — what these matrices need versus what exists

Stated bluntly, because a matrix that assumes unavailable inputs is a plan to discover the gap during
implementation.

| Input | Shipped? | Where it is today |
|---|---|---|
| Swing high / low with confirmation bar | yes | `research/charting/swings.py` — `find_swings`, `swings_as_of` |
| ATR(14) | yes | `research/charting/series.py: atr`; catalogue preset `atr_14` |
| Fitted line (slope + intercept) | **yes, 2026-09-23** | `geometry.fit_line() -> Line(slope, intercept)`. Its slope is pinned by test to equal `ols_slope` exactly, so the two cannot drift |
| Width ratio `w` (convergence **and** parallelism) | **yes, 2026-09-23** | `geometry.width_ratio()` measured at the first and last **pivot**, then `geometry.classify_pair()`. Convergence and parallelism are two bands of one measurement, not two primitives |
| G4 percentage flatness | **yes, 2026-09-23** | `geometry.line_direction()`. Deliberately not `boundary_drift`, which is the P0 ATR test — a hard CI gate (`test_F2_*`) proves the two stay distinguishable |
| `trendline_value_at()` | **yes, 2026-09-23** | `geometry.trendline_value_at(line, x)`. This is what unblocks the sloped neckline, so head & shoulders and inverse head & shoulders no longer wait on the P-1 engine |
| Volume / relative volume (20) | yes | `series.relative_volume`; catalogue `relative_volume_20` |
| RSI(14), EMA, MACD | yes | `series.py`; catalogue presets |
| **ADX(14)** | **not served** | exists only as the private `regime._adx_series`; absent from the chart indicator catalogue |
| **Relative strength** | **partial, not served** | `regime.relative_strength` is vs **NIFTY 500 only** (windows 5/20/50/100). There is **no stock-vs-sector relative strength**; absent from the catalogue |

**Wave A landed on 2026-09-23** and closed the geometry half of this table. The P-1 family is no
longer blocked on primitives; what remains is the detector itself (§39.15). The frozen v1
`config_hash` is unchanged at `05167d3a…`, because the new thresholds are read from the NI-3
configuration (`research/charting/ni3_config.py`, which verifies fingerprint `de86626c…` on load)
and nothing was added to `CONFIG`.

One consequence still stands:

- **The Class C layer cannot be delivered as specified today.** ADX and relative strength are the two
  most-cited Class C inputs in §39.9 and neither is served; stock-vs-sector relative strength does not
  exist at all. Promoting them is a separate, costed piece of work.

### 39.11 Evidence, not quality scores

A pattern's quality is recorded as **the facts that produced it**, not as a number:

```text
{
  "touches": 4,
  "pivot_count": 7,
  "duration_bars": 38,
  "boundary_error_pct": 0.72,
  "convergence_ratio": 0.61,
  "volume_contraction_pct": 28.4
}
```

rather than `Pattern Quality: 18/20`. A component score with no formula, inputs, thresholds,
normalisation, version and missing-data behaviour is not measurable and cannot be validated; it only
looks quantitative. Historical validation then determines which characteristics actually matter,
instead of the weighting asserting it in advance.

This is the same decision as §38.19.4 position 2, which removed the 0–100 headline signal score, and
it extends to the component scores beneath it. §16's pattern-quality model and
`geometry.level_strength` remain descriptive by construction (`is_probability = False`) and are never
presented as a probability.

### 39.12 Detector output contract

The record a detector returns is **not a new schema**. It is the §37.8 common pattern schema and the
shipped `PatternSnapshot` (`research/charting/SNAPSHOT_SCHEMA.md`, §23.1), which already carry
`pattern_id`, `pattern_type`, `direction`, `population`, `status`, `stage`, `levels`, `pivots`,
`components`, `rules`, `events` and `scores`. §39 adds no field names of its own and renames nothing;
the illustrative JSON in the owner's specification is a sketch, not the contract.

What §39 does own is the **delta** — fields a detector must also carry that the current record does
not make explicit:

| Field | Why |
|---|---|
| `detector_version`, `config_version` | §39.2 D3. A record that cannot name its detector cannot be reproduced |
| `config_fingerprint` | NI-3: "the detector code must reproduce this fingerprint … or it is not this table" |
| `flatness_test` | `ATR_DRIFT` or `PCT_DRIFT` — which convention this family used (§39.8) |
| `first_known_date` | the earliest date the structure could have been known (NI-3 §1.1; the §38.15 "Known" marker) |
| `reason_code` | for every rejection and every invalidation (§39.2 D8) |
| `scale` | which swing scale produced it, once the large-swing layer lands (NI-3 §8) |

And the half that is actually enforceable — **fields that must never appear on a detector record**:

```text
headline score or confidence      entry price
probability of success            target price
tradability verdict               stop as a recommendation
alert-worthiness flag             position quantity or R-multiple
historical hit rate or comparables
```

Each of these is a downstream object: setup values belong to the signal evaluator behind the owner
allowlist (§38.19.4 position 3), comparables belong to research (§40 of the Paper PRD), and there is
no headline score anywhere (§38.19.4 position 2). A detector that emits one has crossed the boundary
in §39.13.

Indicator values carried on the record follow the §8.7 indicator contract (`calculation_version`,
`warmup_period`, `point_in_time_validated`, `missing_data_policy`).

### 39.13 The architectural invariant

> A pattern detector may say only whether the historical price structure satisfies its formal
> definition. It must not decide whether the pattern is bullish, profitable, high-probability,
> tradeable, or worth alerting on.

```text
OHLCV → PATTERN DETECTOR → PATTERN + GEOMETRY + EVIDENCE → LIFECYCLE ENGINE
      → SIGNAL EVALUATOR → VOLUME / INDICATOR / RS CONFIRMATION
      → ALERT → PAPER TRADE → HISTORICAL OUTCOME
```

The separation is what makes it possible to test whether a particular pattern *plus* a particular
confirmation actually has an edge, instead of baking an assumption about profitability into the
detector and then measuring it with itself.

**The second boundary — detection versus lifecycle** (owner, 2026-09-23):

> A pattern detector determines structure from confirmed pivots; the replay/lifecycle engine
> determines what happens subsequently to an already-established pattern.

These answer different questions and must not be merged:

| | Question | Answer at bar `t` |
|---|---|---|
| Snapshot detection | "What pattern exists at `t`, using pivots confirmed by `t`?" | a structure, or nothing |
| Replay lifecycle | "What happened to a pattern that was already established?" | a state transition |

The case that forces the distinction: a bar that breaks through a trough may be the same bar that
**displaces that trough as a swing low**. The pair then never was a structure as of `t`, so the
detector must report **no pattern** — not an invalidated one. Reporting INVALIDATED would claim a
structure that was never established. Only when the trough survives as a confirmed pivot is the
break a lifecycle transition.

Getting this wrong produces subtle false invalidations that are very hard to find later, because
each one looks locally reasonable. It is locked by the certification fixtures in
`research/charting/tests/test_patterns_ni3_double.py` (`test_CERT_*`): a break through an
unconfirmed trough must yield no pattern; a break through an established one must invalidate.

### 39.14 Tolerance convention

Already resolved; recorded here so it is not re-litigated per family:

- **P0 families** (support/resistance, rectangle, HH/HL) use the **ATR-normalised** tolerances of
  §30.1 — §35.1 resolves every percentage-versus-ATR clash with "§30.1 stands".
- **The sixteen new families** use the owner's **percentage** rules — §37.7: "these percentage rules
  apply to the new families; the §30.1 ATR rules stay for the P0 families (owner-confirmed, baseline
  v1.1)", with NI-3 as the frozen table of the values.

Where a family is validated, the research record stores `breakout_level`,
`breakout_threshold_pct`, `breakout_threshold_atr` and `breakout_volume_ratio` (§37.7), so the
stability of the two conventions can be compared across volatility regimes rather than assumed.

### 39.15 Prerequisites and build order

**Prerequisites — delivered 2026-09-23 (Wave A).** The dependency graph is one chain, not four
independent items:

```text
fit_line()  ->  trendline_value_at()  ->  width_ratio() at pivots  ->  classify_pair()
```

`convergence_ratio` and "parallelism" are not separate primitives: they are two bands of the single
ratio `w`, which is why the earlier four-item blocker list overstated the work. All of it is in
`research/charting/geometry.py`, with thresholds read from `ni3_config.py`.

**Build order**, cheapest structural value first:

| Wave | Families | State |
|---|---|---|
| 0 | Support/resistance, Rectangle, HH/HL | **done** |
| A | `fit_line`, `trendline_value_at`, `width_ratio`, `line_direction`, `classify_pair` | **done 2026-09-23** |
| 1 | Ascending / descending / symmetrical triangle, rising / falling wedge, ascending / descending channel | unblocked; needs the NI-3 §2 seven-step detector and its 9 fixtures |
| 2 | Bull / bear flag, bull / bear pennant | blocked on wave 1 (P-2 bodies are P-1 shapes) |
| B | Head & shoulders, inverse head & shoulders | unblocked by `trendline_value_at` alone (sloped neckline, NI-3 §6b) — they do **not** wait for the P-1 detector |
| 3 | Double top, double bottom, cup & handle | never blocked; needs only swing + ATR + similarity tolerances |

Wave 3 is not blocked by the fitted-line work, so it can proceed in parallel with wave 1 if the
owner prefers pattern breadth earlier than triangle support.

### 39.16 Conflicts with frozen sources, and what §39 does not change

§39 resolves nothing by itself. Where two frozen sources disagree, the conflict is recorded here with
its owner, because a section that quietly picks one would recreate the drift it exists to prevent.

| # | Conflict | What each source says | Status |
|---|---|---|---|
| C-1 | Flatness test | §30.1 ATR drift (flat ≤ 0.50, sloped ≥ 0.75, with an undocumented middle band) vs NI-3 G4 percentage (≤ 1.5%, one threshold, no gap) | **Already decided, split by family** (§37.7, §38.18). Do not harmonise — harmonising re-mints NI-3 v1.1 and changes frozen v1. `flatness_test` records which was used |
| C-2 | Convergence window | `geometry.convergence_ratio` is documented over the first and last **bar**; NI-3 G5 measures width at the first and last **pivot** | NI-3 G5 governs the new families. The existing parameter naming is misleading — **documentation defect, no code change** |
| C-3 | Expanding / parallel bands | §30.1 has no expanding or parallel band at all; NI-3 has G6 1.43 and G7 0.85–1.15 | Not a conflict but a **gap**: parallelism is net-new and has no §30.1 counterpart |
| **C-4** | **Double-bottom tolerance** | **§13.6 says `abs(T2 − T1) <= 1.0 × ATR` and a 5-bar minimum trough separation. NI-3 B1/B2 say 10 sessions and 3% of price, both OWNER, re-confirmed #110** | **NI-3 governs this family. §13.6's values are superseded for double bottom/top and must not be used.** §35.1's "5-bar separation applies where a pattern rule states it, e.g. §13.6 troughs" now reads against NI-3's 10 and needs the owner's word |
| C-5 | Breakout / failure buffer | §12.2 ± 0.25 × ATR vs NI-3 S5/S6 0.5% | Already resolved (§37.7, §38.18); NI-3 §1.6 stores `breakout_threshold_atr` alongside so the two can be compared |
| C-6 | Volume rule | §12.4 bands and §30.1 follow-through 1.00–4.00× vs NI-3 S8 ≥ 1.5× | Already resolved (#109, #110) and encoded as a **registry property**. Matrix 2's Class B rows are read from the registry, never authored here |
| C-7 | Maximum pattern length | §10.2 `maximum_pattern_length: 120` vs NI-3 C6 cup up to 260 and L2 40/260 | Scoped overrides, not a conflict — but §10.2 read alone gives the wrong answer for cup & handle |
| C-8 | Class C scope | NI-3 requires only ATR(14) and 20-session volume; it names no ADX/RSI/EMA/MACD/RS anywhere | Class C is **new, unfrozen scope**, outside fingerprint `de86626c…`. Promoting any Class C input to a gate requires NI-3 v1.1 and a study-plan amendment |
| C-9 | Class C "never creates the pattern" vs §34.5 | §34.5's Early Pattern Score already weights momentum/relative strength 15% and market/sector context 10% | Both hold, with the line drawn precisely: Class C may feed §34.5 early scores and §16 components — research and UI objects — but **never a §11 lifecycle transition**. §34.5 is not repealed |
| C-10 | Evidence vs scores | §16 Pattern Quality Model and `geometry.level_strength`'s frozen weights vs "evidence, not scores" | Three tiers: the detector record carries raw evidence only; `level_strength` survives as the one frozen composite because it describes a *level*, is `is_probability=False`, and stores its components separately; §16 and §34.5 composites are research objects (§38.19.4 position 2) |
| C-11 | Evidence field units | NI-3 G3 is `pivot_line_residual_max_atr` 0.25 **ATR**; F8/C16 are `1.0×` ratios. §39.11's `boundary_error_pct` and `volume_contraction_pct` are **percentages** | The frozen-unit value is the gating field; the percentage is a derived display field and is never tested against. `convergence_ratio` needs no translation — it is already the frozen name and number |
| C-13 | Double-extreme adjacency | NI-3 §4 says "troughs at least B1 apart and within B2 of each other" without saying the two must be **adjacent** extremes | Read literally, a window with six lows emits pairs whose troughs have four other troughs between them — 320 detections across 12 symbols. The detector requires consecutive same-kind pivots, giving 117 across all 50 (1.2 per family per symbol, in line with the frozen families). **Open question for the owner**; the check is one line in `patterns_ni3.py` and is commented with how to revert |
| C-12 | Missing reason codes | `validate.py` has no "insufficient history" rule and no missing-OHLC-field rule | Genuinely absent. Recorded, not fixed — `RULE_IDS` is a frozen list and extending it is an owner decision |

**What §39 does not change.** NI-3 v1.0 (`de86626c…`), the frozen v1 detector configuration
(`05167d3ae57f…`), study plan v1, §30.1's approved predicates, and the §38.19 Amendment E positions
all stand exactly as they are. §39 adds no number of its own; every value above is a quotation with
its source named.
