# NIVESH.AI — Complete Functional & Business Document
**As of May 2026 · Confidential**

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Business Context & Problem Statement](#2-business-context--problem-statement)
3. [Product Vision & Strategy](#3-product-vision--strategy)
4. [Target User Personas](#4-target-user-personas)
5. [Onboarding Strategy](#5-onboarding-strategy)
6. [Core Functional Capabilities](#6-core-functional-capabilities)
   - 6.1 Portfolio Import — CAS Parsing
   - 6.2 V3 Scoring Engine (38 Primitives)
   - 6.3 Action Planning Engine
   - 6.4 Portfolio Intelligence & Insights
   - 6.5 AI Copilot (Narrative Layer)
   - 6.6 Market Intelligence & Positional Trading
   - 6.7 Goals-Based Planning
   - 6.8 Tax Engine
   - 6.9 Broker Integration (Secure Portfolio Connect)
   - 6.10 MFD Advisor Workspace
   - 6.11 NIDP Data Warehouse
   - 6.12 OpenAlgo Trading Platform
7. [Technical Architecture](#7-technical-architecture)
8. [Data Model](#8-data-model)
9. [Nightly Data Pipeline](#9-nightly-data-pipeline)
10. [Security & Compliance](#10-security--compliance)
11. [Admin Console](#11-admin-console)
12. [API Surface](#12-api-surface)
13. [Current Build Status (May 2026)](#13-current-build-status-may-2026)
14. [Known Gaps & Roadmap](#14-known-gaps--roadmap)

---

## 1. Executive Summary

**Nivesh.ai** is an agentic wealth management system for the Indian retail investor and the MFD/IFA wealth advisor who serves them. It ingests a Consolidated Account Statement (CAS), parses every holding down to ISIN and folio, scores each instrument across 38 deterministic primitives, layers a real-time macro intelligence overlay, and emits an explainable, tax-aware action plan that an investor or advisor can execute with full transparency on the math.

**The core guarantee**: zero hallucinated numbers in the analytics path. Every recommendation traces back to a concrete primitive and a deterministic rule. The LLM exists only to narrate decisions that have already been made by code.

**What it covers today** (May 2026):

| Capability | Status |
|---|---|
| CAS PDF parsing (3 provider fallback chain) | Live |
| 38-primitive V3 scoring across 5 composites | Live |
| 6-rule action plan engine with 4 guardrails | Live |
| Deterministic portfolio insights | Live |
| AI Copilot (LLM narrative, grounded on plan) | Live |
| Market Dashboard (live Nifty + VIX + 12 sectors) | Live |
| BTST/Positional Trading engine | Live |
| Trade Journal (staged entries + exit ladder + P&L) | Live |
| NIDP Data Warehouse (NSE/AMFI/BSE/RBI history) | Live (Phase 1) |
| Corporate Announcements pipeline (S4) | Live |
| Document Intelligence + pgvector corpus (S5 Week 1) | Live |
| Goals-Based Planning | Live |
| Tax Engine (FIFO + LTCG harvesting) | Live |
| MFD Multi-client Advisor Workspace | Live |
| Broker Integration — OpenAlgo SPC (read-only) | Live |
| DPDP Act 2023 compliance scaffolding | Scaffolded |
| Mobile (Capacitor iOS/Android) | Scaffolded |

---

## 2. Business Context & Problem Statement

### 2.1 The Market Opportunity

Indian households hold approximately ₹68 lakh crore in mutual funds and ₹350+ lakh crore in direct equities. Despite this scale, 94% of retail investors cannot answer three basic questions about their portfolio: *What do I own? Is it any good? What should I do about it?*

### 2.2 The Retail Investor's Problem

A typical Indian retail investor has 8–25 mutual fund holdings accumulated across 5–15 years. Their pain points:

- **Fragmentation** — folios scattered across NSDL/CDSL CAS, broker apps, AMC portals, paper statements
- **No independent scoring** — fund ratings on Groww/MoneyControl are vendor-driven; Morningstar star ratings carry documented selection bias
- **Hidden duplicates** — Regular and Direct variants of the same scheme, three large-cap funds holding the same 20 stocks, one AMC owning 60% of the book — undetected
- **Switch math is hard** — "Is the better fund worth the LTCG tax + exit load + alpha gap?" requires computation nobody provides
- **No macro connection** — VIX at 22 and Nifty below 20-DMA should change today's allocation; investors don't know it
- **No single actionable list** — only a do-this-not-that ranking for *their specific portfolio*

### 2.3 The MFD Advisor's Problem

A typical AMFI-registered MFD serves 200–2000 clients. Their bottlenecks:

- **Attention scales linearly with client count** — the client book outgrows available time; "important" drowns in "loud"
- **No cross-book drift detection** — which clients are 5pp behind Nifty, with how much AUM, and why
- **No rebalance trigger** — when does performance drift cross the threshold worth a phone call?
- **Manual plan generation** — Direct-vs-Regular comparisons, switch costs, tax impacts, peer fund alpha per fund per client is impossible without software
- **Compliance pressure** — SEBI Investment Advisor regulations demand explainable, documented reasoning; vibe-based recommendations no longer work

### 2.4 The Active Trader's Problem

A self-directed trader running 5–30 day positional trades has:

- **Twelve signal sources** — Chartink scans, broker scanners, Telegram, Yahoo, NSE bhavcopy — no consolidated ranking
- **No regime overlay** — RSI 65 in a low-vol bull market is different from RSI 65 in a high-VIX risk-off environment
- **No execution discipline** — entry / SL / target / position size needs to be computed before the trade, not retrofitted after

### 2.5 Competitive Landscape

| Category | Examples | Gap |
|---|---|---|
| Robo-advisors | Scripbox, Coin | No CAS import, no per-holding decision, no MFD layer |
| Aggregators | INDmoney, Vested | Pretty dashboards, no scoring, no decisions |
| Screeners | TickerTape, Screener.in | Stock fundamentals only, no portfolio context |
| Trading platforms | Zerodha, Angel | Order execution, no advisory, no scoring |
| LLM chatbots | ChatGPT with portfolio | Hallucinates numbers, no real-time data, no CAS reader |
| MFD CRMs | Wealthy, Smallcase Manager | Workflow management, shallow per-client analytics |

**Nivesh's gap**: deterministic advisory engine that reads the CAS, knows the Indian tax code, integrates with the Indian market (NSE / AMFI / SEBI / RBI), explains its reasoning, and serves both retail self-direction and MFD-scale advisory.

---

## 3. Product Vision & Strategy

### 3.1 Vision

**One explainable, tax-aware, macro-aware action plan per portfolio — generated in under 60 seconds, with every number traceable back to its source.**

### 3.2 Core Design Principles

1. **Zero hallucinated analytics** — LLM never touches numbers. All scores are deterministic Python functions over real market data.
2. **Explainability as a feature** — every action cites exact primitives (drawdown 22%, turnover 85%, expense ratio 1.8%). Users can verify every number.
3. **Tax awareness** — every exit/switch recommendation shows FIFO cost basis, LTCG/STCG liability, exit load, and net benefit. "Worth switching?" is computed, not guessed.
4. **Portfolio-aware, not fund-aware** — exit/add/switch scores consider actual holdings, overlap with the rest of the portfolio, and AMC/category concentration. A great fund can still get a low Add score if it duplicates what you already own.
5. **Rule-based action engine, tunable** — six priority-ordered rules and four guardrails. Every threshold is live-tunable by admin without code deployment.
6. **Separation of analytics and narrative** — all analytics are deterministic; the LLM exists only to convert structured outputs into plain English that users can share and act on.

### 3.3 Revenue Model (current thinking)

| Tier | Offer | Model |
|---|---|---|
| **Free** | Dashboard + insights preview (limited actions) | Acquisition |
| **Retail Pro** | Full action plan + copilot + tax calculator | ₹799–₹1499/year |
| **MFD Workspace** | Multi-client advisory engine + white-label reports | ₹5,000–₹25,000/month per distributor |
| **Data API** | NIDP data-as-a-service for institutional buyers | Usage-based |

---

## 4. Target User Personas

### 4.1 Self-Directed Retail Investor (Primary)

- **Age**: 28–55
- **Corpus**: ₹5L–₹5Cr in mutual funds, 0–30 direct stocks
- **Behaviour**: Uses Groww/Zerodha for execution; trusts WhatsApp groups and YouTube channels for "advice"; checks portfolio 4–6 times a year
- **Trigger to use Nivesh**: received CAS, worried about underperformance, or a friend recommended it
- **Core need**: "Tell me what to actually do with my portfolio, in plain Hindi or English, without me having to become a finance expert"

### 4.2 AMFI-Registered MFD Advisor (Primary)

- **Client book**: 200–2000 households
- **Tools today**: Excel, BSE StarMF, AMC portals, WhatsApp
- **Revenue pressure**: SEBI has tightened expense-ratio rules; advisory fee pressure is growing
- **Core need**: "Give me a weekly 'which clients need attention' list, generate explainable plans I can put in front of regulators, and do it in one tool"

### 4.3 MFD's Client (Impersonated User)

- Doesn't sign in independently; onboarded via a 24-hour Gmail-connect URL shared by their advisor
- Sees a clean Portfolio + Insights + Plan via the MFD's client-360 interface
- Privacy concern: wants to know the advisor can only see investment data, not bank details

### 4.4 Active Positional Trader (Secondary)

- Runs a ₹2L–₹20L positional book alongside a long-term mutual fund portfolio
- Wants a daily "deploy verdict" (go/cautious/defensive), a ranked scan list, and a trade journal with P&L tracking
- Currently the heaviest user of the Market Dashboard and positional scanning features

---

## 5. Onboarding Strategy

### 5.1 Core Principle: Value Before Signup

The ordering is: **Import → Parse → Show Insights → Then ask for account creation.** The portfolio dashboard is never gated behind auth. PAN, KYC, and the full risk questionnaire all wait until after the user experiences their first "wow moment" (seeing their portfolio scored in under 60 seconds).

### 5.2 The 3-Step Golden Flow

```
Step 1 → Import (CAS PDF drag / Gmail connect / broker OAuth)
Step 2 → AI Analysis (10–15s parse + score)
Step 3 → Insights + optional signup
```

North-star metrics: time-to-first-insight < 60s · steps to insight ≤ 3 · drop before insight < 15%.

### 5.3 Landing Page CTA

**One CTA only**: "Import Your Portfolio" — not "Sign Up", not "Get Started". Hero copy: "See all your investments in one place." Google Sign-In is not the hero CTA; it lives in the top right corner.

### 5.4 Progressive Profiling

Not a onboarding form. Data is collected lazily across sessions:
- Session 1: mobile/email
- Session 2: age + goals
- Session 3: income bracket
- Session 4: risk profile questionnaire
- Session 5: family/dependants

### 5.5 Trust Builders (Non-Negotiable)

Every import screen shows: "Read-only · AES-256 encrypted · No trading · No bank access · Delete anytime." These are especially critical for the HNI segment.

### 5.6 Import Source Priority

- **P1**: Broker OAuth (Zerodha, Angel One, Upstox), CAS PDF, Excel upload, NSDL/CDSL
- **P2**: Gmail parsing (auto-pull latest CAS email)
- **P3**: WhatsApp forward
- Manual entry is hidden, not promoted — it is the escape hatch, not the primary path

### 5.7 Smart Error Recovery

Never display "Upload failed." Always: "We found 92% of your portfolio. Help us verify 2 entries." This framing reduces abandonment dramatically.

---

## 6. Core Functional Capabilities

### 6.1 Portfolio Import — CAS Parsing

**What is a CAS?** A Consolidated Account Statement is a monthly PDF delivered by NSDL and CDSL to every investor with a demat account or mutual fund folio. It contains every folio, ISIN, transaction, and unit balance.

**Three-provider fallback chain** (as of April 2026):

| Priority | Provider | Mechanism |
|---|---|---|
| 1 (default) | Nivesh Parser | Google Document AI (Document AI v3) — parallel 3-worker chunked processing, ≤12 pages/chunk |
| 2 (fallback) | Claude Vision | Anthropic Claude Sonnet — page-by-page base64 PNG extraction, 6 pages/batch, max 24 pages |
| 3 (final fallback) | casparser.in API | External REST API; supports NSDL/CDSL/CAMS/KFintech format variants |

**Auto-fallback logic**: tries selected primary provider first; if result is empty or throws, tries remaining providers in order. First non-empty result wins. `BudgetExceededError` (Claude token budget) is caught and treated as fallback-eligible, not fatal.

**What gets extracted**:
- Investor name, PAN, email
- All mutual fund folios (scheme name, AMFI code, plan, ISIN, units, NAV, value)
- All equity holdings (ISIN, symbol, quantity, value, pledge status)
- All transactions (buy/sell/SIP/switch/IDCW, dates, amounts, NAV)
- SGBs, ETFs, bonds, preference shares
- Statement date + period

**Post-parse processing**:
1. Holdings deduplication — Regular + Direct variants of the same scheme collapsed, same-fund multi-folio merged
2. Cost basis reconstruction — FIFO matching from transaction history when invested amount not in CAS
3. Buy-date inference — earliest transaction date per folio used as holding_start_date
4. SIP detection — recurring transactions at consistent intervals tagged as SIPs
5. Portfolio snapshot — each upload frozen as a time-machine snapshot

**Validation stats** (real PDF test, April 2026):
- Nivesh Parser on 18-page NSDL CAS: 97.1% portfolio-value match, 110 holdings, 32 SIP transactions
- Claude Vision on 4-page CAMS CAS: 100% holdings match, 19 holdings in < 8 seconds

---

### 6.2 V3 Scoring Engine (38 Primitives)

**The core analytics engine.** Every mutual fund in the system is scored against 38 primitive signals organized into five composite scores. All computation is deterministic Python; no LLM involvement.

#### 6.2.1 The 38 Primitives

**Category 1 — Returns & Risk-Adjusted (Primitives 1–13)**

| # | Primitive | Source | Description |
|---|---|---|---|
| 1 | `ret_1y` | Groww scrape / NAV history | 1-year absolute return (%) |
| 2 | `ret_3y` | Groww scrape / NAV history | 3-year CAGR (%) |
| 3 | `ret_5y` | Groww scrape / NAV history | 5-year CAGR (%) |
| 4 | `category_avg_1y` | Derived from peer set | Average 1y return for SEBI category |
| 5 | `category_avg_3y` | Derived | Average 3y CAGR for category |
| 6 | `rank_within_category` | Derived | Percentile rank of fund in its category (0–100) |
| 7 | `sharpe_ratio` | Groww scrape | Risk-adjusted return (rolling 3y) |
| 8 | `sortino_ratio` | Groww scrape | Downside-adjusted return |
| 9 | `alpha` | Groww scrape | Excess return vs benchmark |
| 10 | `beta` | Groww scrape | Market sensitivity |
| 11 | `std_dev` | Groww scrape | Annualised standard deviation |
| 12 | `information_ratio` | Derived | Alpha / tracking error |
| 13 | `treynor_ratio` | Derived | (Return − Rf) / beta |

**Category 2 — Cost (Primitives 14–16)**

| # | Primitive | Source |
|---|---|---|
| 14 | `expense_ratio_direct` | Groww scrape |
| 15 | `expense_ratio_regular` | Groww scrape |
| 16 | `expense_trend_delta` | Derived (vs 3y ago from history) |

**Category 3 — Activity & Concentration (Primitives 17–18)**

| # | Primitive | Source |
|---|---|---|
| 17 | `turnover_ratio` | Groww scrape |
| 18 | `top10_concentration_pct` | Groww scrape (top-10 holdings) |

**Category 4 — Fund Health (Primitives 19–21)**

| # | Primitive | Source |
|---|---|---|
| 19 | `manager_tenure_years` | Groww scrape |
| 20 | `aum_cr` | Groww scrape |
| 21 | `fund_age_years` | AMFI scheme master |

**Category 5 — NAV-Derived Analytics (Primitives 22–25)** — computed by `nav_analytics.py` nightly

| # | Primitive | Algorithm |
|---|---|---|
| 22 | `max_drawdown_pct` | Maximum peak-to-trough decline in NAV history |
| 23 | `consistency_score` | % of rolling 12-month windows where fund beat its category average return |
| 24 | `downside_capture_pct` | Fund monthly return / benchmark proxy monthly return, in months where benchmark fell |
| 25 | `aum_trend_score` | OLS slope of ln(AUM) over trailing 24 months (positive = growing, negative = outflows) |

**Category 6 — Portfolio-Level Context (Primitives 26–38)** — computed per-user, per-portfolio

| # | Primitive | Description |
|---|---|---|
| 26 | `overlap_pct` | % of underlying stock holdings that overlap with at least one other fund in portfolio |
| 27 | `avg_overlap_pct_with_portfolio` | Average pairwise stock overlap with all other funds the user holds |
| 28 | `sector_exposure` | Sector breakdown (Technology / Finance / Healthcare / etc.) |
| 29 | `tax_liability_rs` | Estimated LTCG/STCG tax on full redemption (FIFO basis) |
| 30 | `tax_benefit_rs` | Tax saved by switching to Direct vs remaining in Regular |
| 31 | `holding_age_months` | Months since first purchase |
| 32 | `portfolio_fit_score` | How well the fund fits the user's overall portfolio (diversification benefit) |
| 33 | `gap_fit` | Whether this fund fills a genuine allocation gap (debt, small-cap, international) |
| 34 | `amc_concentration_pct` | % of user's AUM managed by this fund's AMC |
| 35 | `category_concentration_pct` | % of user's MF AUM in the same SEBI category as this fund |
| 36 | `asset_alloc_fit` | Whether adding/holding this fund moves asset allocation closer to risk-profile target |
| 37 | `confidence_score` | Overall data completeness confidence (0–100; < 50 triggers low-confidence flag) |
| 38 | `buy_date` | User-specific: date of first investment |

#### 6.2.2 Five Composite Scores

**Weight redistribution principle**: if a primitive is missing (e.g., no 5-year return for a new fund), its weight is redistributed proportionally to available primitives in the same composite. Scores are never penalized for missing data — they adapt.

| Score | Purpose | Key Inputs | Default Weights |
|---|---|---|---|
| **Quality** (0–100) | Is this a good fund? | ret_1y/3y/5y, sharpe, sortino, consistency, drawdown, expense_ratio | Perf 25% · Risk-Adj 20% · Consistency 20% · Drawdown 15% · Cost 10% · AUM/Age 10% |
| **Health** (0–100) | Is it stable? | manager_tenure, aum_trend, turnover, top10_concentration, downside_capture, expense_trend | Manager 25% · AUM-Stability 20% · Turnover 15% · Concentration 15% · Downside 15% · Expense-Trend 10% |
| **Exit** (0–100) | Should I exit? | overlap, tax_liability, quality_inverse, expense_ratio, portfolio_fit | Overlap 25% · Tax 25% · Quality-inverse 25% · Cost 15% · Portfolio-Fit 10% |
| **Add** (0–100) | Should I add? | gap_fit, low_overlap, quality, allocation_need, expense | Gap-Fit 30% · Low-Overlap 25% · Quality 20% · Need 15% · Cost 10% |
| **Portfolio-Fit** (0–100) | Does it fit? | diversification, overlap, amc_concentration, expense, asset_alloc_fit | Diversification 25% · Overlap 25% · AMC 20% · Cost 15% · Asset-Alloc 15% |

**Switch Score** (non-composite, threshold-based):

```
switch_score = (Quality_candidate − Quality_current)
             + overlap_reduction_pts
             + (annual_cost_saving / ₹10,000)
             − (tax_cost / ₹10,000)

Recommend switch = TRUE iff switch_score ≥ 2.0
```

#### 6.2.3 Danger Classification

Each composite score is classified into a danger level:

| Band | Quality/Health | Exit | Interpretation |
|---|---|---|---|
| CRITICAL | < 40 | > 75 | Needs immediate attention |
| WARNING | 40–65 | 55–75 | Monitor, consider action |
| OK | > 65 | < 55 | No action needed |

#### 6.2.4 Score Storage & Caching

- **Primary store**: PostgreSQL `mutual_fund_metadata` table (quality_score, health_score, v3_scored_at columns)
- **Cache**: Redis key `v3:score:{instrument_id}` → full JSON, 24h TTL
- **Fallback**: if Redis down, PG columns used directly
- **Nightly refresh**: V3 scores recomputed after AMFI NAV update and analytics sweep

---

### 6.3 Action Planning Engine

The action plan is a **prioritized, guardrail-constrained list of concrete actions** that an investor should take on their portfolio. It is generated by running six rules in sequence across the entire portfolio.

#### 6.3.1 Six Priority-Ordered Rules

**Rule 1 — Regular → Direct Consolidation**

- **Trigger**: User holds Regular and Direct plans of the same AMC/scheme
- **Action**: EXIT Regular, SWITCH to Direct
- **Guardrail**: Savings must exceed tax cost within 24 months
- **Why it's Rule 1**: Always a win; tax cost is small, expense-ratio saving is permanent

**Rule 2 — AMC Concentration**

- **Trigger**: Any single AMC controls > 15% of portfolio AUM (configurable via admin)
- **Action**: EXIT the highest exit_score fund within that AMC until concentration < threshold
- **Guardrail**: Skip funds with Quality ≥ 75 AND Health ≥ 70 (unless pairwise overlap > 80%)

**Rule 2b — Category Concentration**

- **Trigger**: Any single SEBI MF category > 35% of MF portfolio (configurable)
- **Action**: Same exit-and-replace logic, scoped by category
- **Guardrail**: Same as Rule 2

**Rule 3 — Underperformer Replacement**

- **Trigger**: Quality ≥ 6.5 concern AND ret_1y < 8% AND ret_3y < 10% (configurable thresholds)
- **Action**: EXIT underperformer + ADD a higher-Quality fund in the same SEBI category
- **Guardrail**: A qualifying add_score candidate must exist in the same category

**Rule 4 — Fund Overlap Exit**

- **Trigger**: Two distinct funds (not sibling Regular/Direct) share > 60% stock-level overlap
- **Action**: EXIT the fund with the higher exit_score (keep the better-quality one)
- **Guardrail**: Only when proxy switch_score > 0 (the exit produces net value)

**Rule 5 — Debt Allocation Gap**

- **Trigger**: Debt allocation < risk-profile floor (Low-risk floor: 30%, Moderate: 20%, High-risk: 10%)
- **Action**: ADD a debt fund for the gap amount
- **Guardrail**: Skip AMCs that are already over-concentrated

**Rule 6 — Cost-Leak Switch**

- **Trigger**: Annual cost leak from Regular plan > ₹10,000 (configurable) AND switch_score ≥ 1.0
- **Action**: SWITCH with exact ₹ saving + estimated tax drag shown
- **Guardrail**: Guardrail 2 (tax-exceeds-benefit check)

#### 6.3.2 Four Guardrails

Guardrails block or flag individual actions after rules generate them:

| Guardrail | Condition | Effect |
|---|---|---|
| **High-Quality Protection** | Quality ≥ 75 AND Health ≥ 70 | Block EXIT unless overlap > 80% (overlap override) |
| **Tax-Exceeds-Benefit** | tax_liability > annual_benefit × 2 | Block EXIT; show "tax too high" reason |
| **Recent-Investment Lockout** | holding_age < 6 months | Block EXIT; show "too soon to exit" |
| **Low-Confidence** | confidence_score < 50 | Reduce action count to 2 max; flag "data incomplete" |

#### 6.3.3 Plan Actions

Each action in the plan carries:
- `action_type`: EXIT / ADD / SWITCH / HOLD / REVIEW
- `fund_name`, `isin`, `scheme_code`
- `reason_code` + `reason_text` (deterministic, rule-cited)
- `exit_score`, `add_score`, `switch_score`, `quality_score`, `health_score`
- `estimated_tax_impact_rs`
- `estimated_annual_saving_rs`
- `confidence_score`
- `status`: pending / done / skipped
- Thumbs-up / thumbs-down feedback

#### 6.3.4 Plan Lifecycle

```
Generate Preview → User Reviews → Save & Activate → Mark Actions Done/Skipped → Feedback
```

Plans are versioned. Old plans are archived, not deleted. Re-uploading a new CAS triggers a new plan generation.

---

### 6.4 Portfolio Intelligence & Insights

**Deterministic insights** — not LLM, not rules inference. These are explicit Python checks run after portfolio scoring.

#### 6.4.1 Insight Categories

| Category | What It Detects | Example Output |
|---|---|---|
| **AMC Concentration** | Single AMC > 30% of book | "HDFC AMC holds 42% of your portfolio. Consider diversifying." |
| **Category Concentration** | Single SEBI category > 35% | "Large-cap funds = 68% of your MF book. High concentration." |
| **Fund Overlap** | Pairwise stock-level overlap > 50% | "HDFC Top 100 and Axis Bluechip share 73% of their top holdings." |
| **Regular→Direct Cost Leak** | Annual savings > ₹5,000 available | "Switching to Direct plans saves ~₹18,000/year." |
| **Expense Ratio Outlier** | Fund expense ratio > 1.5× category median | "UTI Flexi Cap charges 1.89% vs 0.82% category median." |
| **Allocation Gap** | Debt < risk-profile floor | "Your debt allocation is 4% vs 20% recommended for Moderate risk." |
| **Stale Fund** | No NAV update > 30 days | "Nippon India Liquid: data 45 days old. Verify status." |
| **Underperformer Alert** | ret_3y < category avg by > 3pp | "ICICI Pru Bluechip underperforms large-cap category by 4.2pp over 3 years." |
| **High Drawdown** | max_drawdown > 35% | "Quant Small Cap: max drawdown 42%. High volatility fund." |
| **Turnover Alert** | turnover_ratio > 100% | "Mirae ELSS turnover: 127%. Elevated churn may compress returns." |

#### 6.4.2 Portfolio Intelligence Tab

Beyond per-fund insights, a portfolio-wide intelligence view:

- **Overlap Heatmap** — n×n matrix of all mutual fund pairs, cell = % stock overlap; drag-to-resize panels
- **AMC Exposure Chart** — donut showing % AUM per AMC
- **Category Allocation** — SEBI category breakdown vs risk-profile target
- **Sector Exposure** — sector drill-down across all equity holdings (direct + MF underlying)
- **Redundancy Score** — compression score (how much the portfolio could be simplified without losing diversification)

---

### 6.5 AI Copilot (Narrative Layer)

The copilot is a conversational AI layer grounded entirely on the user's active action plan and portfolio data. The LLM (GPT-4o-mini via Emergent LLM key) never performs calculations — all numbers are pre-computed deterministically and injected as context.

#### 6.5.1 What the Copilot Does

- **Explains plan actions** — "Why should I exit Axis Bluechip?" → retrieves exit_score breakdown, cites overlap, expense ratio, trailing return vs category
- **Answers portfolio questions** — "How much LTCG would I owe if I exit all Regular plans?" → deterministic calc, narrated
- **What-if scenarios** — "What happens to my score if I remove HDFC Small Cap?" → `scenarios.simulate` API → delta shown
- **Goal progress** — "Am I on track for my 2030 retirement goal?" → goal projection model narrated
- **Market context** — "What does today's Nifty movement mean for my portfolio?" → regime state + sector RS narrated

#### 6.5.2 Grounding Architecture

```
User query
  → Intent classifier (LLM)
  → Context retriever:
      - portfolio_context (holdings, scores, insights)
      - plan_context (active actions + status)
      - goal_context (if applicable)
      - faq_context (product FAQs via RAG)
  → Chart spec generator (if query implies data viz)
  → LLM completion (narrative only)
  → Response with embedded chart JSON (rendered by frontend)
```

#### 6.5.3 Safety Constraints

- LLM is never passed raw financial primitives without instruction to not recalculate
- All monetary amounts in context are strings (e.g., "₹1,23,456") to prevent LLM arithmetic
- Prompt includes explicit guardrail: "Do not perform calculations. Use only the numbers provided."
- `llm_safety.py` screens outgoing prompts for PAN/account patterns

---

### 6.6 Market Intelligence & Positional Trading

#### 6.6.1 Market Dashboard (Live)

**Deploy Verdict Strip** — the gating layer. Answers "Is today a green-light day?"

```
AGGRESSIVE: breadth ≥ 65% above 20EMA + ≥ 2 hot sectors + Nifty uptrend + VIX < 15
NORMAL:     breadth 50–65% + Nifty trend neutral + VIX 15–20
CAUTIOUS:   Nifty below 20-DMA OR breadth < 50% OR VIX 20–25
DEFENSIVE:  Macro risk HIGH OR VIX > 25 OR Nifty in confirmed downtrend
```

Live data (yfinance, ~1-min lag): Nifty 50 (^NSEI), VIX (^INDIAVIX), 12 sectoral indices (Bank, IT, Auto, FMCG, Pharma, Metal, Energy, Infra, Media, PSU Bank, Realty, Finance).

Cache TTL: 30s during market hours (9:15–15:30 IST Mon-Fri), 5 min after-hours.

**Dashboard Sections**:
1. **Deploy Verdict Strip** — hero card with 4-bucket verdict + 5 number tiles + sector dot strip
2. **Macro Bar** — US yields, crude, INR/USD, FII/DII flows, India VIX
3. **Today's Strategy Card** — regime-aware trade posture + live tape overlay
4. **Sector Heatmap** — 12 sectors with RS vs Nifty (HOT/WARM/COOL/COLD) + live overlay
5. **Aligned Picks** — scan results aligned with current regime verdict
6. **What Changed** — significant overnight developments (announcements, corporate events)
7. **Monday Game Plan** — weekend analysis (available Monday morning only)
8. **Positional Top Picks** — top signals from all configured ChartInk scans
9. **Trade Journal** — see below

#### 6.6.2 Positional Scanning

**ChartInk Integration**: Nivesh consumes webhook alerts from ChartInk scanners. Four default BTST scan formulas are seeded:

| Scan | Signal Type | Key Conditions |
|---|---|---|
| `btst.early_accumulation` | Volume contraction + range compression | close > SMA50 > SMA200 · 15d range ≤ 8% · vol ≤ SMA20 · RSI 50–65 |
| `btst.breakout_confirmation` | Confirmed breakout | close > 20d high · vol ≥ 1.5× SMA20 · close > SMA50 |
| `btst.sector_leaders_rs` | Relative strength | close > SMA50 · 1mo ret > 5% · 3mo ret > 10% |
| `btst.exit_warning_distribution` | Distribution / breakdown | close < SMA20 · vol ≥ 1.5× SMA20 · 5d high − close ≥ 5% |

Scan hits are stored in MongoDB `chartink_scan_hits`, enriched with live LTP (90-second in-memory cache), and ranked by regime alignment.

**NSE Bhavcopy** — daily OHLCV for the Nifty 500 universe ingested via NIDP pipeline.

**Technical Indicators** (computed by `feature_calculator.py`):
- RSI (14-period), MACD (12/26/9), Bollinger Bands (20-period)
- SMA 20/50/200, EMA 5/10/20
- Volume vs SMA20 ratio
- 52-week high/low proximity

#### 6.6.3 Trade Journal

Full execution management for positional trades:

**Staged Entry Framework** (per the user's trading framework):

| Stage | Allocation | Trigger |
|---|---|---|
| PILOT | 20% | Initial confirmation signal |
| CONFIRM | 30% | First extension above breakout level |
| SUSTAIN | 30% | Sector strength + price holding above entry |
| MOMENTUM | 20% | Strong follow-through, target in sight |

**Exit Ladder**:
- +5%: cover hedge cost / partial exit
- +8–10%: book 25%
- +12–15%: book another 25%
- Trailing: 5EMA or last swing low

**P&L Engine** — tracks qty_in/qty_out, avg_buy/avg_sell, invested capital, deployed %, realized + unrealized + total P&L.

**Hedge Guidance** — Portfolio summary returns `needs_hedge` flag (gross long ≥ ₹2L or ≥ 5 open trades) + suggested Nifty ATM PE lots (1 lot per ₹6L gross long).

**Seven Journal Endpoints**: open / list / detail / fill-log / stage-plan / close / delete.

---

### 6.7 Goals-Based Planning

Users can define investment goals with a target corpus and timeline. The engine:

1. Computes monthly SIP required given current corpus + assumed CAGR
2. Maps goal to a recommended asset-allocation blend (equity/debt/gold) based on time horizon + risk profile
3. Suggests specific fund categories that fit the goal's allocation
4. Scores the fit of existing holdings against the goal allocation
5. Flags allocation gaps between current holdings and goal-optimal allocation

**Goal types supported**: Retirement, Child Education, Home Purchase, Emergency Fund, Custom.

**API endpoints**: `POST /api/goals/create`, `GET /api/goals/{id}`, `POST /api/goals/{id}/suggest-funds`, `GET /api/goals/{id}/track`.

---

### 6.8 Tax Engine

#### 6.8.1 FIFO Cost Basis Matching

The tax engine (`tax_engine_fifo/`) implements proper FIFO lot matching:
- Every purchase creates a lot: (units, NAV, purchase_date, scheme_code)
- Every redemption matches lots FIFO (oldest first)
- Holding period determines tax regime:
  - **Equity funds & ETFs**: < 1 year = STCG at 20%; ≥ 1 year = LTCG at 12.5% (above ₹1.25L annual exemption, Budget 2024)
  - **Debt funds**: always at slab rate (post-April 2023 tax change)
  - **Hybrid (equity-oriented, > 65% equity)**: treated as equity

#### 6.8.2 Corporate Action Handling

FIFO lots are adjusted for:
- **Stock splits** — unit multiplication, proportional NAV adjustment
- **Dividends (IDCW)** — reinvested dividends create new lots
- **Switches** — treated as redemption + new purchase

#### 6.8.3 Tax Harvesting Suggestions

For holdings with unrealized LTCG approaching the ₹1.25L annual exemption:
- Flag holdings where harvesting (sell + rebuy) would reset cost basis with zero tax
- Show estimated annual tax saved
- Show impact on portfolio (exit load check, bid-ask spread note)

#### 6.8.4 Switch Cost Calculator

Every Switch action shows:
```
Gross Benefit = annual_expense_saving_rs (estimated × 5-year horizon)
Switch Cost   = exit_load_rs + estimated_LTCG_or_STCG_rs
Net Benefit   = Gross Benefit − Switch Cost
Payback Period = Switch Cost / (annual_expense_saving_rs)
```

---

### 6.9 Broker Integration — Secure Portfolio Connect (SPC)

Users can import live equity holdings directly from their broker accounts via read-only OAuth. This eliminates the need to upload a CAS for equity tracking.

**Supported Brokers** (read-only portfolio import):

| Broker | Mechanism | Status |
|---|---|---|
| Zerodha | KiteConnect SDK + Holdings API | Live |
| Upstox | OAuth 2.0 + Holdings API | Live |
| Angel One | SmartAPI + Holdings API | Live |
| Dhan | Dhan HQ SDK | Live |
| Fyers | Fyers API v3 | Live |
| 5Paisa | REST API | Live |
| Kotak Securities | REST API | Live |
| IIFL | REST API | Live |
| HDFC Securities | REST API | Live |

**Architecture**: Each broker adapter in `backend/brokers/` has:
- `api/` — auth (OAuth / API-key), holdings fetch, data normalization
- `mapping/` — instrument code translation (broker symbol → ISIN → instrument_master)
- `database/` — broker-specific symbol cache (SQLite per broker)

**OpenAlgo SPC**: For brokers configured in the user's local OpenAlgo instance, holdings are fetched via the OpenAlgo reverse-proxy at `/api/openalgo/*`. This decouples Nivesh from individual broker API changes.

**Data flow**: Broker holdings → normalize to Nivesh schema → upsert to MongoDB holdings → same scoring + insights pipeline as CAS-parsed holdings.

---

### 6.10 MFD Advisor Workspace

**The multi-client advisory surface** for AMFI-registered distributors.

#### 6.10.1 Client Management

- **Client 360 view** — portfolio health, risk score, last action plan status, pending actions, fund-level alerts
- **Client onboarding wizard** — 4-step flow: email invite → Gmail-connect CAS import → risk profile → plan generation
- **24-hour shareable link** — MFD generates a time-limited URL; client uploads CAS without creating a full account

#### 6.10.2 Advisor Home

Daily digest for the MFD:
- **Total AUM under advisory**
- **Clients needing attention** (performance drift, stale plan, upcoming redemptions)
- **Underperformer alerts** — clients whose funds have dropped a Quality tier since last review
- **Rebalance opportunities** — clients where allocation has drifted > 5% from target
- **Today's insights** — market-level commentary relevant to client book

#### 6.10.3 Portfolio Builder + Export

For each client:
- **AI Portfolio Design** — generates a model portfolio from scratch given risk profile + corpus + goals
- **PDF Report** — white-labeled report with fund scores, plan summary, tax impact, recommendations
- **WhatsApp-ready summary** — 200-word plain-English plan summary for sharing with client

---

### 6.11 NIDP Data Warehouse

**Nivesh Intelligent Data Platform** — the data infrastructure layer that feeds all analytics, scoring, and trading features.

#### 6.11.1 What NIDP Contains

The warehouse holds historical and live market data for the Indian equity and MF universe:

| Dataset | Source | Coverage | Rows (est.) |
|---|---|---|---|
| NSE Bhavcopy (OHLCV) | NSE Archives | 5 years × 2000 symbols | 5M+ |
| Delivery Data | NSE Archives | 5 years | 5M+ |
| FII/DII Flows | NSE | 5 years | 5K+ |
| F&O Bhavcopy | NSE | 5 years | 10M+ |
| AMFI Daily NAV | AMFI | 5 years × 10K schemes | 50M+ |
| MF Monthly Holdings | AMFI disclosures | 3 years × 3K schemes | 100K+ |
| MF Scheme Master | AMFI | All active schemes | 20K+ |
| NSE Quarterly Financials | NSE | 5 years × 2000 companies | 40K+ |
| RBI Yield Curve | RBI | 5 years | 2K+ |
| Corporate Actions | NSE | 10 years | 100K+ |
| Index Constituents | NSE | 6 indices × 5 years | 10K+ |
| Index Daily Close | NSE | 5 years × 6 indices | 10K+ |
| Stock Features (technical) | Derived | Daily × Nifty 500 | 1M+ |
| Corporate Announcements (NSE+BSE) | NSE API / BSE API | Live + 90-day history | 50K+ |
| Document Corpus (PDF chunks) | NSE/BSE filings | Live + historic | 500K+ |

#### 6.11.2 Data Pipeline Architecture

```
Phase 1 (Current) — Pull-based
  Ingestion sources (NSE, BSE, AMFI, RBI, ChartInk)
    ↓
  CLI orchestrator (nidp/cli.py)
    ↓
  Service modules (nidp/services/*)
    ↓
  PostgreSQL (TimescaleDB extension for time-series)

Phase 2 (Planned) — Event-driven
  Same sources → Kafka event bus → Airflow DAGs
  → Replay-from-archive capability
  → Redpanda (Kafka-compatible) + Schema Registry
```

#### 6.11.3 S4 — Corporate Announcements Pipeline (Live as of May 2026)

Both NSE and BSE announcement feeds are ingested and classified:

- **NSE feed**: 237+ announcements/day, 100% with ticker + ISIN + PDF attachment
- **BSE feed**: 200+ announcements/day, 4 paginated pages, 100% with company name + scrip code + PDF
- **Classifier**: `announcement_classifier.py` tags each announcement by category (board meeting, results, dividend, rights issue, CEO change, credit rating, etc.) via Claude Haiku
- **Storage**: Single `nidp.corporate_announcements` table; NSE and BSE rows differentiated by `source` column (NOT two tables — classifier queries are source-agnostic)

#### 6.11.4 S5 Week 1 — Document Intelligence (Live as of May 2026)

Corporate announcement PDFs are downloaded, parsed, and chunked:

- **Two-phase parser**: discover (register pending docs) → parse (download/extract/chunk)
- **`nidp.documents` table** is the work queue; no separate Kafka topic
- **pgvector embedding**: parser writes chunks with `embedding=NULL`; separate embedder service (S5 Week 2) backfills. Parser ships without the 1GB sentence-transformers dependency.
- **HNSW index**: intentionally NOT created until chunk count > 50K (avoids long table lock)
- **Validation**: RTNPOWER 20-page board meeting PDF → 41 chunks in 0.7s; HMAAGRO 10-page filing → clean extraction

#### 6.11.5 28 Avro Contracts

NIDP maintains strict schema contracts as Apache Avro files (`nidp/contracts/*.avsc`):

`bhavcopy_v1`, `delivery_v1`, `fii_dii_v1`, `fno_bhavcopy_v1`, `mf_nav_daily_v1`, `mf_holdings_monthly_v1`, `mf_scheme_master_v1`, `nse_financials_v1`, `rbi_yields_v1`, `corporate_actions_v1`, `index_constituents_v1`, `index_close_v1`, `stock_features_daily_v1`, `validation_finding_v1`, `snapshot_ready_v1`, and 13 more.

#### 6.11.6 NIDP CLI

```bash
python -m nidp.cli migrate              # Apply all schema migrations (001–031)
python -m nidp.cli health               # Connectivity + table checks
python -m nidp.cli ingest <service>     # Single service run (e.g. bhavcopy, bulk_deals)
python -m nidp.cli backfill \
  --from 2025-05-01 --to 2026-05-07    # Full year backfill (~30 min to 5 hours)
python -m nidp.cli backfill \
  --services bhavcopy,delivery         # Scope-limited backfill
```

---

### 6.12 OpenAlgo Trading Platform

**A fully separate, self-hosted trading platform** integrated with Nivesh as the execution layer for active traders.

#### 6.12.1 What OpenAlgo Is

OpenAlgo is an open-source project (integrated into `/app/openalgo`) that provides:

- **Unified Broker API** — 30+ Indian brokers via a single standardised REST interface (`/api/v1/`)
- **Python Strategy Host** — In-browser CodeMirror editor for strategy scripts
- **Flow Builder** — No-code visual strategy design using xyflow/React Flow drag-and-drop
- **Options Suite** — 12 analytical tools: Strategy Builder, Option Chain, IV Smile, GEX, OI Tracker, and more
- **Sandbox Engine** — ₹1 Crore paper trading with realistic margin simulation
- **WebSocket Proxy** — Unified real-time data stream (port 8765, ZeroMQ PUB/SUB)

#### 6.12.2 Integration with Nivesh

| Integration Point | How |
|---|---|
| **SPC (read-only portfolio import)** | OpenAlgo `/api/v1/holdings` → Nivesh backend → holdings upsert |
| **Positional scan execution** | Nivesh generates signal → user routes to OpenAlgo for order |
| **Strategy backtesting** | Nivesh strategy builder hits OpenAlgo backtest engine |
| **Instance management** | Nivesh provisions and manages per-user OpenAlgo instances via `openalgo_instance_manager.py` |

#### 6.12.3 OpenAlgo Architecture

- **Backend**: Flask application (`app.py`, 3000+ LOC) with 40+ blueprints
- **Frontend**: React 19 (built to `/frontend/dist/`, served by Flask static handler)
- **Databases**: 6 SQLite DBs (main, logs, latency, health, sandbox, DuckDB for backtesting)
- **Broker adapters**: 30+ in `openalgo/broker/` (Zerodha, Angel, Dhan, Upstox, Fyers, IIFL, Kotak, and more)

---

## 7. Technical Architecture

### 7.1 High-Level Stack

```
┌─────────────────────────────────────────────────────────┐
│                    CLIENT LAYER                         │
│  React 19 · Tailwind CSS · Shadcn UI · Recharts         │
│  Framer Motion · Capacitor (iOS/Android)                │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTPS / WebSocket
┌─────────────────────▼───────────────────────────────────┐
│                  API LAYER                              │
│  FastAPI (Python 3.11) · asyncio · Pydantic             │
│  43 route files · 170+ service modules                  │
└──────┬──────────────┬──────────────┬────────────────────┘
       │              │              │
┌──────▼──────┐ ┌─────▼──────┐ ┌───▼──────────────────┐
│  MongoDB    │ │ PostgreSQL │ │ Redis                │
│  (User data)│ │ (Market    │ │ (V3 score cache,     │
│  motor async│ │  analytics)│ │  24h TTL)            │
│  Collections│ │ asyncpg    │ │                      │
│  21+        │ │ 19 migr.   │ │                      │
└─────────────┘ └────────────┘ └──────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│              NIDP POSTGRES (separate DB)                │
│  TimescaleDB · 31 migrations · Avro schema contracts    │
│  NSE/AMFI/BSE/RBI/FII-DII market data                  │
└─────────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────┐
│           EXTERNAL DATA SOURCES                         │
│  AMFI (NAV) · NSE (bhavcopy) · BSE (announcements)     │
│  Groww (fund metadata) · RBI (yields) · yfinance        │
│  casparser.in · Google Document AI · Claude Vision      │
│  ChartInk (webhooks) · FRED (macro)                    │
└─────────────────────────────────────────────────────────┘
```

### 7.2 Backend Services Map

The backend is organized into 170+ service modules grouped by domain:

| Domain | Key Services |
|---|---|
| **CAS Parsing** | `cas_api_client`, `nivesh_cas_parser`, `claude_cas_parser`, `cas_parser`, `cas_snapshot_engine`, `cas_transactions` |
| **Scoring** | `v3_scoring`, `v3_integration`, `v3_explainer`, `v3_score_cache`, `nav_analytics`, `nav_analytics_sweep` |
| **Action Planning** | `action_plan_manager`, `rules_config`, `rules_dsl`, `priority_engine`, `decision_engine` |
| **Portfolio Intelligence** | `portfolio_intelligence`, `portfolio_enrichment`, `portfolio_health`, `portfolio_builder`, `portfolio_snapshot` |
| **Data Sourcing** | `groww_client`, `groww_fundamentals`, `amfi_nav`, `benchmark_index`, `pg_writer`, `pg_client` |
| **Tax** | `tax_calculator`, `tax_engine`, `tax_engine_fifo/` |
| **Trading** | `positional_engine/` (15+ modules), `strategy_engine/` |
| **Chat / Copilot** | `copilot_rag/orchestrator`, `copilot_rag/retrievers`, `risk_profile_chat`, `goal_copilot` |
| **Broker Integration** | `brokers/` (9+ adapters), `openalgo_client`, `openalgo_instance_manager` |
| **Market Data** | `live_price`, `macro_engine`, `macro_ingester`, `macro_sector`, `equity_sectors` |
| **Scheduling** | `mf_scheduler` (APScheduler, Asia/Kolkata) |
| **Infrastructure** | `helpers/secrets`, `helpers/feature_flags`, `helpers/datastore_isolation` |

### 7.3 Frontend Structure

- **Router**: React Router (Dashboard shell wrapping sub-pages)
- **State Management**: React Context + local state (no Redux)
- **Component library**: Shadcn UI (Radix primitives) + custom Tailwind components
- **Charting**: Recharts (composition, pie, area, line)
- **Animations**: Framer Motion
- **Build**: CRA + Craco (custom CRA config)
- **Linting**: ESLint + Biome.js
- **Mobile**: Capacitor (iOS 13+, Android 7+) — scaffolded

### 7.4 Deployment

- **Backend**: `uvicorn server:app` on port 8001; APScheduler starts automatically
- **Frontend**: Built to `dist/`, served as FastAPI static mount
- **OpenAlgo**: Separate Flask process on port 5000; WebSocket proxy on port 8765
- **NIDP**: CLI-driven (`python -m nidp.cli`), no daemon; jobs run via cron or APScheduler
- **Env isolation**: `helpers/datastore_isolation.py` enforces that production and preview environments use separate Postgres/Redis/Mongo instances

---

## 8. Data Model

### 8.1 MongoDB Collections (User-Scoped)

| Collection | Contents |
|---|---|
| `users` | email, Google sub, admin flag, risk_profile |
| `user_profiles` | onboarding flags, progressive profiling data |
| `holdings` | Asset records (MF folio, equity, bond, gold, ETF, FD) |
| `portfolios` | Portfolio-level aggregation cache |
| `action_plans` | Plan versions with actions[], scores, plan_summary |
| `pending_actions` | Actions awaiting user confirmation |
| `ai_insights` | Deterministic insights (not LLM) |
| `chat_sessions` | Copilot conversation history |
| `chat_messages` | Individual messages (user + assistant) |
| `cas_parsed_responses` | Cached raw CAS parse output per file_id |
| `cas_transactions` | Extracted transactions from CAS |
| `detected_sips` | Recurring SIP patterns detected from transactions |
| `trade_journal` | Positional trade records (open/closed) |
| `goal_investments` | Goal definitions + allocation targets |
| `upload_tasks` | Async CAS upload task status |
| `system_config` | Secrets, feature flags, rules config, prompts (shared) |

### 8.2 PostgreSQL Tables (Market-Wide Analytics)

| Table | Contents | Rows (approx.) |
|---|---|---|
| `instrument_master` | 735 instruments (712 equity + 23 MF) | 735 |
| `mutual_fund_metadata` | 58-column fund profiles (30+ funds) | 30+ |
| `mutual_fund_holdings` | Top-10 stock holdings per fund | 2,102 |
| `mutual_fund_performance_ratios` | Returns, Sharpe, Sortino, alpha, beta snapshots | 30+ |
| `mutual_fund_nav_history` | EOD NAVs (scheme, date, nav) | 33,994+ |
| `mutual_fund_aum_history` | AUM trend snapshots | — |
| `benchmark_master` | 34 SEBI categories → proxy benchmark fund mapping | 34 |
| `nav_analytics_job_log` | Nightly analytics sweep audit | — |
| `stock_scores` | Per-equity V3 scores | — |
| `benchmark_snapshots` | Daily index closes (14 indices) | — |
| `stock_scan_results` | Technical scan output (Nifty 500 universe) | — |
| `backtest_results` | Strategy backtest outcomes | — |
| `macro_regimes` | Daily regime snapshot (AGGRESSIVE/NORMAL/CAUTIOUS/DEFENSIVE) | — |
| `macro_indicators` | India + global macro metrics | — |

### 8.3 NIDP PostgreSQL Tables (Separate Schema)

| Table | Contents |
|---|---|
| `nidp.bhavcopy` | NSE daily OHLCV |
| `nidp.delivery` | Delivery volume per symbol |
| `nidp.fii_dii_flows` | FII/DII net flows |
| `nidp.mf_nav_daily` | AMFI daily NAV |
| `nidp.mf_holdings` | Top-10 per fund per month |
| `nidp.nse_financials` | Quarterly EPS, dividend |
| `nidp.rbi_yields` | Bond yield curve |
| `nidp.corporate_actions` | Splits, dividends, rights |
| `nidp.corporate_announcements` | NSE+BSE regulatory filings |
| `nidp.documents` | PDF chunks + embedding-ready text |
| `nidp.index_constituents` | Nifty 50/100/200/500/Bank/IT members |
| `nidp.index_daily` | Index daily close |
| `nidp.stock_features_daily` | Technical indicators (MA50, RSI, MACD) |
| `nidp.job_log` | Ingestion audit (service, date, status, rows, duration) |

---

## 9. Nightly Data Pipeline

The `mf_scheduler.py` APScheduler runs automatically at backend startup in Asia/Kolkata timezone:

| Time (IST) | Job | What It Does |
|---|---|---|
| 02:00–05:00 | `drain_weekday` | Process queued fund-scrape tasks (weekday mornings only) |
| 22:00 | `amfi_navs_daily` | Fetch ~14,000 EOD NAVs from AMFI NAVAll.txt; upsert `mutual_fund_nav_history` |
| 22:30 | `analytics_sweep_daily` | Recompute max_drawdown, consistency_score, downside_capture, aum_trend for all funds with ≥ 180 days NAV history (asyncio semaphore, parallel) |
| 22:45 | `v3_rescore_daily` | Recompute Quality + Health composites → write to PostgreSQL + invalidate Redis cache |
| Wed 03:00 | `stale_refresh` | Re-scrape Groww metadata for funds not updated in > 7 days |

Every job writes an audit record to `nav_analytics_job_log`. Status visible in Admin → Data Pipeline Monitor.

---

## 10. Security & Compliance

### 10.1 Authentication

- **Google OAuth 2.0** via Emergent platform (PKCE flow)
- Sessions managed via signed HTTP-only cookies
- Admin role gated separately; `is_admin` flag in MongoDB `users`

### 10.2 Data Security

| Control | Implementation |
|---|---|
| Transport | HTTPS everywhere (TLS 1.3) |
| At-rest (PII) | AES-256 planned for PAN (currently plaintext — P1 backlog) |
| Secret management | Secrets stored in MongoDB `system_config`, never in env files or code |
| Datastore isolation | Production and preview environments use strictly separate Postgres/Redis/Mongo instances (enforced at startup) |
| LLM safety | `llm_safety.py` screens outgoing prompts for PAN/account number patterns |

### 10.3 DPDP Act 2023 Compliance (scaffolded)

India's Digital Personal Data Protection Act 2023 compliance features:

- **Consent management** — `POST /api/compliance/consents` logs explicit, timestamped consent per data category
- **Data export** — `POST /api/compliance/audit-export` generates full data audit trail for the user
- **Right to be forgotten** — `POST /api/compliance/data-deletion` + `DELETE /api/user/pan` wipes all PII and analytics data for a user
- **Audit trail** — every admin action and data-access event logged to `audit_log` collection

### 10.4 Principle of Least Privilege (Broker Integration)

- All broker connections are read-only (holdings + P&L fetch; no order placement via Nivesh backend)
- OAuth tokens are stored encrypted per-user; never logged
- OpenAlgo SPC uses a reverse-proxy architecture — broker credentials never leave the user's local OpenAlgo instance

---

## 11. Admin Console

The admin console (`/admin` route, role-gated) provides live control over every system parameter without code deployment.

### 11.1 Secrets Management

CRUD interface for 30+ registered secrets:

| Category | Secrets |
|---|---|
| Parsing | `GOOGLE_DOCAI_CREDENTIALS_JSON`, `GOOGLE_DOCAI_PROJECT`, `GOOGLE_DOCAI_PROCESSOR`, `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY` |
| LLM | `EMERGENT_LLM_KEY` |
| Auth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GMAIL_OAUTH_CLIENT_ID` |
| Datastores | `POSTGRES_URL`, `REDIS_URL`, `NIDP_POSTGRES_URL` |

All values masked in the UI (show/hide toggle). Changes take effect immediately.

### 11.2 Feature Flags

Each feature flag has:
- **Enabled/disabled toggle**
- **User allowlist** (comma-separated emails for beta access)
- **Description**

Feature flags power gradual rollout of all new features (e.g., `enable_positional_scanner`, `enable_goals_planning`, `enable_mfd_workspace`).

### 11.3 Rules Configuration

Live-tunable thresholds for the action plan engine:

| Parameter | Default | Effect |
|---|---|---|
| AMC concentration threshold | 15% | Rule 2 trigger |
| Category concentration threshold | 35% | Rule 2b trigger |
| Debt floor — Low risk | 30% | Rule 5 trigger |
| Debt floor — Moderate risk | 20% | Rule 5 trigger |
| Debt floor — High risk | 10% | Rule 5 trigger |
| Cost-leak minimum | ₹10,000/year | Rule 6 trigger |
| Min switch score | 1.0 | Rule 6 guardrail |
| High-quality protection threshold | Q≥75 AND H≥70 | Guardrail 1 |
| Recent-investment lockout | 6 months | Guardrail 3 |

### 11.4 Prompts Management

Seven LLM prompts are admin-managed:

| Prompt | Purpose |
|---|---|
| `copilot_system` | Main copilot persona + grounding instructions |
| `plan_summary` | Converts structured plan to 200-word plain English |
| `insight_narrative` | Portfolio insight description |
| `goal_advice` | Goal-based investment guidance |
| `risk_profile_intro` | Risk questionnaire preamble |
| `whatsapp_export` | Mobile-friendly plan summary |
| `mfd_client_report` | Advisor report narrative |

Each prompt has a sandbox test mode: provide mock data, see LLM completion, iterate without affecting live users.

### 11.5 Data Pipeline Monitor

Three-panel view:
- **Job status tiles** — AMFI NAV, Analytics Sweep, V3 Rescore (last run time, status, rows processed, duration)
- **Recent runs** — 20-row audit log from `nav_analytics_job_log`
- **Scheduler status** — APScheduler next-fire time for each job
- **Redis key count** — live count of `v3:score:*` cache keys
- **Manual trigger** — on-demand button for each job
- **Cache invalidation** — "Clear all V3 cache" button

### 11.6 User Management

- **Searchable user table** — email, corpus, last active, plan count
- **Per-user actions**: promote to admin, force logout, reset portfolio
- **Portfolio reset**: wipes 21 user-scoped MongoDB collections + Redis caches; gated by email-confirmation modal showing exact deletion scope

### 11.7 CAS Parser Configuration

Admin toggle for the active CAS parsing provider:
- Nivesh Parser (Google Document AI) — default
- Claude Vision (Anthropic Claude)
- casparser.in API

Shows configured-flag status for each provider. Sandbox mode toggle for casparser.in.

---

## 12. API Surface

### 12.1 User-Facing Endpoints (43+ routes)

#### Portfolio

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/portfolio/cas-upload` | Upload CAS PDF (triggers async parse) |
| POST | `/api/portfolio/upload-raw` | Raw CAS PDF upload (for Claude Vision path) |
| GET | `/api/portfolio/holdings` | All holdings with live prices |
| PUT | `/api/portfolio/holdings/{id}` | Update holding (buy_date, notes) |
| DELETE | `/api/portfolio/holdings/{id}` | Remove holding |
| GET | `/api/portfolio/snapshots` | Time-machine snapshots |
| GET | `/api/portfolio/export/csv` | Download holdings as CSV |

#### Intelligence & Insights

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/intelligence/portfolio` | Overlap matrix, concentration, asset allocation |
| GET | `/api/intelligence/v3-score/{id}` | V3 score breakdown for one fund |
| POST | `/api/insights/generate` | Generate deterministic insights |
| GET | `/api/insights/v3-portfolio` | Per-fund V3 scores + danger + explanation |

#### Action Plans

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/plans/generate` | Generate preview plan |
| POST | `/api/plans/{id}/save` | Activate plan |
| GET | `/api/plans/active` | Current active plan |
| GET | `/api/plans/{id}` | Plan detail |
| PATCH | `/api/plans/{id}/actions/{aid}/status` | Mark done/skipped |
| POST | `/api/plans/{id}/actions/{aid}/feedback` | Thumbs up/down |

#### Market Intelligence

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/positional/market-dashboard` | Deploy verdict + regime + sector heatmap |
| GET | `/api/positional/picks` | Top BTST/positional picks (live LTP enriched) |
| GET | `/api/positional/scans` | Configured scan list |
| POST | `/api/positional/scans/seed-defaults` | Seed 4 default ChartInk scan formulas |
| POST | `/api/positional/scans/{id}/webhook` | Receive ChartInk scan hit |
| POST | `/api/positional/journal` | Open trade journal entry |
| GET | `/api/positional/journal` | List open/closed trades |
| GET | `/api/positional/journal/{id}` | Trade detail (live P&L) |
| POST | `/api/positional/journal/{id}/fill` | Log staged fill |
| POST | `/api/positional/journal/{id}/close` | Close/stop trade |
| GET | `/api/positional/journal/summary/portfolio` | Portfolio P&L + hedge guidance |

#### Goals

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/goals/create` | Define investment goal |
| GET | `/api/goals` | All goals |
| GET | `/api/goals/{id}` | Goal detail + allocation |
| POST | `/api/goals/{id}/suggest-funds` | Fund picker for goal |
| GET | `/api/goals/{id}/track` | Progress tracking |

#### Chat & Copilot

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/chat` | Copilot message (grounded on plan) |
| POST | `/api/scenarios/simulate` | What-if simulator |

#### MFD Advisor

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/advisor/home` | Today's insights + AUM + alerts |
| GET | `/api/advisor/clients` | Client list |
| GET | `/api/mfd/clients/{id}` | Client 360 view |
| POST | `/api/mfd/onboard` | Start client onboarding |
| GET | `/api/mfd/cas-uploads/{file_id}/parsed-response` | View parsed CAS JSON |

#### Compliance

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/compliance/consents` | Consent log |
| POST | `/api/compliance/audit-export` | Data audit export |
| POST | `/api/compliance/data-deletion` | Right to be forgotten |

### 12.2 Admin-Only Endpoints (20+ routes)

| Domain | Key Endpoints |
|---|---|
| Secrets | `GET/POST/DELETE /api/admin/secrets` |
| Feature Flags | `GET/POST /api/admin/feature-flags/{flag}/toggle` |
| Rules | `GET/PATCH /api/admin/rules-config` |
| Prompts | `GET/POST /api/admin/prompts/{id}/test` |
| Data Pipeline | `GET /api/admin/data-pipeline/status`, `POST /api/admin/data-pipeline/trigger/{job}` |
| Users | `GET/DELETE /api/admin/users`, `POST /api/admin/users/{id}/promote-admin`, `POST /api/admin/users/{id}/reset-portfolio` |
| Cache | `POST /api/admin/cache/invalidate` |
| NIDP | `GET /api/admin/nidp/status`, `POST /api/admin/nidp/backfill`, `GET /api/admin/nidp/jobs` |

---

## 13. Current Build Status (May 2026)

### 13.1 What Is Live (fully functional)

| Feature | Notes |
|---|---|
| CAS parsing (3-provider) | Nivesh Parser as default; Claude Vision + casparser.in as fallback |
| V3 scoring (38 primitives, 5 composites) | Nightly refresh from AMFI + Groww |
| Action plan engine (6 rules + 4 guardrails) | All rules active; thresholds live-tunable |
| Portfolio Intelligence (overlap, concentration) | Stock-level overlap heatmap live |
| AI Copilot (grounded narrative) | GPT-4o-mini via Emergent LLM key |
| Market Dashboard (live Nifty + 12 sectors) | 30s cache during market hours |
| Positional trading + Trade Journal | Full staged-entry + exit-ladder + P&L |
| BTST scan integration (ChartInk webhooks) | 4 default scans seeded |
| Goals-Based Planning | Goal create/track/suggest-funds |
| Tax Engine (FIFO + harvesting) | LTCG/STCG per current tax rates (FY 2024–25) |
| MFD Advisor Workspace | Client 360, onboarding wizard, PDF/WhatsApp export |
| Broker Integration SPC | 9 brokers via OpenAlgo read-only |
| OpenAlgo Trading Platform | Separate Flask instance, 30+ broker adapters |
| NIDP Data Warehouse Phase 1 | CLI-driven, 1-year backfill, NSE/AMFI/BSE/RBI |
| S4 Corporate Announcements | NSE + BSE live feed, classifier, PDF attachment |
| S5 Week 1 Document Intelligence | PDF chunking, pgvector-ready, embedder pending |
| Admin Console | Secrets, feature flags, rules, prompts, pipeline monitor, user mgmt |
| DPDP compliance (scaffolded) | Consent, audit export, data deletion endpoints exist |

### 13.2 Validated Numbers (May 8, 2026)

- **Market Dashboard live reading**: CAUTIOUS · Nifty 24,165 (−0.66%) · VIX 17.12 (+3.02%) · IT +1.0% HOT
- **NSE announcements**: 237/day, 100% with ticker + ISIN + PDF
- **BSE announcements**: 200/day, 100% with company name + scrip + PDF
- **CAS parsing accuracy**: 97.1% portfolio value match on 18-page NSDL CAS
- **V3 score cache**: 34,000+ NAV rows, nightly recompute functional
- **BTST picks load time**: 1.0s cold, 0.27s warm (vs 35s+ before the batching fix)

---

## 14. Known Gaps & Roadmap

### 14.1 P1 Backlog (Next Sprint)

| Item | Gap | Fix |
|---|---|---|
| **PAN encryption** | PAN stored as plaintext; AES-256 not yet applied | Encrypt at rest using `pii_security.py` AES utilities already built |
| **Alpha mapping** | Some funds return `alpha = 0`; data quality issue with Groww scraper | Add fallback to benchmark proxy computed from nav_history |
| **DPDP formal compliance** | Scaffolding exists; formal audit trail incomplete | Complete audit middleware, consent versioning, DPA officer designation |
| **S5 Week 2 Embedder** | pgvector chunks written but embeddings are NULL | Deploy sentence-transformers embedder service; create HNSW index after 50K chunks |
| **BSE ISIN resolution** | BSE rows lack ISIN; `ticker_symbol` left NULL | Build join on `nidp.equity_master.scrip_code` at query time |

### 14.2 V3.1 Improvements (Near-Term)

| Item | Description |
|---|---|
| **HOLD action type** | Currently no explicit "Hold — no action needed" verdict; add as a 6th action_type |
| **hold_score composite** | Mirror of exit_score but inverted; drives HOLD verdict |
| **Insight severity** | Add HIGH/MEDIUM/LOW severity to insights (currently all the same visual weight) |
| **Backtest calibration** | Run the 4 BTST ChartInk scans against 2-year historical bhavcopy to validate signal quality |
| **F&O OI anomaly tracker** | OI + Volume + Delivery anomaly detection for F&O stocks (needs F&O bhavcopy + live OI feed) |
| **Auto-Nifty-PE hedge sizing** | Real option chain integration for hedge lot sizing (currently rule-of-thumb) |

### 14.3 Phase 2 — NIDP Event-Driven Pipeline

| Component | Description |
|---|---|
| Kafka / Redpanda | Replace CLI pull-based ingestion with event bus |
| Airflow DAGs | Orchestrate ingestion, validation, feature engineering |
| Schema Registry | Enforce Avro contracts at publish time |
| Replay-from-archive | Raw files stored in MinIO for replaying from historical snapshots |
| Prometheus + Grafana | Pipeline observability dashboard (scaffolded in `nidp/deploy/docker-compose.dev.yml`) |

### 14.4 Mobile App

Capacitor scaffolding exists for iOS and Android. Key remaining work:
- Deep-link handling for CAS callback OAuth flow
- Push notifications for plan action reminders
- Biometric auth (FaceID / fingerprint) for app unlock
- App Store / Play Store submission

### 14.5 Multi-Persona Roadmap

| Phase | Persona | Capability |
|---|---|---|
| **Phase 1 MVP** (done) | Retail investor | CAS + Excel + broker import · dashboard · health score · action plan |
| **Phase 2** (in progress) | Retail + MFD | ICICI/Groww/Upstox SPC · transactions · goals · positional scanner |
| **Phase 3** (planned) | PMS/AIF + Family Office | Multi-account aggregation · WhatsApp CAS import · voice copilot |
| **Phase 4** (aspirational) | Institutional | NIDP data API · quantitative strategy platform · white-label |

---

*Document compiled May 8, 2026. Covers all development on the `nidp` branch through commit `2c1df16`.*
