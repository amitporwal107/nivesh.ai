# API_DOCUMENTATION.md — Nivesh.ai / NIDP

> Canonical detail: `TECHNICAL_ARCHITECTURE.md` §9 (DaaS), §10 (Nivesh App).
> Live specs (the real contract): Nivesh `https://niveshcopilot.com/api/docs`,
> DaaS `https://data.niveshcopilot.com/daas/docs` (OpenAPI 3.1). If code and this doc
> disagree, the OpenAPI/code wins — fix the doc.

## Two APIs
| API | Base | Auth | Scale |
|---|---|---|---|
| Nivesh App | `https://niveshcopilot.com/api` | Google OAuth 2.0 + session cookie; admin `Bearer <ADMIN_TOKEN>` | 180+ endpoints |
| NIDP DaaS | `https://data.niveshcopilot.com/daas` | `X-API-Key: nvd_…` or `Bearer nvd_…`; admin `Bearer <NIDP_DAAS_INTERNAL_TOKEN>` | external, key-gated |
| NIDP Query | `https://data.niveshcopilot.com/query` | internal Bearer | ops/feeds |

## DaaS conventions (§9)
- **Plans:** `free`, `standard`, `pro`, `internal`. Key format `nvd_` + 32-char hex.
- **Rate limit headers:** `X-RateLimit-*`, `X-Daily-*`; `429` + `Retry-After` on exceed.
- **Pagination:** `limit` (1–5000, default 100) + `offset`; `pagination.next_offset`.
- **Envelope:** `{ "data": [...], "pagination": {...}, "meta": { "as_of", "source":"nidp" } }`.
- **DQ envelope (Gate 6, partial):** responses may include `data_quality.dq_status`
  GREEN/AMBER/RED + `degraded_feeds[]` — check it when asserting data is fresh.
- **Endpoint groups:** health, admin(keys), me, catalog, prices, corporate_actions, indices,
  reference, financials, fno, flows, announcements, macro, snapshots, features, mutual_funds,
  mf_performance, events, intelligence, dq_ai, replay, backfill (+ Query API: feeds, validation,
  quality, vm_ops, archive).

## Nivesh App route groups (§10)
`/api/auth`,`/oauth` · `/user` · `/portfolio` (holdings, CAS upload, time-machine) · `/plans`
(V2 action plans) · `/goals` (Monte Carlo) · `/intelligence` · `/insights` · `/chat`,`/copilot`
(LangGraph + SSE) · `/market` · `/broker` (9 brokers) · `/compliance` (DPDP) · `/mfd` · admin
groups `/api/admin/{datastores,nidp,users,rules,secrets,flags}` · `/portfolio-remediation` ·
`/portfolio-exposure`.

## Standard error shape
`{ "error": { "code", "message", "details": {} } }` — `400/401/403/404/409/422/429/500`.

## Validation source of truth
Request/response shapes are defined in code (Pydantic v2 backend; Zod on frontend) and the
OpenAPI specs above — those are authoritative. Document only endpoints that exist; mark
`PLANNED` otherwise.
