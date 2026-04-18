# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 - AI Copilot Phase 2
- [x] **Custom Scenario Builder** — slider-based UI to tweak Equity/Debt/Gold + Max AMC + Max Stock exposure, with auto-balancing allocation (sums to 100%)
- [x] **Rebalance Plan generator** — `POST /api/scenarios/rebalance-plan` outputs REDUCE/EXIT/SWITCH/BUY actions with specific holdings, ₹ amounts, reasons
- [x] **Save/Load scenarios** — named scenarios persisted per user in `saved_scenarios`, inline chip UI with load + delete
- [x] **Apply Changes** — `POST /api/scenarios/apply` persists plan actions to `pending_actions` collection (no portfolio mutation)
- [x] New components: `CustomScenarioBuilder.jsx`, `RebalancePlanDialog.jsx`
- [x] New endpoints: `/api/scenarios/rebalance-plan`, `/save`, `/saved`, `/saved/{id}` (DELETE), `/apply`, `/pending`

### Feb 2026 - AI Copilot Phase 1 MVP
- [x] **Scenario-driven AI Copilot** replacing the AI Overview tab
  - Backend: `/app/backend/routes/scenarios.py` — new module
    - `GET /api/scenarios/suggest` — deterministic scenario generator picks top 4 from: Add Debt, Reduce Top AMC, Switch to Direct, Clean Dead Positions, Reduce Small Cap
    - `POST /api/scenarios/simulate` — returns Before/After metrics (CAGR, risk, cost, 5Y projection) using static per-asset-class CAGR assumptions
    - Simulations persisted in `scenario_simulations` collection
  - Frontend: `/app/frontend/src/components/copilot/` — 4 new components
    - `PortfolioContextHeader.jsx` — snapshot pills + detected issues chips
    - `ScenarioCard.jsx` — category-colored cards with impact chips + Simulate CTA
    - `SimulationPanel.jsx` — 4-metric grid, risk gauge, allocation bars, top-changes, 3 action buttons
    - `AICopilotView.jsx` — orchestrator wiring suggest → simulate flow
  - "AI Overview" tab renamed → "AI Copilot" in InsightsView
  - Existing tabs (Benchmark, Overexposure, Fund Overlap, Performance) untouched
- [x] Phase-1 scope: plan-only actions (no portfolio mutation), static CAGR model (Equity 12%, Debt 7%, Gold 8%, Hybrid 10%), 4-card max suggestions

### Feb 2026 - Mobile-First Responsive Overhaul
- [x] Mobile-first layout across all screens (no desktop regressions)
- [x] `overflow-x: hidden` on body + `min-w-0` on Dashboard flex shell to prevent content width overflow
- [x] `.scrollbar-hide` utility for horizontally-scrollable tab strips
- [x] Benchmark donut+legend stacks vertically on mobile
- [x] ChatView sidebar hidden by default on mobile with overlay
- [x] PortfolioView holdings table wrapped in overflow-x-auto
- [x] Suppressed cross-origin "Script error." overlays on Samsung/older mobile browsers (index.js listeners)

### Apr 2026 - Enhanced AI Insights Engine
- [x] Full portfolio context sent to OpenAI (overexposure, overlap, allocation, cost data)
- [x] Insights cite specific ₹ amounts, %, fund names, ideal ranges
- [x] Issue Breakdown with reason per category
- [x] Reordered AI Overview: Health → Risk → Confidence → Issue Breakdown → Insights → Action Plan

### Prior UX & Architecture
- [x] server.py refactored into 10 route modules (auth, admin, gmail, portfolio, upload, analytics, chat, user, insights, scenarios)
- [x] SSE streaming chat, action intent cards
- [x] Fund Performance P&L Heatmap, MF category cards, stacked allocations
- [x] True look-through allocation via OpenAI gpt-4o-mini
- [x] Motilal Oswal-inspired dark/light dual theme

## Backlog

### P0 (next up)
- AI Copilot Phase 2: Custom Scenario Builder (sliders for Equity/Debt/Gold/AMC cap/Stock cap) + Rebalance Plan generator (step-by-step buy/sell) + Save/Load scenarios persistence
- Action Plan multi-step enforcement (force N steps mapping to every flagged insight — still 1-step issue in old `insights/generate`)
- Security & DPDP: replace hardcoded secrets in tests, remove `eval()`, swap MD5→SHA-256 in analytics.py
- PAN encryption (AES-256), consent logging, audit trails

### P1
- AI Copilot Phase 3: color system polish, icon library, animations, chat repositioning to bottom
- Fund & Stock Rating System (Morningstar-style, AI-driven)
- React hook dependency & array-index key cleanup
- Split oversized React components (InsightsView 2122 lines, OnboardingView 904 lines, DashboardOverview 861 lines)
- Goal-based planning (Retirement, Child Edu, SIPs)
- Stock-level overlap via AMFI disclosure data

### P2
- Historical-backtest CAGR model (upgrade from static assumptions)
- "Apply Changes" with pending-actions persistence
- Broker integrations for real portfolio mutation
- Portfolio versioning (delta tracking)
- PostgreSQL migration
- Android wrap via Capacitor (deferred)
