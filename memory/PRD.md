# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: Primary: CAS Parser Portfolio Connect SDK. Secondary: casparser API -> local OCR.
- **Masterdata**: AMFI NAV (17K+ ISINs) + NSE Bhav Copy (3.3K equities)
- **Live Prices**: yfinance for equity/ETF, AMFI for MF NAV

## Backend Structure (Refactored Apr 2026)
```text
/app/backend/
  server.py           (89 lines - thin entry point)
  deps.py             (shared: DB, repos, config, auth helpers)
  middleware.py        (rate limiting, env validation)
  helpers/parsing.py, portfolio_utils.py
  routes/ (auth, admin, gmail, portfolio, upload, analytics, chat, user, insights)
  services/ (ai_engine with chat_stream, amfi_nav, live_price, masterdata, etc.)
```

## Implemented Features
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] CAS Parser Portfolio Connect SDK widget
- [x] casparser API + Local OCR fallback
- [x] AMFI NAV + NSE Bhav masterdata
- [x] Complete onboarding flow
- [x] Chat Sessions with conversation history
- [x] Risk Profile Questionnaire
- [x] Live equity/ETF prices, AMFI MF NAV, SGB tracking
- [x] Portfolio analytics, health score, risk analysis
- [x] AI-powered chat with portfolio context
- [x] server.py refactored into modular routes
- [x] **Phase 1: AI-first UX** (Apr 2026)
  - [x] SSE streaming chat (POST /api/chat/stream) with 18ms token delay
  - [x] Intent-driven chat empty state (4 intent cards)
  - [x] Quick action buttons on AI responses (Simulate, Rebalance, Compare)
  - [x] Skeleton loaders (Dashboard, Insights, Chat)
  - [x] Streaming fallback to batch endpoint
- [x] **Explainability & Drillability** (Apr 2026)
  - [x] Portfolio Health "How is this calculated?" expandable panel
  - [x] Risk Assessment "Why is this high?" expandable panel with risk drivers
  - [x] Actionable Insights drill-down showing affected holdings with returns/values
  - [x] Issue Breakdown chart clickable — drill into holding lists per category

## Key DB Collections
- `whitelisted_users`, `users`, `user_profiles`
- `portfolios`, `holdings`, `upload_tasks`
- `chat_sessions`, `chat_messages`, `ai_insights`, `portfolio_analysis`

## Backlog (Prioritized)

### P0
- Fund & Stock Rating System (Morningstar-style star ratings, AI-powered analysis)
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1 (Phase 2: Core UX Transformation)
- AI-first navigation (intent-driven homepage)
- Mobile-first layout restructure
- Enhanced simulation UX (sliders, instant recalculation)
- Design system overhaul (8px grid)

### P1 (Features)
- Goal-based planning module (Retirement, Child Education)
- Connect to Human Advisor feature

### P2 (Phase 3: Platform Expansion)
- Broker integrations (Zerodha, Angel One APIs)
- Agent-based backend (separate AI services)
- Personalization engine, Offline support
- Portfolio versioning, PostgreSQL migration
