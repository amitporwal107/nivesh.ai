# OVERRIDE — Feed Reliability: health-endpoint fixes (WORK-0131, WORK-0133)

REASON: The backend changes this session cannot complete the standard
staging-API verification right now: (1) `fastapi` is not installed in this repo
environment, so the daas_api/query_api router unit tests `importorskip` locally
(they run in an env that has fastapi — e.g. staging); (2) TWO consecutive
attempts to deploy + run the fixes on the staging VM returned infrastructure
errors ("Tool permission stream closed before response received"), so live
staging verification could not finish this session. The changes are low-risk
and were statically verified; live verification will run on the next successful
staging deploy. This is a non-silent, tracked skip.

## Changed areas
- `backend/nidp/deploy/vm/health_check.sh` (WORK-0131): `SELECT`/`GROUP BY`
  `service` → `ingester` (the column that actually exists in `nidp.job_log`);
  on DB-connect failure, **SEND** the alert (DB-down *is* the alert) instead of
  swallowing it and exiting; made `NIDP_HOME` overridable so staging can run it.
- `backend/nidp/services/daas_api/routers/health.py` (WORK-0133): added
  `/readyz` (HTTP **503** when the DB is unreachable); `/health` unchanged (still
  200 liveness, db_ok in body).
- `backend/nidp/services/query_api/routers/health.py` (WORK-0133): same `/readyz`.
- `backend/nidp/tests/services/test_health_readyz.py`: unit tests (skip-guarded
  on fastapi).

## What WAS verified this session (real output)
```
$ bash -n nidp/deploy/vm/health_check.sh   → health_check.sh syntax OK
  (grep: only comment mentions of "service" remain; SQL uses "ingester")
$ python3 -m py_compile .../daas_api/routers/health.py .../query_api/routers/health.py → compile OK
$ python3 -m pytest nidp/tests/services/{test_notify,test_feed_reconciler,test_dlq_redrive,test_health_readyz}.py -q
  → 13 passed, 1 skipped in 0.98s   (health_readyz skipped: no fastapi in repo env)
$ bash nidp/tests/test_run_service_retry.sh → ALL BASH RETRY TESTS PASS
```

## Pending staging verification (run on next successful deploy)
- `health_check.sh` against staging `nidp.job_log` → prints real per-ingester
  staleness (not "cannot connect to postgres"); with a test Telegram token,
  confirm the DB-down branch actually pages.
- `/readyz` → `curl` staging daas (`:8083`) / query (`:8090`): 200 when db_ok;
  stop the DB → 503.
- Follow-up (WORK-0133b): update `service_health_collector.py` to probe
  `/readyz` (or inspect the body) so a DB-down outage is recorded as DOWN — it
  currently records UP on any 200.

## Also deferred — Epic-3 classification fixes (2026-07-07, DB-dependent paths)
Unit-verified logic is in `feed_reliability_classification_20260707.md` (Verdict: PASS, 14
content-guard cases + no-regression). The DB/runtime integration below needs a staging deploy:
- **WORK-0137** (`ingester_base.py` content-guard wiring): feed a saved "Access Denied" page to
  an ingester on staging → assert `job_log.status='FAILED'`, `error_class='CONTENT'`.
- **WORK-0138** (`job_log.py` rollup SQL — cannot be unit-tested without Postgres): force a
  SKIPPED run for a feed with prior failures → assert `source_registry.consecutive_failures`
  did NOT reset to 0.
- **WORK-0139** (`amfi_nav` schema contract — parser logic IS unit-tested: 8 schema-contract
  cases + amfi drift/valid/empty + 7 golden pass, 103 total): the *runtime* wiring — a
  SchemaContractError from `parse_nav_all` → `JobRun.__aexit__` → `job_log.status='FAILED'`
  — needs a staging run (feed amfi_nav a saved HTML/renamed-header body → assert FAILED).

## Verdict: OVERRIDE (staging verification deferred — see REASON)
