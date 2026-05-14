# IMPLEMENTATION_GUIDELINES.md
## Nivesh AI Copilot — Architecture & Engineering Rules

> All coding agents MUST follow these guidelines exactly. These override any default patterns.

---

## 1. ARCHITECTURE PRINCIPLES

### P1 — Tool-Grounded Answers Only
Every numerical or factual claim in an agent response MUST originate from a tool call result stored in LangGraph state. Agents may not generate numbers from parametric knowledge. If tool call fails → return structured "data unavailable" error, not a guess.

### P2 — NIDP Is the Only Data Source
Analytics engines and agents never query PostgreSQL directly for market/financial data. They call the `NIDPClient` SDK. The NIDPClient calls the NIDP DAAS API. This ensures all data goes through NIDP's quality gates.

### P3 — Primitive Store Is the Analytics Cache
When V2/V3 scoring engines already computed a primitive (e.g., Piotroski F-Score), retrieve it from `primitive_store` via `PrimitiveStoreClient`. Only recompute if the primitive is stale (`as_of_date < today - 1`). Never duplicate computation.

### P4 — Deterministic Analytics Layer
The analytics engines (technical, fundamental, MF, portfolio, risk, recommendation) are pure functions: `calculate_rsi(prices: list[float], period: int = 14) -> float`. They take validated inputs and return typed outputs. No side effects. No external calls. Fully unit-testable.

### P5 — Agent = Orchestrator, Not Calculator
Specialist agents (LangGraph nodes) orchestrate tool calls and synthesize responses. They do NOT perform calculations inline. All calculations happen in analytics engine tools that the agent invokes.

### P6 — Confidence Propagation
Every tool returns a `confidence` float. The agent combines tool confidences (weighted average or min — depending on context) into the final response confidence. Missing data → confidence ≤ 0.5. Single-tool answer → tool's confidence. Multi-tool → weighted product.

### P7 — Async All The Way Down
No blocking I/O anywhere in the call stack. Use `asyncio`, `httpx.AsyncClient`, `asyncpg`/SQLAlchemy async, `aioredis`. If wrapping a sync library (e.g., TA-Lib), use `asyncio.to_thread()`.

### P8 — Fail Fast at Boundaries
Validate ALL inputs at API boundaries using Pydantic. Internal function calls between services trust their inputs (no double validation). Fail early with clear error messages rather than proceeding with bad data.

### P9 — Idempotency for Pipeline Tasks
All NIDP pipeline tasks and analytics computation tasks must be idempotent. Use `INSERT ... ON CONFLICT DO UPDATE` or upsert patterns. Running a task twice must produce the same result.

### P10 — Compliance is Non-Negotiable
Every response path that could be interpreted as investment advice must pass through the `ComplianceFilter`. It checks: suitability vs user risk profile, mandatory disclaimers, regulatory warnings. There is no "bypass" flag.

---

## 2. LANGGRAPH AGENT FRAMEWORK RULES

### State Schema
Define typed state dicts using `TypedDict`. Never use raw dicts in graph state.

```python
from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
import operator

class CopilotState(TypedDict):
    messages: Annotated[list[BaseMessage], operator.add]
    user_id: str
    session_id: str
    portfolio_context: dict | None
    risk_profile: str | None
    tools_invoked: Annotated[list[str], operator.add]
    confidence: float
    agent_name: str
```

### Graph Construction
```python
from langgraph.graph import StateGraph, END

graph = StateGraph(CopilotState)
graph.add_node("intent_classifier", classify_intent)
graph.add_node("stock_analyst", stock_analyst_agent)
# ... add all specialist agents
graph.add_conditional_edges("intent_classifier", route_to_agent)
graph.set_entry_point("intent_classifier")
```

### Tool Binding
```python
from langchain_core.tools import tool

@tool
async def get_rsi(isin: str, period: int = 14) -> dict:
    """Calculate RSI for a stock. Returns current RSI value and signal."""
    prices = await nidp_client.get_ohlcv(isin, days=period * 3)
    rsi = technical_engine.calculate_rsi(prices.close, period)
    return {"isin": isin, "rsi": rsi, "signal": classify_rsi(rsi), "confidence": 0.95}

agent = agent_model.bind_tools([get_rsi, get_macd, get_fundamentals, ...])
```

### Checkpointing (Conversation Memory)
```python
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

checkpointer = AsyncPostgresSaver.from_conn_string(DATABASE_URL)
graph = compiled_graph.compile(checkpointer=checkpointer)
config = {"configurable": {"thread_id": session_id}}
```

---

## 3. LOGGING RULES

### Logger Setup (every module)
```python
import structlog
log = structlog.get_logger()
```

### Required Log Points
Every tool execution must log:
- **Entry**: `log.info("tool_start", tool=name, params=sanitized_params)`
- **Exit (success)**: `log.info("tool_success", tool=name, duration_ms=elapsed, confidence=result.confidence)`
- **Exit (failure)**: `log.error("tool_failure", tool=name, error=str(e), duration_ms=elapsed)`

Every agent invocation must log:
- **Start**: `log.info("agent_start", agent=name, session_id=sid, user_id=uid)`
- **Tool calls**: `log.info("agent_tool_call", agent=name, tool=tool_name, call_index=n)`
- **Completion**: `log.info("agent_complete", agent=name, confidence=conf, tools_count=n, duration_ms=elapsed)`

Every NIDP API call must log:
- `log.info("nidp_request", endpoint=url, method=method, params=params)`
- `log.info("nidp_response", status=status_code, records=count, duration_ms=elapsed)`

### What NOT to Log
- User PII (name, email, phone) — use `user_id` only
- Portfolio dollar amounts in logs — use `user_id` + `as_of_date`
- Full tool responses in production — log only metadata/counts

### Log Levels
- `DEBUG`: Calculation internals, intermediate values (dev only)
- `INFO`: Tool execution, agent transitions, API calls
- `WARNING`: Stale data (>2 days old), low confidence (<0.6), partial data
- `ERROR`: Tool failure, NIDP API error, validation failure
- `CRITICAL`: Hallucination guard triggered, compliance check failed

---

## 4. VALIDATION RULES

### Input Validation (Pydantic)
```python
from pydantic import BaseModel, field_validator, model_validator
from datetime import date

class StockAnalysisRequest(BaseModel):
    isin: str
    exchange: str = "NSE"
    as_of_date: date | None = None

    @field_validator("isin")
    @classmethod
    def validate_isin(cls, v: str) -> str:
        if not (len(v) == 12 and v[:2] == "IN"):
            raise ValueError(f"Invalid Indian ISIN: {v}")
        return v.upper()
```

### Analytics Input Validation
- Price series: must have ≥ `period * 2` data points before computing any indicator
- Financial ratios: validate denominator ≠ 0 before division; return `None` if undefined
- Dates: always use `date` objects, never raw strings; use `as_of_date` consistently
- ISINs: 12-char, starts with "IN" for Indian instruments
- Scheme codes: validate against AMFI scheme list

### Hallucination Guard Checks
Before including any number in agent response text:
1. Verify the number exists in `state["tool_results"]`
2. Verify `as_of_date` of data ≤ today (reject future dates)
3. Verify value is within plausible range (RSI: 0–100, PE: 0–10000, Returns: -100% to +10000%)
4. If check fails: replace with "data unavailable" and lower confidence to 0.0

### Suitability Validation (Compliance)
```python
def validate_suitability(recommendation: Recommendation, user_profile: RiskProfile) -> bool:
    if user_profile.risk_band == "conservative" and recommendation.risk_level == "high":
        return False
    if recommendation.asset_class == "EQUITY" and user_profile.equity_max_pct < recommendation.suggested_weight:
        return False
    return True
```

---

## 5. TESTING REQUIREMENTS

### Test Structure
```
tests/
  unit/
    analytics/          # Pure function tests — no mocks needed
    agents/             # Agent logic tests with mocked tools
    tools/              # Tool wrapper tests with mocked NIDP
  integration/
    nidp_client/        # Tests against NIDP test environment
    database/           # Tests against test PostgreSQL instance
    langgraph/          # Full graph execution tests
  e2e/
    chat_flows/         # Full user conversation scenarios
```

### Coverage Requirements
- Unit tests: ≥ 90% line coverage for analytics engines
- Integration tests: All tool paths (success + failure) covered
- E2E: Golden path for each of the 9 specialist agents

### Analytics Engine Test Pattern
```python
import pytest
from services.analytics.technical import calculate_rsi

def test_rsi_overbought():
    prices = [100.0] * 10 + [110.0] * 20   # Sustained uptrend
    rsi = calculate_rsi(prices, period=14)
    assert rsi > 70.0, f"Expected overbought RSI, got {rsi}"

def test_rsi_insufficient_data():
    with pytest.raises(InsufficientDataError):
        calculate_rsi([100.0] * 5, period=14)

def test_rsi_range():
    import random
    prices = [random.uniform(90, 110) for _ in range(100)]
    rsi = calculate_rsi(prices)
    assert 0.0 <= rsi <= 100.0
```

### Agent Test Pattern (mock tools)
```python
from unittest.mock import AsyncMock, patch
from agents.specialists.stock_analyst import stock_analyst_agent

@pytest.mark.asyncio
async def test_stock_analyst_uses_tools():
    state = {"messages": [HumanMessage("Analyze RELIANCE")], "user_id": "u1", ...}

    with patch("agents.specialists.stock_analyst.nidp_client") as mock_client:
        mock_client.get_ohlcv.return_value = AsyncMock(return_value=sample_ohlcv)
        result = await stock_analyst_agent(state)

    assert "tools_invoked" in result
    assert "get_rsi" in result["tools_invoked"]
    assert result["confidence"] > 0.0
    assert "disclaimer" in result["response_text"].lower()
```

### Fixture Requirements
- `pytest-asyncio` for all async tests
- `pytest-postgresql` for DB integration tests
- `respx` for mocking HTTPX calls in NIDP client tests
- Never mock the analytics functions themselves — they are pure and fast

---

## 6. SECURITY REQUIREMENTS

### Authentication & Authorization
- All chat API endpoints require valid JWT (existing auth middleware)
- User can only access their own portfolio data (`user_id` from JWT, not from request body)
- Admin endpoints require admin role claim in JWT
- No unauthenticated endpoints except `/health` and `/v1/auth/*`

### Data Isolation
- All database queries must filter by `user_id` (or derive `user_id` from JWT)
- No cross-user data leakage — always parameterized queries, never string formatting in SQL
- Portfolio data in Redis cache: key must include `user_id` in namespace

### Secret Management
- All secrets via environment variables
- Access secrets ONLY through `backend/helpers/secrets.py`
- Never log secret values
- Never commit `.env` files

### Input Sanitization
- All user chat input: strip and truncate to 2000 chars before passing to LLM
- All ISINs: uppercase and regex-validate before DB lookup
- All date inputs: parse with `date.fromisoformat()` and validate range (not future)
- SQL: always use parameterized queries via SQLAlchemy — never f-strings in SQL

### Rate Limiting
- Chat API: 60 requests/minute per user
- Analytics API: 120 requests/minute per user
- Implement via Redis sliding window in middleware

### Audit Trail (7-year retention)
Every agent response must create an `agent_audit_log` record:
```python
audit = AgentAuditLog(
    trace_id=uuid4(),
    session_id=session_id,
    message_id=message_id,
    agent_name=agent_name,
    tools_invoked=tools_list,
    duration_ms=elapsed,
    hallucination_flag=hallucination_detected,
    compliance_flag=compliance_triggered,
)
await db.add(audit)
```

---

## 7. DEFINITION OF DONE

A task is **DONE** when every item below is checked:

### Code Quality
- [ ] All acceptance criteria from TASK_REGISTRY implemented and verified
- [ ] `mypy --strict` passes with zero errors
- [ ] `ruff check` passes with zero warnings
- [ ] `ruff format` applied

### Testing
- [ ] Unit tests written covering all edge cases
- [ ] Unit test coverage ≥ 90% for the module
- [ ] Integration tests for all external calls (NIDP, DB, Redis)
- [ ] All tests pass: `pytest tests/ -x`

### Correctness
- [ ] No hardcoded financial values or magic numbers
- [ ] No bare `except:` clauses
- [ ] No `print()` statements — structlog only
- [ ] All I/O operations are async
- [ ] Pydantic validation on all external inputs

### Agent-Specific (if implementing an agent or tool)
- [ ] Tool returns `confidence` float in response
- [ ] Agent response includes `disclaimer` for financial content
- [ ] All tool invocations logged with `tool_start` / `tool_success` / `tool_failure`
- [ ] Hallucination guard checks applied before response generation
- [ ] Suitability check applied for any recommendation

### Database (if modifying schema)
- [ ] Alembic migration file created and tested (upgrade + downgrade)
- [ ] Indexes added for all filter/join columns
- [ ] No raw `CREATE TABLE` in application code
- [ ] Upsert pattern used for pipeline data

### API (if adding endpoints)
- [ ] FastAPI router with correct prefix
- [ ] Pydantic request/response models
- [ ] Auth middleware applied
- [ ] Rate limiting applied
- [ ] OpenAPI docs auto-generated correctly

### Documentation
- [ ] Module docstring explains purpose (one line)
- [ ] Complex algorithms have inline WHY comments (not WHAT)

---

## 8. STANDARD DISCLAIMER TEXT

Include verbatim in every agent response involving investment recommendations or analysis:

```
DISCLAIMER: This analysis is for informational purposes only and does not constitute 
investment advice. Past performance is not indicative of future results. Please consult 
a SEBI-registered investment advisor before making investment decisions. Mutual fund 
investments are subject to market risks.
```

---

## 9. PRIMITIVE STORE CONTRACT

When writing a new analytics engine that produces scoreable primitives:

```python
async def store_primitive(
    db: AsyncSession,
    as_of_date: date,
    asset_type: str,       # "EQUITY" | "MF" | "ETF"
    asset_id: str,         # ISIN or scheme_code
    primitive_name: str,   # e.g., "rsi_14d", "piotroski_f_score", "sharpe_3y"
    primitive_value: float,
    source_table: str,     # e.g., "nidp_ohlcv"
    calculation_version: str = "v1",
) -> None:
    stmt = pg_insert(PrimitiveStore).values(
        as_of_date=as_of_date,
        asset_type=asset_type,
        asset_id=asset_id,
        primitive_name=primitive_name,
        primitive_value=primitive_value,
        source_table=source_table,
        calculation_version=calculation_version,
    ).on_conflict_do_update(
        index_elements=["as_of_date", "asset_type", "asset_id", "primitive_name", "calculation_version"],
        set_={"primitive_value": primitive_value, "updated_at": func.now()},
    )
    await db.execute(stmt)
```
