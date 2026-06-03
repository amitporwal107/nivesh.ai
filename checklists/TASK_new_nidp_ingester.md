# Checklist — TASK: New NIDP Ingester

**Use when:** adding a data feed ingester under `backend/nidp/services/`.
**Target env:** ☐ Staging   ☐ Prod
**Status:** `NOT STARTED` → `IN PROGRESS` → `DONE` | `🔴 BLOCKED`
**Roles:** FULL_STACK_DEV  ·  Canonical: TECHNICAL_ARCHITECTURE §5, §14.5

## 0. INTAKE
- [ ] Restated the feed: source, table, frequency, severity rules.
- [ ] Loaded `.claude/roles/FULL_STACK_DEVELOPER.md`.
- [ ] Read TECHNICAL_ARCHITECTURE §5 (BaseIngester) + §14.5 (add-ingester steps) — did not guess.
- [ ] Unknown source format / cadence → `NEEDS-INPUT`, not assumed.

## 1. PRE-FLIGHT
- [ ] On `dev`. Followed §14.5: created `service.py`, `parser.py`, `validators.py`, `writer.py`, `__main__.py`, `Dockerfile`.
- [ ] Extends `BaseIngester` (`fetch→raw_archive→parse→validate→persist→emit`).

## 2. EXECUTE
- [ ] Validators set with correct severity (`BLOCK`/`FIX`/`WARN`) — no silent bad data.
- [ ] Registered: `source_registry` migration · cron (`nidp.cron`) · Cloud Scheduler · Cloud Build trigger · Prometheus port.
- [ ] Raw archive SHA-256 dedup honored; no secrets in code.

## 3. VERIFY — STAGING
- [ ] `./test_locally.sh <service>` over a 30-day range — **output shown**.
- [ ] Rows landed in the target table (query it) — shown.
- [ ] No `severity='BLOCK'` in `nidp.validation_findings` for the feed — shown.
- [ ] JobRun ended `OK`/`PARTIAL` (not `FAILED`) in `nidp.job_log` — shown.

## 4. VERIFY — PROD
- [ ] Staging run VERIFIED; merged via PR; Cloud Build deployed the job.
- [ ] Manual prod run (`run_service.sh <svc>` or `gcloud run jobs execute`) — output shown.
- [ ] `nidp.v_feed_status` shows `last_success_at` fresh, `consecutive_failures=0` — shown.
- [ ] Prometheus freshness metric + Grafana Job Health green — shown.

## DONE-GATE
- [ ] Ingester actually ran AND persisted real rows — output shown (never "should ingest").
- [ ] App test (run) AND data test (rows + no BLOCK + feed status) shown.
- [ ] All true → **DONE**; else → **IN PROGRESS**.
- [ ] Source unreachable / schema drift / blocked → `🔴 REAL BLOCKER:` what / why / needed. No fabricated rows.
