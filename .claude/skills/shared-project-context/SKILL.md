---
name: shared-project-context
description: Comprehensive shared project knowledge for all Claude roles working on Nivesh.ai and the NIDP platform.
---

# Nivesh.ai Shared Project Context

## Mission
Nivesh.ai is an AI-powered investment intelligence platform built on top of the NIDP (Nivesh Intelligence Data Platform).

NIDP is the core data, analytics, and agent platform that powers all applications including:
- Nivesh.ai consumer product
- Advisor and MFD dashboards
- Enterprise APIs
- Financial data catalog
- AI copilots and agents

Nivesh.ai helps investors, advisors, and wealth managers understand their portfolios and make better decisions.

The platform transforms raw portfolio data from Consolidated Account Statements (CAS), broker statements, and direct uploads into actionable insights covering:
- Portfolio health
- Asset allocation
- Performance attribution
- Risk analysis
- Tax analysis
- Diversification and concentration
- Benchmarking
- Goal readiness
- AI-driven recommendations

Every role working on this project must optimize for:
- Accuracy of financial calculations
- Data privacy and security
- Simplicity of user experience
- Trust and explainability
- High-quality engineering
- Production reliability
- Reusable platform architecture

---

# NIDP (Nivesh Intelligence Data Platform)

## Purpose
NIDP is the foundational platform that ingests, normalizes, enriches, stores, and serves financial data and analytics.

It acts as the system of record and computational engine for:
- Portfolio data
- Market data
- Mutual fund data
- Corporate fundamentals
- Risk metrics
- Tax analytics
- AI-ready knowledge

## NIDP Layers
1. Data Acquisition Layer
2. Document Processing Layer
3. Normalization Layer
4. Master Data Layer
5. Analytics Engine
6. Insight Generation Layer
7. API Layer
8. Agent Layer
9. Application Layer

## NIDP Data Domains
- Instruments master
- Prices and NAV history
- Corporate actions
- Financial statements
- Shareholding patterns
- Mutual fund scheme metadata
- Portfolio holdings and transactions
- Benchmarks and indices
- Tax rules
- Risk model outputs

## NIDP Core Tables (Conceptual)
- instruments
- prices_eod
- mf_nav_daily
- mf_scheme_master
- portfolios
- holdings
- transactions
- benchmarks
- analytics_results
- recommendations
- document_extractions

## NIDP Services
- FileAgent
- ParsingAgent
- EnrichmentAgent
- AnalyticsAgent
- RiskAgent
- TaxAgent
- RecommendationAgent
- CopilotAgent

## NIDP Strategic Goals
- Build the most comprehensive financial data catalog.
- Serve as a reusable platform for multiple products.
- Support India first, then global expansion.
- Provide institutional-grade analytics through APIs.

---

# Product Vision

## Core Promise
"Upload your portfolio and receive institution-grade analysis, personalized insights, and actionable recommendations in minutes."

## Strategic Goals
1. Become the most trusted AI investment copilot for Indian investors.
2. Simplify portfolio analysis for retail users.
3. Empower advisors and MFDs with scalable analytics.
4. Build a global investment intelligence platform.
5. Create a comprehensive financial data and analytics catalog through NIDP.

## Business Objectives
- Increase portfolio uploads.
- Improve user retention and engagement.
- Drive subscription conversion.
- Enable advisor workflows.
- Build enterprise-ready APIs.

---

# Target Personas

## Retail Investor
Needs easy-to-understand insights and recommendations.

## Mutual Fund Investor
Focuses on expense ratios, overlap, category diversification, and tax efficiency.

## Direct Equity Investor
Needs sector concentration, valuation, and risk analysis.

## Trader
Focuses on exposure, volatility, and tactical insights.

## MFD (Mutual Fund Distributor)
Requires client dashboards, review reports, and recommendation workflows.

## RIA (Registered Investment Advisor)
Needs fiduciary-grade analytics and documentation.

## Wealth Manager
Needs multi-client analytics and scalable reporting.

## Family Office
Requires advanced analytics and institutional reporting.

---

# Product Modules

## 1. Portfolio Upload and Parsing
## 2. Portfolio Dashboard
## 3. Insights and Recommendations
## 4. AI Copilot Chat
## 5. Performance and Benchmarking
## 6. Risk Analysis
## 7. Tax Analysis
## 8. Diversification and Concentration
## 9. Advisor Dashboard
## 10. Market Dashboard

---

# Architecture Principle
All user-facing applications must be built as thin experience layers on top of reusable NIDP data, analytics, and agent services.

---

# Technology Stack
- Frontend: React, Next.js, TypeScript
- Backend: Python, FastAPI
- Database: PostgreSQL
- Caching and queues: Redis and background workers
- AI orchestration: LLM agents and RAG
- Infrastructure: Docker, CI/CD, cloud deployment

---

# Security and Privacy
Always protect PAN, Aadhaar, names, addresses, emails, phone numbers, and account numbers.
Never expose raw PII in logs, prompts, screenshots, or documentation.

---

# Definition of Done
- Requirements documented
- Business rules validated
- Architecture approved
- Code implemented
- Tests passing
- Privacy and security reviewed
- Documentation updated
- Deployment verified
- Monitoring in place

---

# Guardrails
- NIDP is the platform foundation; avoid embedding business logic only in UI applications.
- Prefer reusable services over one-off implementations.
- Do not fabricate financial calculations.
- Do not expose PII.
- Preserve auditability and explainability.

---

# Example Prompt
Use the shared project context to understand both Nivesh.ai and the NIDP platform before executing specialized tasks.
