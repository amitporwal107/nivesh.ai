# Unwired Endpoints Investigation

33 API endpoints have V5 adapters + hooks written but NO V5 page wires them.

**Date:** 2026-05-28
**Investigator:** Claude Code
**Method:** Searched `/app/backend/routes/`, `/app/frontend/src/` (V2/V3/V4), `/app/frontend-v5/src/pages/`, admin routes, and prototype designs.

## Summary

| Category   | Count | Backend routes | V2/V4 usage | V5 adapter + hook | V5 page wired |
|------------|-------|----------------|-------------|-------------------|---------------|
| Scenarios  | 10    | All 10 exist   | 10/10       | Yes               | 0/10          |
| Advisor    | 7     | All 7 exist    | 4/7         | Yes               | 0/7           |
| MFD        | 16    | All 16 exist   | 11/16       | Yes               | 0/16          |

## V5 State

- **Adapters:** `scenarios.adapter.ts`, `advisor.adapter.ts`, `mfd.adapter.ts` -- all written with Zod validation
- **Hooks:** `use-scenarios.ts`, `use-advisor.ts`, `use-mfd.ts` -- all written with React Query
- **Pages:** Zero imports of any of these hooks in `/app/frontend-v5/src/pages/`
- **Routes:** No `/advisor`, `/scenarios`, `/mfd`, or `/clients` routes in `routes.tsx`
- **Prototype:** Design files include screens for Advisor Book (screen 15), Client 360 (screen 16), SIP Board (screen 17/18) in `screens-advisor.jsx` and `screens-advisor-2.jsx`

## V3 Redesign Backlog Status

Per `project_v3_redesign_backlog.md` (2026-05-22):
- **V3-005 Stress Test** (uses scenarios): DEFERRED
- **V3-006 Advisor MFD reframe**: DEFERRED
- **V3-014 Client Snapshot**: DEFERRED (Iteration 4, 10h estimate)

## Full Endpoint Table

| # | Endpoint | Backend exists? | V2/V4 uses it? | Admin uses it? | V5 disposition | Notes |
|---|----------|----------------|----------------|----------------|----------------|-------|
| **Scenarios** | | | | | | |
| 1 | `GET /api/scenarios/suggest` | Yes (`routes/scenarios.py` L166) | Yes -- `V2ScenarioSimScreen.jsx`, `AICopilotView.jsx` | No | WIRE | Core scenario engine. V5 Plan or Risk page should surface scenario cards. Hooks ready (`useScenarioSuggestions`). |
| 2 | `POST /api/scenarios/simulate` | Yes (`routes/scenarios.py` L345) | Yes -- `V2ScenarioSimScreen.jsx`, `AICopilotView.jsx` | No | WIRE | What-if simulation with before/after metrics. Central to the rebalancing UX. Hook ready (`useScenarioSimulate`). |
| 3 | `POST /api/scenarios/rebalance-plan` | Yes (`routes/scenarios.py` L472) | Yes -- `AICopilotView.jsx` (L135, L161) | No | WIRE | Generates step-by-step buy/sell actions. Used after simulate. Hook ready (`useScenarioRebalancePlan`). |
| 4 | `POST /api/scenarios/save` | Yes (`routes/scenarios.py` L605) | Yes -- `AICopilotView.jsx` (L182) | No | WIRE | Persists a named scenario. Part of the simulate-then-save flow. |
| 5 | `GET /api/scenarios/saved` | Yes (`routes/scenarios.py` L623) | Yes -- `AICopilotView.jsx` (L64) | No | WIRE | Lists user's saved scenarios. Needed for the scenario management panel. Hook ready (`useSavedScenarios`). |
| 6 | `DELETE /api/scenarios/saved/{id}` | Yes (`routes/scenarios.py` L632) | Yes -- `AICopilotView.jsx` (L203) | No | WIRE | Delete a saved scenario. Part of scenario management. |
| 7 | `POST /api/scenarios/apply` | Yes (`routes/scenarios.py` L645) | Yes -- `AICopilotView.jsx` (L139) | No | WIRE | Creates pending rebalance plan from scenario actions. Hook ready (`useApplyScenario`). |
| 8 | `GET /api/scenarios/pending` | Yes (`routes/scenarios.py` L668) | Yes -- `AICopilotView.jsx` (L73) | No | WIRE | Lists pending rebalance plans (badge: "3 pending actions"). Hook ready (`usePendingPlans`). |
| 9 | `DELETE /api/scenarios/pending/{planId}` | Yes (`routes/scenarios.py` L677) | Yes -- `AICopilotView.jsx` (L221) | No | WIRE | Cancel a pending plan. |
| 10 | `POST /api/scenarios/pending/{planId}/complete` | Yes (`routes/scenarios.py` L684) | Yes -- `AICopilotView.jsx` (L231) | No | WIRE | Mark plan as executed. |
| **Advisor** | | | | | | |
| 11 | `GET /api/advisor/today` | Yes (`routes/advisor.py` L74) | Yes -- `AdvisorHomeView.jsx` (L40) | No | DEFER | Advisor Home card: top-10 high-priority clients. MFD-persona only. V5 has no advisor route yet; prototype has screen 15 design. |
| 12 | `GET /api/advisor/aum` | Yes (`routes/advisor.py` L136) | Yes -- `AdvisorHomeView.jsx` (L41) | No | DEFER | Advisor Home card: clients ranked by AUM. MFD-persona only. |
| 13 | `GET /api/advisor/underperformers` | Yes (`routes/advisor.py` L239) | Yes -- `AdvisorHomeView.jsx` (L42, L86) | No | DEFER | Advisor Home card: clients lagging benchmark. MFD-persona only. |
| 14 | `GET /api/advisor/rebalance` | Yes (`routes/advisor.py` L377) | Yes -- `AdvisorHomeView.jsx` (L43) | No | DEFER | Advisor Home card: clients off target allocation. MFD-persona only. |
| 15 | `GET /api/advisor/summary` | Yes (`routes/advisor_v4.py` L69) | No -- V4 endpoint, not yet used by any frontend | No | DEFER | V4 advisor book KPI rollup. New endpoint (screen 15). Prototype designed but no V2/V4 caller yet. |
| 16 | `GET /api/advisor/sip-board` | Yes (`routes/advisor_v4.py` L116) | No -- V4 endpoint, not yet used by any frontend | No | DEFER | V4 SIP Board queue (screen 17). Prototype designed but no V2/V4 caller yet. |
| 17 | `GET /api/advisor/sip-board/summary` | Yes (`routes/advisor_v4.py` L199) | No -- V4 endpoint, not yet used by any frontend | No | DEFER | V4 SIP Board aggregate stats (screen 17). Prototype designed but no V2/V4 caller yet. |
| **MFD (workspace + profiles)** | | | | | | |
| 18 | `GET /api/mfd/workspace` | Yes (`routes/mfd.py` L237) | Yes -- `Dashboard.js`, `NiveshV2.jsx`, `Chat.jsx`, `OnboardingView.js` | No | DEFER | Detects workspace mode (INDIVIDUAL vs ADVISORY). Required for advisor gating. |
| 19 | `PATCH /api/mfd/workspace` | Yes (`routes/mfd.py` L244) | Yes -- `MfdDashboard.jsx`, `MfdOnboardingWizard.jsx`, V3 `Onboarding.jsx` | No | DEFER | Switches workspace mode; sets firm name / ARN. MFD onboarding. |
| 20 | `GET /api/mfd/profiles` | Yes (`routes/mfd.py` L269) | Yes -- `MfdDashboard.jsx`, `Dashboard.js`, `NiveshV2.jsx` | No | DEFER | Lists all client profiles with priority scores. Core MFD surface. |
| 21 | `POST /api/mfd/profiles` | Yes (`routes/mfd.py` L292) | Yes -- `MfdOnboardingWizard.jsx`, `AddClientDialog.jsx`, V3 `Onboarding.jsx` | No | DEFER | Creates a new client profile. MFD onboarding + add-client flow. |
| 22 | `GET /api/mfd/profiles/{id}` | Yes (`routes/mfd.py` L327) | Implicit -- V2 fetches via list, not individual GET | No | DEFER | Single profile detail with priority hydration. |
| 23 | `PATCH /api/mfd/profiles/{id}` | Yes (`routes/mfd.py` L334) | Yes -- `MfdOnboardingWizard.jsx` (L268) | No | DEFER | Update client name/AUM/tags/contacts. |
| 24 | `DELETE /api/mfd/profiles/{id}` | Yes (`routes/mfd.py` L361) | Yes -- `MfdDashboard.jsx` (L294) | No | DEFER | Delete a client profile. |
| 25 | `POST /api/mfd/profiles/{id}/activate` | Yes (`routes/mfd.py` L374) | Yes -- `MfdDashboard.jsx`, `MfdOnboardingWizard.jsx`, V3 `Onboarding.jsx` | No | DEFER | Impersonate a client (session-scoped). Core MFD flow. |
| 26 | `POST /api/mfd/profiles/deactivate` | Yes (`routes/mfd.py` L385) | Yes -- `MfdOnboardingWizard.jsx`, `Dashboard.js`, `NiveshV2.jsx` | No | DEFER | Stop impersonation, return to advisor's own view. |
| 27 | `GET /api/mfd/profiles/{id}/notes` | Yes (`routes/mfd.py` L429) | Yes -- `ClientSnapshot.jsx` (L563) | No | DEFER | Get advisor notes for a client. |
| 28 | `PUT /api/mfd/profiles/{id}/notes` | Yes (`routes/mfd.py` L439) | Yes -- `ClientSnapshot.jsx` (L645) | No | DEFER | Save/update advisor notes for a client. |
| 29 | `GET /api/mfd/profiles/{id}/tax-summary` | Yes (`routes/mfd.py` L530) | Yes -- `ClientSnapshot.jsx` (L564) | No | DEFER | Per-client tax summary with FIFO lot-level coverage. Rich endpoint. |
| 30 | `GET /api/mfd/profiles/{id}/portfolio-trend` | Yes (`routes/mfd.py` L930) | Yes -- `ClientSnapshot.jsx` (L562) | No | DEFER | Per-client invested vs current trend + recent buys. |
| 31 | `GET /api/mfd/profiles/{id}/needs-attention` | Yes (`routes/advisor_v4.py` L253) | No -- V4 endpoint, not yet used by V2/V4 frontend | No | DEFER | V4 per-client action items (screen 16 Client 360). Hook ready (`useNeedsAttention`). |
| 32 | `POST /api/mfd/profiles/{id}/call-log` | Yes (`routes/advisor_v4.py` L301) | No -- V4 endpoint, not yet used by V2/V4 frontend | No | DEFER | V4 call logging for advisor CRM (screen 16). Hook ready (`useLogCall`). |
| 33 | `POST /api/mfd/profiles/{id}/sip-nudge` | Yes (`routes/advisor_v4.py` L342) | No -- V4 endpoint, not yet used by V2/V4 frontend | No | DEFER | V4 SIP nudge messaging (screen 17). Hook ready (`useSipNudge`). |

## Disposition Summary

| Disposition | Count | Endpoints |
|-------------|-------|-----------|
| **WIRE**    | 10    | All 10 scenario endpoints (#1-#10) |
| **DEFER**   | 23    | All 7 advisor endpoints (#11-#17) + all 16 MFD endpoints (#18-#33) |
| V2_ONLY     | 0     | None -- all endpoints are relevant to V5 long-term |
| DEAD        | 0     | None -- every endpoint has at least a V2 caller or a designed V4/prototype screen |

## Rationale

### WIRE (Scenarios, 10 endpoints)

The scenario engine is **the core rebalancing UX** for retail users. V2's `AICopilotView.jsx` already uses all 10 endpoints in a fully functional flow: suggest -> simulate -> rebalance-plan -> apply -> pending management. V5 already has a `/plan` route and a Risk page with "Stress scenarios" placeholder text. These should be wired into V5's Plan or a dedicated Scenarios page. The hooks and adapters are complete and tested.

### DEFER (Advisor + MFD, 23 endpoints)

These are **advisor-persona features** (MFD = Mutual Fund Distributor). V5 currently serves the retail persona only:
- No `/advisor` or `/clients` route exists
- The V3 redesign backlog explicitly deferred V3-006 (Advisor MFD reframe) and V3-014 (Client Snapshot)
- The prototype designs exist (screens 15-18) but production has no advisor routes
- V4 endpoints (#15-17, #31-33) are brand new -- not even used by V2/V4 frontend yet

The MFD workspace + profile CRUD (#18-26) is the **prerequisite** for all advisor features. These should be wired as a cohesive Advisor module when the team decides to ship the advisor persona in V5.

### No DEAD or V2_ONLY endpoints

Every endpoint either has active V2 callers (scenarios, MFD workspace/profiles, advisor home cards) or is a freshly built V4 endpoint designed for prototype screens that have not yet shipped in any frontend. None are obsolete.

## Recommended Next Steps

1. **Immediate:** Wire scenarios (#1-#10) into V5's Plan page or create a `/scenarios` route. The hooks (`use-scenarios.ts`) are ready. This gives retail users the what-if + rebalancing flow.

2. **When advisor persona ships:** Build an `/advisor` route hierarchy wiring #11-#17 (book/AUM/SIP board) and `/clients/:id` for #18-#33 (MFD profile management + client 360). The prototype designs in `screens-advisor.jsx` and `screens-advisor-2.jsx` provide the visual spec.

3. **V4-only endpoints (#15-17, #31-33):** These have backend routes but zero frontend callers anywhere. They were built for the V4 mobile spec (api-changes.md B.2-B.9). Consider wiring them directly in V5 rather than adding them to V2/V4 first.
