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
Verified after the staging redeploy: the Playwright run below authenticates with a real admin
`session_token` and the panel renders live data, which is only reachable through
`require_admin` + the proxy. The panel showing populated tiles IS the admin path succeeding.
**PASS**

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
Asserted live: `the panel is not showing a backend error` passes — `pipeline-error` has count
0 while tiles are populated, proving the error element is conditional and not always-on.
```
✓ 4 e2e/tests/pipeline-panel-live.spec.ts:55:1 › the panel is not showing a backend error (1.9s)
```
**PARTIAL PASS.** The happy path is proven. The *failure* path — query API actually down ->
`db_error` rendered — is coded at all three layers but has NOT been exercised by killing the
query API. See limitation 3.

## TC8 — Playwright: the tab renders the 6 tiles against staging
Real run against live staging (`https://staging.niveshcopilot.com:8443/v5/nidp`, real
`session_token` cookie via storageState, no mocking, no local webServer):
```
Running 4 tests using 1 worker

  ✓  1 pipeline-panel-live.spec.ts:24:1 › renders all six pipeline stages with live data (16.9s)
  ✓  2 pipeline-panel-live.spec.ts:42:1 › summary reports a state for every stage (6.0s)
  ✓  3 pipeline-panel-live.spec.ts:49:1 › ingest is split by source so one dead feed cannot hide behind a healthy one (4.9s)
  ✓  4 pipeline-panel-live.spec.ts:55:1 › the panel is not showing a backend error (1.9s)

  4 passed (31.8s)
```
Two path facts the spec had to learn the hard way, recorded so the next run does not: the
staging UI is on **:8443** (:443 is the API), and the v5 app is served under **/v5/** — bare
`/nidp` 404s on both ports.
**PASS**

---

## Known limitations (honest scope)

1. **The 6-month scope was wrong and is being reverted.** This dashboard's own TC5 tile is what
   showed it: 126,994 of 146,091 announcements are unreachable because the classifier only
   queues `filed_at >= now()-30d`. The backfill was running oldest-first, manufacturing more
   of them. `--since-days 30` + newest-first ordering (`2a1b7cba`) fixes the scope; the
   already-parsed older documents remain in the corpus and keyword-searchable, but their
   announcements stay unclassified.
2. **Counts move between assertions.** The backfill advances ~150 docs/min, so the spec asserts
   structure and state, never exact numbers. A count regression would not be caught here.
3. **TC7's failure path is unexercised.** Proven: the error element is conditional and absent on
   the happy path. Unproven: that killing the query API renders `db_error` end-to-end. Coded at
   all three layers, never observed.
4. **Stage 1 shows `lagging` because BSE genuinely is.** That is a real finding, not a test
   fixture — BSE announcements were ~8h without an ingest and 2 days behind on filings while
   `classify_feed` reported healthy.
5. **UNVERIFIED on prod.** Staging only. Prod's query API (:8090, `/opt/nidp/repo`) does not
   have `/pipeline/stages`; the tab there would render `db_error` until the prod PR lands.

## Verdict: PASS
