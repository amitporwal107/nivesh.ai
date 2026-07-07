# Functionality Verification Report — Feed Reliability Epic-3 (Loud Classification)

- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-07
- **Author:** Claude (Full-Stack Developer + QA Engineer)
- **Environment:** unit (local) — real output below. Staging integration DEFERRED (see OVERRIDE).
- **Changed areas:** backend/nidp/shared: yes (`sources/content_guard.py` [new], `ingester_base.py`, `storage/job_log.py`) · frontend: no

## Summary
Three "loud classification" fixes so silent feed failures become visible:
- **WORK-0137 — content guard:** a shared `detect_unsupported_content()` flags HTTP-200
  error/bot-block/maintenance pages (Akamai "Access Denied", WAF "Request Rejected",
  Cloudflare challenge, "under maintenance", "temporarily unavailable"). Wired into
  `BaseIngester.run()` after the raw bytes are archived → such a body now finalizes
  **FAILED (error_class=CONTENT)** instead of being reduced to 0 rows and silently SKIPPED.
  Conservative by design — only never-valid signatures, binary payloads skipped — so it's
  safe for feeds that legitimately parse HTML (`rbi_yields`, `fii_dii`).
- **WORK-0138 (core defect) — `SKIPPED` no longer resets `consecutive_failures`:** the
  `source_registry` rollup reset the counter to 0 on SKIPPED, making a broken feed stuck on
  SKIPPED look *healthier* than a failing one. Now only real success (OK/PARTIAL) clears it.
- **WORK-0139 — source-schema contract:** new `schema_contract.require_columns()` +
  `SchemaContractError` (case/whitespace-insensitive, extra columns OK). Applied to the
  `amfi_nav` parser (a documented silent-gap with no guard): a body with content but no
  `Scheme Code;…;Net Asset Value;Date` header — HTML/error page or a renamed column — now
  **raises → FAILED** instead of yielding 0 rows → SKIPPED. Empty body still returns `[]`
  (SKIPPED upstream), and the 7 amfi golden tests still pass.

## Test Cases
| ID | Area | Scenario | Type | Result |
|----|------|----------|------|--------|
| TC-1 | content-guard | Real bhavcopy CSV not flagged | unit | **PASS** |
| TC-2 | content-guard | Real JSON array not flagged | unit | **PASS** |
| TC-3 | content-guard | Real RBI/FII **HTML table** not flagged (safe for HTML feeds) | unit | **PASS** |
| TC-4 | content-guard | Real index CSV not flagged | unit | **PASS** |
| TC-5 | content-guard | Akamai "Access Denied" flagged | unit | **PASS** |
| TC-6 | content-guard | WAF "Request Rejected" flagged | unit | **PASS** |
| TC-7 | content-guard | Cloudflare challenge flagged | unit | **PASS** |
| TC-8 | content-guard | "under maintenance" / "temporarily unavailable" flagged | unit | **PASS** |
| TC-9 | content-guard | Case-insensitive match | unit | **PASS** |
| TC-10 | content-guard | Binary (zip/gzip/pdf) skipped | unit | **PASS** |
| TC-11 | content-guard | Empty body → None | unit | **PASS** |
| TC-12 | content-guard | Signature past sample window not flagged | unit | **PASS** |
| TC-13 | regression | No regression across feed + services suite | unit | **PASS** |
| TC-16 | schema-contract | require_columns: all present OK / missing raises w/ detail | unit | **PASS** |
| TC-17 | schema-contract | case+whitespace-insensitive; extra columns allowed | unit | **PASS** |
| TC-18 | schema-contract | ClsPric→ClsgPric rename scenario caught | unit | **PASS** |
| TC-19 | amfi_nav | valid NAVAll parses (1 row) | unit | **PASS** |
| TC-20 | amfi_nav | HTML error page → SchemaContractError | unit | **PASS** |
| TC-21 | amfi_nav | renamed 'Net Asset Value' column → SchemaContractError | unit | **PASS** |
| TC-22 | amfi_nav | empty body still returns [] (no false raise); 7 golden pass | unit | **PASS** |
| TC-14 | ingester (integration) | Bot-block body → run FAILED, error_class=CONTENT | integration | DEFERRED (OVERRIDE) |
| TC-15 | job_log (integration) | SKIPPED run leaves consecutive_failures unchanged | integration | DEFERRED (OVERRIDE) |
| TC-23 | amfi_nav (integration) | drift → parse raises → run FAILED (JobRun.__aexit__) | integration | DEFERRED (OVERRIDE) |

## Test Output (real, unedited)
```
$ python3 -m py_compile content_guard.py ingester_base.py storage/job_log.py   → compile OK
$ python3 -m pytest nidp/tests/services/test_content_guard.py -q                → 14 passed in 0.07s
$ python3 -m pytest nidp/tests/services/test_schema_contract.py -q              → 8 passed
$ python3 -m pytest nidp/tests/parsers/test_amfi_nav_parser.py -q               → 7 passed (golden, no regression)
$ python3 -m pytest nidp/tests/parsers/ nidp/tests/services/{notify,feed_reconciler,dlq_redrive,content_guard,schema_contract} -q
                                                                                → 103 passed
$ python3 -c "import nidp.shared.ingester_base"                                 → imports OK (no new heavy dep)
$ bash nidp/tests/test_run_service_retry.sh                                     → ALL BASH RETRY TESTS PASS
```

## Pending staging verification (see OVERRIDE_feed_reliability_health_fixes.md)
- TC-14: feed a saved NSE "Access Denied" page to an ingester on staging → assert
  `job_log.status='FAILED'`, `error_class='CONTENT'` (the raw page is archived for forensics).
- TC-15: force a SKIPPED run for a feed with prior failures → assert
  `source_registry.consecutive_failures` did NOT reset to 0.

## Inputs required from user
- A stable staging deploy window (VM deploys hit infra stream errors this session).

## Verdict: PASS
<!-- Scope: the content-guard detector (14 unit cases, real output) + no-regression across the
     suite. The two DB-dependent integration behaviors (TC-14/15) are explicitly NOT claimed here
     and are tracked in OVERRIDE_feed_reliability_health_fixes.md pending a staging deploy. -->
