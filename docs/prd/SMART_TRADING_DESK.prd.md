# Product Requirements Document (PRD)
## Nivesh Copilot — AI Smart Trading Desk

**Document version:** 1.0  
**Status:** Proposed — Ready for product and engineering review  
**Product:** Nivesh Copilot / Nivesh.ai  
**Platform:** Responsive web application, mobile-first  
**Primary market:** Indian equities and equity derivatives  
**Primary users:** Retail positional traders, active investors, professional traders and research analysts  
**Product category:** AI-powered market intelligence, stock discovery, technical analysis and portfolio risk analytics

---

# 1. Executive Summary

## 1.1 Product vision

Build an AI-powered Smart Trading Desk that unifies market intelligence, stock discovery, chart analysis, corporate events, portfolio analytics and risk management in a single workspace.

The product should help users answer six questions:

1. What is happening in the market?
2. Which stocks have potentially interesting opportunities?
3. What evidence supports or contradicts each opportunity?
4. What corporate events or news could affect the stock?
5. What are the potential entry, exit and downside scenarios?
6. How do these opportunities affect my existing portfolio risk?

Nivesh should combine quantitative models with AI-generated explanations, historical evidence and transparent uncertainty.

## 1.2 Product objectives

- Reduce the time required to discover and investigate market opportunities.
- Identify potentially significant stock movements using quantitative models.
- Detect and validate breakouts, momentum, pullbacks and chart patterns.
- Connect corporate announcements and market events with affected stocks and sectors.
- Provide a consolidated, read-only view of supported broker holdings and positions.
- Calculate hypothetical entry, stop-loss, target and position-sizing scenarios.
- Measure prediction quality through historical validation and paper trading.
- Make AI reasoning traceable to source data, calculations and timestamps.

## 1.3 Non-goals

The initial product will not:

- Place, modify or cancel live orders.
- Automatically execute trading strategies.
- Manage broker funds or transfer money.
- Guarantee stock returns or movement probabilities.
- Treat an AI-generated explanation as a substitute for validated quantitative evidence.
- Present illustrative data as live market information.
- Infer profitability solely from a stock's probability of making a large move.

## 1.4 Product principles

1. **Evidence before explanation:** Quantitative calculations and source evidence must exist before AI generates a narrative.
2. **Risk before reward:** Every actionable-looking opportunity must expose its downside and invalidation conditions.
3. **Probability is not certainty:** Predictions must include horizon, calibration, validation period and limitations.
4. **No hidden look-ahead:** Historical testing must use only information available at the simulated decision time.
5. **Read-only by design:** Broker integrations are restricted to permitted account, portfolio and position data.
6. **Progressive disclosure:** Simple summaries by default; detailed analytics on demand.
7. **Source transparency:** Market events, announcements and AI explanations must be traceable.

---

# 2. Target Users and Use Cases

## 2.1 User personas

### Persona A — Retail positional trader

**Needs**
- Identify opportunities for holding periods of one to several trading sessions.
- Discover momentum stocks and confirmed breakouts.
- Understand entry scenarios, stop-loss levels and potential targets.
- Avoid illiquid stocks and excessive downside risk.

**Success outcome:** Faster, more disciplined research without having to use multiple disconnected tools.

### Persona B — Active market participant

**Needs**
- Monitor market breadth, sector rotation and volatility.
- Track intraday market developments and corporate announcements.
- Compare stock movement probabilities and technical confirmations.
- Maintain a watchlist of developing opportunities.

**Success outcome:** Quickly identify which developments deserve further attention.

### Persona C — Professional trader or research analyst

**Needs**
- Inspect underlying indicator values and raw evidence.
- Validate technical patterns using historical data.
- Review F&O positioning, cash-market price action and derivatives activity.
- Examine model performance, signal quality and false positives.

**Success outcome:** Reproducible analysis with access to detailed evidence and historical performance.

### Persona D — Investor managing multiple broker accounts

**Needs**
- Consolidate holdings and available position data.
- Understand sector, stock and volatility concentration.
- Evaluate a potential opportunity in the context of existing holdings.
- Track hypothetical risk without submitting orders.

**Success outcome:** Better-informed portfolio decisions based on a consolidated view.

## 2.2 Primary user journeys

**Journey 1: Discover an opportunity**

Overview → AI Scanner → Stock Detail → Chart Confirmation → Event Analysis → Risk Scenario → Watchlist or Paper Trade.

**Journey 2: Investigate a market event**

Market Intelligence → Event Detail → Affected Stocks → Technical Confirmation → Historical Event Analysis.

**Journey 3: Evaluate an F&O setup**

Market Pulse → F&O Scanner → Futures Open Interest Analysis → 15-minute Price and OI Confirmation → Cash Chart Confirmation → Risk Scenario.

**Journey 4: Assess portfolio risk**

Connect supported broker read-only account → Consolidated Portfolio → Risk Dashboard → Concentration Analysis → Scenario Analysis.

**Journey 5: Ask the AI Copilot**

Ask a market question → Retrieve relevant market data and sources → Generate an evidence-backed explanation → Open the underlying chart, event or risk analysis.

---

# 3. Product Information Architecture

## 3.1 Primary navigation

The desktop navigation contains:

1. Overview
2. AI Scanner
3. Market Intelligence
4. Chart Analysis
5. Portfolio & Risk
6. More

The More section contains:
- AI Copilot
- Watchlists
- Saved analyses
- Paper Trading
- Learning and methodology
- Settings and integrations

The mobile experience uses a persistent bottom navigation bar with the most frequently used destinations. Secondary screens should remain accessible through contextual actions and More.

## 3.2 Shared application components

Every primary screen must reuse the following components:

- Application header and global search
- Market status and last-updated timestamp
- Watchlist action
- Notification centre
- Stock and sector search
- Date and timeframe selector
- Filter and sort controls
- Data freshness indicator
- AI explanation panel
- Source citations and evidence drawer
- Risk and methodology disclosure
- Empty, loading, error and stale-data states

## 3.3 Responsive layout

**Mobile**
- Single-column card layout.
- Compact index summary.
- Horizontally scrollable filters where appropriate.
- Bottom navigation.
- Charts optimized for touch interaction.
- Tables transformed into compact stock cards where necessary.

**Tablet**
- Two-column dashboard.
- Expandable analysis panels.
- Condensed table layouts.

**Desktop**
- Two- or three-column dashboard.
- Persistent market context.
- Larger stock tables and chart workspace.
- Optional side panel for events, AI explanations and portfolio context.

The design should remain visually consistent with Nivesh Copilot's dark navy, cyan/blue, green-positive and red-negative theme. A light theme may be supported through the existing application design system.

---

# 4. Functional Requirements

Priority definitions:

- **P0:** Required for initial production MVP.
- **P1:** Important follow-up capability.
- **P2:** Advanced or later-phase capability.

## Module 1 — Smart Trading Desk Overview

### 4.1 Purpose

Provide a single-screen summary of market conditions, potentially interesting opportunities, relevant events and portfolio risks.

### 4.2 Screen layout

1. Application header and global search.
2. Index summary cards.
3. Market breadth and market status.
4. AI Market Pulse.
5. Sector performance heatmap.
6. Top AI Opportunities.
7. Key Market Events.
8. Portfolio Snapshot.
9. Risk Dashboard.
10. AI Copilot entry point.

### 4.3 Functional requirements

**OV-001 — Index cards (P0)**

Display configured benchmark indices, including:
- Nifty 50
- Nifty Bank
- Sensex
- India VIX

Fields:
- Latest price
- Absolute change
- Percentage change
- Intraday sparkline
- Last-updated time

Data must be timestamped. If delayed or unavailable, the UI must not imply that the value is live.

**OV-002 — Market breadth (P0)**

Display:
- Advancing stocks
- Declining stocks
- Unchanged stocks
- Breadth ratio
- Optional advance/decline trend

The eligible universe must be stated. Index constituents, all listed equities and the platform's liquid-stock universe must not be mixed without explanation.

**OV-003 — AI Market Pulse (P0)**

Generate a market summary containing:
- Market regime classification
- Supporting quantitative evidence
- Sector leadership
- Important market events
- Potential risks
- Conditions that could invalidate the assessment

Supported regimes:
- Bullish
- Bearish
- Sideways
- High volatility
- Mixed/uncertain

The regime must come from a defined quantitative classification method. The LLM may explain the result but must not silently invent the classification.

**OV-004 — Sector heatmap (P0)**

Show configured sectors ranked by percentage change or another explicitly selected metric.

Capabilities:
- Change timeframe
- Sort by performance
- Filter by sector
- Open sector constituents
- Show market breadth within a sector

**OV-005 — Top AI Opportunities (P0)**

Display the top five to ten eligible stocks with:
- Stock symbol and company name
- Latest available price and timestamp
- Model score or calibrated probability, with its exact meaning
- Prediction horizon
- Technical setup
- Supporting evidence
- Contradictory signals
- Liquidity status
- Risk classification
- Link to detailed analysis

**OV-006 — Key Market Events (P0)**

Show significant announcements, earnings, regulatory developments, deals and market news.

Each event must include its source, publication time, affected instruments and an indication of whether the event has been verified.

**OV-007 — Portfolio snapshot (P1)**

Show:
- Consolidated portfolio value
- Unrealized and realized P&L, where available
- Asset allocation
- Top holdings
- Concentration indicators
- Data synchronization status

**OV-008 — Risk summary (P0)**

Show:
- Portfolio concentration
- Volatility category
- Liquidity assessment
- Sector concentration
- Missing or stale portfolio data

If the user has not connected a broker or uploaded a portfolio, show a useful empty state instead of fabricated holdings.

### 4.4 Acceptance criteria

- All market cards display timestamps and data status.
- Every stock opportunity opens a detailed analysis view.
- Event cards link to the source and affected stocks.
- Portfolio figures are derived from imported or connected account data.
- Missing data is clearly distinguished from zero.
- The dashboard remains usable on a typical mobile viewport without horizontal page scrolling.

---

## Module 2 — AI Opportunity Scanner

### 5.1 Purpose

Discover and rank eligible stocks based on movement probabilities, technical setups, liquidity, market context and risk.

### 5.2 Scanner categories

- All opportunities
- Breakouts
- Momentum
- Pullback continuation
- Reversal candidates
- Unusual volume
- Results-day momentum
- F&O candidates
- User watchlist

Additional filters:
- Sector
- Market capitalization
- Price range
- Liquidity
- Relative volume
- Volatility
- Prediction horizon
- Model probability
- Risk category
- Instrument eligibility

### 5.3 Stock table fields

| Field | Description |
|---|---|
| Symbol | Exchange instrument identifier |
| Price | Latest eligible price |
| Change | Absolute and percentage change |
| AI probability | Probability for a precisely defined outcome |
| Model rank | Relative position within the eligible universe |
| Pattern | Detected technical setup |
| Confirmation | Evidence that supports the setup |
| Catalyst | Relevant event or news, if available |
| Liquidity | Turnover and tradability classification |
| Risk | Estimated risk category |
| Action | Open analysis, watchlist or paper trade |

The interface must distinguish a model score, a ranking percentile and a calibrated probability. These are not interchangeable.

### 5.4 Prediction model integration

Nivesh's existing stock-movement model may be integrated as an initial signal source.

Known baseline model configuration:
- HistGradientBoostingClassifier
- `max_iter=150`
- `learning_rate=0.08`
- `max_leaf_nodes=31`
- `l2_regularization=1.0`
- `random_state=7`
- Monthly retraining on a growing window capped at 18 months
- Feature set based on technicals, fundamentals, ownership and results-related features

The current model and its performance limitations must be documented before production deployment.

**Important model limitation:** Prior evaluation identified substantial dependence on volatility features and gaps in stock-universe coverage. Therefore, the initial scanner must not assume that the model's ranking is a reliable estimate of profitability.

### 5.5 Prediction definitions

The platform must define separate prediction tasks:

**Task A — Large-move probability**

Estimate the probability that a stock reaches a specified upward price threshold within a specified horizon.

**Task B — Directional return**

Estimate expected return or the probability of a positive return after estimated costs over a defined holding period.

**Task C — Trade outcome**

Estimate the probability or expected value of a fully specified trade, including entry timing, exit rules, transaction costs and stop/target logic.

These tasks must have separate labels, validation reports and model versions.

A stock with a high probability of a large move may still be a poor trade if the move is predominantly downward, the entry is unfavorable or the stock is illiquid.

### 5.6 Signal confirmation rules

Technical setups must be generated using deterministic, testable rules.

Example breakout confirmation:
- Price exceeds a defined resistance level.
- Closing or intrabar confirmation meets the configured rule.
- Relative volume exceeds the configured threshold.
- Price and indicator timestamps are aligned.
- Liquidity and tradability gates pass.
- The setup is not invalidated by a gap, circuit condition or other configured constraint.

Thresholds must be configurable and versioned rather than hardcoded into UI components.

### 5.7 Opportunity detail

Every stock detail must contain:

1. Prediction definition and horizon.
2. Model score and calibration information.
3. Technical evidence.
4. Fundamental and ownership context, where available.
5. Corporate events and news.
6. Liquidity and tradability checks.
7. Hypothetical entry, stop and target scenarios.
8. Historical validation statistics.
9. Contradictory evidence.
10. Data freshness and missing inputs.

### 5.8 Acceptance criteria

- Users can filter and sort without losing selected criteria unexpectedly.
- Scanner results disclose the eligible universe and exclusion rules.
- Each prediction has an identifiable model version and evaluation period.
- Missing or unavailable data does not silently become a neutral value.
- A probability is displayed only when supported by an appropriate calibration process.
- Entry and target scenarios are explicitly hypothetical and are not transmitted to brokers.

---

## Module 3 — Market Intelligence

### 6.1 Purpose

Connect market events, corporate disclosures, news and bulk/block deals with the stocks and sectors they may affect.

### 6.2 Event categories

- Corporate announcements
- Quarterly results
- Earnings calls and guidance
- Order wins and contract announcements
- Mergers, acquisitions and corporate actions
- Promoter and ownership disclosures
- Bulk and block deals
- FII/DII activity
- Regulatory and judicial developments
- Sector news
- Macro-economic events
- Exchange notices and trading restrictions

### 6.3 Event feed

Each event must contain:
- Event ID
- Headline
- Source organization
- Source URL or document reference
- Publication timestamp
- Ingestion timestamp
- Event category
- Affected company or instruments
- Sector mapping
- Verification status
- Event importance
- Extracted facts
- AI-generated summary
- Potentially relevant historical context

### 6.4 Event processing pipeline

1. Ingest source records.
2. Normalize timestamps and identifiers.
3. Deduplicate repeated announcements.
4. Map the issuer to canonical stock and exchange identifiers.
5. Classify event type.
6. Extract factual information.
7. Associate relevant sectors and instruments.
8. Calculate deterministic relevance and materiality features.
9. Generate a source-grounded summary.
10. Publish the event with traceable provenance.

### 6.5 Event-to-stock impact

The product may show:
- Directly affected stock
- Related companies
- Potentially affected sectors
- Historical reactions to comparable events
- Current technical confirmation
- Conflicting or mitigating evidence

The system must not automatically label an event as bullish or bearish solely because an LLM considers the language positive or negative.

For example, a large order announcement may be relevant, but the stock's actual reaction also depends on valuation, contract margins, execution risk, prior expectations and market conditions.

### 6.6 Bulk and block deals

Required fields, where available:
- Stock
- Trade date
- Buyer and seller
- Quantity
- Deal price
- Percentage of outstanding shares, if available
- Market price around the event
- Source and publication timestamp

The UI must distinguish confirmed exchange disclosures from inferred institutional activity.

### 6.7 Alerts

Users may create alerts for:
- A selected stock's new material announcement
- A specified event category
- Unusual volume
- A stock entering a selected scanner filter
- A significant sector change
- A configured risk threshold

Alerts should be deduplicated and include the reason they were triggered.

### 6.8 Acceptance criteria

- Every material event has a traceable source.
- The system preserves both publication and ingestion times.
- Duplicate announcements are consolidated without discarding source records.
- Failed feeds are visible to administrators.
- Events are not presented as confirmed if source verification has failed.
- AI summaries distinguish sourced facts from interpretation.

---

## Module 4 — Chart Analysis

### 7.1 Purpose

Provide interactive technical analysis, early breakout detection, chart-pattern confirmation and historical validation.

### 7.2 Chart workspace

Required controls:
- Instrument search
- Exchange and instrument type
- Candlestick chart
- Timeframe selector
- Volume panel
- Indicator controls
- Drawing tools
- Pattern overlays
- Event markers
- Watchlist action
- Historical validation panel

Supported intervals should include daily, 60-minute, 30-minute, 15-minute and 5-minute charts when reliable underlying data is available. Additional intervals may be introduced according to feed coverage.

### 7.3 Technical indicators

Initial supported indicators:
- EMA 20, EMA 50 and EMA 200
- RSI
- ATR and ATR percentage
- VWAP where suitable intraday data exists
- MACD
- Relative volume
- Rate of change
- Relative strength versus a benchmark
- Volume moving average
- Support and resistance

Indicator values, lookback periods and calculation conventions must be documented and consistent across the backend, chart and backtest engine.

### 7.4 Pattern detection

Initial patterns:
- Horizontal resistance breakout
- Consolidation breakout
- Higher highs and higher lows
- Pullback continuation
- Moving-average crossover
- Double top and double bottom
- Cup-and-handle candidate
- Triangle and range compression
- Unusual-volume breakout
- Failed breakout

Patterns must have explicit definitions, minimum data requirements, detection timestamps and invalidation conditions.

### 7.5 Confirmation engine

A pattern should have a state:

- Candidate
- Awaiting confirmation
- Confirmed
- Invalidated
- Expired

A detected chart shape alone is insufficient for a confirmed signal.

The engine should combine:
- Price structure
- Volume
- Trend
- Relative strength
- Volatility
- Liquidity
- Market regime
- Relevant event context

The user must be able to inspect which criteria passed and failed.

### 7.6 Historical validation

The validation panel should display:
- Number of historical occurrences
- Hit rate under a defined outcome
- Average return
- Median return
- Maximum adverse excursion
- Maximum favorable excursion
- Holding period
- Transaction-cost assumptions
- Benchmark comparison
- Sample period
- Out-of-sample performance
- Confidence intervals where statistically appropriate

The system must define whether a hit means an intraday touch, a closing-price threshold or a realized trade outcome. These outcomes must not be combined into a single ambiguous hit rate.

### 7.7 No look-ahead bias

The validation engine must:
- Use only data available at the simulated decision timestamp.
- Avoid using the same candle's final high or low before that information would have been available.
- Respect order-of-events ambiguity when stop-loss and target prices occur within the same candle.
- Apply realistic entry timing and transaction costs.
- Use walk-forward or otherwise appropriately separated out-of-sample periods.
- Prevent future corporate events or revised data from leaking into historical features.

### 7.8 Acceptance criteria

- Indicators match the documented backend calculation.
- Patterns have reproducible definitions.
- Users can inspect the evidence for each confirmation.
- Historical results disclose assumptions and sample sizes.
- Backtest and live-signal calculations use consistent feature definitions.
- Incomplete intraday data is explicitly disclosed.

---

## Module 5 — Portfolio & Risk

### 8.1 Purpose

Provide a consolidated, read-only view of portfolio exposure and the risk of potential opportunities.

### 8.2 Portfolio ingestion

Supported methods:
- Read-only broker connections.
- CSV upload.
- XLS/XLSX upload using defined broker-specific templates.
- Manual portfolio entry as a fallback.

The import pipeline must validate:
- Symbol and exchange
- ISIN, where available
- Quantity
- Average cost
- Instrument type
- Broker account reference
- Currency
- Import timestamp

Duplicate positions, mismatched symbols and unsupported instruments must be flagged rather than silently merged.

### 8.3 Portfolio overview

Display:
- Total reported portfolio value
- Invested value, where derivable
- Realized and unrealized P&L, where supported
- Asset allocation
- Stock and sector concentration
- Top holdings
- Exposure by market capitalization
- Cash balance, if available
- Data freshness and reconciliation status

All totals must specify which accounts and instrument types are included.

### 8.4 Risk dashboard

Required dimensions:
- Single-stock concentration
- Sector concentration
- Correlated exposures
- Volatility
- Drawdown, where sufficient history exists
- Liquidity and estimated liquidation difficulty
- Gap risk
- Portfolio beta, where supported
- Missing price or position data

Risk categories must be supported by explicit rules or models. A green, amber or red label must have an accessible explanation.

### 8.5 Trade scenario calculator

Inputs:
- Reference entry price
- Stop-loss price
- Target price
- Available capital or user-defined risk budget
- Maximum allocation percentage
- Estimated costs
- Position-size constraints

Outputs:
- Per-share downside
- Per-share upside
- Reward-to-risk ratio
- Illustrative position size
- Gross exposure
- Estimated costs
- Potential loss at stop
- Potential profit at target

Basic formulas:

Risk per share = Entry price − Stop price, for a long position.

Reward per share = Target price − Entry price, for a long position.

Reward-to-risk ratio = Reward per share / Risk per share.

Illustrative quantity = Risk budget / Risk per share, subject to capital, liquidity and instrument constraints.

The calculator must validate the direction of all prices and prevent division by zero. Costs and slippage should be included in estimated net outcomes.

A stop price does not guarantee the realized exit price, particularly during gaps or illiquid trading.

### 8.6 Portfolio-aware opportunity analysis

For a potential stock opportunity, show:
- Existing exposure to the stock
- Sector exposure
- Related holdings
- Estimated incremental concentration
- Scenario impact on portfolio value
- Data limitations

This analysis is informational. It must not automatically rebalance or transact.

### 8.7 Acceptance criteria

- Broker account data is accessed only through authorized read-only capabilities.
- Uploaded files are validated before being applied.
- Duplicate holdings are handled transparently.
- Every risk metric states its scope and assumptions.
- Trade scenarios cannot submit orders.
- Stale or incomplete prices are visible.
- Portfolio calculations are reproducible.

---

## Module 6 — More / AI Copilot

### 9.1 Purpose

Provide a conversational interface for querying market data, research, technical signals and portfolio risk.

### 9.2 Example questions

- Why is this stock moving today?
- Which stocks have confirmed breakouts with strong relative volume?
- What are the main risks in this stock?
- Compare two stocks in the same sector.
- Summarize the latest results and management guidance.
- What changed in this stock's technical setup?
- Show similar historical setups and their outcomes.
- How would a hypothetical position affect my portfolio concentration?
- Which important announcements were published after yesterday's close?

### 9.3 AI Copilot architecture

The Copilot should use controlled tools and structured data rather than relying on the language model's memory for market facts.

Potential tools:
- Market snapshot lookup
- Stock profile lookup
- Technical indicator lookup
- Scanner result lookup
- Corporate event search
- Filing retrieval
- Historical validation query
- Portfolio exposure query
- Scenario calculator
- Watchlist operations

The LLM orchestrates queries, explains results and asks clarifying questions when required.

### 9.4 Response structure

Where applicable, responses should contain:

1. Direct answer.
2. Supporting evidence.
3. Relevant data timestamps.
4. Bullish and bearish factors.
5. Key uncertainties.
6. Potential invalidation conditions.
7. Source references.
8. Link to the underlying analysis.

### 9.5 Grounding and hallucination controls

- Do not invent stock prices, financial results or announcements.
- Do not fabricate source citations.
- Do not infer missing values without marking the inference.
- Clearly identify stale or unavailable data.
- Separate factual information from analytical interpretation.
- Use deterministic calculation tools for numerical outputs.
- Display the relevant model or methodology version for quantitative claims.
- Treat third-party content as untrusted input, not executable instructions.

### 9.6 Watchlists and saved research

Users can:
- Create and rename watchlists.
- Add or remove instruments.
- Save analyses.
- Add notes to a setup.
- Set alert criteria.
- Review past alerts and their outcomes.

### 9.7 Settings and integrations

Provide:
- Broker connections
- Portfolio imports
- Notification preferences
- Default market and chart settings
- Data-source status
- Privacy and authorization controls
- AI response preferences
- Session and account security settings

### 9.8 Acceptance criteria

- The Copilot retrieves current or historical facts through authorized data tools.
- Numerical claims are reproducible.
- Material claims have source references when sources exist.
- Users can navigate from a response to its supporting analysis.
- Unsupported requests result in an explicit limitation rather than a fabricated answer.

---

# 5. F&O Intelligence — Cross-Module Capability

Although the primary navigation groups this capability under AI Scanner and Chart Analysis, F&O intelligence is an important extension of the Smart Trading Desk.

## 10.1 Objective

Identify and validate futures and options positioning signals while cross-checking them against the underlying cash-market price action.

## 10.2 Instrument universe

Use the current NSE equity derivatives underlying list as the authoritative starting point for eligible single-stock F&O instruments.

Maintain separate mappings for:
- Cash equity symbol
- Derivatives underlying
- Futures contract
- Options contract
- Expiry
- Lot size
- Strike
- Instrument status

Do not assume every cash-market stock is F&O eligible.

## 10.3 Required data

Where available:
- Underlying cash price and OHLCV
- Futures price and volume
- Open interest and change in open interest
- Futures basis
- Options chain
- Call and put volume
- Call and put open interest
- Implied volatility
- Put-call ratios with explicit calculation definitions
- Expiry and contract specifications

Each feature must carry its source timestamp and availability status.

## 10.4 Build-up classification

The system should classify futures positioning into:

| Price movement | Open-interest movement | Interpretation |
|---|---|---|
| Price rises | OI rises | Long build-up candidate |
| Price falls | OI rises | Short build-up candidate |
| Price rises | OI falls | Short covering candidate |
| Price falls | OI falls | Long unwinding candidate |

These are heuristic interpretations, not direct proof of trader intent. Price/OI classification can be distorted by rollovers, expiry effects, intraday noise and changes in contract participation.

## 10.5 Fifteen-minute signal confirmation

For each eligible underlying:
- Calculate 15-minute price change.
- Calculate OI change over a defined comparable interval.
- Compare futures direction with cash-market price action.
- Evaluate relative volume and market breadth.
- Check VWAP and trend indicators when available.
- Detect divergence between futures and cash.
- Identify missing or delayed derivatives data.
- Assign a setup state: candidate, confirmed, invalidated or unavailable.

A signal must not be marked confirmed solely because the price and OI moved in a qualifying direction once.

## 10.6 F&O scanner output

Required fields:
- Underlying symbol
- Cash price and change
- Futures price and change
- OI and OI change
- Build-up classification
- Cash-market confirmation
- Relative volume
- Relevant expiry
- Setup quality or calibrated probability, where validated
- Key risk flags
- Data timestamp

## 10.7 Acceptance criteria

- F&O eligibility comes from a maintained instrument master.
- Cash and derivatives records are mapped correctly.
- OI calculations compare consistent intervals and contracts.
- Missing OI is not treated as zero.
- Expiry-related distortions are disclosed.
- The system supports research and hypothetical scenarios only.

---

# 6. AI and Quantitative Intelligence Architecture

## 11.1 Design principle

Use deterministic quantitative services for numerical analysis and AI agents for interpretation, summarization and orchestration.

The LLM must not replace the underlying calculation engine.

## 11.2 Logical components

1. **Market Data Service:** Ingests and serves market prices, OHLCV and instrument metadata.
2. **Instrument Master:** Maintains canonical stock, exchange and derivatives identifiers.
3. **Technical Analysis Engine:** Calculates indicators and detects patterns.
4. **Prediction Service:** Serves versioned model predictions and calibration metadata.
5. **Event Intelligence Service:** Ingests, normalizes and links events to instruments.
6. **Fundamental Research Service:** Retrieves company fundamentals and relevant results.
7. **Portfolio Service:** Imports and consolidates read-only portfolio data.
8. **Risk Engine:** Calculates exposure and hypothetical trade scenarios.
9. **Historical Validation Engine:** Runs reproducible backtests and model evaluation.
10. **AI Orchestration Service:** Routes Copilot requests to approved tools.
11. **Notification Service:** Generates deduplicated alerts.
12. **Audit and Observability Service:** Records model versions, data provenance, latency and failures.

## 11.3 Suggested implementation stack

**Frontend**
- React 18
- Tailwind CSS
- Shadcn/UI
- Recharts for supported visualizations
- A suitable candlestick-chart library for OHLCV and technical overlays

**Backend**
- Python FastAPI
- PostgreSQL for transactional and relational data
- TimescaleDB or another appropriate time-series solution if justified by measured query and storage requirements
- Redis for caching and short-lived state where required
- Background workers for ingestion, calculations and scheduled processing

**AI**
- Existing OpenAI integration
- Google Generative AI fallback, where compatible with the required controls
- Tool-based orchestration
- Structured output validation
- Model and prompt version tracking

The architecture should reuse existing Nivesh services wherever practical rather than duplicate ingestion, authentication or scoring logic.

## 11.4 Data flow

Market sources → Ingestion and normalization → Validated storage → Quantitative services → Versioned signals → AI explanations → UI.

For every displayed signal, the backend should retain:
- Instrument identifier
- Observation timestamp
- Signal-generation timestamp
- Feature snapshot reference
- Model version
- Configuration version
- Prediction definition
- Probability or score
- Supporting evidence
- Data-quality flags

## 11.5 AI output contract

A structured signal explanation should contain:

- `instrument_id`
- `signal_type`
- `signal_state`
- `observation_time`
- `generated_at`
- `prediction_horizon`
- `prediction_definition`
- `model_version`
- `probability`, if calibrated
- `supporting_evidence`
- `contradictory_evidence`
- `risk_flags`
- `invalidation_conditions`
- `source_references`
- `data_quality_status`

The AI must not fill unsupported fields with invented values.

---

# 7. Data Requirements and Source Management

## 12.1 Source categories

The ingestion framework should support the following categories, subject to permitted access and licensing:

- NSE and BSE market data
- Exchange instrument masters
- Corporate announcements and filings
- AMFI and other relevant fund reference data where required
- Company financial results and disclosures
- Bulk and block deal disclosures
- FII/DII and institutional flow data where available
- Broker account and portfolio APIs
- Licensed news and market-data providers

The exact source and entitlement must be documented for each field.

## 12.2 Canonical data model

Core entities:
- Instrument
- Exchange
- Trading session
- OHLCV bar
- Technical indicator snapshot
- Prediction
- Pattern detection
- Corporate event
- News article
- Deal disclosure
- Portfolio account
- Holding
- Position
- Watchlist
- Alert
- Paper trade
- Backtest run
- Model version
- Source health record

## 12.3 Data quality checks

Validate:
- Missing bars
- Duplicate records
- Incorrect timestamps
- Invalid OHLC relationships
- Corporate-action adjustments
- Symbol and ISIN mismatches
- Stale market feeds
- Out-of-order updates
- Impossible price movements
- Missing volume or open interest
- Unavailable exchange sessions
- Unexpected changes in instrument eligibility

## 12.4 Source health dashboard

Administrators must be able to see:
- Source status
- Last successful ingestion
- Last attempted ingestion
- Records received
- Records rejected
- Processing latency
- Authentication or access failures
- Rate-limit failures
- Data completeness
- Affected product modules

A failed source must not silently produce an apparently complete market-intelligence view.

## 12.5 Market calendar

Use a maintained exchange calendar for:
- Trading days
- Holidays
- Special sessions
- Market opening and closing times
- Derivatives expiry schedules where applicable

Do not assume that weekends or weekdays alone define market availability.

---

# 8. Historical Validation and Paper Trading

## 13.1 Objective

Ensure the Smart Trading Desk improves decision quality rather than merely generating plausible-looking signals.

## 13.2 Required validation dimensions

For the movement-prediction model:
- Precision at K
- Recall of eligible movers
- Universe coverage
- Probability calibration
- Hit rate by score decile
- Performance by sector and liquidity category
- Performance by market regime
- Performance by volatility regime

For simulated trade strategies:
- Net return after costs
- Win rate
- Average win and loss
- Expectancy
- Maximum drawdown
- Maximum adverse excursion
- Exposure and turnover
- Slippage sensitivity
- Benchmark-relative performance
- Out-of-sample stability

## 13.3 Validation protocol

1. Define the hypothesis before running the experiment.
2. Define the universe and exclusions.
3. Define entry, exit, stop and target rules.
4. Freeze feature definitions and model version.
5. Prevent future-data leakage.
6. Apply costs, slippage and realistic fill assumptions.
7. Use walk-forward evaluation and a genuinely untouched test period where available.
8. Record all parameter changes.
9. Compare against simple baselines.
10. Publish results with sample sizes and uncertainty.

The system must distinguish between exploratory research and pre-registered evaluation.

## 13.4 Paper trading

Users may create hypothetical trades with:
- Instrument
- Signal timestamp
- Reference entry rule
- Simulated entry price
- Stop-loss
- Target
- Quantity
- Estimated costs
- Strategy version
- Rationale
- Exit rule

Track:
- Whether the entry condition was reached
- Actual eligible price observations
- Exit condition
- Gross and net hypothetical P&L
- Maximum favorable excursion
- Maximum adverse excursion
- Rule violations or missing data

Paper trades must never create broker orders.

## 13.5 Historical data integrity

The engine must explicitly handle:
- Corporate actions
- Survivorship bias
- Historical universe membership
- Circuit limits and price gaps
- Trading suspensions
- Liquidity exclusions
- Intrabar stop/target ambiguity
- Delisted or renamed securities
- Historical source availability

A backtest must be reproducible using its saved configuration and data references.

---

# 9. API Requirements

The following endpoints are proposed logical contracts. They must be reconciled with existing Nivesh API conventions before implementation.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/trading-desk/overview` | Market and opportunity summary |
| GET | `/api/v1/market/indices` | Index snapshots |
| GET | `/api/v1/market/breadth` | Market breadth |
| GET | `/api/v1/market/sectors` | Sector performance |
| GET | `/api/v1/scanner/opportunities` | Filtered opportunity list |
| GET | `/api/v1/scanner/opportunities/{id}` | Opportunity detail |
| GET | `/api/v1/instruments/{id}/chart` | OHLCV chart data |
| GET | `/api/v1/instruments/{id}/indicators` | Indicator values |
| GET | `/api/v1/instruments/{id}/patterns` | Pattern detections |
| GET | `/api/v1/instruments/{id}/events` | Related events |
| GET | `/api/v1/events` | Market event feed |
| GET | `/api/v1/events/{id}` | Event detail |
| GET | `/api/v1/portfolio/summary` | Consolidated portfolio summary |
| GET | `/api/v1/portfolio/risk` | Portfolio risk metrics |
| POST | `/api/v1/scenarios/calculate` | Hypothetical risk calculation |
| GET | `/api/v1/fno/scanner` | F&O opportunity candidates |
| GET | `/api/v1/validation/runs/{id}` | Historical validation report |
| GET/POST | `/api/v1/watchlists` | List and create watchlists |
| POST | `/api/v1/paper-trades` | Create hypothetical trade |
| GET | `/api/v1/paper-trades` | List paper trades |
| POST | `/api/v1/copilot/query` | Submit a research question |

The API must enforce authorization, input validation, pagination, rate limits and consistent error responses.

All market-data responses should identify their observation timestamp and freshness status.

No live order-placement endpoint should be included in this product scope.

---

# 10. Security, Privacy and Governance

## 14.1 Authentication and authorization

- Reuse Nivesh's existing authentication system.
- Enforce account and tenant boundaries.
- Validate authorization on every portfolio and broker operation.
- Apply least-privilege access.
- Maintain secure session management.

## 14.2 Broker integrations

- Request only the scopes needed for read-only functionality.
- Never request order-placement permissions for the Smart Trading Desk MVP.
- Protect credentials and tokens using an appropriate secrets-management mechanism.
- Redact sensitive values from application logs.
- Support disconnect and authorization revocation.
- Record connection status and last successful synchronization.
- Prevent accidental write calls in broker adapters.

## 14.3 File upload security

- Validate file type and content.
- Enforce file-size limits.
- Parse uploads in a controlled environment.
- Reject malformed or unsupported files.
- Avoid executing embedded macros or active content.
- Prevent spreadsheet formula injection in exported files.
- Provide a preview before committing imported portfolio records.

## 14.4 AI security

- Treat external documents and news as untrusted data.
- Prevent retrieved content from overriding system instructions.
- Restrict the Copilot to approved tools.
- Validate tool arguments and returned data.
- Do not expose another user's portfolio or conversation.
- Record the sources used for material answers.

## 14.5 Regulatory and legal review

Before production, review:
- Applicable Indian securities-market regulations.
- SEBI requirements relevant to the product's functionality and marketing.
- Applicable rules for investment advice and research services.
- Market-data licensing and redistribution restrictions.
- Privacy, consent and data-retention requirements.
- Broker API terms and permitted use.
- Required risk disclosures and audit trails.

The product's actual regulatory classification must be determined from its implemented functionality, not merely from calling it a research tool.

---

# 11. Non-Functional Requirements

These are proposed engineering targets and must be confirmed against existing infrastructure and data-provider capabilities.

| Area | Requirement |
|---|---|
| Availability | Target 99.5% monthly availability for core application services, excluding declared maintenance and external provider outages |
| Dashboard performance | Target p95 under 2 seconds for cached overview API responses |
| Scanner performance | Target p95 under 3 seconds for common filtered queries |
| Chart loading | Target under 2 seconds for typical cached chart windows |
| AI response | Target first useful response within 3 seconds for simple queries; longer research must expose progress |
| Data freshness | Display actual freshness; define service-specific SLAs based on source entitlement |
| Scalability | Paginated APIs, indexed queries, caching and asynchronous jobs |
| Reliability | Retries, idempotent ingestion and visible source-failure states |
| Security | Encrypted transport, protected credentials, authorization checks and audit logs |
| Accessibility | Keyboard access, sufficient contrast and readable chart summaries |
| Observability | Logs, metrics, traces, model-health and feed-health monitoring |
| Reproducibility | Versioned features, models, configurations and validation runs |

No latency or freshness SLA should imply real-time data unless the underlying feed contract supports it.

---

# 12. UX and Design System Requirements

## 16.1 Visual design

- Dark navy primary theme.
- Cyan and blue navigation and interaction accents.
- Green for positive values.
- Red for negative values and warnings where appropriate.
- Amber for caution and uncertainty.
- Consistent typography, spacing, borders and card radii.

Color must not be the sole means of communicating meaning.

## 16.2 Interaction standards

- Every visible control must have a defined action.
- Filters must support reset and clear states.
- Tables must have loading, empty and error states.
- Destructive operations require confirmation.
- Important actions must be accessible without hover.
- Stock names and values should remain readable on small screens.
- Avoid showing every indicator on the initial screen.

## 16.3 Trust indicators

Every relevant module should expose:
- Last updated
- Source status
- Live, delayed or historical classification
- AI-generated versus deterministic information
- Methodology or model version
- Confidence or uncertainty where supported

## 16.4 Illustrative data

Prototype and demonstration environments must prominently identify synthetic values as illustrative.

Production interfaces must never use illustrative values as a fallback for unavailable live data without explicit labeling.

---

# 13. Product Analytics and Success Metrics

## 17.1 Adoption metrics

- Weekly and monthly active users
- Scanner usage
- Stock-detail views
- Watchlist creation
- Copilot usage
- Portfolio connection and upload completion
- Repeat usage of saved analyses

## 17.2 Research efficiency

- Time from opening the desk to inspecting an opportunity
- Time to retrieve relevant corporate events
- Percentage of opportunities with complete supporting evidence
- Percentage of Copilot answers linked to relevant source records
- User-reported usefulness

## 17.3 Model-quality metrics

- Precision@5 and Precision@10
- Recall of eligible large-move events
- Eligible-universe coverage
- Calibration error
- Net simulated return after costs
- Drawdown and downside-tail metrics
- Performance stability across regimes

## 17.4 Risk and reliability metrics

- Stale-data incidents
- Feed availability
- Instrument-mapping error rate
- Portfolio reconciliation error rate
- Incorrect event-to-stock mapping
- AI factual error rate
- Unsupported probability-display rate
- Historical validation reproducibility

## 17.5 Measurement rules

All metrics must have a written definition, evaluation period and denominator.

Model metrics must be calculated on appropriately separated test data. User engagement must not be treated as proof of trading performance.

Success thresholds should be established after measuring the current baseline.

---

# 14. MVP Scope and Roadmap

## Phase 0 — Foundation and audit

**Goal:** Confirm data and service readiness.

Deliverables:
- Inventory existing APIs, data sources and schemas.
- Review prediction model performance and universe coverage.
- Establish instrument identity and timestamp conventions.
- Define signal and probability semantics.
- Define security boundaries and source entitlements.
- Build baseline feed-health reporting.

Exit criteria:
- Core data sources and failure modes are documented.
- Model output definitions are agreed.
- Missing-data behavior is specified.
- Initial performance and coverage baselines are available.

## Phase 1 — Smart Trading Desk MVP

**Goal:** Deliver a reliable research workspace.

Scope:
- Overview dashboard.
- Market indices and breadth.
- Sector performance.
- AI Scanner with explainable ranking.
- Market Intelligence feed.
- Basic interactive chart and technical indicators.
- Watchlists.
- Hypothetical trade calculator.
- Data freshness and source health.
- Core risk disclosures.

Exit criteria:
- All P0 requirements in these modules pass QA.
- No live order execution is possible.
- Every displayed prediction identifies its definition and model version.
- Production data is timestamped and sourced.

## Phase 2 — Chart intelligence and validation

Scope:
- Pattern detection and confirmation.
- Historical pattern validation.
- Backtest configuration and reporting.
- Paper trading.
- Strategy versioning and experiment records.
- Model calibration and monitoring.

Exit criteria:
- Reproducible historical runs.
- No known look-ahead leakage in the tested pipeline.
- Transaction costs and execution assumptions are documented.
- Results can be compared against baselines.

## Phase 3 — Portfolio and broker intelligence

Scope:
- Read-only broker adapters.
- CSV/XLS/XLSX imports.
- Portfolio consolidation.
- Portfolio concentration and risk.
- Portfolio-aware opportunity scenarios.

Exit criteria:
- Account data is correctly reconciled.
- Broker permissions are limited to approved scopes.
- Imports produce actionable validation errors.
- No write-capable order interface is exposed.

## Phase 4 — Advanced intelligence

Scope:
- F&O build-up analysis.
- Fifteen-minute cash/derivatives confirmation.
- More advanced event-impact analysis.
- Enhanced Copilot tools.
- Personalized alerts.
- Advanced portfolio scenarios.

Exit criteria:
- Derivatives data quality and coverage are sufficient.
- Classification rules are validated.
- Event attribution is traceable.
- Advanced capabilities have independent acceptance tests.

---

# 15. QA Strategy and Acceptance Framework

## 19.1 Functional testing

Test:
- Navigation across all six sections.
- Filters and sorting.
- Stock and sector drill-downs.
- Event-source links.
- Chart controls and indicators.
- Portfolio import and reconciliation.
- Scenario calculations.
- Watchlists and alerts.
- Copilot tool responses.
- Paper-trade lifecycle.

## 19.2 Data testing

Test:
- Missing bars and delayed feeds.
- Incorrect instrument mappings.
- Duplicate announcements.
- Corporate actions.
- Market holidays.
- Missing open interest.
- Partial broker synchronization.
- Out-of-order events.
- Stale price handling.

## 19.3 Model testing

Test:
- Feature parity between training and serving.
- Model-version consistency.
- Probability calibration.
- Prediction horizon correctness.
- Universe eligibility.
- Out-of-sample evaluation.
- Look-ahead leakage.
- Costs and slippage assumptions.
- Model degradation and alerting.

## 19.4 Security testing

Test:
- Unauthorized portfolio access.
- Cross-user data leakage.
- Token and secret redaction.
- Malicious file uploads.
- Prompt injection in retrieved documents.
- Invalid tool requests.
- Accidental broker write operations.

## 19.5 Release gates

A release cannot proceed if:
- Market data is being displayed as live without entitlement or freshness evidence.
- Material AI claims cannot be traced to their sources.
- Prediction probabilities are presented without adequate definitions.
- Critical historical-validation leakage remains unresolved.
- Broker authorization exceeds the intended read-only scope.
- Risk calculations are incorrect.
- Critical security defects remain open.

---

# 16. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Prediction model ranks volatility rather than profitable opportunities | Separate movement prediction from trade expectancy; evaluate net returns |
| Large number of movers are excluded from the model universe | Track coverage and exclusion reasons; revisit liquidity and rank gates |
| Incorrect or stale market data | Source-health monitoring, freshness indicators and fail-closed behavior for affected calculations |
| Corporate-event feed gaps | Multiple permitted sources, feed monitoring and explicit completeness status |
| AI hallucinations | Tool-grounded answers, structured outputs and source references |
| Historical look-ahead bias | Timestamped features, walk-forward testing and independent validation |
| False technical breakouts | Multi-factor confirmation, invalidation criteria and historical statistics |
| Broker symbol mismatch | Canonical instrument master and reconciliation workflow |
| Misleading confidence displays | Probability calibration, sample sizes and uncertainty disclosures |
| Excessive UI complexity | Progressive disclosure, mobile-first information hierarchy and usability testing |
| Unauthorized execution | Read-only broker scopes and no order-placement endpoint |

---

# 17. Open Decisions

The following decisions should be resolved during Phase 0:

1. Which existing Nivesh APIs should be reused and which require extension?
2. Which market-data sources are approved for each instrument and timeframe?
3. What is the authoritative source for intraday OHLCV and F&O open interest?
4. Which prediction models will be exposed in the first release?
5. Which outcomes and horizons have sufficiently calibrated probabilities?
6. Which broker adapters are ready for read-only portfolio access?
7. What is the approved portfolio import template contract?
8. Which chart library best fits licensing, performance and technical-analysis requirements?
9. What are the data-retention and user-consent rules?
10. What source coverage and performance thresholds are required for production?

These are implementation decisions, not reasons to delay the initial UI and API-contract work.

---

# 18. Definition of Done

The Smart Trading Desk MVP is complete when:

- All P0 screens and workflows are implemented.
- Responsive desktop and mobile layouts are verified.
- Market and event data have source and timestamp metadata.
- Scanner outputs are explainable and reproducible.
- Technical indicators are consistent across the UI and backend.
- Risk calculations pass independent test cases.
- Missing and stale data are handled safely.
- AI responses use approved, traceable data sources.
- Read-only integration boundaries are enforced.
- No live trading functionality is present.
- Historical-validation results disclose methodology and assumptions.
- Security, performance, functional and regression testing pass.
- Product analytics and operational monitoring are enabled.
- Product and regulatory reviews are completed for the intended deployment.

---

# 19. Final Product Recommendation

Build the Smart Trading Desk as a shared intelligence platform rather than six disconnected dashboards.

The core product loop should be:

**Market context → Opportunity discovery → Evidence and event analysis → Technical confirmation → Risk scenario → Historical validation → Watchlist or paper trade → Outcome measurement.**

The initial differentiator should be the quality and transparency of this loop. More signals are not inherently better. Nivesh should demonstrate which opportunities it can identify, which it misses, what evidence supports them, and how the resulting strategies perform after costs.

The product should earn user trust through measurable research quality, explainability, source transparency and disciplined risk controls—not through aggressive claims about AI prediction accuracy.