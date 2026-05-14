# Functional Requirements Document — AI COPILOT V1
**Layer:** AI Copilot V1 (RAG-Based Conversational AI)
**Status:** VALIDATED AGAINST CODE — May 2026
**Validation Source:** `routes/chat.py` (lines 1–1151), `services/copilot_rag/__init__.py`, `services/copilot_rag/intent_router.py`, `services/copilot_rag/orchestrator.py`, `services/copilot_rag/retrievers.py`, `services/copilot_rag/chart_specs.py`

---

## DOCUMENT NOTES — What "Copilot V1" Means

> **Copilot V1 = the RAG (Retrieval-Augmented Generation) path.** This is the DEFAULT path used unless `USE_LANGGRAPH_AGENT=true` is set in environment.
>
> Architecture: `User query → Intent classifier (deterministic, keyword-based) → Targeted retriever → LLM completion (narrative only) → Response with optional chart JSON`
>
> Core guarantee: **No number ever comes from the LLM.** All figures are pre-computed by the analytics engine and injected as structured context. The LLM only writes prose around them.
>
> **Copilot V2 (LangGraph multi-agent)** is documented separately in `FRD_COPILOT_V2.md`.

---

## 1. Module: Chat Session Management

### FR-COP1-001 — Create Chat Session
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-001 |
| **Module** | Copilot Session |
| **Feature** | Session Creation |
| **Priority** | High |
| **Source** | `routes/chat.py` |
| **Status** | Live |

**API:** `POST /api/chat/sessions`

**Processing:**
- Creates session record in MongoDB `chat_sessions`
- Returns `session_id`, `created_at`, empty `messages[]`

**Business Rules:**
- One user can have multiple concurrent chat sessions
- Sessions are independent (no cross-session context bleed)
- Sessions persist in MongoDB `chat_messages` (multi-turn conversation history)

---

### FR-COP1-002 — List & Delete Sessions
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-002 |
| **Module** | Copilot Session |
| **Feature** | Session Lifecycle |
| **Priority** | Medium |
| **Source** | `routes/chat.py` |
| **Status** | Live |

**APIs:**
- `GET /api/chat/sessions` — list recent sessions (sorted by updated_at)
- `DELETE /api/chat/sessions/{id}` — delete session + all its messages
- `GET /api/chat/messages?session_id={id}` — fetch full message history
- `DELETE /api/chat/clear` — clear all sessions or single session

---

### FR-COP1-003 — Context Warmup (Pre-loading)
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-003 |
| **Module** | Copilot Session |
| **Feature** | Portfolio Context Pre-Cache |
| **Priority** | High |
| **Source** | `routes/chat.py` — `POST /api/chat/warmup` |
| **Status** | Live |

**Description:** Fire-and-forget endpoint that pre-computes and caches the expensive portfolio context so the first chat message responds in <1 second.

**Rate Limiting:** Exempt from rate limiting (idempotent; calling it repeatedly has no side effect)

**Processing (parallel):**
1. Compute portfolio intelligence (overlap, concentration, compression_score)
2. Compute goals context (goals + actual vs planned SIP gap)
3. Compute health context (portfolio health scorecard + risk drivers)
4. Compute snapshot context (income/expenses/savings rate/corpus/liabilities)
5. Store in Redis with 300-second (5-min) TTL keyed by `user_id`

**Acceptance Criteria:**
- `POST /chat/warmup` → 200 immediately (does not wait for computation)
- First chat message after warmup → responds in < 1 second
- Warmup called twice rapidly → second call is no-op (Redis cache hit)

---

## 2. Module: Intent Classification (Deterministic)

### FR-COP1-004 — Keyword-Based Intent Router
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-004 |
| **Module** | Intent Routing |
| **Feature** | Query Classification |
| **Priority** | Critical |
| **Source** | `services/copilot_rag/intent_router.py` |
| **Status** | Live |

**Description:** Classifies user query into one of 8 intent types using deterministic keyword matching. NO LLM used for classification. Latency target: < 1ms.

**Intent Types:**
| Intent | Trigger Keywords | Retriever Called |
|---|---|---|
| `ranking` | top, best, worst, rank, compare, performance | `get_ranking_payload()` |
| `concentration` | concentration, overexposed, AMC, sector, overlap | `get_concentration_payload()` |
| `overlap` | overlap, duplicate, same stocks, correlation | `get_overlap_payload()` |
| `tax` | tax, LTCG, STCG, capital gains, harvest | `get_tax_payload()` |
| `goals` | goal, retirement, education, on track, SIP gap | `get_goals_payload()` |
| `health` | health, score, grade, risk, quality | `get_health_payload()` |
| `drift` | rebalance, drift, allocation, target | `get_drift_payload()` |
| `generic` | (all other queries) | `get_generic_payload()` |

**Slot-Filling (extracted from query):**
- `metric` — return / profit / loss / value
- `n` — top-N (extracts numeric from "top 5 holdings")
- `grouping` — sector / amc / category
- `chart_requested` — True if query implies a chart ("show me", "visualise", "chart")

**Acceptance Criteria:**
- "Show me my top 5 holdings by value" → intent=ranking, n=5, metric=value, chart_requested=True
- "What's my tax exposure if I sell HDFC Small Cap?" → intent=tax
- "Am I on track for retirement?" → intent=goals
- Same query always produces same intent (deterministic)

---

## 3. Module: Context Retrieval

### FR-COP1-005 — Portfolio Context Block
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-005 |
| **Module** | Context Retrieval |
| **Feature** | Holdings Context Assembly |
| **Priority** | Critical |
| **Source** | `routes/chat.py` — `_render_portfolio_block()` |
| **Status** | Live |

**What It Builds:**
- Holdings table: fund name, type, value, P&L, buy_date, sector
- Pre-sorted rankings: by value, by return, by P&L
- Sector breakdown: % of portfolio per sector
- AMC breakdown: % of portfolio per AMC

**Safety Rule:** Holdings with `buy_price = 0` (unknown cost basis) excluded from return rankings. Returns explicit `_EMPTY_HOLDINGS_BLOCK` string when user has no holdings — LLM cannot confabulate an empty portfolio.

**Monetary Values as Strings:** All amounts formatted as `"₹1,23,456"` strings before LLM injection. This prevents LLM arithmetic on raw numbers.

---

### FR-COP1-006 — Portfolio Intelligence Context
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-006 |
| **Module** | Context Retrieval |
| **Feature** | Stock-Level Look-Through Context |
| **Priority** | High |
| **Source** | `routes/chat.py` — `_compute_portfolio_intelligence_context()` |
| **Status** | Live |

**Context Built:**
- Compression score + effective unique stock count
- Top-10 stocks by combined weight across all funds
- Top-20 stock exposures
- Fund overlap pairs with shared company names
- Category inefficiency warnings ("3 large-cap funds hold 73% identical stocks")
- AMC concentration bucketing
- Sector exposure + redundancy suggestions

**Redis Cache:** 300-second TTL (populated by `/chat/warmup`)

---

### FR-COP1-007 — Active Plan Context
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-007 |
| **Module** | Context Retrieval |
| **Feature** | Action Plan Summary for Chat |
| **Priority** | High |
| **Source** | `routes/chat.py` — `_active_plan_context()` |
| **Status** | Live |

**Context Built:**
- Current active plan: status, creation date
- Pending/completed/skipped action counts
- Total tax impact of all pending exits
- Top 3 pending actions (type, fund, reason)

**Business Rule:** When user asks actionable questions (sell, switch, rebalance, etc.) AND there is no active plan → auto-generates a preview plan via `ActionPlanManager.generate_plan()`. Sets status to 'active' so chat context can cite real actions in the same response.

---

### FR-COP1-008 — Goals Context
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-008 |
| **Module** | Context Retrieval |
| **Feature** | Goals Status for Chat |
| **Priority** | High |
| **Source** | `routes/chat.py` — `_compute_goals_context()` |
| **Status** | Live |

**Context Built:**
- All goals: name, type, target_amount, horizon, on_track_pct
- Actual vs planned SIP gap per goal (6-month lookback from CAS transactions)
- Examples: "Goal: Retirement 2040 ₹2Cr — On track: 62% — Actual SIP ₹15K vs planned ₹50K (BELOW)"

---

### FR-COP1-009 — Health & Snapshot Context
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-009 |
| **Module** | Context Retrieval |
| **Feature** | Health Score + Financial Snapshot |
| **Priority** | Medium |
| **Source** | `routes/chat.py` — `_compute_health_context()`, `_compute_snapshot_context()` |
| **Status** | Live |

**Health Context:** Portfolio health score (0-100) + grade + top 3 risk drivers + component scores

**Snapshot Context:** Monthly income, monthly expenses, savings rate, total corpus, total liabilities. Only included if user has completed the financial snapshot wizard.

---

## 4. Module: RAG Orchestrator

### FR-COP1-010 — RAG Orchestration Pipeline
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-010 |
| **Module** | Copilot RAG |
| **Feature** | Retrieval + LLM Pipeline |
| **Priority** | Critical |
| **Source** | `services/copilot_rag/orchestrator.py` |
| **Status** | Live |

**Pipeline Steps:**
1. `intent_router.classify(user_query)` → intent + slots
2. Retrieve payload from appropriate retriever (targeted SQL/Mongo queries)
3. `chart_specs.generate(intent, payload)` → deterministic chart JSON (if chart_requested)
4. Format payload as bullet list for LLM (`_format_rows_for_llm()`)
5. Construct system prompt (~150 tokens, grounding instructions)
6. `LLM.complete(system_prompt + payload + history + user_query)` → prose
7. Validate any chart specs inline (server-side schema check)
8. Return: `{answer: str, chart_spec: dict|null, intent: str}`

**System Prompt Rules (enforced in prompt, not in code):**
- Use ONLY the numbers in the payload — do NOT recalculate
- Maximum 80 words in response
- Do NOT invent fund names, stock names, or financial figures
- Do NOT provide legal/tax advice — state figures only
- If data is insufficient → say so explicitly

**LLM Used:** GPT-4o-mini via Emergent LLM key (`EMERGENT_LLM_KEY`)

**Acceptance Criteria:**
- Response cites only figures from retrieval payload, no invented numbers
- Response ≤ 80 words (unless chart JSON appended)
- LLM failure → graceful fallback message, not 500 error
- Advisor mode → uses `_ADVISOR_CHAT_SYSTEM` prompt with cross-client book context

---

### FR-COP1-011 — Chart Spec Generation (Server-Side)
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-011 |
| **Module** | Copilot RAG |
| **Feature** | Deterministic Chart JSON |
| **Priority** | High |
| **Source** | `services/copilot_rag/chart_specs.py` |
| **Status** | Live |

**Chart Types Supported (4-type schema):**
| Type | When Used |
|---|---|
| `bar` | Holdings by value, performance comparisons |
| `pie` | Asset allocation, AMC/sector breakdown |
| `line` | NAV history, portfolio value over time |
| `table` | Fund comparison, overlap matrix |

**Architecture:** Chart specs are always generated server-side from retrieval payload. LLM is NEVER asked to generate a chart spec — only to write prose. Chart JSON is validated server-side against the 4-type schema before being sent to frontend.

**Acceptance Criteria:**
- Query "Show me my allocation by sector" → chart_spec.type = "pie" with correct sector data
- Chart spec validation fails → response sent without chart, not error
- Chart spec content matches retrieval payload values (never LLM-invented values)

---

## 5. Module: Chat Endpoints

### FR-COP1-012 — Synchronous Chat Send
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-012 |
| **Module** | Copilot |
| **Feature** | Single-Turn Chat Response |
| **Priority** | High |
| **Source** | `routes/chat.py` — `POST /api/chat/send` |
| **Status** | Live |

**API:** `POST /api/chat/send`

**Input:**
```json
{
  "message": "string (1–4000 chars)",
  "session_id": "string (optional)"
}
```

**Routing Logic:**
- Investor mode (default): RAG orchestrator path
- Advisor mode (workspace = ADVISORY): uses advisor system prompt with book-level context

**Processing:**
1. Validate message length (1–4000 chars)
2. Check session (create new if session_id absent)
3. Load/warm context (from Redis or recompute)
4. Route through RAG orchestrator
5. Check if auto-plan should be generated (actionable keywords detected)
6. Save user message + assistant response to `chat_messages`
7. Return complete response

**Rate Limit:** 200 req/min

---

### FR-COP1-013 — Streaming Chat (SSE)
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-013 |
| **Module** | Copilot |
| **Feature** | Token-by-Token Streaming |
| **Priority** | High |
| **Source** | `routes/chat.py` — `POST /api/chat/stream` |
| **Status** | Live |

**API:** `POST /api/chat/stream`

**Response Format:** Server-Sent Events (SSE). Each event carries a prose chunk (~24 chars for smooth animation).

**V1 Path (default — `_USE_LANGGRAPH = False`):**
1. Load full context (portfolio + plan + goals + health)
2. Build RAG payload per intent
3. Stream LLM tokens via SSE
4. Save complete response + inject metadata on stream completion

**Rate Limit:** 30 req/min (SSE streams are long-lived connections)

---

### FR-COP1-014 — RAG-Only Endpoint
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-014 |
| **Module** | Copilot |
| **Feature** | Direct RAG (Bypasses History) |
| **Priority** | Low |
| **Source** | `routes/chat.py` — `POST /chat/rag` |
| **Status** | Live |

For direct RAG access without conversation history overhead. Used internally for plan-explanation queries.

---

## 6. Module: Copilot Frontend (V1 UI)

### FR-COP1-015 — Copilot Drawer
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-015 |
| **Module** | Copilot UI |
| **Feature** | Sliding Copilot Panel |
| **Priority** | Critical |
| **Source** | `src/components/NiveshCopilotDrawer.jsx` |
| **Status** | Live |

**Triggered By:** Floating button (bottom-right of every page)

**Features:**
- Slides in from right edge
- Resizable via grip handle (drag left/right)
- Maximize to full-screen mode
- Portfolio context warming on open (`POST /api/chat/warmup`)
- Session management: create new / select existing
- Message list with user/assistant bubbles
- Loading skeleton while streaming
- Auto-scroll to latest message

**Interaction:**
- Close: X button, backdrop click, or Escape key
- Keyboard: Enter to send, Shift+Enter for newline

---

### FR-COP1-016 — Chat View
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-016 |
| **Module** | Copilot UI |
| **Feature** | Conversation Interface |
| **Priority** | Critical |
| **Source** | `src/components/ChatView.js` |
| **Status** | Live |

**Features:**
- Multi-turn conversation display
- Streaming animation (token-by-token reveal)
- Inline chart rendering (bar/pie/line/table from chart_spec JSON)
- Source citations shown as chips (e.g., "based on your HDFC Small Cap holding")
- Suggested follow-up questions (generated by LLM + validated)
- Copy response button

---

### FR-COP1-017 — Scenario Engine (AICopilotView)
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-017 |
| **Module** | Copilot UI |
| **Feature** | Pre-built Scenario Cards |
| **Priority** | High |
| **Source** | `src/components/copilot/AICopilotView.jsx` |
| **Status** | Live |

**Pre-Built Scenario Types:**
- Compare tables (fund vs fund)
- Fund card recommendations
- Market brief
- Overlap reveal (for a specific fund pair)
- Rebalance plan
- Sector rotation summary
- SIP planning (required SIP for a goal)
- Stress test (what if market drops 20%)
- Tax harvesting opportunities

**Interaction:**
- Scenario cards shown before user types anything
- Click "Simulate" → `POST /api/scenarios/{id}/simulate`
- Result shown in `SimulationPanel`
- SaveAsPlanCard appears at bottom (V2 bridge — see FR-FE-V2-015)

---

## 7. Module: LLM Safety

### FR-COP1-018 — Prompt Safety Screening
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-018 |
| **Module** | Security |
| **Feature** | PII Scrubbing Before LLM |
| **Priority** | Critical |
| **Source** | `services/llm_safety.py` |
| **Status** | Live |

**Screens for (before LLM injection):**
- PAN patterns: `[A-Z]{5}[0-9]{4}[A-Z]`
- Bank account patterns: 9–18 digit numbers
- Aadhaar patterns: 12-digit numbers

**Action:** Replaces detected patterns with `[REDACTED]` before prompt is sent to OpenAI.

**Acceptance Criteria:**
- User message containing "My PAN is ABCDE1234F" → PAN redacted before LLM call
- Financial analysis still works (numbers retained, only PII-pattern numbers redacted)

---

## 8. Module: Goal-Level Copilot

### FR-COP1-019 — Per-Goal AI Advisor
| Field | Value |
|---|---|
| **Requirement ID** | FR-COP1-019 |
| **Module** | Goals Copilot |
| **Feature** | Goal-Specific Chat |
| **Priority** | High |
| **Source** | `routes/goals.py`, `services/goal_copilot.py` |
| **Status** | Live |

**APIs:**
- `POST /api/goals/{goal_id}/copilot` — natural-language what-if (LLM-powered)
- `GET /api/goals/{goal_id}/copilot/history` — load conversation history
- `DELETE /api/goals/{goal_id}/copilot/history` — clear chat

**Context:** Goal definition + current on_track_pct + actual vs planned SIP + fund allocations

**Example Queries Handled:**
- "Am I on track for retirement by 2040?"
- "What if I increase my SIP by ₹10,000/month?"
- "Which fund is dragging down my retirement goal?"

---

## 9. Gap Analysis — Copilot V1 (Docs vs Code)

| Documented Feature | Code Status | Notes |
|---|---|---|
| Public Copilot route (logged-out users) | **NOT IMPLEMENTED** | Roadmap item; all copilot routes require auth |
| Voice copilot | **NOT IMPLEMENTED** | Phase 3 roadmap |
| WhatsApp CAS import trigger from copilot | **NOT IMPLEMENTED** | Phase 3 roadmap |
| Hindi language support in copilot | **NOT CONFIRMED** | System prompt is in English; no language detection |
| Chart type: candlestick | **NOT SUPPORTED** | Only bar/pie/line/table in chart_specs.py |

---

## 10. Requirement Traceability Matrix

| Req ID | Feature | Status | Source File | API Endpoint | Priority |
|---|---|---|---|---|---|
| FR-COP1-001 | Create Session | IMPLEMENTED | routes/chat.py | POST /api/chat/sessions | High |
| FR-COP1-002 | List/Delete Sessions | IMPLEMENTED | routes/chat.py | GET/DELETE /api/chat/sessions | Medium |
| FR-COP1-003 | Context Warmup | IMPLEMENTED | routes/chat.py | POST /api/chat/warmup | High |
| FR-COP1-004 | Intent Router | IMPLEMENTED | copilot_rag/intent_router.py | (internal) | Critical |
| FR-COP1-005 | Portfolio Context | IMPLEMENTED | routes/chat.py | (internal) | Critical |
| FR-COP1-006 | Intelligence Context | IMPLEMENTED | routes/chat.py | (internal) | High |
| FR-COP1-007 | Plan Context | IMPLEMENTED | routes/chat.py | (internal) | High |
| FR-COP1-008 | Goals Context | IMPLEMENTED | routes/chat.py | (internal) | High |
| FR-COP1-009 | Health/Snapshot | IMPLEMENTED | routes/chat.py | (internal) | Medium |
| FR-COP1-010 | RAG Orchestrator | IMPLEMENTED | copilot_rag/orchestrator.py | (internal) | Critical |
| FR-COP1-011 | Chart Specs | IMPLEMENTED | copilot_rag/chart_specs.py | (internal) | High |
| FR-COP1-012 | Sync Chat | IMPLEMENTED | routes/chat.py | POST /api/chat/send | High |
| FR-COP1-013 | Streaming Chat | IMPLEMENTED | routes/chat.py | POST /api/chat/stream | High |
| FR-COP1-014 | RAG-only | IMPLEMENTED | routes/chat.py | POST /chat/rag | Low |
| FR-COP1-015 | Copilot Drawer | IMPLEMENTED | NiveshCopilotDrawer.jsx | — | Critical |
| FR-COP1-016 | Chat View | IMPLEMENTED | ChatView.js | — | Critical |
| FR-COP1-017 | Scenario Engine | IMPLEMENTED | copilot/AICopilotView.jsx | POST /api/scenarios/{id}/simulate | High |
| FR-COP1-018 | LLM Safety | IMPLEMENTED | services/llm_safety.py | (middleware) | Critical |
| FR-COP1-019 | Goal Copilot | IMPLEMENTED | routes/goals.py | POST /api/goals/{id}/copilot | High |

---

*Document generated May 2026. Validated against commit on branch `nivesh-v2-copilot`. Default path when `USE_LANGGRAPH_AGENT` is not set.*
