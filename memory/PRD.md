# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: Primary: CAS Parser Portfolio Connect SDK. Secondary: casparser API -> local OCR.
- **Masterdata**: AMFI NAV (17K+ ISINs) + NSE Bhav Copy (3.3K equities) + Equity Sector Mapping
- **Live Prices**: yfinance for equity/ETF, AMFI for MF NAV

## Backend Structure
```text
/app/backend/
  server.py           (thin entry point)
  deps.py             (shared: DB, repos, config, auth helpers)
  middleware.py        (rate limiting, env validation)
  helpers/parsing.py, portfolio_utils.py
  routes/ (auth, admin, gmail, portfolio, upload, analytics, chat, user, insights)
  services/ (ai_engine, amfi_nav, equity_sectors, fund_performance, live_price, masterdata, etc.)
```

## Implemented Features
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard + CAS Parser SDK
- [x] Complete onboarding, risk profile, quick setup
- [x] Chat Sessions with SSE streaming (token-by-token)
- [x] Intent-driven chat with quick action buttons
- [x] Skeleton loaders everywhere (no spinners)
- [x] Portfolio Health/Risk explainability panels
- [x] Actionable Insights drill-down (affected holdings)
- [x] Issue Breakdown chart clickable (drill into holdings)
- [x] MF benchmark ratings with overperforming/underperforming drilldown
- [x] Fund Performance Heatmap (color-coded by returns, size by investment)
- [x] MF Category Overlap (separate from equity)
- [x] Equity sector classification (Banking, IT, Pharma, FMCG, etc.)
- [x] Fund House/Sector cards expanded by default
- [x] server.py refactored into modular routes

## Backlog (Prioritized)
### P0
- Fund & Stock Rating System (Morningstar-style star ratings, AI-powered analysis)
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1
- AI-first navigation (intent-driven homepage)
- Mobile-first layout restructure
- Enhanced simulation UX (sliders, instant recalculation)
- Goal-based planning module

### P2
- Broker integrations (Zerodha, Angel One APIs)
- Agent-based backend, personalization, offline support
- Portfolio versioning, PostgreSQL migration
