# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Recharts 3.x + Shadcn UI + Google OAuth (@react-oauth/google)
- **Backend**: FastAPI + Motor/MongoDB + OpenAI SDK (user's personal key)
- **PDF Parsing**: PyPDF2 + pdf2image + poppler + pycryptodome (AES)
- **AI**: OpenAI GPT-4o (CAS parsing) + GPT-4o-mini (chat/insights)
- **Live Prices**: yfinance (Yahoo Finance) for equity/ETF via NSE symbols, AMFI for MF NAV
- **SGB Prices**: RBI ISIN→Issue Price mapping table

## Core Features (Implemented)
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] Multi-format portfolio upload (CAS PDF, CSV, Excel)
- [x] Gmail auto-fetch for CAS statements
- [x] AMFI Live NAV integration & benchmark analysis
- [x] Visual insights (fund overlap, overexposure, performance cards)
- [x] AI-powered chat with portfolio context
- [x] Portfolio Health Score with breakdowns
- [x] Risk analysis with warnings and action plans
- [x] Smart recommendations with specific amounts
- [x] Live equity/ETF prices via Yahoo Finance (NSE ISIN mapping)
- [x] SGB issue price mapping from RBI data
- [x] Portfolio simulation (projected optimized returns)
- [x] Collapsible dashboard sections
- [x] Bar chart for portfolio performance trend
- [x] AMC-grouped fund benchmark drill-down
- [x] Holdings Heatmap with return % labels
- [x] Data quality flags (Simulated, Modeled, Missing CMP)

## Bug Fixes (April 2026 - Session 3)
- [x] **Issue 2 - Heatmap %**: Fixed SVG text rendering — Recharts 3.x strips custom props from Treemap content components. Used inline render function with closure access + system fonts instead of JetBrains Mono (wasn't loading in SVG context)
- [x] **Issue 3 - AI Insights Descriptions**: Enhanced cards to show full description text, current→target values, and fallback messages
- [x] **Issue 4 - SGB Issue Price**: Created comprehensive ISIN→Issue Price mapping table (services/sgb_prices.py) covering all SGB series 2015-2024. SGBs now show correct P&L (160-224% returns)

## Key DB Collections
- `whitelisted_users`: {email, status, is_admin}
- `users`: {user_id, email, name, picture, created_at}
- `portfolios`: {portfolio_id, user_id, name, member_name}
- `holdings`: {holding_id, portfolio_id, user_id, asset_type, name, ticker, quantity, buy_price, current_price, sector, price_source, nse_symbol, sgb_series, sgb_issue_date}

## Key API Endpoints
- `POST /api/auth/google` - Google OAuth login
- `GET /api/portfolio/analytics` - Analytics with live prices, SGB prices, data_flags
- `GET /api/portfolio/simulate` - Simulate optimized portfolio
- `POST /api/portfolio/refresh-prices` - Manual equity/ETF price refresh
- `GET /api/portfolio/deep-analytics` - Advanced analytics
- `GET /api/portfolio/fund-performance` - MF benchmark ratings

## Backlog (Prioritized)
### P0
- server.py refactoring — Split ~2300 lines into /routes directory using APIRouter
- Google OAuth URL whitelisting (blocked on user updating GCP console)

### P1
- **Issue 1 - CAS Monthly Data Chart**: Use actual CAS monthly portfolio values (Feb 2025→Feb 2026) instead of modeled 30-day trend
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Historical stock price API for equity CAGR calculation

### P2
- Finvu Account Aggregator (needs sandbox creds)
- Portfolio versioning (Delta tracking between CAS uploads)
- Agentic AI execution and scenario simulation

## Technical Notes
- Poppler-utils installed via server.py startup event
- OpenAI key is user's personal key (NOT Emergent LLM key)
- Recharts 3.x: Treemap content component does NOT receive custom data fields as props — use inline render function with closure access
- SVG text in Treemap must use system fonts (system-ui), not web fonts (JetBrains Mono doesn't render in SVG)
- Admin user: priyankamantri@gmail.com
