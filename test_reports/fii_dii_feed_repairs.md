# Functionality Verification Report — FII/DII feed repairs (disk, NSE 403 retry, delivery→prices_eod, shareholding quarter grain)

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-18
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging (nidp_staging on nidp-stack-vm; ingesters run as venv Python via /opt/nidp-staging/run_service.sh)
- **Changed areas:** backend routes/services: **yes** (`nidp/shared/sources/nse_fetcher.py`, `nidp/services/delivery/{writer,service}.py`, `nidp/services/nse_financials/writer.py`) · frontend src: no

## Summary
Repair pass over the FAIL/PARTIAL feeds in the nine-feed FII/DII scorecard. Four defects were
root-caused and fixed: (1) the host disk was 100% full, which failed MinIO `PutObject` and so
`nse_shareholding`; (2) `nse_fetcher` treated an NSE 401/403 as terminal after one *immediate*
retry, converting a transient Akamai edge block into hard feed failures across
fii_dii/bhavcopy/delivery/nse_shareholding; (3) `prices_eod.deliv_qty/deliv_pct` had many readers
and **zero** writers, so the 0.20-weight accumulation pillar read nulls; (4) the Screener
shareholding path wrote interim month-end labels into a quarterly table, polluting the quarter axis.

**Not fixed, reported as blocked:** NSE's edge currently 403s this VM's egress IP (34.93.60.254) on
every host, so feeds #1/#4/#7/#9 cannot fetch new data regardless of code. `mf_holdings` (#8) is
broken by per-AMC website drift across ~10 AMCs — a per-site scraper effort, not attempted here.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | infra | Host disk has headroom; MinIO accepts writes | infra | >0 bytes free, MinIO up | PASS |
| TC-2 | nse_fetcher | 3 consecutive NSE 403s then 200 returns the body | unit | returns body, does not raise | PASS |
| TC-3 | nse_fetcher | 403 retry sleeps with non-decreasing backoff | unit | backoff observed | PASS |
| TC-4 | nse_fetcher | 403 clears the cookie jar before re-priming | unit | jar.clear() called | PASS |
| TC-5 | nse_fetcher | Persistent 403 is bounded and still raises | edge | raises after HTTP_RETRY_ATTEMPTS | PASS |
| TC-6 | nse_fetcher | 404 stays terminal (bhavcopy not yet published) | failure | raises, 1 request only | PASS |
| TC-7 | nse_fetcher | Non-NSE host 403 stays terminal | failure | raises, 1 request only | PASS |
| TC-8 | delivery | propagate_to_prices_eod fills deliv_pct for a day | data | >0 rows updated, values sane | PASS |
| TC-9 | delivery | deliv_pct equals deliv_qty/volume from source | data | arithmetic cross-checks | PASS |
| TC-10 | delivery | Full backfill across all delivery_data days | data | prices_eod deliv_pct >0% | PASS |
| TC-11 | shareholding | Genuine quarter ends are preserved | unit | unchanged | PASS |
| TC-12 | shareholding | Interim month ends rejected, not snapped | unit | recognised as non-quarter | PASS |
| TC-13 | shareholding | Leap-year Feb 29 maps to prior Dec quarter | edge | 2023-12-31 | PASS |
| TC-14 | regression | Existing suite unchanged by these edits | regression | same pass/fail as baseline | PASS |
| TC-15 | blocked | NSE fetch succeeds for fii_dii/bhavcopy | api | 200 + rows | **BLOCKED** (see below) |

## Evidence

### TC-1 — disk / MinIO
```
=== BEFORE ===
/dev/sda1        79G   78G  533M 100% /
=== docker builder prune ===   Total: 8.648GB
=== journal vacuum ===         freed 644.1M of archived journals
=== AFTER ===
/dev/sda1        79G   71G  7.7G  91% /
```
MinIO after restart: `nidp-minio Up 8 seconds`, `/data ... 7.7G Avail`.
Prior failure this repaired: `nse_shareholding FAILED — ClientError: An error occurred
(XMinioStorageFull) when calling the PutObject operation: Storage backend has reached its ...`

### TC-2..TC-7 — nse_fetcher unit tests (and proof they are a real gate)
```
=== ORIGINAL code (fix stashed) ===
FAILED nidp/tests/shared/sources/test_nse_fetcher_retry.py::test_403_recovers_after_several_attempts
FAILED nidp/tests/shared/sources/test_nse_fetcher_retry.py::test_403_backs_off_between_attempts
FAILED nidp/tests/shared/sources/test_nse_fetcher_retry.py::test_403_clears_cookie_jar_before_repriming
FAILED nidp/tests/shared/sources/test_nse_fetcher_retry.py::test_403_is_bounded_and_still_fails_loudly
4 failed, 2 passed in 0.30s
=== FIX restored ===
......                                                                   [100%]
6 passed in 0.19s
```
The 2 passing in both are the must-stay-terminal guards (404, non-NSE 403) — the fix did not
over-loosen the retry policy.

### TC-8 / TC-9 — delivery → prices_eod, single day
```
BEFORE 2026-08-11: prices_eod rows=3483 deliv_pct filled=0
propagate_to_prices_eod returned: 3033
AFTER  2026-08-11: rows=3483 filled=3033 avg=62.74 min=0.0000 max=100.0000
   20MICRONS      vol=68836        deliv_qty=38375        deliv_pct=55.7500
   360ONE         vol=477268       deliv_qty=230844       deliv_pct=48.3700
```
Cross-check: 38375/68836 = 55.75% ✓ · 230844/477268 = 48.37% ✓ — the join grain is correct.

### TC-10 — full backfill
```
days to propagate: 40 (2026-05-27 .. 2026-08-11)
TOTAL prices_eod rows updated: 109557
prices_eod overall: rows=422266 deliv_pct filled=112590 (26.66%) across 38 days
```
Final DB state (data test):
```
 deliv_pct_filled_pct | rows_filled | days_covered | avg_deliv_pct
                26.66 |      112590 |           38 |         61.30
```
26.66% is the ceiling because `delivery_data` only spans 38 of prices_eod's 125 days — that is the
delivery feed's own history depth, not a defect in this fix.

### TC-11..TC-13 — shareholding quarter grain
```
20 passed in 0.27s
```
(covers `test_shareholding_quarter_guard.py` + `test_nse_fetcher_retry.py`)

### TC-14 — regression baseline
```
=== BASELINE (my 4 source edits stashed) ===
38 failed, 336 passed, 5 skipped, 21 warnings in 5.27s
=== WITH MY FIXES ===
38 failed, 336 passed, 5 skipped, 21 warnings in 5.19s
```
Identical. All 38 failures pre-date this work (missing `fastapi`/`fastavro` collection errors and
unrelated suites). With the 20 new tests included the run is `356 passed`.

### TC-15 — BLOCKED: NSE edge block
```
$ curl -A '<Chrome UA>' https://www.nseindia.com/                              HTTP 403
$ curl -A '<Chrome UA>' https://nsearchives.nseindia.com/.../BhavCopy_...zip   HTTP 403
$ curl -A '<Chrome UA>' https://www.nseindia.com/api/marketStatus              HTTP 403
$ curl -A '<Chrome UA>' https://archives.nseindia.com/                         HTTP 403
egress IP: 34.93.60.254
5 attempts, 6s apart, all HTTP 403
```
The cookie *prime* itself 403s, so this is IP reputation at Akamai, not a cookie/UA problem. Same
VM succeeded at 2026-08-17 19:00 (`bhavcopy OK 3626 rows`), so the block is transient but currently
active. Non-NSE sources from the same host are healthy: bseindia.com 200, fpi.nsdl.co.in 200.

## Unverified / Out of scope
- **UNVERIFIED:** the nse_fetcher fix cannot be proven against live NSE while the IP block is
  active. It is proven at unit level (TC-2..TC-7) against the exact 403 sequence observed in
  `job_log`. Re-run `bhavcopy`/`fii_dii` once egress is unblocked to confirm end to end.
- **NOT FIXED:** `mf_holdings` (#8) — ~10 AMC scrapers drifted (`hdfc: all listing pages failed`,
  `sbi/icici_pru/kotak/axis/mirae: no listing candidate yielded a match`, `quant: unresolved fund
  name`). Per-site work, needs live iteration per AMC.
- **NOT FIXED:** `shareholding_pattern.mf_pct` / `insurance_pct` are 0% populated (DII
  decomposition). Source confirmed available at NSDL (see below) but not built.
- `amc_urls_drift_check`'s 126 "failures" are a **true-positive alarm** firing as designed
  (`AMC URL drift detected — 5 target(s) have zero healthy candidates`), not a broken feed.

## Verdict: PASS
