# Missing Backend APIs — Deep Investigation

> Generated 2026-05-28 by searching the full backend codebase for each reported 404/405 endpoint.

## Executive Summary

Of the 7 endpoints reported as missing, **6 already exist in the backend** at paths that match what the frontend calls. The real problem is almost entirely **path mismatches in the frontend adapter** (A1) and **HTTP method mismatches** (B2). Only A6 has a genuine access-gate issue (admin-only). Here is the full breakdown:

| # | Endpoint | Verdict | Root Cause |
|---|----------|---------|------------|
| A1 | `POST /api/chat` | **Frontend path wrong** | Backend has `POST /api/chat/send` and `POST /api/chat/stream`. No `POST /api/chat`. |
| A2 | `GET /api/portfolio/upload-latest-task` | **EXISTS** | Backend: `GET /api/portfolio/upload-latest-task` in `routes/upload.py:284` |
| A3 | `GET /api/portfolio/upload-status/{taskId}` | **EXISTS** | Backend: `GET /api/portfolio/upload-status/{task_id}` in `routes/upload.py:218` |
| A5 | `POST /api/plans/refresh-fundamentals` | **EXISTS** | Backend: `POST /api/plans/refresh-fundamentals` in `routes/plans.py:525` |
| A6 | `GET /api/intelligence/v3-score/{instrumentId}` | **EXISTS but admin-only** | Backend: `GET /api/intelligence/v3-score/{instrument_id}` in `routes/intelligence.py:202`. Calls `require_admin(request)` so regular users get 403/401, not 404. |
| A7 | `GET /api/intelligence/sector-peers/{symbol}` | **EXISTS** | Backend: `GET /api/intelligence/sector-peers/{symbol}` in `routes/intelligence.py:277` |
| B2 | `GET /api/signals/generate` | **Method mismatch** | Backend has `GET /api/signals/generate` (routes/plans.py:434). Frontend adapter calls with GET. Backend decorator is `@router.get`. This should work. Re-check staging deployment. |

---

## Detailed Investigation per Endpoint

### A1: POST /api/chat — FRONTEND PATH WRONG

**Frontend calls:** `POST /api/chat` with `{message, session_id}`
**File:** `/app/frontend-v5/src/services/adapters/chat.adapter.ts:41`

**Backend reality:** There is NO route at `POST /api/chat`. The backend has TWO send endpoints:

| Backend Route | File | Line | Description |
|---------------|------|------|-------------|
| `POST /api/chat/send` | `routes/chat.py` | 787 | Non-streaming JSON response. Accepts `ChatMessageInput` with `message` and `session_id` fields. Returns `{user_message, ai_message}`. |
| `POST /api/chat/stream` | `routes/chat.py` | 980 | SSE streaming response. Same request body shape (parsed from `request.json()`). Returns `text/event-stream` with token/meta/widget/done events. |

**Response shape mismatch:** The frontend adapter expects `{reply, message, session_id}` (per `ChatSendRes` schema), but the backend `/chat/send` returns `{user_message: {...}, ai_message: {...}}`. The AI response text is at `ai_message.content`, not at `reply`.

**Fix required (frontend):**
1. Change adapter path from `/api/chat` to `/api/chat/send`
2. Map response: `reply = res.data.ai_message?.content`
3. Map session: `sessionId = res.data.user_message?.session_id`

**Additional finding:** The frontend `getSession(id)` calls `GET /api/chat/sessions/{id}` expecting `{messages: [...]}`, but the backend does NOT have that route. The backend has `GET /api/chat/messages?session_id=...` instead (line 775). The frontend adapter needs to call `/api/chat/messages?session_id=${id}` and wrap the array in `{messages: [...]}`.

---

### A2: GET /api/portfolio/upload-latest-task — EXISTS

**Frontend calls:** `GET /api/portfolio/upload-latest-task`
**File:** `/app/frontend-v5/src/services/adapters/cas-upload.adapter.ts:155`

**Backend implementation:** `routes/upload.py:284-307`

```python
@router.get("/portfolio/upload-latest-task")
async def get_latest_upload_task(request: Request):
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"user_id": user["user_id"]},
        {"_id": 0},
        sort=[("created_at", -1)]
    )
    if not task:
        raise HTTPException(status_code=404, detail="No upload tasks found")
    return task
```

**Verdict:** The route exists and is registered (upload_router is included in server.py:137). If staging returns 404, it means either:
1. The user has never uploaded a CAS PDF (the endpoint returns 404 when there are no tasks — this is **correct behavior**, the frontend handles it via `catch (err) → return null`)
2. The staging deployment is stale

**No fix needed.** The frontend adapter already handles 404 gracefully.

---

### A3: GET /api/portfolio/upload-status/{taskId} — EXISTS

**Frontend calls:** `GET /api/portfolio/upload-status/${taskId}`
**File:** `/app/frontend-v5/src/services/adapters/cas-upload.adapter.ts:149`

**Backend implementation:** `routes/upload.py:218-281`

```python
@router.get("/portfolio/upload-status/{task_id}")
async def get_upload_status(request: Request, task_id: str):
    user = await get_current_user(request)
    task = await db.upload_tasks.find_one(
        {"task_id": task_id, "user_id": user["user_id"]}, {"_id": 0}
    )
    if not task:
        raise HTTPException(status_code=404, detail="Upload task not found")
    return task
```

**Verdict:** Exists. Returns 404 only when the task_id is not found for the user. This is correct behavior.

**No fix needed.**

---

### A5: POST /api/plans/refresh-fundamentals — EXISTS

**Frontend calls:** `POST /api/plans/refresh-fundamentals`
**File:** `/app/frontend-v5/src/services/adapters/plans.adapter.ts:135`

**Backend implementation:** `routes/plans.py:525-554`

```python
@router.post("/plans/refresh-fundamentals")
async def refresh_fundamentals(request: Request):
    from services.groww_fundamentals import refresh_cache_for_user
    user = await get_current_user(request)
    user_id = user["user_id"]
    fundamentals_map = await refresh_cache_for_user(user_id)
    return {
        "success": True,
        "stocks_updated": len(fundamentals_map),
        "updated_stocks": list(fundamentals_map.keys()),
        "message": f"Successfully refreshed fundamental data for {len(fundamentals_map)} stocks"
    }
```

**Verdict:** Exists. Registered via `plans_router` in `server.py:145`.

**Response shape note:** Frontend expects `{holdings_refreshed, refreshed_at}` but backend returns `{success, stocks_updated, updated_stocks, message}`. The frontend adapter maps `holdings_refreshed = obj.holdings_refreshed ?? 0` which will always be 0 since the backend uses `stocks_updated`.

**Fix required (frontend):** Map `holdingsRefreshed: obj.stocks_updated ?? obj.holdings_refreshed ?? 0`.

---

### A6: GET /api/intelligence/v3-score/{instrumentId} — EXISTS but ADMIN-ONLY

**Frontend calls:** `GET /api/intelligence/v3-score/${instrumentId}`
**File:** `/app/frontend-v5/src/services/adapters/intelligence.adapter.ts:31`

**Backend implementation:** `routes/intelligence.py:202-267`

```python
@router.get("/intelligence/v3-score/{instrument_id}")
async def get_v3_score(request: Request, instrument_id: str, refresh: bool = Query(False)):
    await require_admin(request)  # <-- ADMIN GATE
    ...
```

**Verdict:** The route EXISTS and is registered, but it calls `require_admin(request)` on line 209. Regular frontend users will get a 403 (Forbidden) or possibly a 404 depending on how `require_admin` raises. This is NOT truly missing — it is access-gated.

**Decision needed:** Either:
1. **Remove admin gate** — if this score should be visible to all authenticated users
2. **Add a user-facing endpoint** — e.g. `GET /api/funds/{isin}/v3-score` (this already exists in `routes/funds.py` per server.py:171) that computes a user-contextual V3 score
3. **Keep as admin-only** — and remove from the public frontend

The existing `routes/funds.py` (registered at server.py line 171) provides a user-scope V3 score endpoint at `GET /api/funds/{isin}/v3-score` (line 36). It returns `{isin, name, composite_score, scores: {returns, cost, consistency}}` and uses `get_current_user` (not `require_admin`). The frontend should use that instead of the admin-only `/api/intelligence/v3-score/{instrument_id}`.

---

### A7: GET /api/intelligence/sector-peers/{symbol} — EXISTS

**Frontend calls:** `GET /api/intelligence/sector-peers/${symbol}`
**File:** `/app/frontend-v5/src/services/adapters/intelligence.adapter.ts:38`

**Backend implementation:** `routes/intelligence.py:277-319`

```python
@router.get("/intelligence/sector-peers/{symbol}")
async def sector_peer_comparison(request: Request, symbol: str, limit: int = Query(10)):
    await get_current_user(request)  # regular auth, NOT admin-only
    ...
```

**Verdict:** Exists. User-authenticated (not admin-gated). Returns peers from the stock intelligence tool.

**If staging returned 404,** it is likely because:
- The `copilot_tools.stock_intelligence` service import failed on the staging VM
- Or the DAAS reference endpoint was unreachable, causing a 500 that was mistaken for 404

**No fix needed** in the route itself.

---

### B2: GET /api/signals/generate — NOT a method mismatch

**Frontend calls:** `GET /api/signals/generate` (via `http({ path: "/api/signals/generate" })` — GET is the default)
**File:** `/app/frontend-v5/src/services/adapters/plans.adapter.ts:129`

**Backend implementation:** `routes/plans.py:434-479`

```python
@router.get("/signals/generate")
async def generate_signals(request: Request):
    ...
```

**Verdict:** The backend uses `@router.get` which matches the frontend's GET call. The original MISSING-APIS.md reported this as "405 Wrong method (frontend calls GET, backend expects POST)" but **this is incorrect** — the backend decorator is `@router.get`, not `@router.post`.

If staging returned 405, it could be due to:
- A proxy/nginx layer that blocks GET on paths containing "generate"
- A stale deployment where the route was previously POST

**No fix needed** in either frontend or backend.

---

## Additional Discovery: GET /api/chat/sessions/{id} — MISSING

The frontend calls `GET /api/chat/sessions/${id}` to fetch messages for a session, but the backend does NOT have this route.

**Backend has:**
- `GET /api/chat/sessions` — list all sessions (line 668)
- `POST /api/chat/sessions` — create session (line 677)
- `DELETE /api/chat/sessions/{session_id}` — delete session (line 767)
- `GET /api/chat/messages?session_id=...` — get messages for a session (line 775)

**Frontend expects:** `GET /api/chat/sessions/{id}` returning `{messages: [...]}`

**Fix options:**
1. **(Preferred) Fix frontend** — change `getSession(id)` to call `GET /api/chat/messages?session_id=${id}` and wrap in `{messages: data}`
2. **Add backend route** — add `GET /api/chat/sessions/{session_id}` that returns `{messages: [...], ...session_metadata}`

---

## Summary of Required Fixes

### Frontend Fixes (adapter path/response mapping)

| Fix | File | Change |
|-----|------|--------|
| A1 path | `chat.adapter.ts:41` | `/api/chat` → `/api/chat/send` |
| A1 response | `chat.adapter.ts:43-48` | Map `reply` from `res.data.ai_message.content` |
| A1 session fetch | `chat.adapter.ts:61` | `/api/chat/sessions/${id}` → `/api/chat/messages?session_id=${id}` |
| A5 response | `plans.adapter.ts:137` | Map `holdingsRefreshed` from `obj.stocks_updated` |
| A6 path | `intelligence.adapter.ts:32` | Consider using `/api/funds/{isin}/v3-score` instead (user-scoped) |

### Backend Fixes (optional, improves DX)

| Fix | File | Change |
|-----|------|--------|
| A6 access | `intelligence.py:209` | Consider removing `require_admin` or adding a user-facing variant |
| A1 alias (optional) | `chat.py` | Add `POST /api/chat` as an alias for `/api/chat/send` for backwards compat |

### Deployment / Infrastructure Checks

| Item | Check |
|------|-------|
| A2, A3, A5, A7, B2 | Verify staging VM has the latest `routes/upload.py`, `routes/plans.py`, `routes/intelligence.py` deployed |
| All | Run `curl -s https://staging/api/` to confirm the backend is reachable and router registration succeeded |

---

## Proposed OpenAPI for the one truly missing route

### GET /api/chat/sessions/{session_id} (currently missing)

```yaml
openapi: 3.0.3
info:
  title: Chat Session Messages
  version: 1.0.0

paths:
  /api/chat/sessions/{session_id}:
    get:
      summary: Get a single chat session with its messages
      tags: [Chat]
      parameters:
        - name: session_id
          in: path
          required: true
          schema:
            type: string
      responses:
        "200":
          description: Session metadata plus ordered messages
          content:
            application/json:
              schema:
                type: object
                properties:
                  session_id:
                    type: string
                  title:
                    type: string
                  created_at:
                    type: string
                    format: date-time
                  messages:
                    type: array
                    items:
                      type: object
                      properties:
                        message_id:
                          type: string
                        role:
                          type: string
                          enum: [user, assistant]
                        content:
                          type: string
                        created_at:
                          type: string
                          format: date-time
                        widget:
                          type: object
                          nullable: true
                          description: Insight card / widget envelope (NIDP engine)
        "404":
          description: Session not found or does not belong to this user
```

### POST /api/chat (alias route — optional convenience)

If the frontend cannot be updated immediately, add this alias in `routes/chat.py`:

```yaml
paths:
  /api/chat:
    post:
      summary: Send a chat message (alias for /api/chat/send)
      tags: [Chat]
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [message]
              properties:
                message:
                  type: string
                  minLength: 1
                  maxLength: 4000
                session_id:
                  type: string
                  nullable: true
      responses:
        "200":
          description: User message and AI response
          content:
            application/json:
              schema:
                type: object
                properties:
                  reply:
                    type: string
                    description: AI response text (convenience field)
                  session_id:
                    type: string
                  message:
                    type: object
                    properties:
                      role:
                        type: string
                        enum: [assistant]
                      content:
                        type: string
                  user_message:
                    type: object
                  ai_message:
                    type: object
```
