# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: casparser (text PDFs) → Tesseract OCR + ML correction (image PDFs) → OpenAI Vision (fallback, disabled by default for security)
- **Masterdata**: AMFI NAV (17K+ ISINs) + NSE Bhav Copy (3.3K equities)
- **Live Prices**: yfinance (Yahoo Finance) for equity/ETF, AMFI for MF NAV

## CAS Parsing Pipeline (7-Phase)
1. Quick scan first pages → detect CAS type (NSDL/CDSL) + extract summary totals
2. Smart page selection → OCR only holdings pages (skip transactions/KYC/disclaimers)
3. Full Tesseract OCR on selected pages (DPI=200, PSM=4)
4. Section-aware parsing (Equities/ETFs/SGBs/MF Folios — different for NSDL vs CDSL)
5. ML OCR correction engine (learned patterns from manual corrections)
6. Masterdata validation + enrichment (AMFI NAV / NSE Bhav)
7. Summary validation

## Current CAS Parsing Accuracy
| Metric | NSDL | CDSL |
|---|---|---|
| ISIN match | 81% | 62% |
| Value match | 78% | 38% |
| Speed | 30s | 32s |

## Implemented Features
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] Multi-format CAS upload (NSDL/CDSL image PDFs, CAMS/KFintech text PDFs, CSV, Excel)
- [x] casparser integration for text-based CAS (100% accuracy)
- [x] Local Tesseract OCR for image-based CAS (no cloud dependency)
- [x] ML OCR correction engine (learns from manual corrections)
- [x] AMFI NAV + NSE Bhav masterdata for ISIN validation and price correction
- [x] Admin API for manual corrections (ISIN, name, holding values)
- [x] Complete onboarding flow (Existing/New investor paths)
- [x] Quick Setup + Starter Plan for new investors
- [x] Password field for encrypted CAS PDFs
- [x] SEBI disclaimer on all onboarding steps
- [x] Chat Sessions with conversation history
- [x] Risk Profile Questionnaire
- [x] Live equity/ETF prices, AMFI MF NAV, SGB tracking
- [x] Portfolio analytics, health score, risk analysis
- [x] AI-powered chat with portfolio context

## Admin OCR Correction API Endpoints
- `POST /api/admin/ocr-correction/isin` — Teach garbled ISIN → correct ISIN
- `POST /api/admin/ocr-correction/name` — Teach garbled name → correct name + ISIN
- `POST /api/admin/ocr-correction/holding` — Fix a specific holding (updates DB + teaches engine)
- `GET /api/admin/ocr-correction/stats` — Get correction engine statistics

## Key DB Collections
- `whitelisted_users`, `users`, `user_profiles`
- `portfolios`, `holdings`, `upload_tasks`
- `chat_sessions`, `chat_messages`, `ai_insights`

## Backlog (Prioritized)
### P0
- Google OAuth URL whitelisting (blocked on user GCP config)
- server.py refactoring into /routes directory

### P1
- Security: consent screen, PAN encryption, "Delete My Data", audit logging
- Connect to Human Advisor feature
- Goal-based planning module

### P2
- Portfolio versioning (delta tracking between uploads)
- Postgres migration for structured financial data
- S3 encrypted storage for raw CAS PDFs

## Technical Notes
- **CAS parsing (Apr 2026)**: Primary path is CAS Parser API (casparser.in). Secondary is `casparser` library (digital PDFs). Tertiary is local Tesseract OCR + img2table (for scanned PDFs up to 10MB).
- Keys: `CASPARSER_API_KEY`, `CASPARSER_SANDBOX_KEY`, `CASPARSER_USE_SANDBOX` in `/app/backend/.env`
- Sandbox mode returns deterministic sample data (no credits, no real PDF required)
- Masterdata (Apr 2026): `/app/backend/data/amfi_data.csv` (17,588 MFs with plan/option classification), `bhav_copy.csv` (3,365 NSE), `equity_list.csv` (2,256), `sgb_data.csv` (46 SGBs w/ LTP)
- Poppler-utils + Tesseract installed via server.py startup event
- OCR corrections: /app/backend/data/ocr_corrections.json
- Admin user: priyankamantri@gmail.com
