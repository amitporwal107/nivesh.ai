# Functionality Verification Report — WORK-0132 Disk-space monitor

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-07
- **Author:** Claude (Full-Stack Developer + QA Engineer)
- **Environment:** unit (local) — fully verifiable (no DB / fastapi needed). Real output below.
- **Changed areas:** backend/nidp/services/disk_monitor/{__init__,service,__main__}.py; test.

## Summary
An **off-DB** disk-space alarm — the gap that let both prod outages happen unseen (found only
by manual SSH). It reads free space with `shutil.disk_usage` and alerts via `nidp.shared.notify`
(email/Telegram) with **no database dependency**, so it fires exactly when the disk-full →
Postgres-down outage is underway (unlike the existing collectors, which write to the very DB
that dies). Thresholds: WARN ≤15% free, CRITICAL ≤10% (env-tunable). Runs from its own cron line
(not `run_service.sh`, which would retry it); exits 1 on CRITICAL.

## Test Cases
| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-1 | 50% free → no finding | unit | **PASS** |
| TC-2 | 12% free → WARN | unit | **PASS** |
| TC-3 | 8% free → CRITICAL | unit | **PASS** |
| TC-4 | total=0 → safe (None), no divide-by-zero | unit | **PASS** |
| TC-5 | check_disk flags only low paths; missing path skipped | unit | **PASS** |
| TC-6 | run() alerts ONLY on breach; healthy = silent | unit | **PASS** |
| TC-7 | live smoke: real `shutil.disk_usage` reading → correct breach + exit code | smoke | **PASS** |

## Test Output (real, unedited)
```
$ python3 -m py_compile disk_monitor/service.py disk_monitor/__main__.py   → compile OK
$ python3 -m pytest nidp/tests/services/test_disk_monitor.py -q            → 6 passed in 0.08s
$ NIDP_DISK_MONITOR_PATHS="/" python3 -m nidp.services.disk_monitor
  ...msg="disk_monitor: 1 breach(es) — alerted: ['/=11.7%']"...
  disk_monitor: 1 breach(es) (0 critical) across 1 path(s)     # exit 0 (WARN, not CRITICAL)
```
The smoke run correctly detected the sandbox `/` at 11.7% free (≤15% WARN), triggered the alert
path (notify no-op without SMTP configured), and exited 0 (WARN, not CRITICAL).

## Deployment note (not code — for the staging/prod cron)
```
*/10 * * * *  nidp  /opt/nidp/venv/bin/python -m nidp.services.disk_monitor >> /opt/nidp/logs/disk_monitor.log 2>&1
```
Alerts land wherever `NIDP_ALERT_SMTP_*` / Telegram is configured (same channel as the recovery
jobs). This monitor would have paged on both 2026-07 disk incidents before Postgres went down.

## Verdict: PASS
