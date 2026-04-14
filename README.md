# nivesh.ai

**AI-Powered Autonomous Financial Advisor for Indian Investors**

[![Built with FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React%2018-61DAFB?style=flat-square&logo=react)](https://react.dev/)
[![MongoDB](https://img.shields.io/badge/Database-MongoDB-47A248?style=flat-square&logo=mongodb)](https://www.mongodb.com/)
[![GPT-5.2](https://img.shields.io/badge/AI-GPT--5.2-412991?style=flat-square&logo=openai)](https://openai.com/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

> Track all your assets, get AI-powered insights, and make confident investment decisions. Built specifically for Indian retail investors.

![nivesh.ai Dashboard](https://img.shields.io/badge/Status-Production%20Ready-brightgreen?style=flat-square)

---

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Data Sources](#data-sources)
- [Roadmap](#roadmap)

---

## Overview

**nivesh.ai** is a full-stack, AI-powered wealth management platform designed for Indian retail investors. It consolidates portfolios across stocks, mutual funds, ETFs, bonds, gold, and fixed deposits into a single intelligent dashboard with real-time NAV data, benchmark analysis, and actionable AI recommendations.

### Key Differentiators

- **CAS PDF Parsing** — Upload your NSDL/CDSL Consolidated Account Statement (including password-protected and image-based PDFs) and let GPT-5.2 extract all holdings automatically
- **Live AMFI NAV** — Real-time mutual fund pricing from AMFI India (31,000+ schemes)
- **Benchmark Intelligence** — Every mutual fund rated against its category-average benchmark using 1-year historical data
- **Product Intelligence** — Composite Health Score (A+ to F), risk analysis, concentration warnings, and cost optimization suggestions
- **Indian Market Focus** — INR formatting (Lakhs/Crores), SEBI-compliant disclaimers, Indian sector classifications

---

## Features

### Portfolio Management
- Multi-format upload: **CAS PDF** (text + image-based), **CSV**, **Excel (.xlsx)**
- Password-protected PDF support with PyPDF2 + poppler decryption
- Binary streaming upload (bypasses Kubernetes 30s ingress timeout for large files)
- Family portfolio management (Self, Spouse, Child, Parent)
- Smart instrument autocomplete for manual entry (500+ Indian stocks & MFs)
- Asset categorization: Equity, Mutual Fund, ETF, Bond, Gold, FD

### Dashboard & Analytics
- KPI cards: Total Invested, Current Value, Returns, Day Change, Risk Score
- Interactive Treemap heatmap with click-through drill-down
- Asset allocation donut chart and sector exposure bar chart
- 30-day portfolio performance trend
- Top gainers and losers
- Lakh / Crore / Auto number format toggle

### AI-Powered Insights (5-Tab Analysis)

| Tab | What It Shows |
|-----|---------------|
| **AI Overview** | Priority Matrix (2x2), Action Funnel, Risk Gauge, Before/After Impact, Problem Distribution, Detailed Insight Cards |
| **Benchmark** | MF Performance vs Benchmark donut, Best/Worst Performers, Category Overlap bar graph, Fund-by-Fund Benchmark Comparison with alpha |
| **Overexposure** | Fund House (AMC) concentration chart, Sector concentration chart with expandable detail cards |
| **Fund Overlap** | Overlap matrix between MF pairs (by sector, mandate, AMC), High/Medium/Low summary |
| **Performance** | Sortable table with P&L, weight, CAGR, asset type filters, LIVE NAV badges |

### Product Intelligence Engine
- **Health Score** (0-100, Grade A+ to F) — Diversification, Risk, Cost Efficiency, Performance
- **Risk Analysis** — HHI concentration index, top holding %, equity overweight, regular plan warnings
- **Smart Recommendations** — Regular-to-Direct switch savings, dead position cleanup, allocation rebalancing, tax loss harvesting

### AI Chat
- Portfolio-aware financial advisor powered by GPT-5.2
- Conversation history with context from your actual holdings
- Indian market expertise (NSE/BSE, SEBI regulations, tax planning)

### Other
- Google OAuth authentication (Emergent Managed)
- Dark / Light mode
- Fully responsive design

---

## Tech Stack

### Frontend

| Technology | Purpose |
|---|---|
| **React 18** | UI framework |
| **Tailwind CSS** | Utility-first styling |
| **Shadcn/UI** | Component library (buttons, cards, dialogs, tables, etc.) |
| **Recharts** | Charts — PieChart, BarChart, AreaChart, Treemap |
| **Framer Motion** | Animations and transitions |
| **Axios** | HTTP client |
| **Sonner** | Toast notifications |
| **Lucide React** | Icon library |
| **CRACO** | CRA configuration override (path aliases) |

### Backend

| Technology | Purpose |
|---|---|
| **FastAPI** | Async Python web framework |
| **Uvicorn** | ASGI server with hot reload |
| **Motor** | Async MongoDB driver |
| **PyPDF2** | PDF text extraction and decryption |
| **pdf2image + poppler** | Image-based PDF rendering |
| **openpyxl** | Excel file parsing |
| **httpx** | Async HTTP client (AMFI API, mfapi.in) |
| **Pydantic v2** | Request/response validation with strict typing |
| **python-dateutil** | Date parsing for CAGR calculations |

### AI / ML

| Technology | Purpose |
|---|---|
| **GPT-5.2** (via `emergentintegrations`) | CAS PDF parsing, portfolio insights generation, AI chat |
| **Emergent LLM Key** | Universal API key for OpenAI integration |

### Database

| Technology | Purpose |
|---|---|
| **MongoDB** | Document store for users, portfolios, holdings, insights, chat |

### External Data Sources

| Source | Data |
|---|---|
| **AMFI India** (`portal.amfiindia.com/spages/NAVAll.txt`) | Live NAV for 31,000+ mutual fund schemes (refreshed hourly) |
| **mfapi.in** | Historical NAV data per scheme for 1-year return calculations |

### Infrastructure

| Technology | Purpose |
|---|---|
| **Kubernetes** | Container orchestration |
| **Supervisor** | Process management (frontend + backend) |
| **Google OAuth** (Emergent Managed) | Authentication |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLIENT (Browser)                         │
│  React 18 + Tailwind + Recharts + Shadcn/UI + Framer Motion     │
└─────────────────────────────┬────────────────────────────────────┘
                              │ HTTPS
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                     KUBERNETES INGRESS                            │
│              /api/* → Backend (8001)                              │
│              /*     → Frontend (3000)                             │
└─────────────────────────────┬────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
┌─────────────────────────┐    ┌─────────────────────────────────┐
│   FRONTEND (Port 3000)  │    │     BACKEND (Port 8001)         │
│                         │    │                                 │
│  Pages:                 │    │  server.py (Route Layer)        │
│   ├── Landing.js        │    │   ├── Auth Routes               │
│   ├── Dashboard.js      │    │   ├── Portfolio CRUD            │
│   └── AuthCallback.js   │    │   ├── Upload (Raw Binary)       │
│                         │    │   ├── Analytics                  │
│  Components:            │    │   ├── Benchmark                  │
│   ├── DashboardOverview │    │   ├── Insights (AI)              │
│   ├── PortfolioView     │    │   └── Chat (AI)                  │
│   ├── FamilyView        │    │                                 │
│   ├── InsightsView      │    │  models.py (Validation)         │
│   │   ├── AI Overview   │    │  repository.py (DB Access)      │
│   │   ├── Benchmark     │    │  middleware.py (Rate Limit/CORS)│
│   │   ├── Overexposure  │    │                                 │
│   │   ├── Fund Overlap  │    │  services/                      │
│   │   └── Performance   │    │   ├── __init__.py (Intelligence)│
│   ├── ChatView          │    │   ├── ai_engine.py (GPT-5.2)   │
│   └── Sidebar           │    │   ├── amfi_nav.py (Live NAV)   │
│                         │    │   └── fund_performance.py       │
│  Context:               │    │       (Benchmark Ratings)       │
│   ├── AuthContext        │    │                                 │
│   ├── ThemeContext       │    └────────────┬────────────────────┘
│   └── NumberFormatCtx   │                  │
└─────────────────────────┘                  │
                                             ▼
                              ┌──────────────────────────┐
                              │     MongoDB              │
                              │                          │
                              │  Collections:            │
                              │   ├── users              │
                              │   ├── user_sessions      │
                              │   ├── portfolios         │
                              │   ├── holdings           │
                              │   ├── upload_tasks       │
                              │   ├── chat_messages      │
                              │   ├── ai_insights        │
                              │   └── portfolio_analysis │
                              └──────────────────────────┘

                    External Services:
                    ┌─────────────────────────────────┐
                    │  AMFI India (Live NAV, 31K+)    │
                    │  mfapi.in (Historical NAV)      │
                    │  GPT-5.2 (AI Parsing & Chat)    │
                    │  Google OAuth (Authentication)   │
                    └─────────────────────────────────┘
```

### Backend Layer Responsibilities

| Layer | File | Responsibility |
|---|---|---|
| **Routes** | `server.py` | HTTP endpoints, request handling, response formatting. Kept thin — delegates to services. |
| **Validation** | `models.py` | Pydantic models with field validators, enums for asset types and relationships. |
| **Repository** | `repository.py` | All MongoDB operations abstracted. Excludes `_id` from responses. |
| **Middleware** | `middleware.py` | Rate limiting, CORS configuration, environment validation. |
| **Services** | `services/` | Core business logic — health score computation, AI integration, NAV fetching, benchmark analysis. |

---

## Database Schema

### `users`
```json
{
  "user_id": "user_a1b2c3d4e5f6",
  "email": "investor@example.com",
  "name": "Rahul Sharma",
  "picture": "https://...",
  "created_at": "2026-02-14T10:30:00Z"
}
```

### `portfolios`
```json
{
  "portfolio_id": "pf_x1y2z3",
  "user_id": "user_a1b2c3d4e5f6",
  "name": "My Portfolio",
  "member_name": "Rahul Sharma",
  "relationship": "Self",
  "created_at": "2026-02-14T10:30:00Z"
}
```

### `holdings`
```json
{
  "holding_id": "hold_abc123",
  "portfolio_id": "pf_x1y2z3",
  "user_id": "user_a1b2c3d4e5f6",
  "name": "HDFC Top 100 Fund - Direct Growth",
  "ticker": "INF179K01BB2",
  "asset_type": "mutual_fund",
  "quantity": 150.5,
  "buy_price": 520.0,
  "current_price": 612.45,
  "sector": "Large Cap",
  "buy_date": "2023-06-15",
  "nav_source": "AMFI",
  "nav_date": "14-Apr-2026",
  "created_at": "2026-02-14T10:30:00Z"
}
```

### `upload_tasks`
```json
{
  "task_id": "task_def456",
  "user_id": "user_a1b2c3d4e5f6",
  "status": "completed",
  "message": "24 holdings imported from CAS PDF",
  "count": 24,
  "holdings": [{"holding_id": "...", "name": "...", "asset_type": "...", "quantity": 0}],
  "created_at": "2026-02-14T10:30:00Z"
}
```

### `chat_messages`
```json
{
  "message_id": "msg_ghi789",
  "user_id": "user_a1b2c3d4e5f6",
  "role": "user",
  "content": "Should I invest more in mid-cap funds?",
  "created_at": "2026-02-14T10:30:00Z"
}
```

---

## API Reference

### Authentication
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/auth/session` | Exchange Google OAuth session_id for session token |
| `GET` | `/api/auth/me` | Get current authenticated user |
| `POST` | `/api/auth/logout` | Clear session |

### Portfolio Management
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/portfolios` | List all portfolios with holdings count |
| `POST` | `/api/portfolios` | Create new portfolio (name, member, relationship) |
| `DELETE` | `/api/portfolios/{id}` | Delete portfolio and cascade delete holdings |

### Holdings
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/portfolio/holdings` | Get holdings (optional: `portfolio_id`, `asset_type` filters) |
| `POST` | `/api/portfolio/holdings` | Add a single holding |
| `PUT` | `/api/portfolio/holdings/{id}` | Update holding fields |
| `DELETE` | `/api/portfolio/holdings/{id}` | Delete a holding |

### File Upload
| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/portfolio/upload-raw` | **Primary** — Raw binary upload with headers: `X-Filename`, `X-Portfolio-Id`, `X-Password` |
| `POST` | `/api/portfolio/upload` | Multipart upload (CSV/Excel only — PDFs may timeout) |
| `GET` | `/api/portfolio/upload-status/{task_id}` | Poll background CAS PDF processing status |
| `GET` | `/api/portfolio/upload-latest-task` | Get most recent upload task |

### Analytics & Insights
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/portfolio/analytics` | Full dashboard analytics (auto-updates MF NAVs) — returns health_score, risk_analysis, recommendations, heatmap_data, performance_trend |
| `GET` | `/api/portfolio/deep-analytics` | Overexposure (fund house + sector), fund overlap matrix, performance cards |
| `GET` | `/api/portfolio/fund-performance` | MF benchmark ratings — 1Y return vs category-average from mfapi.in |
| `POST` | `/api/nav/refresh` | Force refresh AMFI NAV cache and update all MF holdings |
| `POST` | `/api/insights/generate` | Generate AI-powered insights via GPT-5.2 |
| `GET` | `/api/insights/analysis` | Get cached portfolio analysis |

### AI Chat
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/chat/messages` | Get chat history |
| `POST` | `/api/chat/send` | Send message, receive AI response (portfolio-aware) |
| `DELETE` | `/api/chat/clear` | Clear chat history |

### Search
| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/search/instruments?q=hdfc` | Autocomplete search for Indian stocks & MFs |

---

## Getting Started

### Prerequisites

- **Node.js** 18+ and **Yarn**
- **Python** 3.11+
- **MongoDB** 6.0+
- **poppler-utils** (for image-based PDF parsing)

### Environment Variables

**Backend** (`/backend/.env`):
```env
MONGO_URL=mongodb://localhost:27017
DB_NAME=nivesh_db
CORS_ORIGINS=*
EMERGENT_LLM_KEY=your_emergent_llm_key
```

**Frontend** (`/frontend/.env`):
```env
REACT_APP_BACKEND_URL=http://localhost:8001
```

### Installation

```bash
# Backend
cd backend
pip install -r requirements.txt
sudo apt-get install poppler-utils  # For image-based PDF support
uvicorn server:app --host 0.0.0.0 --port 8001 --reload

# Frontend
cd frontend
yarn install
yarn start
```

The app will be available at `http://localhost:3000`.

---

## Project Structure

```
nivesh.ai/
├── backend/
│   ├── server.py                 # FastAPI routes (thin layer)
│   ├── models.py                 # Pydantic models & enums
│   ├── repository.py             # MongoDB operations
│   ├── middleware.py              # Rate limiting, CORS, env validation
│   ├── instruments_data.py       # Indian stocks/MF autocomplete DB
│   ├── requirements.txt
│   ├── services/
│   │   ├── __init__.py           # Health Score, Risk Analysis, Recommendations
│   │   ├── ai_engine.py          # GPT-5.2 integration
│   │   ├── amfi_nav.py           # AMFI Live NAV scraper (31K+ schemes)
│   │   └── fund_performance.py   # Benchmark ratings via mfapi.in
│   └── tests/
│       ├── test_deep_analytics.py
│       └── test_fund_performance.py
│
├── frontend/
│   ├── package.json
│   ├── tailwind.config.js
│   ├── craco.config.js
│   └── src/
│       ├── App.js
│       ├── index.js
│       ├── pages/
│       │   ├── Landing.js        # Public landing page
│       │   ├── Dashboard.js      # Authenticated dashboard shell
│       │   └── AuthCallback.js   # OAuth callback
│       ├── components/
│       │   ├── Sidebar.js
│       │   ├── DashboardOverview.js
│       │   ├── PortfolioView.js
│       │   ├── FamilyView.js
│       │   ├── ChatView.js
│       │   ├── InsightsView.js   # 5-tab analysis (AI, Benchmark, Overexposure, Overlap, Performance)
│       │   ├── DrilldownModal.js
│       │   └── ui/              # Shadcn components
│       └── context/
│           ├── AuthContext.js
│           ├── ThemeContext.js
│           └── NumberFormatContext.js
│
└── memory/
    └── PRD.md                    # Product requirements document
```

---

## Data Sources

| Source | URL | Data | Update Frequency |
|---|---|---|---|
| **AMFI India NAV** | `portal.amfiindia.com/spages/NAVAll.txt` | Live NAV for 31,000+ MF schemes (ISIN, scheme code, NAV, date) | Cached 1 hour |
| **mfapi.in** | `api.mfapi.in/mf/{scheme_code}` | Historical NAV (daily) per scheme for 1Y return calculation | On-demand |
| **AMFI Fund Performance** | `amfiindia.com/otherdata/fund-performance` | Benchmark returns, riskometer, AUM (reference) | — |
| **AMFI Portfolio Disclosure** | `amfiindia.com/online-center/portfolio-disclosure` | Underlying stock holdings per MF (future integration) | — |

---

## Roadmap

### Completed

- [x] Google OAuth authentication
- [x] Multi-format portfolio upload (CAS PDF, CSV, Excel)
- [x] Password-protected PDF support
- [x] Family portfolio management
- [x] Interactive dashboard with drill-down charts
- [x] AMFI Live NAV integration (31K+ schemes)
- [x] Health Score, Risk Analysis, Recommendations engine
- [x] AI-generated insights (Priority Matrix, Action Funnel)
- [x] MF Benchmark Rating (Outperforming / Meeting / Underperforming)
- [x] Category Overlap bar graph
- [x] Fund-by-Fund Benchmark Comparison with alpha
- [x] Fund House & Sector Overexposure visualization
- [x] Fund Overlap Matrix
- [x] Performance Cards (sortable, filterable, CAGR)
- [x] AI Chat with portfolio context
- [x] Dark / Light mode

### Upcoming

- [ ] Goal-based planning (Retirement, Child Education) with AI-calculated SIPs
- [ ] Historical stock price integration for equity holdings
- [ ] Portfolio disclosure integration for real company-level overlap
- [ ] MF comparison mode (side-by-side)
- [ ] Tax loss harvesting suggestions
- [ ] SIP tracking and recommendations
- [ ] Agentic AI execution and scenario simulation

---

## License

MIT

---

<p align="center">
  <strong>nivesh.ai</strong> — Your money deserves smarter decisions.
</p>
