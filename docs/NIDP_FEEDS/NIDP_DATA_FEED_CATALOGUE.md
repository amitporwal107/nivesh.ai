# NIDP Master Data Feed Catalogue

> Last updated: 2026-05-27  
> Total feeds: 41 across 4 layers

---

## Architecture Overview

NIDP (Nivesh Intelligence Data Platform) organises its data pipeline into 4 layers:

1. **External Ingestion** — raw data pulled from NSE, BSE, AMFI, RBI, FRED, AMC sites, Yahoo Finance, GCS
2. **AI Classification** — Claude Haiku-powered annotation of exchange announcements and events
3. **Derivation Engines** — compute features, fundamentals, technicals, and composite scores
4. **Portfolio + Intelligence Sync** — user portfolio data from GCS + AI intelligence layer

All services are Cloud Run jobs triggered by Cloud Scheduler, idempotent, and write to TimescaleDB (`nidp-stack-vm:5433`).

---

## Layer 1 — External Data Ingestion

### 1.1 Equity Market Data (NSE/BSE)

| # | Service | Source | Data Type | Frequency | Output Table(s) | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|-----------------|--------------------------------------|
| 1 | `bhavcopy` | NSE Archives — `BhavCopy_NSE_CM_*.csv.zip` | Equity EOD OHLCV + volume (all NSE-listed stocks) | Daily ~17:30 IST | `nidp.bhavcopy` | Stores Open, High, Low, Close, Volume for every NSE-listed stock each trading day. This is the single most critical feed — it is the price-history foundation that all technical indicators, momentum scores, and volatility calculations are built on. Without it, no stock health score can be computed. Also serves as the authoritative "market day closed" signal that triggers all downstream feeds. |
| 2 | `delivery` | NSE — `sec_bhavdata_full_DDMMYYYY.csv` | T+1 settlement / delivery quantities by symbol | Daily T+1 | `nidp.delivery` | Stores the quantity of shares that resulted in actual delivery (settled in demat accounts) vs. total traded volume for each stock. Delivery % is a key quality signal — high delivery indicates genuine investor accumulation, low delivery suggests speculative intraday trading. Used as a volume-quality filter in the V3 stock health score and momentum features. |
| 3 | `fno_bhavcopy` | NSE Archives — `BhavCopy_NSE_FO_*.csv.zip` | Futures & Options EOD data (open interest, Greeks) | Daily | `nidp.fno_bhavcopy` | Stores end-of-day data for all F&O contracts: open interest, number of contracts, settlement price, implied volatility for options. Rising open interest alongside rising price confirms a bullish trend; rising OI with falling price signals distribution. Used in market sentiment signals and as a derivatives-based risk indicator for stocks that have F&O coverage. |
| 4 | `index_close` | NSE — `ind_close_all_DDMMYYYY.csv` | EOD closes for all NSE indices | Daily | `nidp.index_close` | Stores the daily closing value for every NSE index (Nifty 50, Bank Nifty, Nifty IT, Nifty Midcap, etc.). These are the benchmark reference values against which stock and fund performance is compared. Alpha (excess return vs. benchmark) and beta (sensitivity to index) are both derived using this feed. Also used to compute relative strength of sectors vs. the broad market. |
| 5 | `index_constituents` | NSE constituent CSVs (Nifty 50/100/200/500/Bank/IT) | Index membership / constituent lists | Quarterly | `nidp.index_constituents` | Stores the list of stocks in each major NSE index at any point in time. Index membership determines the investable universe — only stocks in Nifty 500 or better are scored and recommended. It also drives sector tagging (e.g., a stock in Bank Nifty is tagged as Banking). Used by the scoring engine to gate which stocks enter the quality-health ranking. |
| 6 | `nse_equity_master` | NSE — `EQUITY_L.csv` | Equity master reference: symbols, ISINs, sector, market cap | Weekly | `nidp.sector_master` | Stores the master reference record for every NSE-listed security: trading symbol, ISIN, company name, face value, market lot size, and exchange code. ISINs are the universal cross-source identifier used to match CAS portfolio holdings to NIDP market data. Market cap tier (large/mid/small) is a key input to the risk-tier classification in V3 scoring. |
| 7 | `fii_dii` | NSE JSON API — `fiidiiTradeReact` | FII / DII institutional net cash flows (cash market) | Daily | `nidp.fii_dii` | Stores net buy/sell amounts by Foreign Institutional Investors (FIIs) and Domestic Institutional Investors (DIIs) in the cash equity market each day. FII flows are among the strongest macro-level risk signals — sustained FII selling often precedes market corrections, while FII buying supports uptrends. Used in macro regime scoring and market intelligence context for the copilot. |
| 8 | `bulk_deals` | NSE — `bulk.csv` | Bulk transactions ≥ 0.5% of equity capital | Daily | `nidp.bulk_deals` | Stores every transaction where a single buyer/seller traded ≥ 0.5% of a company's total equity in one day, including client name, price, and quantity. These large disclosed trades reveal institutional conviction — a mutual fund or PE firm taking a bulk position is a strong signal. Used as a positive catalyst signal in the event_analyzer and copilot recommendation context. |
| 9 | `block_deals` | NSE — `block.csv` | Large block trades executed on-exchange | Daily | `nidp.block_deals` | Stores block trades (≥ ₹5 crore) executed in the pre-market block deal window. Block deals indicate large institutional portfolio restructuring — buying or selling at negotiated prices away from the order book. Similar business significance to bulk deals; together they provide a complete picture of large smart-money movements used in momentum and catalyst scoring. |
| 10 | `corporate_actions` | NSE JSON API — `corporates-corporateActions` | Splits, bonuses, dividends, rights issues | Daily (rolling) | `nidp.corporate_actions` | Stores all corporate action events: stock splits, bonus issues, dividends declared, rights issues, and buy-backs. Corporate actions directly affect historical price continuity — a 2:1 split halves the price overnight and all historical prices must be adjusted. Also signals shareholder-friendliness: regular dividend payouts and bonus shares are positive quality signals in fundamental scoring. |

### 1.2 Financials & Exchange Filings

| # | Service | Source | Data Type | Frequency | Output Table(s) | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|-----------------|--------------------------------------|
| 11 | `nse_financials` | NSE XBRL filings — `corporates-financial-results` | Quarterly + Annual P&L, Balance Sheet, Cash Flows (XBRL-parsed) | Daily | `nidp.nse_financials_quarterly`, `nidp.nse_financials_annual` | Stores quarterly and annual financial statements parsed from XBRL filings: revenue, EBITDA, PAT, total debt, cash, capex, and more. This is the raw material for all fundamental analysis — every ratio the fundamental_engine computes (P/E, ROE, debt-to-equity, earnings growth) comes from here. Financial health is one of the two pillars of the V3 stock quality score; poor fundamentals directly lower the score. |
| 12 | `nse_shareholding` | NSE XBRL — `corporate-share-holdings-master` | Promoter / FII / DII / Public shareholding patterns (quarterly) | Daily | `nidp.shareholding_pattern` | Stores the quarterly breakdown of who owns each company's shares: promoters, FIIs, domestic mutual funds, insurance companies, and retail public. Promoter pledging of shares is a major red flag and increases the risk score. Declining promoter holding suggests insider selling. Increasing FII/MF holding signals institutional confidence. All of these feed into the governance and risk dimensions of V3 scoring. |
| 13 | `event_calendar` | NSE corporate event calendar API | Board meetings, quarterly results, AGMs, dividends (+90 day forward window) | Daily | `nidp.event_calendar` | Stores a 90-day forward calendar of all scheduled corporate events: board meetings (for dividend/results), quarterly result dates, AGMs, record dates for corporate actions. This is the scheduling backbone — it tells the system when to expect new financials and triggers the nse_financials ingester proactively. Also used to surface upcoming catalysts to copilot users ("results expected this week"). |
| 14 | `corporate_announcements_nse` | NSE announcements system | All NSE exchange disclosures and filings | Intra-day | `nidp.corporate_announcements` (source=`nse`) | Stores every announcement filed by companies on NSE: quarterly results, board meeting notices, management changes, related-party transactions, regulatory orders, SEBI notices, and more. This is the raw event stream that the announcement_classifier and event_analyzer process into actionable signals. Material announcements (management changes, regulatory action) are negative risk signals; strong results are positive catalysts. |
| 15 | `corporate_announcements_bse` | BSE announcements system | All BSE exchange disclosures and filings | Intra-day | `nidp.corporate_announcements` (source=`bse`) | Same as NSE announcements but from BSE. Companies are listed on both exchanges and often file on BSE earlier or exclusively for some announcement types (BSE has more SME and midcap coverage). Both feeds share the same output table with a source discriminator. Complete dual-exchange coverage ensures no material announcement is missed before it affects price. |

### 1.3 Mutual Funds

| # | Service | Source | Data Type | Frequency | Output Table(s) | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|-----------------|--------------------------------------|
| 16 | `amfi_nav` | AMFI — `amfiindia.com/spages/NAVAll.txt` | Daily MF NAV snapshot for all schemes + scheme master metadata | Daily ~22:30 IST | `nidp.mf_nav_daily`, `nidp.mf_scheme_master` | Stores the daily Net Asset Value (NAV) for every SEBI-registered mutual fund scheme in India — across all fund houses and plan types (direct/regular, growth/IDCW). NAV is the per-unit price of a fund, and its daily movement forms the return history used to compute trailing returns (1M to 5Y), volatility, and Sharpe ratio. These are the core inputs to the MF health score. |
| 17 | `amfi_nav_history` | MFAPI.in — `/mf/{scheme_code}` | Historical NAV backfill per scheme (up to 30 concurrent fetches) | Daily incremental (refetches schemes stale > 7 days) | `nidp.mf_nav_daily` | Backfills years of historical NAV for each scheme from MFAPI.in, an unofficial but reliable aggregator of AMFI data. Without long history, return metrics like 3Y and 5Y CAGR cannot be computed — these long-horizon returns are critical for evaluating whether a fund consistently outperforms its benchmark over market cycles, which is a primary MF quality signal. |
| 18 | `amfi_circulars` | AMFI — notices/circulars page (HTML scrape) | Scheme lifecycle events: mergers, renames, regulatory changes | Daily | `nidp.mf_amfi_circulars` | Stores AMFI regulatory circulars about scheme lifecycle events: fund mergers, scheme renames, strategy changes, and regulatory interventions. When two schemes merge, their NAV histories must be linked to maintain continuity for return calculations. Tracking renames prevents ghost-scheme data. Also surfaces regulatory risk signals (e.g., SEBI actions against a fund house) relevant to MF risk scoring. |
| 19 | `mf_holdings` | 10 AMC disclosure sites (SBI, ICICI Pru, HDFC, Nippon, Kotak, ABSL, UTI, Axis, Tata, Mirae) | Mutual fund portfolio holdings (stocks, bonds, cash) | Monthly (disclosure month) | `nidp.mf_holdings` | Stores the monthly portfolio disclosure of each mutual fund — every security they hold, its percentage weight, and market value. SEBI mandates this disclosure. This data reveals concentration risk (top-10 holding %), sector bets, and overlap between funds in a user's portfolio. High overlap means less diversification. Portfolio concentration and sector tilt are key MF health score inputs. **Currently broken — AMC URLs returning 404.** |
| 20 | `mf_disclosure_snapshot` | AMC regulatory disclosure pages | Scheme disclosure summary snapshots (TER, AUM, classification) | Monthly | `nidp.mf_disclosure_snapshot` | Stores scheme-level regulatory metadata: Total Expense Ratio (TER), AUM (Assets Under Management), SEBI risk classification (Low/Moderate/High), and scheme category. TER directly reduces investor returns — a 1.5% TER vs 0.5% TER compounded over 10 years is a huge performance gap. AUM size affects liquidity risk (very small funds can be wound up). Both feed into MF risk scoring. **Currently broken — AMC URLs returning 404.** |

> **Note:** `mf_holdings` and `mf_disclosure_snapshot` scrapers are currently broken — all 10 AMC disclosure URLs return 404/changed paths. Downstream MF scoring primitives remain at 0% coverage until fixed.

### 1.4 Macro / Interest Rates

| # | Service | Source | Data Type | Frequency | Output Table(s) | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|-----------------|--------------------------------------|
| 21 | `rbi_yields` | RBI — `BS_NSDPDisplay.aspx` (primary) + archive fallback | India G-Sec reference yields (replaces the US ^TNX proxy) | Daily | `nidp.rbi_yields` | Stores daily India government bond (G-Sec) yields across tenors (1Y, 5Y, 10Y, etc.) from the RBI's official reference rate publication. The 10Y G-Sec yield is India's risk-free rate — the foundation of every CAPM-based beta and expected-return calculation. Using actual Indian G-Sec rates (instead of the US 10Y Treasury that was previously used as a proxy) makes all risk-adjusted return metrics accurate for Indian investors. |
| 22 | `fred_macro` | US Federal Reserve FRED API — 8 curated series | Global macro indicators: US rates, inflation, unemployment, credit spreads | Daily (full history refresh, idempotent ON CONFLICT) | `nidp.fred_macro` | Stores global macroeconomic time series: US Fed Funds Rate, 10Y-2Y yield curve spread, CPI inflation, unemployment rate, 10Y and 2Y Treasuries, HY credit spread, and USD/INR exchange rate. These macro indicators define the market regime — rising US rates trigger FII outflows from India; an inverted yield curve signals recession risk globally. Used in macro regime scoring and intelligent copilot commentary. |

**FRED series ingested:**

| Series ID | Description |
|-----------|-------------|
| `FEDFUNDS` | US Federal Funds Rate |
| `T10Y2Y` | 10Y–2Y Treasury spread (yield curve) |
| `CPIAUCSL` | US CPI (inflation) |
| `UNRATE` | US Unemployment Rate |
| `DGS10` | 10-Year Treasury Constant Maturity Rate |
| `DGS2` | 2-Year Treasury Constant Maturity Rate |
| `BAMLH0A0HYM2` | ICE BofA US High Yield spread |
| `DEXINUS` | USD/INR exchange rate |

### 1.5 Monitoring & Backfill Utilities

| # | Service | Source | Data Type | Frequency | Output | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|--------|--------------------------------------|
| 23 | `yfinance_backfill` | Yahoo Finance v8 API — `/chart/{ticker}` | Historical OHLCV (up to 20 years) for Nifty 500 universe | One-shot batch (not scheduled) | `nidp.yfinance_ohlcv` | Seeds the historical OHLCV table with up to 20 years of price data for Nifty 500 stocks, used before the daily bhavcopy feed takes over. Long price history is essential for computing SMA200, 52-week high/low, long-term momentum (12M return), and historical volatility. Without sufficient history, technical indicators like MACD and Bollinger Bands cannot be computed reliably. |
| 24 | `amc_urls_drift_check` | HTTP GET to all AMC + AMFI URL candidates | URL health / availability monitoring (no data ingested) | Daily | `nidp.job_log` (FAILED if any AMC has zero healthy URLs) | Pings all known AMC disclosure page URLs to detect when fund houses silently change or remove their disclosure links. AMC websites frequently restructure without notice, causing silent data gaps in mf_holdings and mf_disclosure_snapshot. A FAILED job_log entry from this check triggers an alert so engineers can update URLs before a monthly disclosure cycle is missed. Pure monitoring — no market data stored. |

---

## Layer 2 — AI Classification

| # | Service | Input | Model | Frequency | Output | Business Significance & Scoring Role |
|---|---------|-------|-------|-----------|--------|--------------------------------------|
| 25 | `announcement_classifier` | Unclassified rows in `nidp.corporate_announcements` (last 30 days) | Claude Haiku | Every 10 min during market hours + once post 17:30 IST | Updates `nidp.corporate_announcements` classification columns | Raw exchange announcements arrive as unstructured text blobs. This service uses Claude Haiku to classify each one into a structured taxonomy: earnings results, dividend declaration, management change, regulatory action, pledge/sale of shares, capex announcement, etc. Classification is what makes announcements queryable and actionable — the event_analyzer and copilot can only reason about "a promoter pledged shares" if the classifier first tagged it correctly. |
| 26 | `event_analyzer` | Recent announcements + `nse_financials_quarterly` + `event_calendar` | Claude (configurable) | Daily | `nidp.corporate_event_signals` | Takes classified announcements and generates investment-grade signals using Claude AI: is this event a positive or negative catalyst, what is the estimated impact magnitude, and does it change the stock's risk profile? Maps to a 20-event-type framework (earnings beat, management exit, regulatory penalty, acquisition, etc.). These signals are the highest-level stock-specific intelligence surfaced to the copilot for recommendation reasoning. |

---

## Layer 3 — Derivation / Computation Engines

All derivation engines read from prior-layer tables and write computed metrics. No external HTTP calls. Run order matters.

```
bhavcopy → feature_snapshotter → technical_indicator_engine
nse_financials → fundamental_engine
                                    ↘
                                      v3_scores_engine → analytics_refresh
amfi_nav + mf_holdings → mf_analytics_engine → mf_derived_refresh
                                    ↗
```

| # | Service | Input Tables | Computes | Frequency | Output Table(s) | Business Significance & Scoring Role |
|---|---------|-------------|---------|-----------|-----------------|--------------------------------------|
| 27 | `feature_snapshotter` | `nidp.stock_ohlcv` (250-bar lookback) | Moving averages, momentum, volatility features | Daily (post-bhavcopy) | `nidp.stock_features_daily` | Computes daily price-based features for every Nifty 500 stock: SMA20/50/200, EMA20, price-to-SMA ratios, 1M/3M/6M/12M momentum, and historical volatility. These are the raw ingredients for the technical_indicator_engine. The SMA200 crossover is one of the most-watched long-term trend signals; price above SMA200 is a prerequisite for a positive technical health rating in V3 scoring. |
| 28 | `technical_indicator_engine` | `nidp.stock_ohlcv` (full history) | RSI, MACD, Bollinger Bands, ADX, Stochastic, volume profile | Daily (backfill-capable via `--from/--to`) | `nidp.stock_technical_indicators_daily` | Computes the full suite of technical indicators used in momentum and trend assessment. RSI identifies overbought/oversold conditions. MACD signals trend reversals. Bollinger Bands measure volatility and breakouts. ADX quantifies trend strength. Together these form the "technical health" half of the V3 stock score — a stock with strong technicals but weak fundamentals gets a split signal that the copilot surfaces explicitly. |
| 29 | `fundamental_engine` | `nidp.nse_financials_quarterly/annual` + price history | P/E, ROE, debt ratios, growth rates, EPS trends | Daily (post `nse_financials`) | `nidp.stock_fundamentals_daily` | Derives financial health ratios from raw XBRL data: Price-to-Earnings, Price-to-Book, Return on Equity, Return on Capital Employed, Debt-to-Equity, Interest Coverage, Revenue Growth (QoQ and YoY), and EPS trends. These ratios are the "fundamental quality" half of the V3 stock score. A company with high ROE, low debt, and consistent earnings growth scores highly; a loss-making company with high leverage scores poorly regardless of its price momentum. |
| 30 | `mf_analytics_engine` | `nidp.mf_nav_daily` + `nidp.mf_holdings` | MF returns, volatility, expense ratios, holdings concentration | Daily | `nidp.mf_analytics_daily` | Computes performance and risk analytics for each mutual fund scheme: trailing returns at 1M, 3M, 6M, 1Y, 3Y, 5Y; annualised volatility; Sharpe ratio; max drawdown; top-10 holding concentration; sector exposure. These are the raw analytics that determine whether a fund is genuinely delivering risk-adjusted outperformance or just riding a bull market. Foundation for the MF health score. |
| 31 | `mf_derived_refresh` | `nidp.mf_analytics_daily` | Rolling returns, cumulative alpha, category ranks | Daily (post `mf_analytics_engine`) | `nidp.mf_derived_metrics` | Computes competitive ranking metrics: rolling return consistency (did it beat the benchmark across multiple periods?), cumulative alpha vs. category benchmark, and percentile rank within peer group (e.g., top 20% among Large Cap funds). Category rank is the key MF scoring gate — only funds in the top quartile of their category receive a positive V3 health signal, preventing mediocre funds from being recommended. |
| 32 | `snapshot_builder` | bhavcopy + delivery + fii_dii + corporate_actions + bulk/block deals + index constituents | Consolidated daily market snapshot (preflight-checked) | Daily | `nidp.daily_snapshot` | Aggregates all daily market data inputs into a single coherent snapshot per date, after running a preflight check that all required feeds have landed. This snapshot is the primary "market day complete" artifact — analytics queries, portfolio valuation, and copilot context generation all read from it. A missing or incomplete snapshot means no portfolio valuation can run for that day. |
| 33 | `v3_scores_engine` | `stock_fundamentals_daily` + `stock_technical_indicators_daily` + `mf_derived_metrics` | V3 composite Quality + Health scores (proprietary framework) | Daily (last in chain) | `nidp.v3_stock_scores_daily`, `nidp.v3_mf_scores_daily` | The final scoring step: combines fundamental quality metrics and technical health indicators into a single composite V3 score per stock, and combines MF return analytics and category ranks into a composite MF score. These scores are the output that gates copilot recommendations — only stocks/funds above the score threshold are surfaced as actionable recommendations. The score band also determines Buy / Hold / Review signals. |
| 34 | `analytics_refresh` | All base tables | Aggregated rankings, performance summaries, user-facing analytics | Daily (final step) | Materialized views + summary tables | Materializes the final user-facing analytics layer: stock rankings by sector, top gainers/losers, best/worst MF categories, sector rotation signals, and market breadth metrics. These pre-aggregated views are what the DaaS API serves directly to the copilot in milliseconds. Without this refresh, the copilot would need to compute rankings on-the-fly from raw tables — making every response slow. |

---

## Layer 4 — Portfolio Sync & Intelligence

### 4.1 Portfolio Data Sync (from GCS)

| # | Service | Source | Data Type | Frequency | Output Table | Business Significance & Scoring Role |
|---|---------|--------|-----------|-----------|-------------|--------------------------------------|
| 35 | `portfolio_holdings_sync` | GCS — CAS export files | Per-account MF + equity holdings snapshots | Daily | `nidp.portfolio_holdings` | Stores each user's current portfolio snapshot — every fund scheme they hold with units, average NAV, and current value — parsed from their Consolidated Account Statement (CAS). This is the bridge between a user's real-world portfolio and NIDP's market data warehouse. Without this sync, the copilot cannot give personalized advice; it can only speak in generalities about stocks or funds. |
| 36 | `portfolio_transactions_sync` | GCS — raw CAS exports | All transactions: buys, sells, reinvestments, corp-action adjustments | Daily | `nidp.portfolio_transactions` | Stores every historical transaction in a user's portfolio: SIP instalments, lump sum purchases, redemptions, switches, STPs, SWPs, and dividend reinvestments. Transaction history is required to compute XIRR (actual personal rate of return), tax lot tracking using FIFO for capital gains calculation, and to reconstruct portfolio evolution over time — all features the copilot uses to answer "how is my portfolio actually performing?" |
| 37 | `portfolio_goals_sync` | GCS — user goals exports | User investment objectives, target allocations, timelines | Daily | `nidp.portfolio_goals` | Stores each user's stated financial goals: target corpus (e.g., ₹1 crore for retirement), investment horizon (e.g., 15 years), risk tolerance (Conservative / Moderate / Aggressive), and preferred asset categories. Goal alignment is used by the copilot to evaluate whether a user's current holdings are actually suitable for their stated objectives — a conservative user heavily invested in small-cap funds is a misalignment the copilot flags. |
| 38 | `portfolio_intelligence_sync` | `nidp.portfolio_holdings` + all market data tables | Computed portfolio-level risk metrics, security mapping, analytics | Daily (post holdings sync) | `nidp.portfolio_intelligence` | Enriches each user's holdings with live market intelligence: maps CAS ISINs to NIDP symbols, fetches current scores and risk ratings, computes portfolio-level beta (overall market sensitivity), sector concentration, equity/debt/cash split, and overlap between held funds. This enriched view is what the copilot reads when a user asks "what's wrong with my portfolio" — it can surface high beta, poor V3-scored funds, or over-concentration as specific findings. |

### 4.2 Intelligence & Event Tracking

| # | Service | Input | Frequency | Output | Business Significance & Scoring Role |
|---|---------|-------|-----------|--------|--------------------------------------|
| 39 | `intelligence_layer` | All NIDP warehouse tables | Daily | `nidp.intelligence_signals` | Synthesises all NIDP data into top-level market intelligence signals: macro regime classification (risk-on / risk-off), sector rotation signals (money moving from IT to PSU Banks, etc.), market breadth (% of Nifty 500 above SMA200), and anomaly flags (unusual FII outflow, earnings revision trends). These signals form the macro + market context that the copilot injects into every user conversation to make advice relevant to current market conditions. |
| 40 | `event_day_poller` | `nidp.event_calendar` | Intra-day | `nidp.event_status` | On the day a corporate event is scheduled (a quarterly result or board meeting), this poller checks whether the event has actually occurred yet — i.e., whether the announcement has landed in corporate_announcements. It emits a trigger signal when the event fires, creating the event-driven chain: event_calendar forecasts → event_day_poller detects → event_analyzer processes within minutes of the announcement going live. |
| 41 | `dq_ai` | `nidp.job_log` + validation failure history | On-demand (CLI) | Console / diagnostic reports | A CLI-only data quality tool for engineers. In `analyze` mode: reads a job_run_id and uses AI to identify patterns in validation failures — e.g., "the last 5 failures for bhavcopy all show a DATE_MISMATCH pattern, likely a scheduler timezone issue." In `propose` mode: generates data expectation rules for a dataset based on its statistical profile. Directly improves data reliability, which is upstream of score accuracy. |

---

## Feed Count Summary

| Layer | Feeds | External Sources |
|-------|-------|-----------------|
| External Ingestion | 24 | NSE (11), AMFI/MFAPI (3), AMC sites (2), RBI (1), FRED (1), BSE (1), Yahoo Finance (1), GCS (4) |
| AI Classification | 2 | Claude Haiku (announcements), Claude (events) |
| Derivation Engines | 8 | Internal DB only |
| Portfolio + Intelligence | 7 | GCS (4), Internal DB (3) |
| **Total** | **41** | |

---

## Run Order (Daily Chain)

```
17:30 IST  ── bhavcopy ──────────────────────────────────────────┐
                ├── delivery (T+1)                                │
                ├── index_close                                   │
                ├── fno_bhavcopy                                  ▼
                └── snapshot_builder ──────────── daily_snapshot

18:00 IST  ── fii_dii, bulk_deals, block_deals
           ── corporate_actions
           ── nse_financials, nse_shareholding
           ── event_calendar → event_day_poller

~19:00 IST ── feature_snapshotter
           ── technical_indicator_engine
           ── fundamental_engine
                └── v3_scores_engine (stock domain)

22:30 IST  ── amfi_nav
           ── amfi_nav_history (incremental)
           ── mf_analytics_engine
                └── mf_derived_refresh
                      └── v3_scores_engine (mf domain)
                            └── analytics_refresh

           ── portfolio_holdings_sync
                └── portfolio_intelligence_sync
                      └── intelligence_layer

Intra-day  ── corporate_announcements_nse / _bse (continuous)
           ── announcement_classifier (every 10 min)
           ── event_day_poller

Weekly     ── nse_equity_master
Quarterly  ── index_constituents
Monthly    ── mf_holdings, mf_disclosure_snapshot
One-shot   ── yfinance_backfill
On-demand  ── dq_ai, amc_urls_drift_check
```

---

## Key Schema Locations

| Schema | Purpose |
|--------|---------|
| `nidp` | Core market data tables (bhavcopy, delivery, fii_dii, mf_*, etc.) |
| `public` | Equity prices, index data |
| `ref` | Instruments, sector master, ISIN mapping |
| `dq` | Data quality — `validation_findings` (note: `job_run_id` not `source_run_id`; `actual` is TEXT `'True'`/`'False'`) |
| `features` | Stock features, fundamentals, technical indicators |
| `events` | Corporate announcements, event calendar, signals |
| `analytics` | MF analytics, portfolio analytics, V3 scores |
| `audit` | 7-year immutable audit trail |
| `portfolio` | Bridge tables for V3 engine + portfolio holdings/intelligence |
| `graph` | Overlap + correlation matrices |
