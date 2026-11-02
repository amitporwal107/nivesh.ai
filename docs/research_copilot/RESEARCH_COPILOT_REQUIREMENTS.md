# Nivesh Research Copilot: requirement, intent catalogue and coverage check

**Status:** DRAFT. It waits on the owner's decisions in section 11. · **Date:** 2 Nov 2026 · **Owner:** Amit Porwal
**Source requirement:** [RESEARCH_COPILOT_QUESTIONNAIRE_SOURCE.md](RESEARCH_COPILOT_QUESTIONNAIRE_SOURCE.md), the owner's paste of 2 Nov, saved verbatim.

**Baseline ("what is built"):** `origin/dev` at 33d266fd (1 Nov 2026), plus the open work named where it matters.

**Evidence used:**
- code on `origin/dev`, cited by path;
- read-only aggregate queries on the staging NIDP warehouse, run on 2 Nov 2026 (Appendix A). The latest trading session in the data is Friday 30 Oct;
- the 31 Oct gap analysis in [../intelligence_copilot/PRD_v2_GAP_ANALYSIS.md](../intelligence_copilot/PRD_v2_GAP_ANALYSIS.md). Facts taken from it, not measured again today, are marked *(31 Oct)*.

**Not verified:** no question from the bank was asked to the running Copilot as a signed-in user, and no answer was graded. Every "routes to" in this document is read from the code, not observed.

---

## 0. Bottom line

1. **What the requirement is:** a question taxonomy for a research-analyst style Copilot. It has 28 categories, about 250 sample questions, 12 intent groups, and an 8-stage answer pipeline (intent → query planner → data agents → structured analysis → evidence validation → AI interpretation → answer with charts, tables, risks and confidence).
2. **It is the question bank that the 31 Oct PRD v2 (evidence-driven visual Copilot) lacks.** The pipeline it recommends is the one PRD v2 recommends, and it is already the shape of the visual-answer engine (`backend/services/copilot_visual`). **Recommendation:** build it on PRD v2's evidence framework and the `visual-answer-v1` contract. Do not start a third Copilot stack.
3. **Coverage today, by category** (section 5):
   - **Built:** 2 of the 27 question categories (technical analysis; sector rotation at sector level).
   - **Partial:** 15 (engine and some data exist, no research-shaped answer).
   - **Blocked by data:** 3 (balance sheet, red flags / forensics, correlation and sensitivity), plus the cash-flow half of financial analysis.
   - **Missing:** 7 (no engine: thesis, historical patterns, hypothesis tests, contradictions, "What changed?", reports, monitoring).
4. **The data gaps are measured, not guessed.** On the staging warehouse, 2 Nov:
   - **empty tables:** cash flow (`nse_financials_cashflow`), consensus estimates (`earnings_estimates`), insider and SAST trades (`insider_sast`) and macro series (`fred_macro`);
   - **never filled:** the balance-sheet columns of the quarterly financials, in every period since Sep 2025;
   - **null for every stock:** EV/EBITDA, interest coverage, current ratio and CFO/PAT;
   - **short history:** daily prices start on 1 Apr 2024; daily features (P/E, ROCE, RSI and so on) start on 29 Dec 2025; earnings-call transcripts start on 19 May 2026.
5. **So several flagship questions cannot be answered truthfully today, and the Copilot must say so instead of letting the model fill the gap.** Examples: "PAT vs operating cash flow", "Is receivables growth unusually high?", "Was the quarter better than expected?", "What is the historical P/E range?", "Compare commentary across the last 4 quarters" and "How sensitive is it to crude?".
6. **The sharpest decision is regulatory, not technical** (section 7). "Investment case", "expensive or cheap", "bullish interpretation", "research conclusion" and "generate a research report" read as research recommendations under SEBI's Research Analyst rules unless Nivesh is registered. This repeats the open SEBI wording decision in PRD v2.
7. **The cheapest valuable first step** is to store the ~250 questions as a routing fixture and run it against the live router. That measures real coverage for near-zero cost. After it come "screen in chat" (already planned as W4 to W7 on the PR #447 stack) and a first "What changed?" answer built only from data that exists.

**PM recommendation: BUILD, in phases** (section 10). Phase 1 uses existing data only. Phase 2 is data ingestion, and Phase 3 is new engines (planner, event and factor study, thesis store). Phase 3 starts only after the PRD v2 composition decision.

---

## 1. The requirement, restated

The owner wants the Copilot to work like a research analyst's assistant. A user should be able to ask any of the questions in the bank and get a structured, evidence-backed answer. The answer should combine several data families at once: fundamentals, technicals, delivery, shareholding, FII/DII, corporate events, sector intelligence and historical validation.

The requirement has four parts:

| Part | What it asks for | Where in the source |
|---|---|---|
| A. Question taxonomy | 27 question categories (1–27) plus suggested prompt cards (28) | §1–§28 |
| B. Answer shapes | Fixed outputs for some commands: the thesis builder (bull / bear / catalysts / monitor / invalidation); hypothesis tests (sample size, period, win rate, mean, median, max drawdown, confidence, limitations); "What changed?" (9 sections in a fixed order); the research report (10 sections) | §15, §22, §25, §26 |
| C. Intent architecture | 12 primary intent groups | "Recommended Intent Architecture" |
| D. Answer pipeline | Intent detection → query planner → data / research agents → structured analysis → evidence and source validation → AI interpretation → answer + charts + tables + risks + confidence. Explicitly *not* "user asks → LLM answers" | "My strongest recommendation" |

**Who the user is:** the source says "research analyst" and "the analyst". Whether that means a retail investor in the existing Investor mode or a new Research mode is not stated (Q1, section 11).

---

## 2. How this relates to work already done or planned

| Existing piece | Relationship | What to do |
|---|---|---|
| PRD v2 "Evidence-driven visual Copilot" + gap analysis (`docs/intelligence_copilot/`, 31 Oct) | Same pipeline, same evidence-first rule. PRD v2 has 18 prompt categories, mostly trader-shaped; this bank is research-shaped | Treat this bank as the research question set *inside* PRD v2. One contract (`visual-answer-v1` grown by fields), one renderer |
| Copilot Research Hub (`docs/prd/COPILOT_RESEARCH_HUB.prd.md`; `backend/services/copilot_tools/research_lenses.py` on dev) | Its 10 lenses (valuation, peers, red flags, risk, what's new, …) are single-company quick answers to categories 1, 6, 7, 13 and 9 | Reuse the lens builders as the data step of the matching blueprints |
| Visual-answer engine (`backend/services/copilot_visual/intents.py`, 17 deterministic intents; 10 block types in `payload.py`) | Already implements "deterministic facts → typed blocks → LLM explains, never adds a number" | Add research intents here; add the missing block types (`line`, `table`, `timeline`) |
| LangGraph router (`backend/nidp/services/copilot_agent/nodes/intent_patterns.py`: stock, market, mf, portfolio, risk, goal, recommendation, backtest, stocks_insights, policy) | The fall-back route for everything the visual intents do not catch | Keep it; the routing fixture (FR-RC-01) shows which questions fall through |
| Screener and watchlist in chat (`docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md`; PR #447 open per the 1 Nov handoff; W4 chat `screen_stocks` intent next) | Categories 11, 12 and part of 23 | Do not duplicate it; this requirement adds only the extra factor definitions (section 5, rows 11–12) |
| Smart Money (`backend/nidp/services/smart_money_scores/service.py`, AMC drill-down and KPI cards on dev) | Category 8 | Reuse; its scope note (MF evidence only; FII/DII QoQ scored elsewhere, not twice) carries over |
| Earnings-surprise tracker (Results week) | Category 4; "surprise" there means vs the company's own baseline band, because there is no consensus | Reuse that definition and say it in the answer |
| AI usage and billing engine PRD (`AI_USAGE_BILLING_ENGINE.prd.md`, a 1 Nov draft that is **not on dev yet**: it is untracked in the shared checkout on `feat/provider-foundations`, with no PR) | Composite research answers make several LLM calls | Meter them through it; no separate counting |

---

## 3. Intent catalogue

### 3.1 The 12 groups as pasted, mapped to today's routes

| # | Group (as pasted) | Categories | What catches these questions today (read from code) |
|---|---|---|---|
| 1 | COMPANY_DISCOVERY | 1 | LangGraph `stock_analyst`; research lenses; `stocks_insights` for filings |
| 2 | FUNDAMENTAL_ANALYSIS | 2 (returns), 3 | `stock_analyst` with `copilot_tools/fundamental.py`, `company_financials.py` |
| 3 | FINANCIAL_ANALYSIS | 2 (revenue, margins, cash flow), 3 | same as 2: the two groups share tools and vocabulary |
| 4 | EARNINGS_INTELLIGENCE | 4 | visual `results_calendar` and `event_intelligence`; `stocks_insights` (results numbers, "compare vs last year") |
| 5 | MANAGEMENT_INTELLIGENCE | 5 | `stocks_insights` (concall, guidance and "what did … say" patterns) |
| 6 | VALUATION_ANALYSIS | 6 | `stock_analyst` (P/E); research lens `valuation` |
| 7 | TECHNICAL_ANALYSIS | 10 | visual `stock_decision`, `breakouts`, `unusual_volume` |
| 8 | SMART_MONEY | 8 | visual `smart_money`; ownership pattern → `stock_analyst` |
| 9 | NEWS_AND_EVENTS | 9, 16 | visual `event_intelligence`, `results_calendar`; `stocks_insights`; regulatory-event pattern |
| 10 | SCREENING_AND_DISCOVERY | 11, 12, 23 | screener and numeric-screen patterns → `recommendation` node; visual `top_opportunities`; `POST /api/screeners/run` |
| 11 | HISTORICAL_VALIDATION | 21, 22 | `backtest_analyst` (lump-sum and SIP backtests only, not factor or event studies) |
| 12 | THESIS_AND_RESEARCH | 15, 24, 26, 27 | nothing |

**Not covered by any pasted group:**
- categories 13 and 14 (company risk, red flags);
- categories 17 to 20 (sector, rotation, macro, sensitivity);
- category 7 (peer comparison);
- category 25 ("What changed?").

### 3.2 Proposed adjustment (owner decision Q3)

- **Merge** FUNDAMENTAL_ANALYSIS and FINANCIAL_ANALYSIS into **FUNDAMENTALS**. Both read the same statements and ratios. A question like "Is ROCE improving?" belongs equally to both, so a router cannot separate them reliably and the split would only create misroutes.
- **Add SECTOR_AND_MACRO** for categories 17 to 20.
- **Add RISK_AND_FORENSICS** for categories 13 and 14. Keep it apart from today's `risk_analyst` node, which is about the user's own portfolio and risk profile, not a company's risks. None of `_P_RISK`'s phrases names company risk. So "What are the biggest risks?" for a company is decided by the stock gate or the LLM classifier today. That is UNVERIFIED and goes into the routing fixture.
- **Treat three things as commands over the groups, not as groups:** COMPARE (category 7, and any "A vs B"), WHAT_CHANGED (category 25, with a 30, 90 or 365-day window) and REPORT (category 26). Each command runs blueprints from several groups.

Result: 13 groups plus 3 commands. Every category 1 to 27 has exactly one home.

### 3.3 What the router must extract from every question

- **group**;
- **entity:** a company, several companies, a sector, a universe (for example "Nifty 500"), or the market;
- **window:** for example 30, 90 or 365 days, "last 4 quarters" or "5 years";
- **command**, if any;
- **persona**, which the app sends today.

If the entity is missing and the thread has none, the Copilot asks for it (FR-RC-03).

---

## 4. The answer pipeline, stage by stage

| Stage (as pasted) | What exists on dev | Gap |
|---|---|---|
| Intent detection | Deterministic visual intents (`copilot_visual/intents.py`), the regex fast path (`intent_patterns.py`), and the LLM classifier (`nodes/intent.py`) | Research intents; entity and window extraction for companies, sectors and universes |
| Query planner | Nothing. Each answer runs one engine | A planner composing several engines into one answer. This is PRD v2's §9 composition gap. Known blueprints get fixed plans; free-form questions get a bounded plan (FR-RC-04) |
| Data / research agents | `copilot_tools/*` (financials, fundamentals, stock intelligence, filings retrieval, market research, research lenses), visual builders, DaaS client | Event and factor study engine; "what changed" diff engine; thesis store |
| Structured analysis | Deterministic builders; `stock_features_daily` already holds most factors in one row per stock per day | Trend definitions ("improving", "accelerating", "consistent") as code, not prose |
| Evidence and source validation | Per-source fresh/stale/missing footer; the compliance node's grounding check; `backend/nidp/eval/rag_eval.py` for citations | Evidence class (verified / reported / inference / scenario) per PRD v2. The 1 Nov handoff also recorded that the grounding check gives false warnings when the visual card's facts reach the model inside the human message |
| AI interpretation | The LLM explains a facts block and is told never to add a number | Interpretation must be labelled as interpretation in sections that are opinion-shaped (bull case, "questions management avoided") |
| Answer + charts + tables + risks + confidence | `visual-answer-v1` with 10 block types: `kpis`, `candles`, `bars`, `heatmap`, `quadrant`, `ranked`, `trade_plan`, `list`, `briefs`, `notice` | No `line` (trends over quarters or years), `table` (peer comparison), or `timeline` (events) block. No `confidence` field. Confidence must mean *evidence coverage*, never a probability of profit (PRD v2 §10.3) |

---

## 5. Coverage by category

Status key:
- **Built:** a deterministic visual answer exists.
- **Partial:** the engine and some data exist, but there is no research-shaped answer.
- **Data gap:** cannot be answered truthfully because the data is empty or absent.
- **Missing:** there is no engine either.

Counts are from Appendix A (2 Nov) unless marked *(31 Oct)*.

| # | Category | Group (proposed) | Status | What exists | Data on staging | Main gap |
|---|---|---|---|---|---|---|
| 1 | Company discovery and overview | COMPANY_DISCOVERY | Partial | `stock_analyst`, stock intelligence, research lenses, filings retrieval | Annual reports 7,130 docs for 2,213 companies; investor presentations 3,507 for 1,293 | Segments, customers, competitors and KPIs exist only as text in filings. Answer by quoting the filing with a link, never as computed numbers. Competitors need an industry map: `sector` is set for only 545 of 2,475 stocks in `stock_features_daily` |
| 2 | Financial analysis | FUNDAMENTALS | Partial; Data gap for cash flow | Financials and fundamentals tools | Quarterly P&L for 2,215 companies. Quarters per company: 363 have 20+, 370 have 12–19, 1,218 have 8–11, 264 have fewer than 8. **Cash-flow table empty.** ROE and ROCE are latest-value only (Trendlyne, 2,121 companies) | "5-year revenue" is possible only where 20 quarters exist (363 companies). ROCE trend has no history (features start on 29 Dec 2025). Cash-flow questions are blocked. Needs a `line` block |
| 3 | Balance sheet and financial health | FUNDAMENTALS | Data gap | D/E latest value (Trendlyne, 2,057 companies) | Balance-sheet columns (equity, debt, current assets, receivables) are 0-filled since Sep 2025. Interest coverage, current ratio and cash are null for every stock | Ingest balance sheets (half-yearly XBRL). Debt maturity exists only as annual-report text. Interest coverage can be derived from P&L (EBITDA ÷ finance costs) where finance costs are filed |
| 4 | Quarterly results intelligence | EARNINGS_INTELLIGENCE | Partial (data strong) | Visual `results_calendar` and `event_intelligence`; earnings-surprise tracker; `event_ai_analysis` | Results filings 15,675 docs for 2,406 companies; the Sep-26 quarter has 797 companies so far (results season). **Consensus table empty** | "Better or worse than expected" and "surprised the market" cannot be measured against estimates. Say so, and use the company's own baseline band or the price reaction. Results blueprint (QoQ, YoY, improved and deteriorated metrics) |
| 5 | Earnings call and management | MANAGEMENT_INTELLIGENCE | Partial (history short) | `stocks_insights` concall and guidance patterns | Transcripts: 3,401 docs for 1,256 companies, **only since 19 May 2026**. 356 companies have 4 or more documents, but documents are not distinct calls (de-duplication UNVERIFIED) | "Last 4 quarters" of commentary is not possible before the Feb 2027 season unless transcripts are backfilled (Q4). The promise tracker needs an extraction store. "Questions management avoided" is interpretation and must be labelled as such |
| 6 | Valuation | VALUATION_ANALYSIS | Partial | Research lens `valuation`; `nidp.v_sector_median_pe`; `pe_vs_sector_pct` | P/E for 1,669 stocks, P/B for 2,058. **EV/EBITDA null for all.** Daily valuation history only since 29 Dec 2025 | Historical P/E range: recompute from `prices_eod` (from 1 Apr 2024) and quarterly EPS, which gives at most about 2.5 years. Scenarios ("if earnings grow 15/20/25%") as arithmetic with stated assumptions, labelled "scenario, not a forecast". SEBI wording for "expensive or cheap" (section 7) |
| 7 | Peer comparison | COMPARE command | Partial | Research lens `peers` | As rows 2, 3 and 6. Banks: the quarterly table has interest earned and expended and NIM, but **no GNPA/NNPA** | `table` block; industry map; bank asset-quality metrics are absent, so "asset quality" in the HDFC/ICICI/Axis example cannot be answered yet |
| 8 | Shareholding and smart money | SMART_MONEY | Partial (the MF-evidence part is built) | Visual `smart_money`; `smart_money_scores` (MF accumulation, AMC drill-down) | Shareholding 2,411 companies to Sep-26 (12,457 rows). MF holdings 3,109 schemes, Sep-25 to Sep-26 (1.69 M rows). **Insider/SAST table empty.** Bulk deals only since 9 Oct 2026 | "Are promoters buying or selling?" is answerable only as the quarterly % change, not transaction by transaction. Named FII entries and exits are not available. Use `shareholding_pattern` for QoQ changes: `fii_pct_change_qoq` in the features is filled for only 546 stocks |
| 9 | Corporate events and news | NEWS_AND_EVENTS | Partial | Visual `event_intelligence`; filings retrieval; announcement classifier | NSE announcements fresh; BSE returns HTTP 403 since 13 Oct *(31 Oct)* | "Why is the stock moving today?" is a composition: live price, same-day filings and the sector move. There is no general news feed. "What happened after similar events?" needs the event-study engine (row 21) |
| 10 | Technical analysis | TECHNICAL_ANALYSIS | **Built** (mostly) | Visual `stock_decision` (candles, EMA 20/50/200, levels), `breakouts`, `unusual_volume`; Chart Analysis v2 | Features for 2,475 stocks to 30 Oct: SMA 20–200, RSI, MACD, 20-day delivery, volume z-score, 52-week distances, accumulation score | Divergence detection and consolidation patterns beyond `pivot_breakout_flag`. "Is institutional participation visible?" can only be a proxy (delivery, bulk deals), and the answer must say so. In Trader mode, "Is the stock bullish?" must not turn into a trade plan unless asked |
| 11 | Multi-factor research queries | SCREENING_AND_DISCOVERY | Partial | `POST /api/screeners/run`; the PR #447 stack (W4 chat screens next) | Most factors are in one features row: ROCE, revenue growth YoY, SMA 50, delivery, 52-week distance | Code definitions for "fundamentally strong", "improving earnings", "strong relative strength" and "earnings surprise". FII increase from `shareholding_pattern`, not the sparse features column |
| 12 | Stock screener queries | SCREENING_AND_DISCOVERY | Partial | as row 11 | D/E, ROE, ROCE, `earnings_consistency_score` | As row 11. "Debt-free" = D/E of 0 from Trendlyne, with the as-of date shown |
| 13 | Risk analysis | RISK_AND_FORENSICS | Partial | Research lens `red_flags`; flags in the features: `earnings_decline_flag`, `debt_spike_flag`, Altman Z, Piotroski (2,077), pledge | — | "Top 10 risks ranked by potential impact" needs a stated ranking method. A ranking made up by the LLM is not allowed. Related-party questions are answerable only from annual-report text. Routing (section 3.2) |
| 14 | Red flag detection (forensic) | RISK_AND_FORENSICS | Data gap | The flags in row 13 | Cash flow empty; receivables and working capital never filled | Most of the 8 checks (profit vs cash, receivables growth, debt vs profit, working capital) are blocked until balance-sheet and cash-flow data is ingested. Today's honest answer is the checks that *can* run plus a list of the ones that cannot |
| 15 | Research thesis builder | THESIS_AND_RESEARCH | Missing | Pieces only (rows 1–14) | — | Composition; bull and bear always together; catalysts from `event_calendar`; invalidation conditions as checkable rules; a saved-thesis store; SEBI |
| 16 | Catalyst discovery | NEWS_AND_EVENTS | Partial | Visual `results_calendar`; `nidp.event_calendar` | Event calendar 28,187 rows for 2,479 companies, up to 5 Dec 2026; `macro_releases` PARTIAL *(31 Oct)* | Policy events. "What could cause a positive surprise?" is interpretation and must be labelled |
| 17 | Sector research | SECTOR_AND_MACRO | Partial | Visual `sector_rotation`; V3 sector composer; `sector_macro_scores` | Sector median P/E history is only about 10 months | Sector earnings growth = quarterly P&L aggregated by industry, which needs the industry map. "Cheapest relative to history" has a short history |
| 18 | Sector rotation | SECTOR_AND_MACRO | **Built** at sector level | Visual `sector_rotation`; `smart_money` sector heatmap | `analytics.sector_snapshot` frozen since 12 Oct *(31 Oct; PR #414)* | The market → sector → industry → company drill needs the industry map |
| 19 | Macro and market | SECTOR_AND_MACRO | Partial; Data gap for macro history | Visual `market_view`; `policy_analyst` (curated rules); market-wide FII/DII flows | FII/DII flows from Sep 2018 to 30 Oct 2026 (2,296 rows). **`fred_macro` empty** | An indicator-history store. "Why is Nifty moving?" needs constituent weight × return contributions; whether such a calculation exists is UNVERIFIED |
| 20 | Correlation and sensitivity | SECTOR_AND_MACRO | Data gap | — | No stored crude, INR or yield history; prices from Apr 2024 | Macro history, then a regression with sample size, R² and period shown. Never "impact" without the statistic |
| 21 | Historical research and patterns | HISTORICAL_VALIDATION | Missing | AI Trader DSL backtester (price rules, walk-forward, holdout) | Prices from 1 Apr 2024; features from 29 Dec 2025; shareholding averages about 5 quarters per company | Similarity search over features; an event-study engine |
| 22 | Hypothesis testing | HISTORICAL_VALIDATION | Missing | As row 21; earnings-surprise validation research branch | As row 21. "FII increase → outperformance" has about 5 to 10 quarterly observations per company | A factor and event study engine with the 8 required outputs, a benchmark, and a refusal below a minimum sample (FR-RC-10) |
| 23 | Research idea generation | SCREENING_AND_DISCOVERY | Partial | Visual `top_opportunities`; AI scanner "Top 10 ideas"; smart-money scanner; breakouts; thematic "which companies announced X" via `stocks_insights` | — | "Improving fundamentals before price momentum" is a composite screen. Wording: "ideas for further research" |
| 24 | Contradiction detection | THESIS_AND_RESEARCH | Missing | — | Transcripts are recent; financials are P&L only | Extract claims from transcripts and check them against the numbers. Show each as a check with the evidence for both sides |
| 25 | "What changed?" | WHAT_CHANGED command | Missing as one answer; every section's data exists | — | Financials and earnings (quarterly) ✓; valuation (from 29 Dec 2025) ✓; price ✓; technicals (from 29 Dec 2025) ✓; FII/DII and promoters (quarterly) ✓; news and events (NSE) ✓; management commentary partial (from May 2026) | A deterministic diff engine with an as-of date per section. A 365-day window exceeds the feature history until 29 Dec 2026, and the answer must say how much of the window it covers |
| 26 | Research report generation | REPORT command | Missing | No report or export code on dev | — | A report is a composition of blueprints, so it comes after them. Export format (Q5). Under SEBI a "research report" is the regulated artefact itself (section 7) |
| 27 | Monitoring and follow-up | THESIS_AND_RESEARCH | Missing | Watchlists (research watchlist; the PR #447 stack) | — | Saved-thesis store with assumptions; "changed since my last research" = WHAT_CHANGED against the saved snapshot; alerts |
| 28 | Prompt cards (UI) | — | Partial | `GET /api/copilot/suggested-prompts` (mode-aware), the DailyQuestionBar strip, `backend/data/nivesh_question_bank.json` | — | A research card set. Show a card only when its answer is built, so a card never leads to a dead end |

**Totals for categories 1–27 (27 in all):**
- Built: 2 (10, 18).
- Partial: 15 (1, 2, 4, 5, 6, 7, 8, 9, 11, 12, 13, 16, 17, 19, 23).
- Data gap: 3 (3, 14, 20). The cash-flow half of 2 is blocked too, but 2 is counted under Partial.
- Missing: 7 (15, 21, 22, 24, 25, 26, 27).

---

## 6. Data reality check (staging NIDP warehouse, 2 Nov 2026)

| Source | Coverage measured | What it unblocks | What it cannot answer |
|---|---|---|---|
| `nidp.prices_eod` | 6,295 symbols, 1 Apr 2024 to 30 Oct 2026 | Price, returns, trend, P/E recompute | Anything that needs more than about 2.6 years of daily history |
| `nidp.stock_features_daily` | 2,703 symbols, 29 Dec 2025 to 30 Oct 2026; 2,475 on the latest day. Trendlyne fundamentals for 2,122 (ROCE 2,121, D/E 2,057, P/B 2,058, P/E 1,669, Piotroski 2,077, delivery 2,475) | Screens; technical, valuation and quality snapshots | **EV/EBITDA, interest coverage, current ratio and CFO/PAT are null for all.** History about 10 months. `sector` set for 545 and `industry` for 521 |
| `nidp.nse_financials_quarterly` | 2,215 companies, 24,163 rows, to Sep-26 | Revenue, EBITDA, PAT and EPS trends; banks' NIM | **Balance-sheet columns empty** in every period since Sep 2025; no GNPA/NNPA |
| `nidp.nse_financials_cashflow` | **0 rows** | — | FCF, PAT vs OCF, cash conversion |
| `nidp.earnings_estimates` | **0 rows** | — | "Beat or miss expectations" |
| `nidp.shareholding_pattern` | 2,411 companies, 12,457 rows, Mar 2012 to Sep 2026 | Promoter, FII, DII and MF % trends; pledge | Transaction-level buying and selling |
| `nidp.mf_holdings_monthly` | 3,109 schemes, Sep 2025 to Sep 2026, 1,687,180 rows | Which funds entered or exited; smart-money scores | More than 13 months back |
| `nidp.insider_sast` | **0 rows** | — | Promoter and insider trades |
| `nidp.bulk_deals` | 229 symbols, 9 Oct to 30 Oct 2026 | Recent bulk deals | Any history |
| `nidp.fii_dii_flows` | Market-wide, Sep 2018 to 30 Oct 2026, 2,296 rows | Market flows | Per-stock flows |
| `nidp.fred_macro` | **0 rows** | — | Macro sensitivity and correlation |
| `nidp.delivery_data` | 4,214 symbols, 1 Apr 2024 to 30 Oct 2026 | Delivery trends | — |
| `nidp.event_calendar` | 2,479 companies, Jun 2024 to 5 Dec 2026, 28,187 rows | Catalysts, results dates | Policy events |
| `nidp.documents` | Announcement attachments 76,334; results 15,675; annual reports 7,130; press releases 5,052; presentations 3,507; **concall transcripts 3,401 (1,256 companies, from 19 May 2026)**; 2,284,948 chunks | Quoted, linked evidence for business, results and commentary | Multi-year commentary history |

**A trap for every historical feature:** shareholding and financials have a `period_end` and a `broadcast_at`. Any backtest or "what happened after" study must use the date the market *knew* the number (`broadcast_at`), not `period_end`. Otherwise the study uses data before it was public (look-ahead bias). FR-RC-10 makes this a test.

---

## 7. Compliance: SEBI wording

The owner's standing rule for the desk is "ideas, not picks": no "buy", "sell", "recommend", "pick", "target" or "best trade". The Copilot already deflects advice questions (`_P_STOCK_INSIGHTS` advice clause). Several questions in this bank ask for outputs that read as a research recommendation, or a research report, under the SEBI (Research Analysts) Regulations, 2014.

The 2024 amendments to those regulations also add duties for research analysts who use AI tools: responsibility for the output, and disclosure to clients. The exact obligations need confirming with counsel. This document is not legal advice.

Until the owner answers Q2 (section 11), the default is **evidence-only wording**:

| Question or output in the bank | Risk | Answer shape under the default |
|---|---|---|
| "Give me the investment/research case" | Reads as a recommendation | A research case: bull evidence and bear evidence side by side, open questions, and what would change the picture. No conclusion |
| "Is [Company] expensive or cheap?" | Valuation verdict | Percentile against its own history and against peers, with the method and period. No "cheap, so attractive" |
| "Give me a bullish interpretation" (alone) | One-sided view | The bullish reading is always shown with the bearish one (AC-RC-05) |
| "Is the stock bullish or bearish?" | Directional call | The trend state by stated rules ("above the 50 and 200 DMA; RSI 61") |
| "Is this event positive, negative or neutral?" | Event call | The classifier's label with its method, plus how the stock moved after similar past events (n, period) |
| "What happens if earnings grow 15/20/25%?" | Implied target price | Arithmetic under stated assumptions, labelled "scenario, not a forecast". No price target |
| "Research Conclusion" (report section 10) | Rating or target | "What the evidence shows, open questions, what would change the view" |
| "Prepare an investment thesis"; "Find hidden opportunities" | Recommendation | "Research thesis" with invalidation conditions; "ideas for further research" |

---

## 8. Requirements

### 8.1 Functional

- **FR-RC-01 Question bank as data.** Store the ~250 questions from the source as a routing fixture. Each one carries its expected group and command, and an entity placeholder. Run it against the live router in CI. Owner decision Q7 picks the file: extend `backend/data/nivesh_question_bank.json` or add a new file.
- **FR-RC-02 Routing.** Every question resolves to a group (section 3.2), entity, window, command and persona. Advice-shaped questions go to the existing deflection.
- **FR-RC-03 Clarify, never guess.** A question that needs an entity, when the thread has none, gets a clarifying question with stock autocomplete. No answer about a guessed company.
- **FR-RC-04 Query planner.** Known blueprints run a fixed plan of tool calls. Free-form composite questions run a bounded plan; the proposed bound is at most 6 tool calls. The plan appears in the evidence panel.
- **FR-RC-05 Grounded numbers.** Every number in an answer comes from a tool result with its source and as-of date. The LLM adds none. This is the existing visual-answer rule.
- **FR-RC-06 Explicit gaps.** When a needed source is empty, stale or too short for the asked window, the answer names what is missing (for example "Cash-flow statements are not in our data yet") and carries no estimate in its place.
- **FR-RC-07 Answer contract.** Extend `visual-answer-v1` with:
  - `line` (trends over quarters or years);
  - `table` (comparisons);
  - `timeline` (events and catalysts);
  - a per-answer `confidence` that means evidence coverage, never a probability of profit.

  Keep the block-type tolerance (unknown or bad blocks degrade safely).
- **FR-RC-08 What changed.** Nine sections in the source's order. Each section carries a status (changed, unchanged or no data), its as-of dates, and the part of the asked window it actually covers.
- **FR-RC-09 Thesis.**
  - Bull case, bear case, catalysts (from `event_calendar` and results dates), KPIs to monitor, and invalidation conditions written as checkable rules (for example "promoter pledge above 10%").
  - Bull and bear are always rendered together.
  - Saved per user; the store is decided in Phase 3.
- **FR-RC-10 Hypothesis test.**
  - **Inputs:** condition, universe, horizon, benchmark.
  - **Outputs:** sample size, period, win rate, mean, median, maximum drawdown, a confidence interval, the benchmark comparison, the definitions used, and the limitations.
  - **Rules:** facts are dated by `broadcast_at`; the answer refuses below a minimum sample (Q6); survivorship handling is stated.
- **FR-RC-11 Monitoring.** "Changed since my last research" compares against the saved thesis snapshot. "What to monitor this week" comes from the event calendar for saved companies.
- **FR-RC-12 Report.** Composed from built blueprints only, carries the compliance footer, and exports in the format chosen in Q5.
- **FR-RC-13 Prompt cards.** A research card set, shown only for answers that are built.
- **FR-RC-14 Compliance lint.** No buy, sell, hold, target price, recommend or pick in generated text (quoting the user's own words is exempt). Section 7 wording applies.

### 8.2 Non-functional

- **Freshness:** per the owner's no-stale-data rule. Price and technical facts are live or from the latest session, with as-of dates shown. Stale facts get the existing banner.
- **Latency:** the target is the owner's call. Proposal: at most 5 s p95 for single-company answers, and at most 15 s for composite answers, with blocks rendered as they arrive. Measure each blueprint before committing to numbers.
- **Cost:** every LLM call is metered through the AI usage engine (`payer_kind=user`).
- **Persona:** answers respect the mode the app sends (Investor, Trader or Advisor), following the 14 Oct rule. An advisor-workspace owner in Investor or Trader mode sees their own data.
- **Language:** the prompt catalogue has a Hindi file (`backend/routes/copilot_prompt_catalog_hi.json`). Whether the research cards need Hindi is an owner call.

---

## 9. Acceptance criteria (the QA contract)

- [ ] **AC-RC-01 Routing.** The full fixture (FR-RC-01) runs in CI. The share of questions routed to their expected group is at least the owner's threshold (proposal: 95%). 100% of advice-shaped questions reach the deflection or the evidence-only wording.
- [ ] **AC-RC-02 Grounding.** For each built blueprint, every number in the text appears in the facts block. On the fixture, the grounding check raises no false warnings.
- [ ] **AC-RC-03 Gap honesty.** While `nse_financials_cashflow` is empty, "Compare PAT versus operating cash flow for <company>" returns a notice naming the missing source and contains no cash-flow figure. Run this on staging data.
- [ ] **AC-RC-04 No consensus.** "Was this quarter better than expected?" says that analyst consensus is not available and names the comparison used instead.
- [ ] **AC-RC-05 Two-sided thesis.** The payload validator rejects a thesis that has a bull section without a bear section, or no invalidation conditions.
- [ ] **AC-RC-06 What changed.** The response has exactly 9 sections in order. Each section has a status of changed, unchanged or no data, plus an `as_of`. If the window is longer than the history, the covered part is stated.
- [ ] **AC-RC-07 Hypothesis.**
  - The output has all the FR-RC-10 fields.
  - Below the minimum sample, the answer is a refusal notice.
  - A fixture where `broadcast_at` is later than `period_end` proves the study uses `broadcast_at`.
- [ ] **AC-RC-08 Compliance lint.** Across a full fixture run, generated text has zero hits for buy, sell, hold, target price, recommend or pick.
- [ ] **AC-RC-09 Clarify.** A question with no entity and no thread symbol produces a clarifying question and no company-specific answer.
- [ ] **AC-RC-10 Rendering.** Playwright: each new block type (`line`, `table`, `timeline`) renders real fixture data and degrades safely on malformed data. Extend the hardcoded INTENTS list in `copilot-app-visual-answer.spec.ts`. That list once hid untested intents.
- [ ] **AC-RC-11 Staging walk.** Before a phase is reported done, each new blueprint is asked live on staging as a signed-in user. The real answer and its data check (Appendix A style) go into `test_reports/`.

---

## 10. Phasing and dependencies

| Phase | Contents | Categories it moves | Depends on |
|---|---|---|---|
| **0. Decisions** | Q1 to Q7 below | — | Owner |
| **1a. Measure** | The question-bank fixture plus a routing test against the current router; report which questions misroute or fall through | All (measurement only) | Q3 (group list) |
| **1b. Blueprints on existing data** | `company_overview` (filing quotes with links); `results_summary`; stock smart-money view; valuation snapshot (current, vs sector, 10-month range); peer `table` for the metrics that exist; catalysts `timeline`; **What changed v1** (8 of 9 sections fully, commentary where transcripts exist); `line`, `table` and `timeline` blocks | 1, 4, 6, 7, 8, 16, 25 | 1a; PRD v2 contract extension |
| **1c. Screens in chat** | The existing plan W4 to W7 (PR #447 stack), plus this bank's factor definitions | 11, 12, 23 | PR #447 merge |
| **1d. Research prompt cards** | Cards only for 1b and 1c answers | 28 | 1b, 1c |
| **2. Data** | Cash flow and balance sheet; P/E history recompute from `prices_eod` and EPS; insider/SAST feed; EV/EBITDA; industry map; transcript backfill; consensus (or an accepted "no consensus"); macro history | 2, 3, 5, 6, 7, 13, 14, 17, 18, 19, 20 | Q4 (sources, spend) |
| **3. Engines** | Query planner and composition (shared with PRD v2 §9); event and factor study engine; thesis store and monitoring; contradiction checks; report export | 9 (history), 15, 21, 22, 24, 26, 27 | PRD v2 composition decision; Q5, Q6; Phase 2 for 14 and 24 |

**Cheaper alternative:** do only 1a, 1c and What changed v1. This gives the bank as a test, screens in chat and the flagship command, all on today's data, without new block types beyond `line`. The trade-off is that peer tables and thesis wait.

---

## 11. Open decisions (NEEDS-INPUT from the owner)

| # | Decision | Why it blocks | Default if not answered |
|---|---|---|---|
| Q1 | Who is the "analyst"? Options: a retail user in Investor mode, a new Research mode in `/app`, or advisors | It sets the surface, the prompt cards and how much depth is shown | Answers inside Investor mode; no new mode |
| Q2 | Is the operating entity a SEBI-registered Research Analyst? | It decides whether "research conclusion", "investment case" and "report" may carry a view | Evidence-only wording (section 7) |
| Q3 | Intent groups: the 12 as pasted, or 13 + 3 commands (section 3.2)? | The routing fixture and the router are built on it | 13 + 3 |
| Q4 | Data sources and spend: (a) balance sheet and cash flow, from our own XBRL parsing (the columns exist but are empty) or Trendlyne; (b) consensus estimates, a paid vendor or accept "no consensus"; (c) transcript backfill before May 2026; (d) macro history source | Phase 2 cannot start without it | Phase 1 only; answers state the gaps |
| Q5 | Report output: an in-chat saved answer with a share link, or a PDF or Word export? | Category 26 design | Saved answer, no file export |
| Q6 | Hypothesis-test rules: minimum sample (proposal: 30 independent events), default universe (proposal: Nifty 500), benchmark (Nifty 50 or the sector index), horizons | FR-RC-10 refusal threshold | The proposals |
| Q7 | Where the question bank lives: extend `nivesh_question_bank.json` or a new fixture file? | FR-RC-01 | A new fixture file next to the existing bank, so existing consumers are not disturbed |

---

## 12. Risks

| Risk | Mitigation |
|---|---|
| Regulatory: answers read as research recommendations | Section 7 wording, AC-RC-08 lint, and the Q2 decision before any report or conclusion ships |
| Pressure to fill gaps: the model invents cash-flow or consensus numbers because the question expects them | FR-RC-05 and FR-RC-06, AC-RC-02 and AC-RC-03; fix the known grounding-check false warnings first so real warnings are not ignored |
| Look-ahead bias in historical studies | `broadcast_at` dating (AC-RC-07) |
| Small samples presented as findings (2.6 years of prices, about 5 quarters of shareholding per company) | Confidence intervals, sample size and limitations always shown; refusal below the minimum |
| Survivorship: whether `prices_eod` keeps delisted symbols is UNVERIFIED | Check before Phase 3; state it in the limitations either way |
| Persona collisions: in Trader mode, "Is the stock bullish?" can become a trade-plan answer | Persona-aware routing; fixture cases per persona |
| Three overlapping specs (PRD v2, Research Hub, this) | One contract, one renderer; this document defers to PRD v2 on the evidence framework |
| Cost: composite answers make several LLM calls | Metering through the AI usage engine; deterministic blueprints first |

---

## 13. Success measure and rollout

- **Measures (proposal, for the owner to confirm):**
  - share of fixture questions answered by a grounded blueprint, per phase;
  - routing accuracy on the fixture;
  - zero compliance-lint hits;
  - zero ungrounded numbers;
  - research questions asked per week. Whether chat logs record the resolved intent today is UNVERIFIED; instrument it if they do not.
- **Rollout:** each blueprint goes behind a feature flag, first for the owner's account (as with `portfolio_hedge`), then for everyone. **Rollback:** turn the flag off. **Trigger:** any compliance-lint hit or any ungrounded number seen on staging.

---

## Appendix A: evidence (read-only, staging NIDP warehouse, 2 Nov 2026)

These were aggregate counts only, through `~/.config/nivesh/nidp-psql.sh`. No rows were changed.

- `prices_eod`: min 2024-04-01, max 2026-10-30, 6,295 symbols.
- `stock_features_daily`: 2,703 symbols, 2025-12-29 to 2026-10-30, 479,789 rows. On 2026-10-30, `fundamentals_source='trendlyne_mcp'` covers 2,122 rows. Non-null counts that day:
  - ROCE 2,121; D/E 2,057; P/B 2,058; P/E 1,669; Piotroski 2,077; `deliv_pct_avg_20` 2,475;
  - `fii_pct_change_qoq` 546; `sector` 545; `industry` 521 (of 2,475);
  - `ev_ebitda`, `cfo_pat_ratio`, `interest_coverage` and `current_ratio` 0.
- `nse_financials_quarterly`: 2,215 symbols, 2002-03-31 to 2026-09-30, 24,163 rows.
  - Quarters per symbol: 20+ = 363; 12–19 = 370; 8–11 = 1,218; fewer than 8 = 264.
  - For every period from 2025-09-30 to 2026-09-30, `total_equity_cr`, `long_term_debt_cr`, `current_assets_cr` and `trade_receivables_cr` are non-null in 0 rows.
  - The 2026-09-30 period has 797 rows.
- Empty tables: `nse_financials_cashflow`, `earnings_estimates`, `insider_sast` and `fred_macro` each have 0 rows.
- `shareholding_pattern`: 2,411 symbols, 2012-03-31 to 2026-09-30, 12,457 rows.
- `mf_holdings_monthly`: 3,109 schemes, 2025-09-01 to 2026-09-01, 1,687,180 rows.
- `bulk_deals`: 229 symbols, 2026-10-09 to 2026-10-30, 1,600 rows.
- `fii_dii_flows`: 2018-09-01 to 2026-10-30, 2,296 rows.
- `event_calendar`: 2,479 symbols, 2024-06-01 to 2026-12-05, 28,187 rows.
- `delivery_data`: 4,214 symbols, 2024-04-01 to 2026-10-30.
- `documents` by `doc_type` (docs / symbols / first and last filing):
  - `announcement_attachment`: 76,334 / 2,448 / 2026-04-17 to 2026-11-01;
  - `financial_results`: 15,675 / 2,406 / from 2026-05-19;
  - `annual_report`: 7,130 / 2,213;
  - `press_release`: 5,052 / 1,322;
  - `investor_presentation`: 3,507 / 1,293;
  - `concall_transcript`: 3,401 / 1,256 / 2026-05-19 to 2026-11-01.
- `document_chunks`: 2,284,948 rows.
- Transcript documents per symbol: 1 = 265, 2 = 450, 3 = 186, 4 = 221, 5 = 75, 6 = 39, 7 or more = 21.

**Code facts (origin/dev 33d266fd):**
- `copilot_visual/intents.py` `INTENTS`: `market_view`, `smart_money`, `top_opportunities`, `breakouts`, `unusual_volume`, `stock_decision`, `expected_move`, `open_trades`, `fno_setups`, `trade_validity`, `exit_options`, `position_size`, `daily_review`, `sector_rotation`, `results_calendar`, `event_intelligence`, `portfolio_hedge`.
- `payload.py` block types: `kpis`, `candles`, `bars`, `heatmap`, `quadrant`, `ranked`, `trade_plan`, `list`, `briefs`, `notice`.
- `git grep` on `backend/routes` and `backend/services` for `research_report|generate_report|pdf_report` finds nothing.
