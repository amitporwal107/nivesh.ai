# Nivesh AI Intelligence Copilot — Evidence-Driven & Visual Intelligence PRD (v2.0)

> **Saved verbatim from the owner, 31 Oct 2026.** It evolves the existing PRDs (Daily Trader Copilot,
> Question-to-Visualization Engine, Portfolio & Broker Hub, Auto-suggestions;
> see `docs/daily_trader_copilot/` on the `feat/daily-trader-copilot` branch) into one broader baseline.
> Gaps against the current build: [`PRD_v2_GAP_ANALYSIS.md`](PRD_v2_GAP_ANALYSIS.md).

The owner's two headline changes:

1. Every question in the Copilot prompt library must have a defined answer blueprint. Answers should be generated
   dynamically from Nivesh's verified data, calculations, research and evidence—not from generic LLM knowledge or
   hardcoded responses.
2. The Copilot must behave like an interactive financial intelligence dashboard inside a chat interface, not like a
   chatbot that returns long paragraphs. It should use charts, metric cards, comparison tables, timelines, scenario
   visualizations and evidence panels wherever they improve understanding.

---

# Nivesh AI Intelligence Copilot

## Consolidated Product Requirements Document

**Version:** 2.0\
**Status:** Product Requirements Baseline\
**Product:** Nivesh.ai / Nivesh Copilot\
**Core Principle:** Evidence Before Intelligence

---

# 1. Product Vision

Build a unified AI-powered financial and market intelligence Copilot that helps Indian retail investors, traders, HNIs and financial advisors make better-informed decisions.

The Copilot should combine:

- Reliable financial and market data.
- Fundamental and technical analysis.
- Sector and industry intelligence.
- Macro-economic intelligence.
- News, regulatory and legal intelligence.
- Smart money and institutional activity.
- Trading strategy analysis and validation.
- Risk management and portfolio intelligence.
- Personalized financial education.

The product should not simply answer questions. It should retrieve relevant evidence, perform calculations, identify relationships, challenge assumptions and communicate conclusions through an intuitive visual experience.

**Positioning:** Nivesh – Understand Before You Invest.

# 2. Product Objectives

1. Provide evidence-backed answers substantially more useful than standalone general-purpose AI.
2. Convert complex financial information into understandable insights.
3. Connect market events, macroeconomic developments, sectors and individual companies.
4. Help users evaluate trading ideas and strategies before risking capital.
5. Make uncertainty, conflicting information and missing data visible.
6. Deliver visually rich and interactive answers within one conversational interface.
7. Improve continuously through historical validation and outcome tracking.

# 3. Target Users

| Persona                 | Primary needs                                                      |
| ----------------------- | ------------------------------------------------------------------ |
| New retail investor     | Understand markets, stocks, risk and investing basics              |
| Active retail trader    | Trading ideas, technical analysis, F&O and risk management         |
| Positional trader       | Stock selection, sector rotation and multi-day opportunities       |
| Long-term investor      | Company quality, valuation and business prospects                  |
| HNI investor            | Portfolio exposure, concentration and macro risks                  |
| MFD / financial advisor | Client portfolio insights, research and explainable reports        |
| Experienced trader      | Strategy validation, derivatives analytics and market intelligence |

# 4. Core Product Experience

## 4.1 Unified Copilot Chat

The entire intelligence experience must be accessible through one conversational interface.

Users should be able to ask questions such as:

- Analyse CG Power from fundamental and technical perspectives.
- Which sectors are showing institutional accumulation?
- What happens to Indian companies if crude rises by 15%?
- Find fundamentally strong stocks near 52-week lows.
- Is this trading strategy worth paper trading?
- What is the impact of this SEBI circular on my portfolio?
- Why did my trading idea fail?
- Compare two stocks for a six-month investment horizon.

The Copilot should automatically identify the required intelligence engines and combine their outputs.

## 4.2 Chat Experience Requirements

- Natural-language input.
- Follow-up questions with conversation context.
- Suggested questions based on the current analysis.
- Searchable prompt library.
- Streaming response generation.
- Interactive charts and tables.
- Expandable evidence and methodology.
- Save, share and export analysis.
- Ability to challenge an answer or request supporting evidence.
- Mobile-first responsive design.

# 5. Functional Requirements

## FR-01: AI Conversational Copilot

The Copilot must:

- Understand user intent and identify relevant entities.
- Identify the required analytical engines.
- Retrieve relevant current and historical data.
- Call deterministic calculation services where required.
- Generate structured, evidence-backed answers.
- Maintain relevant conversation context.
- Identify missing information and ask clarifying questions when necessary.
- Distinguish facts, interpretations and projections.

## FR-02: 360-Degree Stock Intelligence

Provide comprehensive analysis covering:

**Business intelligence**

- Business model and revenue segments.
- Products and services.
- Competitive positioning.
- Industry structure.
- Management and governance.

**Fundamental intelligence**

- Revenue and profit growth.
- Margins and cash flows.
- ROE and ROCE.
- Debt and interest coverage.
- Valuation ratios.
- Earnings quality.
- Promoter, FII, DII and mutual fund ownership.
- Corporate actions and financial red flags.

**Technical intelligence**

- Price and volume trends.
- Moving averages.
- RSI, MACD, ATR and other indicators.
- Support and resistance.
- Breakouts and breakdowns.
- Chart patterns.
- Relative strength.
- Delivery and volume analysis.

**Sector intelligence**

- Sector performance.
- Peer comparison.
- Industry growth.
- Earnings momentum.
- Institutional participation.
- Sector-specific macro sensitivity.

**Forward-looking intelligence**

- Bull, base and bear scenarios.
- Business growth drivers.
- Potential catalysts.
- Key risks.
- Thesis invalidation conditions.
- Indicators to monitor.

## FR-03: Sector Intelligence and Ranking

Rank sectors using measurable and explainable factors.

Initial proposed factors:

| Factor                      | Initial weight |
| --------------------------- | -------------- |
| Relative strength           | 20%            |
| Earnings momentum           | 20%            |
| Fundamental quality         | 15%            |
| Institutional participation | 15%            |
| Valuation                   | 10%            |
| Macro environment           | 10%            |
| Market breadth              | 10%            |

Weights are provisional and must be tested empirically.

Capabilities:

- Sector ranking.
- Sector rotation.
- Sector-versus-market performance.
- Peer and constituent analysis.
- Institutional flow analysis.
- Sector-specific risk.
- Sector outlook and scenario analysis.

## FR-04: Macro Intelligence

Track and analyse:

- RBI repo rate and monetary policy.
- CPI and WPI inflation.
- GDP and IIP.
- PMI and manufacturing activity.
- Fiscal deficit and government spending.
- USD/INR and currency movements.
- Government bond yields.
- Federal Reserve policy.
- Global economic developments.
- Crude oil, natural gas, gold, copper, aluminium, steel and coal.
- Geopolitical developments.

The system must connect macro developments to affected industries, companies and portfolios.

## FR-05: Regulatory and Policy Intelligence

Track relevant developments from:

- SEBI.
- RBI.
- NSE and BSE.
- Ministry of Finance.
- Ministry of Corporate Affairs.
- Ministry of Commerce.
- Relevant government departments.
- Official Gazette and government notifications.

For every important event, explain:

- What changed?
- Who is affected?
- When does it become effective?
- What is the compliance impact?
- Which companies or sectors are exposed?
- What could be the financial or market impact?

## FR-06: Legal and Litigation Intelligence

Track relevant public legal and regulatory developments involving companies.

Sources include:

- Supreme Court.
- High Courts.
- NCLT and NCLAT.
- CCI.
- IBBI.
- Relevant regulatory tribunals and official orders.

The Copilot must distinguish:

- Allegations.
- Investigation.
- Interim orders.
- Final judgments.
- Appeals.
- Settlements.
- Pending proceedings.

Never represent an allegation as an established fact.

## FR-07: News and Corporate Event Intelligence

Capabilities:

- Company announcements.
- Earnings announcements.
- Management changes.
- Orders and contracts.
- Mergers and acquisitions.
- Fundraising.
- Corporate governance events.
- Regulatory developments.
- Industry news.
- Geopolitical events.

Every important news analysis should explain the potential impact, affected entities, time horizon and supporting evidence.

## FR-08: Trading Strategy Builder and Validator

Users can describe strategies in plain English.

The system should:

1. Interpret the strategy.
2. Convert it into explicit entry and exit rules.
3. Identify ambiguous conditions.
4. Validate the required data.
5. Run historical backtests.
6. Include brokerage, taxes, slippage and other relevant costs.
7. Evaluate out-of-sample performance.
8. Perform walk-forward testing.
9. Evaluate performance across market regimes.
10. Assess parameter sensitivity.
11. Recommend paper trading where appropriate.

A strategy's evidence maturity must not be represented as a guaranteed probability of profit.

## FR-09: Risk Management Intelligence

Capabilities:

- Position sizing.
- Stop-loss analysis.
- Risk/reward assessment.
- Portfolio concentration.
- Sector exposure.
- Leverage and margin exposure.
- Options Greeks.
- Expiry risk.
- Liquidity and gap risk.
- Drawdown analysis.
- Risk-profile-based explanations.

Deterministic risk controls must remain authoritative over LLM-generated suggestions.

## FR-10: Portfolio Impact Intelligence

When users connect or upload their portfolios, analyse:

- Asset allocation.
- Sector concentration.
- Stock concentration.
- Portfolio quality.
- Valuation exposure.
- Macro sensitivity.
- Event and regulatory exposure.
- Correlation and diversification.
- Drawdown scenarios.
- Rebalancing considerations.

## FR-11: Daily Market Intelligence

Provide:

- Pre-market briefing.
- Market opening developments.
- Intraday event alerts.
- Sector rotation.
- Smart money activity.
- Closing market summary.
- Important overnight global developments.
- Personalized portfolio impact.

## FR-12: Financial Learning and Education

Explain complex concepts in plain language, with examples and visual explanations.

Learning should be contextual. If a user asks about an options position, explain the relevant Greeks, payoff, maximum loss, breakeven and expiry risk alongside the answer.

# 6. Evidence-Backed Answer Framework

## 6.1 Mandatory Answer Principles

Every analytical response must be:

- Factually grounded.
- Numerically reproducible.
- Time-aware.
- Source-backed.
- Contextually relevant.
- Transparent about uncertainty.
- Clear about limitations.
- Actionable without guaranteeing outcomes.

## 6.2 Evidence Classification

Every important claim must be assigned an evidence type.

| Type                  | Meaning                                                        |
| --------------------- | -------------------------------------------------------------- |
| Verified Fact         | Confirmed through an authoritative source or validated dataset |
| Reported Information  | Published by a credible source but not independently confirmed |
| Analytical Inference  | Conclusion derived from available facts and calculations       |
| Scenario / Projection | Conditional estimate based on stated assumptions               |
| Unknown / Unavailable | Information not available or not sufficiently verified         |

## 6.3 Source Hierarchy

**Tier 1 – Primary and official**

- NSE and BSE disclosures.
- SEBI circulars and orders.
- RBI publications.
- Company annual reports and exchange filings.
- Official court judgments.
- Government notifications.
- MoSPI and other official statistical releases.

**Tier 2 – Established data providers**

- Licensed market-data providers.
- Recognized financial databases.
- Established institutional research datasets.

**Tier 3 – Reputable secondary sources**

- Established financial publications.
- Reputable business news sources.
- Specialist industry publications.

**Tier 4 – Unverified sources**

- Anonymous social media posts.
- Unverified tips.
- Unsubstantiated claims.

Tier 4 information must not independently support investment conclusions.

## 6.4 Universal Answer Contract

The answer generator should select relevant sections based on query intent.

1. Direct answer.
2. Key findings.
3. What the data says.
4. Why it matters.
5. Supporting evidence.
6. Potential implications.
7. Bull, base and bear scenarios where relevant.
8. Risks and invalidation conditions.
9. What to monitor next.
10. Data quality and limitations.

Do not force every section into every answer. A simple educational question should remain simple.

# 7. Visual Response Experience – Core Product Requirement

## 7.1 Product Principle

**The Copilot must not behave like a text-only chatbot.**

It should behave like a financial analyst presenting a compact, interactive research report inside a conversation.

The answer should combine:

- Concise natural-language explanation.
- Visual summaries.
- Interactive analytical components.
- Supporting evidence.
- Expandable technical detail.

The visual experience must be data-driven. Never generate charts, metric values or visual indicators that are not supported by retrieved data.

## 7.2 Visual Response Components

### A. Executive Insight Card

At the beginning of a substantial analysis, display a compact summary.

Example:

**CG Power – Stock Intelligence**

- Overall assessment.
- Fundamental quality.
- Technical trend.
- Sector relative strength.
- Major positive drivers.
- Key risks.
- Last updated timestamp.

The assessment must include its methodology and must not imply a guaranteed investment outcome.

### B. Metric Cards

Use compact metric cards for key numbers.

Examples:

- Revenue growth.
- EBITDA margin.
- ROCE.
- Debt/equity.
- RSI.
- Relative strength.
- FII/DII ownership changes.
- Delivery percentage.
- Valuation multiples.

Every metric must include:

- Value.
- Unit.
- Period/date.
- Comparison or benchmark where meaningful.
- Source or calculation methodology.

### C. Interactive Charts

Support:

- Price and volume charts.
- Moving average overlays.
- RSI and MACD.
- Relative strength charts.
- Revenue and profit trends.
- Cash flow trends.
- Valuation history.
- Ownership trends.
- Sector performance.
- FII/DII flow trends.
- Options payoff graphs.
- Drawdown and equity curves.
- Backtest performance.

Charts should support suitable timeframes, legends, tooltips, source dates and clear units.

### D. Comparison Tables

Use tables for:

- Stock versus peers.
- Sector rankings.
- Fundamental comparison.
- Valuation comparison.
- Strategy comparison.
- Scenario comparison.
- Portfolio exposure.

Highlight meaningful differences without hiding underlying numbers.

### E. Scenario Visualizations

For macroeconomic and forward-looking analysis, show:

| Scenario | Assumption            | Expected direction | Key uncertainty    |
| -------- | --------------------- | ------------------ | ------------------ |
| Bull     | Favourable conditions | Positive           | Execution          |
| Base     | Expected conditions   | Mixed/expected     | Earnings           |
| Bear     | Adverse conditions    | Negative           | Demand and margins |

Where reliable quantitative relationships exist, display estimated ranges and assumptions. Otherwise use qualitative impact descriptions.

### F. Event Timeline

For news, corporate actions, regulatory and legal developments, display:

- Event date.
- Publication date.
- Effective date, if applicable.
- Event description.
- Status.
- Affected company/sector.
- Potential impact.
- Source.

The timeline must distinguish publication date from event date and effective date.

### G. Macro-to-Company Impact Map

Show the relationship:

Macro event → Economic transmission → Sector → Company → Financial metric → Potential market impact.

For example:

Crude oil rises → Input costs increase → Aviation sector → Airline companies → Fuel expenses and margins.

Every relationship should indicate whether it is directly evidenced or an analytical inference.

### H. Evidence Panel

Each substantial answer should provide an expandable evidence section.

Display:

- Claim supported.
- Source title.
- Source organization.
- Publication date.
- Data/event date.
- Retrieval timestamp.
- Evidence classification.
- Link to original source.
- Verification status.

Users must be able to open the underlying evidence.

### I. Data Quality Indicator

Display:

- Data freshness.
- Data completeness.
- Missing metrics.
- Conflicting sources.
- Historical coverage.
- Known limitations.

Avoid a single misleading confidence score when multiple dimensions differ.

### J. Strategy Validation Dashboard

For strategy questions, show:

- Total trades.
- Win rate.
- Net return after costs.
- Profit factor.
- Maximum drawdown.
- Average win/loss.
- Risk/reward.
- Performance by regime.
- Out-of-sample results.
- Parameter sensitivity.
- Paper-trading status.

Use equity curves, drawdown charts and trade-distribution charts where data permits.

## 7.3 Response Layout by Query Type

| Query type          | Preferred visual response                                                  |
| ------------------- | -------------------------------------------------------------------------- |
| Stock analysis      | Executive card, metric cards, price chart, fundamentals, peer table, risks |
| Technical analysis  | Candlestick chart, indicators, support/resistance, volume                  |
| Sector analysis     | Sector ranking, heatmap, relative strength, peer comparison                |
| Macro analysis      | Indicator cards, historical chart, transmission map, scenarios             |
| News analysis       | Event card, timeline, affected entities, evidence panel                    |
| Regulatory analysis | Circular summary, timeline, affected entities, compliance implications     |
| Legal analysis      | Case timeline, current status, parties, verified order links               |
| Strategy validation | Performance cards, equity curve, drawdown, trade distribution              |
| Options analysis    | Payoff graph, Greeks, breakeven, risk metrics                              |
| Portfolio analysis  | Allocation chart, exposure cards, concentration and stress scenarios       |
| Learning question   | Short explanation, annotated example, diagram or interactive illustration  |
| Daily briefing      | Market summary, sector heatmap, movers, event calendar                     |

## 7.4 Adaptive Response Density

The Copilot must adapt its visual and textual density.

**Quick answer**

- One-line conclusion.
- Two or three supporting metrics.
- One important caveat.

**Standard analysis**

- Executive card.
- Relevant charts.
- Key findings.
- Risks and evidence.

**Deep research**

- Full analytical report.
- Multiple visualizations.
- Source-by-source evidence.
- Methodology.
- Scenarios and limitations.

Users should be able to request: "Explain in simple terms", "Show more evidence", "Go deeper", or "Compare visually".

## 7.5 Visual Design Guidelines

- Mobile-first layout.
- Minimalist financial research aesthetic.
- Clear information hierarchy.
- Avoid excessive colors and decorative graphics.
- Use color consistently for positive, negative, neutral and uncertain states.
- Do not communicate a conclusion using color alone.
- Use compact cards and expandable sections.
- Prioritize legibility over visual density.
- Charts must have axes, units, legends and meaningful labels.
- Keep the conversational flow intact; visual components should appear naturally within the answer.
- Provide text alternatives for charts and important metrics.
- Avoid displaying charts when the underlying data is insufficient.

# 8. Complete Prompt Library and Answer Blueprints

The Copilot must support the previously defined 18 prompt categories. The library should store the question, parameters, required engines and expected answer structure.

The answer must be generated dynamically using the latest relevant data and the applicable blueprint.

## Category 1: Stock Discovery and Screening

Example questions:

- Which fundamentally strong stocks are trading near 52-week lows?
- Find stocks with improving earnings and positive relative strength.
- Which stocks have high institutional participation?
- Find companies with improving ROCE and declining debt.
- Which stocks are showing unusual delivery activity?

Answer blueprint:

1. State the screening criteria.
2. Show the number of matching stocks.
3. Display a ranked stock table.
4. Show fundamental and technical metric cards.
5. Explain why each stock qualified.
6. Highlight risks and exclusions.
7. Show data date and screening methodology.

Visuals: ranked table, filters, sector distribution, metric comparison.

## Category 2: Complete Stock Analysis

Example questions:

- Analyse a company from fundamental and technical perspectives.
- Is the current valuation justified?
- What are the major growth drivers?
- What are the risks to the investment thesis?

Answer blueprint:

1. Executive assessment.
2. Business model.
3. Financial performance.
4. Cash flow and balance sheet.
5. Valuation and peer comparison.
6. Technical condition.
7. Ownership and institutional activity.
8. Sector and macro exposure.
9. News and corporate developments.
10. Bull/base/bear scenarios.
11. Risks and thesis invalidation.
12. Evidence and data quality.

Visuals: executive card, financial trends, price chart, peer table, ownership chart, scenario panel.

## Category 3: Technical Analysis

Example questions:

- Is the stock breaking out?
- What are the important support and resistance levels?
- Is momentum improving?
- Is volume confirming the price movement?

Answer blueprint:

1. Current trend and timeframe.
2. Indicator readings.
3. Price structure.
4. Volume and delivery confirmation.
5. Support and resistance.
6. Potential scenarios.
7. Invalidating price conditions.
8. Data timeframe and limitations.

Visuals: candlestick chart, indicators, volume, annotated levels.

## Category 4: Sector Intelligence

Example questions:

- Which sectors are gaining strength?
- Where is institutional money moving?
- Which sectors have improving earnings momentum?
- Which sectors are vulnerable to macro changes?

Answer blueprint:

1. Sector ranking.
2. Relative strength.
3. Earnings momentum.
4. Ownership and flows.
5. Valuation.
6. Market breadth.
7. Macro sensitivity.
8. Risks and future monitoring.

Visuals: sector heatmap, ranking table, relative strength chart, flow chart.

## Category 5: Macro Intelligence

Example questions:

- What happens if crude rises by 15%?
- How does a repo rate change affect banks?
- How could rupee depreciation affect Indian equities?
- What are the implications of US interest-rate changes?

Answer blueprint:

1. Explain the macro event.
2. Show verified indicator history.
3. Explain economic transmission.
4. Identify affected sectors.
5. Identify exposed companies.
6. Explain financial implications.
7. Present scenarios and assumptions.
8. Highlight uncertainty and monitoring indicators.

Visuals: macro cards, historical charts, impact map, scenario comparison.

## Category 6: News and Event Intelligence

Example questions:

- What important developments occurred today?
- Which companies could be affected by this event?
- Is this announcement financially material?
- Has the market already reacted?

Answer blueprint:

1. Event summary.
2. Original source.
3. Event and publication dates.
4. Affected entities.
5. Direct versus indirect impact.
6. Financial and market implications.
7. Price/volume reaction, if available.
8. What to monitor next.

Visuals: news cards, event timeline, affected-company table, price reaction chart.

## Category 7: Regulatory and Policy Intelligence

Example questions:

- Explain the latest SEBI circular.
- Which companies are affected?
- What changes for retail derivatives traders?
- What is the implementation timeline?

Answer blueprint:

1. Official circular summary.
2. What changed.
3. Effective date.
4. Affected participants.
5. Operational and financial implications.
6. Related circulars or amendments.
7. Outstanding clarification or uncertainty.
8. Original document links.

Visuals: regulatory timeline, impact table, before/after comparison.

## Category 8: Legal and Governance Intelligence

Example questions:

- Does the company have major ongoing litigation?
- What is the status of the case?
- Is the issue financially material?
- Are there governance concerns?

Answer blueprint:

1. Identify the case or governance issue.
2. Identify the primary source.
3. Parties and allegations.
4. Proceedings and current status.
5. Orders and appeal history.
6. Potential business/financial implications.
7. Distinguish established facts from allegations.
8. Evidence and limitations.

Visuals: case timeline, status card, issue/impact table.

## Category 9: Strategy Creation and Validation

Example questions:

- Validate my breakout strategy.
- Does this moving-average strategy work?
- What happens if I change the stop loss?
- Does this strategy work in bear markets?

Answer blueprint:

1. Parsed strategy rules.
2. Missing or ambiguous conditions.
3. Data coverage.
4. Backtest methodology.
5. Results after costs.
6. Out-of-sample results.
7. Regime-wise performance.
8. Drawdown and risk.
9. Parameter sensitivity.
10. Limitations and paper-trading recommendation.

Visuals: strategy summary, equity curve, drawdown chart, trade distribution, regime table.

## Category 10: Trading Ideas and Plan Evaluation

Example questions:

- Evaluate this trading idea.
- What is the rationale for this setup?
- What would invalidate the idea?
- Is the trade suitable for my risk profile?

Answer blueprint:

1. Clearly label the output as an idea, not a recommendation.
2. Explain the market thesis.
3. Show supporting technical/fundamental evidence.
4. Define entry conditions.
5. Define invalidation conditions.
6. Estimate risk and reward using explicit assumptions.
7. Identify catalysts and risks.
8. State what requires confirmation.
9. Track the idea's subsequent outcome.

Visuals: idea card, annotated chart, risk/reward diagram, lifecycle status.

## Category 11: F&O and Options Intelligence

Example questions:

- Analyse the options chain.
- Explain the PCR and max pain.
- Compare a bull call spread and bear put spread.
- What is the impact of IV changes?
- What is my maximum loss?

Answer blueprint:

1. Underlying trend.
2. Options-chain snapshot and timestamp.
3. Open interest and changes.
4. PCR and max pain with limitations.
5. IV and expected move.
6. Greeks.
7. Payoff and breakeven.
8. Margin and liquidity.
9. Expiry and gap risk.
10. Exit and invalidation conditions.

Visuals: options chain, payoff graph, Greeks cards, risk summary.

## Category 12: Risk Management and Psychology

Example questions:

- How much capital should I risk?
- How should I size this position?
- Why do I keep exiting profitable trades early?
- How can I reduce overtrading?

Answer blueprint:

1. Identify the risk problem.
2. Explain the relevant concept.
3. Calculate risk using deterministic rules.
4. Show potential loss scenarios.
5. Suggest a practical control.
6. Provide a review checklist.

Visuals: position-sizing calculator, risk meter, loss scenarios, discipline checklist.

## Category 13: Portfolio Analysis

Example questions:

- Is my portfolio diversified?
- Which sectors dominate my portfolio?
- What happens if markets fall 10%?
- Which holdings have deteriorating fundamentals?

Answer blueprint:

1. Portfolio summary.
2. Asset and sector allocation.
3. Concentration and correlation.
4. Fundamental quality.
5. Valuation exposure.
6. Macro and event sensitivity.
7. Stress scenarios.
8. Risks and possible actions.

Visuals: allocation chart, exposure cards, holdings table, stress-test chart.

## Category 14: Earnings and Results

Example questions:

- Analyse the latest quarterly results.
- Did earnings beat expectations?
- Is profit growth supported by cash flow?
- Which metrics deteriorated?

Answer blueprint:

1. Results summary.
2. Year-on-year and quarter-on-quarter comparisons.
3. Revenue, margins, profits and cash flows.
4. Segment performance.
5. Management commentary.
6. Expectations comparison, if reliable data exists.
7. Market reaction.
8. Red flags and follow-up metrics.

Visuals: financial metric cards, quarterly trend charts, segment comparison.

## Category 15: Future Prospects and Scenarios

Example questions:

- What are the company's growth drivers?
- What could affect its business over the next three years?
- What are the major downside risks?
- Which assumptions drive the valuation?

Answer blueprint:

1. Business outlook.
2. Industry growth.
3. Company positioning.
4. Earnings drivers.
5. Valuation assumptions.
6. Bull/base/bear scenarios.
7. Risks and invalidation.
8. Leading indicators to monitor.

Visuals: scenario cards, sensitivity chart, growth-driver map.

## Category 16: Daily Market Briefing

Example questions:

- Summarize today's market.
- What is driving today's market movement?
- Which sectors are outperforming?
- What should I monitor tomorrow?

Answer blueprint:

1. Index performance.
2. Sector performance.
3. Market breadth.
4. Major gainers and losers.
5. FII/DII activity where available.
6. Important news and events.
7. Global developments.
8. Next-session watchlist.

Visuals: index cards, sector heatmap, market breadth, event timeline.

## Category 17: Financial Education

Example questions:

- Explain ROCE.
- How does options theta work?
- What is a bear market?
- How does position sizing work?

Answer blueprint:

1. Simple explanation.
2. Realistic example.
3. Formula where relevant.
4. Visual illustration.
5. Common mistakes.
6. Practical application.

Visuals: annotated diagrams, calculators, payoff examples.

## Category 18: Advanced Research and Peer Comparison

Example questions:

- Compare two companies.
- Identify contradictions between earnings and stock performance.
- Which companies have improving institutional participation?
- Is the market pricing in future growth?

Answer blueprint:

1. Define the comparison basis.
2. Show comparable metrics and dates.
3. Explain differences.
4. Identify conflicting evidence.
5. Discuss valuation and expectations.
6. Present scenarios.
7. State limitations and evidence.

Visuals: side-by-side comparison, normalized charts, ranking table, evidence matrix.

# 9. Multi-Dimensional Intelligence

The Copilot must support questions requiring multiple intelligence engines.

Examples:

- Which companies benefit from lower crude prices but also show improving institutional ownership?
- Find stocks with strong earnings, improving technical momentum and reasonable valuation.
- Which companies have strong fundamentals but material legal or governance risks?
- How would a recession affect my current portfolio?
- Which sectors show positive relative strength but deteriorating earnings?
- Which trading ideas are supported by both technical and fundamental evidence?

The orchestrator should combine relevant engines and produce one coherent answer rather than multiple disconnected agent responses.

# 10. Evidence and Answer Quality Governance

## 10.1 Mandatory Quality Evaluation

Proposed evaluation weights:

| Dimension                     | Weight |
| ----------------------------- | ------ |
| Factual accuracy              | 25%    |
| Evidence and citation quality | 20%    |
| Analytical depth              | 15%    |
| Numerical accuracy            | 15%    |
| Contextual relevance          | 10%    |
| Risk and uncertainty coverage | 10%    |
| Clarity                       | 5%     |

## 10.2 Mandatory Rejection Conditions

Regenerate or block an answer when:

- A figure is fabricated.
- A citation does not support the claim.
- Stale data is presented as current.
- A legal allegation is represented as a final finding.
- A backtest result is invented or not reproducible.
- A target price is presented without a defensible methodology.
- A material contradiction is hidden.
- A calculation cannot be reproduced.
- A critical data dependency is missing.

## 10.3 Confidence and Uncertainty

Confidence must reflect evidence quality, completeness, freshness and consistency.

It must not be presented as the probability that a stock or strategy will make money.

# 11. Technical Architecture

## 11.1 Architecture Principles

- One Copilot orchestrator.
- Specialized intelligence engines.
- Deterministic financial calculation services.
- Centralized evidence and source registry.
- Structured response generation.
- Reusable visual components.
- Full auditability.

## 11.2 Proposed Agents / Engines

1. Copilot Orchestrator.
2. Stock Intelligence Engine.
3. Technical Analysis Engine.
4. Fundamental Analysis Engine.
5. Sector Intelligence Engine.
6. Macro Intelligence Engine.
7. News and Event Intelligence Engine.
8. Regulatory Intelligence Engine.
9. Legal Intelligence Engine.
10. Strategy Validation Engine.
11. F&O Intelligence Engine.
12. Risk Intelligence Engine.
13. Portfolio Intelligence Engine.
14. Learning Engine.
15. Evidence and Quality Engine.

Agents should be logical capabilities, not necessarily independent deployed microservices.

## 11.3 Deterministic Services

Use deterministic services for:

- Financial ratios.
- Technical indicators.
- Returns and volatility.
- Sector rankings.
- Portfolio exposure.
- Position sizing.
- P&L.
- Options Greeks and payoff.
- Backtesting.
- Drawdown.
- Stress testing.
- Scenario calculations.

LLMs should interpret, orchestrate and explain. They should not invent numerical results or replace deterministic financial calculations.

## 11.4 Existing Technology Context

- Backend: Python FastAPI.
- Frontend: React 18.
- UI: Tailwind CSS and Shadcn/UI.
- Charts: Recharts or suitable charting components.
- Database: PostgreSQL.
- Deployment: Docker.
- AI providers: OpenAI with Google Generative AI fallback.

Reuse the existing Nivesh data platform and canonical analytical engines wherever possible. Avoid creating duplicate stock, technical or fundamental calculation engines.

# 12. Proposed Data Model

Additional logical entities:

- `macro_indicators`
- `macro_events`
- `regulatory_events`
- `legal_events`
- `news_events`
- `entity_relationships`
- `event_impact_assessments`
- `sector_intelligence_daily`
- `strategy_validation_runs`
- `strategy_forward_runs`
- `evidence_registry`
- `intelligence_reports`
- `copilot_conversations`
- `copilot_messages`
- `copilot_response_components`
- `copilot_prompt_templates`
- `copilot_answer_blueprints`
- `copilot_source_citations`
- `copilot_quality_evaluations`

Every generated report should retain:

- Data snapshot/reference.
- Source references.
- Calculation methodology.
- Model and prompt version.
- Generation timestamp.
- Relevant assumptions.
- Quality evaluation.

# 13. Structured Copilot Response Contract

The backend must return a structured response rather than an unstructured text blob.

Logical response structure:

```
{
  "query": {
    "question": "",
    "intent": "",
    "entities": [],
    "time_horizon": ""
  },
  "answer": {
    "direct_response": "",
    "summary": "",
    "key_findings": [],
    "analysis_sections": [],
    "contradictions": [],
    "scenarios": [],
    "risks": [],
    "invalidation_conditions": [],
    "monitor_next": []
  },
  "visualizations": [
    {
      "type": "metric_cards",
      "title": "",
      "data": {},
      "source_refs": []
    }
  ],
  "metrics": [],
  "evidence": [],
  "data_quality": {
    "freshness": "",
    "completeness": "",
    "missing_data": [],
    "conflicts": []
  },
  "limitations": [],
  "confidence": {
    "level": "",
    "reason": ""
  },
  "methodology": {
    "model_version": "",
    "calculation_version": "",
    "data_snapshot": ""
  }
}
```

The visualization schema must be typed and validated. The frontend must render only supported component types and must never execute arbitrary model-generated code.

# 14. Frontend Component Architecture

Create a reusable Copilot response component library.

Proposed components:

- `CopilotMessage`
- `ExecutiveInsightCard`
- `MetricCardGroup`
- `StockAnalysisCard`
- `InteractivePriceChart`
- `FinancialTrendChart`
- `TechnicalIndicatorPanel`
- `SectorHeatmap`
- `ComparisonTable`
- `ScenarioComparison`
- `EventTimeline`
- `MacroImpactMap`
- `OptionsPayoffChart`
- `StrategyPerformancePanel`
- `RiskBreakdown`
- `PortfolioAllocationChart`
- `EvidencePanel`
- `DataQualityIndicator`
- `MethodologyAccordion`
- `FollowUpQuestionChips`

The frontend must support:

- Responsive layouts.
- Loading and streaming states.
- Empty and error states.
- Missing-data states.
- Expand/collapse sections.
- Chart timeframe changes where supported.
- Source navigation.
- Export and sharing.
- Accessible text alternatives.

# 15. Copilot Interaction and Differentiation

Three core capabilities should be prominent:

### 1. What changed and why?

Compare current information against historical data and explain the change.

### 2. Show me the evidence

Expose source documents, data points, calculations and methodology.

### 3. Challenge my investment thesis

Actively look for contradictory evidence, weaknesses, downside risks and assumptions that could invalidate the user's view.

Additional interactions:

- Explain this chart.
- Compare with peers.
- Show historical performance.
- What could go wrong?
- What data is missing?
- Simplify this answer.
- Turn this into a paper-trading idea.

# 16. Non-Functional Requirements

- Response generation must be performant and stream progressively.
- Data freshness must be visible.
- All material claims must be traceable.
- Financial calculations must be reproducible.
- User portfolios and conversations must be tenant-isolated.
- Sensitive portfolio information must be protected.
- Model outputs must be auditable.
- Source retrieval failures must be surfaced.
- The UI must remain usable on mobile.
- Visual components must degrade gracefully when data is unavailable.

# 17. Acceptance Criteria

A release is acceptable only when:

1. Users can ask questions through one unified chat interface.
2. The system correctly routes questions to relevant engines.
3. Stock analysis uses Nivesh's underlying market and financial data.
4. Macro, news, legal and regulatory answers cite original sources.
5. Strategy validation uses reproducible calculations and realistic costs.
6. Answers distinguish facts from inferences and projections.
7. Missing, stale and conflicting data are visible.
8. Visualizations use actual structured data.
9. Charts and tables are usable on mobile.
10. Users can inspect evidence and methodology.
11. The system can challenge a user's thesis.
12. Unsupported claims and invented calculations are blocked.

# 18. Success Metrics

**Product usage**

- Copilot weekly active users.
- Questions per active user.
- Follow-up question rate.
- Report save/share rate.
- Repeat usage.

**Answer quality**

- Factual accuracy.
- Citation support rate.
- Numerical calculation accuracy.
- Data freshness compliance.
- Unsupported claim rate.
- User-rated usefulness.

**Visual experience**

- Percentage of eligible answers with useful visualizations.
- Chart/table interaction rate.
- Evidence panel open rate.
- Mobile usability and response completion.
- User comprehension feedback.

**Trading education and validation**

- Percentage of ideas with explicit risk and invalidation.
- Strategy validation completion.
- Paper-trading adoption.
- Difference between backtest and forward-test results.
- User risk-discipline improvement.

# 19. Implementation Roadmap

## Phase 1 – Copilot Foundation

- Unified conversational interface.
- Intent classification and orchestration.
- Evidence registry and source citations.
- Structured response contract.
- Stock intelligence.
- Fundamental and technical visual components.
- Prompt library and answer blueprints.

## Phase 2 – Market and Event Intelligence

- Sector intelligence.
- Macro intelligence.
- News and corporate event intelligence.
- Regulatory and legal intelligence.
- Event timelines and macro impact maps.

## Phase 3 – Trading and Risk Intelligence

- Strategy builder.
- Strategy validation.
- F&O intelligence.
- Options payoff visualizations.
- Risk management.
- Paper-trading integration.

## Phase 4 – Portfolio and Personalization

- Portfolio intelligence.
- Personalized briefings.
- Portfolio stress testing.
- Personalized education.
- Historical conversation and analysis context.

## Phase 5 – Continuous Intelligence Quality

- Answer evaluation framework.
- Contradiction detection.
- Outcome tracking.
- Forward-test feedback.
- Source reliability monitoring.
- Model and prompt performance optimization.

# 20. Final Product Principle

Nivesh must not compete with general-purpose AI by merely providing better-written answers.

It must provide a fundamentally better financial intelligence experience through:

1. Proprietary and reliable financial data.
2. Historical evidence and reproducible calculations.
3. Connections between macro, sectors, companies and portfolios.
4. Contradictory evidence and thesis challenges.
5. Personalized risk and portfolio context.
6. Visually understandable analytical output.
7. Continuous validation against actual outcomes.

**The Copilot should feel like a financial research analyst, market intelligence terminal and personal financial educator combined into one simple conversational experience.**

**Product promise: Ask anything. See the evidence. Understand the impact. Make a more informed decision.**

## My recommendation for the actual UI

The most important design decision is to make the chat response itself a collection of reusable visual components. Don't send the user to a separate dashboard for every answer.

## Example: How a stock-analysis answer should look

CG Power – Intelligence Brief

Illustrative layout

Example structure only. No live stock assessment.

| Tile | Value | Note |
| --- | --- | --- |
| Fundamental quality | Strong | Based on selected metrics |
| Technical trend | Neutral | Illustrative status |
| Sector position | Above average | Illustrative comparison |
| Key concern | Valuation | Requires verification |

What the Copilot found

- Financial performance and cash-flow quality.
- Current technical structure.
- Sector and peer comparison.
- Ownership and institutional activity.

Evidence and analysis (each an expandable section)

- Financial performance — Open analysis
- Technical chart — Open chart
- News and corporate events — View timeline
- Sources and methodology — View evidence

Questions to explore next

- Compare with peers
- Check valuation
- Challenge this thesis

## One architectural recommendation I would treat as critical

Do not let the LLM decide how to draw arbitrary charts or generate frontend code. Instead:

1. The intelligence engine returns structured facts, metrics, evidence and visualization specifications.
2. A response composer decides which supported visual components are appropriate.
3. React renders those components using the existing Nivesh UI library.
4. Every chart and metric retains its source, timestamp and calculation reference.

This makes the visual experience consistent, testable, auditable and much safer for financial information.

The next implementation artifact worth producing is a detailed Copilot UI/UX specification with screen layouts, response-component designs, JSON contracts and React component behaviour, so your frontend and backend teams can build against the same specification.
