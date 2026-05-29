# PR: Adapt Backend APIs to Nivesh v4 Designs

## Summary
[1–2 sentences: what changed and why.]

## Phase Gate Approvals
- ✅ Phase 1 (Gap Analysis) approved on [date]
- ✅ Phase 2 (Design Proposal) approved on [date]
- ✅ Phase 3 (Implementation) — see commits below

## Screen → Endpoint Coverage Map

| # | Screen | Endpoints Serving It | Tests |
|---|---|---|---|
| 01 | Homepage | (none — UI only) | — |
| 02 | Login | POST /auth/login (unchanged) | existing |
| 03 | Onboarding | POST /import/cas/gmail (new), POST /import/cas/upload (new), POST /import/broker/{name}/connect (new) | ✅ |
| 04 | Chat Landing | GET /portfolio/health (new), GET /portfolio/insights (new), POST /chat/messages (new) | ✅ |
| 05–10 | Dashboards | GET /dashboards/{type} (new) | ✅ |
| 11 | Plan Board | GET /plan-board/items, POST /plan-board/items, PATCH /plan-board/items/{id} (all new) | ✅ |
| 12 | Portfolio Builder | POST /builder/allocate, POST /sips/register (new) | ✅ |
| 13 | Recommendations | GET /recommendations/stocks, GET /recommendations/funds (new) | ✅ |
| 14 | Instrument Allocation | GET/PATCH /builder/sleeves/{sleeve} (new) | ✅ |
| 15 | Advisor Book | GET /advisor/book/summary, GET /advisor/clients (new) | ✅ |
| 16 | Client 360 | GET /advisor/clients/{id} (new) + reuses dashboard endpoints with advisor scope | ✅ |
| 17 | SIP Board | GET /advisor/sips/summary, GET /advisor/sips, POST /advisor/sips/{id}/message (new) | ✅ |

## Files Changed
- [N] new endpoint files in `src/api/...`
- [N] modified endpoint files
- Updated OpenAPI spec / Postman collection
- [N] new integration test files

## Test Results
- Full suite: [N passed / N failed]
- New tests added: [N]
- Coverage: [%] (was [%])

## Backward Compatibility
- ✅ No breaking changes to existing endpoints
- Deprecations: [list with sunset dates]

## Performance
- New endpoints profiled; all under [Nms] p95
- Max DB queries per endpoint: [N] (budget: 3)

## Risks and Follow-Ups
- [Any known limitations]
- [Open questions not resolved — link to issue tracker]