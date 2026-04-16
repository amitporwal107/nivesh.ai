# nivesh.ai - Product Requirements Document

## Original Problem Statement
Build an AI-powered autonomous financial advisor (Agentic Wealth System). Focus on Indian market (NSE/BSE, MFs), portfolio upload/parsing, unified dashboard, insights, and chat interface.

## Architecture
- **Frontend**: React + Tailwind CSS + Recharts + Shadcn UI + Google OAuth (@react-oauth/google)
- **Backend**: FastAPI + Motor/MongoDB + OpenAI SDK (user's personal key)
- **PDF Parsing**: PyPDF2 + pdf2image + poppler + pycryptodome (AES)
- **AI**: OpenAI GPT-4o (CAS parsing) + GPT-4o-mini (chat/insights)

## Core Features (Implemented)
- [x] Google OAuth with invite-only whitelist
- [x] Admin dashboard for email whitelisting
- [x] Multi-format portfolio upload (CAS PDF, CSV, Excel)
- [x] Gmail auto-fetch for CAS statements
- [x] AMFI Live NAV integration & benchmark analysis
- [x] Visual insights (fund overlap, overexposure, performance cards)
- [x] AI-powered chat with portfolio context
- [x] Portfolio Health Score with breakdowns
- [x] Risk analysis with warnings
- [x] Smart recommendations (Regular→Direct, rebalancing)

## Bug Fixes (April 2026)
- [x] **Data Quality Flags**: Day Change marked as "Simulated", Performance Trend as "Modeled"
- [x] **Assumed Data Badges**: Holdings with CMP = Buy Price flagged "Needs Data" 
- [x] **Sector Exposure**: Fixed to equity-only (excludes MFs)
- [x] **Calculation Explanations**: Info tooltips on Health Score, Risk Score, Diversification, Cost Efficiency, Performance
- [x] **Risk Drill-down**: Shows risk factors with severity, description, and clickable holdings breakdown
- [x] **Missing CMP Highlighting**: Amber row highlighting + "No live CMP" label in portfolio grid
- [x] **Gmail Import History**: Status endpoint shows last import timestamp; dedicated history API
- [x] **Upload History API**: Track all file uploads with status and timestamps

## Key DB Collections
- `whitelisted_users`: {email, status, is_admin, invited_at, registered_at}
- `gmail_imports`: {user_id, message_id, imported_at, status, count}
- `users`: {user_id, email, name, picture, created_at}
- `portfolios`: {portfolio_id, user_id, name, member_name, relationship}
- `holdings`: {holding_id, portfolio_id, user_id, asset_type, name, isin, quantity, avg_price, current_price, sector, uploaded_at}
- `upload_tasks`: {task_id, user_id, status, message, count, source, created_at}

## Key API Endpoints
- `POST /api/auth/google` - Google OAuth login
- `GET /api/portfolio/analytics` - Portfolio analytics with data_flags
- `GET /api/gmail/status` - Gmail status + last import info
- `GET /api/gmail/history` - Gmail import history
- `GET /api/portfolio/upload-history` - File upload history
- `POST /api/portfolio/upload-raw` - CAS PDF upload
- `GET /api/portfolio/deep-analytics` - Advanced analytics
- `GET /api/portfolio/fund-performance` - MF benchmark ratings

## Backlog (Prioritized)
### P0
- Finvu Account Aggregator integration (needs sandbox credentials)
- Fix portfolio value discrepancy (needs user to upload new CAS for validation)

### P1
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Historical stock price API for equity holdings (live CMP)
- SGB series name preservation in CAS parsing
- MF Performance drill-down with benchmark comparison
- Best & Worst section separated for equity/MF with "show more"

### P2
- Portfolio versioning (Delta tracking between CAS uploads)
- Agentic AI execution and scenario simulation
- Data confidence tracking and improvement guidance
- CAS file download history with links
- UI readability improvements (tabs for categories)

### Refactoring
- server.py split into /routes directory using APIRouter (~2200 lines)

## Technical Notes
- Poppler-utils installed via server.py startup event (survives container restarts)
- OpenAI key is user's personal key (NOT Emergent LLM key)
- Day change and performance trend are SIMULATED (no live market feed)
- Admin user: priyankamantri@gmail.com
