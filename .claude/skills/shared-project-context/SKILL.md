---
name: shared-project-context
description: Comprehensive shared project knowledge for all Claude roles working on Nivesh.ai.
---

# Nivesh.ai Shared Project Context

## Mission
Nivesh.ai is an AI-powered investment intelligence platform that helps investors, advisors, and wealth managers understand their portfolios and make better decisions.

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

---

# Product Vision

## Core Promise
"Upload your portfolio and receive institution-grade analysis, personalized insights, and actionable recommendations in minutes."

## Strategic Goals
1. Become the most trusted AI investment copilot for Indian investors.
2. Simplify portfolio analysis for retail users.
3. Empower advisors and MFDs with scalable analytics.
4. Build a global investment intelligence platform.
5. Create a comprehensive financial data and analytics catalog.

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
- CAMS, KFintech, NSDL, CDSL CAS PDFs
- Broker holdings (ICICI Direct, Angel One, Motilal Oswal)
- Excel and CSV imports
- PII masking
- Data validation

## 2. Portfolio Dashboard
- Net worth summary
- Asset allocation
- Portfolio health score
- Top insights

## 3. Insights and Recommendations
- Strengths and weaknesses
- Actionable suggestions
- Prioritized recommendations

## 4. AI Copilot Chat
- Portfolio Q&A
- Tax and risk questions
- Scenario simulation

## 5. Performance and Benchmarking
- XIRR
- CAGR
- Alpha and beta
- Benchmark comparison

## 6. Risk Analysis
- Volatility
- Drawdown
- Sharpe ratio
- Stress tests

## 7. Tax Analysis
- LTCG/STCG estimation
- Tax-loss harvesting
- Unrealized gains

## 8. Diversification and Concentration
- Sector, market cap, issuer, category, and style exposure

## 9. Advisor Dashboard
- Client monitoring and review workflows

## 10. Market Dashboard
- Macro and market intelligence

---

# Primary Workflow
1. User uploads documents.
2. Files are securely stored.
3. Parsing extracts holdings and transactions.
4. Data is normalized.
5. Instruments are enriched with market and fund metadata.
6. Analytics compute metrics.
7. Insights are generated.
8. Dashboards render results.
9. AI Copilot answers contextual questions.
10. Recommendations are presented.

---

# Financial Domain Knowledge

## Asset Classes
- Equity
- Mutual Funds
- ETFs
- Debt
- Gold
- Cash and Fixed Deposits
- Government Securities
- REITs and InvITs

## Mutual Fund Categories
- Large Cap
- Mid Cap
- Small Cap
- Flexi Cap
- ELSS
- Hybrid
- Debt
- International
- Index Funds

## Key Metrics
- XIRR
- CAGR
- Absolute return
- Alpha
- Beta
- Sharpe ratio
- Sortino ratio
- Standard deviation
- Maximum drawdown
- Expense ratio
- Turnover ratio

---

# Tax Domain Knowledge (India)

## Equity Taxation
- Short-term capital gains (STCG)
- Long-term capital gains (LTCG)

## Mutual Fund Taxation
- Equity-oriented funds
- Debt-oriented funds
- Hybrid funds

## Tax Workflows
- Gain realization analysis
- Tax-loss harvesting
- Estimated tax liability

Note: Tax rules change over time; implementations must be versioned and configurable.

---

# Risk Framework

## Risk Dimensions
- Asset allocation risk
- Concentration risk
- Volatility risk
- Drawdown risk
- Liquidity risk
- Correlation risk
- Tax risk

## Stress Scenarios
- COVID crash
- 2008 crisis
- Rising interest rates
- Sector-specific shocks

---

# Diversification Framework

Analyze concentration across:
- Asset class
- Sector
- Industry
- Market capitalization
- AMC
- Mutual fund category
- Single stock
- Single fund
- Issuer
- Theme

Typical thresholds:
- Single stock > 10–15%
- Single sector > 25–30%
- Single fund > 20–25%

---

# Data Sources

## Mutual Fund Data
- AMFI NAV feed
- AMFI scheme metadata
- MFAPI.in

## Equity Data
- NSE
- BSE
- Yahoo Finance (backfill)

## Corporate Data
- Financial statements
- Shareholding patterns
- Corporate actions

## Benchmark Data
- Nifty indices
- Sensex
- Category benchmarks

---

# Document Parsing

## Supported Inputs
- PDF
- Excel
- CSV
- Images (future)

## Parsing Pipeline
1. OCR if needed.
2. Layout analysis.
3. Table extraction.
4. Entity recognition.
5. Data normalization.
6. Validation.
7. PII masking.

## Critical Fields
- Investor name
- PAN (masked)
- Folio number
- Scheme name
- ISIN
- Quantity
- NAV or price
- Cost basis
- Transactions

---

# Technology Stack

## Frontend
- React
- Next.js
- TypeScript
- Tailwind CSS
- Charting libraries

## Backend
- Python
- FastAPI
- Agent-based services

## Data Layer
- PostgreSQL
- Redis (optional)
- Background jobs

## AI Layer
- LLM orchestration
- Retrieval-augmented context
- Specialized agents

## Infrastructure
- Docker
- CI/CD pipelines
- Cloud deployment

---

# Architecture Principles
- Domain-driven design
- Modular services
- API-first development
- Separation of parsing, enrichment, analytics, and presentation
- Event-driven processing where appropriate
- Idempotent jobs

---

# Engineering Standards

## Coding
- Small, focused modules
- Clear naming
- Type hints
- Docstrings
- Linting and formatting

## API Design
- RESTful endpoints
- Pydantic models
- Consistent error responses
- Pagination and filtering

## Database
- Normalized schema
- Versioned migrations
- Index optimization

## Testing
- Unit tests
- Integration tests
- Regression tests
- Golden datasets for financial validation

---

# Security and Privacy

Always protect:
- PAN
- Aadhaar
- Names
- Addresses
- Emails
- Phone numbers
- Bank and demat account numbers

Requirements:
- Encryption at rest and in transit
- Role-based access
- Secure secret management
- Audit logging
- Data retention policies

Never expose raw PII in logs, screenshots, prompts, or documentation.

---

# Quality Principles
- Financial calculations must be reproducible.
- Recommendations must be explainable.
- UI should be intuitive and mobile-first.
- Every change should include tests.
- Performance should scale to large portfolios.

---

# UI and UX Principles
- Mobile-first design
- Minimal cognitive load
- Persona-specific dashboards
- Rich visualizations
- Clear plain-language summaries
- Drill-down capabilities

---

# Performance Requirements
- Large CAS parsing should complete efficiently.
- Portfolio analytics should be responsive.
- Chat responses should use contextual portfolio data.
- Background jobs should be retryable.

---

# DevOps Principles
- Infrastructure as code
- Automated CI/CD
- Environment promotion
- Health checks
- Monitoring and alerting
- Backup and recovery

---

# Production Support Principles
- Standard incident severity levels
- Root cause analysis
- Runbooks
- Escalation matrix
- Post-incident reviews

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

# Common Cross-Role Workflow
1. Product Manager creates PRD.
2. Business Analyst elaborates stories and acceptance criteria.
3. Architect designs the solution.
4. Designer prepares UX.
5. Developers implement.
6. QA validates.
7. DevOps deploys.
8. Project Manager tracks execution.
9. Production Support monitors and resolves incidents.

---

# Glossary (Selected)
- CAS: Consolidated Account Statement
- XIRR: Extended Internal Rate of Return
- NAV: Net Asset Value
- LTCG: Long-Term Capital Gains
- STCG: Short-Term Capital Gains
- AMC: Asset Management Company
- AUM: Assets Under Management
- PII: Personally Identifiable Information

---

# Guardrails
- Do not fabricate financial calculations.
- Do not expose PII.
- Do not change core business logic without documenting assumptions.
- Always preserve auditability.
- Prefer explainability over opaque recommendations.

---

# Example Prompt
Use the shared project context to understand Nivesh.ai's product, financial domain, architecture, engineering standards, and operational principles before executing specialized tasks.
