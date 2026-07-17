# Functionality verification — 6-stage pipeline dashboard (NIDP Console)

- **Date:** 2026-07-17
- **Branch:** `dev`
- **Environment:** STAGING — query_api on `nidp-stack-vm`, DB `nidp_staging`, UI `frontend-v5`
- **Changed areas:** `backend/nidp/services/query_api/routers/pipeline.py` (new),
  `backend/nidp/services/query_api/app.py`, `backend/services/nidp_query_client.py`,
  `backend/routes/admin_nidp_pipeline.py` (new), `backend/server.py`,
  `frontend-v5/src/components/nidp/PipelinePanel.tsx` (new),
  `frontend-v5/src/pages/NidpConsole/index.tsx`

**Test cases authored BEFORE implementation, per .claude/VERIFICATION_PROTOCOL.md.**

## Design under test

Six stages, each a tile with counts + freshness + its own staleness rule:

| # | Stage | Source of truth | "done" | "stuck" |
|---|---|---|---|---|
| 1 | Ingest | `nidp.corporate_announcements` by `source` | rows | `max(ingested_at)` age |
| 2 | Classify | `event_category` | NOT NULL | NULL & `filed_at` < now()-30d = **unreachable** |
| 3 | Discover | `nidp.documents` | row exists | — |
| 4 | Parse | `parse_status` | `parsed` | `failed & parse_attempts>=5` = exhausted |
| 5 | Chunk | `nidp.document_chunks` | chunk exists | parsed doc w/ 0 chunks |
| 6 | Embed | `document_chunks.embedding` | NOT NULL | unembedded & `max(embedded_at)` ageing |

Why per-stage freshness rather than `classify_feed`: all four pipeline feeds are registered
`expected_freq='event'`, and `classify_feed` only ever returns `stale` for `daily`/`high-freq`.
It calls a two-day-dead BSE feed **healthy**. That is the defect this dashboard exists to fix,
so it must not be built on the thing that has it.

---

## TC1 — query_api `GET /pipeline/stages` returns all 6 stages from the real DB
Real staging response, all six stages present, counts non-fabricated (cross-checked against
direct psql). **Result: TBD**

## TC2 — the endpoint requires a bearer token
Unauthenticated request -> 401/403, not data. **Result: TBD**

## TC3 — admin route `GET /api/admin/nidp/pipeline/stages` requires admin
Non-admin/anon -> 403. Admin -> the payload. **Result: TBD**

## TC4 — it detects the stale BSE feed that classify_feed calls healthy
Staging truth at authoring time: BSE ingest lag 30,151s (8.4h), latest_filed 2026-07-15;
NSE lag 91s. The dashboard MUST show BSE degraded/stale and NSE healthy.
This is the whole point of the feature. **Result: TBD**

## TC5 — it surfaces the 126,994 unreachable announcements
`event_category IS NULL AND filed_at < now()-30d` are NOT "pending" — nothing will ever
classify them. They must be counted separately and labelled, not folded into pending.
**Result: TBD**

## TC6 — it surfaces the embedding gap
523,778 chunks / 6,600 embedded. An embedding outage is indistinguishable from
"nothing to embed" in SQL (`embed_pending` swallows a missing key), so the tile must show
`unembedded` + `latest_embed` age rather than a bare success count. **Result: TBD**

## TC7 — degrades gracefully when the query API is down
Payload carries `db_error`, panel renders the error, no 500 and no blank page.
**Result: TBD**

## TC8 — Playwright: the tab renders the 6 tiles against staging
Real `npx playwright test` output on the changed screen. **Result: TBD**

## Verdict: TBD — IN PROGRESS
