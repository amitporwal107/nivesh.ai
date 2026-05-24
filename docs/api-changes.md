# API Changes Proposal: Nivesh v4

**Date**: 2026-05-24
**Based on**: `docs/gap-analysis.md`
**Status**: Phase 3 Implementation — in progress (2026-05-24)
**Decisions locked**: B1, B2, D1, D2, D3, D4 (approved 2026-05-24)
**Phase 3 started**: 2026-05-24 — all 4 architectural decisions confirmed

---

## Section A — Architectural Decisions

### Decision 1 — Dashboard Endpoint Shape

**Chosen**: **Both — keep six focused endpoints (existing) AND add one composite per dashboard** (new).

- The six existing focused endpoints (`/api/portfolio/exposure/concentration`, `/api/portfolio/risk-analytics`, `/api/goals`, etc.) remain unchanged for advanced callers (admin, partners, mobile-app v2/v3).
- A new composite is added per dashboard type: `GET /api/dashboards/{type}` — `type ∈ {concentration, diversification, risk, performance, goals, tax}`. This is the prototype-fidelity contract v4 uses.
- The composite returns the unified envelope (insight + stat_tiles + breakdown + recommendations + projection) by composing the focused endpoint + the active plan filtered by `source_domain` + the plan health-projection delta — three logical reads, within the 3-DB-query budget per the brief.

**Rationale**: Existing clients stay untouched (additive constraint of the brief satisfied). v4 screens read a single endpoint each, avoiding the 3-call chatty pattern that today's V4 frontend does (GET concentration + GET plans + GET health-projection per page load).

**Trade-offs accepted**: Slight duplication — the composite re-serialises data already in the focused endpoint. Mitigated by the composite running through a shared serializer that calls the same domain service.

### Decision 2 — Recommendation Entity Schema

**Chosen**: Additive evolution of the existing `action` shape. No deprecation of `action_id`, `type`, `status`, `priority`, `reason_text`, `reason_codes`. New fields added:

```typescript
{
  // Existing (unchanged)
  action_id: string,
  type: "EXIT"|"ADD"|"TRIM"|"HOLD"|"REVIEW"|"SWITCH"|"MERGE"|"HARVEST"|"RAISE_SIP",
  status: "PENDING"|"IN_PROGRESS"|"COMPLETED"|"SKIPPED",   // UPPERCASE always
  priority: number,                            // 1 highest, 2, 3
  asset_type: "STOCK"|"FUND"|"DEBT"|"GOLD",
  asset_name: string,
  instrument_id: string | null,
  amount: number,                              // rupees
  reason_text: string,
  reason_codes: string[],
  confidence: "HIGH"|"MEDIUM"|"LOW",
  created_at: ISO_string,

  // NEW — required for v4 (additive)
  verb: "ADD"|"EXIT"|"TRIM"|"HOLD"|"SWITCH"|"MERGE"|"HARVEST"|"RAISE_SIP",
                                              // user-facing verb (PRD §7.4 vocabulary)
                                              // stock verbs: Add/Exit/Trim/Hold
                                              // fund verbs:  Switch/Exit/Add/Merge/Hold
  priority_label: string,                      // "Critical"|"Optimise"|"Enhance" (most dashboards)
                                              // OR "Closes the gap"|"Closes most"|"Partial" (Goals)
  impact: { label: string, value: string },    // {"Impact","+6 pts"} or {"Beta cut","-0.18"}
  effort: "LOW"|"MEDIUM"|"HIGH",
  trade_off: string,                            // MANDATORY per PRD §7.4
  expected_impact: {
    health_delta?: number,                     // pts to health score
    beta_delta?: number,                       // Risk dashboard
    xirr_delta_pp?: number,                    // Performance
    tax_saved_inr?: number,                    // Tax
    funding_pp?: number,                       // Goals (% of target)
    fund_count_delta?: number,                 // Diversification
  },
  source_domain: "concentration"|"diversification"|"risk"|"performance"|"goals"|"tax",
                                              // PRD §8.1 source memory — drives Plan Board origin tag
  exclusive: boolean,                          // true for Goals actions (PRD §7.4 mutually exclusive)

  // NEW — asset-class-aware scoring (per Decision D1, NIDP-sourced)
  scores?: {
    add: number,        // 0-100  "should I add more?"
    exit: number,       // 0-100  "should I exit entirely?"
    switch?: number,    // 0-100  MF only — "is there a better alternative?"
    hold: number,       // 0-100  "is hold-as-is the right call?"
  },
  switch_target?: {                            // populated when verb=SWITCH
    instrument_id: string,
    asset_name: string,
    reason: string,                            // why this alternative
  },
}
```

**Sourcing of `scores`**:
- **Stocks** — Nivesh proxies `GET /v1/stocks/scores/{symbol}` from NIDP (or `POST /v1/stocks/scores/bulk` for the holdings list). NIDP today returns `{quality, health, exit, add, hold}` per symbol — fields `add`, `exit`, `hold` map 1:1 to `scores.{add, exit, hold}`.
- **Funds** — Nivesh proxies `GET /v1/mf/scores/{isin}` from NIDP (or `POST /v1/mf/scores/bulk`). NIDP today returns `{performance, cost, consistency}` sub-scores per ISIN.
- A new user-scope endpoint `GET /api/funds/{isin}/v3-score` (Modified Endpoint C.4) demotes the existing admin-only `/api/intelligence/v3-score/{id}` so the Recommendations screen (13) can render fund sub-scores.

**⚠️ `switch_score` does not exist on NIDP today — Phase 2 must design it.**

Proposed `switch_score` derivation (computed on Nivesh, sourced from NIDP primitives):

```
switch_score(holding_isin) = exit_score(holding_isin)
                           × (1 + replacement_advantage_pp / 100)
```

where:
- `exit_score(holding_isin)` = existing exit score on NIDP `/v1/mf/scores/{isin}` (range 0-100)
- `replacement_advantage_pp` = `top_peer.composite_score − holding.composite_score`, where `top_peer` is the highest-composite-score fund in the same NIDP category as the holding, normalised to 0-25 pp upside
- Result clamped to 0-100

The replacement fund itself populates `switch_target`:

```typescript
switch_target: {
  instrument_id: "INF...",     // top peer in same category with higher composite_score
  asset_name: "Parag Parikh Flexi Cap",
  reason: "Higher composite score (91 vs 78); lower expense ratio; better consistency."
}
```

**Two implementation options**:

| Option | Description | Trade-off |
|---|---|---|
| **A. Nivesh-side computation (recommended for v4)** | Nivesh computes `switch_score` + `switch_target` on Nivesh side by composing NIDP's per-ISIN scores + NIDP's category listing. No new NIDP endpoint. | Logic lives in Nivesh; if other consumers (mobile, partners) need the same primitive later, it duplicates. |
| **B. New NIDP route `GET /v1/mf/scores/{isin}/switch-target`** | NIDP returns `{switch_score, target_isin, advantage_pp, reason}` per ISIN. Pre-computed in nightly scoring batch. | One source of truth; cached; partner-friendly. But: adds NIDP scope to v4 — extra coordination + a NIDP release. |

**Chosen for v4**: **Option A** — Nivesh-side computation. Faster to ship; preserves "no NIDP changes in v4" from Decision 3. If/when a second consumer needs `switch_score`, promote to NIDP via Option B.

**Risks to flag in Phase 3 implementation**:
- Category-mismatch edge cases: smallcap-vs-flexi-cap shouldn't suggest a flexi-cap as switch_target. Add a hard category-match filter.
- Top-peer staleness: NIDP's `/v1/mf/scores/` is refreshed nightly; cache `switch_target` per ISIN for 24h.
- Cost-leak special case: per existing reason_code `COST_LEAK_SWITCH_TO_DIRECT`, the switch_target is the **direct plan of the same fund** (not a different fund) — the algorithm must check this first.

**Rationale**: Additive keeps mobile app + existing partners working. Stock verbs vs fund verbs encoded in `verb` field per asset_type (PRD §7.4). NIDP-sourced scoring satisfies the grounding rule (PRD §11.4). The `expected_impact` block is the missing piece that lets each dashboard's ③ Apply footer animate "before → after" and lets the Plan Board's projected-health ring reconcile (PRD §8.2).

### Decision 3 — NIDP vs Nivesh Service Boundary

**Rule**: Any new endpoint that requires market data, fundamentals, technicals, instrument scoring, peer comparison, or per-user pre-computed intelligence → **NIDP**. Any new endpoint that aggregates / mutates user state → **Nivesh**.

**Placement of v4 new endpoints**:

| Endpoint | Owner | Justification |
|---|---|---|
| `GET /api/dashboards/{type}` | Nivesh | Composite over plan + insight + projection (Nivesh state) |
| `GET /api/recommendations/stocks` | Nivesh (proxy NIDP screening) | Greenfield stock discovery uses NIDP screening engine; surfaced via Nivesh for auth scope |
| `GET /api/funds/{isin}/v3-score` | Nivesh (proxy NIDP) | Demotion of admin-only route to user scope |
| `GET /api/portfolio/tax-summary` | Nivesh | Composes NIDP unrealised gains + user holdings |
| `GET /api/intelligence/portfolio/360` | Nivesh | 6-domain rollup of multiple Nivesh sub-endpoints |
| `GET /api/advisor/summary` | Nivesh | Book-level KPIs aggregated from MFD profiles |
| `GET /api/advisor/sip-board` + `…/summary` | Nivesh | Operations over Nivesh SIP records |
| `GET /api/mfd/profiles/{id}/needs-attention` | Nivesh | Per-client item list |
| `POST /api/mfd/profiles/{id}/review-pack/generate` | Nivesh | Output formatting |
| `POST /api/mfd/profiles/{id}/call-log` | Nivesh | CRM event |
| `POST /api/mfd/profiles/{id}/sip-nudge` | Nivesh | Client-messaging |
| `POST /api/plans/active/actions` | Nivesh | Plan mutation |
| `PATCH /api/plans/{pid}/actions/{aid}/discuss` | Nivesh | Advisor-side write (Discuss-only per PRD §10.2) |

**No new endpoints on NIDP** for v4 — NIDP's existing surface (per-asset scores, snapshots, intelligence rollups) is sufficient. Future enhancement: a `GET /v1/intelligence/portfolio/{user_id}/recommendations` could pre-compute the recommendation set server-side, but that's a Phase 3+ optimization.

### Decision 4 — Advisor vs Investor Endpoint Pattern

**Chosen**: **A — Shared endpoints with role-scoped impersonation** (today's pattern, retained).

- Per-client reads use the existing impersonation: `POST /api/mfd/profiles/{id}/activate` swaps `effective_user_id`; all downstream reads (`/api/insights/v3-portfolio`, `/api/plans/active`, `/api/dashboards/{type}`, etc.) automatically scope to the impersonated client.
- Aggregations stay in the `/api/advisor/*` namespace (`/api/advisor/aum`, `/api/advisor/today`, new `/api/advisor/sip-board`, new `/api/advisor/summary`).
- Per-client mutations from the advisor surface are restricted to **Discuss-only writes** (`PATCH /api/plans/{plan_id}/actions/{action_id}/discuss`) plus client-hand-off events (`POST /api/mfd/profiles/{id}/sip/{sip_id}/request-bank-update`). PRD §10.2 invariant preserved.

**Rationale**: Option B (mirrored namespace) doubles the surface for no UX gain; impersonation is already battle-tested via `mfd_workspace.resolve_effective_user` (deps.py:65-86). One auth gate, one set of endpoints.

### Decision 5 — Health Score Sourcing & Caching

**Where computed**: Nivesh (existing Health-score engine). NIDP supplies the primitives; Nivesh combines them. PRD §11.4 invariant: client + advisor see the identical score.

**Caching**: Per-user, in Redis, TTL 15 min. Invalidated on: `cas-snapshot/{date}/activate`, `POST /api/plans/{pid}/actions/{aid}` (status mutation may shift projection), `POST /api/plans/active/actions` (new action added).

**ETag**: `/api/insights/v3-portfolio` responds with `ETag: "<sha1 of score + grade>"`. Dashboard composite endpoints set the same ETag so the Plan Board can detect score-shift on accept.

**Returned by**:
- `GET /api/insights/v3-portfolio` (source of truth)
- `GET /api/dashboards/{type}` (echoes current + projected in `.projection`)
- `GET /api/plans/active/health-projection` (delta breakdown — kept for backward compat; the new composite supersedes it for v4 reads)
- `GET /api/intelligence/portfolio/360` (per-domain rollup — advisor Client 360)

**Grade collapse (server-side)**: Move 7-band → 4-band ("A+/A → A", "B+/B → B", "C → C", "D/F → D") into the v3-portfolio handler. Per PRD §13.1 ("graded A to D") and to remove the adapter logic currently in the V4 frontend.

### Decision 6 — Plan Board Aggregation

**Pattern**: Plan Board is the cross-dashboard tracker. Every accepted action — from any of the 6 dashboards, including Tax and Goals — flows into `/api/plans/active.actions[]` via:

- **Dashboard actions** (Concentration / Diversification / Risk / Performance): action_plan_manager already produces these on snapshot activation. Add `source_domain` + `verb` + `trade_off` + `expected_impact` + `effort` (Modified Endpoint C.1).
- **Tax actions**: new writer on snapshot activation reads `tax_harvest` widget candidates and emits plan_actions rows with `source_domain="tax"`, `reason_codes=["TAX_HARVEST"]` etc.
- **Goals actions**: new writer reads `goals[].last_simulation.recommendations[]` from the goal engine (today only available inside the widget envelope) and emits plan_actions with `source_domain="goals"`, `exclusive=true`, `reason_codes=["GOAL_SIP_INCREASE"|"GOAL_LUMPSUM"|"GOAL_HORIZON_EXTENSION"]`.
- **Client-side cross-domain composition**: NEW endpoint `POST /api/plans/active/actions` (New Endpoint B.10) lets the client add an action that the engine didn't auto-generate (rare — primarily for advisor "Discuss" items promoted to client plan).

**Reconciliation** (PRD §8.2): `plan.projection.target = current_health_score + sum(action.expected_impact.health_delta WHERE action.status IN (ACCEPTED, COMPLETED))`. The single Health-score engine produces both per-action deltas and dashboard projections, so the numbers reconcile by construction.

---

## Section B — New Endpoints

### B.1 — `GET /api/dashboards/{type}`

**Serves screens**: 05 Concentration, 06 Diversification, 07 Risk, 08 Performance, 09 Goals, 10 Tax (mobile + web)
**Service**: Nivesh
**Auth**: Session cookie (investor) OR session + active `profile_id` (advisor impersonation)
**DB query budget**: ≤3 — (1) domain service call, (2) `plans.active` lookup, (3) `health_projection` cached read

**Request**:
```http
GET /api/dashboards/concentration?lens=sector HTTP/1.1
Cookie: session=<token>
```

**Path params**: `type` ∈ `{concentration, diversification, risk, performance, goals, tax}`
**Query params** (optional):
- `lens` — Concentration: `sector|amc|company|group`; Diversification: `overlap|stocks|category|asset_mix`
- `period` — Performance: `1y|3y|5y` (default `1y`)

**Response 200**:
```json
{
  "type": "concentration",
  "badge": { "label": "High", "tone": "rust" },
  "insight": {
    "headline": "32% of your money is in financials",
    "subtext": "Above the 25% caution line — the single largest concentration.",
    "hero": { "label": "TOP 5", "value": "48%", "tone": "rust" }
  },
  "stat_tiles": [
    { "label": "Top 5", "value": "48%", "tone": "rust" },
    { "label": "HHI", "value": "1840", "sub": "Concentrated" },
    { "label": "Eff. N", "value": "8.2" }
  ],
  "breakdown": {
    "lens": "sector",
    "lens_options": ["sector", "amc", "company", "group"],
    "caution_pct": 25,
    "items": [
      { "name": "Financials", "pct": 32.0, "tone": "rust" },
      { "name": "IT",         "pct": 21.0, "tone": "saffron" },
      { "name": "Consumer",   "pct": 14.0, "tone": "saffron" },
      { "name": "Industrials","pct": 12.0, "tone": "saffron" },
      { "name": "Healthcare", "pct":  9.0, "tone": "moss" }
    ]
  },
  "recommendations": [
    {
      "action_id": "a_01H...",
      "type": "TRIM", "verb": "TRIM",
      "title": "Trim financials from 32% to 22%",
      "subtitle": "SELL HDFC BANKING ETF · ₹1.8L",
      "source_domain": "concentration",
      "asset_type": "STOCK", "asset_name": "HDFC Banking ETF",
      "instrument_id": "INE...",
      "amount": 180000,
      "priority": 1, "priority_label": "Critical",
      "impact":  { "label": "Impact",  "value": "+6 pts" },
      "effort":  "LOW",
      "trade_off": "Realises 3.1K LTCG",
      "expected_impact": { "health_delta": 6 },
      "exclusive": false,
      "status": "PENDING",
      "reason_text": "Financials sector is 32% of portfolio — above 25% caution line.",
      "reason_codes": ["SECTOR_CONCENTRATION"],
      "confidence": "HIGH",
      "scores": { "add": 12, "exit": 78, "hold": 22 },
      "created_at": "2026-05-24T10:00:00Z"
    }
  ],
  "projection": {
    "metric_label": "Projected health",
    "current": 86,
    "projected": 92,
    "unit": "",
    "tone": "moss"
  },
  "etag": "sha1:abc123..."
}
```

**Errors**: `404` (no portfolio data — render Onboarding upsell); `503` (NIDP intelligence stale — surface but still render last-known).

**Backward compat**: Additive. Existing focused endpoints (`/api/portfolio/exposure/concentration` etc.) unchanged.

---

### B.2 — `GET /api/intelligence/portfolio/360`

**Serves screens**: 16 Client 360 (advisor)
**Service**: Nivesh
**Auth**: Session + impersonation context (`POST /api/mfd/profiles/{id}/activate` first)
**DB queries**: ≤3 — composes v3-portfolio + tax-summary + goals/snapshot in one server-side call

**Request**:
```http
GET /api/intelligence/portfolio/360 HTTP/1.1
Cookie: session=<token>; active_profile_id=<profile_uuid>
```

**Response 200**:
```json
{
  "client": {
    "profile_id": "p_01H...",
    "name": "Rohan Mehta",
    "aum_rs": 18000000,
    "style": "GOAL_LED",
    "risk_profile": "MODERATE",
    "last_seen_days": 14
  },
  "health": { "score": 62, "grade": "C", "tone": "rust" },
  "domains": [
    { "key": "concentration",   "score": 38, "tone": "rust",  "metric_label": "Sector concentration", "metric_value": "38%" },
    { "key": "performance",     "score": 78, "tone": "moss",  "metric_label": "XIRR", "metric_value": "19%" },
    { "key": "risk",            "score": 64, "tone": "gold",  "metric_label": "Beta", "metric_value": "1.28" },
    { "key": "diversification", "score": 82, "tone": "moss",  "metric_label": "Funds", "metric_value": "8" },
    { "key": "tax",             "score": 70, "tone": "indigo","metric_label": "Harvest", "metric_value": "₹14K" },
    { "key": "goals",           "score": 45, "tone": "rust",  "metric_label": "At risk", "metric_value": "1" }
  ],
  "needs_attention": [
    {
      "item_id": "n_01H...",
      "title": "Child-education goal will miss by ₹11L",
      "subtitle": "Goals · suggest SIP raise",
      "source_domain": "goals",
      "severity": "HIGH",
      "discuss_status": "PENDING"
    }
  ],
  "actions": ["prepare_review_pack", "log_a_call", "open_plan_board"]
}
```

---

### B.3 — `GET /api/mfd/profiles/{id}/needs-attention`

**Serves screens**: 16 Client 360
**Service**: Nivesh
**Auth**: Advisor session
**DB queries**: 1 — reads from `plan_actions` joined with `insights` filtered by severity ≥ HIGH

**Request**:
```http
GET /api/mfd/profiles/p_01H.../needs-attention HTTP/1.1
```

**Response 200**:
```json
{
  "items": [
    {
      "item_id": "n_01H...",
      "title": "Child-education goal will miss by ₹11L",
      "subtitle": "Goals · suggest SIP raise",
      "source_domain": "goals",
      "severity": "HIGH",
      "discuss_status": "PENDING",
      "linked_action_id": "a_01H..."
    }
  ]
}
```

---

### B.4 — `POST /api/mfd/profiles/{id}/review-pack/generate`

**Serves screens**: 16 Client 360 ("Prepare review pack" CTA)
**Service**: Nivesh
**Auth**: Advisor session
**Returns**: Async task — poll status

**Request**:
```http
POST /api/mfd/profiles/p_01H.../review-pack/generate HTTP/1.1
Content-Type: application/json

{
  "format": "pdf",
  "sections": ["health", "domains", "needs_attention", "plan", "performance"]
}
```

**Response 202**:
```json
{
  "task_id": "t_01H...",
  "status": "QUEUED",
  "estimated_seconds": 15
}
```

**Polling**: `GET /api/mfd/profiles/{id}/review-pack/{task_id}` returns `{status, download_url?}`.

---

### B.5 — `POST /api/mfd/profiles/{id}/call-log`

**Serves screens**: 16 Client 360 ("Log a call" CTA)
**Service**: Nivesh
**Auth**: Advisor session

**Request**:
```http
POST /api/mfd/profiles/p_01H.../call-log HTTP/1.1
Content-Type: application/json

{
  "occurred_at": "2026-05-24T15:30:00Z",
  "duration_min": 20,
  "channel": "PHONE",
  "outcome": "DISCUSSED_REBALANCE",
  "note": "Discussed concentration trim; client agreed to ₹1.8L sell of HDFC Banking ETF."
}
```

**Response 201**: `{ "call_log_id": "c_01H...", "occurred_at": "..." }`

---

### B.6 — `GET /api/advisor/summary`

**Serves screens**: 15 Advisor Book (top stat row)
**Service**: Nivesh
**Auth**: Advisor session
**DB queries**: 2 — sums + counts across the advisor's profiles

**Request**:
```http
GET /api/advisor/summary HTTP/1.1
```

**Response 200**:
```json
{
  "book_aum_rs": 410000000,
  "avg_health_score": 79,
  "needs_attention_count": 5,
  "actions_open_count": 38,
  "clients_total": 24
}
```

---

### B.7 — `GET /api/advisor/sip-board`

**Serves screens**: 17 SIP Board (queues + list)
**Service**: Nivesh
**Auth**: Advisor session
**DB queries**: 2 — SIPs joined with bounce records, filtered by `state`

**Request**:
```http
GET /api/advisor/sip-board?state=failed&cycle=2026-05 HTTP/1.1
```

**Query params**:
- `state` — `failed | expiring | step_up | healthy` (default: all four returned grouped)
- `cycle` — `YYYY-MM` (default: current cycle)

**Response 200**:
```json
{
  "cycle": "2026-05",
  "queues": {
    "failed":    [ /* SipBoardRow */ ],
    "expiring":  [ /* SipBoardRow */ ],
    "step_up":   [ /* SipBoardRow */ ],
    "healthy":   [ /* SipBoardRow (truncated to 20) */ ]
  }
}
```

**SipBoardRow**:
```json
{
  "sip_id": "s_01H...",
  "profile_id": "p_01H...",
  "client_name": "Anjali Desai",
  "fund_isin": "INF...",
  "fund_name": "Parag Parikh Flexi Cap",
  "amount_rs": 15000,
  "cadence": "MONTHLY",
  "state": "failed",
  "last_bounce_reason": "INSUFFICIENT_BALANCE",
  "last_bounce_date": "2026-05-02",
  "cycles_missed": 2,
  "next_debit_date": "2026-06-02",
  "mandate_id": "m_01H...",
  "mandate_expiry_date": "2027-04-30",
  "proposed_stepup_pct": null,
  "available_actions": ["MESSAGE_CLIENT", "REQUEST_BANK_UPDATE"]
}
```

---

### B.8 — `GET /api/advisor/sip-board/summary`

**Serves screens**: 17 SIP Board (top stat row)
**Service**: Nivesh
**Auth**: Advisor session
**DB queries**: 1 — single aggregation query

**Response 200**:
```json
{
  "cycle": "2026-05",
  "monthly_inflow_rs": 640000,
  "active_sips_count": 68,
  "failed_count": 3,
  "mandate_at_risk_count": 4
}
```

---

### B.9 — `POST /api/mfd/profiles/{id}/sip-nudge`

**Serves screens**: 17 SIP Board ("Message" CTA)
**Service**: Nivesh
**Auth**: Advisor session

**Request**:
```http
POST /api/mfd/profiles/p_01H.../sip-nudge HTTP/1.1
Content-Type: application/json

{
  "sip_id": "s_01H...",
  "template": "BOUNCE_INSUFFICIENT_BALANCE",
  "channel": "EMAIL"
}
```

**Response 202**: `{ "nudge_id": "n_01H...", "queued_at": "..." }`

**Templates**: `BOUNCE_INSUFFICIENT_BALANCE | BOUNCE_MANDATE_LIMIT | BOUNCE_ACCOUNT_CLOSED | MANDATE_EXPIRY | STEPUP_DUE`. Body composed server-side from a NIDP-grounded template (no LLM in critical path).

---

### B.10 — `POST /api/plans/active/actions`

**Serves screens**: 09 Goals (when Goals action created from goal-engine), 10 Tax (when Tax action created from widget candidate), 16 Client 360 ("Discuss" promotion)
**Service**: Nivesh
**Auth**: Session

**Request**:
```http
POST /api/plans/active/actions HTTP/1.1
Content-Type: application/json

{
  "source_domain": "tax",
  "type": "HARVEST",
  "verb": "HARVEST",
  "asset_type": "FUND",
  "asset_name": "Nippon Smallcap",
  "instrument_id": "INF...",
  "amount": 70000,
  "priority": 1, "priority_label": "Critical",
  "impact":  { "label": "Tax saved", "value": "₹2.8K" },
  "effort": "LOW",
  "trade_off": "Re-entry at market price",
  "expected_impact": { "tax_saved_inr": 2800, "health_delta": 1 },
  "exclusive": false,
  "reason_text": "Long-term gain harvestable within ₹1.25L FY limit.",
  "reason_codes": ["TAX_HARVEST"],
  "confidence": "HIGH"
}
```

**Response 201**: returns the full Recommendation object including server-assigned `action_id` and `created_at`.

**Idempotency**: Pass `Idempotency-Key: <uuid>` header to make repeated POSTs from the same client idempotent.

---

### B.11 — `PATCH /api/plans/{plan_id}/actions/{action_id}/discuss`

**Serves screens**: 16 Client 360 ("Discuss" buttons per item)
**Service**: Nivesh
**Auth**: Advisor session (impersonation required)

**Request**:
```http
PATCH /api/plans/p_01H.../actions/a_01H.../discuss HTTP/1.1
Content-Type: application/json

{
  "discussion_note": "Client agreed to consider; awaiting confirmation."
}
```

**Response 200**:
```json
{
  "action_id": "a_01H...",
  "discussed_at": "2026-05-24T15:35:00Z",
  "discussed_by_advisor_id": "u_advisor_01H...",
  "discussion_count": 1,
  "discussion_note": "Client agreed to consider; awaiting confirmation."
}
```

**Note**: Per PRD §10.2 — this DOES NOT change `action.status`. The client retains sole control over Accept/Skip.

---

### B.12 — `GET /api/portfolio/tax-summary`

**Serves screens**: 10 Tax dashboard (replaces widget-pattern call)
**Service**: Nivesh
**Auth**: Session
**DB queries**: ≤3 — holdings + capital_gains + tax_rules lookup

**Request**:
```http
GET /api/portfolio/tax-summary?fy=2025-26 HTTP/1.1
```

**Response 200**:
```json
{
  "fy": "2025-26",
  "ltcg_limit_rs": 125000,        // ₹1.25L per Jul-2024 tax law (FIX C.8.1)
  "ltcg_used_rs": 18000,
  "ltcg_remaining_rs": 107000,
  "total_harvestable_rs": 14000,
  "days_to_fy_end": 41,
  "candidates": [
    {
      "instrument_id": "INF...",
      "fund_name": "Nippon Smallcap",
      "gain_rs": 70000,
      "gain_type": "LTCG",
      "days_held": 420,
      "eligible": true,
      "eligible_after_date": null,
      "wash_sale_risk": false
    }
  ],
  "warning": null
}
```

---

### B.13 — `GET /api/recommendations/stocks`

**Serves screens**: 13 Recommendations (top stocks list)
**Service**: Nivesh (proxies NIDP screening engine)
**Auth**: Session
**DB queries**: 1 — single NIDP call to `/v1/stocks/scores/?top=5&profile=balanced`

**Request**:
```http
GET /api/recommendations/stocks?profile=balanced&top=5 HTTP/1.1
```

**Query params**:
- `profile` — `conservative | balanced | growth` (derived from user's risk_profile if omitted)
- `top` — int (default 5, max 20)
- `sector` — optional sector filter

**Response 200**:
```json
{
  "profile": "balanced",
  "items": [
    {
      "rank": 1,
      "symbol": "HDFCBANK",
      "name": "HDFC Bank",
      "sector": "Financials",
      "composite_score": 86,
      "scores": {
        "fundamentals": 92, "technicals": 78,
        "fundamentals_reason": "ROE 17% · low NPA",
        "technicals_reason": "Above 200-DMA"
      }
    }
  ],
  "compliance_note": "SEBI screened ideas — not buy advice. Review before investing."
}
```

---

### B.14 — `GET /api/recommendations/funds`

**Serves screens**: 13 Recommendations (top funds list)
**Service**: Nivesh (proxies NIDP `/v1/mf/scores/`)
**Auth**: Session
**DB queries**: 1

**Request**:
```http
GET /api/recommendations/funds?sleeve=equity&top=4 HTTP/1.1
```

**Query params**:
- `sleeve` — `equity | debt | hybrid | liquid`
- `top` — int (default 4)
- `category` — optional category filter (e.g. `flexi-cap`)

**Response 200**:
```json
{
  "sleeve": "equity",
  "items": [
    {
      "rank": 1,
      "isin": "INF...",
      "name": "Parag Parikh Flexi Cap",
      "category": "Flexi Cap",
      "composite_score": 91,
      "scores": {
        "returns": 96, "cost": 94, "consistency": 92
      }
    }
  ]
}
```

---

## Section C — Modified Endpoints

### C.1 — `GET /api/plans/active` — augment action shape

**Serves**: every dashboard that consumes `recommendations[]` + Plan Board (Screens 05–11, 16)
**Backward compat**: ✅ Additive. Existing clients ignore new fields.

**Before** (existing action shape — abridged):
```json
{
  "plan": {
    "actions": [
      {
        "action_id": "a_01H...",
        "type": "TRIM",
        "status": "PENDING",
        "priority": 1,
        "asset_type": "STOCK",
        "asset_name": "HDFC Banking ETF",
        "amount": 180000,
        "reason_text": "...",
        "reason_codes": ["SECTOR_CONCENTRATION"]
      }
    ]
  }
}
```

**After** (additive):
```json
{
  "plan": {
    "actions": [
      {
        "action_id": "a_01H...",
        "type": "TRIM",
        "status": "PENDING",
        "priority": 1,
        "asset_type": "STOCK",
        "asset_name": "HDFC Banking ETF",
        "amount": 180000,
        "reason_text": "...",
        "reason_codes": ["SECTOR_CONCENTRATION"],

        // NEW
        "verb": "TRIM",
        "priority_label": "Critical",
        "impact":  { "label": "Impact", "value": "+6 pts" },
        "effort": "LOW",
        "trade_off": "Realises 3.1K LTCG",
        "expected_impact": { "health_delta": 6 },
        "source_domain": "concentration",
        "exclusive": false,
        "scores": { "add": 12, "exit": 78, "hold": 22 },
        "switch_target": null
      }
    ]
  }
}
```

**Also: add filter query param** `?source_domain=concentration|diversification|risk|performance|goals|tax` — pushes domain filtering server-side (currently done client-side per V4 frontend).

---

### C.2 — `GET /api/insights/v3-portfolio` — collapse grade 7→4 server-side

**Serves**: 04 Chat Landing + every dashboard (via composite)
**Backward compat**: ⚠️ behaviour change. The `grade` field switches from 7-band ("A+","A","B+","B","C","D","F") to 4-band ("A","B","C","D"). For mobile-app compatibility, **add a new `grade_band` field**; keep `grade` returning 7-band until mobile-app migrates.

**Before**:
```json
{ "health": { "score": 86, "grade": "A+", "components": {...}, "partial_data": false } }
```

**After** (additive):
```json
{ "health": {
    "score": 86,
    "grade": "A+",        // 7-band (existing — unchanged)
    "grade_band": "A",    // NEW — 4-band per PRD §13.1
    "components": {...},
    "partial_data": false,
    "low_confidence": false
}}
```

**Also: add ETag header** `ETag: "sha1:<hash>"` for invalidation.

---

### C.3 — `GET /api/portfolio/risk-analytics` — add Max DD + VaR inline

**Serves**: 07 Risk dashboard
**Backward compat**: ✅ Additive.

**Before** (abridged):
```json
{
  "weighted_beta": 1.31,
  "weighted_volatility": 0.22,
  "weighted_sharpe": 0.71,
  "risk_drivers": [...]
}
```

**After** (additive):
```json
{
  "weighted_beta": 1.31,
  "weighted_volatility": 0.22,
  "weighted_sharpe": 0.71,
  "max_drawdown_pct": -29.0,   // NEW
  "var_1d_rs": 148000,          // NEW (computed inline, same as widget)
  "var_1d_pct": 8.0,            // NEW
  "portfolio_value_rs": 1840000,// NEW
  "var_confidence": 0.95,       // NEW
  "risk_drivers": [...]
}
```

**Note**: keeps `POST /api/copilot/widgets/portfolio_var` (chat widget). Dashboard reads from `risk-analytics` to avoid POST + chat-envelope overhead.

---

### C.4 — `GET /api/funds/{isin}/v3-score` — new user-scope endpoint (demotion of admin route)

**Serves**: 13 Recommendations (per-fund sub-scores)
**Backward compat**: ✅ Existing `/api/intelligence/v3-score/{id}` remains admin-only and unchanged. This is a NEW user-callable route.

**Request**:
```http
GET /api/funds/INF209KB17W5/v3-score HTTP/1.1
```

**Response 200**:
```json
{
  "isin": "INF209KB17W5",
  "name": "Parag Parikh Flexi Cap",
  "composite_score": 91,
  "scores": {
    "returns": 96,
    "cost": 94,
    "consistency": 92
  },
  "as_of": "2026-05-23"
}
```

---

### C.5 — `GET /api/portfolio/exposure/concentration` — add `top5_pct`, `caution_pct`

**Serves**: 05 Concentration (via composite)
**Backward compat**: ✅ Additive.

**After** (additive fields per lens):
```json
{
  "sector": {
    "items": [...],
    "hhi": 0.184,
    "hhi_x10000": 1840,    // NEW (already-scaled convenience)
    "effective_n": 8.2,
    "top5_pct": 48.0,      // NEW
    "caution_pct": 25,     // NEW (policy constant, may become risk-band-derived later)
    "hero_insight": {...}
  },
  ...
}
```

---

### C.6 — `GET /api/portfolio/exposure/fund-overlap/matrix` — add `unique_stocks_count`

**Serves**: 06 Diversification
**Backward compat**: ✅ Additive.

**After**:
```json
{
  "funds": [...],
  "pairs": [...],
  "max_pct": 78,
  "high_pairs": 3,
  "unique_stocks_count": 42   // NEW
}
```

---

### C.7 — `GET /api/portfolio/fund-performance` — add benchmark-alpha period

**Serves**: 08 Performance dashboard
**Backward compat**: ✅ Additive (existing `benchmark_name` = peer-avg unchanged; new fields added).

**After**:
```json
{
  "funds": [
    {
      "isin": "INF...",
      "name": "Nippon Smallcap",
      "alpha_1y_peer_pp": 8.2,        // EXISTING (peer-avg)
      "alpha_3y_benchmark_pp": 8.2,   // NEW (vs SEBI benchmark index)
      "benchmark_index": "Nifty Smallcap 250 TRI",  // NEW
      "as_of": "2026-05-23"
    }
  ]
}
```

**Also**: add `?period=1y|3y|5y&benchmark=peer|index` query params (default `period=1y&benchmark=peer` for backward compat).

---

### C.8 — `POST /api/portfolio-builder/generate` — accept full slider input

**Serves**: 12 Portfolio Builder
**Backward compat**: ⚠️ Additive request fields; existing callers passing only `{monthly_sip_rs, lumpsum_rs}` still work (other fields default).

**Before**:
```json
{ "monthly_sip_rs": 40000, "lumpsum_rs": 0 }
```

**After** (additive):
```json
{
  "monthly_sip_rs": 40000,
  "lumpsum_rs": 0,
  "monthly_surplus_rs": 40000,    // NEW (slider; if absent, defaults to monthly_sip_rs)
  "horizon_years": 11,             // NEW (slider; if absent, defaults to None = profile-derived)
  "risk_bucket": "moderate"        // NEW (slider; if absent, defaults to user.risk_profile)
}
```

**Response**: extended to include per-instrument `cap_pct`:

```json
{
  "sleeves": [
    {
      "kind": "equity",
      "pct": 60.0,
      "monthly_rs": 24000,
      "items": [
        {
          "isin": "INF...",
          "name": "Parag Parikh Flexi Cap",
          "monthly_rs": 5000,
          "pct_of_sleeve": 20.8,
          "cap_pct": 35.0          // NEW (per-instrument cap; client uses for guardrail)
        }
      ]
    }
  ]
}
```

---

### C.9 — `GET /api/portfolio/sips` — add mandate / bounce / step-up fields

**Serves**: 17 SIP Board (per-client SIP rows)
**Backward compat**: ✅ Additive.

**After** (additive fields per SIP):
```json
{
  "sips": [
    {
      "sip_id": "s_01H...",
      "fund_name": "Parag Parikh Flexi Cap",
      "amount_rs": 15000,
      "cadence": "MONTHLY",

      // NEW
      "state": "failed",                    // failed|expiring|step_up|healthy
      "mandate_id": "m_01H...",
      "mandate_expiry_date": "2027-04-30",
      "last_bounce_reason": "INSUFFICIENT_BALANCE",
      "last_bounce_date": "2026-05-02",
      "cycles_missed": 2,
      "next_debit_date": "2026-06-02",
      "proposed_stepup_pct": null
    }
  ]
}
```

---

### C.10 — `GET /api/mfd/profiles` — add health/last-seen/band

**Serves**: 15 Advisor Book (per-client row)
**Backward compat**: ✅ Additive.

**After** (additive fields per profile):
```json
{
  "profiles": [
    {
      "profile_id": "p_01H...",
      "name": "Rohan Mehta",
      "aum_rs": 18000000,
      "priority_score": 0.91,

      // NEW
      "health_score": 62,
      "health_grade": "C",
      "last_seen_days": 14,
      "band": "needs_attention",      // needs_attention | review_soon | healthy
      "top_issue_label": "Goal at risk · child education 74%"
    }
  ]
}
```

---

## Section D — Deprecations

| Endpoint | Field/Path | Replaced By | Deprecation Date | Removal Date |
|---|---|---|---|---|
| `POST /api/copilot/widgets/tax_timing` | Duplicate route registration (lines 1507 & 1663 of copilot_widgets.py) | First registration — delete the dead one | v4 release | v4 release |
| `POST /api/copilot/widgets/tax_harvest` | `ltcg_limit_rs = 100_000` constant | New constant `125_000` per Jul-2024 tax law | v4 release | v4 release |
| HOLD action status writer | writes lowercase `"pending"` | Uppercase `"PENDING"` to pass validator | v4 release | v4 release |
| FLAG action path | uses `id` field instead of `action_id` | Normalise to `action_id` | v4 release | v5 release |
| `GET /api/intelligence/v3-score/{id}` | Admin-only despite being natural user route | New user-scope `GET /api/funds/{isin}/v3-score` (C.4) | v4 release | n/a — admin path retained for admin users |
| Insights screen Mockup §02 | Password sign-in + OTP login tiles | Google-only per D4 decision | v4 release | n/a (never built) |
| Insights screen Mockup §03 | Broker-connect tile | Dropped per B2 decision | v4 release | n/a (never built) |

---

## Section E — Web vs Mobile Handling

Per gap analysis Finding C.7 — **no API divergence**. Both prototypes share 99% of element IDs; mobile only adds UI-only IDs (`tabbar`, `al-sleevebadge`).

**Recommendation**: Single endpoint set, no `view=` query param needed. Responsive rendering on the client.

| Screen | Web | Mobile | Handling |
|---|---|---|---|
| 04 Chat Landing | Health ring + 3 insights + top rec + chips + chat bar | Same content | Identical response |
| 05–10 Dashboards | Three-section layout, side-by-side stats | Three-section layout, stacked stats | Identical response |
| 11 Plan Board | Hero ring + 3 columns (To-do/Done/Skip) | Hero ring + stacked columns | Identical response |
| 12 Builder | 3 horizontal slider rows + alloc bar | 3 stacked slider rows + alloc bar | Identical response |
| 14 Alloc | Per-instrument inline editor | Per-instrument editor with sleeve badge | Identical response (mobile shows sleeve badge from context) |
| 15-17 Advisor | Wider layouts | Stacked | Identical response |

---

## Section F — Updated Postman Collection

**File**: `docs/v4-designs/nivesh-postman-collection.v2.json`
**Diff summary**:
- **14 new endpoints** added (B.1 – B.14)
- **10 endpoints modified** (C.1 – C.10) — additive shape changes; request examples updated
- **2 routes deprecated** (`/copilot/widgets/tax_timing` dead registration; mockup login tiles)

The v2 collection is structurally identical to v1 — same auth setup, same variables (`{{BASE_URL}}`, `{{SESSION_TOKEN}}`), same folder structure. New endpoints are added under existing folder groups where logical (e.g. `B.1` under a new `dashboards` folder; `B.7` under `advisor`; `C.1–C.9` updated under their existing folders).

---

## Section G — Implementation Order

Recommended sequence for Phase 3. Group by dependency: schema first, aggregators last. Effort sizing: **S** = 0.5 day, **M** = 1–2 days, **L** = 3+ days.

| # | Item | Effort | Primary risk | Depends on |
|---|---|---|---|---|
| 1 | **Recommendation schema augmentation (C.1)** — add `verb`, `priority_label`, `impact`, `effort`, `trade_off`, `expected_impact`, `source_domain`, `exclusive`, `scores`, `switch_target` to action_plan_manager; rewrite serialiser | M | Action shape touched by 8 producers; need full backfill of `trade_off`, `effort`, `expected_impact` defaults for legacy actions. | none — blocks every dashboard composite |
| 2 | **Tax + Goals action writers (Decision 6)** — extend snapshot-activation pipeline to emit tax + goals actions into `plan_actions` table | M | Goal-engine actions are mutually exclusive; needs `exclusive=true` + Plan Board mutual-exclusion logic. | (1) |
| 3 | **Modified `GET /api/plans/active`** — new fields populated + `?source_domain=` filter + HOLD status uppercase fix + FLAG `id`→`action_id` normalisation | S | HOLD/FLAG fixes are non-additive — coordinate with mobile-app release. | (1) |
| 4 | **`GET /api/insights/v3-portfolio` grade collapse (C.2)** — add `grade_band` field + ETag | S | Keep 7-band `grade` for backward compat. | none |
| 5 | **6× `GET /api/dashboards/{type}` composite (B.1)** — implement one (concentration) end-to-end, verify pattern, then template the other 5 | L | Composite contract used by V4 frontend; bugs cascade across 6 screens. Implement one, pause for review, then rest. | (1), (3), (4) |
| 6 | **`GET /api/portfolio/risk-analytics` additions (C.3)** — Max DD + VaR inline | S | VaR computation already exists in `copilot_widgets.py` — extract into shared service. | none |
| 7 | **`GET /api/portfolio/tax-summary` (B.12)** — promotion of widget to dashboard endpoint, with ₹1.25L fix | S | Patch the stale ₹1L constant. | none |
| 8 | **`GET /api/portfolio/exposure/*` additions (C.5, C.6)** — `top5_pct`, `caution_pct`, `unique_stocks_count` | S | Pure additive. | none |
| 9 | **`GET /api/portfolio/fund-performance` (C.7)** — benchmark-alpha period | M | Needs SEBI benchmark index mapping per category — may require NIDP enhancement. | none |
| 10 | **`POST /api/plans/active/actions` (B.10)** — cross-domain action create | S | Idempotency-Key required to avoid duplicates from accept-spam. | (1), (3) |
| 11 | **`PATCH /api/plans/{pid}/actions/{aid}/discuss` (B.11)** — advisor Discuss-only write | S | Per PRD §10.2 — MUST NOT change status; enforce in handler. | (1), (3) |
| 12 | **`GET /api/funds/{isin}/v3-score` (C.4)** — user-scope fund score | S | Just lifts admin gate; same underlying service. | none |
| 12b | **`switch_score` + `switch_target` computation (Decision 2)** — Nivesh-side helper combining NIDP exit_score with category-top-peer lookup | M | New algorithm; category-match guard + cost-leak special case; cache per-ISIN 24h. | (12) |
| 13 | **`GET /api/recommendations/stocks` (B.13) + `…/funds` (B.14)** — NIDP proxy for top picks | M | Needs `?profile=` derivation from user risk_profile. | none |
| 14 | **`GET /api/portfolio-builder/generate` extensions (C.8)** — full slider input + per-instrument `cap_pct` | M | Existing handler accepts only 2 fields; needs careful additive defaults. | none |
| 15 | **`GET /api/portfolio/sips` extensions (C.9)** — mandate / bounce / state | M | Some fields require new ingestion from mandate provider (BSE Star/MFU). For v4: stub `mandate_id`, surface what we have. | none |
| 16 | **`GET /api/intelligence/portfolio/360` (B.2)** — Client 360 6-domain rollup | M | 4-source composition; needs caching to stay ≤3 queries. | (4) |
| 17 | **`GET /api/mfd/profiles` additions (C.10)** — health/last-seen/band per profile | M | `last_seen_days` requires advisor-activity tracking — may need new table. | none |
| 18 | **`GET /api/mfd/profiles/{id}/needs-attention` (B.3)** | S | Joins plan_actions + insights + tax-summary candidates. | (16), (17) |
| 19 | **`GET /api/advisor/summary` (B.6)** + **`GET /api/advisor/sip-board[/summary]` (B.7, B.8)** | M | Two aggregations; SIP-board requires (C.9) state field. | (15), (17) |
| 20 | **`POST /api/mfd/profiles/{id}/sip-nudge` (B.9)** + **`POST /api/mfd/profiles/{id}/call-log` (B.5)** | S | Template-based; no LLM in critical path. | (17) |
| 21 | **`POST /api/mfd/profiles/{id}/review-pack/generate` (B.4)** — PDF generation | M | Async task; existing PDF infra (`portfolio-builder/export.pdf` pattern) reusable. | (16), (18) |

**Total estimated effort**: ~24–32 dev days for one engineer. Cuts to ~12–16 days with 2 engineers (frontend + backend) working in parallel.

**Pattern-confirmation pause** (per the brief): after item (5) "implement Concentration composite end-to-end", pause for diff review before continuing the other 5 dashboards.

---

## Section H — Open Questions Resolved Since Gap Analysis

| # | Question | Answer | Source |
|---|---|---|---|
| Q1 | NIDP vs Nivesh boundary | All new v4 endpoints live on Nivesh; NIDP unchanged | Decision 3 |
| Q2 | Recommendation generation timing | Pre-computed at snapshot activation; cached | Decision 6 + PRD §4.3 |
| Q3 | Health score single source | Nivesh engine, NIDP primitives; ETag for invalidation | Decision 5 |
| Q4 | Chat backend / LLM provider | Existing `/api/copilot/agents/*` framework — no change | Carried forward (non-blocking) |
| Q5 | Plan persistence model | Versioned (`/api/plans/history` + single `active`) — existing | Confirmed |
| Q6 | Advisor permissioning | Read-only on client state; Discuss-only writes | Decision 4 + PRD §10.2 |
| Q7 | **SIP execution path** | **Deferred** — Builder = save-plan-only, SIP Board = nudge-only, no Retry | **B1 decision (approved)** |
| Q8 | **Broker connect scope** | **Dropped from v4** — Gmail CAS + Upload CAS + Manual only | **B2 decision (approved)** |
| Q9 | CAS sync/async | Async via `task_id` — existing | Confirmed |
| Q10 | Concentration `caution_pct` source | Policy constant `25` exposed in dashboard composite; risk-band derivation future enhancement | Decision 1 |
| Q11 | NIDP connection indicator | Surface real staleness via `/v1/intelligence/portfolio/sync/status` | C.3 (not in v4 scope; can be deferred) |
| Q12 | Tax expiry timer | FY-end based; `days_to_fy_end` + per-lot `eligible_after_date` exposed | B.12 |
| Q13 | Insight "Needs-info" variant | Add `insight.state` field — deferred to Phase 4 (out of v4 scope) | Carried forward |
| Q14 | Per-action `verb` vocabulary | Encoded in `verb` field per asset_type | Decision 2 |
| Q15 | Plan Board back-link | `source_domain` field carries it | Decision 2 |

### Questions still open (none block Phase 3)

- **Insight "Needs-info" variant routing** — additive future field; doesn't block any v4 screen rendering data we already have.
- **Concentration caution_pct per risk band** — policy constant for v4; future per-risk-band override.
- **Mobile app migration timeline for 4-band grade** — kept 7-band `grade` field; mobile migrates at its own pace.

---

## Section I — Phase Gate

**Status**: ✅ **Phase 2 complete**
**Awaiting**: Approval to proceed to Phase 3 (Implementation)

**Critical reviews requested before code is written**:

1. **Recommendation schema (Decision 2)** — this shape is touched by 8 producer paths and 9+ consumer screens. Sanity-check the field list, especially `expected_impact` field names (the dashboard ③ Apply animations bind directly to these names).

2. **Dashboard composite contract (B.1)** — the response envelope is the prototype-fidelity contract for v4. Confirm field naming (`stat_tiles[]` vs `metrics{}`, `breakdown.items[]` vs `breakdown.bars[]`, etc.) before all 6 dashboards are templated.

3. **Tax + Goals action writers (Decision 6 + implementation step 2)** — the biggest schema decision. Confirm that goal-engine recommendations (`sip_increase`, `lumpsum_topup`, `horizon_extension`) should be written into `plan_actions` with `exclusive=true` rather than kept in a separate `goal_actions` table. The choice affects how Plan Board renders mutual exclusion and how `expected_impact.funding_pp` reconciles.

4. **`switch_score` algorithm (Decision 2)** — Option A (Nivesh-side composition from NIDP primitives) is chosen for v4 speed. Confirm the formula `switch_score = exit_score × (1 + replacement_advantage_pp/100)` and the three guard cases (category-match, top-peer staleness 24h cache, cost-leak special case = direct plan of same fund). If preferred, switch to Option B (new NIDP route) before Phase 3.

**Side fixes to ship independently of v4** (recap from gap analysis Section F):
1. `tax_timing` duplicate registration — delete dead one
2. `tax_harvest` ₹1L → ₹1.25L LTCG constant
3. HOLD action status lowercase bug
4. FLAG action `id` → `action_id`
5. `/api/intelligence/v3-score/{id}` admin-gate review

**Phase 2 ends here. STOP. Await explicit approval before Phase 3.**
