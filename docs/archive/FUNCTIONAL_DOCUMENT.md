# Nivesh.ai — Functional Document

> **One-liner.** An Agentic Wealth Operating System for the Indian retail investor and the wealth advisor who serves them — turning a stack of CAS PDFs and live market noise into a single, explainable, tax-aware action plan.

---

## 1 · Executive summary

Indian households hold ~₹68 lakh crore across mutual funds and another ~₹350 lakh crore in direct equities, but most investors have no working answer to the question *"what do I own, is it any good, and what should I do about it?"*. The market is full of dashboards, screeners, and Telegram tipsters. None of them pull your real holdings, score them on first principles, account for tax + cost friction, factor in the macro regime, and tell you what to do — with reasons you can verify.

Nivesh does. It ingests your CAS (Consolidated Account Statement), parses every holding down to ISIN and folio, scores each instrument across 38 deterministic primitives, layers a real-time macro intelligence overlay on top, and emits an action plan that an MFD advisor or a self-directed retail investor can actually execute — with the math shown.

There is no hallucinated number anywhere in the analytics path. The LLM exists only to narrate decisions that have already been made deterministically.

---

## 2 · The problem we solve

### 2.1 The retail investor's problem

A typical Indian retail investor has 8–25 mutual fund holdings accumulated over 5–15 years. They don't know:

- **What they own** — folios scattered across NSDL + CDSL CAS, broker apps, AMC portals, paper statements
- **Whether it's any good** — fund ratings on Groww/MoneyControl are vendor-driven; star ratings have well-documented selection bias
- **Whether they have duplicates** — Regular and Direct variants of the same scheme, three large-cap funds that hold the same 20 stocks, an AMC owning 60% of their book
- **Whether to switch** — the math behind "is the better fund worth the LTCG tax + exit load + alpha gap?" is non-trivial, and nobody shows it
- **What the market is doing** — and how that should change *their* allocation, today
- **What single, ranked, do-this-not-that list of actions** exists for *their* portfolio

### 2.2 The MFD advisor's problem

A typical MFD advisor serves 200–2000 clients. They cannot:

- **Look at every client every day** — the client book outgrows attention; "important" gets lost in "loud"
- **Detect performance drift across the book** — which clients are 5pp behind Nifty, with how much AUM, why
- **Surface rebalance opportunities** — when does drift cross the threshold worth a phone call vs not
- **Generate plans at scale** — manually pulling Direct-vs-Regular comparisons, switch costs, tax impacts, peer fund alpha for each fund in each client's portfolio is impossible without software
- **Answer "why" with confidence** — clients ask "why are you recommending this?" and a vibe-based answer no longer works under SEBI Investment Advisor regs

### 2.3 The trader's problem (newer surface)

A self-directed trader running 5–30 day positional trades has:

- **Twelve different signal sources** — Chartink scans, broker scanners, Twitter, Telegram, Yahoo data, NSE bhavcopy
- **No single ranking** — every source gives a list, no source gives a *plan*
- **No regime overlay** — RSI 65 in a low-vol bull market means something different than RSI 65 in a high-VIX risk-off — but the screeners don't know that
- **No execution discipline** — entry / SL / target / position size needs to be computed *before* the trade, not retrofitted after

### 2.4 What the market currently offers

| Tool class | Examples | What it does well | What it fails at |
|---|---|---|---|
| Robo-advisors | Scripbox, Coin | Goal-based MF baskets | No CAS import, no per-holding decision, no MFD layer |
| Aggregators | INDmoney, Vested | Pretty dashboards across CAS | No scoring, no decisions, just visualisation |
| Screeners | TickerTape, Screener.in | Stock fundamentals lookup | No portfolio context, no plan |
| Trading platforms | Zerodha, Angel | Order execution | No advisory, no scoring |
| LLM chatbots | ChatGPT, Bard with portfolio | Conversational | Hallucinates numbers, cannot read CAS, no real-time data |
| MFD CRMs | Wealthy, Smallcase manager | Workflow management | Per-client analytics is shallow; no built-in advisory engine |

Nivesh sits in the gap that none of these fill: **a deterministic advisory engine that reads your CAS, knows the Indian tax code, integrates with the Indian market (NSE / AMFI / SEBI), explains its reasoning, and serves both retail self-direction and MFD scale**.

---

## 3 · Who Nivesh is for

### 3.1 Primary persona — the self-directed retail investor

- 25–55 years old
- ₹5L–₹5Cr investable corpus
- 8–25 mutual fund holdings + 0–30 direct stocks
- Tech-comfortable, time-poor
- Uses Groww/Zerodha/Coin for execution; uses Excel + WhatsApp groups for "advice"

### 3.2 Primary persona — the wealth advisor (MFD)

- AMFI-registered Mutual Fund Distributor
- 200–2000 clients
- Currently using Excel + bespoke spreadsheets + AMC portals
- Bottleneck is time-per-client and ability to articulate "why" under SEBI scrutiny

### 3.3 Secondary persona — the MFD's client (impersonated user)

- Doesn't sign in directly; sees a clean Portfolio + Insights + Plan via the MFD's invite link
- Onboards via a 24h-shareable Gmail-connect URL, consents to data use, uploads CAS

### 3.4 Future persona — the active trader

- Manages a positional book on top of long-term investments
- Wants a single ranked daily picks list with macro alignment + execution rules
- Currently served by the Market Dashboard + Positional Picks panel

---

## 4 · What Nivesh does — functional capabilities

This section is organised by user-visible capability, not by code module.

### 4.1 Read your portfolio in 30 seconds

**Input** — a CAS (Consolidated Account Statement) PDF from NSDL or CDSL. Email-delivered monthly by both depositories, free.

**What happens**
1. Drag the PDF into Nivesh (or click "Connect via Gmail" — it auto-pulls your latest CAS)
2. The parser extracts every folio, ISIN, transaction, NAV, and unit-balance
3. Holdings are deduplicated (Direct + Regular plans of the same scheme are normalised; folios for the same fund collapse into one row)
4. Cost basis is reconstructed from transactions when CAS doesn't ship invested amounts directly
5. Each upload becomes a frozen point-in-time snapshot — re-uploading next month gives you a Time-Machine

**What you get** — a clean, deduplicated, cost-basis-aware portfolio with no manual data entry.

### 4.2 Score every holding on first principles

For each mutual fund, Nivesh computes **four orthogonal composite scores** from 38 primitive signals:

| Score | What it asks | Sample inputs |
|---|---|---|
| **Quality** | Is this a good business? | ROE, debt-to-equity, EPS growth, promoter holding, market-cap stability, earnings consistency |
| **Health** | What's its current trajectory? | Revenue growth, margin trend, debt trend, earnings surprise, volatility, dividend yield |
| **Exit** | Is now the time to sell? | PE overvaluation, earnings decline, quality deterioration, debt spike, liquidity risk, tax impact |
| **Add** | Should you put more in? | Sector gap, low overlap, relative valuation, quality, momentum, dividend |

Every primitive has a defined formula. Every weight is editable in the admin panel. Every score persists alongside its component breakdown so a user can drill in and see *why* a fund got a 72.

### 4.3 Tell you what to do with each holding

For each holding, the engine emits a **recommendation card** answering four questions:

1. **Why** — what triggered this verb (Exit / Switch / Add / Hold)?
2. **What to do** — the specific action (e.g. "Switch from Regular to Direct of HDFC Top 100")
3. **Cost & Tax** — switch cost as a % of corpus, broken down (expense delta, exit load, LTCG drag)
4. **Worth it?** — yes/no based on whether expected alpha covers the friction

The verb itself comes from a **5-bucket switch decision taxonomy**:

- **STAY** — keep the fund, it's fine
- **SWITCH-TO-DIRECT** — same fund, switch from Regular to Direct plan (saves ~0.7–1% p.a. expense ratio)
- **SWITCH-TO-PEER** — exit this fund and buy a better-scoring peer in the same category
- **EXIT-TO-CASH** — fund is broken; the fix isn't another fund, it's redemption
- **REVIEW** — needs human eyes (low confidence, manager change, etc.)

### 4.4 Generate a portfolio-wide action plan

Nivesh runs **7 deterministic rules in sequence** across the entire portfolio:

1. **Regular → Direct conversions** (always-win switches; no risk, just tax)
2. **AMC concentration** — flags when one AMC owns >30% of the book
3. **Category drift** — over-concentration in any single MF category
4. **Performance laggards** — funds with V3 quality issues + high exit-score
5. **Overlap collapse** — multiple funds holding >70% identical stocks
6. **Debt allocation** — drift from risk-profile-appropriate equity/debt mix
7. **Hold everything** — fallback when nothing else triggers

The output is a **kanban-style Action Plan board** with EXIT / SWITCH / ADD / HOLD lanes. Each card has its reason text, cost math, and an action verb. The user (or advisor) can mark a card as actioned and the plan re-flows.

### 4.5 Read the macro regime

Every weekday at 18:35 IST, Nivesh ingests 5 macro metrics — Brent crude, USDINR, US 10y yield, Nifty 50, India VIX — and classifies the day into a 4-axis regime:

| Axis | Possible values |
|---|---|
| **Market** | BULL / BEAR / NEUTRAL |
| **Inflation** | RISING / FALLING / NEUTRAL |
| **Liquidity** | ABUNDANT / TIGHT / NEUTRAL |
| **Risk** | LOW / MEDIUM / HIGH |

A composite risk score maps to a **macro multiplier** (1.0× / 0.9× / 0.8×) which automatically scales every position-size recommendation. In a HIGH-risk regime, every recommended trade size is 80% of base. The user doesn't need to remember to "trim aggressive sizing in volatile markets" — the system does it.

### 4.6 Show sector tilts with reasons

The Sector Heatmap shows which sectors are in tailwind and which are headwind, with a one-sentence rationale per sector:

> **AVIATION (+4.2)** — Crude falling → cheaper ATF → aviation margin tailwind
> **PAINT (+4.2)** — Crude falling → cheaper inputs → margin expansion for paint
> **OIL_GAS (−4.2)** — Crude falling → revenue compression for upstream

The rationale is generated from a hardcoded sensitivity matrix (PAINT crude=−1.0, IT usd=+1.0, BANK yield=−0.5, etc.) plus a templated reasons dict. Not LLM. Reproducible. Auditable.

### 4.7 Generate 5–30 day positional trade ideas

The Positional Engine sits **on top of** the long-term scoring layer:

- Pulls daily OHLCV + delivery % from NSE bhavcopy for ~2,700 cash-segment stocks
- Receives **real-time Chartink scan triggers** via webhook (Chartink alert fires → POSTs to Nivesh → hit lands in the universe within seconds)
- Computes 24 technical features per stock (SMA, EMA, RSI, MACD, ATR, Bollinger width, slope, swing levels, volume Z, delivery trend, etc.)
- Combines into 6 sub-scores (trend / momentum / structure / accumulation / sector / risk) → final weighted score
- Classifies the stock into a **stage**: ACCUMULATION / EARLY_BREAKOUT / BREAKOUT / EXTENDED / WEAK
- Generates a stage-aware **trade plan** — entry, stop-loss, target, risk:reward (≥1:1.5 floor)
- Applies the macro multiplier from §4.5 to position-size

During market hours (09:15–15:30 IST), each pick gets a **live readiness chip**:

- **🟢 TRIGGERED** — current LTP at or above entry
- **🟡 NEAR** — within 2% of entry
- **WAIT / FAR** — below entry
- **🔴 STOPPED** — LTP at or below stop-loss

Polled every 60 seconds. The user sees their picks update in real-time without staring at a separate ticker.

### 4.8 Plan around goals, not just funds

For users who want goal-based planning, Nivesh offers:

- Goal creation flow with target amount + target date
- Required SIP computation (with assumed return ranges)
- On-track / off-track tracking against current corpus
- Auto-suggested fund baskets matched to goal horizon + risk profile
- Per-goal Copilot route ("am I on track for my child's education?")

### 4.9 Be tax-smart by default

Every Exit or Switch recommendation accounts for:

- **LTCG** (12.5% above ₹1.25L threshold under FY25-26 rules)
- **STCG** (20% on holdings <1 year)
- **Debt fund slabs** (post-2023 debt tax regime)
- **ELSS lock-in** (3-year tax-saving lock-in is enforced — Nivesh won't recommend exiting an ELSS within lock-in)
- **Buy-date attribution** — the user can edit buy-date inline; Nivesh recomputes LTCG/STCG split

The **switch cost framework** computes:

```
switch_cost % = expense_delta + redemption_load + tax_drag − expected_alpha
```

If switch_cost is negative (i.e. expected alpha exceeds friction), the recommendation is "switch". If positive, "stay". The math is shown to the user, not hidden behind an opaque verdict.

### 4.10 Serve advisors at scale (MFD multi-client)

The MFD layer is a first-class product surface, not an afterthought:

- **Workspace + profile model** — one MFD owns multiple shadow-user profiles
- **Profile activation (impersonation)** — the MFD can "enter" any client's portfolio with one click; every page in the app then shows that client's data
- **Advisor Home** — proactive 4-card grid:
  - **Today** — clients meeting today / called recently / at risk
  - **AUM** — AUM movement, top contributors, churn
  - **Underperformers** — clients lagging Nifty 50 by ≥ N pp
  - **Rebalance** — clients off target allocation
- **Client invite** — generate a 24h-shareable URL with consent; the client uploads their CAS at their end without needing a Nivesh login
- **Action plans** for each client are computed independently with the same engine — the advisor isn't doing a different analysis for retail vs MFD; they're using the same core

### 4.11 Be DPDP-compliant from day one

- Consent collection on every onboarding step
- PAN never stored raw; hashed at write
- Audit log for every PII operation
- User can export their full data as JSON
- Consent revocation cascades to data deletion

### 4.12 Embedded Copilot — explain anything

A chat drawer accessible from any page. Grounded on:

- Active Action Plan
- Current portfolio holdings + V3 scores
- Recent transactions + SIP detection
- Macro context

Not grounded on the LLM's training data. The retrievers ([copilot_rag](backend/services/copilot_rag/)) feed the LLM only data the user owns. The LLM emits chart specs (validated server-side against a narrow 4-type schema) and narrative text that wraps deterministic numbers. **No number ever comes out of the LLM that wasn't first computed by the analytics layer.**

---

## 5 · How Nivesh works — the architecture, told as a story

This section walks through what happens when a user uploads their CAS, end-to-end.

### 5.1 The data layer — what we know about the world

Every piece of "fact" Nivesh knows comes from one of these sources, each ingested on a known cadence:

| Source | What it gives us | Cadence |
|---|---|---|
| **AMFI `NAVAll.txt`** | Daily NAV for every Indian MF (~10,000 schemes) | Daily 17:30 IST |
| **Groww `__NEXT_DATA__`** | Fund metadata: AUM, expense, manager, holdings, ratings (38 fields per fund) | Weekly (drain queue) |
| **NSE bhavcopy `sec_bhavdata_full`** | Daily OHLCV + delivery % for ~2,700 cash-segment stocks | Daily ~13:00 IST |
| **NSE archive (corporate filings)** | Shareholding pattern, bulk/block deals (planned) | Quarterly + daily |
| **yfinance** | Macro metrics (crude, USD, yields, indices) + benchmark indices | Daily 18:30 IST |
| **Morningstar (scrape)** | Quantitative star rating per equity stock | Weekly |
| **Chartink webhook** | Real-time scan-trigger alerts (when user-saved scans fire) | Event-driven |
| **Alpha Vantage** | Fallback for macro metrics | On yfinance failure |
| **CAS PDF (user-uploaded)** | The user's actual holdings + transactions | On upload |

Every ingest is **idempotent** (re-running doesn't duplicate), **sanity-gated** (values >10% off the prior bar are rejected), and **audit-logged**.

### 5.2 The scoring layer — turning data into judgement

Once a CAS lands, Nivesh has a list of (fund_isin, units, buy_price, buy_date) tuples. To turn that into "your portfolio is over-concentrated in IT and you have two large-cap funds that overlap 87%", three things happen:

1. **Fund metadata join** — every ISIN is joined against `mutual_fund_metadata` (the 38-column central table) to get manager, expense, AUM, ratings, top-10 holdings, etc.
2. **Score computation** — Quality / Health / Exit / Add composites are computed per fund (cached in Redis with 24h TTL)
3. **Portfolio analysis** — overlap detection (stock-level look-through across funds), AMC concentration, category drift, sector exposure, duplicate-fund detection, tax-cost projections

All of this is **deterministic** — same input always produces same output. No LLM in the loop. The same code runs in tests and in production.

### 5.3 The decision layer — turning judgement into action

Three engines collaborate:

- **V3 Decision Engine** — per-holding 5-bucket verdict (STAY / SWITCH-TO-DIRECT / SWITCH-TO-PEER / EXIT-TO-CASH / REVIEW) + reason text
- **Action Plan Manager** — applies 7 portfolio-level rules sequentially, generates a plan
- **Switch Cost Framework** — for every Exit/Switch, computes whether the cost-of-switch is justified by expected alpha

The output is a **plan** — a list of cards, each with a verb, a target instrument, expected impact, and reason text. The user can act on each card or override.

### 5.4 The presentation layer — surfacing the plan

The frontend has six primary surfaces:

| Page | Audience | What it shows |
|---|---|---|
| **Onboarding** | New user | Name → CAS → risk profile → goals (4 steps) |
| **Portfolio** | All | Holdings table with V3 scores, action badges, expandable per-row Decision Card |
| **Insights** | All | Quality issues, health gaps, exit candidates, add suggestions — sectional |
| **Action Plan** | All | Kanban board with EXIT / SWITCH / ADD / HOLD lanes |
| **Goals** | All | Per-goal tracking with on-track/off-track |
| **Market Dashboard** | All | Macro regime + sector heatmap + positional picks |
| **Advisor Home** | MFD | 4-card proactive grid across the client book |

The **Nivesh Copilot** drawer is accessible from every page — same context, different surface.

### 5.5 The cadence layer — when things refresh

| Time | What happens |
|---|---|
| 08:30 IST | V3 nightly rescore of every fund |
| 13:00 IST (after) | NSE bhavcopy publishes — positional engine ingests OHLCV |
| 17:30 IST | AMFI NAV pull + `nav_analytics_sweep` |
| 18:30 IST | Benchmark indices refresh (Nifty 50 + Midcap + Smallcap + 500) |
| 18:35 IST | Macro intelligence refresh (`macro_engine.run_daily`) |
| 19:00 IST (weekdays) | Cron-of-last-resort hits `/api/macro/refresh` (remote-agent fallback) |
| 23:30 IST | Portfolio EOD snapshot |
| Real-time | Chartink webhooks land as soon as scans fire |
| Real-time | LTP polling on Positional Picks every 60s during market hours |

Every job is observable in the admin Data Pipeline tile — last-run + duration + row counts + manual trigger button.

---

## 6 · Why we built it this way — key architectural decisions

These are the decisions that defined the product's character.

### 6.1 Deterministic analytics, narrative LLM

**Decision** — every number on screen is computed by a deterministic Python function. The LLM only narrates decisions.

**Why** — under SEBI Investment Advisor regs, "the fund is bad because the LLM said so" is not a defensible position. Under DPDP, an unauditable recommendation is a compliance risk. Under user trust, a hallucinated number once destroys credibility forever.

**Consequence** — the V3 scoring sheet is the source of truth. The code mirrors the sheet. The LLM gets the score and writes a sentence around it. Same score in tests, in dev, in prod. No drift.

### 6.2 Rules + DSL + admin-tunable thresholds

**Decision** — every rule that drives a recommendation is expressed as a DSL clause (whitelisted AST, no eval) with thresholds editable in the admin UI.

**Why** — the right "performance laggard" threshold isn't 25% lag, it's "whatever the senior advisor thinks". Rules need to be tunable without a deploy. They need to be auditable (every threshold change is logged).

**Consequence** — onboarding a new advisory partner means editing rules, not editing code.

### 6.3 Indian-context first

**Decision** — every interaction assumes Indian context. CAS (NSDL/CDSL), AMFI scheme codes, NSE/BSE symbols, INR everywhere, Asia/Kolkata timezone, FY25-26 tax slabs, ELSS lock-in, DPDP compliance.

**Why** — generic portfolio tools don't model Direct vs Regular MF plans. Don't account for SIP-mode tax arithmetic. Don't know that ELSS is locked for 3y. Building for "global" first means under-serving the Indian investor everywhere.

**Consequence** — every screen, every score, every action is computed against Indian rules. Adding a new geography would be a rewrite, not a config.

### 6.4 Multi-tenant from day 1

**Decision** — the data model assumes "user owns multiple profiles" from migration 001. There's no retail-only mode that gets bolted onto MFD later.

**Why** — MFDs are 50% of the value capture. Bolting multi-tenant onto a single-tenant app breaks every assumption (auth, billing, pages).

**Consequence** — workspace + profile + impersonation are first-class. The Advisor Home is not a separate app; it's a different page in the same app, gated by `workspace.role`.

### 6.5 Macro-aware by default

**Decision** — every position-size recommendation is multiplied by the current macro multiplier (1.0× / 0.9× / 0.8×) without the user having to think about it.

**Why** — the same RSI 65 setup means different things in different regimes. Asking the user to mentally apply "trim sizing in volatile markets" is asking them to do the system's job.

**Consequence** — the macro layer is not a nice-to-have widget. It's wired into the trade-planner output.

### 6.6 Real-time where it matters, batch where it doesn't

**Decision** — long-term scoring is overnight batch (cheap, stable). Positional triggers are real-time webhook (fresh, expensive). Live LTP is poll-on-demand only when market is open.

**Why** — you don't need real-time fund metadata. You do need real-time scan triggers. Mixing the two means paying the cost of the highest-cadence path on every code path.

**Consequence** — fund scoring runs on a 24h cadence, costs ~₹0.1/user/month in compute. Positional webhooks land in <1s and cost nothing per event.

### 6.7 Time-Machine, not a single state

**Decision** — every CAS upload becomes a frozen snapshot. Reads default to "latest", but historical snapshots are queryable.

**Why** — "what was my portfolio worth on 31-Mar-2024" is a real question, especially around tax filing season. Versioning every state means you never lose history.

**Consequence** — Mongo collections are append-only on snapshot writes. Storage cost is a few KB/snapshot/month — negligible. Capability is permanent.

---

## 7 · Why Nivesh is unique

### 7.1 vs. retail aggregators (INDmoney, Vested, Coin)

| | Aggregators | Nivesh |
|---|---|---|
| CAS upload | ✅ | ✅ |
| V3 fund scoring with shown math | ❌ | ✅ |
| Per-holding decision card with cost + tax | ❌ | ✅ |
| Switch cost framework | ❌ | ✅ |
| Action plan generation | ❌ | ✅ |
| Macro overlay | ❌ | ✅ |
| Positional engine | ❌ | ✅ |
| MFD multi-client mode | ❌ | ✅ |
| Explainable, auditable analytics | ❌ | ✅ |

Aggregators show *what you have*. Nivesh shows *what to do about it*.

### 7.2 vs. ChatGPT-with-portfolio bots

| | LLM bots | Nivesh |
|---|---|---|
| Conversational | ✅ | ✅ (Copilot drawer) |
| Reads CAS | partial / hallucinates | ✅ deterministic |
| Numbers in answers are accurate | ❌ — frequently hallucinates | ✅ — analytics layer never lies |
| Auditable | ❌ | ✅ |
| Real-time market data | ❌ | ✅ |
| MFD compliance-grade | ❌ | ✅ |

Nivesh's Copilot is grounded on *the user's actual data*. The LLM cannot invent a holding, a NAV, or a recommendation — only narrate ones the deterministic layer has produced.

### 7.3 vs. screeners (TickerTape, Screener.in, Chartink)

| | Screeners | Nivesh |
|---|---|---|
| Fundamental data lookup | ✅ | ✅ |
| Custom scans | ✅ | ✅ (via Chartink integration) |
| Portfolio context | ❌ | ✅ |
| Per-holding action plan | ❌ | ✅ |
| Macro regime overlay | ❌ | ✅ |
| Real-time webhook integration | ❌ | ✅ |
| Tax-aware decisions | ❌ | ✅ |

Screeners give you a list. Nivesh gives you a *ranked, regime-aware, tax-aware, executable* list.

### 7.4 vs. MFD CRMs (Wealthy, Smallcase Manager, Nirmal Bang)

| | MFD CRMs | Nivesh |
|---|---|---|
| Client book management | ✅ | ✅ (Advisor Home) |
| Bulk client report generation | ✅ | ✅ |
| Built-in advisory engine | ❌ — you bring your own analysis | ✅ — V3 + Action Plan |
| Per-client proactive insights | ❌ | ✅ — 4 cards always-fresh |
| LLM Copilot per client | ❌ | ✅ |
| One-click client impersonation | partial | ✅ |
| SEBI-compliant reasoning trail | partial | ✅ — every recommendation has audit-logged inputs |

MFD CRMs are workflow tools. Nivesh is an advisory engine *and* a workflow tool.

### 7.5 The single sentence that summarises the moat

**Nivesh is the only Indian-context, deterministic, explainable, real-time advisory engine that ships with a built-in MFD multi-tenant layer and a trader-grade positional overlay — with every number on screen reproducible from a public formula, and every recommendation traceable to a logged rule.**

The combination is the product. Any one of those properties — Indian-context, deterministic, real-time, MFD-native, positional-aware, explainable — is somewhere in the market. None of them are together.

---

## 8 · What "good" looks like — outcomes

### 8.1 For the retail investor

- **Time-to-clarity** — from "I have 14 funds and don't know what I'm doing" to "here are the 3 actions to take, ranked, with cost and tax shown" in **<10 minutes**
- **Quantified switch decisions** — "the math says SWITCH because the 0.9% expense saving exceeds the 0.4% tax drag over my horizon"
- **Macro discipline** — automatic position-size scaling without the user having to remember to do it
- **Compounding** — over a 5-year hold, the Direct-vs-Regular savings + better fund selection + lower tax drag adds up to 1–2% p.a. — on a ₹50L corpus that's ₹50k–₹1L per year

### 8.2 For the MFD advisor

- **Client capacity uplift** — from 200 clients (the Excel ceiling) to 2,000+ (the Nivesh ceiling) without adding headcount
- **Defensible recommendations** — every action card has a logged reason; SEBI audit becomes "show me your rules table"
- **Proactive client outreach** — Advisor Home surfaces "5 clients lagging Nifty by 8pp" before the client calls *you*
- **Plan generation in seconds** — what used to take 30 min/client in Excel is now a one-click `POST /api/plans/generate`

### 8.3 For the trader

- **Single ranked picks list** instead of 12 screener tabs
- **Macro-aware sizing** — automatically smaller positions in HIGH-risk regimes
- **Real-time triggers** via Chartink webhook — alert fires → pick lands in your panel within seconds
- **Live readiness chips** — at a glance, "is this thing actionable right now?" without staring at a separate ticker

### 8.4 For the platform itself (the meta-outcome)

- **Compliance posture** — DPDP-clean, SEBI-defensible, audit-logged
- **Cost** — ~₹0.1/user/month at the scoring layer, ~₹0/event for webhook signals; LLM cost only on Copilot use
- **Maintainability** — rules/thresholds editable in admin UI without deploy; the engine doesn't care which threshold you tune

---

## 9 · Roadmap — what's next

The current system covers the loop **"data → score → decide → act"** for the retail and MFD personas, plus a v1 trader overlay. The roadmap focuses on **hardening the data backbone** (the NIDP — Nivesh Intelligence Data Platform — initiative) and **deepening the trader surface**.

### 9.1 NIDP — sequenced

1. **Snapshot Engine** *(highest priority)* — `stock_daily_snapshot` materialised view that gives every consumer one frozen as-of row instead of joining 5 tables. Eliminates "mixed timelines" risk.
2. **Data validation framework** — assert on every ingest (row counts, null patterns, value ranges); reject before insert; log to `validation_log`
3. **Observability dashboard** — Prometheus-style metrics + Grafana surface; alerts on freshness > 24h
4. **Failure classification** — typed errors (NSE_DOWN, PARSER_FAIL, DATA_MISMATCH) instead of single fail bucket
5. **NSE hardening** — rotating user agents, retry windows on 403/503, optional proxy rotation
6. **FII/DII flow ingester** — daily NSE archive
7. **Shareholding poller** — quarterly corporate filings with promoter pledge change detection
8. **Bulk/block deals ingester** — daily
9. **Corporate actions feed** — event-driven
10. **StockEdge cross-check** — field-level diff with tolerance bands

### 9.2 Trader surface deepening

- Playbook header (Bias / Aggression / Max Trades / Focus / Avoid as a sticky strip)
- Hero / Secondary / Watchlist priority layout
- Per-pick distance-to-trigger / execution rules / position size
- Mini sparklines (last 20 days) per pick
- Portfolio Impact view ("If you take all trades: total exposure 80%, sector concentration banking 40%")
- Day-over-day diff ("INDUSINDBK upgraded · RELIANCE unchanged")
- Outcome tracker — every signal evaluated 5/10/20 days later → learning loop into the scorer weights

### 9.3 Equity decision engine (parked feature unlock)

The V3 stock scoring infrastructure already exists; the action verb is currently parked. Next step is the equity decision engine — same 5-bucket taxonomy as funds (STAY / SWITCH / EXIT / TRIM / ADD) plus a peer-stock hydrator.

### 9.4 Compliance + audit deepening

- Audit log viewer in admin panel (data exists; UI surface is pending)
- Automated data retention sweeps (delete CAS PDFs after N days)
- DPO alerting on suspicious access patterns

### 9.5 Distribution

- Embedded mode for MFD partners — Nivesh as a white-labelled iframe inside an existing MFD CRM
- Public Copilot route (logged-out users can ask non-portfolio questions to evaluate the product)
- Mobile app (currently mobile-responsive web only)

---

## 10 · Glossary (Indian context terms)

For non-Indian-market readers.

- **CAS** — Consolidated Account Statement. A PDF summary of all your demat + MF holdings, emailed monthly by NSDL or CDSL (the two depositories).
- **NSDL / CDSL** — National Securities Depository Limited / Central Depository Services Limited. The two Indian securities depositories.
- **AMFI** — Association of Mutual Funds in India. Publishes daily NAV for every Indian MF scheme.
- **MFD** — Mutual Fund Distributor. AMFI-registered intermediary who advises clients on MF investments and earns commission.
- **SEBI** — Securities and Exchange Board of India. The market regulator.
- **DPDP** — Digital Personal Data Protection Act, 2023. India's primary data privacy regulation.
- **SIP** — Systematic Investment Plan. Recurring monthly MF purchase.
- **Direct vs Regular plan** — every Indian MF has two NAV variants. Regular plans pay an MFD commission baked into the expense ratio (~0.7–1% higher). Direct plans don't. Same scheme, different cost.
- **LTCG / STCG** — Long-Term / Short-Term Capital Gains tax. For equity MFs, LTCG kicks in after 1 year (12.5% above ₹1.25L p.a.); STCG is 20% under 1 year.
- **ELSS** — Equity Linked Savings Scheme. Tax-saving MF category with mandatory 3-year lock-in.
- **Bhavcopy** — NSE's daily OHLCV CSV file, published ~13:00 IST every trading day.
- **FII / DII** — Foreign / Domestic Institutional Investors. Their daily net buy/sell on NSE is published; widely watched as a sentiment indicator.

---

## 11 · Further reading

- **Technical detail** — `/app/README.md` (especially §13 Market Intelligence and §14 Feature inventory)
- **Iteration timeline** — `/app/memory/PRD.md`
- **V3 scoring spec** — `/app/memory/V2_SCORING_LOGIC.md` + `/app/docs/V3_CALCULATION_PRIYANKA.md`
- **Action rules spec** — `/app/memory/V2_ACTION_GENERATION_RULES_COMPLETE.md`

For business / commercial questions, see the founders' memo (separate document, not in repo).
