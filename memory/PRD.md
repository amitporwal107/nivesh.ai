# WealthPilot - AI Financial Advisor Platform

## Architecture
- Backend: FastAPI + MongoDB + GPT-5.2 (emergentintegrations)
- Frontend: React + Tailwind + Shadcn UI + Recharts + Framer Motion
- Auth: Emergent Google OAuth
- Design: Kuvera-inspired (light/dark theme)

## What's Been Implemented (Apr 14, 2026)
### Core Features
- Google OAuth, portfolio CRUD, CAS PDF/CSV/Excel upload with AI parsing
- Dashboard: 5 KPI cards, performance trend, asset allocation donut, sector bar, heatmap treemap
- AI Chat (GPT-5.2), AI Insights generation

### New Features (This Session)
- **Family Portfolios**: Create/delete portfolios per family member (Self, Spouse, Child, Parent)
- **Multi-CAS Upload**: Upload CAS per portfolio member with password prompt
- **Asset Type Tabs**: Equity, Mutual Funds, ETFs, Gold & SGB, Other with counts
- **Sort & Filter**: Search by name/ticker/sector, sort by name/value/returns, filter by member
- **Smart Autocomplete**: 100+ Indian stocks, MFs, ETFs, gold bonds searchable when adding holdings
- **Dark Theme**: Full dark mode toggle with CSS variables
- **Top Movers Charts**: Horizontal bar charts for gainers/losers
- **Portfolio Member Column**: Holdings table shows which member owns each holding

## Backlog
### P1
- [ ] Real-time market price fetching (NSE/BSE API)
- [ ] Portfolio-specific analytics (per family member)
- [ ] Performance vs benchmark
### P2
- [ ] Agentic AI layer, Tax optimization
- [ ] Broker PDF parsing (Zerodha, ICICI, Angel One)
- [ ] Alerts & notifications
