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
- [x] Chat Sessions with conversation history & context
- [x] Markdown rendering for AI chat responses
- [x] Risk Profile Questionnaire (6-question detailed assessment, sidebar)

## Complete Onboarding Flow (Implemented - Apr 16, 2026)
- [x] **Step 1: Investor Type** — Existing Investor / New to Investing selection
- [x] **New Investor Path (8 steps)**:
  - Age input with +/- buttons and preset options
  - Investment Goal selection (Retirement, House, Education, Travel, Wealth, Emergency)
  - Risk Appetite (Conservative, Moderate, Aggressive)
  - Investment Horizon (< 3yr, 3-7yr, 7-15yr, 15+yr)
  - Monthly Investment (optional, with ₹5K/10K/25K/50K presets)
  - Starter Plan — rule-based allocation (Equity/Debt/Gold/Cash), fund category recommendations, SIP wealth projection, personalized insights
  - Playbook (3 Cards: Start SIP, Track Goals, Learn & Grow)
  - → Dashboard
- [x] **Existing Investor Path (4 steps)**:
  - Data Source Selection: Upload CAS (CDSL/NSDL), Fetch from Gmail, Account Aggregator (Coming Soon)
  - Upload step with drag-drop zone / Gmail connect
  - Playbook (3 Cards: Portfolio Health Check, Smart Rebalancing, Set Goals)
  - → Dashboard
- [x] **SEBI Disclaimer** — "For educational purposes only. Please consult a SEBI registered investment advisor." visible on all steps
- [x] Backend endpoints: POST /api/user/quick-setup, POST /api/user/complete-onboarding

## Bug Fixes (April 2026 - Session 3)
- [x] **Issue 2 - Heatmap %**: Fixed SVG text rendering
- [x] **Issue 3 - AI Insights Descriptions**: Enhanced cards with full descriptions
- [x] **Issue 4 - SGB Issue Price**: Comprehensive ISIN→Issue Price mapping

## Key DB Collections
- `whitelisted_users`: {email, status, is_admin}
- `users`: {user_id, email, name, picture, created_at}
- `user_profiles`: {user_id, journey_type, risk_profile, onboarding_completed, quick_setup, starter_plan}
- `portfolios`: {portfolio_id, user_id, name, member_name}
- `holdings`: {holding_id, portfolio_id, user_id, asset_type, name, ticker, quantity, buy_price, current_price, sector}
- `chat_sessions`: {session_id, user_id, title, created_at}
- `chat_messages`: {message_id, session_id, user_id, role, content, created_at}

## Key API Endpoints
- `POST /api/auth/google` - Google OAuth login
- `GET /api/user/profile` - Full user profile (journey, risk, quick_setup, starter_plan)
- `POST /api/user/journey` - Set investor type
- `POST /api/user/quick-setup` - Save quick setup + generate starter plan
- `POST /api/user/complete-onboarding` - Mark onboarding complete
- `POST /api/user/risk-profile` - Save detailed risk assessment
- `GET /api/portfolio/analytics` - Analytics with live prices
- `POST /api/portfolio/upload` - Upload CAS/CSV/Excel
- `GET /api/portfolio/simulate` - Simulate optimized portfolio
- `POST /api/chat/` - AI chat with portfolio context
- `GET /api/chat/sessions` - Chat session history

## Backlog (Prioritized)
### P0
- server.py refactoring — Split ~2500 lines into /routes directory using APIRouter
- Google OAuth URL whitelisting (blocked on user updating GCP console)

### P1
- Connect to a Human Advisor (from user's .docx file)
- Goal-based planning module (Retirement, Child Education) with AI-calculated SIPs
- Issue 1 - CAS Monthly Data Chart: Use actual CAS monthly portfolio values

### P2
- Finvu Account Aggregator integration (needs sandbox creds)
- Portfolio versioning (Delta tracking between CAS uploads)
- Agentic AI execution and scenario simulation

## Technical Notes
- Poppler-utils installed via server.py startup event (DO NOT REMOVE)
- OpenAI key is user's personal key (NOT Emergent LLM key)
- Recharts 3.x: Treemap content component does NOT receive custom data fields as props
- Admin user: priyankamantri@gmail.com
- Starter plan allocation is rule-based (age + risk + horizon), no OpenAI dependency
