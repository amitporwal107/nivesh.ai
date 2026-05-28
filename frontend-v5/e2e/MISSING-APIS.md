# Missing Backend APIs — Frontend Endpoints with No Backend

> Generated 2026-05-28 by testing all 87 frontend adapter endpoints against live staging  
> Updated 2026-05-28 — corrected statuses after deeper investigation

## Category 1: Truly Missing (404) — Backend route doesn't exist

| # | Method | Endpoint | Frontend adapter | Screen that needs it | Priority | Status |
|---|--------|----------|-----------------|---------------------|----------|--------|
| ~~A1~~ | ~~POST~~ | ~~`/api/chat`~~ | ~~`chat.adapter.ts → send()`~~ | ~~Chat copilot~~ | ~~P1~~ | **FIXED** — real endpoint is `POST /api/chat/send` |
| A2 | GET | `/api/portfolio/upload-latest-task` | `cas-upload.adapter.ts → latestTask()` | Onboarding — resume upload status | P2 | **Still 404** |
| A3 | GET | `/api/portfolio/upload-status/{taskId}` | `cas-upload.adapter.ts → status()` | Onboarding — poll upload progress | P2 | **Still 404** |
| ~~A4~~ | ~~POST~~ | ~~`/api/mfd/profiles/deactivate`~~ | ~~`mfd.adapter.ts → deactivateProfile()`~~ | ~~Advisor~~ | ~~P3~~ | **NOT MISSING** — returns 200, was incorrectly listed |
| A5 | POST | `/api/plans/refresh-fundamentals` | `plans.adapter.ts → refreshFundamentals()` | Plan board — refresh scoring data | P3 | **500** (route exists, backend error) |
| A6 | GET | `/api/intelligence/v3-score/{id}` | `intelligence.adapter.ts → v3Score()` | Fund Details — V3 breakdown | P2 | **500** (route exists, pipeline data issue) |
| A7 | GET | `/api/intelligence/sector-peers/{symbol}` | `intelligence.adapter.ts → sectorPeers()` | Fund Details — peer comparison | P3 | **Still 404** |

## Category 2: Wrong Method (405) — Route exists but frontend calls wrong HTTP method

| # | Frontend calls | Backend expects | Endpoint | Fix |
|---|---------------|----------------|----------|-----|
| B1 | GET | POST | `/api/auth/logout` | Frontend uses POST ✅ (GET test was just probe) |
| B2 | GET | POST | `/api/signals/generate` | Frontend adapter uses GET, backend expects POST |
| B3 | GET | PUT | `/api/goals/snapshot` (PUT for write) | Frontend uses PUT for write, GET for read — both exist |

## Category 3: Exists but not wired in frontend — Backend has it, frontend stubs

| # | Endpoint | Backend status | Frontend status | Notes |
|---|----------|---------------|----------------|-------|
| C1 | `GET /api/dashboards/risk` | ✅ 200 | Returns zeroed stub data | Backend has risk dashboard but frontend doesn't render it |
| C2 | `GET /api/dashboards/diversification` | ✅ 200 | Returns empty stub for correlation | Backend has diversification dashboard but frontend stubs correlation |
| C3 | `GET /api/dashboards/concentration` | ✅ 200 (via `/api/dashboards/{domain}`) | Frontend uses direct `/api/portfolio/exposure/concentration` instead | Two sources of truth — pick one |

## Category 4: Frontend has adapters, no page wired yet

| # | Adapter | Endpoints | Screen needed | Notes |
|---|---------|-----------|---------------|-------|
| D1 | `scenarios.adapter.ts` | 10 endpoints (`suggest`, `simulate`, `rebalance-plan`, `save`, `saved`, `apply`, `pending`, `complete`) | Portfolio Builder (prototype screen 12) | All backend endpoints exist ✅ |
| D2 | `advisor.adapter.ts` | 7 endpoints (`today`, `aum`, `underperformers`, `rebalance`, `summary`, `sip-board`, `sip-board/summary`) | Advisor screens (prototype Book/360/SIP) | All backend endpoints exist ✅ |
| D3 | `mfd.adapter.ts` | 15 endpoints (`workspace`, `profiles`, `notes`, `tax-summary`, `portfolio-trend`, `needs-attention`, `call-log`, `sip-nudge`, `review-pack`) | MFD workspace | All backend endpoints exist ✅ |
| D4 | `intelligence.adapter.ts` | `simulate`, `v3-score/{id}`, `sector-peers/{symbol}` | Fund Details, What-if simulation | Simulate exists ✅, v3-score 404 ❌ |
| D5 | `goals.adapter.ts` | `{goalId}/simulate`, `{goalId}/what-if`, `fund-shortlist/{bucket}`, `{goalId}/copilot` | Goals deep-dive, Monte Carlo | Need to verify per-goal endpoints |
| D6 | `plans.adapter.ts` | `{planId}/simulate`, `{planId}/save`, `history`, `active/health-projection` | Plan board expanded | health-projection exists ✅, history exists ✅ |

## Category 5: Chat — critical gap

The chat system has a fundamental gap:

| Component | Endpoint | Status | Notes |
|-----------|----------|--------|-------|
| Suggested prompts | `GET /api/copilot/suggested-prompts` | ✅ Works | Returns persona-tagged prompts |
| Session list | `GET /api/chat/sessions` | ✅ Works | Returns session array |
| Session create | `POST /api/chat/sessions` | ✅ Works | Creates new session |
| Session get | `GET /api/chat/sessions/{id}` | ✅ Works | Returns messages |
| Session delete | `DELETE /api/chat/sessions/{id}` | Not tested | Probably works |
| **Send message** | **`POST /api/chat`** | **❌ 404** | **Critical — can't send messages!** |

The frontend `chat.adapter.ts` calls `POST /api/chat` with `{message, session_id}`, but the backend returns 404. The actual backend chat endpoint may be at a different path (e.g. `/api/copilot/chat` or `/api/chat/sessions/{id}/messages`).

## Proposed API Contracts for Missing Endpoints

### A1: `POST /api/chat` (or wherever the send endpoint lives)

```yaml
# chat-send.yaml
POST /api/chat:
  requestBody:
    application/json:
      schema:
        type: object
        required: [message, session_id]
        properties:
          message: { type: string }
          session_id: { type: string }
  responses:
    200:
      schema:
        type: object
        properties:
          reply: { type: string }
          session_id: { type: string }
          message:
            type: object
            properties:
              role: { type: string, enum: [assistant] }
              content: { type: string }
```

### A2/A3: Upload status tracking

```yaml
# upload-status.yaml
GET /api/portfolio/upload-status/{taskId}:
  parameters:
    - name: taskId
      in: path
      required: true
      schema: { type: string }
  responses:
    200:
      schema:
        type: object
        properties:
          task_id: { type: string }
          status: { type: string, enum: [QUEUED, PARSING, COMPLETED, FAILED] }
          progress_pct: { type: integer }
          count: { type: integer, nullable: true }
          message: { type: string, nullable: true }
          parser_source: { type: string, nullable: true }

GET /api/portfolio/upload-latest-task:
  responses:
    200:
      schema:
        type: object
        nullable: true
        properties:
          task_id: { type: string }
          status: { type: string }
```

### A6: V3 Score per instrument

```yaml
# v3-score.yaml
GET /api/intelligence/v3-score/{instrumentId}:
  parameters:
    - name: instrumentId
      in: path
      required: true
      schema: { type: string }
    - name: refresh
      in: query
      schema: { type: boolean, default: false }
  responses:
    200:
      schema:
        type: object
        properties:
          instrument_id: { type: string }
          name: { type: string }
          v3_score: { type: number }
          coverage_pct: { type: number }
          grade: { type: string, enum: [A, B, C, D, F] }
          composites:
            type: object
            properties:
              returns: { $ref: '#/CompositeScore' }
              risk: { $ref: '#/CompositeScore' }
              cost: { $ref: '#/CompositeScore' }
              consistency: { $ref: '#/CompositeScore' }
              portfolio_fit: { $ref: '#/CompositeScore' }
              esg_proxy: { $ref: '#/CompositeScore' }
    404:
      description: Instrument not found in NIDP

CompositeScore:
  type: object
  properties:
    score: { type: number }
    primitives: { type: object }
```

### B2: Signals generate — method fix

```yaml
# Frontend calls GET, backend expects POST
# Fix: change frontend adapter from GET to POST
# Or: backend should accept GET for idempotent generation
GET /api/signals/generate:  # add GET support
  responses:
    200:
      schema:
        type: object
        properties:
          signals:
            type: array
            items:
              type: object
              properties:
                type: { type: string }
                priority: { type: integer }
                message: { type: string }
                holding_name: { type: string }
                health_score_impact: { type: number }
```

## Advisor API Contract Mismatches (all endpoints return 200, but shapes differ from advisor.yaml)

See `BUG-TRIAGE.md > Advisor/MFD API Contract Gaps` for full detail. Summary:

| Endpoint | YAML field | Real field |
|----------|-----------|-----------|
| `/api/mfd/workspace` | `mode` | `type` |
| `/api/mfd/profiles` | `total` | `count` |
| `/api/advisor/today` | `high_priority[]` | `rows[]` (flat, not pre-bucketed) |
| `/api/advisor/aum` | `clients[]` + `mom_change_pct` | `rows[]` + `aggregate_mom_pct` |
| `/api/advisor/underperformers` | `underperformers[]` + `benchmark_xirr_pct` | `rows[]` + `benchmark_return_pct` |
| `/api/advisor/rebalance` | `threshold_pp` + `clients[]` | `gap_threshold_pp` + `rows[]` |

## Summary

| Category | Count | Action |
|----------|-------|--------|
| **404 Missing** | 3 (A2, A3, A7) | Build backend endpoints |
| **500 Backend error** | 2 (A5, A6) | Backend pipeline fix |
| **Wrong path (fixed)** | 1 (A1 chat) | ✅ Fixed in `chat.adapter.ts` |
| **405 Wrong method** | 1 real (signals/generate) | Fix frontend adapter method |
| **Backend exists, frontend stubs** | 3 | Wire real data into pages |
| **Advisor contract gaps** | 7 mismatches | Fix contracts + adapters when advisor pages built |
| **Adapter exists, no page** | 6 groups (~32 endpoints) | Build pages or defer |

**Total: 87 frontend endpoints, 49 verified working, 3 truly missing (404), 2 backend-broken (500), 33 unwired/deferred**
