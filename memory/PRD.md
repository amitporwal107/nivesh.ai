# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor for Indian market.

## Architecture
- React + Tailwind + Shadcn | FastAPI + MongoDB + OpenAI gpt-4o-mini
- CAS Parser SDK, AMFI NAV, NSE Bhav Copy, yfinance

## Implemented Features
- [x] Google OAuth + whitelist + Admin, CAS Parser SDK
- [x] Onboarding, Risk Profile, Quick Setup
- [x] SSE streaming chat + intent UX + quick actions + skeleton loaders
- [x] MF benchmark + Portfolio P&L Heatmap + Fund House stacked chart
- [x] Fund Overlap v2 (duplication score, AI insights, stacked bars)
- [x] AI Look-Through Allocation Analysis (OpenAI, no PII)
- [x] Dual-mode theme (Light + Dark MOS-inspired)
- [x] MOS-style allocation display (alert + stacked bar + drillable sectors)
- [x] **AI Overview page restructured**:
  - Flow: Health → Risk → Confidence → Issue Breakdown → Cost Leakage → Insights → Action Plan → Simulate
  - Data Confidence capped at 100% (was 105%)
  - Removed "Optimized Portfolio" label and "Do Nothing" standalone section
  - Simulate shows Before/After only after button click
  - "Data missing" shown when data unavailable (no hallucination)

## Backlog
### P0
- Fund & Stock Rating System, Security (DPDP Act)
### P1
- Stock-level overlap, mobile-first layout, goal-based planning
### P2
- Broker integrations, agent-based backend, offline support
