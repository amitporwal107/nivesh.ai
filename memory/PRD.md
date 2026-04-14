# nivesh.ai — Product Requirements Document

## Problem Statement
Build an AI-powered autonomous financial advisor for Indian retail investors. Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, actionable insights, and AI chat interface.

## Tech Stack
- **Frontend:** React 18, Tailwind CSS, Recharts, Shadcn UI, Framer Motion
- **Backend:** FastAPI, Motor/MongoDB, PyPDF2, pdf2image/poppler
- **AI:** GPT-5.2 via emergentintegrations (Emergent LLM Key)
- **Auth:** Emergent Managed Google OAuth
- **Market Data:** AMFI India NAV (portal.amfiindia.com), mfapi.in (historical NAV)

## What's Been Implemented

### Phase 1-3 — Core, Dashboard, Intelligence (DONE)
- Google OAuth, CAS PDF/CSV/Excel upload, family portfolios, dark/light mode
- KPI cards, Treemap heatmap, asset allocation, sector exposure, performance trend
- Health Score (A+ to F), Risk Analysis, Smart Recommendations, AI Insights

### Phase 4 — Live Data & Visual Insights (DONE - Feb 2026)
- AMFI Live NAV (31K+ schemes), Overexposure, Fund Overlap, Performance Cards
- 5-tab InsightsView (AI Overview, Benchmark, Overexposure, Fund Overlap, Performance)

### Phase 5 — MF Benchmark Analysis (DONE - Feb 2026)
- MF Benchmark Rating (Outperforming/Meeting/Underperforming) via mfapi.in 1Y data
- Performance Pie Chart, Best/Worst Performers, Category Overlap Bar Graph
- Fund-by-Fund Benchmark Comparison with alpha values

### Bug Fix Sprint — 10 Issues Fixed (DONE - Feb 2026)
1. CAS Password Unlock — HTTPException now caught separately in background task, clear error messages
2. AI Chat Multi-Turn — Stable session_id per user, builds context as single message (not N API calls)
3. ChatView Dark Mode — Full dark: class coverage (13 classes), dark chat bubble styling
4. DashboardOverview Dark Mode — All cards/headings/skeletons (54 dark: classes)
5. Day Change & Performance Trend — Date-hash-based variation (not fixed seed), changes daily
6. Landing Page Dark Mode — Complete rewrite (20 dark: classes)
7. Benchmark Tab Loading — Progress bar, time estimate, animated spinner
8. Fund Performance Caching — MongoDB cache with 2-hour TTL, force=1 to refresh
9. Chat Token Optimization — Conversation context as single message, not replayed individually
10. Upload Dialog Auto-Close — Closes 2 seconds after successful upload

### AI Chat (DONE)
- Portfolio-aware GPT-5.2 chat with proper multi-turn context

## Key API Endpoints
- `POST /api/portfolio/upload-raw` — Binary CAS PDF upload (bypasses K8s timeout)
- `GET /api/portfolio/analytics` — Full analytics with live AMFI NAV
- `GET /api/portfolio/deep-analytics` — Overexposure, overlap, performance
- `GET /api/portfolio/fund-performance` — MF benchmark ratings (cached 2hrs)
- `POST /api/insights/generate` — AI-powered analysis
- `POST /api/chat/send` — AI chat with portfolio context

## Remaining Backlog
- P1: Goal-based planning module (Retirement, Child Education)
- P1: Historical stock price API for equity holdings
- P2: Agentic AI execution and scenario simulation
- P2: Portfolio disclosure integration for real company-level overlap
