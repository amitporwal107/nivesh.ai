# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System) for Indian market.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + Tesseract OCR
- **AI**: OpenAI gpt-4o-mini for chat, insights, allocation analysis (gpt-4o for CAS parsing)
- **Masterdata**: AMFI NAV + NSE Bhav Copy + Equity Sector Mapping
- **Live Prices**: yfinance for equity/ETF, AMFI for MF NAV

## Implemented Features
- [x] Google OAuth + invite-only whitelist + Admin dashboard
- [x] CAS Parser SDK widget + fallbacks
- [x] Onboarding, Risk Profile, Quick Setup
- [x] SSE streaming chat + intent-driven UX + quick action buttons
- [x] Skeleton loaders, explainability panels
- [x] Actionable Insights drill-down (affected holdings)
- [x] MF benchmark ratings with drilldown + Portfolio Performance Heatmap
- [x] Stacked allocation chart (Current vs Balanced) for Fund House
- [x] MF Category Overlap card grid
- [x] Equity sector classification
- [x] Fund Overlap Tab v2 (duplication score, AI insights, stacked bars, sector exposure)
- [x] **AI Look-Through Allocation Analysis** (OpenAI-powered):
  - True sector exposure (not MF categories — actual Financials, IT, Energy, etc.)
  - Top 10 company exposure across all funds
  - Concentration risk flags (sector >30%, company >10%)
  - Cached for 6 hours, no PII sent to OpenAI
- [x] server.py refactored into modular routes

## Security
- PII sanitization: Only fund names, weights, sectors sent to OpenAI
- No user_id, email, PAN, address in any AI prompt
- Holdings projection restricted: `name, ticker, asset_type, quantity, current_price, sector`

## Backlog
### P0
- Fund & Stock Rating System (Morningstar-style star ratings)
- Security: PAN encryption (AES-256), consent logging, audit trails (DPDP Act)

### P1
- Stock-level overlap via AMFI portfolio disclosure data
- Mobile-first layout, enhanced simulation UX, goal-based planning

### P2
- Broker integrations, agent-based backend, offline support, portfolio versioning
