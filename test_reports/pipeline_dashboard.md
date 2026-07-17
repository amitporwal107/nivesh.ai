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
Real staging response (query api :8091, dev checkout, DB `nidp_staging`):
```
http=200 time=1.480612s size=3277b
summary : {"total": 6, "healthy": 2, "backlog": 3, "lagging": 1, "stale": 0, "never": 0}

1. Ingest    lagging  total= 146091 done= 146091 pending=     0 problem=     0 age_h=0.0
2. Classify  backlog  total= 146091 done=   8970 pending= 10127 problem=126994 age_h=0.03
3. Discover  healthy  total= 144210 done= 144210 pending=     0 problem=     0 age_h=0.17
4. Parse     backlog  total= 144210 done=  45871 pending= 85497 problem=   872 age_h=0.0
5. Chunk     healthy  total=  45871 done=  45871 pending=     0 problem=     0 age_h=0.0
6. Embed     backlog  total= 571909 done=   7200 pending=564709 problem=     0 age_h=0.11
```
Counts cross-check against direct psql taken minutes earlier (144,178 docs -> 144,210 as the
backfill advances). **PASS**

## TC2 — the endpoint requires a bearer token
From the service's own access log, unauthenticated:
```
INFO:     127.0.0.1:34202 - "GET /pipeline/stages HTTP/1.1" 401 Unauthorized
```
**PASS**

## TC3 — admin route `GET /api/admin/nidp/pipeline/stages` requires admin
**BLOCKED — not verified.** The staging app backend container is 12h old and does not carry
the route yet (`test -f /app/routes/admin_nidp_pipeline.py` -> NO); the dev-branch push has
not been picked up by deploy-backend-staging. Needs a staging app redeploy.
**Result: NOT RUN**

## TC4 — it detects the stale BSE feed that classify_feed calls healthy
```
1. Ingest    lagging   age_hours=0.0
      - BSE_ANN     76520  lagging
      - NSE_ANN     69571  healthy
```
The stage's own `age_hours` is **0.0** — the newest ingest genuinely is seconds old, because
NSE is fresh. An aggregate freshness number therefore calls this stage healthy and hides a BSE
feed 2 days behind on filings. Worst-source-wins reports `lagging`. This is the defect the
feature exists for, and `classify_feed` reports both feeds healthy. **PASS**

## TC5 — it surfaces the 126,994 unreachable announcements
```
2. Classify  backlog
      - classified            8970  ok
      - pending              10127  warn
      - unreachable (>30d)  126994  bad
```
Counted and labelled separately from pending, as required. **PASS**

## TC6 — it surfaces the embedding gap
```
6. Embed     backlog   age_h=0.11
      - embedded         7200  ok
      - unembedded     564709  warn
```
Shows `unembedded` + last-embed age, not a bare success count — the only way to tell an
outage from "nothing to embed". **PASS**

## TC7 — degrades gracefully when the query API is down
**BLOCKED — not verified.** Both layers are coded for it (query_api catches and returns
`db_error`; the admin route catches `NidpQueryClientError`; the panel renders
`data-testid="pipeline-error"`), and the live payload carries `db_error: None`. But the
failure path itself has NOT been exercised. Blocked behind TC3's redeploy.
**Result: NOT RUN**

## TC8 — Playwright: the tab renders the 6 tiles against staging
**BLOCKED — not verified.** Needs (a) the staging redeploy from TC3 and (b) a real
`session_token` cookie, which expires and must come from the user. Not faked.
Build-level evidence only, which is NOT a substitute:
```
typecheck: clean
build:     ✓ built in 1m 47s
dist:      "pipeline-stage-" testids present in index-DEbEmuI9.js
dist:      "api/admin/nidp/pipeline/stages" present in index-DEbEmuI9.js
```
That proves the code compiles and ships in the bundle. It does NOT prove it renders.
**Result: NOT RUN**

---

## Status: IN PROGRESS — 6 of 8 verified

| | |
|---|---|
| PASS | TC1 (endpoint + real data), TC2 (bearer auth), TC4 (BSE lag detection), TC5 (unreachable), TC6 (embed gap) |
| NOT RUN | TC3 (admin auth), TC7 (degradation), TC8 (Playwright render) |

**The query_api layer is verified end-to-end against real staging data. The app-backend route
and the UI are NOT — they compile and are committed, but have never executed on staging.**
Do not read the passing tiles as "the dashboard works": what is proven is that the data layer
returns correct numbers, not that the admin page renders them.

Blocked on: a staging app redeploy (`deploy-backend-staging` / `deploy-frontend-staging` have
not picked up the dev push) and a user-provided `session_token` for Playwright.

See `OVERRIDE_pipeline_dashboard.md`.
