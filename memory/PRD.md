# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: Primary: CAS Parser Portfolio Connect SDK (@cas-parser/connect). Secondary fallback: casparser API -> local OCR.
- **Masterdata**: AMFI NAV (17K+ ISINs) + NSE Bhav Copy (3.3K equities)
- **Live Prices**: yfinance (Yahoo Finance) for equity/ETF, AMFI for MF NAV

## Backend Structure (Refactored Apr 2026)
```text
/app/backend/
  server.py           (89 lines - thin entry point)
  deps.py             (shared: DB, repos, config, auth helpers)
  middleware.py        (rate limiting, env validation)
  helpers/
    parsing.py         (CSV, Excel, CAS PDF parsing, save_holdings)
    portfolio_utils.py (extract_fund_house, compute_fund_overlap)
  routes/
    auth.py            (Google OAuth, session management)
    admin.py           (Whitelist CRUD, stats, OCR corrections)
    gmail.py           (Gmail OAuth, scan, import CAS from email)
    portfolio.py       (Portfolio CRUD, Holdings CRUD, instrument search)
    upload.py          (File upload, CAS PDF processing, CAS Connect SDK)
    analytics.py       (Portfolio analytics, deep analytics, fund performance)
    chat.py            (AI chat sessions + SSE streaming)
    user.py            (Profile, onboarding, risk profile, quick setup)
    insights.py        (AI-powered portfolio insights)
  services/
    ai_engine.py       (OpenAI integration: chat, chat_stream, analyze, CAS parse)
```

## Implemented Features
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] CAS Parser Portfolio Connect SDK widget
- [x] casparser API integration for text-based CAS
- [x] Local Tesseract OCR for image-based CAS (fallback)
- [x] AMFI NAV + NSE Bhav masterdata
- [x] Complete onboarding flow
- [x] Chat Sessions with conversation history
- [x] Risk Profile Questionnaire
- [x] Live equity/ETF prices, AMFI MF NAV, SGB tracking
- [x] Portfolio analytics, health score, risk analysis
- [x] AI-powered chat with portfolio context
- [x] Legacy upload paths disabled (CAS Connect only)
- [x] server.py refactored into modular routes
- [x] **Phase 1: AI-first UX** (Apr 2026)
  - [x] SSE streaming chat (POST /api/chat/stream) — token-by-token response
  - [x] Intent-driven chat empty state (4 intent cards)
  - [x] Quick action buttons on AI responses (Simulate, Rebalance, Compare)
  - [x] Skeleton loaders (Dashboard, Insights, Chat)
  - [x] Streaming fallback to batch endpoint

## Key DB Collections
- `whitelisted_users`, `users`, `user_profiles`
- `portfolios`, `holdings`, `upload_tasks`
- `chat_sessions`, `chat_messages`, `ai_insights`

## Backlog (Prioritized)

### P0 (Phase 1 remaining)
- Explainability drawer on insights ("Why this recommendation?")
- Mobile-optimized dataviz (simplify charts for mobile)
- Basic analytics tracking (time to first insight, recommendation clicks)

### P0 (Other)
- Fund & Stock Rating System (Morningstar-style star ratings, AI-powered analysis)
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1 (Phase 2: Core UX Transformation)
- AI-first navigation (intent-driven homepage)
- Mobile-first layout restructure
- Enhanced simulation UX (sliders, instant recalculation)
- Design system overhaul (8px grid)

### P1 (Features)
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Connect to Human Advisor feature

### P2 (Phase 3: Platform Expansion)
- Broker integrations (Zerodha, Angel One APIs)
- Agent-based backend (separate AI services)
- Personalization engine
- Offline support (Service Worker)

### P2 (Infrastructure)
- Portfolio versioning (delta tracking)
- PostgreSQL migration
- S3 encrypted storage for raw CAS PDFs
