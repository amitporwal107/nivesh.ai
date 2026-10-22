# Nivesh Smart Money Intelligence — Market Data Source Inventory

**Document type:** Data-source inventory and implementation guide  
**Product:** Nivesh Market Intelligence / Smart Money Intelligence Engine  
**Market:** Indian equities, mutual funds and listed derivatives  
**Status:** Initial source inventory; verify access, schemas, licensing and availability before production use

## 1. Objective

Identify and integrate reliable data sources that help Nivesh determine:

- Where FII/FPI and DII capital is flowing at the overall market level.
- Which mutual funds and disclosed institutional shareholders are increasing or reducing stock holdings.
- Which sectors are strengthening or weakening.
- Which stocks show evidence consistent with accumulation or distribution.
- Whether those signals are confirmed by price, volume, derivatives, fundamentals and corporate events.

**Critical distinction:** Daily aggregate FII/DII cash flows do not reveal which individual stocks institutions bought or sold. Stock-level conclusions require holdings disclosures, disclosed transactions, shareholding filings and/or other clearly labelled market-activity proxies.

## 2. Institutional flow sources

| Source | Raw URL | Primary data | Intended use | Typical cadence |
|---|---|---|---|---|
| NSE FII/DII reports | https://www.nseindia.com/reports/fii-dii | Published FII/FPI and DII cash-market buy, sell and net values | Daily institutional-flow context, rolling trends, foreign selling versus domestic absorption | Daily, as published |
| NSE All Reports | https://www.nseindia.com/all-reports | Exchange reports across market segments | Discover and download market-wide reports | Daily / report-dependent |
| SEBI FPI investment statistics | https://www.sebi.gov.in/statistics/fpi-investment.html | FPI investment statistics and other published FPI information | Cross-check foreign investment trends and available asset-class data | Report-dependent |
| AMFI portfolio disclosures | https://www.amfiindia.com/online-center/portfolio-disclosure | Mutual-fund scheme portfolio disclosures | Stock-level scheme holdings and changes across reporting dates | Typically monthly |
| AMFI monthly data | https://www.amfiindia.com/research-information/amfi-monthly | Mutual-fund industry flows, AUM and category statistics | Industry-level flow and allocation context | Monthly |

### Derived features

- Daily net flow: `buy_value - sell_value` where source definitions support that calculation.
- Rolling net flow over 5, 20 and 60 sessions.
- Cumulative net flow and buying/selling streaks.
- Flow acceleration/deceleration and historical percentile.
- Foreign-versus-domestic flow divergence.
- Flow regime relative to index performance and volatility.

**Data rule:** preserve source labels and definitions. Do not combine incompatible categories or exchange-specific totals without documenting the calculation.

## 3. Exchange market activity: prices, delivery, deals and derivatives

| Source | Raw URL | Data to investigate | Intelligence use |
|---|---|---|---|
| NSE All Reports | https://www.nseindia.com/all-reports | Equity bhavcopy, security-wise deliverable positions, bulk/block deals, short-selling and volatility reports where available | Price/volume anomalies, delivery trends, deal activity and historical validation |
| NSE bulk/block deals | https://www.nseindia.com/report-detail/display-bulk-and-block-deals | Published transaction details, such as client, side, quantity, price and date where disclosed | Large disclosed transactions; investigate potential ownership changes |
| NSE derivatives reports | https://www.nseindia.com/all-reports-derivatives | Participant-wise open interest, participant-wise trading volume, FII derivatives statistics, contract data and combined OI where published | Derivatives positioning and sentiment |
| NSE OI spurts | https://www.nseindia.com/market-data/oi-spurts | Open-interest changes | Unusual contract activity |
| NSE derivatives market snapshot | https://www.nseindia.com/market-data/analysis-and-tools-derivatives-market-snapshot | Futures/options market statistics | Derivatives activity and market structure |
| BSE market reports | https://www.bseindia.com/markets/equity/EQReports/MRC.aspx?Type=1 | Published BSE cash-market reports | Cross-exchange validation |
| BSE India | https://www.bseindia.com/ | Exchange data and disclosures | Additional market reports and corporate filings |

### Interpretation cautions

- Rising delivery participation may support an accumulation hypothesis, but delivery data does not identify the buyer.
- Rising open interest is not inherently bullish or bearish. Interpret it with price direction, contract type and available participant data.
- A bulk/block deal can be a transfer between investors rather than new institutional demand.
- Treat cash-market activity and derivatives positioning as separate signals.
- Confirm exact report names, schemas, historical availability and access conditions during implementation; exchange portals and report URLs can change.

## 4. Mutual-fund portfolio and flow intelligence

| Source | Raw URL | Use |
|---|---|---|
| AMFI portfolio disclosures | https://www.amfiindia.com/online-center/portfolio-disclosure | Scheme-level portfolio files |
| AMFI scheme-wise disclosure page | https://www.amfiindia.com/otherdata/scheme-wise-disclosure | Additional scheme-level disclosure access; verify current route and availability |
| AMFI monthly data | https://www.amfiindia.com/research-information/amfi-monthly | Industry flows, AUM and category trends |
| AMFI scheme details | https://www.amfiindia.com/research-information/other-data/scheme-details | Scheme identifiers and classifications, where provided |
| AMFI NAV history | https://www.amfiindia.com/nav-history-download | Historical mutual-fund NAV data |
| Individual AMC websites | Example: https://www.sbimf.com/ | Cross-check factsheets and portfolio disclosures |

### Features to calculate

1. **Share-count change:** current disclosed shares minus prior disclosed shares.
2. **Holding percentage change:** change relative to prior disclosed shares, with explicit handling of zero or missing prior holdings.
3. **Portfolio-weight change:** current portfolio weight minus prior portfolio weight.
4. **Accumulation breadth:** count of independent schemes increasing exposure.
5. **New position / exit:** position first appearing or disappearing between disclosures.
6. **Concentration:** whether changes are broad-based or concentrated in a small number of schemes.
7. **Estimated holding-value change:** separate share-count effects from price effects.
8. **Disclosure freshness:** age of the latest available holding record.

### Important caveats

- A higher market value may simply reflect a higher stock price. Compare shares held and portfolio weights, not value alone.
- Several schemes may belong to the same AMC; avoid treating them as fully independent evidence.
- A position disappearing from a file may reflect a reporting, classification or mapping issue. Validate before calling it a complete exit.
- Monthly holdings are delayed disclosures, not real-time buying signals.
- Store the reporting date and actual publication/availability timestamp separately.

## 5. Company ownership and corporate-event sources

| Source | Raw URL | Data | Use |
|---|---|---|---|
| NSE shareholding-pattern filings | https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern | Reported ownership by shareholder category and disclosed holders, as available | Quarterly ownership changes |
| NSE corporate announcements | https://www.nseindia.com/companies-listing/corporate-filings-announcements | Company announcements and material events | Explain changes in price, volume or institutional interest |
| NSE financial results | https://www.nseindia.com/companies-listing/corporate-filings-financial-results | Published company results | Earnings and fundamental confirmation |
| BSE corporate announcements | https://www.bseindia.com/corporates/ann.html | Company filings and announcements | Cross-exchange event coverage |
| BSE shareholding pattern | https://www.bseindia.com/markets/equity/EQReports/ShareholdingPattern.aspx | Ownership disclosures where available | Cross-check shareholding changes |
| SEBI | https://www.sebi.gov.in/ | Regulatory filings, disclosures and enforcement information | Regulatory and corporate-risk intelligence |

### Features to derive

- FPI, DII, mutual-fund, insurance and other disclosed institutional ownership changes.
- New institutional holders and changes in shareholder concentration.
- Promoter holding reductions and pledge changes where reported.
- Results, contract wins, acquisitions, regulatory actions and other material events.
- Ownership changes alongside price performance and sector trends.

**Caveat:** shareholding patterns are periodic disclosures. Do not present quarterly ownership data as live institutional activity.

## 6. Licensed real-time and historical market-data providers

Public reports may be sufficient for an initial EOD prototype. A production service may need licensed feeds for reliable historical data, intraday prices, corporate actions, normalized identifiers and service-level commitments.

| Provider | Raw URL | Evaluate for | Checks before procurement |
|---|---|---|---|
| NSE Data & Analytics | https://www.nseindia.in/static/nse-data-and-analytics/data-information-vending | Official exchange real-time, end-of-day, historical and corporate data products | Required products, entitlements, history depth, delivery method, latency and redistribution rights |
| BSE India | https://www.bseindia.com/ | Exchange market data and disclosures | Coverage, historical access, delivery and licensing |
| TrueData | https://www.truedata.in/ | Potential commercial real-time and historical Indian market feeds | Exchange/segment coverage, intraday bars, derivatives, uptime, history and rights |
| Global Datafeeds | https://globaldatafeeds.in/ | Potential commercial exchange feeds and historical data | Product coverage, API/feed access, data quality, licensing and service terms |

These are candidates for evaluation, not a guarantee that every dataset is included in standard packages.

### Procurement checklist

- Written permission for commercial use and user-facing display.
- Rights to calculate and redistribute derived indicators and scores.
- Historical depth, adjustments and corporate-action handling.
- Intraday latency, update frequency and uptime/SLA.
- API limits, concurrent connections and rate limits.
- Data corrections, missing bars and outage handling.
- Exchange segment coverage and instrument identifiers.
- Restrictions on storage, caching and retention.
- Cost at the expected symbol count and user scale.

## 7. Fundamental, macroeconomic and sector data

| Source | Raw URL | Use |
|---|---|---|
| NSE financial results | https://www.nseindia.com/companies-listing/corporate-filings-financial-results | Results, revenue, margins and earnings context |
| BSE corporate announcements | https://www.bseindia.com/corporates/ann.html | Material corporate events |
| RBI | https://www.rbi.org.in/ | Rates, liquidity, banking and macroeconomic information |
| MoSPI | https://www.mospi.gov.in/ | Inflation, GDP, industrial production and official economic releases |
| Nifty Indices | https://www.niftyindices.com/ | Index methodology, constituents and sector benchmarks |
| NSE India | https://www.nseindia.com/ | Market breadth, sector activity and index performance |

### Derived context

- Earnings surprises and changes in reported fundamentals.
- Sector-specific regulatory, commodity or policy catalysts.
- RBI policy and macroeconomic event calendars.
- Sector relative strength and market breadth.
- Correlation of institutional-flow regimes with sector performance.

## 8. Recommended source-to-feature mapping

| Feature | Primary source | Target refresh |
|---|---|---|
| FII/FPI and DII cash flows | NSE; cross-check with other published sources | Daily, after publication |
| Mutual-fund stock accumulation | AMFI and AMC portfolio disclosures | On publication; typically monthly |
| FPI/DII ownership changes | NSE/BSE shareholding filings | On filing; typically quarterly |
| Bulk/block deals | NSE/BSE | Daily or as published |
| Delivery and abnormal volume | Exchange security-wise reports | EOD; intraday only with an appropriate licensed feed |
| Derivatives participant positioning | NSE derivatives reports | Daily, after publication |
| Sector rotation | Prices, volumes and index constituents | EOD; intraday with licensed feeds |
| Fundamentals and corporate events | Exchange filings | On publication |
| Smart Money Score | Validated upstream features | Daily, with event-driven recalculation |
| AI explanations and alerts | Nivesh signal engine | When a meaningful signal changes |

Refresh intervals are design targets, not guarantees of source publication times.

## 9. Suggested ingestion architecture

1. **Source collectors:** fetch files or call approved APIs; record source URL, retrieval time, reporting date and status.
2. **Immutable raw storage:** retain source payloads and checksums where licensing permits.
3. **Parsing and validation:** normalize file formats, schemas, units, currencies and date conventions.
4. **Identifier reconciliation:** use ISIN as a preferred key where available; map to exchange symbols and canonical Nivesh instruments.
5. **Normalized database:** store flows, holdings, deals, prices, derivatives and corporate events separately.
6. **Feature generation:** compute rolling flows, holding deltas, relative strength, volume anomalies and freshness.
7. **Signal generation:** calculate accumulation/distribution scores with evidence references and data confidence.
8. **API and UI:** expose ranked candidates, charts, time periods, evidence and invalidation conditions.
9. **Monitoring:** alert on failed jobs, stale sources, duplicate files, schema changes and reconciliation errors.

### Suggested core tables

- `institutional_flow_daily`
- `institutional_holdings_monthly`
- `institutional_ownership_changes`
- `market_deals`
- `market_prices_daily`
- `market_delivery_daily`
- `derivatives_participant_daily`
- `corporate_events`
- `sector_flow_features`
- `smart_money_features_daily`
- `smart_money_signals`
- `smart_money_backtest_results`
- `data_source_runs`

Each normalized record should carry source provenance and relevant timestamps. Store raw disclosures separately from derived features and scores so historical signals can be reproduced.

## 10. Data quality and point-in-time controls

- Separate trading date, reporting date, publication time and ingestion time.
- Preserve provisional/final status and source revisions.
- Detect duplicate files and duplicate records.
- Validate quantities, prices, totals, missing fields and unexpected schema changes.
- Reconcile NSE/BSE records carefully; do not sum the same market-wide statistic twice.
- Handle ISIN changes, corporate actions, mergers, splits and symbol changes.
- Track stale or missing observations and lower signal confidence accordingly.
- Use only data that was available at the historical signal timestamp in backtests.
- Keep a record of every feature value used to generate each historical signal.
- Do not use a language model to invent missing market observations.

## 11. Initial implementation priorities

### Phase 1 — Market-flow foundation
- NSE daily FII/DII flows.
- NSE EOD prices and available delivery reports.
- Rolling flow analytics and market-wide dashboard.
- Source freshness, history and data-quality monitoring.

### Phase 2 — Mutual-fund and ownership intelligence
- AMFI scheme portfolio ingestion.
- ISIN-level reconciliation.
- Share-count and portfolio-weight changes.
- NSE/BSE shareholding patterns and corporate announcements.

### Phase 3 — Accumulation and distribution signals
- Bulk/block deal processing.
- Derivatives participant reports.
- Price/volume/relative-strength confirmation.
- Smart Money Score with explicit evidence and confidence.

### Phase 4 — Predictive intelligence
- Point-in-time historical dataset.
- Walk-forward backtests.
- Forward returns, benchmark-relative returns and drawdown.
- Transaction-cost and liquidity assumptions.
- Alerts when a signal strengthens, weakens or is invalidated.

## 12. Success metrics

Evaluate the system on more than the number of stocks flagged:

- **Data coverage:** fraction of the target universe with valid and fresh inputs.
- **Signal precision:** fraction of flagged stocks that outperform an appropriate benchmark over a predefined horizon.
- **Risk-adjusted results:** returns after realistic costs, maximum drawdown and downside risk.
- **Lead time:** whether signals precede a breakout or merely follow it.
- **Robustness:** performance across market regimes, sectors and market-cap groups.
- **Calibration:** whether predicted probabilities align with observed frequencies.
- **Reproducibility:** whether historical signals can be rebuilt from information available at the time.

## 13. Key design principle

Keep two concepts separate in the UI and data model:

1. **Observed institutional activity:** directly supported by reported flows, holdings or disclosed transactions.
2. **Inferred smart-money activity:** a hypothesis based on price, volume, delivery, derivatives and other indirect signals.

Every signal should show its evidence, data timestamps, confidence, risks and invalidation criteria. This distinction is central to making Nivesh's market intelligence explainable, auditable and suitable for historical validation.


---

# Product Requirements Addendum: Stock-Level FII/DII/MF Money-Flow Intelligence

**Purpose:** Extend the source inventory above into an implementable Nivesh feature that identifies which stocks show disclosed institutional accumulation/distribution and which stocks show indirect evidence of emerging institutional interest.

## 14. Product objective

Nivesh shall help users answer:

1. Which stocks have demonstrable changes in FII/FPI, DII or mutual-fund ownership?
2. Which mutual-fund schemes are increasing or reducing their holdings?
3. Which stocks have the broadest and most persistent institutional accumulation evidence?
4. Which stocks show possible current accumulation based on market activity, despite the absence of real-time stock-level institutional trade disclosure?
5. Which sectors are attracting or losing institutional interest?
6. How fresh, complete and reliable is the evidence for each conclusion?

The feature is an **intelligence and research tool**, not a claim to observe every institutional order in real time and not an automated trading instruction.

## 15. Scope

### In scope

- Stock-level institutional ownership change analysis.
- Mutual-fund scheme portfolio comparisons across reporting periods.
- FII/FPI and DII ownership change analysis where disclosed.
- Bulk/block deal ingestion and participant/entity resolution where disclosed.
- Daily aggregate FII/DII cash-flow context.
- Price, volume, delivery and relative-strength confirmation.
- Sector rotation and accumulation/distribution breadth.
- A ranked stock scanner with filters, evidence, confidence, freshness and risk factors.
- AI explanations grounded in structured data and source records.
- Historical point-in-time validation and performance reporting.
- Watchlists and user-configurable alerts for changes in evidence.

### Out of scope for the initial release

- Claiming to know every FII/DII stock purchase in real time.
- Inferring a specific institution's undisclosed position from price or volume alone.
- Treating every bulk/block deal as fresh institutional accumulation.
- Automatic order placement or broker execution.
- Presenting a score as a guaranteed prediction of future returns.

## 16. User stories

- As a retail investor, I want to see stocks where mutual-fund holdings have increased across successive disclosures.
- As an active trader, I want to find stocks where disclosed institutional interest aligns with price strength, volume and delivery signals.
- As a research analyst, I want to inspect the underlying scheme, holding quantity, reporting period and source for every ownership-change claim.
- As a portfolio manager, I want to compare accumulation breadth across sectors and market-cap groups.
- As a risk-conscious user, I want to know when the evidence is stale, contradictory, concentrated or invalidated.
- As a Nivesh operator, I want failed source jobs, schema changes, missing records and low-confidence mappings surfaced before they affect scores.

## 17. Stock-level evidence model

Every signal must be assigned an evidence class. Do not combine these classes into a single unqualified claim.

| Evidence class | Meaning | Permitted user-facing language |
|---|---|---|
| **A — Disclosed holdings change** | A reported holder or scheme's disclosed shares/ownership changed between known reporting dates | “Reported holdings increased/decreased between [date] and [date].” |
| **B — Disclosed transaction** | A published deal or filing identifies a transaction and the relevant disclosed participant information | “A disclosed transaction was reported on [date].” |
| **C — Market-activity proxy** | Price, volume, delivery, relative strength or derivatives activity is consistent with accumulation/distribution but does not identify the buyer/seller | “Market activity is consistent with possible accumulation.” |
| **D — Composite inference** | Multiple independent evidence classes align | “Multiple signals suggest possible institutional accumulation; direct stock-level confirmation is incomplete.” |
| **Insufficient evidence** | Inputs are missing, stale, ambiguous or contradictory | “Insufficient evidence to classify.” |

A stock can have more than one evidence class at the same time. Each class must retain its own timestamps and sources.

## 18. Required scanner filters

The Smart Money Stock Scanner should support:

- **Investor type:** All, FII/FPI, DII, mutual funds, insurance/other disclosed institutions.
- **Signal type:** Accumulation, distribution, mixed, newly disclosed position, exit, strengthening, weakening.
- **Universe:** Nifty 500, Nifty 1000, all supported liquid NSE equities, custom watchlist.
- **Lookback:** 1 month, 3 months, 6 months, 12 months, plus custom reporting-date range.
- **Evidence class:** Disclosed holdings, disclosed transaction, market proxy, composite inference.
- **Signal score:** Configurable minimum score and ranking.
- **Data confidence:** High, medium, low, insufficient.
- **Freshness:** Fresh, ageing, stale.
- **Sector and market-cap bucket.**
- **Liquidity and trading-value floor.**
- **Price confirmation:** Above/below EMA20, EMA50, EMA200; relative strength; breakout status.
- **Volume/delivery confirmation:** Abnormal volume, delivery participation change, persistence.
- **Ownership breadth:** Number of schemes/independent reporting entities increasing or reducing exposure.
- **Event filters:** Results, corporate announcements, bulk/block deals and other material events where available.

The UI must state that the universe and filters affect coverage. A stock excluded by liquidity or data-availability rules must not silently disappear from coverage reporting.

## 19. Stock-level output columns

Each scanner result should include:

1. Stock name, exchange symbol, ISIN and sector.
2. Current price and as-of timestamp, where licensed/available.
3. Investor category and evidence class.
4. Prior and current holding quantity, reporting dates and quantity change.
5. Prior and current portfolio weight, where available, and percentage-point change.
6. Reported ownership percentage and change, where available.
7. Count of schemes/entities increasing holdings and count reducing holdings.
8. New position or exit status, with validation notes.
9. Disclosed deal details and source reference, where applicable.
10. Daily aggregate FII/DII flow context, explicitly labelled as market-wide rather than stock-specific.
11. Price relative strength, trend and breakout state.
12. Volume and delivery indicators with their calculation periods.
13. Sector trend and breadth.
14. Smart Money Accumulation Score and Distribution Score, displayed separately.
15. Data confidence, data completeness and freshness.
16. Positive evidence, contradictory evidence and potential invalidation conditions.
17. Source links and last updated time.
18. Historical signal date and subsequent validation metrics, if available.

## 20. Feature definitions and calculation rules

### 20.1 Mutual-fund holdings

For each scheme–ISIN pair and reporting date:

- `shares_delta = shares_current - shares_previous`
- `shares_pct_change = shares_delta / shares_previous` only when prior shares are greater than zero.
- `portfolio_weight_delta_pp = weight_current_pct - weight_previous_pct`
- `new_position = shares_previous == 0 and shares_current > 0`, only after checking corporate actions, identifier changes and file coverage.
- `potential_exit = shares_previous > 0 and shares_current == 0`, pending validation that the current file is complete and the scheme/ISIN mapping is stable.

Store absolute share changes separately from holding-value changes. Do not infer buying from a market-value increase alone.

### 20.2 Breadth and concentration

- Count schemes increasing exposure, reducing exposure and unchanged.
- Group schemes by AMC or common fund family to avoid overstating independent confirmation.
- Compute capital/portfolio-weighted changes only where the required data is available and comparable.
- Flag when the signal is driven by one scheme, one AMC or a small number of holders.
- Where reporting records cannot be reliably treated as independent, label breadth as a raw scheme count rather than independent institutional confirmation.

### 20.3 FII/FPI and DII ownership

- Compare disclosed shareholding categories across reporting periods.
- Store reported ownership percentage and percentage-point change.
- Preserve the original category labels and filing dates.
- Do not interpret aggregate daily FII/DII net flow as a stock-level ownership change.
- Handle category reclassification, public-float changes, share issuance, buybacks and corporate actions.

### 20.4 Market-activity proxies

Potential features include:

- Relative volume against a comparable historical baseline.
- Delivery quantity and delivery participation changes where valid data is available.
- Price return and relative strength against sector and broad-market benchmarks.
- EMA20/EMA50/EMA200 trend alignment.
- Consolidation range, breakout and failed-breakout state.
- Abnormal price/volume activity and persistence over multiple sessions.
- Futures open-interest and participant positioning where available, kept separate from cash ownership evidence.
- Liquidity, spread and gap risk.

These features are **proxies**, not proof that an institution is the buyer. Document the formulas and their limitations.

## 21. Proposed scoring model

Use two separate scores rather than one ambiguous score:

- **Accumulation Score (0–100)**
- **Distribution Score (0–100)**

An initial accumulation model for research and validation may allocate:

| Component | Initial weight |
|---|---:|
| Disclosed institutional ownership/holding changes | 25% |
| Volume and delivery confirmation | 20% |
| Price structure and relative strength | 20% |
| Sector and market-wide flow context | 15% |
| Fundamental quality | 10% |
| Persistence and breadth | 10% |
| **Total** | **100%** |

These weights are hypotheses for an initial baseline, not validated predictive coefficients. Build a corresponding distribution model with appropriately inverted/defined signals and explicit treatment of conflicting evidence.

### Scoring requirements

- Normalize features using documented methods and suitable historical baselines.
- Prevent duplicate or highly correlated features from receiving undue weight.
- Apply explicit missing-data rules; do not silently impute missing ownership data as zero.
- Track data completeness separately from signal strength.
- Penalize stale records, low-quality mappings, low liquidity and conflicting evidence.
- Keep direct disclosure evidence distinguishable from market-proxy evidence.
- Display component contributions and the main factors that raised or lowered the score.
- Version every scoring configuration and retain the feature snapshot used for each signal.
- Calibrate weights only after point-in-time walk-forward testing and out-of-sample evaluation.

### Suggested display bands

| Score | Label | Interpretation |
|---|---|---|
| 75–100 | Strong evidence | Multiple supportive signals; still requires risk checks |
| 50–74 | Developing | Some evidence, but confirmation is incomplete |
| 0–49 | Weak or mixed | Evidence is weak, contradictory or insufficient |

These are display bands, not probabilities of a price increase. Do not label a score as “75% probability” unless a separately validated probability model supports that interpretation.

## 22. Data confidence and freshness

Provide separate fields for:

- `data_confidence`: high / medium / low / insufficient.
- `data_completeness_pct`: percentage of required features successfully populated, with a documented denominator.
- `latest_reporting_date`: last date the source says the record describes.
- `published_at`: publication timestamp if known.
- `retrieved_at`: time Nivesh collected the source.
- `processed_at`: time parsing/normalization completed.
- `freshness_status`: fresh / ageing / stale.
- `mapping_confidence`: confidence that source security/scheme maps to the canonical instrument.
- `evidence_class`: A, B, C or D as defined above.

Freshness thresholds must be source-specific. A monthly mutual-fund portfolio should not be marked stale merely because it is not daily; it should be evaluated against its expected publication cadence and the latest expected disclosure.

## 23. UI/UX requirements

### 23.1 Smart Money overview

Show:

- Latest published aggregate FII/FPI and DII net flows.
- 5-, 20- and 60-session flow trends.
- Sectors with strengthening and weakening evidence.
- Top accumulation and distribution candidates.
- Number of stocks with fresh, ageing and stale evidence.
- Clear as-of dates and data-source status.

### 23.2 Stock scanner

Provide filter controls from Section 18 and a sortable table from Section 19. Use compact, mobile-first presentation with a detailed stock view for drill-down.

### 23.3 Stock evidence detail

For each stock, show:

- Timeline of reported holdings and disclosed transactions.
- Scheme/holder-level changes where disclosure permits.
- Price, volume and delivery chart with signal dates.
- Sector-relative-strength context.
- Accumulation and distribution score history.
- Evidence supporting the signal and evidence against it.
- Data freshness, confidence, source links and known limitations.
- Conditions that would invalidate the current interpretation.

### 23.4 AI Copilot questions

Support natural-language queries such as:

- “Which Nifty 500 stocks had the broadest mutual-fund accumulation over the last three disclosed months?”
- “Which stocks have increasing disclosed institutional ownership and positive sector-relative strength?”
- “Show stocks where delivery activity and price strength are improving, but ownership confirmation is not yet available.”
- “Which stocks have both accumulation and distribution evidence?”
- “Which high-scoring signals are based on stale or incomplete disclosures?”
- “What changed in institutional holdings for this stock between the last two reporting periods?”

AI responses must be grounded in stored records, identify the period used and link to supporting evidence. If data is unavailable, the assistant must say so.

## 24. API requirements

Suggested endpoints (final route names may follow existing Nivesh API conventions):

- `GET /api/market-intelligence/smart-money/overview`
- `GET /api/market-intelligence/smart-money/stocks`
- `GET /api/market-intelligence/smart-money/stocks/{symbol}`
- `GET /api/market-intelligence/smart-money/stocks/{symbol}/holdings-history`
- `GET /api/market-intelligence/smart-money/stocks/{symbol}/evidence`
- `GET /api/market-intelligence/smart-money/sectors`
- `GET /api/market-intelligence/smart-money/flows`
- `GET /api/market-intelligence/smart-money/data-quality`
- `GET /api/market-intelligence/smart-money/backtest`

Support pagination, sorting, filter parameters, `as_of`/reporting-date filters, source metadata and stable response schemas. APIs must not mix real-time price timestamps with delayed ownership-reporting dates without explicitly labelling them.

## 25. Data model additions

In addition to the tables in Section 9, add or extend:

### `institutional_holding_observations`

Suggested fields:

- `id`
- `reporting_entity_id`
- `entity_type` (scheme, AMC, FPI, DII category, other disclosed holder)
- `scheme_id` nullable
- `instrument_id`
- `isin`
- `reporting_date`
- `published_at` nullable
- `shares_held` nullable
- `holding_pct` nullable
- `portfolio_weight_pct` nullable
- `holding_value` nullable
- `source_id`
- `source_document_id`
- `retrieved_at`
- `mapping_confidence`
- `record_status`

### `institutional_holding_deltas`

Suggested fields:

- `instrument_id`
- `reporting_entity_id`
- `previous_reporting_date`
- `current_reporting_date`
- `previous_shares`
- `current_shares`
- `shares_delta`
- `shares_pct_change` nullable
- `previous_weight_pct` nullable
- `current_weight_pct` nullable
- `weight_delta_pp` nullable
- `change_class` (increase, decrease, new, possible_exit, unchanged, unknown)
- `validation_status`
- `source_references`

### `smart_money_signal_snapshots`

Suggested fields:

- `instrument_id`
- `signal_timestamp`
- `accumulation_score`
- `distribution_score`
- `data_confidence`
- `data_completeness_pct`
- `evidence_classes`
- `feature_snapshot_version`
- `scoring_model_version`
- `positive_evidence`
- `negative_evidence`
- `invalidation_conditions`
- `source_references`

Add appropriate indexes for instrument/date, entity/date, reporting date and scanner filters. Use foreign keys where appropriate. Store source payloads only as permitted by source terms.

## 26. Acceptance criteria

The feature is ready for release when:

1. Daily aggregate FII/DII records can be traced to source and date.
2. Mutual-fund holdings from two or more reporting periods can be reconciled by stable instrument and scheme identifiers.
3. Share-count changes are computed separately from market-value changes.
4. New positions and exits are validated against missing files, identifier changes and corporate actions.
5. Every stock-level claim is labelled as disclosed evidence, market proxy or composite inference.
6. The scanner supports investor type, signal, universe, lookback, sector, score, confidence and freshness filters.
7. The stock detail view displays evidence, dates, sources and contradictory signals.
8. Missing/stale data lowers confidence or results in “insufficient evidence”; it is not silently treated as zero.
9. Historical scoring uses only records available at the original signal timestamp.
10. Backtests include a benchmark, predefined horizons, liquidity rules, transaction costs where relevant, and out-of-sample evaluation.
11. Every score can be reproduced from a stored feature snapshot and model version.
12. UI labels do not imply real-time institutional order visibility where only delayed or indirect evidence exists.

## 27. Historical validation plan

- Define horizons before testing, for example 5, 20 and 60 trading sessions.
- Compare subsequent returns against an appropriate market/sector benchmark.
- Report hit rate, excess return, drawdown, turnover and performance by sector and market-cap group.
- Include transaction costs and liquidity constraints for strategy-like evaluations.
- Use walk-forward testing and point-in-time data.
- Respect actual filing publication times, not merely the reporting period end date.
- Avoid survivorship bias by preserving historical universe membership.
- Compare the model with simple baselines such as relative strength alone, ownership change alone and equal-weight combinations.
- Report confidence intervals and sample sizes; do not claim predictive success from a small number of examples.

## 28. Delivery roadmap

### Phase 1 — Reliable data foundation
- Ingest daily FII/DII aggregate flows.
- Ingest EOD prices and available delivery data.
- Establish source provenance, timestamps, monitoring and reconciliation.

### Phase 2 — Disclosed stock-level institutional changes
- Ingest AMFI/AMC portfolio disclosures.
- Reconcile schemes, ISINs and corporate actions.
- Calculate share-count and portfolio-weight deltas.
- Ingest NSE/BSE shareholding patterns and deal disclosures.

### Phase 3 — Scanner and explainable scoring
- Build accumulation/distribution features.
- Add evidence classification, confidence and freshness.
- Implement stock scanner, stock detail and source-linked explanations.

### Phase 4 — Validation and alerts
- Run point-in-time walk-forward validation.
- Calibrate scoring and probability outputs only when justified.
- Add alerts for meaningful score changes, new disclosures and invalidation.

## 29. Final product principle

Nivesh must clearly distinguish:

- **Where institutional money has demonstrably moved** — supported by reported holdings or disclosed transactions.
- **Where market activity suggests possible ongoing accumulation** — inferred from price, volume, delivery, derivatives and other indirect features.
- **Where the evidence is incomplete** — clearly labelled as unknown rather than converted into a confident claim.

This evidence-first approach enables Nivesh to identify stocks attracting disclosed institutional interest and stocks worth investigating for possible emerging accumulation, while avoiding unsupported claims of real-time institutional order-flow visibility.


---

# Product Requirements Addendum: Stock Selection and Recommendations Using Smart Money Intelligence

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

---

# PRD Governance Addendum: Review Disposition and Implementation Decisions
**Date:** 2026-10-22  
**Purpose:** Resolve implementation risks raised in the Requirement Review of Smart Money Recommendations (§30–42).  
**Authority:** This addendum governs implementation where earlier sections of this document conflict with it. It does not claim that unresolved product, data, or regulatory decisions have already been approved.

## 43. Executive decision

The Smart Money Intelligence and Stock Recommendations capability remains a valid product objective, but the earlier recommendation addendum is **not implementation-ready as written**. Engineering must not create a parallel composite engine or enable direct stock recommendations on the basis of the earlier scoring proposal.

The implementation must follow these principles:

1. **One canonical stock-opportunity engine.** Reconcile the requirements with `docs/INTEGRATED_STOCK_ENGINE_DESIGN.md` before coding. Do not independently implement a second set of weights, states, gates, or snapshots.
2. **Separate opportunity quality from trade readiness.** Institutional accumulation evidence is not an entry signal. Entry readiness requires its own setup, trigger, invalidation, liquidity, and risk checks.
3. **No unsupported institutional claims.** If direct holdings evidence is unavailable or stale, do not describe a stock as institutionally accumulated. Market proxies must be visibly labelled as proxies.
4. **No production headline composite until validation.** The proposed 25/25/20/15/15 weights and 80/65/50 bands are provisional ideas only; they are not approved production thresholds.
5. **Fail safely on compliance.** Keep direct stock recommendations disabled until the organisation's applicable SEBI registration, permitted output scope, disclaimers, review process, and record-keeping requirements are confirmed by qualified compliance/legal reviewers.
6. **Reuse existing risk and recommendation infrastructure.** Extend the current planner and recommendation UI where suitable instead of duplicating them.
7. **Preserve point-in-time evidence and auditability.** Capture the data publication/availability time, feature snapshot, engine/config version, gate results, and reason codes for every evaluated candidate before any user-facing rollout.

## 44. Canonical design and score ownership

### 44.1 Required decision

Before implementation, the product owner and engineering lead must explicitly designate one canonical design between:

- `docs/INTEGRATED_STOCK_ENGINE_DESIGN.md`; and
- the Smart Money Recommendations addendum in this document.

**Recommended default:** Use `docs/INTEGRATED_STOCK_ENGINE_DESIGN.md` as the canonical engine design because the review reports that it specifies the existing score composition, missing-data handling, gates, status vocabulary, API placement, and daily snapshot more concretely. Treat this document as the product requirements and data-source specification, and update it to reference the canonical engine rather than re-specifying a competing score.

This is a recommendation for approval, not a claim that the repository's owners have already approved the choice.

### 44.2 Score namespace and ownership

Do not create a new field that ambiguously reuses `final_score`, `band`, or `accumulation_score`.

Before adding or changing a score, document:

- its exact purpose and scale;
- whether it measures opportunity quality, entry readiness, risk, or a market proxy;
- its input features and weights;
- its missing-data and coverage rules;
- its calibration and validation status;
- its relationship to the current user-visible score and band;
- its owner, version, and deprecation plan.

If a dedicated stock-level smart-money metric is retained, use the explicit name `smart_money_accumulation_score`. Do not overload the existing `accumulation_score` fields, which the review reports exist on different scales in different tables.

### 44.3 Provisional weights and bands

The weights in §32 and the fixed bands in §32 must be treated as **unapproved hypotheses**, not release requirements. They must not be wired into production as fixed business rules before evaluation.

The existing production bands already use the 80/65/50 boundaries with different labels. Do not introduce a second interpretation of those values in the same product.

A proposed new score must be evaluated against:
- the live score distribution;
- a simple baseline and existing score;
- sector and market-cap slices where sample size permits;
- out-of-time performance;
- coverage and missingness;
- stability across market regimes, with limitations disclosed where the available history is insufficient.

Percentile bands may be evaluated as an alternative, but must not be adopted automatically: percentile ranks are relative to the selected universe and do not by themselves establish predictive value or investment suitability.

## 45. Smart Money evidence eligibility and coverage

### 45.1 Evidence classes

Every smart-money signal must distinguish:

- **Direct disclosed evidence:** disclosed mutual-fund holdings and changes, shareholding-pattern disclosures, bulk/block deals, and other attributable filings where the source supports the claim.
- **Market proxies:** delivery percentage, relative volume, price/volume behaviour, and other indirect signals.
- **Unavailable or stale evidence:** missing, delayed, unmapped, or insufficiently current data.

A proxy may contribute to a separately named accumulation/market-pressure feature, but must not be presented as proof of FII, DII, or mutual-fund buying.

### 45.2 Missing direct evidence

When direct institutional evidence is missing, the engine must not silently redistribute its weight and continue labelling the result a Smart Money score.

The canonical engine owner must choose and document one of these policies before implementation:

1. **Evidence-gated Smart Money classification:** no institutional-accumulation classification unless minimum direct evidence requirements are met; or
2. **Split outputs:** publish a direct-evidence coverage/status field separately from a market-proxy score, and prohibit proxy-only results from being labelled “institutional accumulation.”

**Recommended default:** Use the split-output policy, with an explicit `direct_evidence_status`, `direct_evidence_coverage_pct`, `proxy_coverage_pct`, `evidence_as_of`, and `evidence_sources` field set. A proxy-only stock may be considered by a general technical or opportunity screen, but cannot receive a confirmed institutional-accumulation label.

Coverage must be shown to users and available to ranking, filtering, validation, and audit processes.

### 45.3 Data readiness reported by the review

The review reports the following staging observations as of 2026-10-22; they must be rechecked against the target environment before implementation or release:

- MF holdings history: approximately 13 months, with more than one million monthly-delta rows reported.
- Mapping from held ISINs to priced NSE equities is incomplete overall, although the review reports full mapping coverage for the Nifty 500 universe.
- FII/DII ownership deltas are populated for only a small fraction of the reported 2,479-symbol universe.
- Aggregate FII/DII flow history and block-deal records are sparse in the inspected tables.
- Market-proxy fields are reported as much more complete than direct institutional evidence.
- Several distress/fundamental inputs are empty because the NSE financials feed has not succeeded.
- Sector-rotation data is described as designed but not yet populated in the target schema.

These are environment-specific findings, not permanent guarantees. Add automated freshness, completeness, mapping, and feed-health checks rather than hard-coding the counts into business logic.

## 46. Fundamental and sector data prerequisites

Before the fundamental quality and distress gates are relied upon:

1. Restore and monitor the financial-data feed that supplies interest coverage, CFO/PAT, Altman Z, and EV/EBITDA, or explicitly mark each affected gate as unevaluable.
2. Distinguish **pass**, **fail**, and **unknown/unavailable** for every gate. Unknown must not be treated as pass or silently converted to zero.
3. Do not claim that a distress gate has protected a recommendation when its required input is missing.
4. Use sector-specific scoring profiles. Do not apply universal P/E or debt/equity thresholds to sectors for which they are not appropriate.
5. Create and populate the sector-rotation dataset before claiming stock-level sector rotation is an available input. Until then, label the available market-regime inputs accurately (for example, index trend or volatility regime).

## 47. One gate sequence and one gate catalogue

The previous requirements leave gate ordering ambiguous. The canonical engine must adopt the following sequence unless the owner approves and documents an alternative:

1. **Data validity and coverage:** determine whether required inputs are fresh, mapped, and sufficient to evaluate the candidate.
2. **Eligibility gates:** apply the canonical universe, tradability, liquidity, and instrument constraints.
3. **Hard risk/compliance gates:** apply applicable exclusion rules; unresolved compliance must prevent restricted user-facing output.
4. **Opportunity-quality calculation:** calculate only from eligible, available components and expose component coverage.
5. **Trade-readiness evaluation:** independently evaluate setup, trigger, invalidation, reward/risk, and execution constraints.
6. **Output-state mapping:** assign one canonical status and reason codes from the results above.

Gates must override an otherwise high score. A score must never reinstate a candidate excluded by a hard gate. Retain the rejected candidate and reason in the audit record without presenting it as an eligible recommendation.

### 47.1 Gate thresholds

Do not invent a second set of numeric thresholds in this addendum. Reuse the existing approved universe and liquidity rules, including the reported ₹10 crore 20-session average daily traded value floor and other named gates in `docs/SMART_TRADING_DESK_FUNCTIONALITY.md`, **only after verifying that they are current, approved, and applicable to this product**.

For every gate, document:
- machine-readable predicate;
- numeric threshold and units, where applicable;
- data source and lookback window;
- treatment of stale or missing data;
- severity (`exclude`, `warning`, or `unevaluable`);
- reason code and user-facing explanation;
- owner and version.

If a required input is unknown, mark the relevant gate `unevaluable` and prevent claims that depend on it. The product owner must decide whether this means exclusion or a restricted watchlist state for each gate class.

## 48. Canonical states and machine predicates

Do not ship multiple competing vocabularies for the same candidate. Map the user-facing labels to the canonical state machine in the integrated engine design, subject to owner approval.

The state machine must provide deterministic, testable predicates for at least:
- `excluded`;
- `avoid`;
- `watchlist`;
- `setup_forming`;
- `trigger_ready`;
- `confirmed`.

For each state, define:
- required evidence and coverage;
- hard-gate conditions;
- opportunity-quality conditions, if validated;
- technical trigger and invalidation conditions;
- allowed user-facing language;
- transition rules and reason codes.

Terms such as “improving market proxies,” “acceptable fundamentals,” and “confirmed strength” are not implementable until translated into measurable predicates. A high opportunity-quality score alone must not imply `trigger_ready` or `confirmed`.

## 49. Risk sizing and recommendation cards

### 49.1 Reuse the existing planner

Do not implement a separate position-size formula in the PRD or a parallel calculator. Integrate with the existing positional planner and preserve its documented constraints, including risk-budget sizing, allocation caps, maximum quantity, lot rounding, and the explanation of which constraint bound.

### 49.2 Missing user risk budget

A risk category such as “moderate” is not a monetary per-trade risk budget. The product must not fabricate a rupee risk budget or position size.

If the user's approved risk budget, capital/allocation constraints, or required inputs are missing:
- do not display a personalised quantity;
- state which input is missing;
- offer a neutral next step to complete the required profile or enter an explicit budget, subject to the approved product and compliance scope.

### 49.3 Invalidation and reward/risk

Every trade-readiness output must define the source of its invalidation level and the conditions that invalidate the setup. Use the existing planner's approved reward/risk floor (reported as 1.5) only after verifying that it remains the current rule. Do not create a target or stop solely to make a candidate pass a score threshold.

### 49.4 User-facing recommendation surface

Extend the existing recommendation card and positional workflow where practical. Do not create a second card or route unless product design explicitly requires it.

A card must distinguish:
- observed facts and source timestamps;
- direct institutional evidence versus market proxies;
- opportunity quality versus trade readiness;
- data coverage and uncertainty;
- failed, passed, and unevaluable gates;
- entry/stop/target/quantity fields, if permitted at all by the approved regulatory posture;
- explanation of why the candidate is included, downgraded, or excluded.

## 50. Regulatory posture and release control

This section is a product-control requirement, not legal advice. Qualified compliance/legal reviewers must confirm the applicable Indian regulatory requirements before the product exposes regulated outputs.

The repository review reports that `backend/config/allocation_policy.yaml` currently sets:
- registration to `TBD`;
- `direct_stock_recommendations_enabled: false`;
- `disclaimer_required: true`.

It also reports a public AMFI distributor identifier and an unresolved SEBI RA/IA decision. Those details must be independently confirmed by the responsible compliance owner; an AMFI distributor registration must not be assumed to authorise direct stock research or personalised stock advice.

Until that decision is recorded and approved:
1. Keep `direct_stock_recommendations_enabled` false.
2. Keep restricted outputs behind the existing owner/admin allowlist.
3. Do not expose personalised entry, stop, target, position quantity, suitability, or portfolio-specific stock advice to ordinary users.
4. Clearly distinguish educational market intelligence and factual disclosures from research recommendations and personalised advice.
5. Require appropriate disclaimers and a documented record-keeping process for every permitted output.
6. Review all relevant surfaces, including `/pro-trader`, recommendations pages, APIs, exports, notifications, and Copilot responses. UI gating alone is insufficient if an API or alternate surface exposes the same restricted content.

The release decision must record the confirmed registration category, allowed output types, permitted user groups, disclaimer wording/placement, review responsibility, and audit-retention requirements. No engineer should infer these from the scoring design.

## 51. Point-in-time research and auditability

### 51.1 Required point-in-time data

A backtest must not use a disclosure before it was publicly available. For each relevant dataset, retain both the economic/as-of date and the first known/publication/availability timestamp where obtainable.

Prioritise:
1. daily historical index-constituent snapshots;
2. a publication/availability timestamp for monthly MF holdings;
3. reliable publication timestamps for shareholding-pattern records;
4. source and ingestion timestamps for deals and filings.

Where publication time cannot be recovered, mark the affected observations as point-in-time uncertain and exclude them from strict point-in-time claims or report the limitation explicitly.

### 51.2 Historical universe and sample limitations

The review reports that index constituent history is insufficient and that available price, feature, and holdings history covers roughly 10–13 months, representing a limited range of market regimes. These limitations must be rechecked and recorded in the experiment metadata.

Until sufficient history exists:
- do not claim robust performance across market regimes;
- do not imply survivorship-bias-free results;
- report the actual sample period, eligible-symbol count, coverage, and exclusions;
- report confidence intervals and sample sizes where statistically meaningful;
- mark sector, market-cap, and regime slices as inconclusive when their samples are inadequate;
- continue collecting immutable point-in-time data so future studies become possible.

### 51.3 Per-candidate audit record

Before any user-facing pilot, persist an immutable or append-only audit record containing:
- evaluation timestamp and data-as-of timestamps;
- symbol, instrument, and universe membership;
- source/feature snapshot reference;
- direct-evidence and proxy coverage;
- component scores and unavailable components;
- gate decisions, thresholds, and reason codes;
- opportunity and trade-readiness states;
- model, feature, configuration, and strategy versions/hashes;
- output permitted/blocked decision and applicable policy version;
- experiment or validation version where relevant.

Reuse the repository's existing audit and paper-trade snapshot patterns after verification; do not introduce an unrelated audit mechanism.

## 52. `/pro-trader` access-control remediation

The review reports that `/pro-trader` exposes entry, stop-loss, target, and reward/risk details to logged-in users without the intended admin gate or disclaimer. This is an independent remediation item and must not wait for the Smart Money engine.

Acceptance criteria:
- route access is guarded consistently with the approved allowlist/policy;
- APIs supplying restricted fields enforce the same authorisation server-side;
- restricted fields are not exposed through client payloads to unauthorised users;
- approved disclaimers appear wherever required;
- automated tests cover unauthorised direct navigation, API access, exports, and Copilot responses;
- access-control changes are verified in the deployed environment.

The report's route and component paths should be rechecked in the current branch before making code changes.

## 53. Revised implementation sequence

### Phase 0 — Governance and canonicalisation
- Approve the canonical design and score ownership.
- Resolve the compliance posture and allowed output scope.
- Inventory existing score fields, states, gates, planner, cards, routes, and APIs.
- Reconcile duplicate definitions and publish one canonical state/gate catalogue.

**Exit criteria:** no unresolved conflict over score ownership, state vocabulary, gate ordering, or permitted output scope.

### Phase 1 — Preserve data that cannot be reconstructed later
- Begin daily snapshots of historical index constituents.
- Add and populate MF holding publication/availability timestamps where recoverable.
- Backfill shareholding publication timestamps where possible.
- Persist source and ingestion timestamps and source provenance.

**Exit criteria:** data-quality checks report coverage and timestamp completeness, and point-in-time limitations are explicit.

### Phase 2 — Repair data readiness
- Restore the financial-data feed and expose health/freshness status.
- Populate sector-rotation data or formally scope it out until available.
- Improve aggregate FII/DII flow and deal-source coverage where licensed and feasible.
- Add ISIN mapping coverage, unmapped-value reporting, and stale-data monitoring.

**Exit criteria:** required features are either populated and tested or explicitly marked unavailable; no silent fallback is presented as institutional evidence.

### Phase 3 — Implement evidence and candidate states
- Build direct-evidence and market-proxy outputs separately.
- Apply the single canonical gate sequence.
- Map candidates to one state machine with deterministic predicates and reason codes.
- Integrate the existing planner and recommendation card without duplicating them.
- Keep restricted recommendation output disabled until the approved release conditions are met.

**Exit criteria:** unit, integration, data-quality, access-control, and audit tests pass.

### Phase 4 — Validate before enabling a headline score
- Compare against simple baselines and existing production scores.
- Use strict point-in-time and out-of-time evaluation where data supports it.
- Include costs and relevant execution assumptions for trade studies.
- Report sample size, coverage, confidence intervals, and survivorship limitations.
- Pre-register experiment hypotheses, metrics, and pass/fail thresholds before evaluating results.

**Exit criteria:** the owner and research reviewer approve the results and documented thresholds. If the sample is insufficient, the result remains experimental/watchlist-only rather than being promoted to a production recommendation score.

### Phase 5 — Controlled release
- Release only the output types authorised by compliance.
- Use an owner/internal pilot first, then expand only after audit, access-control, and data-quality checks.
- Monitor source freshness, coverage drift, gate distribution, score distribution, user-facing output, and post-release outcomes.
- Provide a rollback switch for recommendation output independent of data ingestion.

**Exit criteria:** the approved policy is enforced across all user-facing surfaces and the rollback path is tested.

## 54. Revised acceptance criteria

The feature is not ready for production until all applicable criteria pass:

1. One canonical engine design and one score/state vocabulary are approved.
2. Direct institutional evidence and market proxies are distinguishable in storage, APIs, UI, and explanations.
3. Missing or stale evidence cannot silently become zero, pass, or a claim of institutional buying.
4. Coverage and evidence timestamps are queryable and visible where material.
5. Gate predicates, thresholds, unknown-data handling, ordering, and reason codes are documented and tested.
6. The engine reuses the canonical universe gates and existing risk planner rather than duplicating them.
7. A missing user risk budget never yields an invented personalised position size.
8. Historical evaluations disclose point-in-time limitations, sample sizes, and survivorship bias.
9. Immutable or append-only audit records can reproduce why a candidate was included, excluded, or shown.
10. The applicable registration and allowed-output decision is recorded before restricted stock recommendations are enabled.
11. Route, API, export, and Copilot access controls enforce the same policy.
12. A headline composite is enabled only after pre-registered validation passes agreed thresholds.
13. Operational monitoring detects feed failures, stale sources, mapping drops, and sudden changes in coverage or score distribution.
14. The `/pro-trader` exposure reported in the review is remediated or explicitly accepted by the accountable compliance owner before a related release.

## 55. Decision register

The following items require named owners and recorded decisions. Do not treat the recommendation in this table as an already approved decision.

| Decision | Recommended default | Required owner |
|---|---|---|
| Canonical design | Integrated Stock Engine Design; this PRD supplies data/source requirements | Product + Engineering |
| Composite weights | No new production weights until validated | Research + Product |
| Score bands | Inherit the canonical engine's one vocabulary; recalibrate only with evidence | Research + Product |
| Missing direct evidence | Split direct evidence from proxies; no proxy-only institutional claim | Data + Research |
| Gate sequence | Data validity → eligibility → hard risk/compliance gates → opportunity score → trade readiness → output state | Engineering + Risk |
| Gate thresholds | Reuse verified, approved existing thresholds; document each predicate | Product + Risk |
| Position sizing | Use the existing planner; no size without required budget and inputs | Risk + Engineering |
| Regulatory scope | Keep direct recommendations disabled pending written compliance decision | Compliance/Legal + Product |
| Point-in-time gaps | Start immutable universe snapshots and improve publication timestamps immediately | Data Engineering |
| Production score release | Require pre-registered, reproducible validation | Research + Product |

## 56. Source-review traceability

This governance addendum was prepared from the uploaded document titled **“Requirement Review — Smart Money Recommendations Addendum (§30–42)”**, dated 2026-10-22. That review labels some findings as verified and others as reported. Counts, repository paths, deployment behaviour, registrations, and configuration values are therefore **review-reported observations that must be rechecked in the target branch/environment before operational action**.

This document resolves requirements at the product/specification level. It does not claim to have modified the codebase, staging database, production configuration, or regulatory registration.

---

# Consolidated Conversation Record and Current Milestone
**Prepared:** 2026-10-22

> **Status convention:** Metrics and implementation states in this section are reported by the project owner in the conversation and are not independently verified here. Check the actual registry, repository, and warehouse before acting on them.

## 57. Product decision: extend the existing stock-selection engine

The agreed direction is to **enhance the existing stock-selection criteria with Smart Money Accumulation features**, not create a parallel stock-ranking engine. The existing engine remains canonical for ranking, eligibility gates, recommendation states, and risk planning.

Principles:
- One canonical stock-selection engine and one primary ranking.
- Separate opportunity quality from trade readiness.
- Keep direct ownership/deal evidence distinct from price/volume proxies.
- Preserve missing, stale, unmapped, or incomparable evidence as unknown.
- Never silently redistribute the missing Smart Money component's weight.
- Avoid double-counting promoter/FII/DII ownership already present in other components.
- Run in shadow mode before changing the production composite.
- Reuse existing gates, positional planner, APIs and recommendation cards.
- Do not promote a score merely because more data has arrived.

## 58. Smart Money score and feature contract

If a dedicated score is retained, use the explicit name `smart_money_accumulation_score`. Do not overload existing `accumulation_score` fields, which have reportedly been used on different scales.

Suggested fields:
- `smart_money_accumulation_score`: experimental normalized score, 0–100 only if calibrated.
- `direct_evidence_status`: `available`, `partial`, `unavailable`, `stale`, or `incomparable`.
- `direct_evidence_coverage_pct`, `proxy_coverage_pct`.
- `evidence_as_of`, `evidence_sources`, `feature_version`.
- `classification_break_flag`, `publication_provenance`, `ingest_version`.

Direct evidence:
- Mutual-fund scheme holdings and changes.
- Quarterly promoter/FII/DII/public ownership disclosures when periods are comparable.
- Bulk/block deals with sufficient source detail.
- Attributable filings when supported by the source.

Indirect proxies:
- Delivery percentage and changes versus baseline.
- Relative volume and volume z-scores.
- Price/volume accumulation patterns.
- Existing trend and relative-strength features.

Proxies may indicate market pressure; they are not proof of institutional buying. A proxy-only stock must not be labelled “confirmed institutional accumulation.” Missing direct evidence must not silently become zero, pass, or a positive institutional claim.

### Mutual-fund holdings features
Consider scheme-level share changes, weight changes where denominators are valid, breadth of schemes accumulating, consistency across periods, AMC breadth, mapping quality, and publication freshness. Do not treat holdings as known before the applicable publication/availability timestamp. Unknown publication provenance remains explicit.

### Ownership-change features
Preserve raw promoter/FII/DII/public categories and reporting periods. Calculate deltas only across comparable periods. The project reports a per-stock classification-break detector requiring both FII falling by at least 10 percentage points and `OTHERS` rising by at least 10 percentage points. Pilot breaks were reported at RELIANCE `202306`, 360 ONE `202309`, and Aarti Industries `202312`. These are examples, not hardcoded global break dates.

When a delta spans a break:
- `fii_chg_pp = NULL`;
- set `fii_spans_classification_break`;
- do not bridge or infer a comparable FII delta;
- retain raw data and the reason for the unavailable delta.

### Bulk/block deals
NSE's rolling `bulk.csv` reportedly could not supply the required history; Trendlyne was added as a historical source. A later project update reported 19,787 deal legs with history to 2006. An earlier analysis found roughly 38–47% of symbol-days were exact offsetting transfer days. `v_trendlyne_deals_net` reportedly matches legs on `(symbol, date, quantity, price)` before computing net flow.

Keep raw legs; version the netting logic; test duplicates and partial loads; retain unmatched legs. Netting does not prove that every remaining deal is directional conviction. Since the feed has no publication timestamp, the reported conservative rule is that a deal is usable only strictly after its trade date.

## 59. Data sources and reported data estate

These figures are point-in-time project reports and may change during ingestion.

| Source | Reported state | Unique contribution / limitation |
|---|---:|---|
| AMC files | 1,687,180 rows | AMC's own source files and provenance |
| ScanX scheme holdings | 56,884 rows and climbing in one update | Scheme-level holdings across AMCs |
| ScanX directory | 52 AMCs, 1,434 schemes | HDFC and Mirae reportedly became reachable |
| Trendlyne ownership | 2,479 symbols; 86.4% coverage reported | Aggregate FII/institutional fields; no DII token in described setup |
| Trendlyne deals | 19,787 legs in latest update | Historical deal evidence to 2006 |
| Company-page ownership | 23–24 quarters per stock back to 2021-03 in pilot | Promoter/FII/DII/public ownership |
| Index constituents | Four snapshots reported | Insufficient for robust historical membership reconstruction |

### ScanX scheme holdings
The project update reports Dhan skill documentation says ScanX has no documented public API and Overview data is available without authentication. Page fetching is the available route. One request returns 12 months per scheme. HDFC Flexicap's HDFCBANK holding reportedly changed from 88,634,120 to 92,350,446 shares. Observed scheme slugs were `-direct-growth`, so the specific direct/regular plan-variant inflation seen in migration 177 did not appear in this dataset. This does not prove all scheme duplication risks are impossible.

Initial company slug derivation failed because ScanX URLs retain registered suffixes omitted from display names; candidate slugs are now tried in order. Harvested `company_slug` should be retained to avoid repeated guessing.

### Company-page shareholding history
The shareholding ingester was reported built and verified in a pilot:
- 23–24 quarters per stock, back to 2021-03;
- DII present on 100% of pilot rows;
- per-stock classification-break detection;
- `publication_provenance='unknown'` where retrieval time is the only availability bound;
- `ingest_version` on every row.

Full-universe status is partial. The 1,021-target run was deferred while the ScanX scheme job continued against the same public host.

### Financial-data gap
The default company page reportedly contains 14 fundamental fields such as book value, PE and PB, but this does not establish availability of interest coverage or CFO. Those are on separate tabs that had not yet been fetched. Do not claim the `NSE_FINANCIALS` gap is solved until those tabs are ingested and field-level coverage measured.

## 60. Frozen research protocols

Two studies are reported frozen and protected by an append-only trigger on `smart_money_study_config`.

### Study 001
- ID: `NIDP-SM-VALIDATION-001`
- Reported SHA-256 prefix: `6bcd0fe4d048b8cd…`
- Primary horizon: 20 sessions
- Incremental-return hurdle: +1.0 percentage points net of modeled costs
- No Nifty 500 TRI exists in the warehouse; the Nifty 500 price index is used with an approximately 0.1 percentage-point dividend-gap caveat.
- The project reports the primary paired A-vs-B comparison uses an identical universe, so the benchmark does not enter the primary paired difference.

### Study 002
- ID: `NIDP-SM-VALIDATION-002`
- Reported SHA-256 prefix: `1a4b7d6f20a55494…`
- Purpose: deal-feature ablation, Model C versus Model B.
- Separate study because the frozen Study 001 configuration rejected edits; an attempted hurdle change from 1.0 to 0.1 was reportedly rejected and the value remained unchanged.

The hashes above are prefixes, not full hashes. Load and verify full hashes and configs from the research registry before running. Do not recreate a frozen config from prose.

### Eligibility and point-in-time universe
The project uses a price-based point-in-time liquidity rule rather than index membership because only four index-constituent snapshots were reported. The exact liquidity lookback and thresholds must come from the frozen configuration and code, not be inferred here.

## 61. Paired B-versus-C evaluator — next critical path

**Reported status: not started.** This is the next priority.

### Objective
Determine whether the frozen deal feature in Model C improves results over baseline Model B on the same eligible symbol-days under the frozen study contract.

### Required process
1. Verify the study ID, full configuration hash and immutable configuration.
2. Verify feature definitions, source columns, data cutoff and look-ahead protections.
3. Build the eligible symbol-day population once using the frozen price-based liquidity rule.
4. Join B and C on identical symbol-date keys; report missing pairs and treat them symmetrically.
5. Apply identical outcome labels, entry assumptions, horizon and transaction costs.
6. Calculate paired net-return differences over 20 sessions.
7. Report eligible rows, B predictions, C predictions, paired rows, exclusions, unique symbols and dates.
8. Report the primary paired difference and confidence interval. Specify the interval method and resampling unit before examining results; account for dependence across symbols and dates where appropriate.
9. Report turnover, costs, drawdown and coverage as secondary diagnostics.
10. Disclose the Nifty 500 price-index versus TRI difference in market-context reporting.
11. Persist an immutable/reproducible run manifest.
12. Never modify the frozen configuration to obtain a pass.

### Required report
- Study ID and full configuration hash.
- Run ID, code revision, feature version and data snapshot identifiers.
- Evaluation window and data-as-of timestamps.
- Eligibility rule and sample counts at each stage.
- B/C coverage, missing pairs and common sample.
- Primary paired net-return difference in percentage points and confidence interval/method.
- Cost assumptions and secondary risk/performance metrics.
- Source-quality and feature-availability diagnostics.
- Exclusion reasons and limitations.
- Registered hurdle and explicit `PASS`, `FAIL`, or `INCONCLUSIVE`.
- Promotion recommendation, defaulting to `NO PROMOTION` unless all preregistered conditions pass.

Gate meanings:
- `PASS`: registered primary hurdle and validity checks pass.
- `FAIL`: valid evaluation, criterion not met.
- `INCONCLUSIVE`: insufficient sample, broken data, missing pairs, unresolved validity issues or uncertainty too wide for the registered rule.

Do not promote based only on secondary metrics when the primary criterion fails.

### Evaluator acceptance criteria
- Full frozen hashes verified; no config mutation.
- No feature available before its permitted timestamp.
- Identical eligible symbol-days for B and C.
- Missing pairs and coverage reported.
- Primary metric, confidence interval and costs reproducible.
- Run manifest sufficient to reproduce the result.
- Explicit gate result tied to registered hurdle.
- No promotion after a failed or inconclusive run.

## 62. Implementation order and concurrency

1. **Priority:** build and test the paired B-vs-C evaluator and auditable report.
2. Let the active ScanX scheme run finish; avoid overlapping the full ownership run against the same host.
3. Run the full 1,021-target shareholding ingestion after the current ScanX workload completes.
4. Integrate ownership/deal features into the existing stock-selection pipeline in shadow mode.
5. Fetch the balance-sheet/cash-flow tabs and measure field coverage independently.
6. Make any promotion decision only after the frozen evaluation and validity checks.

The full ownership run is not required to start the evaluator if frozen B/C inputs are already sufficient. If missing ownership data is part of the registered feature contract, stop or report `INCONCLUSIVE`; do not substitute a different feature silently.

## 63. Market Intelligence screen — Smart Money Movement

A visual concept was generated in the Nivesh Copilot dark UI style. Implementation status is not established.

### Layout
- **Global navigation:** Dashboard, Market Intelligence, Stock Analysis, Screeners, Portfolios, Watchlist, Alerts; global search; notifications/settings.
- **Page header:** “Smart Money Movement”; NSE, BSE, AMFI and shareholding-disclosure sources; 1M/3M/6M/1Y time filters; visible data-as-of and data-status labels.
- **KPI cards:** FII net cash flow, DII net cash flow, mutual-fund accumulation breadth, stocks with rising institutional ownership.
- **Sector rotation:** net flow by sector, percentage of total, and number of stocks; source, period and coverage shown.
- **Flow regime:** FII/DII time series and evidence-grounded summary. Show historical reactions only if a valid study is published; otherwise say no validated study is available.
- **Stock-level scanner:** rank, stock/symbol, sector, MF holding changes and scheme breadth, FII/DII ownership changes and quarter, bulk/block activity, delivery versus baseline, Smart Money score if validated, evidence class and freshness.
- **Filters:** universe, sector, time window, direct-evidence coverage, evidence class, accumulation/distribution direction, freshness.
- **Stock detail:** overview, Smart Money, financials, technicals, news; “why it surfaced” explanations; MF holdings breadth; FII/DII deltas and comparability warnings; netted deal history; proxies; score coverage/freshness; link to existing detailed analysis.
- **Copilot:** explain flows, show rising MF holdings, compare FII/DII, identify direct evidence plus proxy confirmation, flag classification breaks, explain missing evidence.

### Screen acceptance criteria
- Filters update all relevant panels consistently.
- Data-as-of and source status visible.
- Aggregate daily FII/DII cash flows are never presented as stock-specific flow.
- MF holding changes show scheme breadth and reporting period.
- Ownership deltas spanning classification breaks are flagged/unavailable.
- Proxy-only evidence is not labelled direct institutional accumulation.
- Transfer-day netting is reflected in deal summaries.
- Missing historical studies are shown as unavailable, not as forecasts.
- Use existing stock-analysis surfaces where practical.
- All prototype data is marked illustrative; live data requires actual sourced values.

## 64. Decisions and unresolved items

### Decided
- Extend the existing stock-selection engine; no parallel ranking engine.
- Keep direct evidence and proxies separate.
- Run in shadow mode before score promotion.
- Preserve frozen Study 001 and Study 002.
- Paired B-vs-C evaluator is the next critical path.
- Use a point-in-time price-based liquidity rule rather than sparse historical index membership.
- Detect ownership classification breaks per stock; do not bridge incomparable FII data.
- Do not overlap full ownership ingestion with the active ScanX run against the same host.
- Do not claim financial-data coverage is fixed before measuring the relevant tabs.
- No score has been promoted.

### Open
- Build evaluator and auditable report.
- Verify full hashes in the study registry.
- Run full shareholding universe after active ScanX run.
- Enforce publication availability and conservative deal availability.
- Complete any outstanding Trendlyne ownership ingester work in the target branch.
- Fetch balance-sheet/cash-flow tabs and measure CFO/interest-coverage completeness.
- Quantify incremental value of deal features.
- Decide whether and how a validated Smart Money component enters the existing composite.
- Verify production score/gate mapping.
- Replace the revoked staging token via the authorised secret-management process and retain query-string log redaction.

## 65. Risks and limitations
- Counts may change during ingestion.
- Reporting period is not publication timestamp.
- Unknown provenance limits strict point-in-time claims.
- Classification breaks can create false deltas.
- Matched deal legs may be transfers; unmatched legs are not automatically conviction.
- MF holding changes can reflect corporate actions or denominator effects.
- Sparse index-constituent history limits survivorship-bias-free tests.
- Nifty 500 price index is not TRI; disclose the dividend-gap caveat.
- Incomplete financial fields leave some gates unevaluable.
- A higher score does not automatically imply a better trade.
- More rows and feeds do not establish predictive value.

## 66. Latest milestone status

| Workstream | Reported status |
|---|---|
| Product direction | Extend existing stock-selection engine |
| Market Intelligence screen | Visual concept generated; implementation unconfirmed |
| Frozen studies | Frozen, append-only trigger reported |
| Historical Trendlyne deals | 19,787 legs reported in latest update |
| Deal transfer netting | `v_trendlyne_deals_net` reported implemented |
| ScanX scheme holdings | Active run reported |
| Shareholding ingester | Built and verified in pilot |
| Classification-break controls | Implemented and tested on pilot cases |
| Full 1,021-target run | Deferred until ScanX scheme run finishes |
| Financial tabs / CFO / interest coverage | Unverified; gap open |
| Paired B-vs-C evaluator | Not started; next critical path |
| Auditable evaluation report | Not started |
| Score promotion | None |

## 67. Final product principle

Nivesh should not merely count institutional transactions. It should construct a time-aware, source-attributed and reproducible evidence chain that distinguishes:
1. who appears to be accumulating or reducing ownership;
2. which disclosures support that conclusion;
3. whether deal activity remains directional after matched transfers are removed;
4. whether independent market proxies corroborate or contradict direct evidence; and
5. whether the feature adds measurable out-of-sample value to the existing stock-selection engine.

Success is not the number of feeds, rows, scores or alerts. Success is a reproducible demonstration that Smart Money evidence improves stock selection under the frozen protocol, without look-ahead leakage, misleading coverage claims or duplicate ranking logic.
