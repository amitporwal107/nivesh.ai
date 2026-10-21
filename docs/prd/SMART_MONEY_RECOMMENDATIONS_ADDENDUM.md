# Product Requirements Addendum: Stock Selection and Recommendations Using Smart Money Intelligence

> Sections 30–42 of "Nivesh Smart Money Intelligence — Market Data Source Inventory"
> (updated version supplied by the user on 2026-10-22). Sections 1–29 of that document
> cover the data-source inventory and the stock-level money-flow addendum.

**Purpose:** Define how Nivesh uses institutional money-flow intelligence as one input to stock discovery, eligibility, ranking, recommendation, position sizing and risk management.

## 30. Product objective

Nivesh shall convert Smart Money Intelligence into an explainable stock-selection workflow. The system should identify candidates from disclosed institutional activity and market signals, evaluate them using fundamentals and technicals, apply risk and portfolio constraints, and present recommendations appropriate to the user's selected investment horizon.

**Core principle:** Institutional accumulation identifies where to investigate. Fundamentals determine what may be worth owning. Technicals help determine when an entry may be appropriate. Risk management determines whether and how much exposure is suitable.

A high Smart Money Score alone must never trigger a buy recommendation.

## 31. Stock-selection workflow

1. **Smart Money discovery:** Identify disclosed holdings changes, institutional ownership changes, deal disclosures and emerging market-activity signals.
2. **Sector and market confirmation:** Evaluate sector leadership, market breadth and aggregate FII/FPI/DII flow context.
3. **Fundamental quality:** Assess revenue and earnings growth, ROCE, ROE, leverage, cash-flow quality, valuation and corporate/governance risks.
4. **Technical entry validation:** Evaluate trend, relative strength, breakout/pullback structure, volume confirmation, support and invalidation.
5. **Risk and portfolio fit:** Assess position size, downside, liquidity, volatility, correlation, sector concentration and user portfolio constraints.
6. **Explainable recommendation:** Rank eligible candidates, show evidence and counter-evidence, state risks, and specify what would invalidate the thesis.

The pipeline must support hard eligibility gates. A candidate that fails a mandatory risk, data-quality or suitability rule must be rejected or deferred even if its composite score is high.

## 32. Recommendation score

Create a separate **Nivesh Stock Recommendation Score (0–100)**. Keep it distinct from the Smart Money Accumulation Score and Distribution Score.

Proposed initial weights for research and backtesting:

| Factor | Initial weight | Inputs |
|---|---:|---|
| Smart Money Intelligence | 25% | Disclosed holdings changes, breadth, persistence, evidence class and confidence |
| Fundamental Quality | 25% | Growth, ROCE, ROE, leverage, cash flow, earnings quality and corporate risks |
| Technical Strength | 20% | Trend, relative strength, breakout quality, volume confirmation and invalidation |
| Sector and Market Regime | 15% | Sector rotation, market breadth, index trend and aggregate institutional flow context |
| Valuation and Risk | 15% | Valuation, downside, liquidity, volatility, event risk and portfolio fit |
| **Total** | **100%** | |

These weights are hypotheses for a baseline, not validated predictive coefficients. Calibrate them only after point-in-time walk-forward and out-of-sample testing.

### Suggested score bands

| Score | Initial classification | Expected product behavior |
|---|---|---|
| 80–100 | High-priority candidate | Consider a recommendation only if all mandatory checks pass |
| 65–79 | Watch / potential opportunity | Wait for missing confirmation or suitable entry conditions |
| 50–64 | Developing candidate | Continue monitoring |
| Below 50 | Low priority | Exclude from the primary recommendation list unless a separate strategy justifies review |

These bands are product defaults, not probabilities of positive returns. A score of 85 must not be represented as an 85% chance of profit.

### Scoring requirements

- Keep the accumulation score, distribution score, recommendation score and data confidence as distinct fields.
- Do not let missing institutional data automatically count as negative evidence or as a zero factor score.
- Keep direct ownership/transaction evidence separate from indirect price/volume proxies.
- Prevent duplicated or highly correlated features from receiving undue weight.
- Show factor contributions and the principal positive and negative drivers.
- Version every scoring configuration and retain the feature snapshot used for each recommendation.
- Calibrate scores and any probability estimates only after out-of-sample validation.

## 33. Recommendation states

The engine should produce clear research states, not just a ranked list.

| State | Typical evidence | Product behavior |
|---|---|---|
| **Early accumulation watchlist** | Holdings/ownership changes or improving market proxies; technical confirmation may be incomplete | Add to watchlist and identify evidence needed next; do not call it a confirmed institutional buy |
| **Confirmed-strength candidate** | Disclosed institutional evidence aligns with positive technical signals, acceptable fundamentals and liquidity | Evaluate potential entry, expected return, downside and portfolio suitability |
| **Institutional divergence** | Ownership evidence and price/volume trend disagree | Explain the divergence and require investigation; do not assume it is automatically bullish or bearish |
| **Distribution / exit-risk watchlist** | Reported holdings decline alongside weakening price structure or sector conditions | Trigger thesis review or risk alert; do not infer that every institution is selling |
| **Insufficient evidence** | Data is missing, stale, ambiguous or contradictory | Avoid a directional recommendation until evidence is adequate |

Keep **institutional accumulation** and **technical entry readiness** as separate dimensions. A fundamentally attractive stock may not be an attractive entry at its current price.

## 34. Strategy profiles and holding horizons

Recommendations must be strategy-specific. The same institutional signal should not generate identical recommendations for long-term investors and positional traders.

### 34.1 Long-term investing

Illustrative horizon: 6–36 months.

- Sustained mutual-fund and institutional ownership growth across disclosed periods.
- Durable earnings, cash generation, ROCE and balance-sheet quality.
- Reasonable valuation relative to growth, quality and peers.
- Sector tailwinds and a defensible business thesis.
- Output: investment thesis, valuation scenarios, downside risks and portfolio-allocation suitability.

### 34.2 Positional / swing trading

Illustrative horizon: 5–30 trading sessions.

- Improving relative strength and trend alignment.
- Base breakout or pullback setup with a defined invalidation level.
- Volume confirmation and supportive sector conditions.
- Acceptable expected reward-to-risk after costs and slippage.
- Output: entry conditions, invalidation, target/exit logic and risk-based position size.

### 34.3 Event-driven opportunities

Horizon depends on the event and strategy.

- Results, disclosed deals, corporate announcements or material regulatory events.
- Assess whether the information is new, already priced in or uncertain.
- Account for gap risk, volatility and event uncertainty.
- Output: event thesis, scenarios, risks and conditions for avoiding the trade.

Horizons are configurable starting defaults. Each strategy requires separate validation.

## 35. Eligibility and risk gates

Before ranking candidates as recommendations, apply mandatory checks, including:

- Minimum data completeness and acceptable source freshness.
- Reliable instrument and ownership mapping.
- Minimum liquidity and trading-value thresholds.
- Fundamental-quality and balance-sheet rules appropriate to the strategy.
- Governance, regulatory and material corporate-risk checks.
- Valuation constraints where relevant to the strategy.
- Defensible entry and invalidation plan for trading recommendations.
- Portfolio concentration, sector exposure and correlation constraints.
- Event and gap-risk checks.
- User risk tolerance, investment horizon and existing holdings where that information is available and permissioned.

The system must record the reason for each rejection, downgrade or deferral. A candidate excluded by data or liquidity filters must remain visible in coverage diagnostics.

## 36. Position sizing and portfolio risk

A recommendation score must not determine position size by itself. Size should be calculated from the user's risk budget, entry assumptions, invalidation level, liquidity and portfolio constraints.

For a basic cash-equity risk calculation:

`quantity = floor(risk_budget_per_trade / abs(entry_price - stop_price))`

This is a starting formula only. Before showing a final quantity, account for transaction costs, slippage, lot sizes where applicable, liquidity, gap risk and the possibility of stop execution beyond the intended level.

The portfolio-risk layer should assess:

- Maximum exposure per stock and sector.
- Correlation and overlapping underlying holdings.
- Existing portfolio allocation and cash needs.
- Liquidity and volatility limits.
- Earnings/event risk and overnight gap risk.
- Tax and transaction-cost considerations where relevant.
- Total portfolio downside under adverse scenarios.

If entry, stop or risk-budget inputs are unavailable, the system must not invent a position size.

## 37. Recommendation card requirements

Every recommendation card should display:

- Stock name, symbol, sector and current price with timestamp, where licensed/available.
- Recommendation state and strategy horizon.
- Recommendation Score and its factor breakdown.
- Separate Smart Money Accumulation Score and Distribution Score.
- Evidence class, data confidence, completeness and freshness.
- FII/FPI, DII and mutual-fund holdings evidence with reporting dates.
- Scheme/holder breadth and concentration caveats where available.
- Fundamental thesis and valuation context.
- Technical entry conditions and invalidation level, if applicable.
- Expected-return/downside scenarios and reward-to-risk assumptions, if calculated.
- Position size only when user risk inputs and all required market data are available.
- Positive evidence, contradictory evidence and principal risks.
- What would strengthen, weaken or invalidate the thesis.
- Source links and last-updated timestamps.

The card must distinguish a **watchlist candidate** from an **entry-ready setup**. A high composite score does not mean that an entry condition has been met.

## 38. AI Copilot requirements

Support questions such as:

- “Find Nifty 500 stocks where mutual-fund accumulation is increasing and technical strength is improving.”
- “Which candidates have strong fundamentals but are waiting for a breakout?”
- “Show stocks where FII ownership is falling while domestic institutional ownership is increasing.”
- “Which recommendations fit my current portfolio without increasing sector concentration?”
- “What changed since the previous session that caused this recommendation to improve or deteriorate?”
- “Which high-scoring candidates have stale ownership disclosures or weak liquidity?”
- “Compare the institutional, fundamental and technical evidence for these stocks.”

Copilot answers must be grounded in structured data, show the reporting period and source links, identify missing evidence and avoid invented prices, holdings or probabilities. If the data does not support an answer, it must say so.

## 39. Validation and model comparison

Before promoting the composite model to production recommendations, compare at least these historical baselines:

1. Fundamental quality only.
2. Technical strength only.
3. Smart Money Intelligence only.
4. Combined institutional, fundamental, technical, sector and risk model.

Evaluate whether the combined model adds value over the baselines. Report:

- Forward returns over predefined horizons.
- Excess returns against appropriate market and sector benchmarks.
- Hit rate, maximum drawdown and downside risk.
- Turnover and realistic transaction costs.
- Results by sector, market capitalization and market regime.
- Whether institutional evidence appears early enough to be useful.
- Sample size and confidence intervals.

Use point-in-time holdings, actual publication timestamps, historical universe membership and walk-forward/out-of-sample testing. Do not treat a holding as known at the reporting-period end if it was published later.

## 40. Additional acceptance criteria for recommendations

The recommendation layer is ready for release when:

1. The Recommendation Score is separate from the accumulation and distribution scores.
2. The factor breakdown and evidence supporting each recommendation are visible.
3. Mandatory data-quality, fundamental, liquidity and risk gates can override a high score.
4. Watchlist, entry-ready, divergence, distribution-risk and insufficient-evidence states are distinguishable.
5. Recommendations are generated for a selected strategy horizon with horizon-appropriate rules.
6. Position size is not generated without a risk budget and valid entry/invalidation assumptions.
7. Portfolio concentration and correlation checks are applied when portfolio data is available and authorized.
8. Every recommendation can be reproduced from a stored feature snapshot, source references and model version.
9. The UI never presents a score as a probability unless a separate probability model has been calibrated and validated.
10. Backtests compare the combined model against simpler baselines using point-in-time data and realistic costs.
11. Source freshness, contradictory evidence and limitations are visible to the user.
12. AI explanations do not make unsupported claims about undisclosed institutional trades.

## 41. Recommendation implementation roadmap

### Phase 1 — Candidate discovery
- Use disclosed institutional holdings and market proxies to generate a candidate universe.
- Keep evidence classes, confidence and freshness visible.
- Add sector and market-regime context.

### Phase 2 — Eligibility and multi-factor ranking
- Add fundamental-quality, technical-strength, valuation and risk factors.
- Implement mandatory eligibility gates and the initial Recommendation Score.
- Explain exclusions, downgrades and score contributions.

### Phase 3 — Strategy-specific recommendations
- Build separate long-term, positional and event-driven rule sets.
- Add entry readiness, invalidation and portfolio-fit checks.
- Implement risk-budget-based position sizing where inputs are available.

### Phase 4 — Historical validation and controlled rollout
- Compare factor-only baselines with the combined model.
- Run point-in-time walk-forward and out-of-sample tests.
- Publish model performance and limitations.
- Enable alerts and production recommendations only after defined acceptance thresholds are met.

## 42. Recommendation design principle

Smart Money Intelligence should be a core input to stock selection, not a standalone buy/sell signal.

Nivesh should first discover candidates from disclosed institutional activity and market signals, then assess business quality, confirm technical conditions, apply portfolio and risk constraints, and rank the remaining candidates for the user's chosen horizon.

The model should earn its weight through measured incremental value over existing fundamental and technical approaches. The sophistication of a score is not evidence that it predicts returns.
