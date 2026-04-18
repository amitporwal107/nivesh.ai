# nivesh.ai - Product Requirements Document

## Implemented Features (Latest)

### Feb 2026 - Mobile-First Responsive Overhaul
- [x] **Mobile-first layout across all screens** (no desktop regressions)
  - Landing page: hero preview cards stack on mobile (`grid-cols-1 sm:grid-cols-3`); footer stacks
  - Dashboard shell: `pt-16 md:pt-4` so mobile hamburger doesn't overlap headers
  - Sidebar: already drawer-based on mobile, unchanged
  - DashboardOverview: asset-allocation donut+legend stacks vertically on mobile, heatmap legend wraps, header action buttons wrap, KPI padding + text size responsive
  - InsightsView: 5-tab navigation now horizontally scrollable (`overflow-x-auto scrollbar-hide`), 4-col grid → 2-col on mobile
  - ChatView: sidebar hidden by default on mobile (<md), overlay with backdrop; header title/subtitle responsive; message bubbles widen to 85% on mobile; "Clear" button becomes icon-only
  - PortfolioView: holdings table wrapped in `overflow-x-auto` for horizontal scroll; asset-type tabs scroll horizontally; filter bar stacks on mobile; dialog scrollable
  - OnboardingView: wizard content scrolls from top on mobile, 3-col projection → 1-col
  - RiskProfileView: 4-col allocation → 2-col on mobile; result action buttons stack
  - FamilyView: header stacks on mobile, Add Member button full-width
- [x] Added `.scrollbar-hide` CSS utility in App.css

### Apr 2026 - Enhanced AI Insights Engine
- [x] Full portfolio context sent to OpenAI: overexposure, overlap, allocation, cost data
- [x] Every insight cites specific ₹ amounts, %, fund names, ideal ranges
- [x] Issue Breakdown shows "reason" for each category
- [x] Insights cover: AMC concentration, sector exposure, cost leakage, debt gap, equity underperformance
- [x] Action Plan with ₹ impact (e.g., "Switch ₹12L to direct plans → save ₹60K/year")

### Prior UX & Architecture
- [x] server.py refactored into 9 route modules + deps + helpers
- [x] AI streaming chat via SSE, action intent cards, hybrid Chat+Control layout
- [x] Explainability drawers, drill-down into affected holdings
- [x] Fund Performance P&L Heatmap, MF category cards, stacked allocations
- [x] True look-through allocation via OpenAI gpt-4o-mini (`/api/portfolio/allocation-analysis`)
- [x] Motilal Oswal-inspired Dark/Light dual theme
- [x] Reordered AI Overview: Health → Risk → Confidence → Issue Breakdown → Insights → Action Plan → Simulate

## Backlog
### P0
- Action Plan multi-step enforcement (only 1 step generated today; need N steps mapping to every flagged insight)
- Security & DPDP Act: replace hardcoded secrets in tests with env, remove `eval()` in test_bug_fixes_iteration9.py, swap MD5 → SHA-256 in analytics.py
- PAN encryption (AES-256), consent logging, audit trails

### P1
- Fund & Stock Rating System (Morningstar-style, AI-driven)
- React hook dependency & array-index key cleanup across Dashboard/InsightsView/Gmail/Auth
- Split `InsightsView.js` (2131 lines), `OnboardingView.js` (904 lines), `DashboardOverview.js` (861 lines)
- Goal-based planning (Retirement, Child Edu, SIPs)
- Stock-level overlap via AMFI disclosure data

### P2
- Portfolio versioning (delta tracking)
- PostgreSQL migration for relational structure
- Broker integrations, agent-based backend, offline support
