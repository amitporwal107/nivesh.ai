# Functional Use Cases — Nivesh.ai V2 Frontend

This document describes every screen, what it offers to the user, and exactly how the user navigates from one screen to another. Written as functional use cases in plain English.

---

## UC-01: Visitor Lands on Homepage

**Screen:** Homepage (`/`)  
**Actor:** Unauthenticated visitor (or returning logged-in user)  
**Entry:** Direct URL, search engine, or marketing link

### What the screen offers

- A top navigation bar with links: **Product**, **For advisors**, **Pricing**, and **Sign in**.
- A hero section with the headline *"Your portfolio, finally legible"* and a subline explaining the product.
- Two CTA buttons: **"Check my portfolio free"** (primary) and **"Watch 90-second tour"** (secondary).
- A **Portfolio Health Preview Card** that shows:
  - If the user is logged in: their real health score (0–100), letter grade (A/B/C/D), six dimension bars (risk, concentration, diversification, cost, tax, goals), and top 3 insights.
  - If not logged in: placeholder bars and a *"Sign in to see your insights"* prompt.
- A **Feature Trio** section with three cards: "Read every holding" → "Score across 20 checks" → "Show you what to do".
- A bottom CTA repeating **"Check my portfolio"**.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Sign in"** in the top nav | Login page (`/login`) | Always |
| Clicks **"Check my portfolio free"** (hero CTA) | Login page (`/login`) | Always |
| Clicks **"Check my portfolio"** (bottom CTA) | Login page (`/login`) | Always |
| Clicks **"Watch 90-second tour"** | No navigation (video modal or external link) | Always |

---

## UC-02: User Signs In

**Screen:** Login (`/login`)  
**Actor:** New or returning user  
**Entry:** From Homepage CTA, or direct URL, or redirect after session expiry

### What the screen offers

A two-column layout:

**Left column (editorial):**
- Nivesh branding and logo.
- For a **new user**: generic welcome headline.
- For a **returning user**: personalized *"Welcome back, {name}."* greeting plus three KPI cards showing their last-known Health Score, AUM (total portfolio value), and number of actionable insights.

**Right column (auth form):**
- **Google Sign-In button** — one-click OAuth via Google Identity Services. Shows "Loading..." while GIS SDK initializes, "Signing in..." during the auth call.
- A divider labelled "WHITELISTED EMAIL".
- **Magic Link section** — an email input field with real-time domain validation. Displays an **ALLOWED** (green) or **BLOCKED** (red) badge based on the email domain. Allowed domains: `gmail.com`, `googlemail.com`. When allowed, a **"Send magic link"** button becomes active.
- Security footer: *"ENCRYPTED · NEVER STORED · ARN-128459"*.

**Error states:**
- If the Google SDK fails to load: *"Google Sign-In failed to load"* message.
- If sign-in fails: toast notification with the error.
- If magic link succeeds: toast confirming the email was sent.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Completes Google Sign-In | Dashboard (`/dashboard`) | User's `onboarding_completed` is `true` |
| Completes Google Sign-In | Onboarding (`/onboarding`) | User's `onboarding_completed` is `false` (first-time user) |
| Clicks "Send magic link" | Stays on login (toast confirms email sent) | User receives link in email, clicks it to authenticate |

**Routing logic after authentication:**
```
if (user.onboardingCompleted === true)  → navigate("/dashboard")
if (user.onboardingCompleted === false) → navigate("/onboarding")
```

---

## UC-03: First-Time User Imports Investments (Onboarding)

**Screen:** Onboarding (`/onboarding`)  
**Actor:** First-time authenticated user  
**Entry:** Automatic redirect after first sign-in (UC-02)

### What the screen offers

A stepper at the top shows this is **Step 2 of 4** ("Connect investments"). Below it, three method cards the user can choose from:

#### Method 1: Gmail CAS Import (default)
- Description: *"Authorize Gmail → system scans for CAS/eCAS emails → auto-parses holdings"*.
- Shows the three OAuth scopes being requested:
  1. Read messages with CAS/eCAS/CAMS keywords
  2. Download PDF attachments under 5 MB
  3. Identity (email + display name)
- **"Authorize with Google"** button to trigger Gmail OAuth.
- Security note: *"OAuth 2.0, revocable anytime, India-hosted"*.
- Estimated time: ~30 seconds.

#### Method 2: CAS Upload (NSDL/CDSL)
- A drag-and-drop zone (or file browse button) accepting PDF files up to 10 MB.
- Optional password field for encrypted PDFs.
- Upload progress bar with percentage and status text (QUEUED → PARSING → COMPLETED or FAILED).
- On success: green checkmark with confirmation.
- On failure: error message with reason and *"Try a different file or check the password"*.
- Helper link to request a CAS statement.
- Estimated time: ~2 minutes.

#### Method 3: CDSL OTP (real-time)
- Form fields: PAN input, mobile number (+91), and a 6-digit OTP input.
- **"Verify & fetch holdings"** button.
- Security disclaimer: *"CDSL/NSDL/SEBI-compliant, we never store your OTP"*.
- Estimated time: ~60 seconds.

**Footer actions:**
- **"Skip for now · add later"** — skips import entirely.
- **"Back"** button — goes to the previous page.
- **"Continue · Goals →"** — proceeds after a successful import.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Successfully imports via any method, clicks **"Continue · Goals →"** | Dashboard (`/dashboard`) | Import completed |
| Clicks **"Skip for now · add later"** | Dashboard (`/dashboard`) | Always (skips import) |
| Clicks **"Back"** | Previous page (`navigate(-1)`) | Always |

---

## UC-04: User Views Dashboard (Main Hub)

**Screen:** Dashboard (`/dashboard`)  
**Actor:** Authenticated user with or without portfolio data  
**Entry:** After login/onboarding, or via sidebar "Overview" link

### What the screen offers

This is the main hub of the application. From here, the user can access every other feature.

**Header:**
- Eyebrow label: *"Dashboard"*.
- Dynamic headline based on health score: *"Your portfolio is {tone} {phrase}"* (e.g., "Your portfolio is mostly healthy").
- Sub-headline showing the top insight or an onboarding prompt.

**Hero Card — 3 columns:**

| Column | Content |
|---|---|
| **Portfolio Value** | Total AUM in ₹ (e.g., "₹24.8 L"), year-over-year change with arrow and %, a mini sparkline area chart of NAV history |
| **Health Score** | Score 0–100 with a circular progress ring, letter grade (A/B/C/D), verdict text (e.g., "Excellent — keep it up") |
| **Risk Meter** | Risk bucket name (Very low / Low / Moderate / High / Very high), visual gauge (level 1–5) |

**Top Insights section:**
- Count badge: *"{N} insights · plain English"*.
- Up to 3–5 insight cards, each showing:
  - Colored left border (green = good, amber = warning, red = urgent).
  - Insight title in bold.
  - Source domain in mono (e.g., "CONCENTRATION", "TAX").
  - Right arrow indicating it's clickable.

**Improve CTA (dark card at the bottom):**
- Shows current score and projected target score.
- Text: *"Take your score from {current} → {target} in {N} moves"*.
- **"Improve portfolio"** button.

**Empty state (no portfolio data):**
- Message prompting the user to upload a statement.
- Link to go to Onboarding.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks any **insight card** | Recommendations (`/recommendations?focus={recId}`) | Always — deep-links to the specific recommendation |
| Clicks **"Improve portfolio"** CTA button | Recommendations (`/recommendations`) | Always |
| Clicks **"Upload a statement"** (empty state) | Onboarding (`/onboarding`) | Only when portfolio is empty |
| Uses **sidebar** navigation | Any sidebar destination (see UC-11) | Always |

---

## UC-05: User Explores Portfolio Holdings

**Screen:** Portfolio (`/portfolio`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Portfolio builder"

### What the screen offers

**Header:**
- Eyebrow: *"Portfolio"*.
- Headline: *"{count} holdings, {total value}"* (e.g., "12 holdings, ₹24.8 L").

**KPI strip (4 cards):**

| KPI | Example |
|---|---|
| Market value | ₹24.8 L |
| Invested (+ holding count) | ₹18.2 L · 12 holdings |
| P&L (signed, color-coded) | +₹6.6 L (+36.2%) |
| Monthly SIP total | ₹25,000/mo |

**Tabbed content:**

**Tab 1 — Holdings (default):**
- A table listing every holding with columns: Fund name, Category, Current value, Units, P&L, SIP amount.
- Each fund name is clickable → navigates to Fund Details.

**Tab 2 — Allocation:**
- A donut chart showing allocation by asset class (Equity, Debt, Hybrid, etc.).
- A list below the chart: color dot + asset class label + percentage + ₹ value.

**Tab 3 — SIPs:**
- Header: "Active SIPs" with a badge showing total monthly SIP.
- List of funds with active SIPs: fund name, start date, monthly amount.

**Empty state:**
- *"No holdings found"* with a **"Connect investments"** link.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks a **fund name** in the Holdings table | Fund Details (`/funds/{fundId}`) | Always |
| Clicks **"Connect investments"** (empty state) | Onboarding (`/onboarding`) | Only when holdings list is empty |
| Switches **tabs** (Holdings / Allocation / SIPs) | Same page — content changes in-place | Always |

---

## UC-06: User Views Fund Details

**Screen:** Fund Details (`/funds/:id`)  
**Actor:** Authenticated user  
**Entry:** Clicking a fund name from the Portfolio Holdings table (UC-05)

### What the screen offers

**Header:**
- Eyebrow: *"Fund"*.
- Category badge (e.g., "EQUITY LARGE CAP").
- Fund name as a large headline.
- Metadata row: AMC name · ISIN · AMFI code.

**KPI strip (4 cards):**

| KPI | Example |
|---|---|
| Your value | ₹3.2 L (142.5 units) |
| Invested | ₹2.4 L (since Mar 2021) |
| Returns | +₹80,000 (+33.3%) |
| NAV | ₹224.50 (as of 27 May 2026) |

**Returns card (left column):**
- Annualized returns for 6 periods: 1M, 3M, 6M, 1Y, 3Y, 5Y.
- Each period shows the percentage in green (positive) or red (negative).
- Footer: CAGR value.

**Risk card (right column):**
- Risk meter visualization (1–5 level gauge).
- Expense ratio: percentage + "Annual · direct plan".

**Active SIP card (conditional):**
- Only shown if this fund has an active SIP.
- Monthly amount and start date.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Back to portfolio"** (empty/error state) | Portfolio (`/portfolio`) | If fund ID doesn't match any holding |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-07: User Reviews Recommendations

**Screen:** Recommendations (`/recommendations`)  
**Actor:** Authenticated user  
**Entry:** Dashboard insight card click, Dashboard "Improve portfolio" CTA, Concentration "See the fix" button, or sidebar "Recommendations" link

### What the screen offers

**Header:**
- Eyebrow: *"Recommendations"*.
- Headline: *"3 categories, {count} moves"*.
- Description: *"We never push trades — these are suggestions ranked by impact."*

**Filter tabs:**
- **All** · {count} — shows every recommendation.
- **Keep** · {count} — holdings that are fine, no action needed.
- **Reduce** · {count} — holdings to trim or exit.
- **Add** · {count} — new investments to consider.

**Recommendation cards (grid):**
Each card shows:
- **Action badge**: KEEP (neutral), REDUCE/SELL (red), BUY/ADD (green).
- **Title**: the holding or action name.
- **Why**: plain-English explanation of the rationale.
- **Benefit**: what the user gains (e.g., "Save ₹8,400/yr in fees").
- **Risk impact**: how portfolio risk changes.
- **Suggested action**: specific instruction (e.g., "Sell ₹74,000 of HDFC Mid-Cap").
- **Health delta**: expected health score change (e.g., "+3 pts").
- **"Apply" button**: triggers the recommendation (mutation with pending state).

**Query parameter support:**
- `/recommendations?focus={recId}` — auto-scrolls to and highlights a specific recommendation (used when arriving from a Dashboard insight click).

**Empty state:**
- Shown when the portfolio is healthy and no recommendations exist.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Apply"** on a card | Stays on page — triggers backend mutation, button shows pending state | Always |
| Switches **filter tabs** | Same page — list filters in-place | Always |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-08: User Chats with AI Copilot

**Screen:** Chat (`/chat`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Chat copilot", or mobile bottom nav → "Chat"

### What the screen offers

**Header:**
- Eyebrow: *"Chat"*.
- Headline: *"Ask anything about your portfolio"*.

**Initial state (no messages yet):**
- 4 **suggested prompt buttons** (fetched from API, e.g., *"Why is my score 74?"*, *"Which funds overlap most?"*, *"Am I paying too much in fees?"*, *"What should I sell first?"*).
- Skeleton loaders shown while prompts are loading.
- A "Ready" badge with: *"Pick a question above or type your own..."*.

**Active chat state:**
- **User messages**: right-aligned, light background.
- **AI messages**: left-aligned with Nivesh icon, larger text.
- **Typing indicator**: 3 animated dots while the AI is generating a response.
- Messages scroll automatically to the latest.

**Composer (sticky at the bottom):**
- Plus icon (left).
- Text input field with placeholder: *"Ask anything..."*.
- Send button (blue, right).
- Error message displayed below composer if send fails.

**Session management:**
- A chat session is created lazily on the first message send (not on page load).
- Subsequent messages use the same session ID.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks a **suggested prompt** | Stays on page — prompt text fills the composer, user can edit or send | Always |
| Types and hits **Enter** or clicks **Send** | Stays on page — message appears in chat, AI responds | Always |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-09: User Tracks Goals

**Screen:** Goals (`/goals`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Goals"

### What the screen offers

**Header:**
- Eyebrow: *"Dashboard · goals"*.
- Headline with insight text or *"X of Y goals on track"*.
- Status badge: GOOD / WATCH / ATTENTION / INFO.

**KPI strip (up to 4 cards, dynamic from API):**
- Tiles showing relevant goal metrics (e.g., total funded, gap, monthly SIP needed).

**Main content — 2 columns:**

**Left column — Trajectory Chart:**
- An SVG fan chart showing the projected growth path.
- Confidence bands at 68% and 95%.
- A dashed "required" line showing the target.
- Goal markers (circles) — green if on track, red/amber if at risk.
- X-axis: years. Y-axis: ₹ Cr labels.

**Right column — Focus Panel (highlighted goal):**
- Auto-selects the first at-risk goal (or first goal if all are on track).
- Shows: goal name with icon, target amount + date, progress bar with percentage.
- 4 metric tiles: On hand, Required, Monthly SIP, Gap (shortfall).
- **"Suggest fix →"** button — shown if the goal is behind schedule.

**All Goals Table:**
- Columns: Goal name, Target date, Target amount, Funded %, Monthly SIP, Status.
- Status badges: **DONE** (green), **ON TRACK** (green), **BEHIND** (red/amber).
- Hoverable rows.
- **"+ Add goal"** button in the table header.

**Suggested Moves (conditional):**
- If the API returns goal-related moves, a card shows recommendations with impact estimates.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Suggest fix →"** on an at-risk goal | Recommendations (`/recommendations`) | Goal is behind schedule |
| Clicks **"+ Add goal"** | Not yet implemented (placeholder) | — |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10: User Analyses Risk

**Screen:** Risk (`/risk`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Risk"

### What the screen offers

**Header:**
- Eyebrow: *"Risk analysis"*.
- Headline in amber/warning color: *"One bad quarter could cost ₹{amount}"*.
- Description: *"That's the 95th-percentile worst case..."*.
- **ATTENTION** badge.

**KPI strip (4 cards):**

| KPI | Description |
|---|---|
| VaR 95% 1Y | Value at Risk — maximum expected loss in 1 year at 95% confidence |
| Volatility | Annualized portfolio volatility % |
| Max drawdown | Worst historical peak-to-trough decline % |
| Beta | Portfolio beta vs NIFTY 500 benchmark |

**Risk Drivers card:**
- Label: *"What's making it risky · share of σ"*.
- A ranked list of the biggest contributors to portfolio risk.
- Each item: name, a capacity bar showing contribution share, percentage.

**Stress Scenarios table:**
- Columns: Scenario, Portfolio impact, Benchmark impact, Recovery time.
- 5 pre-defined scenarios (e.g., 2008 crash, COVID-19 drop, rate hike, etc.).
- Portfolio impact % is color-coded: red (severe), amber (moderate), green (mild).

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| This is a read-only analysis view — no outbound navigation buttons | — | — |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10a: User Analyses Concentration

**Screen:** Concentration (`/concentration`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Concentration"

### What the screen offers

**Header:**
- Eyebrow: *"Risk · concentration"*.
- Headline in red: *"One in three rupees sits in {top sector}"*.
- Description with policy cap context.
- **ATTENTION** badge.

**KPI strip (4 cards):**

| KPI | Description |
|---|---|
| Top sector | Largest sector exposure (% + name) |
| Top stock | Largest single-stock exposure (% + name) |
| Over policy | Count of sectors exceeding the policy cap |
| HHI | Herfindahl-Hirschman Index (concentration metric) |

**Sector Exposure Treemap:**
- A treemap visualization of all sectors. Over-capped sectors are highlighted.

**Allocation vs Cap table:**
- Columns: Sector name, Capacity bar (with cap line overlay), Actual %, Status.
- Status: *"+Xpt over"* (red) or *"within"* (gray).

**Easy Fix CTA (dark card):**
- Recommended action: *"Trim {top stock}. Bring {sector} from X% to Y%"*.
- **"See the fix →"** button.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"See the fix →"** | Recommendations (`/recommendations`) | Always |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10b: User Analyses Diversification

**Screen:** Diversification (`/diversification`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Diversification"

### What the screen offers

**Header:**
- Eyebrow: *"Risk · diversification"*.
- Headline in red: *"{count} pairs are nearly the same trade"*.
- Description about redundant holdings costing fees.

**KPI strip (4 cards):**

| KPI | Description |
|---|---|
| Effective N | Number of truly distinct bets (lower = less diversified) |
| Redundant pairs | Count of fund pairs with correlation ≥ 0.85 |
| Avg cross-correlation | Average pairwise correlation (target ≤ 0.50) |
| Overlap waste | ₹ amount effectively duplicated |

**Correlation Matrix card:**
- A matrix visualization showing pairwise fund correlations.
- Badge: *"{count} hot pairs"*.
- Color legend:
  - Blue: < 0.5 (diversifying — good).
  - Amber: 0.5–0.7 (related — watchlist).
  - Red: ≥ 0.7 (redundant — action needed).

**Fund Overlap table:**
- Columns: Fund A, ↔, Fund B, Capacity bar, Overlap %.
- Color-coded by status (diversifying / related / redundant).
- Footer: *"{count} pairs analysed"*.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| This is a read-only analysis view — no outbound navigation buttons | — | — |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10c: User Views Performance

**Screen:** Performance (`/performance`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Performance"

### What the screen offers

**Header:**
- Eyebrow: *"Dashboard · performance"*.
- Headline from API or *"Your performance at a glance"*.
- Badge: GOOD / WATCH / ATTENTION / INFO.
- **Period toggle** (top-right): **1Y** / **3Y** / **5Y** buttons — switching refetches all data.

**KPI strip (up to 4 cards, dynamic from API).**

**Main content — 2 columns:**

**Left column — Attribution Waterfall:**
- An SVG waterfall chart showing what contributed to (or detracted from) returns.
- Green bars = positive contribution. Red bars = negative.
- Starts from portfolio total, breaks down into individual contributors.

**Right column — Top Contributors:**
- Ranked list of funds by contribution.
- Each item: fund name, return %, alpha contribution %.
- Color-coded: green (positive), red (negative).

**Monthly Returns Grid:**
- Grid of 6–12 month cells showing:
  - Month label.
  - Portfolio return %.
  - Benchmark return %.
  - Beat indicator dot (green = outperformed, red = underperformed).

**Suggested Moves (conditional):**
- Performance-related recommendations from the API.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **1Y / 3Y / 5Y** toggle | Same page — data refreshes for selected period | Always |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10d: User Views Tax Dashboard

**Screen:** Tax (`/tax`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Tax"

### What the screen offers

**Header:**
- Eyebrow: *"Dashboard · tax"*.
- Headline from API or *"Your tax picture, plain and simple"*.
- Badge: GOOD / WATCH / ATTENTION / INFO.

**KPI strip (up to 4 cards, dynamic from API).**

**Main content — 2 columns:**

**Left column — Tax Timeline Chart:**
- SVG bar chart: gains (amber bars, above zero line) and losses (green bars, below zero line) by month.
- Highlighted bar for the current month.

**Right column — Harvest Plan:**
- Label: *"Harvest plan"*.
- Badge: *"{count} lots flagged"*.
- List of tax-loss harvesting candidates: name, optional ticker, loss amount (red).
- Net savings tile (if data present).
- **"Schedule harvest →"** button.
- Empty state: *"No lots flagged yet"*.

**Tax Breakdown Grid (up to 4 cards):**
- Income type breakdown: label (e.g., "Short-term gains"), amount, tax rate, tax payable.

**Suggested Moves (conditional).**

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Schedule harvest →"** | Not yet implemented (placeholder) | — |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-10e: User Uses Plan Board

**Screen:** Plan (`/plan`)  
**Actor:** Authenticated user  
**Entry:** Sidebar → "Plan board"

### What the screen offers

**Header:**
- Eyebrow: *"Workspace · Plan board"*.
- Headline: *"Your plan, end-to-end"*.
- **"Export PDF"** button (secondary).
- **"Execute →"** button (primary).

**Summary Strip (conditional):**
- This week's move count, annual savings (₹, green), health impact (+X pt), cash needed, compliance status.

**4-Column Kanban Board:**

| Column | Contents |
|---|---|
| **Backlog** | Actions not yet scheduled |
| **This week** | Actions planned for this week |
| **In flight** | Actions currently being executed |
| **Done · 30d** | Actions completed in the last 30 days |

**Plan cards (within each column):**
- Action badge: SELL/SWITCH/REDUCE (red), BUY/ADD/SIP_INCREASE (green), SIP_DECREASE (amber).
- Holding name (bold).
- Optional: suggested alternative (e.g., "→ Parag Parikh Flexi Cap").
- Annual savings badge (₹, green).
- Rationale text (2-line clamp).
- Due date + owner avatar.

**Empty state:**
- *"No active plan"* headline.
- **"Generate plan →"** button.

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Export PDF"** | Not yet implemented (placeholder) | — |
| Clicks **"Execute →"** | Not yet implemented (placeholder) | — |
| Clicks **"Generate plan →"** (empty state) | Not yet implemented (placeholder) | — |
| Uses **sidebar** navigation | Any sidebar destination | Always |

---

## UC-11: Persistent Navigation (Sidebar & Mobile Nav)

**Actor:** Any authenticated user  
**Available on:** Every authenticated page

### Desktop Sidebar (always visible on screens ≥ 1024px)

The sidebar is fixed on the left (224px wide) and divided into two groups:

**DASHBOARDS group:**

| Link | Destination |
|---|---|
| Overview | `/dashboard` (UC-04) |
| Concentration | `/concentration` (UC-10a) |
| Diversification | `/diversification` (UC-10b) |
| Risk | `/risk` (UC-10) |
| Performance | `/performance` (UC-10c) |
| Goals | `/goals` (UC-09) |
| Tax | `/tax` (UC-10d) |

**WORKSPACE group:**

| Link | Destination |
|---|---|
| Plan board | `/plan` (UC-10e) |
| Portfolio builder | `/portfolio` (UC-05) |
| Chat copilot | `/chat` (UC-08) |
| Recommendations | `/recommendations` (UC-07) |

**Sidebar footer (sticky):**
- User avatar + display name.
- Portfolio label: *"₹ X.X L · NIDP ✓"*.
- Not clickable — for context only.

The currently active page is highlighted in the sidebar.

### Mobile Bottom Navigation (screens < 1024px)

A fixed bottom bar with 4 tabs:

| Tab | Destination |
|---|---|
| Home | `/dashboard` (UC-04) |
| Portfolio | `/portfolio` (UC-05) |
| Tips | `/recommendations` (UC-07) |
| Chat | `/chat` (UC-08) |

On mobile, a **Topbar** replaces the sidebar at the top showing the current page title.

---

## UC-12: User Manages Settings

**Screen:** Settings (`/settings`)  
**Actor:** Authenticated user  
**Entry:** Sidebar (if linked) or direct URL

### What the screen offers

**Header:**
- Eyebrow: *"Settings"*.
- Headline: *"Make it yours"*.
- Description: *"Pick a look, control your notifications..."*.

**Theme card:**
- Two theme buttons: **Light** and **Dark**.
- Each shows 3 color swatches previewing the theme palette.
- Selected theme has an accent highlight.
- Switching applies immediately (persisted to localStorage).

**Notifications card:**
- 4 toggle switches:
  1. *"A goal needs a top-up"* (default: on)
  2. *"Tax-saving window opens"* (default: on)
  3. *"My SIP runs each month"* (default: off)
  4. *"Daily money update"* (default: off)

**Account card:**
- Email address (read-only).
- Connection status: *"Connected · Google OAuth"*.
- **"Export my data"** link.
- **"Sign out"** button (red).

### Navigation from this screen

| User action | Destination | Condition |
|---|---|---|
| Clicks **"Sign out"** | Login page (`/login`) — session cleared, React Query cache wiped | Always |
| Clicks **"Export my data"** | Not yet implemented (placeholder) | — |
| Switches **theme** | Same page — visual theme changes in-place | Always |
| Toggles **notifications** | Same page — toggles change in-place | Always |

---

## Complete Navigation Map

Below is the master flow showing how every screen connects to every other screen:

```
                        ┌──────────┐
                        │ Homepage │
                        │  (/)     │
                        └────┬─────┘
                             │ CTA: "Check my portfolio" / "Sign in"
                             ▼
                        ┌──────────┐
                        │  Login   │
                        │ (/login) │
                        └────┬─────┘
                             │
              ┌──────────────┼──────────────┐
              │ onboarding   │              │ onboarding
              │ incomplete   │              │ complete
              ▼              │              ▼
        ┌───────────┐       │        ┌───────────┐
        │ Onboarding│       │        │ Dashboard  │◄────────────────┐
        │(/onboarding)      │        │(/dashboard)│                 │
        └─────┬─────┘       │        └─────┬──────┘                 │
              │ Continue /   │              │                        │
              │ Skip         │              │ Insight click /        │
              └──────────────┘              │ "Improve portfolio"    │
                                            ▼                       │
                                   ┌─────────────────┐             │
                                   │ Recommendations  │             │
                                   │(/recommendations)│             │
                                   └────────┬─────────┘             │
                                            │                       │
              ┌─────────────────────────────┘                       │
              │ (All other pages reachable via sidebar)              │
              │                                                     │
    ┌─────────┼─────────┬──────────┬──────────┬──────────┐         │
    ▼         ▼         ▼          ▼          ▼          ▼         │
┌────────┐┌───────┐┌────────┐┌─────────┐┌──────┐┌──────────┐     │
│Portfolio││ Risk  ││Concentr││Diversif.││Goals ││   Chat   │     │
│(/portfo││(/risk)││(/concen││(/divers ││(/goal││  (/chat) │     │
│  lio)  ││       ││tration)││ ific.)  ││  s)  ││          │     │
└───┬────┘└───────┘└───┬────┘└─────────┘└──┬───┘└──────────┘     │
    │                   │                    │                      │
    │ Fund click        │ "See the fix"      │ "Suggest fix"        │
    ▼                   ▼                    ▼                      │
┌──────────┐    ┌─────────────────┐  ┌─────────────────┐          │
│Fund Detail│    │ Recommendations │  │ Recommendations │          │
│(/funds/id)│   │(/recommendations)│ │(/recommendations)│          │
└──────────┘    └─────────────────┘  └─────────────────┘          │
                                                                    │
    ┌──────────┐  ┌───────────┐  ┌──────────┐                     │
    │   Tax    │  │Performance│  │   Plan   │                     │
    │  (/tax)  │  │(/performa-│  │  (/plan) │                     │
    │          │  │   nce)    │  │          │                     │
    └──────────┘  └───────────┘  └──────────┘                     │
                                                                    │
    ┌──────────┐                                                    │
    │ Settings │── "Sign out" ──► Login (/login)                   │
    │(/settings)│                                                   │
    └──────────┘                                                    │
                                                                    │
    Empty state on Dashboard or Portfolio ──► Onboarding ───────────┘
```

---

## Cross-Cutting Concerns

### Authentication Guard
- There is **no centralized route guard** currently wired. A `RequireAuth` component exists in the codebase but is not active.
- Protection is **implicit**: each page calls API hooks, and if the session is expired (401), the individual hook/error handler surfaces the failure. The user would need to manually navigate to `/login`.
- Post-login, the app routes based on `user.onboardingCompleted`.

### Responsive Behavior
- **Desktop (≥ 1024px)**: Left sidebar (224px) + main content area.
- **Mobile (< 1024px)**: Top bar + main content + fixed bottom nav (4 tabs: Home, Portfolio, Tips, Chat). Full sidebar is hidden.

### Data Loading Pattern
- Every page shows a **LoadingSkeleton** while its React Query hooks are fetching.
- Every page shows an **ErrorState** with retry if the API call fails.
- Every page shows an **EmptyState** with contextual messaging if no data exists.

### Not Yet Implemented (Placeholder Buttons)
These UI elements exist but have no wired behavior:
- Goals: "+ Add goal", "Suggest fix" (partially wired)
- Tax: "Schedule harvest →"
- Plan: "Generate plan →", "Export PDF", "Execute →"
- Settings: "Export my data"
- Mobile Topbar: hamburger menu button
