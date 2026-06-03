# PR: Nivesh v4 API Adaptation — Phase 3 & 4 Complete

## Summary

Adapts the Nivesh backend to serve all 17 v4 screens across mobile and webapp.
14 new endpoints + 10 modified endpoints per `docs/api-changes.md`.

All changes are **additive** — no existing endpoints were modified in a breaking way.

## Screen → Endpoint Mapping

| Screen | Mobile | Web | Primary Endpoint(s) |
|--------|--------|-----|---------------------|
| 01 Homepage | ✓ | ✓ | `GET /api/insights/v3-portfolio` (+ ETag) |
| 02 Health Score | ✓ | ✓ | `GET /api/insights/v3-portfolio` |
| 03 Plan Board | ✓ | ✓ | `GET /api/plans/active?source_domain=` |
| 04 Concentration | ✓ | ✓ | `GET /api/dashboards/concentration` |
| 05 Diversification | ✓ | ✓ | `GET /api/dashboards/diversification` |
| 06 Risk | ✓ | ✓ | `GET /api/dashboards/risk` |
| 07 Recommendations | ✓ | ✓ | `GET /api/recommendations/stocks`, `/funds` |
| 08 Goals | ✓ | ✓ | `GET /api/dashboards/goals` |
| 09 Tax | ✓ | ✓ | `GET /api/dashboards/tax` |
| 10 Performance | ✓ | ✓ | `GET /api/dashboards/performance`, `GET /api/portfolio/fund-performance?period=&benchmark=` |
| 11 Action Detail | ✓ | ✓ | `GET /api/plans/active` (augmented action schema) |
| 12 Intelligence 360 | ✓ | ✓ | `GET /api/intelligence/portfolio/360` |
| 13 SIP Board (investor) | ✓ | ✓ | `GET /api/portfolio/sips` (+ v4 state/mandate fields) |
| 14 Portfolio Builder | ✓ | ✓ | `POST /api/portfolio-builder/generate` (+ horizon_years, risk_bucket) |
| 15 Advisor Book | — | ✓ | `GET /api/advisor/summary` |
| 16 Client 360 (advisor) | — | ✓ | `GET /api/mfd/profiles/{id}/needs-attention`, `GET /api/intelligence/portfolio/360`, `POST /api/mfd/profiles/{id}/review-pack/generate` |
| 17 SIP Board (advisor) | — | ✓ | `GET /api/advisor/sip-board`, `GET /api/advisor/sip-board/summary` |

## New Files

| File | Purpose |
|------|---------|
| `backend/routes/dashboards.py` | 6-domain composite (B.1) — screens 04–09 |
| `backend/routes/recommendations.py` | Screened ideas (B.10, B.11) — screen 07 |
| `backend/routes/advisor_v4.py` | Advisor/MFD/Intelligence (B.2–B.9) — screens 12, 15–17 |
| `backend/services/snapshot_action_writers.py` | Tax + Goals actions on activation (Decision 6) |
| `backend/services/switch_score.py` | Nivesh-side switch_score (Option A, 24h cache) |
| `backend/services/action_recommendation_schema.py` | v4 action augmentor (verb, effort, source_domain…) |
| `backend/tests/test_v4_endpoints.py` | Integration tests — NSDL ECAS fixture + aporwal107 session |

## Modified Files

| File | Change |
|------|--------|
| `backend/routes/analytics.py` | C.7: `?period=` and `?benchmark=` on fund-performance |
| `backend/routes/portfolio_builder.py` | C.8: `monthly_surplus_rs`, `horizon_years`, `risk_bucket` |
| `backend/routes/cas_transactions.py` | C.9: v4 SIP state/mandate/bounce fields |
| `backend/routes/cas_snapshots.py` | Post-activation action writers hook (Decision 6) |
| `backend/routes/insights.py` | ETag on v3-portfolio (Plan Board cache invalidation) |
| `backend/routes/plans.py` | `?source_domain=` server-side filter |
| `backend/routes/copilot_widgets.py` | LTCG ₹1.25L fix + duplicate route removed |
| `backend/services/pi_bridge.py` | Fix: uses PI_POSTGRES_URL (wrong pool → Grade F bug) |
| `backend/server.py` | Register dashboards_router, recommendations_router, advisor_v4_router |

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Dashboard shape | `GET /api/dashboards/{type}` composite | Single fetch per screen, ≤3 DB queries |
| Recommendation schema | Additive — 10 new fields | No breaking changes to mobile/V3 clients |
| Tax+Goals writers | Fire-and-forget on snapshot activation | Plan Board pre-populated without extra navigation |
| switch_score | Option A: Nivesh-side, `exit_score × (1 + advantage_pp/100)` | NIDP owns primitives; Nivesh owns action scoring |
| Goals exclusivity | `exclusive: true` on all Goals actions | PRD §7.4 — mutually exclusive funding paths |

## Test Coverage

```bash
cd backend
pytest tests/test_v4_endpoints.py -v
# Uses aporwal107@gmail.com session + sdk_real_nsdl_full.json NSDL ECAS fixture
```

11 test functions covering:
- NSDL ECAS fixture schema validation (60 demat lines, 52 MF schemes)
- All 6 dashboard types (non-500 assertion)
- Dashboard envelope shape (stat_tiles, breakdown, recommendations, projection)
- Recommendations compliance_note (SEBI regime)
- Fund performance period/benchmark params
- SIP v4 state/mandate fields
- ETag on v3-portfolio (body + header)
- Plan source_domain filter
- switch_score unit tests (formula, 3 guard cases)
- LTCG ₹1.25L constant

## Breaking Changes

None. All changes additive.
