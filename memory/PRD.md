# nivesh.ai — Product Requirements Document

## Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System) for Indian retail investors. Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, actionable insights, and AI chat interface. Clean Kuvera-inspired theme (white, emerald green, generous spacing).

## User Persona
Indian retail investors managing multiple investments across stocks, mutual funds, ETFs, bonds, gold, and FDs. Families managing portfolios for multiple members.

## Core Requirements
- Google OAuth authentication
- Multi-format portfolio upload (CAS PDF, CSV, Excel) with password protection
- Family portfolio management
- Interactive dashboard with drill-down charts
- AI-powered insights and recommendations
- Live market data integration
- Chat interface with portfolio-aware AI

## Tech Stack
- **Frontend:** React, Tailwind CSS, Recharts, Shadcn UI, Framer Motion
- **Backend:** FastAPI, Motor/MongoDB, PyPDF2, pdf2image/poppler
- **AI:** GPT-5.2 via emergentintegrations (Emergent LLM Key)
- **Auth:** Emergent Managed Google OAuth
- **Market Data:** AMFI India NAV API (portal.amfiindia.com)

## Architecture
```
/app/backend/
├── server.py (Thin route layer)
├── models.py (Pydantic models, enums)
├── repository.py (MongoDB operations)
├── middleware.py (Rate limiting, CORS)
├── instruments_data.py (Static instrument DB)
└── services/
    ├── __init__.py (Health score, risk analysis, recommendations)
    ├── ai_engine.py (GPT-5.2 integration)
    └── amfi_nav.py (AMFI NAV scraper)

/app/frontend/src/
├── components/
│   ├── DashboardOverview.js, PortfolioView.js, FamilyView.js
│   ├── InsightsView.js (4-tab: AI Overview, Overexposure, Fund Overlap, Performance)
│   ├── ChatView.js, Sidebar.js, DrilldownModal.js
│   └── ui/ (Shadcn components)
├── context/ (Auth, Theme, NumberFormat)
└── pages/ (Landing, Dashboard, AuthCallback)
```

## What's Been Implemented

### Phase 1 — Core (DONE)
- [x] Google OAuth via Emergent Auth
- [x] CAS PDF parsing (text + image-based) with password support
- [x] CSV and Excel portfolio upload
- [x] Raw binary upload endpoint (bypasses K8s 30s timeout)
- [x] Family portfolio management
- [x] Asset categorization (equity, MF, ETF, bond, gold, FD)
- [x] Instrument autocomplete search
- [x] Dark/Light mode toggle

### Phase 2 — Dashboard & Analytics (DONE)
- [x] KPI cards (invested, current, returns, day change, risk)
- [x] Interactive Treemap heatmap with drill-down
- [x] Asset allocation donut chart with click-through
- [x] Sector exposure horizontal bar chart
- [x] Performance trend area chart (30-day)
- [x] Top gainers/losers lists
- [x] Lakh/Crore number format toggle

### Phase 3 — Product Intelligence (DONE)
- [x] Composite Health Score (diversification, risk, cost, performance)
- [x] Risk Analysis with warnings
- [x] Smart recommendations (Regular→Direct, dead positions, allocation)
- [x] AI-generated insights with Priority Matrix
- [x] Action Funnel visualization
- [x] Before/After impact comparison
- [x] Problem distribution donut
- [x] Risk gauge current vs target

### Phase 4 — Live Data & Visual Insights (DONE - Feb 2026)
- [x] AMFI Live NAV integration (31K+ schemes, auto-updates MF prices)
- [x] Fund House / AMC Overexposure visualization (bar chart + expandable cards)
- [x] Sector Concentration visualization (bar chart + expandable cards)
- [x] Fund Overlap Matrix (programmatic overlap by sector/category/AMC)
- [x] Performance Cards (sortable table with P&L, weight, CAGR, LIVE NAV badges)
- [x] 4-tab InsightsView (AI Overview, Overexposure, Fund Overlap, Performance)
- [x] NAV refresh endpoint

### AI Chat (DONE)
- [x] Portfolio-aware AI chat with GPT-5.2
- [x] Conversation history
- [x] Clear chat functionality

## Key API Endpoints
- `POST /api/auth/session` — Exchange Google OAuth session
- `POST /api/portfolio/upload-raw` — Binary upload (CAS PDF bypass)
- `GET /api/portfolio/analytics` — Full analytics with AMFI NAV updates
- `GET /api/portfolio/deep-analytics` — Overexposure, overlap, performance cards
- `POST /api/nav/refresh` — Manual AMFI NAV refresh
- `POST /api/insights/generate` — AI-powered portfolio analysis
- `POST /api/chat/send` — AI chat with portfolio context

## Remaining Backlog

### P1 — Next Up
- [ ] Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- [ ] Free Indian market API for historical stock prices (for equity holdings)

### P2 — Future
- [ ] Agentic AI execution and scenario simulation
- [ ] Tax loss harvesting suggestions
- [ ] SIP tracking and recommendations
