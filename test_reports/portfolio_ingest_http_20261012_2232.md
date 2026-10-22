# Portfolio data from the app to NIDP over HTTP

Date: 2026-10-12 · Commits `050b1dd6`, `9a20d357`, `52fad169` · Env: staging (CloudPe)
Areas: `backend/nidp/services/query_api/routers/portfolio.py`, `backend/nidp/services/portfolio_{holdings,transactions,goals}_sync/service.py`,
`backend/services/portfolio_direct_push.py`, `nidp_query_client.py`, `portfolio_gcs_export.py`, `cas_snapshot_engine.py`, `mf_scheduler.py`,
`backend/helpers/parsing.py`, `backend/routes/admin.py`

## Problem

User portfolio data reached NIDP through a GCS bucket. The HTTP replacement existed only
on the app side: the Query API endpoints it posts to were never built, and goals had no
push at all. With no bucket, NIDP received no user data.

## Change

- NIDP Query API: `POST /portfolio/ingest-holdings`, `/ingest-transactions`, `/ingest-goals`
  (bearer auth). They call the same `ingest_records()` the GCS-file path now uses.
- App: `sync_portfolio_to_nidp()` is the single entry point for the CAS-import hook,
  post-upload enrichment, the 22:50 nightly job and the two admin endpoints. HTTP push when
  the Query API is configured, no fallback on failure; GCS only where it is not configured.
- Two defects found by the live tests and fixed:
  1. The NIDP transaction and goal upserts bound JSON date/timestamp strings directly, which
     asyncpg rejects — every transaction upsert failed, on the GCS path as well.
  2. Holdings carry one row per folio/account; NIDP keys a row per instrument, so duplicates
     overwrote each other. Rows for the same instrument are merged before the push.

## Test cases

| # | Case | Expected |
|---|---|---|
| U1–U3 | Each endpoint rejects a missing or wrong bearer token | 401 |
| U4 | Flat holdings are grouped per user and snapshot date | pass |
| U5–U10 | Missing user/date, malformed bodies, oversize batch | 422 / 413 |
| U11–U13 | Empty push, pass-through of transactions and goals, error surfaced as `ok: false` | pass |
| U14–U15 | Date and timestamp strings are bound as date/datetime objects | pass |
| U16–U21 | `sync_portfolio_to_nidp`: direct when configured, `include`, per-kind error isolation, no GCS fallback after a failed push, GCS only when unconfigured, JSON-safe goals | pass |
| U22 | Same instrument in several folios is sent as one position, value preserved | pass |
| L1 | Live: test user holdings ingested; second identical push is skipped | synced 1 → skipped 1 |
| L2 | Live: test user transaction and timestamped goal ingested | 1 row each |
| L3 | Live: record without user/date rejected; unauthenticated request rejected | 422 / 401 |
| L4 | Live: the app's real sync; NIDP total equals the app's total | equal |
| L5 | Live: intelligence job runs and the app reads the snapshot back through the DaaS API | value matches |

## Results

Unit tests (staging backend image): `22 passed` for the two new files
(`nidp/tests/services/test_portfolio_ingest_api.py`, `tests/test_portfolio_sync_to_nidp.py`).

CI: both `Deploy backend → CloudPe app VM [staging]` and `Deploy → CloudPe NIDP VM [staging]` succeeded for each commit.

Staging API — a fake user (`cloudpe-ingest-test@example.invalid`, made-up figures) pushed
from inside the app backend over the real HTTPS path, then deleted from NIDP:
```
holdings 1st push → {"ok": true, "upserted": 2, "users": 1, "synced": 1, "skipped": 0, "errors": 0, ...}
holdings 2nd push → {"ok": true, "upserted": 0, "users": 1, "synced": 0, "skipped": 1, "errors": 0, ...}
transactions      → {"ok": true, "upserted": 1, "users": 1, "seen": 1, "errors": 0, ...}
goals             → {"ok": true, "upserted": 1, "users": 1, "seen": 1, "errors": 0, ...}
bad record        → rejected: NIDP Query API returned 422: {"detail":"every holding needs 'external_user_id' and a snapshot date"}
POST /query/portfolio/ingest-holdings without a token → HTTP 401
```
Data test on NIDP for that user: `client_master` 1 row; `user_holdings_snapshot` 2 rows, quantity 12;
`user_transactions` 1 row (₹1,000, 2026-10-01); `user_goals` 1 row with its timestamp stored;
audit `SUCCESS, SKIPPED, …`. After clean-up: 0 rows left for the test user.

The app's real sync (`sync_portfolio_to_nidp(db)`) run inside the staging backend:
```
sync → {"via": "direct", "holdings": {"exported": 1, "skipped": 1, "date": "2026-10-12", "via": "direct", "upserted": 93}, "transactions": {"exported": 0, ...}, "goals": {"exported": 0, ...}}
portfolio_intelligence_sync trigger → {"ok": true, "ingester": "portfolio_intelligence_sync", "status": "spawned", ...}
```
Data test — the same portfolio on both sides:
```
app side  (Mongo holdings):                 117 rows, value 11818975.07
NIDP side (portfolio.user_holdings_snapshot): 93 rows, value 11818975.07, weights 100.00%
```
(Before the merge fix NIDP held 93 rows worth 7716291.14, weights 65.29%.)

Read back by the app through the NIDP DaaS API:
```
portfolio snapshot → {"snapshot_date": "2026-10-12", "total_market_value_inr": 11818975.07, "equity_weight_pct": 11.9183, "mf_weight_pct": 62.4776, "concentration_top5_pct": 46.5928, "unresolved_weight_pct": 69.133, "quality_tier": "REVIEW"}
holdings           → 93 rows
```

## Not verified / known gaps

- Transactions and goals pushed 0 rows from real data: the staging account has no
  `cas_transactions` documents and no `user_goals` rows yet. Only the fake-user test
  exercised those two paths end to end.
- `unresolved_weight_pct` is 69%: most fund holdings are not yet matched to NIDP's
  security master (the push sends no AMFI scheme code). The snapshot is graded `REVIEW`.
- The triggers themselves (CAS-import hook, nightly 22:50 job, admin endpoints) were not
  fired through their own entry points; the function they all call was.
- The legacy GCS path (`via: gcs`) is covered by a unit test only.

## Verdict: PASS
