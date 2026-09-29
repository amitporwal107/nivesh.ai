# Functionality Verification Report — Event AI analysis ingest API

- **Branch:** feat/event-ai-ingest-api (off origin/dev)
- **Date:** 2026-09-29
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit (fastapi 0.110.1 / pymongo 4.6.3 = staging pins); staging after deploy
- **Changed areas:** backend routes/services: yes (routes/event_ai_ingest.py, helpers/secrets.py, server.py) · frontend src: no

## Summary
`POST /api/internal/event-ai-analysis/bulk` upserts corporate-event AI analyses into Mongo
`event_ai_analysis`. `GET .../stats` reports what has landed. Auth is the header X-Event-AI-Key against
the admin-managed EVENT_AI_INGEST_KEY secret; unset returns 503. This lets background jobs on nidp-stack-vm
write without ssh, database credentials or a user GCP token.

## Test Cases
| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-1 | secret unset | 503, nothing written | PASS |
| TC-2 | missing / wrong key | 401, nothing written | PASS |
| TC-3 | same batch sent twice | 1 upsert then 1 match; idempotent | PASS |
| TC-4 | {"$date": iso} and ISO strings | stored as tz-aware datetimes (+05:30 kept) | PASS |
| TC-5 | same filing, different model tag | 2 documents side by side | PASS |
| TC-6 | invalid docs in a batch (missing field, top-level $ key) | rejected individually; good ones written | PASS |
| TC-7 | more than 200 docs | 422 | PASS |
| TC-8 | stats | totals equal what was written | PASS |

## API / Endpoint Tests (staging)
- **pytest:** `pytest tests/test_event_ai_ingest.py -q` → `8 passed in 0.48s`
- **Staging endpoint:** UNVERIFIED — requires deploy (merge to dev) and EVENT_AI_INGEST_KEY set in staging secrets.
  After deploy: `POST /api/internal/event-ai-analysis/bulk` with the key → expect HTTP 200, then `GET .../stats`.

## UI / Playwright Tests
Not applicable — no frontend change.

## Data Correctness (staging)
Pending deploy. The target collection already exists (loaded via ssh) with the same _id scheme, so API upserts
replace-in-place rather than duplicate.

## Inputs required from user
- Approval to merge (a dev merge deploys on nivesh-app-vm, ~4.2 GB free).

## Verdict: PASS
