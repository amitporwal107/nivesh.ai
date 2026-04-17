# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: Primary: CAS Parser Portfolio Connect SDK (@cas-parser/connect). Secondary fallback: casparser API → local OCR.
- **Masterdata**: AMFI NAV (17K+ ISINs) + NSE Bhav Copy (3.3K equities)
- **Live Prices**: yfinance (Yahoo Finance) for equity/ETF, AMFI for MF NAV

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
- [x] Masterdata enrichment preserves cost data (quantity not recalculated when avg_cost available)

## Key DB Collections
- `whitelisted_users`, `users`, `user_profiles`
- `portfolios`, `holdings`, `upload_tasks`
- `chat_sessions`, `chat_messages`, `ai_insights`

## Key Technical Notes
- **CAS parsing (Apr 2026)**: Primary path is CAS Parser Portfolio Connect SDK widget. Backend mints short-lived `at_` access tokens via `POST /api/casparser/access-token`. Widget's `onSuccess` posts parsed data to `POST /api/portfolio/import-connect`. Gmail OAuth callback at `/cas-callback` handles `handleInboxCallback()`.
- Keys: `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY`, `CASPARSER_USE_SANDBOX` in `/app/backend/.env`
- Masterdata: `/app/backend/data/amfi_data.csv`, `bhav_copy.csv`, `equity_list.csv`, `sgb_data.csv`
- Admin user: priyankamantri@gmail.com

## Backlog (Prioritized)
### P0
- server.py refactoring into /routes directory (2800+ lines)
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Connect to Human Advisor feature

### P2
- Portfolio versioning (delta tracking between uploads)
- PostgreSQL migration for structured financial data
- S3 encrypted storage for raw CAS PDFs
