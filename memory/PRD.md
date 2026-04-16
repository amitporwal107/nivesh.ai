# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Recharts + Shadcn UI + Google OAuth (@react-oauth/google)
- **Backend**: FastAPI + Motor/MongoDB + OpenAI SDK (user's personal key)
- **PDF Parsing**: PyPDF2 + pdf2image + poppler + pycryptodome (AES)
- **AI**: OpenAI GPT-4o (CAS parsing) + GPT-4o-mini (chat/insights)
- **Live Prices**: yfinance (Yahoo Finance) for equity/ETF via NSE symbols

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
- [x] Portfolio simulation (projected optimized returns)
- [x] Collapsible dashboard sections
- [x] Bar chart for portfolio performance trend
- [x] AMC-grouped fund benchmark drill-down
- [x] Data quality flags (Simulated, Modeled, Missing CMP)

## Bug Fixes & Enhancements (April 2026 - Session 2)
- [x] **Issue 7 - Live Prices**: Yahoo Finance integration for equity/ETF CMP via ISIN→NSE symbol mapping (33 holdings updated)
- [x] **Issue 1 - Actionable Insights**: Recommendations now show specific reduce/add amounts with current→target percentages + Simulate Optimized Portfolio button
- [x] **Issue 2 - 0% Returns**: Fixed by live price integration (equities now show actual P&L)
- [x] **Issue 3 - Risk Drill-Down**: Risk factors now include specific action plans with guidance
- [x] **Issue 4 - Bar Graph**: Portfolio Performance trend changed from AreaChart to BarChart with benchmark explanation
- [x] **Issue 5 - Fund Benchmark Drill-Down**: Fund-by-Fund comparison now grouped by AMC with expandable details
- [x] **Issue 6 - Collapsible Widgets**: All major dashboard sections (Performance, Allocation, Sector, Heatmap) are now collapsible
- [x] **Issue 8 - Performance Graph**: 30-day modeled trend with "How is this calculated?" explanation

## Key DB Collections
- `whitelisted_users`: {email, status, is_admin, invited_at, registered_at}
- `gmail_imports`: {user_id, message_id, imported_at, status, count}
- `users`: {user_id, email, name, picture, created_at}
- `portfolios`: {portfolio_id, user_id, name, member_name, relationship}
- `holdings`: {holding_id, portfolio_id, user_id, asset_type, name, isin, quantity, avg_price, current_price, sector, price_source, nse_symbol, price_updated_at}
- `upload_tasks`: {task_id, user_id, status, message, count, source, created_at}

## Key API Endpoints
- `POST /api/auth/google` - Google OAuth login
- `GET /api/portfolio/analytics` - Portfolio analytics with live prices, data_flags, live_price_stats
- `GET /api/portfolio/simulate` - Simulate optimized portfolio with projected returns
- `POST /api/portfolio/refresh-prices` - Manual equity/ETF price refresh from Yahoo Finance
- `GET /api/gmail/status` - Gmail status + last import info
- `GET /api/portfolio/deep-analytics` - Advanced analytics with live prices
- `GET /api/portfolio/fund-performance` - MF benchmark ratings
- `POST /api/portfolio/upload-raw` - CAS PDF upload

## Backlog (Prioritized)
### P0
- server.py refactoring — Split ~2200 lines into /routes directory using APIRouter
- Google OAuth URL whitelisting (blocked on user updating GCP console)

### P1
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Finvu Account Aggregator integration (needs sandbox credentials)
- Historical stock price API for equity CAGR calculation

### P2
- Portfolio versioning (Delta tracking between CAS uploads)
- Agentic AI execution and scenario simulation
- Performance graph matching actual CAS monthly data (Issue 8 partially done — currently modeled)

## Technical Notes
- Poppler-utils installed via server.py startup event (survives container restarts)
- OpenAI key is user's personal key (NOT Emergent LLM key)
- Day change and performance trend are SIMULATED (no live market feed)
- Live equity/ETF prices via yfinance + NSE ISIN mapping (cached 5 min)
- Admin user: priyankamantri@gmail.com
