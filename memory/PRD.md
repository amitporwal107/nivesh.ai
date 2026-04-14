# WealthPilot - AI Financial Advisor Platform

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System) for Indian retail investors. Phase 1 MVP.

## Architecture
- Backend: FastAPI + MongoDB + GPT-5.2 (via emergentintegrations)
- Frontend: React + Tailwind + Shadcn UI + Recharts
- Auth: Emergent Google OAuth
- Design: Kuvera.in inspired (clean white, emerald green)

## What's Been Implemented (Apr 14, 2026)
- Google OAuth login via Emergent Auth
- Portfolio CRUD (add/edit/delete holdings)
- **CAS PDF upload** with AI-powered parsing (GPT-5.2 vision, async background processing)
- CSV and Excel (.xlsx) upload support
- Portfolio analytics (asset allocation, sector exposure, risk scoring)
- AI Chat interface (GPT-5.2 financial advisor)
- AI Insights generation
- Dashboard with charts (pie chart, sector bars, risk meter)
- Responsive sidebar navigation

## Bug Fixes
- CAS PDF upload: Fixed image-based PDF support (PyPDF2 returns empty text for NSDL CAS)
- Added page-by-page AI vision processing for image-based PDFs
- Made CAS upload async with polling to avoid HTTP timeout
- Fixed Excel column index bug (name_i=0 evaluated as falsy)
- Fixed CSV encoding for non-UTF-8 files

## Prioritized Backlog
### P0
- [x] CAS PDF upload parsing (DONE)
- [ ] Real-time market price fetching

### P1  
- [ ] Advanced portfolio scoring (ML-based)
- [ ] Scenario simulation
- [ ] Tax optimization suggestions
- [ ] Goal-based planning (retirement, education)

### P2
- [ ] Agentic AI layer (autonomous agents)
- [ ] Broker PDF parsing (Zerodha, ICICI, Angel One)
- [ ] Performance vs benchmark comparison
- [ ] Alerts & notifications
- [ ] Auto execution (broker integration)
