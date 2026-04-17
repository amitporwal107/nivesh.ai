# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **CAS Parsing**: CAS Parser Portfolio Connect SDK. Fallback: casparser API -> local OCR.
- **Masterdata**: AMFI NAV + NSE Bhav Copy + Equity Sector Mapping
- **Live Prices**: yfinance for equity/ETF, AMFI for MF NAV

## Implemented Features
- [x] Google OAuth + invite-only whitelist + Admin dashboard
- [x] CAS Parser SDK widget + casparser API + OCR fallback
- [x] Onboarding, Risk Profile, Quick Setup
- [x] SSE streaming chat with intent-driven UX + quick action buttons
- [x] Skeleton loaders everywhere
- [x] Portfolio Health/Risk explainability panels
- [x] Actionable Insights drill-down (affected holdings)
- [x] Issue Breakdown chart clickable (drill into holdings)
- [x] MF benchmark ratings with drilldown
- [x] **Stacked allocation chart** (Current vs Balanced) for Fund House Concentration
- [x] **Portfolio Performance Heatmap** (P&L-driven, not benchmark)
- [x] **MF Category Overlap card grid** (replacing bar chart)
- [x] Equity sector classification (Banking, IT, Pharma, etc.)
- [x] Fund House/Sector cards expanded by default
- [x] server.py refactored into modular routes

## Backlog
### P0
- Fund & Stock Rating System (Morningstar-style star ratings)
- Security: PAN encryption, consent logging, audit trails (DPDP Act)

### P1
- Mobile-first layout, enhanced simulation UX, goal-based planning

### P2
- Broker integrations, agent-based backend, offline support, portfolio versioning
