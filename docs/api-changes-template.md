# API Changes Proposal: Nivesh v4

**Date**: [YYYY-MM-DD]  
**Based on**: docs/gap-analysis.md  
**Status**: Draft — awaiting approval

---

## Section A — Architectural Decisions

> These are the load-bearing decisions. Get these right and the endpoint 
> work below becomes mechanical. Each decision must have a chosen option 
> AND a rationale.

### Decision 1: Dashboard Endpoint Shape
**Question**: One composite endpoint vs six focused endpoints for the 
analytical dashboards (concentration, diversification, risk, performance, 
goals, tax)?

**Options considered**:
- A. `GET /dashboards/{type}` — single endpoint, type param
- B. `GET /dashboards/concentration`, `/dashboards/risk`, etc. — six endpoints
- C. `GET /portfolio/analytics` returning all six — UI picks

**Chosen**: [A | B | C]  
**Rationale**: [why]  
**Trade-offs accepted**: [what we give up]

### Decision 2: Recommendation Entity Schema
**Chosen schema**:
```typescript
{
  id: string,
  title: string,
  // ... (see gap analysis Finding 2)
}
```
**Rationale**: [why this shape]

### Decision 3: NIDP vs Nivesh Service Boundary
**Rule**: [Explicit rule for placing a new endpoint in one or the other.]
**Examples**:
- Holdings, classifications, raw analytics → NIDP
- Plan board, chat, recommendation state, advisor workflows → Nivesh

### Decision 4: Advisor vs Investor Endpoint Pattern
**Chosen**: [A | B]  
- A. Shared endpoints with `clientId` query param + role check
- B. Mirrored `/advisor/clients/{id}/...` namespace

**Rationale**: [why]

### Decision 5: Health Score Sourcing
**Where computed**: [NIDP | Nivesh]  
**Caching**: [strategy]  
**Returned by**: [list endpoints that include current/projected health]

### Decision 6: Plan Board Aggregation
**Pattern**: [how recommendations from 6 dashboards become plan items]

---

## Section B — New Endpoints

> One subsection per new endpoint. Include full request/response examples.

### B.1 — `GET /dashboards/{type}`
**Serves screens**: 05, 06, 07, 08, 09, 10 (mobile + web)  
**Service**: Nivesh  
**Auth**: Investor JWT (or advisor JWT with `clientId` query param per Decision 4)

**Request**:
```http
GET /dashboards/concentration HTTP/1.1
Authorization: Bearer <jwt>
```

**Response 200**:
```json
{
  "type": "concentration",
  "issueCount": 1,
  "insight": {
    "headline": "32% of your money is in financials",
    "subtext": "Above the 25% caution line — the single largest concentration."
  },
  "metrics": {
    "topConcentration": { "label": "Top 5 Stocks", "value": 48, "unit": "%" },
    "hhi": { "label": "HHI", "value": 1840 },
    "effectiveN": { "amcs": 8, "groups": 2 }
  },
  "breakdown": {
    "type": "bySector",
    "cautionLine": 25,
    "items": [
      { "label": "Financials", "value": 32 },
      { "label": "IT", "value": 21 },
      ...
    ]
  },
  "recommendations": [ /* Recommendation[] per Decision 2 */ ],
  "projection": {
    "metric": "health",
    "current": 86,
    "projected": 86
  }
}
```

**Error responses**: [list]

### B.2 — `POST /plan-board/items`
[similar structure]

### B.3 — [next endpoint]
...

---

## Section C — Modified Endpoints

> One subsection per modified endpoint. Show before/after.

### C.1 — `GET /portfolio` — add `dayChange` field
**Serves screens**: 04 (mobile home portfolio card)

**Before**:
```json
{ "currentValue": 1840000, "invested": 1500000, "returns": 340000 }
```

**After (additive)**:
```json
{ 
  "currentValue": 1840000, 
  "invested": 1500000, 
  "returns": 340000,
  "dayChange": { "absolute": 12400, "percent": 0.67 }
}
```

**Backward compat**: ✅ Additive only. Existing clients unaffected.

### C.2 — [next modification]
...

---

## Section D — Deprecations

| Endpoint | Field/Path | Replaced By | Deprecation Date | Removal Date |
|---|---|---|---|---|
| GET /portfolio | legacyRiskScore | (none — unused) | v4 release | v5 release |

---

## Section E — Web vs Mobile Handling

[For each case where web and mobile mockups suggest different shapes, 
state how it's handled — usually one of: identical response, optional 
fields, `view=` parameter, or separate endpoint.]

| Screen | Web Behavior | Mobile Behavior | Handling |
|---|---|---|---|
| 04 Chat Landing | Shows 3 insights + top recommendation | Shows 3 insights only | Single endpoint; `topRecommendation` field always returned, mobile UI hides it |
| | | | |

---

## Section F — Updated Postman Collection

**File**: `v4-designs/nivesh-postman-collection.v2.json`  
**Diff summary**: 
- [N] new endpoints added
- [N] endpoints modified (response shape)
- [N] endpoints marked deprecated

---

## Section G — Implementation Order

> Recommended sequence for Phase 3. Group by dependency: foundations first, 
> aggregators last.

1. **Recommendation entity** (DB model + shared serializer) — blocks dashboards
2. **Dashboard endpoint** `GET /dashboards/{type}` — one type first, then rest
3. **Plan board endpoints** — depends on Recommendation entity
4. **Portfolio builder endpoints**
5. **Advisor endpoints** — depend on investor endpoints being stable
6. **Modifications to existing endpoints** — last, lowest risk

For each item, estimated effort: [S/M/L] and primary risk: [text]

---

## Section H — Open Questions Resolved Since Gap Analysis

> Reference Section D of gap-analysis.md. For each question, either record 
> the answer or carry forward to a follow-up.

| # | Question | Answer | Source |
|---|---|---|---|
| 1 | NIDP vs Nivesh boundary | [answer] | [PRD section / human input] |
| | | | |

### Questions still open
[List any that didn't get answered. Flag if they block Phase 3.]

---

## Section I — Phase Gate

**Status**: Phase 2 complete  
**Awaiting**: Approval to proceed to Phase 3 (Implementation)  
**Critical reviews requested**: [highlight 2-3 specific decisions you want 
the human to sanity-check before code is written]