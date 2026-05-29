# Gap Analysis: Nivesh v4 Designs vs Existing APIs

**Date**: 2026-05-24
**Agent/Reviewer**: Claude (Phase 1 synthesis per AGENT_BRIEF.md)
**Sources reviewed**:
- `docs/v4-designs/Nivesh_PRD.docx` (v1.0, May 2026) + `PRD.pdf`
- `docs/v4-designs/webapp/*` (17 SVG mockups, OCR'd)
- `docs/v4-designs/mobile/*` (17 SVG mockups, OCR'd)
- `docs/v4-designs/nivesh_app.html` + `nivesh_mobile.html` (HTML prototypes — authoritative field-binding source)
- `docs/v4-designs/nivesh-postman-collection.json` (449 endpoints)
- `docs/v4-designs/nidp-postman-collection.json` (127 endpoints)

---

## Section A — Source Inventory

### A.1 PRD Summary

**Product one-liner** (PRD §1):
> Nivesh tells an investor — in plain words — exactly how healthy their portfolio is, and what to do next; and gives their advisor the same truth, scaled across an entire book.

**v4 scope** (PRD §13.1 phasing):
- **Phase 1**: Onboarding, CAS import, Wave-1 insights, health score, chat landing
- **Phase 2**: Wave-2 insights, all six dashboards, action matrices, Plan Board
- **Phase 3**: Wave-3 insights, portfolio builder, instrument sizing, SIP planner
- **Phase 4**: Advisor book, Client 360, SIP Board

**Out of scope (v1, per PRD §2.4)**:
- Trade execution / order placement (Nivesh is diagnostic + advisory, not a broker)
- Asset / money custody
- Auto-rebalance — every change is human-accepted
- Per PRD §13.2: stock-level recommendations may require SEBI **RA registration** (higher bar than RIA) — compliance review needed before stock recs ship
- Per PRD §13.2: advisor tier structure (senior/branch roll-up) deferred — changes data model to client → RM → branch

**PRD vs PDF reconciliation**: The .docx and .pdf were treated as the same source per the PRD's own preamble ("Companion deliverable: nivesh_app.html"). The PRD's content extracted from docx without table-style errors (1294 lines including 19 tables). Both should be considered canonical; no divergence detected in the extracted content. **Per the brief, docx wins any future conflict.**

### A.2 Key Domain Concepts Confirmed from PRD

| Concept | Definition | PRD section |
|---|---|---|
| **Health Score** | One number, 0–100, with a letter grade. *"The score a client sees in their chat is the identical score the advisor sees on their book. If these ever diverged, trust would break."* Produced by the Health-score engine — one of three shared engines. | §4.3 (Table 5), §11.4 |
| **Recommendation** | Ranked action with: priority badge (Critical / Optimise / Enhance, or for Goals: Closes-the-gap / Closes-most / Partial), impact / effort / trade-off triplet (trade-off field is **mandatory**), Accept / Why? / Skip controls. Where an action moves an instrument, the row expands into a two-layer view (category → exact exit + exact entry + 2 alternatives). | §7.4 |
| **Insight Card** | Reusable card surfacing one of 20 deterministic diagnostic findings. Carries: severity badge (HIGH/MEDIUM/LOW), headline finding with the actual triggering number, two stat tiles, a mini-visual, two chips (left → dashboard, right → follow-up Q). | §6.2 |
| **Plan Board** | The one screen belonging to no single dashboard. Cross-cutting tracker where every action accepted across all 6 dashboards collects, gets worked, and gets marked done. Status spine: To-do / Done / Skipped. Two scores: current projected health and target. Source memory: every action remembers its origin dashboard. | §8 |
| **NIDP** | "Nivesh Investment Data Platform" — the holdings data layer. *"All three engines operate on NIDP. The grounding discipline is absolute: every figure shown to a user traces to NIDP data, and none is invented."* | §4.3, §11.4 |
| **The Three Engines** | (1) Health-score engine — produces the 0–100 score. (2) Rule engine — evaluates the 20 diagnostic signals as deterministic rules and ranks findings by severity. (3) Screening engine — scores every stock and fund on fundamentals + technicals; single source for instrument recommendations. | §4.3 |
| **Twenty Insights** | Library of 20 deterministic checks organised in 3 waves by data dependency: Wave 1 = holdings math only (concentration, too many funds, weak diversification, excess cash, drift); Wave 2 = holdings + market data (smallcap, volatility, downside, expense ratios, international, thematic, return efficiency); Wave 3 = holdings + user input (retirement, inflation, emergency fund, tax, quality, governance, emotional mismatch, recession). | §6.1, §6.3 |
| **Action Matrix** | The recommendation matrix is the heart of every dashboard. Stock verbs: Add / Exit / Trim / Hold. Fund verbs: Switch / Exit / Add / Merge / Hold. | §7.4 |
| **Additive vs Exclusive Actions** | Most dashboards: accepted actions are additive (3 trims → all 3 apply, impacts sum). Goals dashboard is the deliberate exception — actions are mutually exclusive paths (raise SIP / extend timeline each independently re-solves the funding equation, so accepting one clears the others). Matrix component carries an `exclusive` flag per row. | §7.4 |
| **Multi-lens Switcher** | Concentration and Diversification carry a lens switcher reading off one shared look-through computation. Concentration lenses: stock, sector, AMC, company, promoter group. Diversification lenses: fund overlap, repeated stocks, category, asset mix. Each lens has its own caution line. | §7.3 |
| **Score-weight + Caps + Snap** | Builder's instrument-level sizing: (1) Score-weight sleeve in proportion to each instrument's blended score from the screening engine. (2) Apply per-instrument caps (~10–12% single stocks, ~25–35% funds). (3) Snap to ₹500 multiples; residue absorbed so sleeve total is conserved exactly. | §9.3 |
| **Drift Guardrail** | Builder's editable allocation: a drift guardrail computes deviation from the assessed risk profile and labels green / amber / red. *"The guardrail never blocks an override — it makes the deviation visible."* | §9.2 |
| **Funding Check** | SIP planner runs standard future-value projection per goal and reports honestly whether the plan reaches the target. *"It will show red when the math does not work."* | §9.4 |
| **Persona A — Investor** | Indian retail investor, 28–50, salaried or self-employed, holds MFs and often direct stocks, holdings accumulated not designed. Success metric: opens Nivesh, understands score in 30 seconds, accepts 1–2 actions with confidence. | §3.1 (Table 2) |
| **Persona B — Advisor / RM** | SEBI-registered advisor or RM managing 20–200 client portfolios. Walks in to a triaged "Needs attention" list each day. Advisor product is the client product *inverted* — same engine, re-aggregated. Advisor-side actions read **Discuss**, not Accept. | §3.2 (Table 3), §10 |

### A.3 Screen Inventory

| # | Screen | Persona | Group | Mobile? | Web? | HTML section ID |
|---|---|---|---|---|---|---|
| 01 | Homepage | Public | Marketing | ✓ | ✓ | `s-home` |
| 02 | Login | Public | Auth | ✓ | ✓ | `s-login` |
| 03 | Onboarding | Investor | Onboarding | ✓ | ✓ | `s-onboard` |
| 04 | Chat Landing | Investor | Chat | ✓ | ✓ | `s-landing` |
| 05 | Concentration Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_conc` |
| 06 | Diversification Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_div` |
| 07 | Risk Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_risk` |
| 08 | Performance Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_perf` |
| 09 | Goals Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_goals` |
| 10 | Tax Dashboard | Investor | Dashboard | ✓ | ✓ | `s-d_tax` |
| 11 | Plan Board | Investor | Plan | ✓ | ✓ | `s-plan` |
| 12 | Portfolio Builder | Investor | Builder | ✓ | ✓ | `s-builder` |
| 13 | Recommendations | Investor | Builder | ✓ | ✓ | `s-recs` |
| 14 | Instrument Allocation | Investor | Builder | ✓ | ✓ | `s-alloc` |
| 15 | Advisor Book | Advisor | Advisor | ✓ | ✓ | `s-adv_book` |
| 16 | Client 360 | Advisor | Advisor | ✓ | ✓ | `s-adv_360` |
| 17 | SIP Board | Advisor | Advisor | ✓ | ✓ | `s-adv_sip` |

### A.4 API Inventory

**nivesh-postman-collection.json** — 449 endpoints across 35 groups.

Top user-facing groups relevant to v4 screens (admin/devops endpoints excluded):

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/auth/google` | Google OAuth exchange → session cookie | Public |
| GET | `/api/auth/me` | Current user identity | Session |
| POST | `/api/auth/logout` | Clear session | Session |
| GET | `/api/onboarding/state` | Onboarding step + holdings count | Session |
| POST | `/api/onboarding/gmail/auto-import` | Auto-import CAS from Gmail (OAuth) | Session |
| POST | `/api/onboarding/upload-cas` | CAS PDF upload + parse | Session |
| POST | `/api/onboarding/pan` | Persist PAN (encrypted) | Session |
| POST | `/api/portfolio/upload` | Generic CAS / CSV / Excel upload | Session |
| POST | `/api/portfolio/upload-raw` | Large / password-protected CAS upload | Session |
| GET | `/api/portfolio/upload-status/{task_id}` | Poll async CAS parse | Session |
| GET | `/api/portfolio/holdings` | Raw user holdings | Session |
| GET | `/api/portfolio/holdings-enriched` | Holdings + xirr + classifications | Session |
| GET | `/api/portfolio/cas-snapshots` | List CAS snapshots (no holdings) | Session |
| GET | `/api/portfolio/cas-snapshot` | Full snapshot (with holdings) | Session |
| GET | `/api/portfolio/cas-performance` | XIRR + return series over time | Session |
| GET | `/api/portfolio/sips` | Detected SIPs from CAS transactions | Session |
| GET | `/api/portfolio/exposure/concentration` | Sector/AMC/company/group breakdown | Session |
| GET | `/api/portfolio/exposure/fund-overlap/matrix` | Pairwise fund-overlap matrix | Session |
| GET | `/api/portfolio/risk-analytics` | beta / volatility / sharpe / drivers | Session |
| GET | `/api/portfolio/fund-performance` | 1Y returns + 1Y alpha vs peer-avg | Session |
| GET | `/api/portfolio/stock-scores` | Per-stock quality/exit/add scores | Session |
| GET | `/api/portfolio/deep-analytics` | overexposure / performance_cards / duplication | Session |
| GET | `/api/insights/v3-portfolio` | Health score 0-100 + grade (7-band) + components | Session |
| GET | `/api/insights` | List of insight findings | Session |
| GET | `/api/insights/analysis` | Detailed insight envelope | Session |
| GET | `/api/insights/{id}/optimization-plan` | Per-insight optimisation actions | Session |
| GET | `/api/intelligence/portfolio` | Portfolio intelligence rollup | Session |
| GET | `/api/intelligence/portfolio/{user_id}` | Per-user (advisor impersonation) | Session |
| GET | `/api/intelligence/v3-score/{instrument_id}` | Single instrument v3 score | **Admin only** |
| GET | `/api/plans/active` | Active plan + actions[] | Session |
| GET | `/api/plans/active/health-projection` | Plan-level health delta | Session |
| GET | `/api/plans/history` | Historical plans | Session |
| PATCH | `/api/plans/{plan_id}/actions/{action_id}` | Update action status (accept/done/skip) | Session |
| PATCH | `/api/plans/{plan_id}/actions/{action_id}/feedback` | Why? feedback | Session |
| DELETE | `/api/plans/active` | Archive current active plan | Session |
| GET | `/api/goals` | Goals list with `last_simulation` | Session |
| GET | `/api/goals/{goal_id}` | Single goal | Session |
| GET | `/api/goals/snapshot` | Financial snapshot (age/income/risk) | Session |
| GET | `/api/goals/fund-shortlist/{bucket}` | Goal-bucket fund picks | Session |
| POST | `/api/goals` | Create goal | Session |
| PATCH | `/api/goals/{goal_id}` | Update goal | Session |
| POST | `/api/goals/{goal_id}/simulate` | Re-run goal projection | Session |
| POST | `/api/portfolio-builder/generate` | Generate proposal from monthly_sip + lumpsum | Session |
| POST | `/api/portfolio-builder/simulate` | Simulate any allocation | Session |
| POST | `/api/portfolio-builder/export.pdf` | Builder result as PDF | Session |
| POST | `/api/copilot/ask` | Free-form chat Q&A | Session |
| POST | `/api/copilot/brief` | One-shot CIO brief | Session |
| POST | `/api/copilot/explain` | Per-insight explainer | Session |
| GET | `/api/copilot/models` / `/api/copilot/agents` | LLM model + agent metadata | Session |
| POST | `/api/copilot/agents/oneshot` | Single-turn agent call | Session |
| POST | `/api/copilot/agents/route` | Intent routing | Session |
| POST | `/api/copilot/feedback` | Thumbs up/down | Session |
| POST | `/api/copilot/widgets/portfolio_var` | 1d VaR widget | Session |
| POST | `/api/copilot/widgets/tax_harvest` | LTCG harvest candidates | Session |
| POST | `/api/copilot/widgets/tax_timing` | LTCG flip-timing opportunities | Session |
| POST | `/api/copilot/widgets/stress_test` | Crash scenario simulator | Session |
| POST | `/api/copilot/widgets/risk_suitability` | Risk vs profile comparison | Session |
| POST | `/api/copilot/widgets/sip_plan` | SIP allocation projection | Session |
| POST | `/api/copilot/widgets/rebalance_plan` | Rebalance suggestion | Session |
| POST | `/api/copilot/widgets/fund_card` / `compare_funds` / `overlap_reveal` | Fund detail widgets | Session |
| POST | `/api/copilot/widgets/holding_technicals` / `company_financials` | Holding detail widgets | Session |
| GET | `/api/chat/sessions` | Chat session list | Session |
| GET | `/api/chat/messages` | Messages in a session | Session |
| POST | `/api/chat/send` / `/api/chat/rag` | Send a chat message | Session |
| GET | `/api/advisor/aum` | Clients ranked by AUM + MoM | Advisor session |
| GET | `/api/advisor/today` | Top-N clients by priority score | Advisor session |
| GET | `/api/advisor/rebalance` | Clients deviating from target allocation | Advisor session |
| GET | `/api/advisor/underperformers` | Clients lagging benchmark | Advisor session |
| GET | `/api/mfd/profiles` | MFD client profiles with priority | Advisor session |
| GET | `/api/mfd/profiles/{id}` | Single profile | Advisor session |
| GET | `/api/mfd/profiles/{id}/tax-summary` | Per-client unrealized gain + harvesting | Advisor session |
| GET | `/api/mfd/profiles/{id}/portfolio-trend` | Invested vs current trend | Advisor session |
| GET | `/api/mfd/profiles/{id}/notes` | Freeform notes | Advisor session |
| PUT | `/api/mfd/profiles/{id}/notes` | Save notes + SIP context | Advisor session |
| POST | `/api/mfd/profiles/{id}/activate` | Impersonate this client | Advisor session |
| POST | `/api/mfd/profiles/deactivate` | Exit impersonation | Advisor session |
| GET | `/api/portfolio/compare` | Two-snapshot comparison | Session |
| GET | `/api/portfolio/snapshot` | Single snapshot | Session |
| GET | `/api/portfolio/snapshots` | Snapshot list | Session |
| GET | `/api/index/benchmark` | Fund category → benchmark mapping | Session |
| GET | `/api/index/latest` | Latest index snapshot | Session |
| GET | `/api/compliance/consents` | DPDP consent state | Session |
| POST | `/api/compliance/consents/{purpose}` | Grant consent | Session |
| DELETE | `/api/compliance/account` | Right to erasure | Session |
| ... | (admin/devops endpoints) | ~280 admin endpoints excluded from this table | Admin |

**nidp-postman-collection.json** — 127 endpoints across ~25 groups (NIDP Data Platform API).

| Method | Path | Purpose | Auth |
|---|---|---|---|
| GET | `/v1/intelligence/portfolio/{external_user_id}/snapshot` | Portfolio snapshot (per-user, pre-computed) | API key |
| GET | `/v1/intelligence/portfolio/{external_user_id}/holdings` | Holdings (per-user) | API key |
| GET | `/v1/intelligence/portfolio/sync/status` | Last per-user sync timestamp | API key |
| GET | `/v1/intelligence/snapshots/market` | Market brief (global) | API key |
| GET | `/v1/intelligence/features/stocks/{symbol}` | Computed features for a stock | API key |
| GET | `/v1/intelligence/events` / `/events/{id}` / `/events/search` | Corporate / market events | API key |
| GET | `/v1/intelligence/graph/correlations` | Correlation graph | API key |
| GET | `/v1/intelligence/graph/entity-links` | Entity link graph | API key |
| GET | `/v1/intelligence/reference/securities` | Master security list | API key |
| GET | `/v1/intelligence/dq/scores` | Data-quality scores | API key |
| GET | `/v1/features/stocks/{symbol}` / `.../latest` | Stock primitive features | API key |
| GET | `/v1/mf/scores/` | MF scoring outputs | API key |
| GET | `/v1/mf/performance/category/{category}` | MF category performance | API key |
| GET | `/v1/mf/amcs` | AMC list | API key |
| GET | `/v1/stocks/scores/` | Stock screening scores | API key |
| GET | `/v1/fundamentals/{symbol}` (`/v1/financials/{symbol}`) | Fundamentals payload | API key |
| GET | `/v1/prices/adjusted/{symbol}` | Split/bonus-adjusted prices | API key |
| GET | `/v1/fno/{symbol}` | F&O OI / IV | API key |
| GET | `/v1/flows/block-deals` | Block deals | API key |
| GET | `/v1/macro/fred` | FRED macro series | API key |
| GET | `/v1/announcements` / `/announcements/{id}` | NSE/BSE announcements | API key |
| GET | `/v1/corporate-actions` / `.../{symbol}` | Corporate actions | API key |
| GET | `/v1/events/calendar` / `/v1/events/{symbol}` | Event calendar / per-symbol events | API key |
| GET | `/v1/signals/latest` / `.../{symbol}` | Trading signals | API key |
| GET | `/v1/indices` | Indices list | API key |
| GET | `/v1/holidays` | Trading holidays | API key |
| GET | `/v1/snapshots/market` | Daily market snapshot | API key |
| GET | `/v1/backfill/runs` / `.../status/{id}` | Backfill orchestration | API key |
| GET | `/v1/dq/diagnostics` / `.../expectations/active` / `.../proposals` | Data quality runtime | API key |
| GET / POST | `/v1/replay/...` | Replay pipeline | API key |
| GET | `/health`, `/query/health`, `/feeds`, `/catalog`, `/certification`, `/validation`, `/archive/{ingester}` | Platform meta + ops | API key |
| GET / POST / DELETE | `/admin/keys/...` | API-key admin | Internal token |

### A.5 Interpretation of NIDP vs Nivesh split

The split is unambiguous in both the codebase and the PRD:

- **NIDP** is the upstream data platform — ingestion of market data (prices, fundamentals, F&O, macro, announcements, corporate actions), feature computation (stock primitives, MF scores), the screening / scoring engine, the intelligence graph (correlations, entity links), and per-user *pre-computed* portfolio snapshots. It is accessed via API key and is **stateless w.r.t. users** beyond the snapshot cache.
- **Nivesh** is the product API — auth, sessions, onboarding, CAS parsing, plans, goals, chat, advisor workspace, recommendation generation (action plan manager), Plan Board, Builder. It owns user state, accepts mutations (PATCH /plans/actions/{id}), and proxies NIDP for computed intelligence.

The PRD §11.4 grounding rule — *"every figure on every screen traces to NIDP data, and none is invented"* — is operationalised by Nivesh routes that compose data from NIDP intelligence + the user's own holdings, never re-deriving numbers NIDP already produces. Per the project memory, NIDP duplicates already detected in Nivesh (equity_pct / beta / top_sector) should migrate to NIDP-sourced reads from `/v1/intelligence/portfolio/{user_id}/snapshot`.

For v4, the boundary suggests:
- **NIDP-owned**: any new endpoint requiring market data, fundamentals, technicals, instrument scoring, peer comparison, or per-user snapshot intelligence.
- **Nivesh-owned**: any new endpoint that aggregates/mutates user state (plans, goals, Plan Board actions, Builder proposals, advisor workspace).

---

## Section B — Screen-by-Screen Mapping

> **Status legend**
> ✅ Exact match — endpoint returns exactly what's needed
> ⚠️ Partial — endpoint exists but needs modification (new field, query param, or shape change)
> ❌ Missing — no endpoint covers this
> 🗑️ Redundant — UI no longer needs something the API returns
> N/A — UI-only (navigation, static copy, client-state)

### Group 1: Public + Auth (Screens 01, 02, 03)

#### 01 — Homepage

| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Hero "Know exactly how healthy your portfolio is" headline | Static copy | — | N/A | UI-only |
| "Check my portfolio free" CTA | Navigates to `/login` | — | N/A | |
| "See how it works" CTA | Navigates to `/landing` (demo data) | — | N/A | Public demo path not yet wired |
| Three feature cards (Import, Health score, Know what to do) | Static copy + icons | — | N/A | |
| Sample-score teaser card ("86 — financials over-concentrated") | Static demo data | — | N/A | Should use static fixture, not live data |
| Top-nav: Product / For advisors / Sign in | Static links | — | N/A | |

#### 02 — Login

| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Mobile/email + password sign-in | Credentials | ❌ none | ❌ Missing | No password endpoint exists. Per project memory and code grep: only `/api/auth/google` and `/api/auth/gmail-session` exist. Either drop password-login from v4 or add `POST /api/auth/password` (compliance impact). |
| "Forgot?" link | Password reset flow | ❌ none | ❌ Missing | Same — no password infra. Drop or build. |
| Google OAuth button | `code` + `state` from Google | `POST /api/auth/google` | ✅ | Body: `{credential, ...}`. Returns user doc. |
| OTP login button | Mobile + OTP verify | ❌ none | ❌ Missing | No OTP routes exist. Either drop, or add `POST /api/auth/otp/request` + `/api/auth/otp/verify`. |
| Advisor sign-in link | Routes to advisor flow | — | N/A | Same auth, different post-login routing |
| Create-an-account link | Routes to `/onboard` | — | N/A | |

#### 03 — Onboarding

| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| "Import CAS from Gmail" (Fastest) | OAuth + auto-fetch latest CAS email | `POST /api/onboarding/gmail/auto-import` | ✅ | Body: scope+token. Returns parsed snapshot. |
| Gmail OAuth start | Auth URL | `GET /api/auth/gmail-exchange` | ✅ | |
| "Upload CAS statement" + password | PDF + PDF password | `POST /api/onboarding/upload-cas` or `POST /api/portfolio/upload-raw` (large files) | ✅ | Two endpoints; raw for password-protected/large PDFs |
| Upload progress / task status | `task_id` poll | `GET /api/portfolio/upload-status/{task_id}` + `GET /api/portfolio/upload-latest-task` | ✅ | |
| "Connect your broker" (Zerodha/Groww/Upstox) | Broker OAuth | ❌ none for end-user | ❌ Missing | Per project memory: no broker-connect routes for retail. `/api/broker/accounts/...` exists but is admin/OpenAlgo. Drop from v4 or define new broker-connect flow. |
| "Add holdings manually" fallback | UI to add ISIN + units | ⚠️ partial | ⚠️ Partial | No bulk manual-holdings endpoint; would compose multiple `POST /api/portfolio/holdings/...` calls. Cleanest fix: add `POST /api/portfolio/holdings/manual` taking `[{isin, units, avg_price}]`. |
| PAN consent + capture | Encrypted PAN persist | `POST /api/onboarding/pan` + `PUT /api/compliance/pan` | ✅ | |
| Onboarding state probe | Current step / holdings count | `GET /api/onboarding/state` | ✅ | |
| "Review parsed holdings" step (PRD §5.1: review precedes analysis) | Parsed holdings before score | `GET /api/portfolio/holdings` after upload completes | ⚠️ Partial | Returns holdings, but no dedicated "preview / approve / discard" UX endpoint. Could compose; or add `POST /api/portfolio/holdings/confirm` to gate v3 score computation. |

### Group 2: Chat (Screen 04)

#### 04 — Chat Landing

| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Brand mark + "NIDP connected" badge | NIDP health indicator | ⚠️ partial | ⚠️ Partial | Per Open Question #11 — is this a real health check or a brand label? `GET /v1/intelligence/portfolio/sync/status` exists on NIDP; could surface staleness. Today the UI shows it unconditionally. |
| "Portfolio analysed · NIDP-grounded" eyebrow | Boolean from snapshot | `GET /api/portfolio/cas-snapshots` (count > 0) | ✅ | |
| Health ring `pb-score` (86) + grade ("Grade A") | health.score (0-100), health.grade | `GET /api/insights/v3-portfolio` | ⚠️ Partial | Returns 7-band A+/A/B+/B/C/D/F but PRD §13.1 "A to D" — adapter must collapse 7→4 bands. Per project memory: this is the V4 frontend's current adapter behaviour. |
| Health ring breakdown (Diversification / Risk / Cost / Performance) | health.components.{...}.{score,weight} | `GET /api/insights/v3-portfolio` | ✅ | `.health.components` carries 4 sub-scores. |
| Top-3 insight cards (rust/gold borders, dashboard label, impact badge, chevron) | `top_recommendations[].{title,kind,impact,signal_type}` | `GET /api/intelligence/portfolio` | ✅ | `kind` field used by adapter for dashboard routing. |
| Top recommendation card ("Trim financials from 32% to 22%") | First PENDING action with verb + entity + projected delta | `GET /api/plans/active` (`.plan.actions[0]`) | ⚠️ Partial | Has action.reason_text, asset_name, amount. **Missing: per-action `expected_impact.health_delta`** to render "+6 pts". Today the V4 client uses a static "+6 pts" estimate — flagged Finding C.6. |
| Prompt chips ("Build me a portfolio", "Is my portfolio too risky?", "Show my action plan") | List of suggested-prompts | `GET /api/copilot/suggested-prompts` | ✅ | Returns `prompts[].{label, query, tier, badge, viz}`. Exists in code (memory) though not in the Postman collection — flag for inclusion in v2 collection. |
| Sticky bottom chat bar (+/input/↑) | Send a message + stream a response | `POST /api/chat/send` or `POST /api/copilot/ask` | ✅ | Two paths exist. PRD §4.1 demands chat-as-home; the entry point should be unified. |
| Insight card → dashboard deep-link | Map `kind` / `signal_type` → dashboard route | client-side mapping | N/A | UI mapping only. |

### Group 3: Analytical Dashboards (Screens 05–10)

> ⚠️ All 6 dashboards share the **identical** structural pattern per PRD §7.1 (Table 11):
> ① Insight — headline + hero metric + supporting stat tiles + chart
> ② Recommendations — ranked action matrix
> ③ Apply — projected-metric footer + "Send to Plan board"
>
> Document the shared envelope here once. Per-screen tables list only type-specific metrics + breakdowns.

**Shared envelope fields** (all 6 dashboards)

| Field | Type | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| `issueCount` (badge in topnav) | int | composable from `/api/plans/active` + `/api/insights` | ⚠️ Partial | No per-dashboard issue count exposed. Currently the V4 client derives it; consider exposing `count` per domain in a future composite. |
| `insight.headline` (narrative — "32% of your money is in financials") | string | per-dashboard endpoint (e.g. `concentration.hero_insight.headline`) | ⚠️ Partial | Each domain returns its own `hero_insight` shape (string vs object). Worth unifying. |
| `insight.subtext` (caution-line explanation) | string | same per-domain endpoint | ⚠️ Partial | Same unification opportunity. |
| `recommendations[]` (the action matrix) | Recommendation[] | `GET /api/plans/active` (filtered by domain) | ⚠️ Partial | The action schema is the keystone shape (Finding C.2). Missing: `tradeOff` field (mandatory per PRD §7.4), `expected_impact` per action, `priority_label` ("Critical"/"Optimise"/"Enhance"). |
| `projection.current` / `projection.projected` ("86 → 92") | int / int | `GET /api/plans/active/health-projection` | ⚠️ Partial | Today returns only `delta_total + delta_by_component`. **No per-action health delta** — Finding C.6. |
| `acceptedCount` (③ Apply counter) | int | derived client-side from accepted action ids | N/A | Client-side state today. |
| "Send to Plan board" action | Promote local-accept → server PATCH | `PATCH /api/plans/{plan_id}/actions/{action_id}` | ✅ | Body: `{status: ACCEPTED}`. Per project memory: HOLD path writes `"pending"` lowercase, validator enforces UPPERCASE → silent bug to be fixed alongside any new aggregation endpoint. |

#### 05 — Concentration (type-specific)

OCR + HTML IDs confirm: `cn-headline` `cn-sub` `cn-t5` `cn-hhi` `cn-effn` `cn-chips` `cn-caution` `cn-lenslbl` `cn-rows` `cn-matrix` `cn-proj` `cn-accn` `cn-badge`. Five lenses per PRD §7.3: stock / sector / AMC / company / promoter group.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Headline `cn-headline` ("32% of your money is in financials") | string from active lens | `GET /api/portfolio/exposure/concentration` (`{lens}.hero_insight.headline`) | ✅ | Returns hero_insight per lens (sector/amc/company/group). |
| Subtext `cn-sub` ("Above the 25% caution line…") | string | same | ✅ | `{lens}.hero_insight.detail` |
| Top 5 stat `cn-t5` ("48%") | sum of top-5 weights | same | ⚠️ Partial | Not exposed as a single field; client computes from `.amc.items[].pct`. Add `top5_pct` per lens for cleanliness. |
| HHI stat `cn-hhi` (1840) | Herfindahl-Hirschman Index | same | ⚠️ Partial | API returns HHI as 0–1 float (e.g. 0.184); UI shows 0–10000 form (×10000). Adapter normalises; could be unified. |
| Effective N stat `cn-effn` (8.2) | 1/HHI | same | ✅ | `{lens}.effective_n`. |
| Caution-line indicator `cn-caution` ("CAUTION 25%") | static 25% threshold | client-side | ⚠️ Partial | Per Open Question #10: where does the 25% threshold come from? PRD doesn't specify. Either expose `caution_pct` server-side or document as policy constant. |
| Lens chips `cn-chips` (Stocks / AMC / Companies / Groups) | UI tabs | client switches | N/A | PRD §7.3 says 5 lenses but mockup shows 4 (stock lens missing). Confirm via PRD §7.3 if `look-through stock` is the same as `company`. |
| Bar rows `cn-rows` ("Financials 32%, IT 21%, Consumer 14%, …") | `{lens}.items[].{name, pct}` | same | ✅ | |
| Ranked action matrix `cn-matrix` | Recommendation[] filtered to `reason_codes ∩ {SECTOR_CONC, AMC_CONC, COMPANY_CONC, OVERLAP_CONSOLIDATION}` | `GET /api/plans/active` | ⚠️ Partial | Filter applied client-side; cleaner if domain-tagged server-side. **Trade-off field missing** in action schema. |
| Per-action priority badge ("Critical" / "Optimise") | string | client maps from `priority: int 1/2/3` | ⚠️ Partial | Adapter maps int → label; should be `priority_label` server-side per PRD §7.4. |
| Per-action impact / effort / trade-off triplet | three strings | client uses `reason_text` for impact | ❌ Missing | **trade-off field is mandatory per PRD §7.4** but not in current action schema. Effort field also missing. |
| Per-action "Why?" button | calls explainer | `POST /api/copilot/explain` | ⚠️ Partial | Returns an explainer but not bound to a specific action_id; would benefit from `?action_id=` query param. |
| Projected health footer `cn-proj` ("86 → 92") | int → int | `GET /api/plans/active/health-projection` | ⚠️ Partial | Only plan-level total exists; per-action increment needed for live-on-accept animation (Finding C.6). |
| Accepted count `cn-accn` | int | client local state | N/A | |
| "Send to Plan board" → /plan | Promote accepted | `PATCH /api/plans/.../actions/...` | ✅ | |
| Badge in topnav `cn-badge` ("High") | severity from worst HHI/concentration | derived | ⚠️ Partial | No `badge_tone` field returned; client computes from HHI thresholds. |

#### 06 — Diversification

OCR fields: "FUNDS / OVERLAP / UNIQUE STOCKS / 8 / 61% / 42", "PAIRWISE FUND OVERLAP", pairs list. HTML IDs: shared with Concentration via the same naming convention.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Headline ("3 funds hold near-identical stocks") | high_pairs count | `GET /api/portfolio/exposure/fund-overlap/matrix` | ✅ | Returns `pairs[]` (upper triangle, sorted desc, capped 25) + `high_pairs`. |
| Subtext | static narrative | derived | ⚠️ Partial | Could expose `.hero_insight` like Concentration does. |
| Funds count tile | `funds.length` | same | ✅ | |
| Max overlap % tile ("61%") | `max_pct` | same | ✅ | |
| **Unique stocks tile (42)** | int | `GET /api/portfolio/exposure/fund-overlap/matrix` | ❌ Missing | Per memory: unique-stocks count not exposed. Add `unique_stocks_count` to response. |
| Pairwise fund-overlap bars | pairs[].{fund_a, fund_b, overlap_pct} | same | ✅ | |
| Recommendation matrix | actions filtered to OVERLAP_CONSOLIDATION / REGULAR_DIRECT_DUPLICATE / COST_LEAK_SWITCH | `GET /api/plans/active` | ⚠️ Partial | Same trade-off/effort gap as Concentration. |
| "Funds after cleanup" projection footer ("8 → 5") | int → int | derived from plan improvements | ⚠️ Partial | `plan.improvements.overlap_pct` exists but no fund-count delta. Add `improvements.fund_count` to plan-projection response. |
| Send to Plan board | PATCH actions | `PATCH /api/plans/.../actions/...` | ✅ | |

#### 07 — Risk

OCR: "8.0% / 1-DAY VaR / Swings 1.3x the market / BETA / VOLATILITY / MAX DD / SHARPE / 1.31 / 22% / -29% / 0.71 / WHAT'S DRIVING THE RISK / Smallcap weight 44% / High-beta names 37% / …". HTML IDs: `rk-drivers`, `rk-matrix`, `rk-proj`, `rk-accn`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| VaR ring centre value ("8.0% 1-DAY VaR") | `var_1d_pct` | `POST /api/copilot/widgets/portfolio_var` | ⚠️ Partial | Widget exists but it's a chat-widget pattern (POST + transformer). For a dashboard, prefer `GET /api/portfolio/risk-analytics` to also carry VaR. |
| Headline ("Swings 1.3× the market") | derived from weighted_beta | `GET /api/portfolio/risk-analytics` (`weighted_beta`) | ✅ | |
| Subtext ("A 95% one-day loss near ₹1.48L on ₹18.4L") | `var_1d_rs` + `portfolio_value_rs` | VaR widget (POST) | ⚠️ Partial | Same widget concern as above. |
| Beta tile | `weighted_beta` | `GET /api/portfolio/risk-analytics` | ✅ | |
| Volatility tile | `weighted_volatility` | same | ✅ | |
| **Max DD tile (-29%)** | maximum drawdown | — | ❌ Missing | Per project memory: `risk-analytics` returns weighted_beta / weighted_sharpe / weighted_volatility / risk_drivers but **no max_drawdown**. Add `max_drawdown_pct` to risk-analytics response (or expose via `/api/copilot/widgets/stress_test`). |
| Sharpe tile | `weighted_sharpe` | `GET /api/portfolio/risk-analytics` | ✅ | |
| Risk drivers list `rk-drivers` | `risk_drivers[].{type, label, detail, impact, pct}` | same | ✅ | Returns label + detail + impact tone. |
| Recommendation matrix `rk-matrix` | actions filtered to HIGH_BETA / HIGH_VOLATILITY | `GET /api/plans/active` | ❌ Missing reason codes | Per project memory: no HIGH_BETA / HIGH_VOLATILITY reason codes exist in action plan today. The V4 client uses TRIM/HOLD action types as a proxy. Add the codes server-side. |
| Projected beta footer `rk-proj` ("1.31 → 1.13") | beta_before / beta_after | derived from plan.improvements | ❌ Missing | `plan.improvements.weighted_beta.{before, after}` not present. Add to plan-projection. |
| Send to Plan board | PATCH actions | `PATCH /api/plans/.../actions/...` | ✅ | |

#### 08 — Performance

OCR: "Beating Nifty by 2.6 pp / YOUR XIRR / NIFTY / ALPHA / 21% / 18.4% / +2.6 / FUND VS ITS BENCHMARK - 3-YR / Nippon Smallcap 8.2pp / Parag Flexi Cap 6.0pp …". HTML IDs: `w-d_perf`, otherwise generic.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Headline ("Beating Nifty by 2.6 pp") | alpha vs benchmark | `GET /api/portfolio/cas-performance` + `GET /api/index/latest` | ⚠️ Partial | No single endpoint returns headline string; client must compose. |
| Your XIRR tile (21%) | portfolio xirr | `GET /api/portfolio/holdings-enriched` (`.totals.xirr_pct`) | ✅ | Per project memory: portfolio XIRR lives on holdings-enriched, NOT on cas-performance. |
| Nifty tile (18.4%) | benchmark return same period | `GET /api/index/latest` (`name=NIFTY 50`) | ⚠️ Partial | Returns latest snapshot; period-matched return needs computation. Add `period=1y/3y/5y` param. |
| Alpha tile (+2.6 pp) | XIRR - benchmark | client-side derivation | ⚠️ Partial | Same: derived; could be a composite "performance summary" endpoint. |
| Per-fund vs benchmark bars ("Nippon Smallcap 8.2pp …") | per-fund alpha | `GET /api/portfolio/fund-performance` | ⚠️ Partial | **Per project memory: returns 1Y alpha vs *peer-average* (`category Avg`), NOT vs SEBI benchmark index, and NOT 3-yr.** Mockup explicitly shows "FUND VS ITS BENCHMARK - 3-YR". Either: (a) add `?period=3y&benchmark=index` to fund-performance, or (b) build a new `GET /api/portfolio/fund-performance/benchmark-alpha?period=3y`. |
| Recommendation matrix | actions filtered to LOW_RETURN_EFFICIENCY / UNDERPERFORMING_FUND | `GET /api/plans/active` | ❌ Missing reason codes | Add codes. Today the V4 frontend has no Performance screen wired up. |
| Projected XIRR footer ("21.0 → 22.1") | xirr_before / xirr_after | — | ❌ Missing | Per project memory: no per-action XIRR delta. Add to plan-projection. |
| Send to Plan board | PATCH actions | `PATCH /api/plans/.../actions/...` | ✅ | |

#### 09 — Goals

OCR: "Child education goal is behind / CURRENT SIP / NEEDED / SHORTFALL / 12K / 19K / 11L / ALL GOALS - PROJECTED FUNDING / Retirement 96% / Emergency fund 88% / Home down-payment 81% / Child education 74%". HTML IDs: `w-d_goals`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Headline ("Child education goal is behind") | worst-funded goal narrative | derived from `goals[].on_track_pct` ascending | ✅ | |
| Subtext ("On the current SIP it lands at 74% of the ₹42L target") | string | derived from goal.last_simulation | ⚠️ Partial | Composed client-side; could expose as `goal.summary` |
| Current SIP tile | sum of detected SIPs to goal | `GET /api/portfolio/sips` + goal mapping | ⚠️ Partial | No explicit SIP-to-goal mapping endpoint. |
| Needed SIP tile | required SIP to hit target | `GET /api/goals` (`goals[].last_simulation.required_sip_rs`) | ✅ | |
| Shortfall tile | corpus shortfall | `GET /api/goals` (`goals[].last_simulation.shortfall_rs`) | ✅ | |
| All-goals progress bars (Retirement 96%, …) | `goals[].on_track_pct` | `GET /api/goals` | ✅ | |
| Recommendation matrix (Raise SIP / Lump sum / Extend goal) | goal-engine recommendations | — | ❌ Missing | **Per project memory: goal engine emits `sip_increase, sip_step_up, lumpsum_topup, horizon_extension, target_reduction, do_nothing, rebalance_to_growth` but these DO NOT flow into `/api/plans/active`.** Today Goals dashboard and Plan Board are decoupled. Two options: (a) feed goal-engine recommendations into the plan_actions table so they appear in /plans/active filtered by reason_code = GOAL_*; (b) Expose `GET /api/goals/{id}/recommendations` and have the client merge with /plans/active. **Recommended (a)** — Plan Board is the cross-cutting tracker per PRD §8. |
| `exclusive` flag (PRD §7.4 — Goals actions are mutually exclusive) | boolean per action | — | ❌ Missing | Action schema lacks `exclusive` flag. Add it (default false; goals-domain actions set true). |
| Priority badge labels — Closes-the-gap / Closes-most / Partial | string | client maps | ⚠️ Partial | Different from other dashboards' Critical/Optimise/Enhance per PRD §7.4. `priority_label` field would carry both vocabularies. |
| Projected funding footer ("74% → 100%") | funded_before / funded_after | — | ❌ Missing | Add `goals[].projected_on_track_pct` post-plan to /api/plans/active/health-projection. |
| Send to Plan board | PATCH actions | (depends on Goals→Plan integration above) | ❌ Missing | Blocked on the same gap. |

#### 10 — Tax

OCR: "₹14K of tax is harvestable now / Long-term gains can be booked before FY-end / HARVESTABLE / LTCG USED / DAYS LEFT / 14K / 18K / 41 / HARVEST OPPORTUNITY BY HOLDING / Nippon Smallcap 70K / …". HTML IDs: `w-d_tax`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Headline ("₹14K of tax is harvestable now") | total_harvestable_rs derived | `POST /api/copilot/widgets/tax_harvest` (`.data.total_harvestable_rs`) | ⚠️ Partial | Widget pattern (POST + chat-widget envelope). Promote to `GET /api/portfolio/tax-summary` for dashboard consumption. |
| Subtext | static | — | N/A | |
| Harvestable tile (₹14K) | float | tax_harvest widget | ⚠️ Partial | Same as above. |
| LTCG used tile (₹18K) | `ltcg_used_rs` | tax_harvest widget | ⚠️ Partial | Same. |
| **LTCG limit** | `ltcg_limit_rs` | tax_harvest widget | ⚠️ Partial | **Per project memory: hardcoded at `₹100_000` — should be ₹1,25,000 (post-Jul-2024 tax law). Stale.** Fix independently of v4. |
| Days-left tile (41) | days till FY-end | client (FY-end – today) | N/A | Could be client-derived. |
| Harvest opportunity per holding | candidates[] | tax_harvest widget (`.data.candidates[].{fund_name, gain_rs, gain_type, days_held, eligible}`) | ✅ | |
| Recommendation matrix (Harvest 5 lots / Shift to arbitrage / Use ELSS) | tax actions | — | ❌ Missing | **Per project memory: tax actions do NOT exist in `action_plan_manager` — only inside widget payloads. Plan Board cannot show tax actions today.** Add a tax action generator that writes to plan_actions with reason_code = TAX_HARVEST / TAX_STRUCTURING / TAX_80C. |
| Projected tax saved footer ("₹0 → ₹2.8K") | tax_saved_before / tax_saved_after | — | ❌ Missing | New field on plan-projection. |
| Send to Plan board | PATCH actions | (depends on Tax→Plan integration above) | ❌ Missing | Blocked. |
| Duplicate route warning | — | — | — | **Per project memory: `tax_timing` is registered TWICE in `copilot_widgets.py` (lines 1507 and 1663). Latest wins; first is dead code. Fix independently.** |

### Group 4: Plan Board (Screen 11)

#### 11 — Plan Board

OCR: "Plan board / 86 / PROJECTED / Your plan lifts health to 99 / 0 of 6 actions done - gathered from 4 dashboards / TO DO 6 / DONE 0 / SKIPPED 0 / per-action cards with origin dashboard tag". HTML IDs: `pb-ring`, `pb-score`, `pb-target`, `pb-prog`, `pb-bar`, `pb-todo`, `pb-todoc`, `pb-done`, `pb-donec`, `pb-skip`, `pb-skipc`, `pb-pill`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Topnav badge "Active plan" / `pb-pill` | plan status | `GET /api/plans/active` | ✅ | |
| Hero ring centre score `pb-score` (86) | current health score | `GET /api/insights/v3-portfolio` (`.health.score`) | ✅ | Per PRD §8.1: "current projected health (base plus points already earned)" |
| Hero ring target `pb-target` (99) | base + all accepted actions' delta | `GET /api/plans/active/health-projection` (`.delta_total`) + base score | ⚠️ Partial | Combine client-side; could be one endpoint returning {base, current_projected, target_full}. |
| Headline ("Your plan lifts health to 99") | derived | — | ⚠️ Partial | Client-composed; could expose `plan.headline` for prototype-fidelity. |
| Progress bar `pb-bar` / `pb-prog` ("0 of 6") | doneCount / totalCount | `GET /api/plans/active` | ✅ | |
| TO DO group `pb-todo` / count `pb-todoc` | actions where status ∉ {COMPLETED, SKIPPED} | `GET /api/plans/active` (filter) | ✅ | |
| DONE group `pb-done` / count `pb-donec` | status = COMPLETED | same | ✅ | |
| SKIPPED group `pb-skip` / count `pb-skipc` | status = SKIPPED | same | ⚠️ Partial | **Per project memory: HOLD path writes "pending" lowercase, status validator enforces UPPERCASE. HOLD actions can never be PATCHed today — silent bug.** Fix HOLD writer to uppercase. |
| Per-action card with origin dashboard tag (Concentration / Risk / Goals…) | `action.source_domain` | — | ❌ Missing | **Required for PRD §8.1: "source memory — every action remembers its origin dashboard, shown on a coloured rail; a tap returns the client to where the action came from."** Add `source_domain` to action schema. |
| Per-action verb (Trim / Switch / Harvest / Merge / Raise SIP) | `action.verb` | — | ❌ Missing | Today verb is inferred from `type` (EXIT/ADD/TRIM/HOLD/REVIEW). PRD §7.4 specifies stock verbs (Add/Exit/Trim/Hold) AND fund verbs (Switch/Exit/Add/Merge/Hold). Action schema needs an explicit `verb` field per asset_type. |
| Per-action delivered-health-when-done | `action.health_delta` | — | ❌ Missing | Same as Finding C.6. |
| Mark done / Mark skip / Undo controls | client-state today; PATCH on commit | `PATCH /api/plans/{plan_id}/actions/{action_id}` | ⚠️ Partial | API supports it but HOLD-status bug above. Add idempotent PATCH semantics. |
| Sort: To-do by priority, Done newest first, Skipped at bottom | client-side | — | N/A | |

### Group 5: Builder + Recommendations (Screens 12, 13, 14)

#### 12 — Portfolio Builder

OCR: "Risk appetite slider / Monthly surplus ₹40,000 / Goal horizon 11 years / PROPOSED ALLOCATION / Equity 60% / Debt 30% / Gold 10% / SIP PLAN SPLIT ACROSS GOALS / PRIMARY GOAL FUNDING - PROJECTED / 110% On track". HTML IDs: `bd-risk` `bd-riskv` `bd-inc` `bd-incv` `bd-hor` `bd-horv` `bd-allocbar` `bd-allocrows` `bd-sips` `bd-fundcheck`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Risk appetite slider `bd-risk` (5-band: Conservative…Aggressive) | int 0-4 | `GET /api/goals/snapshot` (`.risk_profile`) | ⚠️ Partial | **Per project memory: stored values are `conservative / moderately_conservative / moderate / moderately_aggressive / aggressive` (5-band) — but PRD §9.1 (Table 14 implicit) shows `Cautious / Growth` labels. Adapter must remap labels.** |
| Monthly surplus slider `bd-inc` | rupees | client state | N/A | |
| Goal horizon slider `bd-hor` | years | client state | N/A | |
| Proposed allocation bar `bd-allocbar` (Equity 60 / Debt 30 / Gold 10) | sleeve % | `POST /api/portfolio-builder/generate` | ⚠️ Partial | **Per project memory: accepts ONLY `{monthly_sip_rs, lumpsum_rs}` — NOT `{monthly_surplus, horizon_years, risk_bucket}`. Risk is read from stored profile; horizon hardcoded `None`. Mockup's 3-slider input card cannot bind to this endpoint as-is.** Modify to accept all three sliders. |
| Per-sleeve fund picks (Parag Flexi / Mirae Large / Motilal Mid for Equity sleeve) | top funds by sleeve | response of `/portfolio-builder/generate` | ✅ | Returns proposal with funds per sleeve. |
| Per-sleeve rupee allocation ("₹24,000/mo") | sleeve_amount | same | ✅ | |
| Bottom links: "See top picks → /recs" and "Fine-tune split → /alloc" | nav | — | N/A | |
| SIP plan per goal `bd-sips` (Child ed 45% ₹18K / Retirement 35% ₹14K / …) | goal allocation | `POST /api/copilot/widgets/sip_plan` (`.data.allocation[]`) | ⚠️ Partial | Widget pattern. Promote to `POST /api/portfolio-builder/sip-plan`. |
| Primary goal funding check `bd-fundcheck` ("110% On track") | future-value projection vs target | per-goal simulate | ⚠️ Partial | `POST /api/goals/{id}/simulate` returns FV result. Builder context needs cross-goal aggregation. |
| Accept & register SIPs CTA | persist plan + create SIPs | — | ❌ Missing | No SIP-registration endpoint. PRD §13.2 Open Question: "SIP retry mechanics depend on BSE Star / MFU integration capability." Same blocker for registration. Mark as deferred; reads "register" today but is plan-persist only. |
| Adjust funds → /alloc | nav | — | N/A | |

#### 13 — Recommendations

OCR: "Recommended for you / SCORED ON FUNDAMENTALS, TECHNICALS & CONSISTENCY / TOP STOCKS FOR YOUR PROFILE / HDFC Bank Financials 86 / FUNDAMENTALS 92 TECHNICALS 78 / ROE 17% - low NPA / Above 200-DMA / TOP FUNDS FOR YOUR SLEEVES / Parag Parikh Flexi Cap 91 / RETURNS 96 COST 94 CONSISTENCY 92". HTML IDs: `w-recs`, `mx-`, `ft-`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Top stocks list | top-N stocks by composite score per sector exposure | `GET /api/portfolio/stock-scores` | ⚠️ Partial | Returns `scores.{quality, health, exit, add}` per stock the user already holds. **No greenfield stock-discovery endpoint for "TOP STOCKS FOR YOUR PROFILE".** Add `GET /api/recommendations/stocks?profile=balanced&top=5`. |
| Per-stock score (86, 86, 82…) | composite 0-100 | derived from quality.score | ⚠️ Partial | Quality score is 0-10; UI shows 0-100. Adapter scales ×10. |
| Per-stock Fundamentals score (92) | fundamentals primitive | `GET /api/portfolio/stock-scores` (`quality.components.fundamentals` × 10) | ⚠️ Partial | Per memory: `fundamentals_score ≈ quality.components`. |
| Per-stock **Technicals score (78)** | technicals primitive | — | ❌ Missing | **Per project memory: no technicals primitive stored.** Add a technicals_score field (or compute from price action). |
| Per-stock fundamental explainer ("ROE 17% - low NPA") | one short reason | `GET /api/portfolio/stock-scores` (`recommendation.reason`) | ⚠️ Partial | Only one explainer string; UI needs two (fundamentals + technicals). |
| Per-stock technical explainer ("Above 200-DMA") | one short reason | — | ❌ Missing | Same — needs second explainer. |
| Top funds list per sleeve | top-N funds by composite score per sleeve | `GET /api/goals/fund-shortlist/{bucket}` | ⚠️ Partial | Bucket keys are `equity / debt / hybrid / liquid` — NOT `short/medium/long/very_long` as some docs suggest. Returns shortlist OK. |
| Per-fund 3 sub-scores (RETURNS 96 / COST 94 / CONSISTENCY 92) | `quality.components.{performance, cost, consistency}` × 10 | `GET /api/intelligence/v3-score/{id}` | ❌ Admin-gated | **Per project memory: `/api/intelligence/v3-score/{id}` is admin-only (`require_admin`). Sub-scores exist internally in `v3_scoring.py:206-220` but not exposed at user layer.** Add user-callable `GET /api/funds/{id}/v3-score` returning `{performance, cost, consistency}`. |
| "Use these in my allocation" CTA | feeds back into Builder | client-state | N/A | |
| Compliance banner ("SEBI SCREENED IDEAS - NOT BUY ADVICE") | static | — | N/A | |

#### 14 — Instrument Allocation

OCR: "Equity sleeve / ₹24,000/mo / Parag Parikh Flexi Cap FUND 5,000 / Mirae Asset Large Cap FUND 4,500 / Motilal Oswal Midcap FUND 5,000 / HDFC Bank 3,500 / Bharti Airtel 3,000 / Tata Consultancy 3,000 / 15% 13% 13% / A HOLDING EXCEEDS ITS CAP". HTML IDs: `al-bar`, `al-rows`, `al-amt-`, `al-pct-`, `al-balance`, `al-reset`, `al-status`, `al-s-`, plus mobile-only `al-sleevebadge`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Sleeve total ("₹24,000 / mo") | sleeve_amount | from builder context | N/A | |
| Per-instrument row (name + ₹ amount + slider + % cap badge) | instrument + cap | `POST /api/portfolio-builder/generate` returns proposal | ⚠️ Partial | Returns funds + amounts per sleeve but **per-instrument `cap` / `allocation_cap_pct` not returned.** Per memory: the 35 / 30 / 25 / 12 / 10 % caps in the mockup are unbacked. Add `cap_pct` to each proposal item. |
| "A HOLDING EXCEEDS ITS CAP" warning + colour | derived from amount vs cap | client-side | ⚠️ Partial | Driven by missing `cap_pct`. |
| Re-balance button `al-balance` ("Auto-balance") | recompute proportions | `POST /api/portfolio-builder/simulate` | ✅ | |
| Reset to proposed `al-reset` | restore initial proposal | client-state | N/A | |
| Confirm split CTA | persist split | — | ❌ Missing | Same registration gap as Builder. |
| Sleeve badge `al-sleevebadge` (mobile only) | sleeve name | client | N/A | Web shows in topnav title. |

### Group 6: Advisor (Screens 15, 16, 17)

#### 15 — Advisor Book

OCR: "Advisor book / @ 24 CLIENTS / PRIYA NAIR - RM-204 / ₹41Cr / 79 / 5 / 38 / Needs attention 5 / Review soon 7 / Healthy 12 / All 24 / Rohan Mehta 62 14d / Goal at risk - child education 74% / Anjali Desai 58 31d / Tax harvest ₹40K - FY-end 41d / …". HTML IDs: `ab-filters`, `ab-list`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| RM identity (Priya Nair - RM-204) | advisor profile | `GET /api/mfd/workspace` + `GET /api/auth/me` | ✅ | |
| Top stat row: Book AUM / Avg health / Needs attention / Actions open | `total_aum_rs`, avg health, count_at_risk, open_actions_total | `GET /api/advisor/aum` (`.total_aum_rs`) + per-client roll-ups | ⚠️ Partial | Per memory: advisor/aum returns `{rows, total_aum_rs, aggregate_mom_pct, headline}` — no avg-health/at-risk/actions-open aggregates. Add `GET /api/advisor/summary` returning all four. |
| Band filter chips `ab-filters` (Needs attention / Review soon / Healthy / All) | band counts | `GET /api/mfd/profiles` (`priority` ranking) | ⚠️ Partial | Per memory: `mfd/profiles` returns each profile with a priority score. Bands (needs/review/healthy) must be derived client-side from priority thresholds OR add `band` field server-side. |
| Client row `ab-list` (name + score + last-seen days + top issue) | per-client: name, health, last_seen_days, top_issue_summary | `GET /api/mfd/profiles` + per-client `GET /api/intelligence/portfolio/{user_id}` | ⚠️ Partial | Per memory: `/mfd/profiles` has NO `health / flag / band / last_seen_days` — V4 must derive these client-side via impersonation + composing. Add `health_score`, `last_seen_days`, `top_issue_label` to /mfd/profiles. |
| Priority sort (blends health + time-sensitivity + contact gap) | priority_score | `GET /api/mfd/profiles` (returns priority_score) | ✅ | Per memory: priority resolution lives in `mfd_workspace.py`. |
| Open SIP board link | nav | — | N/A | |

#### 16 — Client 360

OCR: "Back to book / Open client chat / Rohan Mehta / 62 / 1.8CR AUM - GOAL-LED - MODERATE - LAST SEEN 14D / Concentration HIGH 38% / Performance XIRR 19% OK / Risk BETA 1.28 / Diversification 8 funds OK / Tax HARVEST 14K / Goals 1 AT RISK / What needs you 3 items / Discuss buttons / Prepare review pack / Log a call / Plan board". HTML IDs: `s-adv_360`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Client card (name, badge, AUM, style, risk, last seen) | profile + aum | `GET /api/mfd/profiles/{id}` (impersonation context) | ⚠️ Partial | Needs `style` (Goal-led / Discretionary) and `last_seen_days` — not currently in profile shape. |
| Health score (62) | impersonated `health.score` | `GET /api/insights/v3-portfolio` (after `POST /api/mfd/profiles/{id}/activate` impersonation) | ✅ | Per memory: impersonation works via `mfd_workspace.resolve_effective_user` (deps.py:65-86). |
| 6 domain tiles (Concentration / Performance / Risk / Diversification / Tax / Goals) with health-line + key metric | 6-domain rollup | composed from `/api/insights/v3-portfolio.health.components` + per-domain calls | ⚠️ Partial | **Per memory: `/api/intelligence/portfolio` does NOT return `components.{...}`. The 6-tile grid must compose from 4 sources:** v3-portfolio (diversification/risk/cost/performance), mfd-profile tax-summary (tax), goals/snapshot (goals). Concentration is a sub_score under Diversification. Add a single composite `GET /api/intelligence/portfolio/360` returning all 6 domain summaries. |
| Per-tile tap → opens dashboard | nav | — | N/A | |
| "What needs you" list (3 items: Goal at risk / Tax expires / Concentration) | open advisor-relevant items | `GET /api/advisor/today` | ⚠️ Partial | Returns top-N clients with dominant action; not per-client "needs you" list. Add `GET /api/mfd/profiles/{id}/needs-attention`. |
| Per-item "Discuss" button (PRD §10.2: advisor never writes Accept) | mark item as discussed | — | ❌ Missing | Add `PATCH /api/mfd/profiles/{id}/actions/{action_id}/discuss` (records discussion timestamp, doesn't change client's plan). |
| "Prepare review pack" CTA | generate PDF/email pack | — | ❌ Missing | **Per memory: definitive 🔴 GAP. No review-pack endpoint.** Add `POST /api/mfd/profiles/{id}/review-pack/generate`. |
| "Log a call" CTA | record CRM note | `PUT /api/mfd/profiles/{id}/notes` | ⚠️ Partial | Notes endpoint exists but freeform. Add a typed `POST /api/mfd/profiles/{id}/call-log` with date/duration/outcome. |
| "Plan board" CTA | navigates to client's plan (impersonated) | `POST /api/mfd/profiles/{id}/activate` then `GET /api/plans/active` | ✅ | |

#### 17 — SIP Board

OCR: "SIP board / @ 4 NEED ACTION / RM-204 - CYCLE MAY 2026 / MONTHLY INFLOW / ACTIVE SIPS / FAILED / MANDATE AT RISK / ₹6.4L / 68 / 3 / 4 / Failed 3 / Expiring 4 / Step-up due 5 / Healthy 56 / Anjali Desai / Parag Parikh Flexi Cap - ₹15K/mo / Bounced 2 May - insufficient balance / 2 CYCLES MISSED / Message / Vikram Shah / Mirae Large Cap - ₹25K/mo / Bounced 5 May - mandate limit exceeded / 1 CYCLE MISSED / Message / Sanjay Rao / HDFC Short Term Debt - ₹10K/mo / Update bank / Bounced 7 May - bank account closed / 1 CYCLE MISSED". HTML IDs: `sb-filters`, `sb-list`.

| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Cycle indicator ("CYCLE MAY 2026") | current SIP cycle month | server time | N/A | |
| Top stats: Monthly inflow / Active SIPs / Failed / Mandate at risk | sum of inflows, count, failed count, mandate count | per-profile SIPs | ❌ Missing | **Per memory: no aggregate SIP-board endpoint exists at advisor scope. Per-client `/api/portfolio/sips` exists.** Add `GET /api/advisor/sip-board/summary` returning the 4 KPIs. |
| Queue filter chips (Failed / Expiring / Step-up due / Healthy) | queue counts | — | ❌ Missing | Need `state` field per SIP. Add `GET /api/advisor/sip-board?state=failed|expiring|step_up|healthy`. |
| Per-row: client + fund + ₹/mo + bounce reason + cycles missed | SIP detail + bounce reason | `GET /api/portfolio/sips` (per client, impersonated) | ❌ Missing fields | **Per memory: definitive 🔴 GAP. No `mandate_id / expiry_date / next_debit_date / last_bounce_reason / proposed_stepup` fields.** Add to /api/portfolio/sips. |
| "Message" CTA (queue-specific action) | template message + delivery | — | ❌ Missing | No client-messaging route exists in this collection at the advisor scope. Could use `POST /api/copilot/client-message` but that generates text, doesn't send. Add `POST /api/mfd/profiles/{id}/sip-nudge`. |
| "Update bank" CTA (when bounce reason = closed account) | trigger client-side update flow | — | ❌ Missing | Needs an "intent" event the client receives. Add `POST /api/mfd/profiles/{id}/sip/{sip_id}/request-bank-update`. |
| "Retry" SIP (open question per PRD §13.2) | — | — | ❌ Missing | **PRD §13.2 open question: "Whether a failed SIP is advisor-retriggerable or notify-only depends on BSE Star / MFU integration capability."** Blocker — flag for product decision before designing endpoint. |
| Step-up linkage to Goals dashboard ("raise SIP" recommendation becomes a step-up item here, PRD §10.3) | bi-directional link | — | ❌ Missing | Cross-domain wiring. Same goals → plan integration gap. |

---

## Section C — Cross-Cutting Findings

### Finding C.1: Dashboard Contract Unification

**Question:** Should the six dashboards be served by one composite `GET /api/dashboards/{type}` or six focused endpoints (today's status quo, with shape drift)?

**Current state:** Six different endpoints with **inconsistent envelopes**:
- `/api/portfolio/exposure/concentration` returns `{amc, sector, company, group}` with `{items, hhi, effective_n, hero_insight}` per lens.
- `/api/portfolio/exposure/fund-overlap/matrix` returns `{funds, matrix, pairs, max_pct, high_pairs}` — no `hero_insight`.
- `/api/portfolio/risk-analytics` returns `{weighted_beta, weighted_sharpe, weighted_volatility, risk_drivers}` — no max_drawdown, no `hero_insight`.
- `/api/portfolio/cas-performance` returns time series.
- `/api/goals` returns goal list.
- Tax has no GET — only POST widget endpoints.

**Recommendation: ONE composite per-dashboard endpoint** with a unified envelope:

```
GET /api/dashboards/{type}    // type: concentration|diversification|risk|performance|goals|tax
{
  type: "concentration",
  badge: { label: "High", tone: "rust" },
  insight: { headline: "32% of your money is in financials",
             subtext: "Above the 25% caution line",
             hero_metric: { label: "TOP 5", value: "48%", tone: "rust" } },
  stat_tiles: [ {label, value, tone, sub}, ... ],          // 3-4 tiles
  breakdown: { lens: "sector",
               lens_options: ["sector","amc","company","group"],
               caution_pct: 25,
               items: [ {name, pct, tone}, ... ] },
  recommendations: [ Recommendation, ... ],                 // domain-filtered
  projection: { metric_label: "Projected health",
                current: 86, projected: 92, unit: "" }
}
```

**Trade-off:** One endpoint per dashboard with a thin transformer; less proliferation of per-domain shapes. Existing endpoints remain (additive) for advanced callers; the dashboard endpoint is the user-facing contract.

**3-DB-query budget compliance:** Each dashboard endpoint composes from (1) the domain analytics call (already exists), (2) the active plan filtered by domain reason_codes, (3) the health-projection delta. Caching the active plan in a request-scoped lookup keeps it to ≤3 logical queries.

### Finding C.2: Recommendation Entity Schema

**Question:** What is the canonical `Recommendation` object?

**Current state (from action_plan_manager.py, per memory):**
```
{
  action_id, type: "EXIT|ADD|TRIM|HOLD|REVIEW",
  priority: int OR "high|medium|low" (drift),
  asset_type, asset_name, instrument_id|asset_id|null,
  amount, exit_score|add_score, confidence: "HIGH|MEDIUM|LOW",
  reason_text, reason_codes: [str],
  status: "PENDING|IN_PROGRESS|COMPLETED|SKIPPED" UPPERCASE,
  // HOLD path writes "pending" lowercase → silent bug
  score_breakdown, tax_impact, fundamentals,
  created_at
}
```

**Missing fields from every dashboard + Plan Board (per PRD §7.4, §8.1):**
- `tradeOff` (string, **mandatory** per PRD §7.4)
- `effort: "LOW|MEDIUM|HIGH"`
- `impact: { label, value }` (e.g. `{label: "Beta cut", value: "-0.18"}`)
- `expected_impact: { health_delta, risk_delta_beta, xirr_delta_pp, tax_saved_inr, beta_delta }`
- `source_domain: "concentration|diversification|risk|performance|goals|tax"` (PRD §8.1 source memory)
- `verb` — per-asset-type vocabulary (stock: Add/Exit/Trim/Hold; fund: Switch/Exit/Add/Merge/Hold)
- `priority_label` — dashboard-specific vocabulary (Critical/Optimise/Enhance OR Closes-the-gap/Closes-most/Partial per PRD §7.4)
- `exclusive: bool` — true for Goals actions (PRD §7.4)

**Proposed canonical schema:**

```typescript
{
  id: string,                                // action_id
  type: "EXIT"|"ADD"|"TRIM"|"HOLD"|"REVIEW"|"SWITCH"|"MERGE"|"HARVEST"|"RAISE_SIP",
  verb: string,                              // user-facing verb (PRD §7.4 vocabulary)
  title: string,                             // "Trim financials from 32% to 22%"
  subtitle: string,                          // "SELL HDFC BANKING ETF · 1.8L"
  source_domain: "concentration"|"diversification"|"risk"|"performance"|"goals"|"tax",
  asset_type: "STOCK"|"FUND"|"DEBT"|"GOLD",
  asset_name: string,
  instrument_id: string | null,
  amount: number,                            // rupees
  priority: number,                          // 1, 2, 3
  priority_label: string,                    // "Critical" or "Closes the gap"
  impact: { label: string, value: string },  // {"Impact", "+6 pts"} or {"Beta cut", "-0.18"}
  effort: "LOW"|"MEDIUM"|"HIGH",
  tradeOff: string,                          // MANDATORY per PRD §7.4
  expected_impact: {                         // for projection footers
    health_delta?: number,                   // ⊕ pts to health score
    beta_delta?: number,                     // for Risk dashboard
    xirr_delta_pp?: number,                  // for Performance
    tax_saved_inr?: number,                  // for Tax
    funding_pp?: number,                     // for Goals
  },
  exclusive: boolean,                        // true for Goals (mutually exclusive paths)
  status: "PENDING"|"IN_PROGRESS"|"COMPLETED"|"SKIPPED",  // UPPERCASE always
  reason_text: string,                       // why-explainer body
  reason_codes: string[],                    // for filtering
  confidence: "HIGH"|"MEDIUM"|"LOW",
  created_at: ISO_string,
}
```

**Screens producing recommendations:** 05 Concentration, 06 Diversification, 07 Risk, 08 Performance, 09 Goals, 10 Tax, 12 Builder (proposed allocation), 13 Recommendations (top picks), 16 Client 360 (Discuss items).

**Screens consuming recommendations:** 04 Chat Landing (top recommendation card), 05–10 (each dashboard's matrix), 11 Plan Board (aggregated To-do/Done/Skipped).

### Finding C.3: NIDP vs Nivesh Boundary

**Proposed placement for new endpoints introduced by Phase 2:**

| Proposed endpoint | Nivesh / NIDP | Rationale |
|---|---|---|
| `GET /api/dashboards/{type}` | Nivesh | Composes user state (plan) + intelligence; mutations live on Nivesh side. |
| `GET /api/recommendations/stocks?profile=` | NIDP (proxy via Nivesh) | Greenfield stock discovery uses screening engine on NIDP; expose via `/v1/intelligence/recommendations/stocks` and proxy. |
| `GET /api/funds/{id}/v3-score` | Nivesh | Demotes admin-only `/api/intelligence/v3-score/{id}` to a user-scope read; reads from NIDP scores tables. |
| `GET /api/portfolio/tax-summary` | Nivesh | Uses NIDP for unrealised gains but joins with user holdings (Nivesh-owned). |
| `GET /api/intelligence/portfolio/360` | Nivesh | 6-domain rollup composes from multiple Nivesh sub-endpoints. |
| `GET /api/advisor/sip-board` | Nivesh | Operations layer over Nivesh-owned SIP records. |
| `GET /api/mfd/profiles/{id}/needs-attention` | Nivesh | Per-client item list using Nivesh plan + insights. |
| `POST /api/mfd/profiles/{id}/review-pack/generate` | Nivesh | Output formatting / PDF; consumes Nivesh state. |
| `PATCH /api/plans/{plan_id}/actions/{id}/discuss` | Nivesh | Mutation on Nivesh plan. |
| Per-action `expected_impact.health_delta` | Nivesh | The health-score engine producing the delta is on Nivesh today; future move to NIDP would require lifting the engine. |

**Principle:** All new user-facing endpoints live on Nivesh. NIDP gains only the screening / scoring extensions needed for "Top stocks for your profile" (greenfield discovery). The PRD §11.4 grounding rule is satisfied because Nivesh continues to read all primitives from NIDP, never recompute them.

### Finding C.4: Advisor vs Investor Endpoint Reuse

**Two options:**

**A. Same endpoints with role-scoped impersonation (current pattern).** Advisor calls `POST /api/mfd/profiles/{id}/activate` then issues the same `/api/insights/v3-portfolio`, `/api/plans/active`, etc. — `mfd_workspace.resolve_effective_user` (deps.py:65-86) swaps `effective_user_id` server-side.

**B. Mirrored `/api/advisor/clients/{id}/...` namespace** that proxies to the same handlers.

**Recommendation: A (impersonation), with two enhancements.**

1. Keep advisor-specific aggregations (`/api/advisor/aum`, `/api/advisor/today`, the new `/api/advisor/sip-board`, `/api/advisor/summary`) under the `/api/advisor/*` namespace.
2. For per-client reads, prefer impersonation over namespace mirroring. The CAS-snapshot family already accepts an explicit `?profile_id=` — promote that pattern to other read endpoints so the advisor doesn't have to switch impersonation context for every read.

**Trade-off:** Option B doubles the surface area for negligible UX gain; A preserves the principle in PRD §10.2 that the advisor sees the same data the client sees. The minor cost is that all client reads scope through `effective_user_id`, which is already proven.

**Permissioning:** Per PRD §10.2 — advisor never silently mutates. All advisor-side mutations must be Discuss-only (`PATCH /api/mfd/profiles/{id}/actions/{action_id}/discuss`) or hand off to the client (`POST /api/mfd/profiles/{id}/sip/{sip_id}/request-bank-update`).

### Finding C.5: Plan Board as Aggregation Sink

**Today's write path:** Each dashboard accumulates accepted actions in client-side state, then commits with `PATCH /api/plans/{plan_id}/actions/{action_id}` per action. This is correct for actions already in the plan.

**Missing:** A way to create a NEW action on the active plan when the source is a widget (Tax) or a domain that doesn't feed action_plan_manager (Goals).

**Recommendation:** Add `POST /api/plans/active/actions` accepting:
```
{
  source_domain, asset_type, asset_name, instrument_id, amount,
  type, verb, priority, priority_label,
  impact: {label, value}, effort, tradeOff,
  expected_impact: {...}, reason_text, reason_codes
}
```
This unblocks Tax actions appearing on the Plan Board (Finding for Screen 10) and Goals actions (Finding for Screen 09). All new fields match the canonical Recommendation schema (Finding C.2).

**Cross-dashboard PRD §8 invariant:** The Plan Board's projected score equals the sum of every dashboard's projection. This is satisfied iff (a) each action carries `expected_impact.health_delta`, and (b) the same health-score engine computes both per-action deltas and dashboard projections. Today (a) is missing — addressing it gates score reconciliation.

### Finding C.6: Health Score Sourcing & Caching

**Single source of truth:** `GET /api/insights/v3-portfolio` returns:
- `health.score` (0-100)
- `health.grade` (7-band A+/A/B+/B/C/D/F — PRD §11.4 says "A to D" so adapter collapses 7→4)
- `health.components.{diversification, risk, cost, performance}.{score, weight}`
- `health.partial_data: bool` + `low_confidence: bool`

**Where each screen reads it:**
- Chat Landing (04): main ring
- All dashboards (05-10): topnav badge implicitly via `health.components[...].score`
- Plan Board (11): hero ring centre + target
- Advisor Book (15): per-client health column
- Client 360 (16): main score card

**Caching strategy:**
- Per-user TTL ~15 min — score regenerates after `cas-snapshot/{date}/activate` or `holdings` mutation.
- Add `ETag` header so the Plan Board can detect when accepting an action has shifted the score upstream.
- Expose `GET /api/insights/v3-portfolio?include=components,projection` to bundle base score + accepted-plan projection in one call (replaces `/health-projection` for dashboard reads).

**Grade collapse rule (server-side):**
```
A+/A → "A", B+/B → "B", C → "C", D/F → "D"
```
Currently done client-side; **move to server** so investor + advisor see identical bands without two adapter codepaths.

### Finding C.7: Web vs Mobile Divergence

Both HTML prototypes share 99% of element IDs. Diffs detected:

| Screen | Divergence | Recommendation |
|---|---|---|
| All | Mobile adds `tabbar` (bottom tab strip), webapp uses sidebar / topnav | UI-only — same API. |
| 03 Onboarding | Identical content | None. |
| 04 Chat Landing | Identical fields | None. |
| 05-10 Dashboards | Identical fields, mobile uses single-column scroll | None. |
| 12 Builder | Identical fields | None. |
| 14 Instrument Allocation | Mobile adds `al-sleevebadge` (which sleeve you're editing); webapp shows sleeve in topnav title | None (UI only). |
| 15-17 Advisor | Identical fields | None. |

**Conclusion:** No web-vs-mobile API divergence. **Recommendation: a single endpoint set per screen.** No `view=mobile|web` query param needed. Use HTTP `Accept: application/json` plus client-side responsive rendering.

The webapp prototype additionally exposes IDs (`an-`, `ft-`, `mx-`, `crumb`) for the prototype's debug navigator that don't appear in mobile — these are not part of the product surface.

### Finding C.8: Redundant / Deprecated Fields

| Endpoint | Field | Reason for removal | Deprecation plan |
|---|---|---|---|
| `GET /api/copilot/widgets/tax_harvest` | `ltcg_limit_rs = 100_000` hardcoded | Stale (Indian tax law updated Jul-2024 to ₹1,25,000) | Patch the constant; no API shape change. **Fix independently of v4.** |
| `POST /api/copilot/widgets/tax_timing` | Route registered twice (lines 1507 & 1663 of copilot_widgets.py) | Dead code; latest registration wins | Delete the first registration. **Fix independently.** |
| `GET /api/portfolio/fund-performance` | `benchmark_name = "{cat} Avg"` (peer-average, not SEBI benchmark index) | Mockup §08 shows "vs benchmark - 3yr" | Either rename field to `peer_avg_alpha_1y` and add new field `benchmark_alpha_3y` against SEBI index, or split into two endpoints. |
| `GET /api/portfolio/deep-analytics` | Doc claims beta/sharpe/drawdown/sortino — actually returns `{overexposure, performance_cards, duplication}` | Documentation drift; metrics live on risk-analytics | Fix API_INVENTORY documentation; no shape change. |
| `GET /api/intelligence/v3-score/{id}` | Admin-gated despite being the natural user-callable fund score | Block v4 Recommendations screen | Either remove `require_admin` (with auth scope check), or add user-callable proxy `GET /api/funds/{id}/v3-score`. |
| Action `status` "pending" lowercase | HOLD writer disagrees with PATCH validator (UPPERCASE) | HOLD actions can never be PATCHed | Fix HOLD writer. **Silent bug; fix independently.** |
| Action `id` vs `action_id` | FLAG action path uses `id`; rest use `action_id` | Schema drift | Normalise to `action_id` everywhere. |

### Finding C.9: Recurring Patterns Worth Standardising

1. **Domain-tagged filtering**: Every dashboard manually filters `plan.actions[]` by reason_codes. Add server-side `?source_domain=concentration` query param to `/api/plans/active` to push the filter down.

2. **Hero insight envelope**: Concentration has `hero_insight.{tone, headline, detail}`. Diversification, Risk, Performance, Goals, Tax do not. Adopt the same envelope across all six analytics endpoints.

3. **Projection envelope**: Dashboards each have a custom `{before, after, unit}` shape. Standardise to `projection: { metric_label, current, projected, unit, tone }`.

4. **Pagination**: Most user-facing endpoints do not paginate. Add `?page=&page_size=` (default 50) to list endpoints likely to grow (chat messages, transactions, advisor profiles) to avoid silent truncation.

5. **Error envelope**: Spot-checked endpoints return errors as `{detail: "..."}` (FastAPI default). Standardise to `{error: {code, message, request_id}}` for v4 surfaces.

6. **Per-action explainer**: `POST /api/copilot/explain` does not accept `action_id`. Add the param so the "Why?" button on each action card binds 1:1.

7. **Composite endpoints over chatty UIs**: Client 360 and Advisor Book today require 3–5 reads per page. Pursue `/api/intelligence/portfolio/360` and `/api/advisor/summary` to consolidate.

8. **`/api/copilot/suggested-prompts` is missing from the Postman collection** but referenced by code. Add it to the v2 collection.

---

## Section D — Open Questions

> Every question is answered with PRD evidence where available, or flagged as **blocking** Phase 2 if it affects API shape.

1. **NIDP vs Nivesh boundary for new endpoints** — *Answered* in Finding C.3: all user-facing v4 endpoints live on Nivesh; NIDP extensions only for the screening engine (greenfield stock discovery). Non-blocking.

2. **Recommendation generation: pre-computed or on-demand?** — *PRD §4.3*: the rule engine "runs all twenty and ranks the findings by severity" — implying pre-computed at health-score time. *Answer*: pre-computed on snapshot activation; cached per-user; refreshed on holdings/snapshot mutation. Non-blocking.

3. **Health score formula: single source?** — *PRD §11.4 + Table 5*: "If these ever diverged, trust would break." *Answer*: single Health-score engine on Nivesh today; sub-scores read from NIDP primitives. Move grade-collapse server-side (Finding C.6). Non-blocking.

4. **Chat backend: existing service or new build? LLM provider?** — *PRD §4.1*: chat is home, but PRD doesn't specify provider. Existing `/api/copilot/agents/{...}` runs over the existing LangGraph agent framework with selectable model. **Blocking for chat-streaming SLA design only — non-blocking for v4 screens which use the existing endpoints.**

5. **Plan Board persistence: single active plan or versioned?** — *PRD §8 + existing `/api/plans/history` + `/api/plans/active`*: model is versioned (history + active). *Answer*: keep single active plan with versioned history. Non-blocking.

6. **Advisor permissioning: can advisor act on behalf of client?** — *PRD §10.2*: "advisor never edits a client's plan silently — advisor-side actions read Discuss, not Accept." *Answer*: advisor read-only on client state; Discuss-only writes. Non-blocking.

7. **SIP execution path: direct AMC/BSE Star MF or broker hand-off?** — *PRD §13.2 open question* — not yet decided. **Blocking for "Accept & register SIPs" button (Screen 12) AND "Retry" SIP (Screen 17).** Until answered, Screen 12 CTA is a save-plan-only operation; Screen 17 is read-only / nudge-only.

8. **Broker connect scope: which brokers in v4 vs roadmap?** — Mockup §03 lists Zerodha / Groww / Upstox but no route exists. *Open question* — drop from v4 for now, or scope a hosted OpenAlgo integration. **Blocking for Screen 03 broker tile.**

9. **CAS import sync/async** — *Answered* by existing endpoints: async via `task_id` polling (`upload-status/{task_id}`). Non-blocking.

10. **Concentration cap source: user setting, policy, or risk-derived?** — *PRD doesn't specify*. Mockup hardcodes 25% caution line. **Blocking for Concentration dashboard `caution_pct` semantics** — Recommend policy constant (25%) with future override per risk band.

11. **NIDP connection indicator: real health check or brand label?** — *Existing endpoint*: `GET /v1/intelligence/portfolio/sync/status`. *Answer*: surface real staleness. Non-blocking.

12. **Tax harvest expiry timer semantics: FY-end or per-lot?** — *PRD doesn't specify*. Mockup shows "DAYS LEFT 41" which is FY-end (Mar 31). Server should expose `days_to_fy_end` AND per-lot `eligible_after_date` for fine-grained reasoning. Non-blocking.

13. *(new)* **Insight `Needs-info` variant routing** — PRD §6.2 says insights lacking data render as a `Needs-info` card pointing at what to provide. No endpoint surfaces this state today. Add `insight.state: "computed"|"needs_info"|"unavailable"` with a `needs_info.required: [string]` field. Non-blocking but adds value.

14. *(new)* **Per-action `verb` vocabulary** — PRD §7.4 distinguishes stock verbs (Add/Exit/Trim/Hold) from fund verbs (Switch/Exit/Add/Merge/Hold). The server must emit the correct verb per asset_type; today the client maps `type` to verb. Non-blocking but listed in Finding C.2.

15. *(new)* **Source-domain back-link on Plan Board** — PRD §8.1 requires a tap on a Plan Board action to return to its origin dashboard. Requires `source_domain` (Finding C.2) + a deep-link convention.

---

## Section E — Summary Counts

| Status | Count | % of mapped rows |
|---|---|---|
| ✅ Exact match | 47 | 35% |
| ⚠️ Partial match | 50 | 37% |
| ❌ Missing | 24 | 18% |
| N/A (UI-only) | 14 | 10% |
| 🗑️ Redundant | 0 | 0% |
| **Total mapped rows** | **135** | **100%** |

(Counted from Section B tables across all 17 screens.)

### Estimated change scope for Phase 2

- **New endpoints**: 12
  - `GET /api/dashboards/{type}` (composite, ×6 types)
  - `GET /api/recommendations/stocks?profile=`
  - `GET /api/funds/{id}/v3-score` (user-scope demotion)
  - `GET /api/portfolio/tax-summary`
  - `GET /api/intelligence/portfolio/360` (client-360 6-domain rollup)
  - `GET /api/advisor/sip-board` + `/api/advisor/sip-board/summary`
  - `GET /api/advisor/summary` (book KPIs)
  - `GET /api/mfd/profiles/{id}/needs-attention`
  - `POST /api/mfd/profiles/{id}/review-pack/generate`
  - `POST /api/mfd/profiles/{id}/call-log`
  - `POST /api/mfd/profiles/{id}/sip-nudge`
  - `POST /api/plans/active/actions` (cross-domain action creation)
  - `PATCH /api/plans/{plan_id}/actions/{action_id}/discuss` (advisor-side)

- **Modified endpoints**: 9
  - `/api/plans/active` — add `?source_domain=` filter, add per-action fields (Finding C.2)
  - `/api/plans/active/health-projection` — add per-action breakdown
  - `/api/insights/v3-portfolio` — collapse grade 7→4 server-side
  - `/api/portfolio/risk-analytics` — add `max_drawdown_pct`, expose VaR inline
  - `/api/portfolio/exposure/concentration` — add `top5_pct`, `caution_pct`
  - `/api/portfolio/exposure/fund-overlap/matrix` — add `unique_stocks_count`
  - `/api/portfolio/fund-performance` — add `?period=3y&benchmark=index`
  - `/api/portfolio-builder/generate` — accept `{monthly_surplus, horizon_years, risk_bucket}`; return per-instrument `cap_pct`
  - `/api/portfolio/sips` — add mandate / bounce-reason / step-up fields
  - `/api/mfd/profiles` — add `health_score`, `last_seen_days`, `top_issue_label`, `band`

- **Fields to add**: ~25 (across the schema gaps)

- **Fields to deprecate**: 3 (peer-avg benchmark naming, hardcoded LTCG limit, lowercase status)

- **Endpoints to deprecate**: 1 (`POST /api/copilot/widgets/tax_timing` duplicate registration — delete the dead one)

### High-risk areas requiring deepest design attention in Phase 2

1. **Recommendation entity schema** (Finding C.2) — affects 8 screens producing/consuming actions; biggest blast radius.
2. **Plan-projection per-action delta** (Finding C.6) — required for live-on-accept animations across all 6 dashboards.
3. **NIDP boundary for greenfield stock discovery** (Finding C.3) — touches `screening engine` ownership.
4. **Goals → Plan integration** (Screen 09 + Finding C.5) — decoupled today; unblocks Goals matrix + Tax matrix.
5. **Advisor SIP-board** (Screen 17) — single largest cluster of missing endpoints + blocking PRD open questions (§13.2).
6. **Status drift fixes** (Finding C.8) — non-additive (would change existing behaviour); must coordinate with mobile client.

---

## Section F — Phase Gate

**Status**: ✅ **Phase 1 complete**
**Awaiting**: Approval to proceed to Phase 2 (Design Proposal — `docs/api-changes.md` + `nivesh-postman-collection.v2.json`)

**Blocking questions from Section D that must be answered before Phase 2 can proceed:**
- **Q7**: SIP execution path (BSE Star vs MFU vs broker hand-off) — blocks Builder Screen 12 "Accept & register SIPs" + SIP Board Screen 17 "Retry" semantics. Decision needed: ship Phase 2 with these as deferred (read-only / nudge-only), or wait for Q7 resolution.
- **Q8**: Broker connect scope — blocks Onboarding Screen 03 broker tile. Decision needed: drop from v4 (per project memory recommendation), or scope hosted OpenAlgo.

**Non-blocking questions that should be answered alongside Phase 2 design:**
- Q10: Concentration `caution_pct` semantics (policy constant vs risk-band-derived).
- New Q13: Insight `Needs-info` variant — additive, low-risk to defer.

**Side findings worth surfacing for independent fixes (not part of v4 scope but discovered during this analysis):**
1. ₹1L LTCG limit hardcoded — should be ₹1,25,000 per Jul-2024 tax law (Finding C.8)
2. `tax_timing` route registered twice — delete the dead registration (Finding C.8)
3. HOLD action status drift — lowercase "pending" vs UPPERCASE validator (Finding C.8)
4. FLAG action path uses `id` not `action_id` — normalise (Finding C.8)
5. `/api/intelligence/v3-score/{id}` is admin-gated despite being the natural user-callable fund score (Finding C.8)
6. `/api/portfolio/deep-analytics` documentation drift — fix API_INVENTORY (Finding C.8)

**Phase 1 ends here. STOP. Await explicit approval before Phase 2.**
