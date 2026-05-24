# Gap Analysis: Nivesh v4 Designs vs Existing APIs

**Date**: [YYYY-MM-DD]  
**Agent/Reviewer**: [name]  
**Sources reviewed**: Nivesh_PRD.docx, v4-designs/mobile/*, v4-designs/webapp/*, 
nivesh-postman-collection.json, nidp-postman-collection.json

---

## Section A — Source Inventory

### PRD Summary
- **Product one-liner**: [from PRD]
- **v4 scope**: [list features in scope]
- **Out of scope**: [list]
- **PRD vs PDF reconciliation**: [identical / differs — note differences]

### Key Domain Concepts Confirmed from PRD
| Concept | Definition | PRD section |
|---|---|---|
| Health Score | [definition] | [section] |
| Recommendation | [schema] | [section] |
| Plan Board | [definition] | [section] |
| NIDP | [definition] | [section] |
| [others...] | | |

### Screen Inventory
| # | Screen | Persona | Group | Mobile? | Web? |
|---|---|---|---|---|---|
| 01 | Homepage | Public | Auth | ✓ | ✓ |
| 02 | Login | Public | Auth | ✓ | ✓ |
| 03 | Onboarding | Investor | Auth | ✓ | ✓ |
| 04 | Chat Landing | Investor | Chat | ✓ | ✓ |
| 05 | Concentration Dashboard | Investor | Dashboard | ✓ | ✓ |
| 06 | Diversification Dashboard | Investor | Dashboard | ✓ | ✓ |
| 07 | Risk Dashboard | Investor | Dashboard | ✓ | ✓ |
| 08 | Performance Dashboard | Investor | Dashboard | ✓ | ✓ |
| 09 | Goals Dashboard | Investor | Dashboard | ✓ | ✓ |
| 10 | Tax Dashboard | Investor | Dashboard | ✓ | ✓ |
| 11 | Plan Board | Investor | Plan | ✓ | ✓ |
| 12 | Portfolio Builder | Investor | Builder | ✓ | ✓ |
| 13 | Recommendations | Investor | Builder | ✓ | ✓ |
| 14 | Instrument Allocation | Investor | Builder | ✓ | ✓ |
| 15 | Advisor Book | Advisor | Advisor | ✓ | ✓ |
| 16 | Client 360 | Advisor | Advisor | ✓ | ✓ |
| 17 | SIP Board | Advisor | Advisor | ✓ | ✓ |

### API Inventory

**nivesh-postman-collection.json** ([N] endpoints)
| Method | Path | Purpose | Auth |
|---|---|---|---|
| | | | |

**nidp-postman-collection.json** ([N] endpoints)
| Method | Path | Purpose | Auth |
|---|---|---|---|
| | | | |

**Interpretation of NIDP/Nivesh split**: [agent's assessment]

---

## Section B — Screen-by-Screen Mapping

> Status legend:  
> ✅ Exact match — endpoint returns exactly what's needed  
> ⚠️ Partial — endpoint exists but needs modification (new field, query param, shape change)  
> ❌ Missing — no endpoint covers this  
> 🗑️ Redundant — UI no longer needs something the API returns  
> N/A — UI-only (navigation, static copy, client-state)

### Group 1: Public + Auth (Screens 01, 02, 03)

#### 01 — Homepage
| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| | | | | |

#### 02 — Login
| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| | | | | |

#### 03 — Onboarding
| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| | | | | |

### Group 2: Chat (Screen 04)

#### 04 — Chat Landing
| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| | | | | |

### Group 3: Analytical Dashboards (Screens 05–10)

> ⚠️ All 6 dashboards share an identical structural pattern:
> 1. Header with issue count badge
> 2. Insight headline + subtext  
> 3. 3–4 key metric cards
> 4. Breakdown chart (categorical bars)
> 5. Ranked recommendations with {impact, effort, tradeOff, priority}
> 6. Apply panel with projected metric + "Send to Plan board" action
> 
> Document shared envelope here once; per-screen tables list only 
> type-specific metrics and breakdown fields.

**Shared envelope fields** (all 6 dashboards):
| Field | Type | Status | Notes |
|---|---|---|---|
| issueCount | int | | |
| insight.headline | string | | |
| insight.subtext | string | | |
| recommendations[] | Recommendation[] | | See entity schema in Section C |
| projection.current | number | | |
| projection.projected | number | | |

#### 05 — Concentration (type-specific)
| Element | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| Top 5 Stocks % | float | | | |
| HHI score | int | | | |
| Effective N (AMCs, Groups) | int, int | | | |
| Sector breakdown bars | [{sector, pct}] + caution line | | | |

#### 06 — Diversification
[table]

#### 07 — Risk
[table]

#### 08 — Performance
[table]

#### 09 — Goals
[table]

#### 10 — Tax
[table]

### Group 4: Plan Board (Screen 11)

#### 11 — Plan Board
| Element / Action | Data Needed | Existing Endpoint | Status | Notes |
|---|---|---|---|---|
| | | | | |

### Group 5: Builder + Recommendations (Screens 12, 13, 14)

#### 12 — Portfolio Builder
[table]

#### 13 — Recommendations
[table]

#### 14 — Instrument Allocation
[table]

### Group 6: Advisor (Screens 15, 16, 17)

#### 15 — Advisor Book
[table]

#### 16 — Client 360
[table]

#### 17 — SIP Board
[table]

---

## Section C — Cross-Cutting Findings

### Finding 1: Dashboard Contract Unification
[Analysis of whether to use one composite endpoint or six focused endpoints. 
Include rationale, request/response sketch, trade-offs.]

### Finding 2: Recommendation Entity Schema
[Proposed shared schema. List every screen that produces or consumes recommendations.]

Proposed schema:
```typescript
{
  id: string,
  title: string,
  subtitle: string,
  action: { type: "SELL"|"BUY"|"SWITCH"|"HARVEST"|"MERGE"|"RAISE_SIP"|..., 
            target: string, amount?: number },
  priority: "CRITICAL" | "OPTIMISE",
  impact: { label: string, value: string | number },
  effort: "LOW" | "MEDIUM" | "HIGH",
  tradeOff: string,
  sourceDashboard: "concentration"|"diversification"|"risk"|"performance"|"goals"|"tax",
  status: "open" | "accepted" | "skipped" | "done"
}
```

### Finding 3: NIDP vs Nivesh Boundary
[For each proposed new endpoint, indicate which service should own it.]

### Finding 4: Advisor vs Investor Endpoint Reuse
[Analysis of options:
A. Same endpoints with role-scoped clientId param
B. Mirrored /advisor/clients/{id}/... paths that proxy to investor logic
Recommendation with rationale.]

### Finding 5: Plan Board as Aggregation Sink
[How "Send to Plan board" works across dashboards. Single POST endpoint.]

### Finding 6: Health Score Ubiquity
[Which endpoints should return current/projected health score. Caching strategy.]

### Finding 7: Web vs Mobile Divergence
| Screen | Divergence Detected | Recommendation |
|---|---|---|
| | | |

### Finding 8: Redundant / Deprecated Fields
| Endpoint | Field | Reason for Removal | Deprecation Plan |
|---|---|---|---|
| | | | |

### Finding 9: Recurring Patterns Worth Standardizing
[E.g., consistent pagination, consistent "top N" query params, consistent 
error format. Note any inconsistency in existing APIs and propose fix.]

---

## Section D — Open Questions

> Every question MUST have either an answer from PRD or be flagged for 
> human input. Do not proceed to Phase 2 with unanswered questions that 
> affect API shape.

1. **NIDP vs Nivesh boundary**: [specific question]
2. **Recommendation generation timing**: pre-computed or on-demand?
3. **Health score formula**: server-side single source of truth?
4. **Chat backend**: existing service or new build? LLM provider?
5. **Plan board persistence**: single active plan or versioned?
6. **Advisor permissioning**: can advisor act on behalf of client?
7. **SIP execution path**: direct AMC/BSE Star MF or broker hand-off?
8. **Broker connect scope**: which brokers in v4 vs roadmap?
9. **CAS import sync/async**: synchronous or job-based?
10. **Concentration cap source**: user setting, policy, or risk-derived?
11. **NIDP connection indicator**: real health check or brand label?
12. **Tax harvest expiry timer semantics**: FY-end or per-lot?
[add as discovered]

---

## Section E — Summary Counts

| Status | Count | % |
|---|---|---|
| ✅ Exact match | | |
| ⚠️ Partial match | | |
| ❌ Missing | | |
| 🗑️ Redundant | | |
| N/A (UI-only) | | |
| **Total elements analyzed** | | 100% |

### Estimated change scope
- New endpoints: [n]
- Modified endpoints: [n]
- Fields to add: [n]
- Fields to deprecate: [n]
- Endpoints to deprecate: [n]

### High-risk areas requiring deepest design attention in Phase 2
1. Dashboard contract design (affects 6 screens)
2. Recommendation entity model (affects 8+ screens)
3. NIDP/Nivesh placement decisions
4. Plan board aggregation write path
5. Advisor vs investor reuse pattern
6. Health score sourcing and caching

---

## Section F — Phase Gate

**Status**: Phase 1 complete  
**Awaiting**: Approval to proceed to Phase 2 (Design Proposal)  
**Blocking questions**: [list any from Section D that must be answered 
before Phase 2 can proceed]