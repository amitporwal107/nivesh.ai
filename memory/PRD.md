# WealthPilot - AI Financial Advisor Platform

## Original Problem Statement
Build an AI-powered autonomous financial advisor for Indian retail investors. Phase 1 MVP.

## Architecture
- Backend: FastAPI + MongoDB + GPT-5.2 (emergentintegrations)
- Frontend: React + Tailwind + Shadcn UI + Recharts
- Auth: Emergent Google OAuth

## What's Been Implemented (Apr 14, 2026)
- Google OAuth login via Emergent Auth
- Portfolio CRUD (add/edit/delete holdings)
- CAS PDF upload with AI-powered parsing (GPT-5.2 vision, async background processing)
- CSV and Excel (.xlsx) upload support
- Portfolio analytics (asset allocation, sector exposure, risk scoring)
- AI Chat interface (GPT-5.2 financial advisor)
- AI Insights generation
- Dashboard with charts

## Bug Fixes Applied
1. CAS PDF: Image-based PDF support (NSDL CAS PDFs are rendered as images)
2. CAS PDF: Page count detection fallback (pdfinfo/poppler when PyPDF2 fails with startxref error)
3. CAS PDF: Raw upload endpoint to avoid multipart form parsing timeout on large files
4. CAS PDF: Async background processing with status polling
5. CAS PDF: pdf2image fallback for page extraction when PyPDF2 page split fails
6. CSV: Multi-encoding support (UTF-8, latin-1, cp1252)
7. Excel: Column index bug fix (name_i=0 evaluated as falsy)

## Backlog
### P0 - Done
- [x] CAS PDF upload parsing
### P1
- [ ] Real-time market price fetching
- [ ] Advanced portfolio scoring
- [ ] Tax optimization suggestions
### P2
- [ ] Agentic AI layer
- [ ] Broker PDF parsing (Zerodha, ICICI, Angel One)
- [ ] Performance vs benchmark
- [ ] Alerts & notifications
