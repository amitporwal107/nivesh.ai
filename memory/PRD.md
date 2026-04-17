# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor for Indian market.

## Architecture
- React + Tailwind + Shadcn | FastAPI + MongoDB + OpenAI gpt-4o-mini
- CAS Parser SDK, AMFI NAV, NSE Bhav Copy, yfinance

## Implemented Features
- [x] Google OAuth + whitelist + Admin
- [x] CAS Parser SDK + fallbacks, onboarding, risk profile
- [x] SSE streaming chat + intent UX + quick actions + skeleton loaders
- [x] Explainability panels (health, risk)
- [x] Insights drill-down, issue breakdown clickable
- [x] MF benchmark + Portfolio P&L Heatmap
- [x] Fund House stacked allocation (Current vs Balanced)
- [x] Fund Overlap v2 (duplication score, AI insights, stacked bars)
- [x] AI Look-Through Allocation (OpenAI, no PII)
- [x] **Dual-mode theme** (Light + Dark, MOS-inspired dark design)
- [x] **MOS-style allocation display**: Alert banners, stacked sector bars, Sector/Company toggle, drillable cards
- [x] Equity sector classification (Banking, IT, Pharma, etc.)
- [x] server.py refactored into modular routes

## Backlog
### P0
- Fund & Stock Rating System (Morningstar-style)
- Security: PAN encryption, consent logging (DPDP Act)

### P1
- Stock-level overlap via AMFI disclosure data
- Mobile-first layout, simulation UX, goal-based planning

### P2
- Broker integrations, agent-based backend, offline support
