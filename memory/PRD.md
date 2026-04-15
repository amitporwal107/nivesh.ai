# nivesh.ai — Product Requirements Document

## Problem Statement
AI-powered autonomous financial advisor for Indian retail investors. Invite-only access, portfolio upload/parsing, unified dashboard, actionable insights, AI chat.

## Tech Stack
- **Frontend:** React 18, Tailwind CSS, Recharts, Shadcn UI, Framer Motion, @react-oauth/google
- **Backend:** FastAPI, Motor/MongoDB, PyPDF2, pdf2image/poppler, google-api-python-client
- **AI:** OpenAI SDK direct (gpt-4o for CAS parsing, gpt-4o-mini for chat/insights)
- **Auth:** Direct Google OAuth 2.0 + Email Whitelist
- **Market Data:** AMFI NAV, mfapi.in
- **Email:** Gmail API (read-only, CAS auto-fetch)

## What's Been Implemented (All Complete)

### Core — Auth, Upload, Dashboard
- Direct Google OAuth 2.0 + invite-only email whitelist
- Admin panel (sidebar tab) with add/remove/block/bulk-upload/CSV
- CAS PDF/CSV/Excel upload, family portfolios, dark/light mode
- Interactive dashboard with drill-down charts

### AI & Insights (Redesigned)
- **Portfolio Health Score** — Single metric (0-100) with circular gauge
- **Actionable Insight Cards** — Problem → Why → Action → Impact in collapsible cards
- **"If You Apply These Changes"** — Before/After with ₹ impact and 10Y wealth gain
- **"What Happens If You Do Nothing?"** — Urgency section with annual cost leak
- **Interactive Action Funnel** — Checkboxes with progress tracker
- **Data Confidence Score** — Shows data quality (holdings tracked, NAV matched)
- **Severity hierarchy** — Critical (red), Important (amber), Optimize (blue), Positive (green)

### Market Data & Benchmark
- AMFI Live NAV (31K+ schemes), Overexposure, Fund Overlap, Performance Cards
- MF Benchmark Rating via mfapi.in (Outperforming/Meeting/Underperforming)

### Gmail Auto-Fetch
- Gmail OAuth connect, CAS email scanner, one-click import, deduplication

### Cost Optimization
- Switched from Emergent LLM Key (GPT-5.2) to direct OpenAI SDK
- gpt-4o-mini for chat & insights (~90% cost reduction)
- gpt-4o for CAS parsing (accuracy-critical)

## Admin
- Admin email: priyankamantri@gmail.com (seeded on startup)
- Whitelisted: priyankamantri@gmail.com, rohit123gupta@gmail.com

## Remaining Backlog
- P0: Finvu Account Aggregator integration
- P1: Goal-based planning (Retirement, Child Education)
- P1: Historical stock price API for equity
- P2: Agentic AI execution and scenario simulation
