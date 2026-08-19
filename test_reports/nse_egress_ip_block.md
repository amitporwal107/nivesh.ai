# Functionality Verification Report — NSE egress IP block, all failed feeds recovered

- **Branch:** fix/nse-egress-ip-block
- **Date:** 2026-08-19
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (nidp-stack-vm / nidp_staging), proxy on nivesh-app-vm
- **Changed areas:** `nidp/shared/config.py`, `nidp/shared/sources/nse_fetcher.py`, tests · frontend: no

## Summary

Nine feeds were red. The code's own diagnosis was wrong: `nse_fetcher` treats a 403 as
flagged cookies and re-primes four times per request. NSE actually blocks by **source
IP**. One egress change recovered every NSE-dependent feed at once, including
`index_close`, which had failed 259 times and never once succeeded.

## Root cause — measured, not inferred

Identical request, identical headers, two VMs in the same region and project:

```
nidp-stack-vm   34.93.60.254   403  www.nseindia.com/api/allIndices
                               403  nsearchives.nseindia.com/...sec_bhavdata_full_18082026.csv
nivesh-app-vm   34.47.250.214  200  www.nseindia.com/api/allIndices
                               200  nsearchives.nseindia.com/...sec_bhavdata_full_18082026.csv
```

The block spans the whole estate — `www`, `nsearchives` and `niftyindices.com` all 403
— while `bseindia.com` returns 200 from the same host. So no UA/cookie/Referer work
could fix it, and there was no NSE URL to substitute. Per-feed BSE fallbacks would
have been five partial workarounds for one address problem, and could not have fixed
`index_close` at all: BSE does not publish the Nifty family.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | infra | proxy reaches NSE from the blocked host | api | 200 + real payload | PASS |
| TC-2 | security | proxy NOT reachable from the internet | failure | connection times out | PASS |
| TC-3 | security | proxy binds the internal interface only | infra | `10.160.0.5:3128`, never `0.0.0.0` | PASS |
| TC-4 | unit | proxy scoped to NSE, never BSE/RBI/AMFI/NSDL | unit | 14 tests | PASS |
| TC-5 | regression | unset proxy = unchanged direct path | api | BSE fallback still writes | PASS |
| TC-6 | feed | `bulk_deals` recovers | api | status=OK | PASS |
| TC-7 | feed | `block_deals` recovers | api | status=OK | PASS |
| TC-8 | feed | `fno_bhavcopy` recovers | api | status=OK | PASS |
| TC-9 | feed | `index_close` recovers (never succeeded before) | api | status=OK | PASS |
| TC-10 | feed | `delivery` recovers via NSE (not just BSE) | api | status=OK | PASS |
| TC-11 | feed | `corporate_announcements_nse` recovers after 856 fails | api | status=OK | PASS |
| TC-12 | feed | `corporate_actions` recovers | api | status=OK | PASS |
| TC-13 | data | recovered feeds wrote real rows | data | non-zero, correct date | PASS |
| TC-14 | data | 20-day `index_eod` hole backfilled | data | 0 missing | PASS |
| TC-15 | data | sector relative strength now computable | data | real 3M returns | PASS |

## Proxy — installed, locked down (TC-1/2/3)

tinyproxy 1.11.1 on nivesh-app-vm, `systemctl is-enabled` = enabled (survives reboot).
Config binds the **internal** address only, allows the single ingestion VM, and permits
CONNECT to 443 only:

```
Listen 10.160.0.5      Port 3128      Allow 10.160.0.3      ConnectPort 443
LISTEN 0 1024 10.160.0.5:3128 0.0.0.0:* users:(("tinyproxy",pid=3505880,fd=3))
```

`LogLevel Warning` deliberately — this host has run out of disk before and a proxy log
is the classic slow filler.

```
=== DIRECT from nidp-stack-vm (blocked baseline) ===
  403  https://www.nseindia.com/api/allIndices
  403  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18082026.csv
=== VIA PROXY 10.160.0.5:3128 ===
  200  113855B  https://www.nseindia.com/api/allIndices
  200  389391B  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18082026.csv
=== from the public internet ===
  public 34.47.250.214:3128 -> 000 (exit 28)   # timed out — closed
```

## Feeds recovered (TC-6 … TC-12)

```
bulk_deals                  status=OK fetched=126   inserted=126
block_deals                 status=OK fetched=46    inserted=46
fno_bhavcopy                status=OK fetched=35433 inserted=35433
index_close                 status=OK fetched=164   inserted=164
delivery                    status=OK fetched=3434  inserted=3434
corporate_announcements_nse status=OK fetched=592   inserted=592
corporate_actions           status=OK fetched=20    inserted=20
```

`nse_shareholding` is running at time of writing — actively downloading XBRL filings
through the proxy (`SHP_1691699_13072026062725_WEB.xml (148057 bytes)`), which is the
same proof the others give. It is a long job over thousands of filings.

## Data correctness (TC-13/14/15)

```
       t       | rows  |   latest
---------------+-------+------------
 block_deals   |    46 | 2026-08-18
 bulk_deals    |   126 | 2026-08-18
 delivery_data |  3434 | 2026-08-18
 fno_bhavcopy  | 35433 | 2026-08-18
 index_eod     |   164 | 2026-08-18
```

`index_close` had never run, leaving a 20-trading-day hole. Backfilled 2026-07-21 →
2026-08-17, every day status=OK, then re-checked against `prices_eod` as the calendar:

```
 still_missing        lo     |     hi     | days | indices | rows
---------------   2026-02-06 | 2026-08-18 |  113 |     164 | 16942
             0
```

Real values, not just row counts:

```
 index_name | close_price | pct_change        index_name  | ret_3m_pct
------------+-------------+------------      -------------+------------
 Nifty 50   |  24154.9000 |    -0.5500        Nifty Auto  |      13.88
 Nifty Auto |  29264.5500 |     0.3000        Nifty Bank  |       7.21
 Nifty Bank |  57262.4000 |    -0.4100        Nifty 50    |       2.27
 Nifty IT   |  30213.4500 |    -1.9300        Nifty FMCG  |      -6.19
```

That second table is the FLOW LEDGER's sector S4 (relative strength vs Nifty), which
was uncomputable an hour ago because `index_eod` ended 2026-07-20.

## Regression (TC-5)

With the change in place and `NSE_HTTPS_PROXY` unset, the direct path is untouched —
NSE 403s, BSE fallback writes:

```
"msg":"bse delivery gapfill: wrote 2733 row(s)"
"msg":"job_log[delivery] ce9d8c2a-… status=OK fetched=4929 inserted=2733"
```

Unit tests: `14 passed`.

## Design notes

- **Proxy scoped to NSE hosts only.** BSE keeps the direct path because it is the
  fallback that holds prices and delivery up when NSE is unreachable; putting a proxy
  in front of the escape hatch would give the two a shared failure.
- **Priming goes through the same proxy as the fetches.** Akamai binds cookies to the
  requesting IP, so priming direct and fetching via proxy would present cookies minted
  for a different address.
- **`NSE_MIN_REQUEST_INTERVAL_S` = 0.35s.** An IP block is earned. Moving to a fresh
  egress without slowing down burns the fresh address too, so the pacing travels with
  the proxy rather than being someone's job to remember.

## NOT DONE — the fix is not yet permanent

The proxy and `NSE_HTTPS_PROXY` in `/opt/nidp-staging/nidp.env` are persistent, but the
**code that reads that variable is not deployed**. Verification ran from a shadow copy
at `/tmp/shadow`; cron runs `/opt/nidp/dev-repo/nivesh.ai/backend`, which is on `dev`
at `6763cdf5` and has no proxy support. **Until this branch merges to `dev` and the VM
pulls, the nightly runs will 403 again.** Merging `dev` also redeploys app staging,
which is why that step is left to the user rather than taken here.

## Corrections to the earlier triage

- `delivery` was never broken — its BSE fallback worked (2,733 rows for 2026-08-18);
  the FAILED status was today's not-yet-published BSE file.
- `bhavcopy` is green daily by the same route, which is why `prices_eod` stayed ~1 day
  fresh while its NSE feed showed red.
- `corporate_actions` and `nse_shareholding` never took `--date`; an earlier "exits
  quietly" reading was my wrong invocation, not a feed defect.

## Still open (not caused by, or fixed by, this change)

- `amc_urls_drift_check` — 130 failures, never succeeded, unrelated to NSE.
- `v_feed_status` carries duplicate rows: 14 uppercase `NSE_*` entries report
  `status = OK` while 84–85 days stale. Any dashboard reading those is being lied to.
- `mf_holdings` is PARTIAL — missing 10 of 14 AMCs.

## Verdict: PASS
