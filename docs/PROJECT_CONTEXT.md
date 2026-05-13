# PROJECT_CONTEXT.md
## Nivesh AI Copilot — Single Source of Truth for All Coding Agents

> **USAGE RULE**: Every coding agent MUST read this file at task start. Extract only the sections relevant to your task. Do NOT re-read the full PRD PDFs.

---

## 1. PROJECT SUMMARY

**Product**: Nivesh AI Copilot — ChatGPT-style conversational financial intelligence platform for Indian retail investors, MFDs, RIAs, and wealth advisors.

**Core AI Pattern**: Domain-Aware Tool-Based Agentic RAG with Deterministic Analytics. All numerical answers are grounded in tool outputs — no invented numbers.

**NIDP Role**: The Nivesh Intelligence Data Platform (NIDP) is the authoritative enterprise data catalogue. It is the single source of truth for all analytics, scoring, APIs, and AI responses. The Copilot never reads raw market data directly — it always goes through NIDP DAAS APIs.

**KPI Targets**:
- Hallucination rate < 1%
- Response latency < 5 seconds (P95)
- Tool execution success rate > 99.5%
- CSAT > 4.7 / 5
- Availability 99.9%

**Release Milestones**:
1. **Internal Alpha** (Sprint 4 end) — Core agents + analytics working internally
2. **Advisor Beta** (Sprint 7 end) — Full specialist agents + portfolio analytics for beta advisors
3. **Production GA** (Sprint 10 end) — All features, compliance, observability, full launch

---

## 2. TECHNICAL ARCHITECTURE

### 9 Product Architecture Layers (bottom → top)
1. **Data Sources** — NSE, BSE, AMFI, RBI, Bloomberg, broker feeds
2. **NIDP Data Pipeline** — Ingestion, normalization, validation, quality gates
3. **NIDP DAAS API** — Internal REST API exposing all NIDP data to services
4. **Primitive Store** — Normalized scoring primitives from V2/V3 engines
5. **Analytics Engines** — 6 deterministic calculation engines (see §5)
6. **Agent Tool Registry** — All analytics + NIDP endpoints wrapped as LangGraph tools
7. **LangGraph Orchestrator** — Multi-agent routing and state management
8. **Specialist Agents** — 9 domain agents (see §6)
9. **FastAPI Chat API** — WebSocket + REST endpoints consumed by frontend

### 10 AI Components
1. Intent Classifier — Routes queries to correct specialist agent
2. Tool Registry — Wraps all analytics/data functions as callable tools
3. LangGraph State Machine — Manages multi-turn conversation state
4. Specialist Agent Pool — 9 domain-expert agents
5. Hallucination Guard — Validates all numeric outputs against tool results
6. Confidence Scorer — Attaches 0.00–1.00 confidence to every response
7. Compliance Filter — Suitability + risk disclosure enforcement
8. Conversation Memory — Per-user short-term + long-term memory in PostgreSQL
9. Response Formatter — Structures output with citations, disclaimers, charts
10. Observability Layer — Langfuse traces + Prometheus metrics + audit logs

### Repository Structure
```
nivesh-ai-copilot/           # or within /app/
  apps/
    api/                     # FastAPI chat server
    frontend/                # Next.js / React UI
  services/
    analytics/               # 6 analytics engines
    recommendation/          # Composite recommendation engine
    memory/                  # Conversation memory service
  agents/
    orchestrator/            # LangGraph graph definition
    specialists/             # 9 specialist agent implementations
    tools/                   # Tool registry wrappers
  shared/
    nidp_client/             # NIDP DAAS API SDK
    primitives/              # Primitive store client
    schemas/                 # Pydantic models
    utils/                   # Shared utilities
  infrastructure/
    docker/
    k8s/
    terraform/
  tests/
    unit/
    integration/
    e2e/
  docs/
```

### Existing Codebase Status (as of 2026-05-13)
The following is already built under `/app/backend/`:

**NIDP Data Pipeline (COMPLETE)**:
- `nidp/services/amfi_circulars/`, `amfi_nav/`, `amfi_nav_history/`
- `nidp/services/announcement_classifier/`, `bhavcopy/`
- `nidp/services/block_deals/`, `bulk_deals/`, `corporate_actions/`
- `nidp/services/corporate_announcements/`
- `nidp/services/portfolio_holdings_sync/` (new — CAS sync pipeline)
- `nidp/dags/` — DAGs: corporate_actions, delivery, flows, macro, market_eod, quality_gate, reference
- `nidp/migrations/046_nidp_portfolio_sync_log.sql`
- `nidp/migrations/047_nidp_performance_layer.sql`

**Backend Routes (PARTIAL)**:
- `routes/auth.py`, `routes/admin_nidp.py`, `routes/admin_users.py`
- `routes/copilot_widgets.py` — widget API endpoints
- `models_copilot_widgets.py` — widget DB models

**Frontend (PARTIAL)**:
- `frontend/src/components/copilot/widgets/` — OverlapRevealWidget, RebalancePlanWidget, SectorRotationWidget, StressTestWidget, TaxHarvestWidget
- `frontend/src/pages/Chat.jsx` — Chat page shell
- `frontend/src/pages/NiveshV2.jsx` — V2 UI shell
- `frontend/src/components/v2app/` — V2 component library

**What remains to build**: LangGraph agents, analytics engines, primitive store, full tool registry, recommendation engine, conversation memory, hallucination guard, full chat API, observability.

---

## 3. DOMAIN MODEL

### Core Entities

| Entity | Key Fields | Source |
|--------|-----------|--------|
| User | user_id, risk_profile, goals[], kyc_status, broker_links[] | PostgreSQL users table |
| Portfolio | portfolio_id, user_id, holdings[], as_of_date, xirr | portfolio_holdings_sync |
| Holding | isin, symbol, quantity, avg_cost, current_value, weight_pct | CAS / broker feed |
| Stock | isin, symbol, exchange, sector, industry, market_cap_category | NIDP reference |
| MutualFund | scheme_code, isin, amc, category, sub_category, benchmark | AMFI / NIDP |
| Instrument | asset_type ∈ {EQUITY, MF, ETF, BOND, GOLD}, isin | Unified |
| Goal | goal_id, user_id, target_amount, horizon_years, risk_band | User-defined |
| RiskProfile | profile_id, risk_band ∈ {conservative, moderate, aggressive}, score | Questionnaire |
| Primitive | as_of_date, asset_type, asset_id, primitive_name, primitive_value, primitive_percentile, source_table, calculation_version | Primitive Store |
| Conversation | session_id, user_id, messages[], agent_traces[], created_at | Memory store |

### Scoring Model — Recommendation Composite (0–100)
| Component | Weight | Engine |
|-----------|--------|--------|
| Fundamental Score | 30% | Fundamental Analytics |
| Technical Score | 20% | Technical Analytics |
| Valuation Score | 15% | Fundamental Analytics |
| Risk Suitability | 15% | Risk Analytics |
| Portfolio Fit | 10% | Portfolio Analytics |
| Goal Alignment | 10% | Goal Planning |

### Risk Bands
- **Conservative**: Debt/hybrid heavy, max 30% equity, low volatility tolerance
- **Moderate**: Balanced 50/50, medium volatility tolerance
- **Aggressive**: 70%+ equity, high volatility tolerance, long horizon

---

## 4. MODULE MAP

### Analytics Engines (services/analytics/)

| Engine | Key Calculations | Primary Inputs |
|--------|-----------------|----------------|
| `technical/` | RSI, MACD, Bollinger Bands, ADX, ATR, EMA, SMA, Volume OBV | OHLCV price series |
| `fundamental/` | ROE, ROCE, PE, PB, EV/EBITDA, Piotroski F-Score, Altman Z-Score, DCF | Financial statements |
| `mutual_fund/` | Sharpe, Sortino, Treynor, Alpha, Beta, Rolling Returns, Overlap Matrix, Expense Ratio | NAV history, benchmark |
| `portfolio/` | XIRR, Diversification Score, Concentration (HHI), Sector allocation, Asset allocation | Holdings + prices |
| `risk/` | VaR (95%, 99%), CVaR, Suitability Score, Volatility, Max Drawdown, Correlation | Portfolio, risk profile |
| `recommendation/` | Composite Score 0–100, Buy/Hold/Sell signal, Conviction level | All engine outputs |

### Specialist Agents (agents/specialists/)

| Agent | Trigger Intent | Primary Tools |
|-------|---------------|---------------|
| `market_analyst` | Market overview, indices, macro | NIDP market data, macro indicators |
| `stock_analyst` | Stock analysis, fundamentals, technical | Technical + Fundamental engines |
| `mf_analyst` | Fund analysis, comparison, selection | MF Analytics engine, AMFI data |
| `portfolio_analyst` | Portfolio review, performance, rebalancing | Portfolio + Risk engines |
| `risk_analyst` | Risk profiling, suitability, stress test | Risk engine, user profile |
| `goal_planner` | Goal setting, SIP planning, retirement | Goal engine, portfolio projections |
| `recommendation` | Buy/hold/sell recommendations | Recommendation engine (all inputs) |
| `compliance` | Regulatory checks, suitability filters | Risk profile, regulatory rules |
| `report_generator` | PDF/HTML report generation | All agents, formatting tools |

### NIDP DAAS API Client (shared/nidp_client/)
14 tool categories exposed as SDK methods:
1. Market Data (indices, OHLCV, breadth)
2. Stock Fundamentals (financials, ratios, screener)
3. Mutual Fund Data (NAV, AUM, portfolio, returns)
4. Corporate Actions (dividends, splits, buybacks, results)
5. Announcements (NSE/BSE filings, news sentiment)
6. Bulk/Block Deals
7. Delivery & Volume
8. Macro Indicators (CPI, repo rate, FII/DII flows)
9. Portfolio Holdings (user CAS data)
10. Benchmark Data (Nifty 50, Nifty 500, sector indices)
11. Historical Prices (EOD, adjusted, split-adjusted)
12. Sector/Industry Classification
13. Peer Comparison
14. Watchlist / Alerts

---

## 5. API INVENTORY

### Chat API (FastAPI — apps/api/)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/v1/chat/session` | Create new chat session |
| GET | `/v1/chat/session/{session_id}` | Get session history |
| POST | `/v1/chat/message` | Send message, get response (REST) |
| WS | `/v1/chat/ws/{session_id}` | WebSocket streaming chat |
| GET | `/v1/chat/session/{session_id}/export` | Export conversation as PDF |
| DELETE | `/v1/chat/session/{session_id}` | Delete session |

### Portfolio API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/portfolio/{user_id}` | Get user portfolio summary |
| GET | `/v1/portfolio/{user_id}/holdings` | Get holdings list |
| GET | `/v1/portfolio/{user_id}/performance` | XIRR, returns, benchmarks |
| POST | `/v1/portfolio/{user_id}/analyze` | Trigger portfolio analysis |
| GET | `/v1/portfolio/{user_id}/overlap` | Fund overlap matrix |
| GET | `/v1/portfolio/{user_id}/rebalance` | Rebalancing suggestions |

### Analytics API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/v1/analytics/stock/{isin}/technical` | Technical indicators |
| GET | `/v1/analytics/stock/{isin}/fundamental` | Fundamental ratios |
| GET | `/v1/analytics/mf/{scheme_code}/performance` | MF performance metrics |
| GET | `/v1/analytics/recommendation/{isin}` | Composite recommendation score |

### Admin / NIDP API (existing)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/admin/nidp/status` | NIDP pipeline status |
| POST | `/admin/nidp/trigger/{dag_id}` | Trigger DAG manually |
| GET | `/admin/nidp/quality` | Quality gate results |

---

## 6. DATABASE SCHEMA SUMMARY

### Core Tables

**users** (existing)
```sql
user_id UUID PK, email, phone, kyc_status, risk_profile_id, created_at
```

**portfolio_holdings** (new — migration 020)
```sql
holding_id UUID PK, user_id FK, isin, symbol, exchange, quantity DECIMAL,
avg_cost DECIMAL, current_price DECIMAL, as_of_date DATE,
source ENUM('CAS','BROKER','MANUAL'), updated_at TIMESTAMPTZ
```

**portfolio_pg_user_map** (new — migration 020)
```sql
pg_user_id UUID PK, user_id FK, pg_account_id TEXT, broker TEXT, linked_at TIMESTAMPTZ
```

**nidp_portfolio_sync_log** (new — migration 046)
```sql
sync_id UUID PK, user_id FK, status ENUM, cas_file_hash TEXT,
records_processed INT, errors JSONB, synced_at TIMESTAMPTZ
```

**nidp_performance_layer** (new — migration 047)
```sql
perf_id UUID PK, user_id FK, as_of_date DATE, xirr DECIMAL,
absolute_return DECIMAL, benchmark_return DECIMAL, alpha DECIMAL,
computed_at TIMESTAMPTZ
```

**primitive_store** (to build)
```sql
prim_id UUID PK, as_of_date DATE, asset_type TEXT, asset_id TEXT,
primitive_name TEXT, primitive_value DECIMAL, primitive_percentile DECIMAL,
source_table TEXT, calculation_version TEXT,
created_at TIMESTAMPTZ,
UNIQUE(as_of_date, asset_type, asset_id, primitive_name, calculation_version)
```

**chat_sessions** (to build)
```sql
session_id UUID PK, user_id FK, title TEXT, agent_context JSONB,
created_at TIMESTAMPTZ, last_message_at TIMESTAMPTZ
```

**chat_messages** (to build)
```sql
message_id UUID PK, session_id FK, role ENUM('user','assistant','tool'),
content TEXT, tool_calls JSONB, confidence DECIMAL, created_at TIMESTAMPTZ
```

**agent_audit_log** (to build)
```sql
trace_id UUID PK, session_id FK, message_id FK, agent_name TEXT,
tools_invoked JSONB, duration_ms INT, hallucination_flag BOOL,
compliance_flag BOOL, created_at TIMESTAMPTZ
```

### NIDP Tables (existing)
- `nidp_bhavcopy`, `nidp_nav`, `nidp_nav_history`, `nidp_corporate_actions`
- `nidp_announcements`, `nidp_block_deals`, `nidp_bulk_deals`
- `nidp_delivery_volumes`, `nidp_macro_indicators`
- All have `source_run_id`, `job_run_id`, `quality_status`, `ingested_at`

**GOTCHA**: `job_run_id` is the correct column name (NOT `source_run_id`). `actual` field in `validation_findings` is TEXT `'True'`/`'False'`, not boolean.

### TimescaleDB Hypertables
- `nidp_ohlcv` — partitioned by `trade_date`
- `nidp_nav_history` — partitioned by `nav_date`
- `nidp_performance_layer` — partitioned by `as_of_date`

### pgvector Tables
- `nidp_documents` — `(doc_id, content, embedding vector(1536), source, created_at)` — for RAG over announcements/filings

---

## 7. CODING STANDARDS

### Language & Framework
- **Python 3.12** only. Use `|` union types, not `Optional[X]`. Use `match` for dispatch.
- **FastAPI** for all HTTP services. Use `APIRouter` with prefix. No global state in route handlers.
- **Pydantic v2** for all request/response models. Use `model_validator` not `validator`.
- **SQLAlchemy 2.0** with `async` sessions. Never use ORM lazy loading in async context.
- **Alembic** for all migrations. Never run raw `CREATE TABLE` in application code.

### Naming Conventions
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- DB tables: `snake_case` with service prefix (e.g., `nidp_`, `copilot_`)
- API routes: kebab-case path segments, snake_case query params

### Code Rules
- **No tool-free numbers**: Every numerical claim in an agent response MUST come from a tool call result. No hardcoded financial figures.
- **Type hints everywhere**: All function signatures must have full type annotations.
- **No bare `except:`**: Always catch specific exceptions.
- **No `print()`**: Use `structlog` for all logging.
- **Async by default**: All I/O (DB, HTTP, Redis) must be async.
- **No secrets in code**: All secrets via environment variables, accessed through `helpers/secrets.py`.
- **Idempotency**: All data pipeline tasks must be idempotent (re-runnable without duplicate data).
- **Confidence mandatory**: Every agent response object must include `confidence: float` (0.00–1.00).
- **Disclaimers mandatory**: Every investment-related response must include the standard disclaimer.

### Error Handling Pattern
```python
from structlog import get_logger
log = get_logger()

try:
    result = await tool.execute(params)
except NIDPAPIError as e:
    log.error("nidp_api_failure", tool=tool.name, error=str(e))
    raise AgentToolError(f"Data unavailable: {tool.name}") from e
```

### Response Schema (all agent outputs)
```python
class AgentResponse(BaseModel):
    query_id: str
    session_id: str
    agent: str
    response_text: str
    confidence: float          # 0.00–1.00
    tools_invoked: list[str]
    data_as_of: date | None
    disclaimer: str            # Always present for financial responses
    charts: list[ChartSpec]    # Optional
    citations: list[Citation]  # Source references
    follow_up_questions: list[str]
```

---

## 8. DEFINITION OF DONE (per task)

A task is COMPLETE only when ALL of the following pass:

- [ ] **Implementation**: All acceptance criteria from TASK_REGISTRY implemented
- [ ] **Tests**: Unit tests ≥ 90% coverage; integration tests for all tool calls; edge cases covered
- [ ] **Types**: `mypy --strict` passes with zero errors
- [ ] **Linting**: `ruff check` passes with zero warnings
- [ ] **No hardcoded values**: No financial constants, no API keys, no magic numbers without named constants
- [ ] **Logging**: All entry/exit points of tools and agents emit structured logs via structlog
- [ ] **Error handling**: All external calls wrapped in try/except with specific exception types
- [ ] **Schema validation**: All inputs validated with Pydantic before processing
- [ ] **Async**: All I/O operations are async
- [ ] **Migration**: If DB schema changed, Alembic migration file included and tested
- [ ] **API contract**: If new endpoint added, OpenAPI spec auto-generated and matches Pydantic model
- [ ] **Confidence**: Agent responses include confidence score
- [ ] **Disclaimer**: Financial responses include standard disclaimer

---

## 9. IMPLEMENTATION STRATEGY

### Development Phases

| Phase | Focus | Sprint | Status |
|-------|-------|--------|--------|
| 0 | Repo setup, CI/CD, dev environment | S0 | Mostly done |
| 1 | NIDP SDK + data access layer | S1 | Mostly done (NIDP pipeline built) |
| 2 | Primitive store + V2/V3 adapter | S1-S2 | TODO |
| 3 | Technical analytics engine | S2 | TODO |
| 4 | Fundamental analytics engine | S2-S3 | TODO |
| 5 | Mutual fund analytics engine | S3 | TODO |
| 6 | Portfolio analytics engine | S3-S4 | Partial (XIRR, holdings sync done) |
| 7 | Risk analytics engine | S4 | TODO |
| 8 | Recommendation engine | S4-S5 | TODO |
| 9 | LangGraph orchestrator + tool registry | S5 | TODO |
| 10 | Specialist agents | S5-S6 | TODO |
| 11 | Conversation memory | S6 | TODO |
| 12 | FastAPI chat API + WebSocket | S6-S7 | Partial (Chat.jsx shell exists) |
| 13 | Frontend chat + dashboard | S7-S8 | Partial (widgets built) |
| 14 | Security + compliance layer | S8-S9 | TODO |
| 15 | Observability + production hardening | S9-S10 | TODO |

### Key Architectural Decisions
1. **LangGraph over raw LangChain**: Use `StateGraph` with typed state dicts. Agents are nodes; routing is edges.
2. **Tool-first grounding**: Agents MUST call tools. If a tool fails, the agent returns "data unavailable" — never guesses.
3. **Primitive store as cache**: Reuse V2/V3 scoring engine outputs via primitive adapters — don't re-implement scoring logic.
4. **NIDP as sole data source**: No direct DB reads from analytics engines — always via NIDP DAAS API client.
5. **Async throughout**: Python asyncio + FastAPI async routes + SQLAlchemy async sessions.
6. **Streaming responses**: WebSocket with `async_generator` patterns for token streaming.

### Data Refresh Schedule (IST)
- EOD batch: 6 PM – 11 PM (all NIDP pipelines run in sequence)
- Intraday: Price quotes via TrueData live feed (trial through 2026-05-14 — validation only)
- Analytics recompute: Triggered after EOD batch completes (queue-based)
- Primitive store refresh: Nightly post-analytics

### Environment Variables (required)
```
NIDP_API_BASE_URL, NIDP_API_KEY
OPENAI_API_KEY, OPENAI_MODEL (default: gpt-4o)
LANGFUSE_SECRET_KEY, LANGFUSE_PUBLIC_KEY, LANGFUSE_HOST
DATABASE_URL (PostgreSQL async DSN)
REDIS_URL
TRUEDATA_USERNAME, TRUEDATA_PASSWORD (trial only)
```
