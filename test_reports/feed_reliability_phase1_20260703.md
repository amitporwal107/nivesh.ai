# Functionality Verification Report — Feed Reliability Phase 1 (Auto-Recovery)

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-03
- **Author:** Claude (Full-Stack Developer + QA Engineer)
- **Environment:** unit (local) — verified with real test output below. Staging deploy PENDING.
- **Changed areas (this session):**
  - `backend/nidp/shared/notify.py`
  - `backend/nidp/services/feed_reconciler/{__init__,service,__main__}.py`
  - `backend/nidp/services/dlq_redrive/{__init__,service,__main__}.py`
  - `backend/nidp/deploy/vm/run_service.sh` (bounded retry)
  - tests: `backend/nidp/tests/services/test_{notify,feed_reconciler,dlq_redrive}.py`,
    `backend/nidp/tests/test_run_service_retry.sh`
  - frontend src: no

## Summary
Epic 1 (auto-recovery) code is **complete and unit-verified**: (1) `feed_reconciler` detects
missed `(feed, trading-day)` gaps and heals them via the idempotent `run_backfill`; (2)
`dlq_redrive` reprocesses PENDING `dq.dlq_findings` and transitions `replay_status`; (3)
`run_service.sh` now bounds-retries transient failures with backoff; (4) `shared/notify.py`
is a dependency-free env-gated email helper. Verified with 13 pytest cases + 3 bash cases (real
output below). **NOT yet done:** cron/registry wiring (WORK-0128/0129) and staging deployment +
live integration (needs VM access + SMTP creds) — explicitly not claimed here.

## Test Cases
| ID | Area | Scenario | Type | Result |
|----|------|----------|------|--------|
| TC-1 | reconciler | No gaps → no heal, JobRun OK | unit | **PASS** |
| TC-2 | reconciler | Gaps present, source recovers → healed, OK | unit | **PASS** |
| TC-3 | reconciler | Gap remains after heal → FAILED + actionable alert | edge | **PASS** |
| TC-4 | reconciler | Weekend excluded from gaps | edge | **PASS** |
| TC-4b | reconciler | Feed not in backfill registry not falsely healed | failure | **PASS** |
| TC-5 | dlq_redrive | Re-run now succeeds → REPLAYED (+ replayed_at) | unit | **PASS** |
| TC-6 | dlq_redrive | Still failing, attempts<MAX → PENDING, attempt recorded | unit | **PASS** |
| TC-7a | dlq_redrive | Attempts reach MAX → INVESTIGATING | edge | **PASS** |
| TC-7b | dlq_redrive | Aged-out + failing → DROPPED | edge | **PASS** |
| TC-8 | dlq_redrive | Unknown/non-runnable feed → INVESTIGATING, no crash | failure | **PASS** |
| TC-9 | notify | SMTP unconfigured → False, no raise | unit | **PASS** |
| TC-10 | notify | SMTP configured → builds+sends EmailMessage | unit | **PASS** |
| TC-11 | run_service.sh | Fails twice then succeeds, MAX=3 → exit 0, 3 attempts | failure | **PASS** |
| TC-12 | run_service.sh | Exit code 2 (usage) → not retried, exit 2 | edge | **PASS** |
| TC-13 | run_service.sh | MAX=1 (legacy) → single attempt, failure propagates | edge | **PASS** |
| TC-14 | integration | Heal a real gap on staging job_log | integration | PENDING (needs VM access) |
| TC-15 | integration | Flip a real staging DLQ row | integration | PENDING (needs VM access) |
| TC-16 | integration | Real email delivered | integration | PENDING (needs SMTP creds) |

## Test Output (real, unedited)
```
$ bash -n nidp/deploy/vm/run_service.sh
run_service.sh syntax OK

$ bash nidp/tests/test_run_service_retry.sh
TC-11 PASS (rc=0 attempts=3)
TC-12 PASS (rc=2 attempts=1)
TC-13 PASS (rc=1 attempts=1)
ALL BASH RETRY TESTS PASS

$ python3 -m pytest nidp/tests/services/test_notify.py nidp/tests/services/test_feed_reconciler.py nidp/tests/services/test_dlq_redrive.py -q
.............                                                            [100%]
13 passed in 0.15s
```

## Live Staging Verification — 2026-07-03 (feed_reconciler)
Deployed the code to `/opt/nidp/dev-repo/nivesh.ai` and ran against the **staging DB**
(`nidp_staging`, staging venv). Real, unedited output:

```
# 1. Detect (dry-run) — found 11 real gaps in the last 6 trading days:
feed_reconciler: 11 gap(s) in 2026-06-25..2026-07-02: bhavcopy@2026-06-29,
  index_close@{06-25,06-29,06-30,07-01,07-02}, fii_dii@{06-25,06-29,06-30,07-01,07-02}
job_log[feed_reconciler] ... status=OK fetched=11 inserted=0   # JobRun row written

# 2. Heal (scoped to tiny feeds index_close,fii_dii to respect the 150M disk budget):
feed_reconciler: healed 5/10 gap(s); 5 remaining
job_log[fii_dii] ... status=OK fetched=2 inserted=2 target_date=2026-07-02  # real re-ingest
notify: no alert channel configured — alert NOT delivered (⚠ 5 gap(s) could NOT be healed)  # gating OK
job_log[feed_reconciler] ... status=PARTIAL fetched=10 inserted=5 skipped=5
FREE before: 92M → after: 91M   # negligible disk cost

# 3. Confirm persistence (fresh dry-run, default feeds): gaps 11 → 6
feed_reconciler: gaps=6 healed=0 remaining=6   # 5 fii_dii gaps closed; index_close×5 + bhavcopy@6/29 remain
```

Result: **PASS (live)** — reconciler detects real gaps, heals what it can (fii_dii persisted),
surfaces what it can't, writes JobRun rows, and correctly gates the alert. TC-14 verified.

Observations (real feed bugs the reconciler EXPOSED, tracked separately):
- `index_close` ingestion is genuinely failing in staging for all 5 days (not a reconciler
  fault — the heal attempted and honestly reported it unhealed). Candidate: WORK-0137/0139.
- Minor: an `aiohttp` "Unclosed client session" warning in the fetch/backfill path on process
  exit (cosmetic; run completes and data persists). Worth a small cleanup.

## Data Correctness (staging) — remaining
- dlq_redrive: PENDING DLQ live run — not yet exercised (TC-15).
- notify: real email delivery — pending SMTP creds (TC-16).

## Inputs required from user
- Deployment path to the staging NIDP VM (SSH to pull+apply+verify, or a deploy trigger).
- SMTP credentials for the email channel (`NIDP_ALERT_SMTP_*`) to verify real delivery.

## Not claimed / remaining Phase-1 work
- WORK-0128 (schedule reconciler+redrive in cron + register in NIDP_INGESTERS) — deploy-time
  config, not wired this turn.
- WORK-0129 (enable staging feed cron) — a staging-activity policy decision, deferred.
- Staging deployment + live integration (TC-14/15/16).

## Verdict: PASS
<!-- Scope: the four code components changed this session (feed_reconciler, dlq_redrive,
     shared/notify.py, run_service.sh retry). 13 pytest + 3 bash cases pass with real output
     above. Cron wiring and staging integration are explicitly NOT claimed and remain PENDING. -->
