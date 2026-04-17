# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System) for Indian market.

## Architecture
- **Frontend**: React + Tailwind CSS + Shadcn UI + Google OAuth
- **Backend**: FastAPI + Motor/MongoDB + casparser + OpenAI gpt-4o-mini
- **Masterdata**: AMFI NAV + NSE Bhav Copy + Equity Sector Mapping
- **Live Prices**: yfinance for equity/ETF, AMFI for MF NAV

## Implemented Features
- [x] Google OAuth + whitelist + Admin
- [x] CAS Parser SDK + fallbacks
- [x] Onboarding, Risk Profile, Quick Setup
- [x] SSE streaming chat + intent UX + quick actions
- [x] Skeleton loaders, explainability panels
- [x] Insights drill-down (affected holdings)
- [x] MF benchmark ratings + Portfolio Heatmap (P&L-driven)
- [x] Stacked allocation chart (Current vs Balanced)
- [x] Fund Overlap v2 (duplication score, AI insights, stacked bars)
- [x] AI Look-Through Allocation Analysis (OpenAI, no PII)
- [x] **Dark Theme UI Overhaul** (Motilal Oswal-inspired):
  - #09090B background, #121212 surface, #1A1A1A hover
  - Red/amber/green alert banners on dark surfaces
  - Dark tabs with active state (#27272A)
  - All cards, charts, insights in dark theme
  - Clean, crisp, low cognitive load design
- [x] server.py refactored into modular routes

## Design System
- Background: #09090B, Surface: #121212, Hover: #1A1A1A
- Text: white/zinc-400/zinc-500
- Alerts: red-500/10, amber-500/10, emerald-500/10
- Accent: teal-600 (buttons), emerald-500 (positive), red-500 (negative)

## Backlog
### P0
- Fund & Stock Rating System (Morningstar-style)
- Security: PAN encryption, consent logging (DPDP Act)

### P1
- Stock-level overlap via AMFI disclosure
- Mobile-first layout, simulation UX, goal-based planning

### P2
- Broker integrations, agent-based backend, offline support
