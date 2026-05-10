# NIDP → Nivesh Copilot Integration Plan

## Objective
Integrate **NIDP market/macro/event intelligence** into Nivesh Copilot so chat responses are:
- portfolio-aware (existing behavior), and
- market-context aware (new behavior),
without breaking current `/api/chat/*` and `/api/copilot/*` contracts.

---

## 1) What already exists in this repo

### Copilot/chat surfaces
- `backend/routes/chat.py` powers conversational assistant endpoints used in-app.
- `backend/routes/copilot.py` powers CIO assistant endpoints (`/api/copilot/explain`, `/ask`, etc.).

### NIDP capabilities already present
- `backend/nidp/services/daas_api/` exposes read APIs (`/v1/prices`, `/v1/corporate-actions`, `/v1/flows`, `/v1/macro`, `/v1/snapshots`, `/v1/features`, etc.).
- `backend/nidp/migrations/032_nidp_feeds_subscriptions.sql` and `backend/services/feed_rag/` indicate feed/RAG plumbing intended for copilot grounding.

### Net: integration is mostly an application-wiring problem
NIDP data plane exists; Copilot exists; we need a **context adapter** between them.

---

## 2) Recommended target architecture

Add a small NIDP adapter layer in the main backend:

1. **NIDP client** (HTTP)
   New service module (`backend/services/nidp_client.py`) that calls DaaS API with API key.

2. **Market context builder**
   New module (`backend/services/nidp_context.py`) that transforms raw API responses into concise LLM-safe blocks:
   - market regime (index trend, breadth proxy)
   - flows (FII/DII trend)
   - near-term event calendar
   - symbol-level facts (latest close, 1d/1w change, recent corporate events)

3. **Prompt injection point**
   In `routes/chat.py` and `routes/copilot.py`, append a `NIDP_CONTEXT` section to system/context prompt only when:
   - feature flag enabled
   - NIDP call healthy
   Else fail-open to current behavior.

4. **Caching + graceful degradation**
   - Redis cache by `(user_id/symbols + date bucket)` for 5–30 min.
   - Timeout budget per request (e.g., 700–1200 ms total NIDP enrichment).
   - On timeout/error: continue response with existing portfolio context.

---

## 3) Data contract for Copilot prompt context

Use a compact schema to prevent token bloat:

```json
{
  "as_of": "2026-05-10T00:00:00Z",
  "market": {
    "regime": "risk_on|neutral|risk_off",
    "headline": "NIFTY 50 +0.6% WoW, FII net buyers 3/5 sessions"
  },
  "symbols": [
    {
      "symbol": "RELIANCE",
      "last_close": 0,
      "chg_1d_pct": 0,
      "chg_1w_pct": 0,
      "events": ["Q4 result due this week"]
    }
  ],
  "macro": ["India 10Y yield: ..."],
  "events": ["RBI policy on ..."]
}
```

Prompt rules:
- Prefer deterministic facts from `NIDP_CONTEXT`.
- Never fabricate missing values.
- If NIDP unavailable, explicitly switch to portfolio-only reasoning.

---

## 4) Integration steps (execution order)

### Phase 1 — plumbing (low risk)
1. Add env vars in backend config:
   - `NIDP_DAAS_BASE_URL`
   - `NIDP_DAAS_API_KEY`
   - `NIDP_COPILOT_ENABLED` (default false)
2. Implement `nidp_client.py` with typed methods and retries.
3. Add `nidp_context.py` aggregator with strict timeout.

### Phase 2 — route wiring
4. Inject NIDP context into:
   - `/api/chat/send`
   - `/api/chat/stream`
   - `/api/copilot/ask`
   - `/api/copilot/explain`
5. Gate with feature flag for staged rollout (internal users first).

### Phase 3 — quality + observability
6. Add metrics/log fields:
   - `nidp_enrichment_ms`
   - `nidp_cache_hit`
   - `nidp_enrichment_status` (ok/timeout/error)
7. Add circuit breaker after consecutive failures.
8. Add snapshot tests for prompt blocks and endpoint behavior.

---

## 5) Minimum test plan

1. Unit tests
- `nidp_client` handles auth errors, 429, retries, and timeout.
- `nidp_context` composes deterministic output with partial data.

2. API tests
- Chat send/stream with NIDP on/off.
- Copilot ask/explain with NIDP failure (must still return 200 and useful answer).

3. Regression
- Existing chat/coplan tests remain green with flag disabled.

---

## 6) Rollout checklist

1. Deploy with `NIDP_COPILOT_ENABLED=false`.
2. Smoke test with internal advisor accounts.
3. Enable for 5% cohort.
4. Monitor latency and response quality.
5. Expand to 100% after stable 48 hours.

---

## 7) Open decisions

1. **Transport choice:** call NIDP DaaS HTTP vs direct DB read from monolith.
   - Recommendation: HTTP DaaS first (clear contract, decoupled infra).
2. **Freshness target:** intraday vs EOD for each insight block.
3. **User messaging:** whether to disclose “market context refreshed at <ts>” in UI.

---

## 8) Suggested first implementation PR scope

Keep first PR intentionally small:
1. Add `nidp_client.py` + env wiring.
2. Add `nidp_context.py` for 2 blocks only:
   - index trend headline
   - top portfolio symbols latest close + 1D change
3. Inject into `/api/chat/send` only behind feature flag.

Then expand incrementally to stream + copilot routes + events/macro blocks.
