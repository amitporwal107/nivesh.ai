---
name: shared-project-context
description: Comprehensive shared project knowledge for all Claude roles working on Nivesh.ai and the NIDP platform.
---

# Nivesh.ai Shared Project Context

# Golden Source Rule
This skill is a summary and orientation guide. The ultimate source of truth is the repository documentation under `docs/`, followed by implementation code under `backend/`, `frontend/`, `deploy/`, and `data/`.

Before making strategic, architectural, product, engineering, or operational decisions, always review the relevant canonical documents.

If there is any conflict between this skill and the documentation, the documentation takes precedence.

---

# Canonical Documentation Sources (Source of Truth)

## Strategic and Platform Context
- `docs/BUILD_CONTEXT.md`
- `docs/FRD_NIDP_PROJECT.md`
- `docs/NIDP_STATUS.md`
- `docs/ONBOARDING_STRATEGY.md`
- `docs/FRD_VERSION_REGISTRY.json`

## Product Requirements
- `docs/FRD_ADMIN_CONSOLE.md`
- `docs/FRD_COPILOT_V1.md`
- `docs/FRD_COPILOT_V2.md`
- `docs/FRD_V1_BACKEND.md`
- `docs/FRD_V1_FRONTEND.md`
- `docs/FRD_V2_BACKEND.md`
- `docs/FRD_V2_FRONTEND.md`

## Engineering Standards
- `docs/IMPLEMENTATION_GUIDELINES.md`

## Infrastructure and Security
- `docs/GCP_DEPLOYMENT_GUIDE.md`
- `docs/IAM_GUIDE.md`

## Operations and Runbooks
- `docs/operations/`

## Historical Context
- `docs/archive/`

---

# Mandatory Document Review Sequence

## Product Manager
1. FRD_NIDP_PROJECT
2. BUILD_CONTEXT
3. FRD_VERSION_REGISTRY
4. Relevant FRDs

## Business Analyst
1. FRD_NIDP_PROJECT
2. Relevant FRDs
3. IMPLEMENTATION_GUIDELINES

## Technical Architect
1. BUILD_CONTEXT
2. FRD_NIDP_PROJECT
3. NIDP_STATUS
4. IMPLEMENTATION_GUIDELINES
5. Deployment guides

## Full Stack Developer
1. BUILD_CONTEXT
2. Relevant backend/frontend FRDs
3. IMPLEMENTATION_GUIDELINES
4. Existing source code

## DevOps Engineer
1. GCP_DEPLOYMENT_GUIDE
2. IAM_GUIDE
3. docs/operations

## Quality Analyst
1. Relevant FRDs
2. BUILD_CONTEXT
3. IMPLEMENTATION_GUIDELINES

## Production Support
1. docs/operations
2. NIDP_STATUS
3. BUILD_CONTEXT

---

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

## Major Analytics Engines (from BUILD_CONTEXT)
- Technical Indicator Engine (28 indicators)
- Fundamental Analytics Engine
- Mutual Fund Analytics Engine
- Portfolio Analytics Tools
- Capital Gains Engine
- Risk and Stress Testing Engine

## AI Architecture
- RAG Orchestrator
- LangGraph multi-agent copilot
- Market Analyst
- Stock Analyst
- Mutual Fund Analyst
- Portfolio Analyst
- Risk Analyst
- Goal Planner
- Recommendation Engine
- Compliance Agent

## NIDP Strategic Goals
- Build the most comprehensive financial data catalog.
- Serve as a reusable platform for multiple products.
- Support India first, then global expansion.
- Provide institutional-grade analytics through APIs.

---

# Architecture Principle
All user-facing applications must be built as thin experience layers on top of reusable NIDP data, analytics, and agent services.

---

# Technology Stack
- Frontend: React, Next.js, TypeScript
- Backend: Python, FastAPI
- Database: PostgreSQL / TimescaleDB
- Caching and queues: Redis and background workers
- AI orchestration: LLM agents, RAG, LangGraph
- Infrastructure: Docker, CI/CD, GCP Cloud Run and related services

---

# Security and Privacy
Always protect PAN, Aadhaar, names, addresses, emails, phone numbers, and account numbers.
Never expose raw PII in logs, prompts, screenshots, or documentation.

---

# Definition of Done
- Relevant source documents reviewed
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
- Repository documentation is the golden source of truth.
- NIDP is the platform foundation; avoid embedding business logic only in UI applications.
- Prefer reusable services over one-off implementations.
- Do not fabricate financial calculations.
- Do not expose PII.
- Preserve auditability and explainability.

---

# Example Prompt
Use the shared project context and review the canonical documentation sources before executing specialized tasks.
