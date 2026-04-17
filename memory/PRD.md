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
    chat.py            (AI chat sessions)
    user.py            (Profile, onboarding, risk profile, quick setup)
    insights.py        (AI-powered portfolio insights)
```

## Implemented Features
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] CAS Parser Portfolio Connect SDK widget (PDF upload, Gmail inbox import, CDSL OTP)
- [x] OAuth callback page (/cas-callback) for SDK Gmail flow
- [x] casparser API integration for text-based CAS (100% accuracy)
- [x] Local Tesseract OCR for image-based CAS (fallback)
- [x] AMFI NAV + NSE Bhav masterdata for ISIN validation and price enrichment
- [x] Complete onboarding flow (Existing/New investor paths)
- [x] Quick Setup + Starter Plan for new investors
- [x] Password field for encrypted CAS PDFs
- [x] SEBI disclaimer on all onboarding steps
- [x] Chat Sessions with conversation history
- [x] Risk Profile Questionnaire
- [x] Live equity/ETF prices, AMFI MF NAV, SGB tracking
- [x] Portfolio analytics, health score, risk analysis
- [x] AI-powered chat with portfolio context
- [x] Legacy upload paths disabled (CAS Connect only)
- [x] Masterdata enrichment preserves cost data
- [x] **server.py refactored** into modular routes (2882 -> 89 lines)

## Key DB Collections
- `whitelisted_users`, `users`, `user_profiles`
- `portfolios`, `holdings`, `upload_tasks`
- `chat_sessions`, `chat_messages`, `ai_insights`

## Key Technical Notes
- CAS parsing (Apr 2026): Primary path is CAS Parser Portfolio Connect SDK widget.
- Keys: `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY`, `CASPARSER_USE_SANDBOX` in `/app/backend/.env`
- Masterdata: `/app/backend/data/amfi_data.csv`, `bhav_copy.csv`, `equity_list.csv`, `sgb_data.csv`
- Admin user: priyankamantri@gmail.com

## Backlog (Prioritized)
### P0 (Next)
- Fund & Stock Rating System (Morningstar-style star ratings, AI-powered analysis)
  - MF performance ratings + star ratings using GPT
  - Stock ratings with fundamentals (P/E, PEG, dividend yield via yfinance)
  - Both: rate user's holdings + discovery/screener tool
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Connect to Human Advisor feature

### P2
- Portfolio versioning (delta tracking between uploads)
- PostgreSQL migration for structured financial data
- S3 encrypted storage for raw CAS PDFs
