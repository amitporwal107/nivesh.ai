# Functional Requirements Document — NIVESH V1 FRONTEND
**Layer:** Nivesh V1 Frontend (Base UI Layer)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `/app/frontend/src/pages/`, `/app/frontend/src/components/`, `/app/frontend/src/App.js`, `/app/frontend/src/components/Sidebar.js`

---

## DOCUMENT NOTES — What "V1 Frontend" Means

> **V1 Frontend** covers the original retail investor UI: landing page, Google OAuth, portfolio overview, holdings management, basic insights, risk profiling, CAS upload, and onboarding. These components existed before the Plan Board (V2 surface) and copilot were introduced.
>
> **V2 Frontend** (see `FRD_V2_FRONTEND.md`) covers: Plan Board (`/components/v2/`), V3 score displays, decision cards, portfolio intelligence.
>
> Both V1 and V2 UI components live in the same React 19 app; the distinction is the tab/surface they appear on.

**Tech Stack:**
- React 19.0.0 + React Router 7.5.1
- Tailwind CSS 3.4.17 + Shadcn UI (Radix primitives)
- Recharts (data visualisation), Framer Motion (animations)
- TanStack Query / Axios for API calls
- Capacitor 7 (iOS/Android — scaffolded)
- Create React App + Craco build

---

## 1. Module: Routing & Application Shell

### FR-FE-SHELL-001 — Application Routing
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-SHELL-001 |
| **Module** | Application Shell |
| **Feature** | Client-Side Routing |
| **Priority** | Critical |
| **Source** | `src/App.js` |
| **Status** | Live |

**Route Map:**
| Path | Component | Auth Required |
|---|---|---|
| `/` | `Landing` | No |
| `/dashboard` | `Dashboard` (ProtectedRoute) | Yes |
| `/privacy` | `Privacy` | No |
| `/cas-callback` | `CasCallback` | No |
| `/cas-connect/:token` | `CasConnect` | No |
| `/nidp` | `NidpConsole` | Yes (Admin) |
| `*` | Redirect to `/` | — |

**Business Rules:**
- `ProtectedRoute` reads auth state from `AuthContext`; unauthenticated users are redirected to `/`
- Dashboard uses URL hash for tab navigation (`/dashboard#overview`, `#plan_board`, etc.) — shareable and back-button safe
- `/cas-connect/:token` is a public invite flow — no auth required

---

### FR-FE-SHELL-002 — Navigation Sidebar
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-SHELL-002 |
| **Module** | Application Shell |
| **Feature** | Tab Navigation |
| **Priority** | Critical |
| **Source** | `src/components/Sidebar.js` |
| **Status** | Live |

**Retail User Navigation Tabs (INDIVIDUAL workspace):**
| Tab ID | Label | Badge | Component |
|---|---|---|---|
| `overview` | Dashboard | — | DashboardOverview |
| `market` | Market | — | MarketDashboard |
| `strategy_builder` | Strategy Builder | BETA | StrategyBuilder |
| `plan_board` | Plan Board | V2 | PlanBoardView |
| `portfolio` | Portfolio | — | ActionablePortfolioView |
| `insights` | Insights | — | InsightsView |
| `goals` | Goals | — | GoalsView |

**Advisor Navigation Tabs (ADVISORY workspace, no client selected):**
- Advisor (MFD client list), Market, Strategy Builder

**Client-Context Tabs (ADVISORY, client impersonated):**
- Back-to-clients banner, Client 360, same retail tabs

**Acceptance Criteria:**
- Tab click updates URL hash; page refreshes/back-button preserves tab state
- "V2" badge visible on Plan Board tab
- "BETA" badge visible on Strategy Builder
- Advisor workspace shows MFD-specific tabs when `workspaceType = "ADVISORY"`

---

### FR-FE-SHELL-003 — Authentication Context
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-SHELL-003 |
| **Module** | Application Shell |
| **Feature** | Auth State Management |
| **Priority** | Critical |
| **Source** | `src/context/AuthContext.js` |
| **Status** | Live |

**Context Provides:**
- `user` — current user object (null if unauthenticated)
- `loading` — auth check in progress
- `googleClientId` — fetched from `GET /api/auth/google-client-id`
- `loginWithGoogle(credential)` — calls `POST /api/auth/google`
- `logout()` — calls `POST /api/auth/logout`, clears local state
- `checkAuth()` — re-validates session via `GET /api/auth/me`

---

## 2. Module: Landing Page

### FR-FE-LAND-001 — Public Landing Page
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-LAND-001 |
| **Module** | Landing |
| **Feature** | Hero CTA + Social Proof |
| **Priority** | Critical |
| **Source** | `src/pages/Landing.js` |
| **Status** | Live |

**Page Sections:**
1. **Hero** — Primary CTA: "Import Your Portfolio" (NOT "Sign Up")
2. **Score Preview Cards** — 4 sample score cards (Quality, Risk, Exit, Add) as social proof
3. **Feature Grid** — 6 feature highlights: Know what you own / Clear actions / Spot risks / AI copilot / Goals / Tax-smart
4. **Before/After Example** — optimisation illustration for a sample portfolio
5. **3-Step Flow CTA** — Connect → Analyze → Optimize
6. **Google Sign-In button** — top-right corner (secondary CTA, not hero)

**Business Rules (from ONBOARDING_STRATEGY.md, validated against code):**
- ONE dominant CTA only ("Import Your Portfolio")
- Google Sign-In is not the hero — lives in top-right
- Trust builders on every import screen: "Read-only · AES-256 encrypted · No trading · No bank access · Delete anytime"

**Acceptance Criteria:**
- Unauthenticated user sees landing page
- Authenticated user redirected to `/dashboard`
- Google Sign-In button visible and functional
- Trust messaging visible without scrolling on mobile

---

## 3. Module: Dashboard Overview (V1 Home)

### FR-FE-DASH-001 — Portfolio Summary Dashboard
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-DASH-001 |
| **Module** | Dashboard |
| **Feature** | Overview Tab |
| **Priority** | Critical |
| **Source** | `src/components/DashboardOverview.js` |
| **Status** | Live |

**Sections Displayed:**
1. **Portfolio Allocation Pie Chart** — equity/debt/gold/other breakdown
2. **Asset Class Breakdown** — cards per asset type with value + %, collapsible
3. **Health Score Metrics** — 0-100 score with letter grade (A+ to F), 5 component bars
4. **Holdings Heatmap** — grid of holdings colour-coded by return % (green/red gradient)
5. **Top Holdings** — ranked by current value with P&L indicators

**Interactive Behaviours:**
- Collapsible sections with localStorage persistence (state preserved across page refreshes)
- Drag-to-resize section heights
- InfoTooltip on every metric with plain-English explanation
- "Simulated" badge on assumed/estimated data
- Responsive layout: single column on mobile, 2-column on tablet+

**API Calls:**
- `GET /api/portfolio/holdings` — holdings with current prices
- `GET /api/intelligence/portfolio` — asset allocation + concentration data
- Health score computed from portfolio intelligence data

**Acceptance Criteria:**
- Empty portfolio → empty state with CTA to upload CAS
- Portfolio with holdings → pie chart renders with correct percentages
- Collapse/expand state persists after page refresh (localStorage)
- Heatmap shows red for negative returns, green for positive

---

## 4. Module: Portfolio Management (V1 Holdings UI)

### FR-FE-PORT-001 — Holdings Table (Actionable Portfolio View)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-PORT-001 |
| **Module** | Portfolio |
| **Feature** | Interactive Holdings Table |
| **Priority** | Critical |
| **Source** | `src/components/PortfolioView.js`, `ActionablePortfolioView.js` |
| **Status** | Live |

**Table Columns:**
- Holding name, ticker/ISIN
- Asset type
- Quantity, buy price, current price
- P&L (absolute + %)
- Buy date (inline editable)
- Sector, category
- Action buttons (Edit, Delete)

**Filters Available:**
- Asset type filter: Equity / MF / ETF / Bond / Gold / FD
- Sector filter: IT / Banking / Pharma / FMCG / etc.

**Interactive Features:**
- **Inline buy-date editing** — click date → date picker → save/cancel (Enter/Escape keyboard support)
- **Add holding modal** — form with validation
- **Edit holding modal** — same form pre-populated
- **Delete holding** — confirmation required
- **CAS import button** — triggers upload modal
- **Export CSV** — `GET /api/portfolio/export/csv`
- **Positional picks** — shows recommendations from positional engine (if any)

**Acceptance Criteria:**
- Holdings table renders all user holdings
- Asset type filter narrows visible rows
- Inline date edit updates buy_date via `PUT /api/portfolio/holdings/{id}`
- Delete removes holding from table without page refresh
- CSV export downloads file with all holdings

---

### FR-FE-PORT-002 — CAS Upload Flow
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-PORT-002 |
| **Module** | Portfolio |
| **Feature** | CAS Import Modal |
| **Priority** | Critical |
| **Source** | Multiple components (modal triggered from portfolio tab) |
| **Status** | Live |

**Upload Steps:**
1. Drag-and-drop or file picker — PDF only, max 25 MB
2. Password hint shown: "Your CAS password is typically your PAN in UPPERCASE"
3. Upload progress indicator
4. Parse result confirmation: "Found X holdings" or "Error: [provider-specific message]"
5. Smart error recovery: "We found 92% of your portfolio. Help us verify 2 entries." (never "Upload failed.")

**Acceptance Criteria:**
- Non-PDF file → rejected with file type error before upload
- File > 25 MB → rejected with size error
- Successful parse → holdings count shown, user proceeds to dashboard
- Failed parse → meaningful error, not generic "Upload failed"

---

### FR-FE-PORT-003 — CAS Connect (Public Invite Wizard)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-PORT-003 |
| **Module** | Portfolio |
| **Feature** | Standalone CAS Import Wizard |
| **Priority** | High |
| **Source** | `src/pages/CasConnect.jsx` |
| **Status** | Live |

**Route:** `/cas-connect/:token` (public, no auth required)

**5-Step Wizard:**
| Step | Content |
|---|---|
| 0 (Welcome) | Trust intro: what data is collected and why |
| 1 (Client Details) | Name, Mobile, Email, PAN + 3 consent checkboxes |
| 2 (Google Sign-In) | OAuth sign-in to access Gmail |
| 3 (Select CAS Emails) | Checkbox list of matching emails; auto-uses PAN as PDF password |
| 4 (Processing) | Live status polling via background job |
| Fallback | Direct PDF upload (for users without Gmail) |

**Validation Rules:**
- PAN format: `^[A-Z]{5}[0-9]{4}[A-Z]$`
- All 3 consent checkboxes mandatory to proceed
- Mobile: valid Indian mobile format
- Email: valid format

**Business Rules:**
- Token is time-limited (24 hours)
- Expired token → error screen with contact advisor CTA
- Data belongs to the MFD advisor who generated the token

**Acceptance Criteria:**
- Invalid PAN format → field error, cannot proceed
- Unchecked consent → cannot proceed to step 2
- Expired token → appropriate error, not a broken page
- Successful CAS import → holdings imported to advisor's client profile

---

## 5. Module: Risk Profile Assessment

### FR-FE-RISK-001 — Risk Questionnaire UI
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-RISK-001 |
| **Module** | Risk Profile |
| **Feature** | Interactive Risk Questionnaire |
| **Priority** | High |
| **Source** | `src/components/RiskProfileView.js` |
| **Status** | Live |

**6-Question Format:**
- Progress bar showing question number
- Radio group for each question with 4 options
- Back/Next navigation
- Final screen: risk category displayed + recommended allocation chart

**Output Display:**
- Risk category label (Aggressive / Moderately Aggressive / Moderate / Moderately Conservative / Conservative)
- Recommended asset allocation: equity % / debt % / gold % / cash % as a visual bar

**Acceptance Criteria:**
- All 6 questions must be answered to proceed to results
- Back button returns to previous question without losing answers
- Result matches backend computation (FR-USER-002)
- Allocation chart renders correctly

---

## 6. Module: Basic Insights (V1 Insights View)

### FR-FE-INS-001 — Insights Tab (V1)
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-INS-001 |
| **Module** | Insights |
| **Feature** | Portfolio Intelligence Display |
| **Priority** | Critical |
| **Source** | `src/components/InsightsView.js` |
| **Status** | Live |

**Sections Rendered:**
1. **Portfolio Intelligence Tab** (`PortfolioIntelligenceTab.jsx`) — fund overlap analysis, compression score, top stock overexposure
2. **V3 Portfolio Insights** (`V3PortfolioInsights.jsx`) — per-fund quality/health/exit/add scores
3. **AI Copilot Section** (collapsible) — scenario suggestions, what-if simulator

**Interactive Behaviours:**
- CollapsibleSection with drag-to-resize
- Focus mode: one section expands to fill viewport
- Collapse/expand state persisted in localStorage
- Each insight card shows: title, description, impact, affected funds

**Acceptance Criteria:**
- Insights section shows deterministic rules output (no LLM in this path)
- Empty portfolio → empty state with upload CTA
- Overlap pair shown when two funds share > 50% stock overlap
- Each insight shows affected fund names and concrete ₹/% values

---

## 7. Module: Goals UI

### FR-FE-GOAL-001 — Goals View
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-GOAL-001 |
| **Module** | Goals |
| **Feature** | Goal Cards + Progress |
| **Priority** | High |
| **Source** | `src/components/goals/GoalsView.jsx` |
| **Status** | Live |

**Features:**
- Create goal card (button with goal type picker)
- Goals grid: each goal shows type icon, target amount, horizon, on-track %
- Progress bar per goal
- Edit goal (modal)
- Delete goal (soft delete → status = 'abandoned')
- Financial snapshot wizard (one-time profile capture)
- Goal copilot (AI advisor per goal, separate chat history)

**Goal Type Icons:**
- Retirement 🏖, Education 🎓, Home 🏠, Emergency 💰, Wealth 📈, Custom ✨

**Acceptance Criteria:**
- Max 4 active goals — 5th creation shows "Maximum goals reached" message
- on_track_pct shown as % with colour coding (green ≥ 80%, amber 50–79%, red < 50%)
- Edit goal → Monte Carlo re-runs and on_track_pct updates
- Delete goal → removed from list, archived in backend

---

## 8. Module: MFD Advisor Workspace (V1 Advisory UI)

### FR-FE-MFD-001 — Advisor Home
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-MFD-001 |
| **Module** | MFD |
| **Feature** | Multi-Client Advisory Dashboard |
| **Priority** | High |
| **Source** | `src/components/mfd/AdvisorHomeView.jsx`, `MfdDashboard.jsx` |
| **Status** | Live |

**Four-Card Grid (Advisor Home):**
1. **Today** — clients meeting today / recently called / at risk
2. **AUM** — total AUM, top contributors, churn
3. **Underperformers** — clients lagging Nifty by ≥ N pp
4. **Rebalance** — clients off target allocation

**Client Management:**
- Searchable client list table (name, AUM, last active, plan status)
- "View Client" → enters impersonation mode (advisor sees client's full dashboard)
- "Invite Client" → generates 24h-shareable CAS upload link
- Banner shown when in client-context: "Viewing [Client Name]'s portfolio"
- "Back to clients" → deactivates impersonation

**Key MFD Components:**
- `ClientSnapshot.jsx` — Client 360 view (holdings, insights, risks, plan status)
- `CasTimeMachine.jsx` — historical portfolio snapshots per client
- `LiveEventFeed.jsx` — real-time activity feed
- `MacroBar.jsx` — market macro indicators
- `SectorHeatmap.jsx` — sector performance visualisation
- `WeekendWatchlist.jsx` — recommended holdings for review
- `TaxSnapshotInfo.jsx` — tax planning insights per client
- `MfdOnboardingWizard.jsx` — 4-step client onboarding flow

**Acceptance Criteria:**
- Advisor logs in → workspace type = ADVISORY → MFD tabs visible
- Client impersonation → all analytics show client's data, not advisor's
- "Back to clients" → advisor's own workspace restored
- Client invite link → expires after 24 hours

---

## 9. Module: Market Dashboard (V1 Market Surface)

### FR-FE-MKT-001 — Market Dashboard
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-MKT-001 |
| **Module** | Market |
| **Feature** | Market Intelligence Dashboard |
| **Priority** | High |
| **Source** | `src/components/MarketDashboard.jsx` (via `#market` tab) |
| **Status** | Live |

**Sections:**
1. **Deploy Verdict Strip** — AGGRESSIVE / NORMAL / CAUTIOUS / DEFENSIVE + 5 number tiles
2. **Macro Bar** — US yields, crude, INR/USD, FII/DII flows, India VIX
3. **Today's Strategy Card** — regime-aware trade posture
4. **Sector Heatmap** — 12 sectors with RS vs Nifty (HOT/WARM/COOL/COLD)
5. **Positional Top Picks** — BTST signals from ChartInk scans
6. **Trade Journal** — open/closed positional trades with P&L

**Live Readiness Chips (per pick):**
- 🟢 TRIGGERED — LTP at or above entry
- 🟡 NEAR — within 2% of entry
- WAIT / FAR — below entry
- 🔴 STOPPED — LTP at or below stop-loss

**Cache:** 30s during market hours (9:15–15:30 IST), 5 min after-hours

---

## 10. Module: Number Format & Theme

### FR-FE-UTIL-001 — INR Number Formatting
| Field | Value |
|---|---|
| **Requirement ID** | FR-FE-UTIL-001 |
| **Module** | Utilities |
| **Feature** | Indian Number Formatting |
| **Priority** | High |
| **Source** | `src/context/NumberFormatContext.js` |
| **Status** | Live |

**Format Rules:**
- All monetary values in INR with Indian comma system (e.g., ₹1,23,456)
- Crores displayed as "₹1.23Cr"
- Lakhs as "₹12.3L"
- Percentages: 1 decimal place
- Context provider wraps entire app; format functions available via `useNumberFormat()`

---

## 11. Gap Analysis — V1 Frontend (Docs vs Code)

| Documented Feature | Code Status | Notes |
|---|---|---|
| Mobile OTP login screen | **NOT FOUND** | Only Google OAuth in Landing.js |
| Biometric auth (FaceID/fingerprint) | **NOT IMPLEMENTED** | Capacitor scaffolded; biometric plugin not installed |
| Deep-link handling for CAS callback | **PARTIAL** | `/cas-callback` route exists; deep-link handling incomplete |
| Push notifications | **NOT IMPLEMENTED** | Capacitor scaffolded only |
| WhatsApp forward CAS import (P3) | **NOT IMPLEMENTED** | Not in any component |
| Dark mode | **PARTIAL** | Tailwind dark: prefixes present; ThemeContext exists but toggle UI not prominent |

---

## 12. Requirement Traceability Matrix

| Req ID | Feature | Status | Component | API Endpoint | Priority |
|---|---|---|---|---|---|
| FR-FE-SHELL-001 | Routing | IMPLEMENTED | App.js | — | Critical |
| FR-FE-SHELL-002 | Sidebar Nav | IMPLEMENTED | Sidebar.js | — | Critical |
| FR-FE-SHELL-003 | Auth Context | IMPLEMENTED | AuthContext.js | GET /api/auth/me | Critical |
| FR-FE-LAND-001 | Landing Page | IMPLEMENTED | Landing.js | — | Critical |
| FR-FE-DASH-001 | Overview Tab | IMPLEMENTED | DashboardOverview.js | GET /api/portfolio/holdings | Critical |
| FR-FE-PORT-001 | Holdings Table | IMPLEMENTED | PortfolioView.js | GET/PUT/DELETE /api/portfolio/holdings | Critical |
| FR-FE-PORT-002 | CAS Upload | IMPLEMENTED | (upload modal) | POST /api/portfolio/cas-upload | Critical |
| FR-FE-PORT-003 | CAS Connect Wizard | IMPLEMENTED | CasConnect.jsx | POST /api/public/cas-invite/* | High |
| FR-FE-RISK-001 | Risk Questionnaire | IMPLEMENTED | RiskProfileView.js | POST /api/user/risk-profile | High |
| FR-FE-INS-001 | Insights Tab | IMPLEMENTED | InsightsView.js | POST /api/insights/generate | Critical |
| FR-FE-GOAL-001 | Goals View | IMPLEMENTED | GoalsView.jsx | POST/GET /api/goals | High |
| FR-FE-MFD-001 | Advisor Home | IMPLEMENTED | MfdDashboard.jsx | GET /api/mfd/clients | High |
| FR-FE-MKT-001 | Market Dashboard | IMPLEMENTED | MarketDashboard.jsx | GET /api/positional/market-dashboard | High |
| FR-FE-UTIL-001 | Number Format | IMPLEMENTED | NumberFormatContext.js | — | High |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`.*
