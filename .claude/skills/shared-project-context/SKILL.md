---
name: shared-project-context
description: Shared project knowledge for all Claude roles working on Nivesh.ai.
---

# Nivesh.ai Shared Project Context

## Product Vision
Nivesh.ai is an AI-powered investment intelligence platform that helps Indian investors upload CAS statements and brokerage portfolio files, analyze portfolio health, and receive actionable insights across performance, diversification, taxation, risk, benchmarking, and personalized recommendations.

## Target Personas
- Retail investors
- Mutual fund investors
- Direct equity investors
- Traders
- Mutual Fund Distributors (MFDs)
- Registered Investment Advisors (RIAs)
- Wealth managers

## Core Modules
1. Portfolio Upload and Parsing
2. Portfolio Dashboard
3. Insights and Recommendations
4. AI Copilot Chat
5. Risk Analysis
6. Tax Analysis
7. Performance and Benchmarking
8. Diversification and Concentration
9. Advisor Dashboard
10. Market Dashboard

## Key Workflow
1. User uploads CAS PDF or broker statement.
2. Parsing services extract holdings and transactions.
3. Holdings are normalized and enriched with market and fund data.
4. Analytics compute risk, tax, performance, and diversification metrics.
5. Dashboards and AI Copilot present insights and recommendations.

## Technology Stack
- Frontend: React / Next.js / TypeScript
- Backend: Python FastAPI and supporting services
- Data: PostgreSQL and market data pipelines
- AI: LLM-powered agent architecture
- Infrastructure: Docker, CI/CD, cloud deployment

## Engineering Principles
- Mobile-first design
- API-first architecture
- Modular agents and services
- Strong test coverage
- Secure handling of financial and personal data
- PII masking in logs and sample documents

## Coding Standards
- Small, focused modules
- Type hints and documentation
- Automated tests for critical logic
- Configuration externalized via environment variables
- Structured logging and monitoring

## Data Privacy
Always mask or avoid exposing:
- PAN
- Aadhaar
- Name
- Address
- Email
- Phone number
- Account numbers

## Definition of Done
- Requirements documented
- Architecture reviewed
- Code implemented
- Tests passed
- Security and privacy validated
- Documentation updated
- Deployment verified

## Common Commands
- Understand the relevant docs before making changes.
- Follow existing architectural patterns.
- Preserve backward compatibility where possible.
- Add or update tests.
- Update documentation.

## Example Prompt
"Use the shared project context to understand the Nivesh.ai platform before performing your specialized role tasks."
