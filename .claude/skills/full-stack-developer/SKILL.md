---
name: full-stack-developer
description: Project-trained full stack developer for NIDP and Nivesh.ai.
---

# Full Stack Developer Skill

## Mission
Design, build, test, and maintain frontend and backend features for Nivesh.ai and the NIDP platform.

## Mandatory Pre-Read
1. ../shared-project-context/SKILL.md
2. docs/BUILD_CONTEXT.md
3. docs/FRD_V2_BACKEND.md
4. docs/FRD_V2_FRONTEND.md
5. docs/IMPLEMENTATION_GUIDELINES.md
6. Relevant source code modules

## Core Responsibilities
- Implement APIs and UI features
- Build data models and migrations
- Integrate analytics and AI services
- Write unit and integration tests
- Fix bugs and performance issues
- Maintain backward compatibility

## Technical Mental Model
Nivesh.ai is a thin user-facing application built on top of NIDP.

Layers:
1. Data ingestion and pipelines
2. Analytics engines
3. DAAS APIs
4. Copilot tools
5. LangGraph agents
6. FastAPI endpoints
7. Next.js frontend

## Primary Code Areas
- backend/nidp/
- backend/services/
- backend/routes/
- frontend/
- deploy/
- tests/

## Major Engines
- Technical Indicator Engine
- Fundamental Analytics Engine
- Mutual Fund Analytics Engine
- Portfolio Analytics Tools
- Capital Gains Engine
- LangGraph Copilot Agent

## Key Database Tables
- prices_eod
- stock_features_daily
- mf_nav_daily
- nse_financials_quarterly
- holdings
- transactions
- analytics_results
- recommendations

## Scheduled Jobs
- Technical indicators nightly
- Fundamental analytics refresh
- Mutual fund analytics refresh
- Market data ingestion
- Document processing jobs

## Standard Workflow
1. Read FRD and existing implementation.
2. Identify impacted modules.
3. Design API/schema changes.
4. Implement backend logic.
5. Implement frontend UI.
6. Add tests.
7. Validate with realistic data.
8. Update documentation.

## Coding Standards
- Follow existing patterns.
- Use strong typing.
- Keep functions focused.
- Avoid duplication.
- Externalize configuration.
- Never log PII.

## Testing Requirements
- Unit tests for business logic.
- Integration tests for APIs.
- Regression tests for financial calculations.
- Edge case validation.

## Security Requirements
- Mask PAN and other PII.
- Validate all inputs.
- Enforce authorization.
- Protect secrets.

## Performance Guidelines
- Batch database operations.
- Minimize N+1 queries.
- Use background jobs for heavy computation.
- Cache expensive calculations where appropriate.

## Common Tasks
- Add a new analytics API
- Build a dashboard widget
- Extend LangGraph nodes
- Add a scheduled job
- Optimize parsing pipelines
- Fix tax calculation defects

## Definition of Done
- Requirements understood
- Code implemented
- Tests passing
- Documentation updated
- Privacy validated
- Performance acceptable

## Reference Documents
- technical-architecture.md
- tech-stack.md
- database-schema.md
- sequence-diagrams.md
- scheduled-jobs.md
- coding-standards.md
- testing-strategy.md
- deployment-overview.md

## Example Prompt
Implement the requested feature by reviewing the relevant FRDs, existing modules, database schema, and tests. Follow NIDP platform architecture and update all impacted layers.
