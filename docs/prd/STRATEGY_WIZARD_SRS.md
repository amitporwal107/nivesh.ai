# Nivesh — Strategy Wizard
## Software Requirements Specification (SRS)

| | |
|---|---|
| **Product** | Nivesh — AI-Powered India Equity Strategy Platform |
| **Module** | Strategy Wizard ("Strategy Lab" equivalent) |
| **Target segment** | Wealthy investors / High-Net-Worth Individuals (HNIs), Family Offices |
| **Document version** | 1.0 (Draft) |
| **Status** | For review |
| **Date** | 28 June 2026 |
| **Owner** | Product |

> **Note on assumptions.** This specification assumes an India-focused, SEBI-regulated equity product, delivered web-first with a companion mobile experience, with AI-assisted strategy generation and broker/custodian integration for execution. Every material assumption is flagged inline with **[ASSUMPTION]** and consolidated in Section 13. Adjust those before sign-off.

---

## 1. Introduction

### 1.1 Purpose
This document defines the functional, non-functional, data, integration, and compliance requirements for the **Nivesh Strategy Wizard** — a guided, five-step flow that lets an HNI investor go from a stock universe to a live, executed strategy in one continuous experience.

### 1.2 Product vision
Nivesh gives sophisticated individual investors institutional-grade quantitative tooling — universe construction, strategy design, screening, backtesting, and execution — wrapped in a guided wizard and augmented by an AI co-pilot, so that a wealthy investor (or their advisor) can build, validate, and deploy a rules-based portfolio without writing code.

### 1.3 Scope

**In scope (this release)**
- The five-step Strategy Wizard: Universe → Strategy → Screen → Backtest → Execute.
- AI co-pilot ("Nivesh AI") that generates screening criteria from natural-language intent and provides step-level guidance.
- Public and private (user-created) universes.
- Strategy creation from natural language and from templates.
- Rules-based screening against the chosen universe.
- Historical backtesting with performance and risk analytics.
- Order generation and execution via integrated broker/custodian.
- Subscription tiers with AI usage limits.

**Out of scope (this release)** — *[ASSUMPTION — confirm]*
- Derivatives, F&O, commodities, and currency strategies (equity cash only initially).
- Discretionary advisory / RIA recommendations (the platform provides tools, not personalised advice — see Section 10).
- International equities.
- Algorithmic intraday / high-frequency execution.

### 1.4 Target users & personas

| Persona | Description | Key needs |
|---|---|---|
| **The Self-Directed HNI** | ₹2–50 Cr+ investable equity, financially literate, wants control and transparency. | Powerful screening, backtest credibility, fast execution, large-ticket handling. |
| **The Delegating HNI** | Wealthy but time-poor; relies on AI + templates and light oversight. | Guided flow, AI co-pilot, plain-language explanations, guardrails. |
| **The Family Office / Advisor** | Manages capital for one or more wealthy clients/entities. | Multi-account context, audit trail, compliance reporting, reusable strategies. |

> **[ASSUMPTION]** The platform targets investors who self-execute through their own broker accounts (execution-only), not a discretionary PMS mandate. If Nivesh intends to operate as a PMS/RIA, Section 10 expands materially.

### 1.5 Definitions & glossary

| Term | Meaning |
|---|---|
| **Universe** | A curated set of stocks the strategy operates on (e.g., Nifty 500, a sector theme, or a user-defined list). |
| **Strategy** | A named set of screening rules + ranking + position sizing logic. |
| **Screen / Screening** | Applying strategy rules to a universe to produce a candidate stock list. |
| **Backtest** | Simulating a strategy over historical data to estimate performance and risk. |
| **Execute** | Translating a screened/sized portfolio into broker orders. |
| **Nivesh AI** | The AI co-pilot that generates rules from intent and gives contextual help. |
| **HNI** | High-Net-Worth Individual. |
| **3M Return** | Trailing 3-month return, shown as a universe momentum signal. |
| **Trend tag** | A momentum/interest descriptor on a universe (e.g., *Building / Strong / Cooling*). |

---

## 2. Overall description

### 2.1 Product context
The Strategy Wizard sits inside the broader Nivesh app alongside **Portfolio**, **Pulse** (market intelligence), and account management. A persistent top bar shows live market tickers (e.g., NIFTY FMCG, NIFTY INFRA, USD/INR), primary navigation, the user's plan/upgrade entry point, theme toggle, and account menu.

### 2.2 High-level flow
```
[Universe] ──▶ [Strategy] ──▶ [Screen] ──▶ [Backtest] ──▶ [Execute]
   Step 1        Step 2         Step 3        Step 4         Step 5
     │             │              │             │              │
     └─────────────── Nivesh AI co-pilot (context-aware per step) ──┘
```

### 2.3 Operating environment *[ASSUMPTION]*
- **Clients:** Modern desktop browsers (Chrome, Edge, Safari, Firefox — current and prior major version); responsive web for tablet; native or PWA mobile companion.
- **Backend:** Cloud-hosted, India region for data residency (see 10.3).
- **Market data:** Real-time/near-real-time NSE/BSE feeds plus historical EOD and corporate-action-adjusted data.

### 2.4 Assumptions & dependencies
See Section 13 for the consolidated list.

---

## 3. Functional Requirements — Wizard Framework

> Requirement IDs use the pattern **FR-W** (wizard shell), **FR-1..5** (steps), **FR-AI** (co-pilot), **FR-X** (cross-cutting). Priority: **M** = Must, **S** = Should, **C** = Could.

### 3.1 Wizard shell

| ID | Requirement | Priority |
|---|---|---|
| FR-W1 | The wizard SHALL present five sequential steps — Universe, Strategy, Screen, Backtest, Execute — with a persistent progress indicator showing the active step, completed steps, and remaining steps. | M |
| FR-W2 | The progress indicator SHALL display the current position (e.g., "Step 1/5 — Select Your Stock Universe") and a primary call-to-action contextual to the step (e.g., "Pick a universe", "Pick a strategy"). | M |
| FR-W3 | The wizard SHALL provide **Back** and **Next/primary-CTA** navigation. The primary CTA SHALL be disabled until the step's minimum completion criteria are met. | M |
| FR-W4 | The wizard SHALL **persist in-progress state** (selected universe, draft strategy, screen results) so a user can leave and resume without losing work. | M |
| FR-W5 | A user SHALL be able to **revisit any completed prior step** to change a selection; the system SHALL flag downstream steps as "needs re-run" when an upstream change invalidates them. | M |
| FR-W6 | The wizard SHALL support **saving a draft strategy run** and naming it for later reuse. | S |
| FR-W7 | The system SHALL support **light and dark themes** via the global theme toggle, persisted per user. | S |
| FR-W8 | All steps SHALL surface the **Nivesh AI** panel, scoped to the current step's context. | M |
| FR-W9 | The wizard SHALL be fully usable **without** AI (manual path) so AI limits never hard-block a user from completing a run. | M |

---

## 4. Step 1 — Universe Selection

**Goal:** Let the user choose or create the set of stocks the strategy will run against.

### 4.1 Browse & discover

| ID | Requirement | Priority |
|---|---|---|
| FR-1.1 | The system SHALL offer two universe sources via a toggle: **Public Universes** (curated by Nivesh) and **My Universes** (user-created), each showing a count. | M |
| FR-1.2 | Each universe SHALL be displayed as a card showing: name, category icon, a **trailing 3-month return**, a **trend tag** (e.g., *Building / Strong / Cooling*) and an interest descriptor (e.g., *Warming up / High interest*). | M |
| FR-1.3 | The system SHALL provide a **search box** to find universes by name/keyword. | M |
| FR-1.4 | The system SHALL provide **filter chips** by type — *Broad Market*, *Sector Themes* — and by **trend** — *All Trends, Hot, Warming, Cooling* — combinable with search. | M |
| FR-1.5 | Universe cards SHALL include a short description (e.g., "Top 10 stocks by market cap in key EV related sectors"). | M |
| FR-1.6 | Selecting a universe SHALL trigger the **Nivesh AI** panel to populate step-specific insights ("Select a universe to get insights" → insights on selection). | S |
| FR-1.7 | The system SHALL display **broad-market universes** (e.g., Nifty 200, Nifty 500), **thematic/sector universes** (e.g., Infra, Green Energy, EV, Dividend), and SHALL be extensible to new universes without a client release. | M |

### 4.2 Create a universe

| ID | Requirement | Priority |
|---|---|---|
| FR-1.8 | The user SHALL be able to **Create Universe** — a private, named set of stocks. | M |
| FR-1.9 | Universe creation SHALL support: manual stock selection (search & add), upload of a ticker list (CSV), and rule-based definition (e.g., market cap > X, sector = Y). | S |
| FR-1.10 | For HNIs, the system SHALL support **importing existing holdings** (from broker/CAS) as a universe, so strategies can be run against the current portfolio. | S |
| FR-1.11 | The system SHALL enforce a **maximum universe size** per plan tier and warn before exceeding it. | S |

### 4.3 Acceptance criteria (Step 1)
- A user can find, filter, and select a public universe in under three interactions.
- A created private universe persists under **My Universes** and is selectable in a later run.
- The chosen universe carries forward to Step 2 and is visible throughout the wizard.

---

## 5. Step 2 — Strategy

**Goal:** Define the rules that pick and rank stocks within the universe — via AI from plain language, or via templates/manual rules.

### 5.1 AI-assisted strategy creation

| ID | Requirement | Priority |
|---|---|---|
| FR-2.1 | The system SHALL provide a **"Create Private Strategy"** flow where the user describes screening criteria in natural language and the AI builds structured rules from it. | M |
| FR-2.2 | The input SHALL accept free text (e.g., *"Deep value — low P/E, high dividend yield, strong balance sheet"*) with helper guidance naming supported factor families (valuation, quality, momentum, earnings, technicals). | M |
| FR-2.3 | The system SHALL offer **inspiration presets** as one-tap starting points, e.g.: *Momentum (RS > 80, near 52-week high)*, *Deep value*, *Quality growth (high ROE, revenue CAGR > 20%, debt-free)*, *Contrarian (beaten down 40%+ but fundamentally strong)*, *Low volatility (beta < 0.8, stable EPS)*, *Magic Formula (rank by ROCE and earnings yield)*. | M |
| FR-2.4 | On **Build Strategy**, the AI SHALL return a structured, **editable** rule set (factors, operators, thresholds, ranking, weights) — not an opaque black box. | M |
| FR-2.5 | When the **AI request limit is reached**, the system SHALL show a clear, non-blocking message (e.g., *"Could not generate strategy — AI request limit reached"*) and SHALL offer alternatives: use a template, build rules manually, or upgrade plan. | M |
| FR-2.6 | The user SHALL be able to **manually add, edit, reorder, and remove rules** regardless of how the strategy was created. | M |

### 5.2 Strategy library & management

| ID | Requirement | Priority |
|---|---|---|
| FR-2.7 | The system SHALL provide a library of **public strategy templates** plus the user's **saved private strategies**. | M |
| FR-2.8 | Strategies SHALL be **named, saved, versioned, duplicable, and deletable**. | S |
| FR-2.9 | A strategy SHALL define: (a) screening filters, (b) a ranking/scoring method, (c) selection count (top-N), and (d) position-sizing/weighting scheme (equal-weight, score-weighted, market-cap-weighted, custom). | M |
| FR-2.10 | For HNIs/family offices, strategies SHALL be **shareable** across the user's own linked accounts/entities (with permission controls). | C |

### 5.3 Acceptance criteria (Step 2)
- A plain-language description produces an editable, transparent rule set.
- AI limit errors never dead-end the user; a manual/template path is always available.
- A saved strategy is reusable in a future wizard run.

---

## 6. Step 3 — Screen

**Goal:** Apply the strategy to the universe and produce the ranked candidate list.

| ID | Requirement | Priority |
|---|---|---|
| FR-3.1 | The system SHALL run the selected strategy against the selected universe and return a **ranked candidate list** with the score and contributing factor values per stock. | M |
| FR-3.2 | Results SHALL be **sortable and filterable** by any displayed column (score, P/E, ROE, momentum, etc.). | M |
| FR-3.3 | The system SHALL show **how many of the universe passed each rule** (a funnel), so the user understands which filters are binding. | S |
| FR-3.4 | The user SHALL be able to **tune thresholds inline** and re-screen without leaving the step. | M |
| FR-3.5 | The user SHALL be able to **manually include/exclude** specific stocks from the candidate list, with the reason captured for the audit trail. | S |
| FR-3.6 | The system SHALL display **data freshness/as-of timestamp** and flag any stocks with stale or missing data. | M |
| FR-3.7 | The screen output SHALL be **exportable** (CSV/Excel) and the candidate list SHALL carry forward to Backtest and Execute. | S |
| FR-3.8 | Nivesh AI SHALL be able to **explain the result** in plain language ("Why did stock X rank #1?") on request. | S |

### 6.1 Acceptance criteria (Step 3)
- Screen returns a deterministic, reproducible ranked list for a given strategy + universe + as-of date.
- Threshold edits re-screen in near-real-time.

---

## 7. Step 4 — Backtest

**Goal:** Validate the strategy historically before risking capital — critical for HNI trust.

| ID | Requirement | Priority |
|---|---|---|
| FR-4.1 | The user SHALL configure a backtest with: **date range, rebalance frequency** (e.g., monthly/quarterly), **initial capital, position sizing**, and **costs** (brokerage, STT, slippage). | M |
| FR-4.2 | The system SHALL compute and display **performance metrics**: total return, CAGR, vs. benchmark (e.g., Nifty 500), alpha/beta. | M |
| FR-4.3 | The system SHALL compute and display **risk metrics**: max drawdown, volatility, Sharpe, Sortino, win rate, turnover. | M |
| FR-4.4 | The system SHALL render an **equity curve** vs. benchmark, a **drawdown chart**, and a **periodic returns** view. | M |
| FR-4.5 | The backtest SHALL use **point-in-time, survivorship-bias-free, corporate-action-adjusted** data, and SHALL state this and its limitations to the user. | M |
| FR-4.6 | The system SHALL display a **trade log / holdings over time** for transparency and export. | S |
| FR-4.7 | The user SHALL be able to **compare multiple strategy variants** side by side. | C |
| FR-4.8 | The system SHALL display a **prominent disclaimer** that past performance does not guarantee future results (see 10.2). | M |
| FR-4.9 | Backtests SHALL be **saved with the run** so results are auditable and reproducible. | S |

### 7.1 Acceptance criteria (Step 4)
- A backtest produces consistent metrics for identical inputs.
- Costs and rebalancing are explicitly modelled and disclosed.
- Required risk disclaimers are always shown.

---

## 8. Step 5 — Execute

**Goal:** Turn the validated, sized portfolio into broker orders — with HNI-grade controls.

| ID | Requirement | Priority |
|---|---|---|
| FR-5.1 | The system SHALL generate an **order basket** (buy/sell, quantity, target weights) from the screened, sized portfolio, reconciled against the user's current holdings (rebalance vs. fresh deploy). | M |
| FR-5.2 | The user SHALL **review and approve** every order set before submission (no auto-execution without explicit consent). | M |
| FR-5.3 | The system SHALL integrate with **at least one supported broker/custodian** to place orders, via the broker's authenticated API/order-routing. *[ASSUMPTION — broker list TBD]* | M |
| FR-5.4 | The system SHALL support **large-ticket handling for HNIs**: order slicing, impact-cost warnings, liquidity checks (avg. daily volume), and limit/market/iceberg order types where the broker supports them. | S |
| FR-5.5 | The system SHALL show a **pre-trade summary**: estimated cost, charges/taxes, cash required, resulting allocation. | M |
| FR-5.6 | The system SHALL display **order status** (placed/partial/filled/rejected) and a post-trade confirmation. | M |
| FR-5.7 | Executed strategies SHALL be **tracked in Portfolio** with ongoing performance vs. the backtested expectation. | S |
| FR-5.8 | The system SHALL support **rebalance reminders/alerts** on the strategy's chosen frequency. | S |
| FR-5.9 | Every execution SHALL be written to an **immutable audit log** (who, what, when, approval, order IDs). | M |
| FR-5.10 | For family offices, the system SHALL allow **executing the same strategy across multiple linked accounts/entities** with per-account review. | C |

### 8.1 Acceptance criteria (Step 5)
- No order leaves the system without explicit user approval.
- Pre-trade costs/taxes are shown and reconcile with broker confirmations.
- Every executed action is auditable.

---

## 9. Nivesh AI Co-Pilot (cross-cutting)

| ID | Requirement | Priority |
|---|---|---|
| FR-AI1 | A **context-aware AI panel** SHALL be available on every step ("Ask about this step…") and SHALL adapt its guidance to the current step and selections. | M |
| FR-AI2 | The AI SHALL generate **structured, editable strategy rules** from natural language (see FR-2.x). | M |
| FR-AI3 | The AI SHALL **explain results** (universe trends, screen rankings, backtest outcomes) in plain language. | S |
| FR-AI4 | AI usage SHALL be **metered per plan** with a visible counter (e.g., "100/100"), graceful limit messaging, and an upgrade path. | M |
| FR-AI5 | AI outputs that influence investment decisions SHALL carry a **"not investment advice"** disclaimer and SHALL be reproducible/traceable for audit. | M |
| FR-AI6 | The AI SHALL **never auto-place orders**; it may only prepare baskets for human approval. | M |
| FR-AI7 | AI prompts and outputs SHALL be **logged** (subject to privacy rules) for quality and compliance review. | S |

> **[ASSUMPTION]** Nivesh AI is an information/automation tool, not a SEBI-registered advisor. If it makes personalised recommendations, RIA registration and suitability obligations apply (Section 10).

---

## 10. Compliance, Regulatory & Risk

### 10.1 Onboarding & identity

| ID | Requirement | Priority |
|---|---|---|
| FR-C1 | The system SHALL enforce **KYC** before any execution capability is enabled, integrating with KRA/CKYC. *[ASSUMPTION — India]* | M |
| FR-C2 | The system SHALL apply **AML / sanctions screening** appropriate to HNI/family-office onboarding. | M |
| FR-C3 | The system SHALL capture and store **investor risk profile / consent** records. | M |

### 10.2 Disclosures
| FR-C4 | All performance, backtest, and AI outputs SHALL display required risk disclosures and the past-performance disclaimer. | M |
| FR-C5 | The system SHALL clearly state whether it provides **execution-only tooling** vs. advice, and SHALL not blur the line. | M |

### 10.3 Data protection
| FR-C6 | The system SHALL comply with India's **DPDP Act** (and applicable financial-data regulations): consent, purpose limitation, data residency, breach notification. | M |
| FR-C7 | Personal, holdings, and trading data SHALL be **encrypted at rest and in transit**. | M |
| FR-C8 | The system SHALL maintain **complete, tamper-evident audit trails** for strategy runs and executions for the statutory retention period. | M |

> **Action required:** Confirm Nivesh's regulatory posture (execution-only platform / RIA / PMS / broker tie-up). This determines registration, suitability, fee disclosure, and segregation-of-duties requirements, and may add steps to the Execute flow.

---

## 11. Non-Functional Requirements

### 11.1 Performance & scalability
| ID | Requirement | Priority |
|---|---|---|
| NFR-1 | Screening against a 500-stock universe SHALL return results in **≤ 3 seconds** (p95). | M |
| NFR-2 | A standard backtest (5-year, monthly rebalance, 500-stock universe) SHALL complete in **≤ 15 seconds** (p95); long jobs SHALL run async with progress + notification. | S |
| NFR-3 | The platform SHALL support concurrent backtests without degrading interactive steps. | M |

### 11.2 Availability & reliability
| NFR-4 | Target **99.9% uptime** during NSE/BSE market hours. | M |
| NFR-5 | Order-execution paths SHALL fail safe — never submit duplicate or partial-unintended orders on retry. | M |

### 11.3 Security
| NFR-6 | **Multi-factor authentication** SHALL be required; HNI accounts SHALL support hardware/biometric MFA. | M |
| NFR-7 | **Role-based access control** for family-office/advisor multi-account contexts; least-privilege by default. | M |
| NFR-8 | Broker credentials/tokens SHALL be stored in a **secrets vault**; OAuth/token-based linking preferred over storing passwords. | M |
| NFR-9 | Independent **security testing / pen-test** before each major release. | S |

### 11.4 Usability & accessibility
| NFR-10 | The wizard SHALL be operable by a non-technical HNI; primary path completable without documentation. | M |
| NFR-11 | The UI SHALL meet **WCAG 2.1 AA**. | S |
| NFR-12 | The UI SHALL be responsive (desktop-first, usable on tablet/mobile) and support light/dark themes. | S |

### 11.5 Observability
| NFR-13 | All wizard steps, AI calls, and order events SHALL emit structured logs and metrics for monitoring and audit. | M |

---

## 12. Data, Integrations & Supporting Features

### 12.1 Data requirements
| ID | Requirement | Priority |
|---|---|---|
| FR-D1 | **Live/near-live quotes** for NSE/BSE equities and index tickers (e.g., NIFTY FMCG, NIFTY INFRA), plus **USD/INR**. | M |
| FR-D2 | **Historical EOD prices**, point-in-time and corporate-action-adjusted, for backtesting. | M |
| FR-D3 | **Fundamentals** (P/E, ROE, ROCE, dividend yield, debt, revenue/earnings growth, market cap) at sufficient history for the supported factors. | M |
| FR-D4 | **Technical/derived signals** (RS, 52-week high/low, beta, volatility) computed and refreshed on schedule. | M |
| FR-D5 | Universe **3M return and trend tags** computed and refreshed regularly. | M |

### 12.2 Integrations
- **Market data vendor(s)** — real-time + historical (e.g., exchange feed / licensed vendor). *[ASSUMPTION — vendor TBD]*
- **Broker/custodian APIs** — order placement, holdings, funds. *[ASSUMPTION — broker list TBD]*
- **KYC/AML providers** — KRA/CKYC, sanctions screening.
- **Notification channels** — email, push, SMS/WhatsApp for alerts and order status. *[ASSUMPTION]*

### 12.3 Supporting product features (referenced, specified separately)
| ID | Requirement | Priority |
|---|---|---|
| FR-X1 | A persistent **market ticker bar** (key indices + USD/INR) with live values and % change. | M |
| FR-X2 | A **Portfolio** module tracking holdings and live/deployed strategies. | M |
| FR-X3 | A **Pulse** market-intelligence module (news/trends/insights). | S |
| FR-X4 | **Subscription tiers** with an upgrade entry point; AI request limits and feature gating per tier. | M |

---

## 13. Assumptions, Dependencies & Open Questions

**Assumptions**
1. India equity cash segment only for v1; F&O/commodities/global out of scope.
2. Execution-only platform (user trades through their own broker accounts), not PMS/RIA discretionary management.
3. Web-first with responsive/mobile companion.
4. Nivesh AI is an automation/information tool, not a registered advisor.
5. India data residency and DPDP applicability.

**Open questions (need product/legal/commercial decisions)**
- What is Nivesh's exact **regulatory registration** (execution-only / broker partner / RIA / PMS)? This is the single biggest scope driver.
- Which **broker(s)/custodian(s)** for execution, and what order types do they expose?
- Which **market-data vendor(s)** and what's the licensing for redistribution of fundamentals/derived signals?
- What are the **plan tiers** and the AI-usage limits per tier?
- Are **family-office multi-account** and **shared strategies** in v1 or a later release?
- Notification channels in scope (WhatsApp/SMS regulatory constraints)?

**Dependencies**
- Availability of point-in-time, survivorship-free historical data for credible backtests.
- Broker API stability and rate limits.
- Legal sign-off on disclosures and the advice/execution boundary.

---

## 14. Success Metrics (suggested)

| Metric | Target |
|---|---|
| Wizard completion rate (Universe → Execute) | > 40% of started runs *[set baseline]* |
| Median time to first executed strategy | < 20 minutes |
| AI-generated strategies that user edits & keeps | > 60% |
| Backtest-to-execute conversion | > 25% |
| HNI 90-day retention | *[set target]* |

---

## 15. Future Enhancements (roadmap candidates)
- Multi-factor optimisation and risk-parity sizing.
- Portfolio-level constraints (sector caps, single-stock caps, ESG screens).
- Walk-forward and Monte Carlo robustness testing.
- Tax-aware rebalancing and harvesting (relevant for HNIs).
- Family-office consolidated reporting across entities.
- Derivatives overlays and hedging strategies.
- Goal-based and SIP-style automated deployment.

---

*End of specification — v1.0 Draft. Resolve the open questions in Section 13 (especially regulatory posture, broker, and data vendor) before development sign-off.*
