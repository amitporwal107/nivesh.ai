# Feed Reliability — finishing the 3 partials (WORK-0138 / 0144 / 0145)

- **Date:** 2026-07-08
- **Environment:** unit (local) — fully verifiable. On `dev` after push.

## Summary
- **WORK-0138 — SKIPPED split (holiday vs suspect):** the core defect was already fixed
  (SKIPPED no longer resets `consecutive_failures`). Now finished: a new sync
  `is_trading_day()` + `BaseIngester` classifies an empty/0-row result — on a **trading day**
  it finalizes SKIPPED with `error_class="SUSPECT_EMPTY"` + a WARN (a likely silent break);
  on a holiday/weekend/no-date it stays a benign SKIP. No migration (uses error_class).
- **WORK-0144 — one source of truth:** new `nidp.shared.feed_registry` (`FEEDS` manifest);
  `feed_health_check.EXPECTED_FEEDS` now **derives** from it (19 feeds, byte-identical to the
  old hardcoded list), and the drift test enforces the cron schedule agrees. Add/change a feed
  in one place.
- **WORK-0145 — decommission Cloud Scheduler:** VM cron already declared authoritative
  (nidp.cron header). Added `decommission_cloud_scheduler.sh` (dry-run by default) to delete the
  `nidp-cron-*` triggers. The actual deletion is **token-gated** (the GCP token expired) — run
  the script with a `cloudscheduler.admin` token to finish it.

## Test Cases
| ID | Area | Result |
|----|------|--------|
| TC-1 | 0138 is_trading_day == weekday<5 across 10 days | **PASS** |
| TC-2 | 0138 holiday excluded from trading days | **PASS** |
| TC-3 | 0138 empty/0-row on trading day → SUSPECT_EMPTY | **PASS** |
| TC-4 | 0138 weekend/no-date → benign (None) | **PASS** |
| TC-5 | 0144 EXPECTED_FEEDS derives from registry (identical) | **PASS** |
| TC-6 | 0144 registry has no dupes; valid severities; slo>0 | **PASS** |
| TC-7 | 0144 still exactly 19 monitored feeds (no drift) | **PASS** |
| TC-8 | 0144 drift guardrail (every ERROR feed scheduled in cron) | **PASS** |
| TC-9 | 0145 decommission script syntax OK (dry-run default) | **PASS** |
| TC-10 | regression: full feed-reliability suite | **PASS** |

## Test Output (real)
```
$ bash -n decommission_cloud_scheduler.sh                         → OK
$ python3 -m pytest <full feed-reliability suite> -q             → 124 passed, 1 skipped
$ python3 -c "from ...feed_health_check.__main__ import EXPECTED_FEEDS; print(len(EXPECTED_FEEDS))" → 19
$ bash nidp/tests/test_run_service_retry.sh                       → ALL BASH RETRY TESTS PASS
```

## Verdict: PASS
0138 and 0144 are fully complete + tested. 0145's code is complete; the GCP trigger deletion is
token-gated (run `decommission_cloud_scheduler.sh` with a valid token to finish that step).
