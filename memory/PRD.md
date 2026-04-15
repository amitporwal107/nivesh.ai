# nivesh.ai — Product Requirements Document

## Problem Statement
AI-powered autonomous financial advisor for Indian retail investors. Portfolio upload/parsing, unified dashboard, actionable insights, AI chat. Invite-only access with email whitelisting.

## Tech Stack
- **Frontend:** React 18, Tailwind CSS, Recharts, Shadcn UI, Framer Motion, @react-oauth/google
- **Backend:** FastAPI, Motor/MongoDB, PyPDF2, pdf2image/poppler, google-api-python-client
- **AI:** GPT-5.2 via emergentintegrations (Emergent LLM Key)
- **Auth:** Direct Google OAuth 2.0 + Email Whitelist
- **Market Data:** AMFI India NAV (portal.amfiindia.com), mfapi.in (historical NAV)
- **Email:** Gmail API (read-only, CAS auto-fetch)

## What's Been Implemented

### Phase 1-3 — Core, Dashboard, Intelligence (DONE)
- Google OAuth (direct, not Emergent), invite-only whitelist
- CAS PDF/CSV/Excel upload, family portfolios, dark/light mode
- Interactive dashboard with drill-down charts, Health Score, Risk Analysis
- AI chat with multi-turn memory, smart recommendations

### Phase 4 — Live Data & Visual Insights (DONE)
- AMFI Live NAV (31K+ schemes), Overexposure, Fund Overlap, Performance Cards
- 5-tab InsightsView (AI Overview, Benchmark, Overexposure, Fund Overlap, Performance)

### Phase 5 — MF Benchmark Analysis (DONE)
- MF Benchmark Rating (Outperforming/Meeting/Underperforming) via mfapi.in
- Performance Pie Chart, Best/Worst Performers, Category Overlap Bar Graph

### Phase 6 — Invite-Only Access (DONE)
- Direct Google OAuth 2.0 (replaced Emergent Auth)
- Email whitelist system (MongoDB whitelisted_users collection)
- Admin panel (sidebar tab for admin users only)
- Add/remove/block/bulk-upload users, stats dashboard
- Auto-seed admin on startup (priyankamantri@gmail.com)

### Phase 7 — Gmail Auto-Fetch (DONE - Apr 2026)
- **Gmail OAuth Connect** — Separate OAuth flow for read-only Gmail access
- **CAS Email Scanner** — Scans inbox for emails from NSDL/CDSL/CAMS/KFintech with PDF attachments
- **Confidence Scoring** — Each email scored 0.0-1.0 based on sender/subject matching
- **Auto-Import** — One-click import of CAS PDF from Gmail into existing parser
- **Source Tagging** — Holdings tagged with source (CAS/email/manual) and confidence score
- **Deduplication Engine** — Merges holdings if same name+ISIN already exists (updates, doesn't duplicate)
- **Password Support** — Password field per attachment for encrypted CAS PDFs
- **Import Tracking** — gmail_imports collection tracks what's been imported to prevent duplicates

### Bug Fix Sprint — 10 Issues (DONE)
- CAS password unlock (missing pycryptodome)
- AI Chat multi-turn memory, ChatView/Dashboard/Landing dark mode
- Day change variation, benchmark caching, upload auto-close, chat token optimization

## Key API Endpoints
- `POST /api/auth/google` — Google OAuth login + whitelist check
- `GET /api/gmail/connect` — Start Gmail OAuth flow
- `GET /api/oauth/gmail/callback` — Gmail OAuth callback
- `POST /api/gmail/scan` — Scan Gmail for CAS emails
- `POST /api/gmail/import` — Import CAS from Gmail attachment
- `GET /api/portfolio/analytics` — Full analytics with AMFI NAV
- `GET /api/portfolio/fund-performance` — MF benchmark ratings
- `POST /api/admin/whitelist/add` — Add email to whitelist

## Remaining Backlog
- P0: Finvu Account Aggregator integration (needs sandbox credentials)
- P1: Goal-based planning module (Retirement, Child Education)
- P1: Historical stock price API for equity holdings
- P2: Agentic AI execution and scenario simulation
