# Copilot Q&A Coverage Matrix — NIDP-grounded deterministic answers

> **Status of this doc:** coverage audit (deliverable 1 of the "deterministic answer layer" work).
> No code changed. Grounded in a read of the live copilot agent + tools + DaaS client on
> branch `feat/selection-framework` (2026-06-28). Where a row says "wired", it means a tool
> in `backend/services/copilot_tools/` actually surfaces that field today — verified by reading
> the function, not inferred from the question bank.
>
> **Source spec:** the 298-row `nivesh_question_bank.json` (each row carries `intent`,
> `data_source`, `live_static`, `needs_disclaimer`). This matrix maps every subcategory in that
> bank to: *is the data in NIDP?* → *which tool/endpoint serves it today?* → *what's the gap?*

---

## 1. How to read this (the design it feeds)

Per the locked decisions, the deterministic layer is a **capability registry** sitting on the
existing LangGraph router (`backend/nidp/services/copilot_agent/`). It does **not** replace the
LLM; the LLM still *phrases* an answer over locked tool data (anti-hallucination rules in
`_llm.py` + the `compliance` node remain the floor). The registry's job is to make
**routing + data-source selection deterministic** and to enforce the no-data policy.

Every question subcategory falls into one of three buckets:

| Bucket | Meaning | Layer behaviour |
|---|---|---|
| **A — WIRED** | NIDP data exists **and** a tool already surfaces it | Route → tool → LLM phrases locked data. Deterministic today. |
| **B — DATA, NOT WIRED** | NIDP data exists but no tool surfaces it (or only partially) | Build/extend a tool. Until then, behaves like C. |
| **C — NO NIDP DATA** | Not in the data lake at all | LLM answers from general knowledge **with a loud disclaimer** ("not from Nivesh data; may be outdated"). Per locked decision. |

The registry stores, per subcategory: `intent`, `data_source`, `bucket`, `tool/endpoint`,
`needs_disclaimer`, and (for C) `disclaimer_class`.

---

## 2. Headline coverage

Counts are by **question-bank subcategory** (a few rows are mixed and noted inline). Treat these
as ±a couple per section — the point is the shape, not a false-precision total.

| Section | A — Wired | B — Data, wire it | C — No data → LLM+disclaimer |
|---|---:|---:|---:|
| Stocks | ~38 | ~11 | ~22 |
| Mutual Funds | ~50 | ~10 | ~14 |
| ETFs & Index Funds | 0 | 1 | 6 |
| Market Pulse | ~7 | ~9 | ~11 |
| Portfolio (personalised) | ~16 | ~5 | ~3 |
| Planning & Education | ~5 | ~3 | ~5 (concept explainers) |
| Account & Platform | 0 | 0 | ~12 (action/execution — out of copilot scope) |

**Takeaways**
1. **Portfolio (73%) and Risk (88%) are the strongest** — these are the home turf and already deterministic.
2. **Stocks and Mutual Funds are mostly wired** for fundamentals/technicals/scores/holdings; the gaps are predictable (analyst estimates, third-party ratings, calendar-year returns, intraday).
3. **Market Pulse is the weakest data-backed section** — international markets, commodities/FX, macro calendar, IPO pipeline, and VIX are simply not ingested.
4. **Account/Platform questions are *action* intent, not Q&A** — they belong to transactional routes, not this layer. Flag as out-of-scope, hand off to the relevant flow.

---

## 3. Stocks

Tools: `copilot_tools/fundamental.py`, `technical.py`, `company_financials.py`,
`stock_intelligence.py`, `instrument_research.py`; node `nodes/stock.py`.
Primary data: DaaS `/v1/features/stocks/{symbol}/latest`, `/v1/financials/{symbol}`,
`/v1/shareholding/{symbol}`, `/v1/corporate-actions/{symbol}`, `/v1/stocks/scores/{symbol}`.

| Subcategory (example) | Bucket | Where it's served / why not |
|---|---|---|
| Live price; up/down today | A | `instrument_research` `close`, `day_change_pct` (EOD — **not** intraday tick) |
| 52-week high/low | A | `technical` `dist_52w_high_pct/low_pct` |
| All-time high/low | C | not in feature store |
| OHLC (open/high/low/prev close) | B | only `close`/`prev_close` surfaced; OHLCV exists in `prices_eod` — wire it |
| Volume; unusual volume | B | only `vol_z20` (z-score); raw volume in `prices_eod` not surfaced |
| Pre-open / GIFT indication | C | no intraday/pre-open feed |
| Circuit (upper/lower) | C | not ingested |
| Face value / lot size | B | face value only via split events; F&O lot size not surfaced |
| P/E | A | `fundamental` `pe_ttm` |
| P/E vs 5-year average | C | only current sector median; no 5y history |
| P/E vs sector/peers | A | `fundamental` `sector_median_pe` + `pe_ttm` |
| P/B | A | `fundamental` `pb` |
| PEG | A | `instrument_research` computes `pe_ttm / eps_growth_yoy_pct` |
| EV/EBITDA | A | `stock_intelligence` `ev_ebitda` primitive |
| P/S | C | no price-to-sales primitive |
| Market cap | A | `market_cap_cr`, `market_cap_bucket` |
| Enterprise value (absolute) | B | only EV/EBITDA ratio; absolute EV not exposed |
| Overvalued/undervalued; fair/intrinsic value | B→C | qualitative `valuation_signal` only; no computed intrinsic value (DCF) → phrase signal, disclaim the rest |
| Cheap vs history | C | no historical valuation band |
| Period returns 1M…10Y | B | `return_20d_pct`/`return_252d_pct` only; longer windows derivable from `prices_eod` |
| CAGR since listing | C | not computed |
| Vs index / vs sector | B | relative strength exists in intel features; not consistently surfaced |
| Best/worst calendar years; crash drawdown | C | not computed |
| ROE | A | `fundamental` `roe_pct` |
| ROCE / ROIC | A | `stock_intelligence` `roce_pct` |
| Margins (net/op/EBITDA/gross) | A (partial) | `company_financials` `ebitda_margin_pct`, `pat_margin_pct` (no gross) |
| Margin trend | A | `profit_margin_trend_pct` + quarterly interpretation |
| Asset turnover | C | not in feature store |
| Revenue growth (YoY/CAGR) | A | `revenue_growth_yoy_pct`, `revenue_growth_3y_cagr_pct` |
| Profit / EPS growth | A | `pat_growth_yoy_pct`, `eps_growth_yoy_pct`, 3y CAGR |
| Growth accelerating/slowing | A | `company_financials` `growth_trend` |
| Earnings forecast next year | C | no analyst estimates |
| D/E | A | `debt_to_equity` |
| Total / net debt | A | `total_debt_cr`, `net_debt_cr` |
| Debt-free? | B | inferable from `total_debt_cr≈0`; not flagged |
| Interest coverage | A | `interest_coverage` primitive |
| Current / quick ratio | C | balance-sheet ratios not computed |
| FCF trend | C | cash-flow statement not extracted |
| Cash reserves | A | `company_financials` `cash_cr` |
| Red flags | B | implicit in Altman-Z / Piotroski / pledge; no explicit taxonomy |
| Latest quarterly results | A | `company_financials` (8 quarters) |
| Beat/miss estimates | C | no estimates to compare |
| EPS (TTM/quarterly) | A | quarterly `eps_basic`; TTM via `pe_ttm` |
| Income statement / balance sheet / cash flow | B | P&L + partial BS; **no cash-flow statement** |
| Next results date | C | no earnings calendar per stock |
| Concall takeaways; guidance | C | no transcripts/guidance |
| Dividend yield | A | `dividend_yield_pct` |
| Dividend history; ex-date; buyback | A | `instrument_research` corporate-actions |
| Payout ratio | C | not computed |
| Promoter holding; pledging; FII/DII; MF holders | A | `company_financials.get_shareholding_analysis` |
| Shareholding pattern change | A | QoQ deltas surfaced |
| Bulk / block deals | B | data in `nidp.bulk_deals`/`block_deals`; no tool reads it |
| Support/resistance | A | `swing_low_20`/`swing_high_20` |
| 50/200 DMA | A | `sma20/50/200` |
| RSI; MACD | A | `rsi14`, `macd`, `macd_hist` |
| Bollinger | C | not in feature store |
| Chart pattern | C | not detected |
| Technical buy/sell | A | rules-based on fundamental/technical scores |
| Pivots | B | only `pivot_breakout_flag` boolean; not levels |
| Trend | A | trend vs SMA + composite |
| Analyst consensus / target / range / split / changes | C | **no analyst feed** — whole subsection |
| Stock split / bonus / rights history | A | corporate-actions |
| M&A; demerger/spin-off/delisting | C | not classified separately |
| Latest news; why-move; sentiment | B/C | only AI-classified **NSE/BSE announcements** (`/v1/announcements`, `/v1/signals`) — not a news feed; phrase those, disclaim "announcements only" |
| Legal / regulatory; retail/social buzz | C | not tracked |
| Beta; volatility | A | `beta_1y`, `volatility_1y_pct`/`atr_pct` |
| Short interest / delivery % | B | delivery % in `nidp.delivery_data`; not surfaced. Short interest: C |
| Business model / segments / competitors / moat / management / risks | C | qualitative — no knowledge base. (Segments partly in financials but not extracted) |
| Head-to-head; buy LT; trade ST; bull/bear; hold/exit | A | compose existing tools; `hold/exit` uses portfolio holdings |
| ESG / governance / auditor | C | not ingested |

---

## 4. Mutual Funds

Tools: `copilot_tools/mf.py`, `mf_intelligence.py`, `mf_cards.py`, `sip.py`,
`scheme_resolver.py`; nodes `nodes/mf.py`, `nodes/goal.py`.
Primary data: DaaS `/v1/mf/performance/scorecard/{code}`, `/v1/mf/schemes/{code}`,
`/v1/mf/holdings/{code}`, `/v1/mf/nav/{code}`, `/v1/mf/schemes/{code}/events`,
`/v1/mf/performance/v3-primitives/bulk`.

| Subcategory | Bucket | Where it's served / why not |
|---|---|---|
| Latest NAV; NAV history | A | `/mf/nav/{code}` |
| Fund type; category; benchmark; launch date/age | A | `/mf/schemes/{code}` |
| AUM | A | scorecard `aum_cr` |
| Returns 1Y/3Y/5Y/since-inception; CAGR | A | scorecard `return_1y/3y/5y`, `return_since_launch_cagr` |
| Calendar-year returns | C | not in scorecard |
| Rolling returns | B | v3-primitives endpoint exists; not called by copilot |
| Vs benchmark | B | `alpha_*` only — no direct index overlay |
| Vs category average | B | `category_avg_*` exists in primitives; only shown in returns view |
| Category rank | A | `composite_rank`, `total_in_category` |
| SIP vs lumpsum | A (math) | `sip.py` projections |
| Expense ratio (+ direct/regular gap) | A | scorecard `ter` + primitives `expense_ratio_direct/regular` |
| Expense vs category | B | only `qtile_ter` quartile, not absolute peer avg |
| Exit load | A | `exit_load_pct/text` |
| Minimum investment | C | not in scheme master |
| Std dev / volatility | A | `volatility_1y` |
| Sharpe; Sortino; beta; alpha | A | scorecard + primitives (1Y/3Y) |
| Max drawdown | A | `max_drawdown_1y` |
| Riskometer | A | `risk_o_meter` |
| Upside/downside capture | C | not computed |
| Value Research / Morningstar / CRISIL rating | C | **no third-party ratings** — whole subsection |
| Top holdings; sector allocation; cap split; holdings count; top-10 concentration | A | `/mf/holdings/{code}` |
| Portfolio turnover | A | scorecard `portfolio_turnover_pct` |
| Overlap between two funds | A | `/mf/holdings/overlap` |
| Recent portfolio changes | C | no holdings-delta feed (manager/TER events only) |
| Fund manager; AMC | A | scheme detail |
| Manager tenure / track record | B | `manager_tenure_years` in primitives; not surfaced |
| Other funds by same manager | C | no manager→funds reverse lookup |
| Debt: duration / YTM / credit quality / rate risk | B (partial) | credit `rating` aggregated from holdings; duration/YTM not in feed |
| Taxation (LTCG/STCG, ELSS 80C, IDCW) | C | no tax-rules engine. **Disclaim — tax rules drift.** |
| Growth vs IDCW | A | plan metadata via scheme detail |
| How to invest / STP / SWP | C | action intent — hand off to platform |
| Lock-in | A (partial) | ELSS inferable from category; explicit lock-in field not present |
| Fund vs fund; fund vs index; good-LT; exit/switch | A | compose scorecard + overlap + events |
| Fund vs FD/PPF | C | no fixed-income comparison data |
| Risk-profile fit; horizon; goal fit; beginner | B/C | inferred from vol/drawdown; no questionnaire wiring |
| Consistency; crash performance (2020) | A / C | `qtile_consistency` (A); 2020-specific history (C) |
| SIP growth / goal-SIP / step-up | A (math) | `sip.py` |
| Past-SIP value | C | no historical SIP-execution lookup |
| Best category / top SIP / lowest expense / high-Sharpe / best ELSS | A | `/mf/performance/category` + screener |
| NFOs open | C | no NFO feed |

---

## 5. ETFs & Index Funds

| Subcategory | Bucket | Note |
|---|---|---|
| Tracking error | C | no tracking-error field |
| ETF vs index fund (educational) | C | educational; LLM+disclaimer |
| ETF liquidity / bid-ask spread | C | no intraday/quote data |
| iNAV vs price (premium/discount) | C | no intraday NAV |
| Index fund P/E / yield | C | no index-composition valuation feed (note: `nidp.index_eod` has index PE/PB/div-yield — **possible B** if wired) |
| Gold / silver ETF | C | no commodity-ETF metadata |
| US / international indices | C | no international universe |

> One genuine **B** opportunity: `nidp.index_eod` already stores `pe_ratio`, `pb_ratio`,
> `div_yield` per index — "Nifty fund's current P/E" could be wired off the existing index feed.

---

## 6. Market Pulse

Node `nodes/market.py`; DaaS `/v1/indices/summary`, `/v1/flows/fii-dii`, `/v1/macro/latest`,
`/market-pulse/{movers,earnings,corporate-actions,institutional-positioning,articles}`.

| Subcategory | Bucket | Note |
|---|---|---|
| FII/DII today/month/sector/trend; FII pressure | A | `/v1/flows/fii-dii` |
| Nifty/Sensex/Bank Nifty today + levels | A | `/v1/indices/summary` |
| Market breadth (adv/decl); midcap vs smallcap | B | indices summary lacks breadth; derivable from `prices_eod` |
| India VIX | C | **not ingested** (note: `fred_macro` has US VIXCLS, not India VIX) |
| Top gainers/losers; 52w highs/lows today | A | `/market-pulse/movers` |
| Sector leaders/laggards; best sector; sectoral perf | B | sector screener exists; not routed through market node |
| Defensive rotation; smart money | C | no rotation metric |
| Earnings this week/today | A | `/market-pulse/earnings` |
| Dividends/bonus/splits this month; ex-dates soon | A | `/market-pulse/corporate-actions` |
| Board meetings / AGMs | C | not in corporate-actions feed |
| Big corporate / deal news | B | `/market-pulse/articles` (announcement-derived) |
| IPOs open/upcoming; GMP; apply?; listing; allotment | C | **no IPO/primary-market feed** — whole subsection |
| US / Asia / Europe / GIFT Nifty; Dow/Nasdaq/S&P | C | **no international market feed** |
| Crude/Brent; gold; silver; DXY; USD-INR | C | **no commodities/FX feed** (FRED has US oil/gold spot only — partial B) |
| Fed; RBI repo; CPI; GDP; IIP/PMI; budget | C/B | RBI yields in `nidp.rbi_yields` (B); decisions/CPI/GDP/calendar not tracked (C) |
| 10Y G-Sec yield | B | `nidp.rbi_yields` exists; not surfaced via market node |
| FII index futures/options positions; OI/PCR | A | `/market-pulse/institutional-positioning` |
| Long/short buildup; max pain; rollover | B | `nidp.fno_bhavcopy` + `v_options_chain_latest` exist; not surfaced |
| Hot theme; market summary; what-to-watch; mood | B/C | articles give theme/sentiment; forward-looking/mood are C |

---

## 7. Portfolio (personalised)

Tools: `copilot_tools/portfolio.py`, `risk.py`; nodes `nodes/portfolio.py`, `nodes/risk.py`.
This is the most complete section.

| Subcategory | Bucket | Where served |
|---|---|---|
| Portfolio today; value; P&L / XIRR; best/worst | A | `get_portfolio_xirr`, `get_portfolio_summary` |
| Drag / drivers | A | xirr rows + summary |
| Event impact on holdings | B | corporate-actions not joined to holdings |
| Sector overexposure; concentration; cap mix; asset mix | A | `get_concentration_breakdown`, `get_portfolio_summary` |
| Fund overlap | A | `get_portfolio_overlap` |
| Rebalance; trim; underperformers | A | `get_rebalance_plan`, `get_top_recommendations` |
| Deploy new money | B | screener can suggest; no "where to put ₹X" allocator |
| Goal tracking | B | handled in goal node, not portfolio tools |
| Tax-loss harvest; realised cap gains | A | `get_tax_harvest_candidates`, `get_full_tax_report` |
| Price alerts; watchlist; results-notify | C | action intent — no CRUD in copilot |

**Risk (88% — strongest):** risk-profile fit, portfolio risk rating, VaR (1d/10d, 95/99),
volatility, max drawdown, beta, stress tests (GFC/COVID/rate/inflation) all **A** via
`risk.py`. Correlation-based diversification is **B** (endpoint exists, not wired).

---

## 8. Planning & Education / Account & Platform

| Subcategory | Bucket | Note |
|---|---|---|
| Retirement / goal / tax calculators; SIP calculator | A | goal node + `sip.py` + `get_full_tax_report` |
| Asset allocation by age; inflation-adjusted | B | `get_target_allocation` by risk profile (age/inflation not used) |
| Emergency fund size | C | no calculator |
| Concept explainers (PE, SIP, compounding, …) | C | **deliberately blocked today** by anti-hallucination rules; safest as curated static content, else LLM+disclaimer |
| Account: order status, buy/redeem/switch, SIP manage, KYC, statement, mandate, nominee, how-to | C (out of scope) | `intent: action` — route to transactional flows, not this Q&A layer |

---

## 9. The no-data (Bucket C) policy — disclaimer classes

Per the locked decision, Bucket C answers come from LLM general knowledge **with a loud
disclaimer**. Not all C is equal — propose three disclaimer classes so the layer can pick wording:

1. **`stale_market`** — figures that move and we don't track (analyst targets, IPO GMP,
   international/commodity/FX levels, India VIX, NFOs). *"This isn't from Nivesh's data and may be
   out of date — verify before acting."*
2. **`rules_drift`** — tax/regulatory facts that change with law (LTCG/STCG, ELSS 80C, IDCW tax).
   *"General guidance only; tax rules change — confirm current rules / consult a professional."*
3. **`qualitative`** — judgement with no single source (moat, management quality, governance,
   business model). *"This is a general view, not Nivesh analysis or a recommendation."*

Bucket C rows that are **action intent** (Account/Platform, how-to-invest, STP/SWP) should **not**
get an LLM answer — they hand off to the relevant product flow.

---

## 10. Recommended build order (for the layer that follows this audit)

1. **Ship the registry over Bucket A first** — it's already deterministic; the registry just makes
   routing explicit and lets us assert "this question is answered from `<tool>`" in tests.
2. **Highest-value Bucket B wins** (data already in the lake, only wiring needed):
   index P/E from `index_eod`; 10Y yield + RBI repo from `rbi_yields`; raw volume/OHLC + delivery %
   from `prices_eod`/`delivery_data`; bulk/block deals; F&O OI/PCR/max-pain from `fno_bhavcopy`;
   longer-window stock returns; MF rolling returns / vs-category / manager tenure (already in
   primitives). These convert C-looking answers into deterministic ones cheaply.
3. **Wire the Bucket C disclaimer classes** so no-data answers are safe by construction.
4. **Mark Account/Platform action intents** as hand-offs, not Q&A.

---

*Generated from a read-only audit of `copilot_tools/*`, `copilot_agent/nodes/*`, and
`daas_client.py`. Field/endpoint names are quoted from the code as of 2026-06-28. Counts are
subcategory-level estimates; the per-row truth is in the section tables above.*
