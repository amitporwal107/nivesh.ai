# Functional Requirements Document — AI COPILOT V2
**Layer:** AI Copilot V2 (LangGraph Multi-Agent + NIDP-Grounded)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `routes/chat.py` (lines 23–36, 1015–1074), `routes/copilot_agents.py`, `services/copilot_tools/`, `backend/NIDP_COPILOT_INTEGRATION_PLAN.md`

---

## DOCUMENT NOTES — What "Copilot V2" Means

> **Copilot V2 = the LangGraph multi-agent path.** It activates when `USE_LANGGRAPH_AGENT=true` is set as an environment variable.
>
> V2 extends V1 (RAG-based) with:
> 1. **LangGraph graph orchestration** — multi-step agent reasoning vs single-turn RAG
> 2. **Copilot Tools** — 8 specialist tool modules (portfolio, recommendation, technical, fundamental, risk, mf, sip, daas_client) that can be called by the LangGraph agent
> 3. **NIDP Market Context** — planned integration to inject live market data (prices, macro, flows, events) into copilot responses
> 4. **Agent Registry** — 7 named agents (portfolio_analyst, risk_advisor, tax_advisor, etc.) + model picker
>
> **Current State (May 2026):** V2 path is feature-flagged (`USE_LANGGRAPH_AGENT`). The LangGraph graph import guard falls back to V1 RAG if LangGraph cannot be imported, so V2 is non-breaking.

---

## 1. Module: LangGraph Agent Graph

### FR-COP2-001 — LangGraph Route Activation
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-001 |
| **Module** | LangGraph Agent |
| **Feature** | Feature-Flagged Agent Path |
| **Priority** | High |
| **Source** | `routes/chat.py` lines 23–36 |
| **Status** | Feature-flagged — `USE_LANGGRAPH_AGENT=true` required |

**Activation:**
```python
_USE_LANGGRAPH = os.environ.get("USE_LANGGRAPH_AGENT", "").lower() in ("1", "true", "yes")
if _USE_LANGGRAPH:
    from nidp.services.copilot_agent.graph import get_graph as _get_copilot_graph
```

**Fallback Guard:** If `nidp.services.copilot_agent.graph` import fails (LangGraph not installed or NIDP service not available) → `_USE_LANGGRAPH` is set to False → V1 RAG path used transparently.

**Route Difference in `/api/chat/stream`:**
- V1 path: RAG orchestrator → LLM tokens streamed
- V2 path: `graph.astream_events()` → LangGraph event stream with `version="v2"` metadata

---

### FR-COP2-002 — LangGraph Agent Graph Architecture
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-002 |
| **Module** | LangGraph Agent |
| **Feature** | Multi-Step Reasoning Graph |
| **Priority** | High |
| **Source** | `nidp/services/copilot_agent/graph.py` (referenced in chat.py) |
| **Status** | Feature-flagged |

**Graph Design Principles:**
- Multi-agent orchestration: an orchestrator node routes to specialist tool nodes
- Each tool node executes a specific analysis (portfolio, technical, fundamental, etc.)
- Graph state preserves intermediate results across tool calls
- Final node synthesises all tool outputs into a narrative response

**Streaming:** Uses `astream_events()` with `version="v2"` — provides richer event types (on_chat_model_stream, on_tool_start, on_tool_end) for UI progress indicators.

---

## 2. Module: Agent Registry & Model Picker

### FR-COP2-003 — Agent Registry
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-003 |
| **Module** | Agent Registry |
| **Feature** | Named Agent List |
| **Priority** | Medium |
| **Source** | `routes/copilot_agents.py` |
| **Status** | Live |

**API:** `GET /api/copilot/agents`

**7 Registered Agents:**
| Agent ID | Name | Specialty |
|---|---|---|
| `auto` | Auto-Route | Default; intent router picks specialist |
| `portfolio_analyst` | Portfolio Analyst | Holdings analysis, scoring, overlap |
| `risk_advisor` | Risk Advisor | Risk profiling, allocation, stress testing |
| `tax_advisor` | Tax Advisor | Capital gains, LTCG/STCG, harvesting |
| `fund_researcher` | Fund Researcher | Fund comparison, expense ratios, manager |
| `goal_planner` | Goal Planner | SIP planning, Monte Carlo, goal tracking |
| `market_analyst` | Market Analyst | Macro regime, sector rotation, BTST |

**Intent Routing API:** `POST /api/copilot/agents/route` — deterministic intent router pre-computes which agent ribbon to render before the user finishes typing.

---

### FR-COP2-004 — Model Picker
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-004 |
| **Module** | Agent Registry |
| **Feature** | LLM Backend Selection |
| **Priority** | Low |
| **Source** | `routes/copilot_agents.py` |
| **Status** | Live |

**API:** `GET /api/copilot/models/picker`

**3 Supported Backends:**
| Model ID | Description | Default |
|---|---|---|
| `gpt-4o` | GPT-4o (full capability) | Yes |
| `gpt-4o-mini` | GPT-4o-mini (fast, cheaper) | No |
| `claude-3-5-sonnet` | Claude 3.5 Sonnet | No |

---

### FR-COP2-005 — Oneshot Agent Endpoint
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-005 |
| **Module** | Agent Registry |
| **Feature** | Single-Turn Specialist Call |
| **Priority** | Medium |
| **Source** | `routes/copilot_agents.py` |
| **Status** | Live |

**API:** `POST /api/copilot/agents/oneshot`

**Use Case:** Generates widget-level content (e.g., rationale text for a specific fund card) without a full chat session.

---

## 3. Module: Copilot Tools (Specialist Analysis Modules)

### FR-COP2-006 — Portfolio Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-006 |
| **Module** | Copilot Tools |
| **Feature** | Portfolio Computation Library |
| **Priority** | High |
| **Source** | `services/copilot_tools/portfolio.py` (24.4 KB) |
| **Status** | Live — used by oneshot and LangGraph agent |

**Capabilities (callable by agent):**
- XIRR computation on holdings (Extended Internal Rate of Return)
- Asset allocation analysis vs target
- Pairwise fund overlap computation
- Rebalancing suggestions (current vs target allocation)
- Tax-harvest candidate identification
- Stress test simulation (portfolio value at −20%, −30%, −40% market drop)

**Acceptance Criteria:**
- XIRR computed from holdings with valid buy_date and buy_price only
- Stress test returns: current_value, value_at_drop, loss_amount per scenario
- Tax harvest candidates filtered: unrealized LTCG ≤ ₹1.25L exemption AND holding > 1yr

---

### FR-COP2-007 — Recommendation Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-007 |
| **Module** | Copilot Tools |
| **Feature** | Composite Stock/Fund Scorer |
| **Priority** | High |
| **Source** | `services/copilot_tools/recommendation.py` (18.4 KB) |
| **Status** | Live |

**5-Dimension Composite Scorer:**
| Dimension | Weight | Source |
|---|---|---|
| Technical | 25% | RSI, MACD, SMA crossovers |
| Fundamental | 30% | ROE, debt/equity, EPS growth, Piotroski |
| Valuation | 15% | PE ratio, PB ratio vs sector median |
| Risk | 15% | Beta, ATR, max drawdown, Sharpe |
| Portfolio Fit | 15% | Overlap, gap-fill, AMC concentration |

**Output:** Overall score (0-100) + per-dimension breakdown + BUY/HOLD/AVOID verdict + explanation

---

### FR-COP2-008 — Fundamental Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-008 |
| **Module** | Copilot Tools |
| **Feature** | Equity Fundamental Checks |
| **Priority** | Medium |
| **Source** | `services/copilot_tools/fundamental.py` (12.1 KB) |
| **Status** | Live |

**Metrics Computed:**
- Piotroski F-Score (9-point financial health indicator)
- ROE (Return on Equity) vs sector median
- Debt/Equity ratio + trend
- Altman Z-Score (bankruptcy risk)

---

### FR-COP2-009 — Technical Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-009 |
| **Module** | Copilot Tools |
| **Feature** | Technical Signal Detection |
| **Priority** | Medium |
| **Source** | `services/copilot_tools/technical.py` (9.9 KB) |
| **Status** | Live |

**Signals:**
- RSI (14-period) — overbought/oversold
- MACD (12/26/9) — signal line crossover
- SMA price signals — above/below 50/200 SMA

---

### FR-COP2-010 — Risk Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-010 |
| **Module** | Copilot Tools |
| **Feature** | Portfolio Risk Metrics |
| **Priority** | High |
| **Source** | `services/copilot_tools/risk.py` (17.1 KB) |
| **Status** | Live |

**Metrics Computed:**
- Portfolio beta vs Nifty 50
- Average True Range (volatility)
- Maximum drawdown (portfolio-level)
- Sharpe ratio (portfolio-level)
- Sortino ratio (portfolio-level)
- Comparison vs user's risk profile target

---

### FR-COP2-011 — Mutual Fund Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-011 |
| **Module** | Copilot Tools |
| **Feature** | MF Category Screening |
| **Priority** | Medium |
| **Source** | `services/copilot_tools/mf.py` (11.0 KB) |
| **Status** | Live |

**Capabilities:**
- SEBI category screening by expense ratio, AUM, NAV trends
- Peer fund comparison within category
- Manager tenure check
- AUM trend analysis (growing/shrinking)

---

### FR-COP2-012 — SIP Analysis Tool
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-012 |
| **Module** | Copilot Tools |
| **Feature** | SIP Adequacy & Gap Detection |
| **Priority** | High |
| **Source** | `services/copilot_tools/sip.py` (11.4 KB) |
| **Status** | Live |

**Capabilities:**
- Required SIP computation: `FV = PMT × [((1+r)^n − 1) / r]` rearranged for PMT
- Current SIP detection from CAS transactions (recurring amount at consistent intervals)
- SIP adequacy: actual_sip vs required_sip per goal
- SIP gap alert: "Your retirement goal needs ₹45K/mo; you're investing ₹15K/mo"

---

### FR-COP2-013 — DaaS Client
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-013 |
| **Module** | Copilot Tools |
| **Feature** | NIDP Data API Client |
| **Priority** | Medium |
| **Source** | `services/copilot_tools/daas_client.py` (3.4 KB) |
| **Status** | Live — scaffolded |

**Description:** HTTP client wrapper for the NIDP Data-as-a-Service API. Provides access to NIDP market data (prices, macro, FII/DII flows, corporate events) for the LangGraph agent.

**Endpoints Wrapped:**
- `/v1/prices` — current and historical prices
- `/v1/macro` — macro indicators (VIX, yields, INR/USD, crude)
- `/v1/flows` — FII/DII net flows
- `/v1/events` — corporate events and announcements

---

## 4. Module: NIDP Copilot Integration (Planned Phase 2)

### FR-COP2-014 — NIDP Market Context Injection
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-014 |
| **Module** | NIDP Copilot |
| **Feature** | Live Market Data in Copilot |
| **Priority** | High |
| **Source** | `backend/NIDP_COPILOT_INTEGRATION_PLAN.md` |
| **Status** | PLANNED — not yet integrated |

**Objective:** Inject NIDP-sourced market intelligence into copilot responses without breaking existing `/api/chat/*` contracts.

**NIDP Context Block Schema (planned):**
```json
{
  "as_of": "2026-05-14T15:30:00+05:30",
  "market_regime": "CAUTIOUS",
  "symbols": [
    {
      "symbol": "NSEI",
      "close": 24165,
      "change_1d_pct": -0.66,
      "change_1w_pct": 1.2
    }
  ],
  "macro": {
    "vix": 17.12,
    "usd_inr": 83.45,
    "crude_brent": 82.3,
    "us_10y_yield": 4.35
  },
  "events": [
    {
      "symbol": "RELIANCE",
      "type": "earnings",
      "summary": "Q4 FY26 results announced"
    }
  ]
}
```

**Gating:** `NIDP_COPILOT_ENABLED` feature flag

**Caching:** Redis cache by `(user_id/symbols + date bucket)` — TTL 5–30 min. Budget: 700–1200ms timeout before fallback to V1 context.

**Integration Points (Phase 2):**
- `POST /api/chat/send`
- `POST /api/chat/stream`
- `POST /api/copilot/ask` (planned)
- `POST /api/copilot/explain` (planned)

---

### FR-COP2-015 — Market Context Builder
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP2-015 |
| **Module** | NIDP Copilot |
| **Feature** | Market-Aware Context Assembly |
| **Priority** | Medium |
| **Source** | `NIDP_COPILOT_INTEGRATION_PLAN.md` |
| **Status** | PLANNED |

**Transforms NIDP raw API into copilot-safe blocks:**
1. **Index Trend Block** — Nifty direction, % change, vs 20-DMA
2. **FII/DII Flows Block** — net buy/sell last 5 sessions
3. **Corporate Events Block** — relevant events for holdings the user owns
4. **Symbol Facts Block** — for any holding the user is asking about

**Prompt Injection Point:** Appended as `NIDP_CONTEXT` section to system prompt, after portfolio context and before user query.

---

## 5. Gap Analysis — Copilot V2 (Docs vs Code)

| Feature | Status | Notes |
|---|---|---|
| LangGraph graph implementation | **PARTIAL** — import exists, graph.py in NIDP module | Not confirmed functional without enabling flag + full NIDP deployment |
| NIDP market context injection | **PLANNED ONLY** | Design in NIDP_COPILOT_INTEGRATION_PLAN.md; code not yet wired |
| Agent ribbon UI (pre-render) | **LIVE** | `/api/copilot/agents/route` endpoint exists |
| Tool execution feedback (streaming) | **PLANNED** | `on_tool_start/on_tool_end` events in LangGraph stream not yet surfaced in frontend |
| Multi-model support (Claude) | **SCAFFOLDED** | Model picker returns Claude but routing not confirmed |
| Agent memory (cross-session) | **NOT IMPLEMENTED** | Each session is stateless; no persistent agent memory |

---

## 6. Requirement Traceability Matrix

| Req ID | Feature | Status | Source | API / Flag | Priority |
|---|---|---|---|---|---|
| FR-COP2-001 | LangGraph Activation | IMPLEMENTED | routes/chat.py | USE_LANGGRAPH_AGENT env | High |
| FR-COP2-002 | Graph Architecture | PARTIAL | nidp/services/copilot_agent/ | (internal) | High |
| FR-COP2-003 | Agent Registry | IMPLEMENTED | routes/copilot_agents.py | GET /api/copilot/agents | Medium |
| FR-COP2-004 | Model Picker | IMPLEMENTED | routes/copilot_agents.py | GET /api/copilot/models/picker | Low |
| FR-COP2-005 | Oneshot Agent | IMPLEMENTED | routes/copilot_agents.py | POST /api/copilot/agents/oneshot | Medium |
| FR-COP2-006 | Portfolio Tool | IMPLEMENTED | copilot_tools/portfolio.py | (internal tool) | High |
| FR-COP2-007 | Recommendation Tool | IMPLEMENTED | copilot_tools/recommendation.py | (internal tool) | High |
| FR-COP2-008 | Fundamental Tool | IMPLEMENTED | copilot_tools/fundamental.py | (internal tool) | Medium |
| FR-COP2-009 | Technical Tool | IMPLEMENTED | copilot_tools/technical.py | (internal tool) | Medium |
| FR-COP2-010 | Risk Tool | IMPLEMENTED | copilot_tools/risk.py | (internal tool) | High |
| FR-COP2-011 | MF Tool | IMPLEMENTED | copilot_tools/mf.py | (internal tool) | Medium |
| FR-COP2-012 | SIP Tool | IMPLEMENTED | copilot_tools/sip.py | (internal tool) | High |
| FR-COP2-013 | DaaS Client | IMPLEMENTED | copilot_tools/daas_client.py | (NIDP API client) | Medium |
| FR-COP2-014 | NIDP Context Injection | PLANNED | backend/NIDP_COPILOT_INTEGRATION_PLAN.md | NIDP_COPILOT_ENABLED flag | High |
| FR-COP2-015 | Market Context Builder | PLANNED | backend/NIDP_COPILOT_INTEGRATION_PLAN.md | (internal) | Medium |

---

*Document generated May 2026. V2 path activated by `USE_LANGGRAPH_AGENT=true`. Without flag, V1 RAG path (FRD_COPILOT_V1.md) is used.*
