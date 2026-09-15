# Functionality Verification Report — best-case fixes for the open issues

- **Branch:** feat/research-qa-exercise (uncommitted working tree)
- **Date:** 2026-08-19
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend routes/services: **yes** · frontend src: no

## Summary
Pass over every issue left open by the earlier feed-repair and NSE→NSDL/BSE migration work.
Seven were fixed and verified; three are reported with evidence and a decision left to the owner
because the fix would trade one problem for a bigger one.

The single most important finding is not a code bug: **none of the previous fixes were in effect on
schedule.** Cron runs from `/opt/nidp/dev-repo/nivesh.ai`; all the work lives in `/app`. That is why
`bhavcopy` and `fii_dii` still recorded FAILED at 19:01 on 2026-08-18 instead of falling back.

## Test Cases

| ID | Issue | Fix | Type | Result |
|----|-------|-----|------|--------|
| TC-1 | BSE volume corrupts vol_z20 / accumulation pillar | source-aware masking | unit | PASS |
| TC-2 | Missing delivery coerced to a real 0% | NaN, not zero | unit | PASS |
| TC-3 | `drop_bse_gapfill_for` never exercised | live run | e2e | PASS |
| TC-4 | `drop_bse_delivery_gapfill_for` never exercised | live run | e2e | PASS |
| TC-5 | fii_dii missing 14 trading days | NSDL archive backfill | e2e | PASS |
| TC-6 | index_close 253 / amfi_nav 85 cryptic failures | write-target guard | unit+e2e | PASS |
| TC-7 | 24 job_log rows stranded in RUNNING | stale-run reaper | unit+e2e | PASS |
| TC-8 | disk alarm sent 123+ identical emails | throttle + escalation | unit | PASS |
| TC-9 | analytics chain "stalled" since Aug 15 | diagnosis | e2e | PASS (not a fault) |
| TC-10 | regression unchanged | full suite | regression | PASS |

## Evidence

### TC-1 / TC-2 — indicators no longer trust cross-exchange volume
`_fetch_price_history` filtered on `series='EQ'` with **no source filter**, so BSE gap-fill days
entered the 20-day volume baseline at roughly a tenth of NSE volume — reading as a volume collapse
and firing false distribution signals. Separately `COALESCE(deliv_pct, 0.0)` in SQL and
`float(r["deliv_pct"] or 0)` in `_to_arrays` turned a *missing* delivery figure into a real 0%,
dragging `deliv_pct_avg_20` down — while `delivery_stats` was already NaN-aware and being defeated.

Fix: volume/delivery are masked to NaN for non-NSE sources and for genuinely missing values;
`volume_stats` became NaN-aware with a minimum-comparable-bars floor. Prices from BSE bars are
still used — price continuity is the point of the fallback.
```
12 passed in 0.16s
```
Tests pin both directions, including `test_zero_coercion_would_have_broken_it` and
`test_delivery_avg_would_be_wrong_with_zeros`, which fail if the old behaviour returns.

### TC-3 / TC-4 — the NSE-precedence deletes, previously UNVERIFIED
```
BEFORE  prices_eod BSE rows for 2026-08-14: 2735
BEFORE  delivery   BSE rows for 2026-08-14: 2735
drop_bse_gapfill_for          -> 2735
drop_bse_delivery_gapfill_for -> 2735
AFTER   prices_eod BSE rows for 2026-08-14: 0
AFTER   delivery   BSE rows for 2026-08-14: 0
second call (idempotence)     -> prices=0 delivery=0
CONTROL 2026-08-13 still has  : prices=2754 delivery=2754
```
Exact deletion, idempotent, control day untouched. Both days were then re-filled
(`inserted=2735` each) so no data was left removed.

### TC-5 — fii_dii gap closed from the NSDL archive
`Archive.aspx` is an ASP.NET postback: `__EVENTTARGET=btnSubmit1`, date in `hdnDate` (`txtDate` is
disabled in the DOM and is not posted). Date format matters — `05-08-2026` is read as 08-May-2026.
```
fii_dii backfill: 16 missing day(s): 2026-06-15 ... 2026-08-14
fii_dii_flows upserted 120 rows
fii_dii backfill: wrote 120 row(s) covering 16 day(s); still missing: none
```
Coverage (data test):
```
 trading_days | days_with_fii_dii | still_missing
           49 |                49 |             0
```
Was 33 of 47. The parser now reads each row's own Reporting Date, so one parser serves both the
single-day Latest page and the multi-day Archive.

### TC-6 — index_close / amfi_nav
`nidp.index_eod` and `nidp.mf_nav_daily` are pass-through VIEWS over **FDW foreign tables** into
production. A foreign table has no unique constraint, so `INSERT ... ON CONFLICT` can never work:
```
InvalidColumnReferenceError: there is no unique or exclusion constraint matching the ON CONFLICT specification
```
253 and 85 consecutive identical failures, neither ingester having ever succeeded.
```
index_close: nidp.index_eod is a view over prod_data.index_eod (f), prod_nidp.index_eod (f), not a
  writable table — an upsert cannot match a conflict target here. Reads still work; this
  environment sources the data elsewhere.
job_log[index_close] status=SKIPPED fetched=0 inserted=0 duration=73ms
job_log[amfi_nav]    status=SKIPPED fetched=0 inserted=0 duration=68ms
```
Guard verified against real relations — critically including the negative controls:
```
  nidp.index_eod            -> view over prod_data.index_eod (f) ...
  nidp.mf_nav_daily         -> view over prod_data.mf_nav_daily (f) ...
  nidp.prices_eod           -> OK (writable)
  nidp.delivery_data        -> OK (writable)
  nidp.fii_dii_flows        -> OK (writable)
  nidp.shareholding_pattern -> OK (writable)
```
A near-miss caught by those controls: asyncpg returns postgres `"char"` as **bytes**, so relkind
arrives as `b'r'`. Un-decoded it matches no branch and would have flagged every healthy table as
unwritable, silently stopping working feeds. Pinned by `test_write_target_guard`. `10 passed`.

### TC-7 — stale RUNNING rows
24 job_log rows were stranded in RUNNING with no live process, the oldest 2,026 hours (85 days).
Because `v_feed_status` reports each ingester's *latest* run, a stranded latest row makes a dead
feed look busy, so no staleness alarm can fire — the failure hides itself.
```
reaped 17 abandoned RUNNING job_log row(s) older than 6h: announcement_classifierx1,
  corporate_announcements_nsex1, document_parserx10, intelligence_layerx3,
  mf_derived_refreshx1, price_adjusterx1
 stale_running
             0
```
Rows younger than the threshold were correctly left alone. History stays honest — `finished_at` is
derived from `started_at`, not `now()`:
```
 price_adjuster | FAILED | 2026-05-26 16:21 | 2026-05-26 22:21 | abandoned: still RUNNING 6h after start ...
```
Wired into `feed_health_check` (already runs every 30 min), inside a try/except so maintenance can
never break the health check. `8 passed`.

### TC-8 — the disk alarm was not broken, it was ignorable
The 2026-08 disk-full outage — which took out MinIO, `nse_shareholding` and the nightly analytics
chain — **was detected correctly and emailed 123+ times**:
```
    123 notify.send_email: sent '🔴 CRITICAL NIDP disk low: / 2.4% free, /mnt/nidp-nfs 1.8% free' to ['aporwal107@gmail.com']
    123 disk_monitor: 2 breach(es) — alerted: ['/=2.4%', '/mnt/nidp-nfs=1.8%']
     21 notify.send_email: sent '🔴 CRITICAL NIDP disk low: / 1.2% free, /mnt/nidp-nfs 0.4% free' ...
```
One identical email every 10 minutes for days is what makes an alert ignorable. Fix: alert
immediately on a new or escalated situation, then at most once per window (default 6h,
`NIDP_DISK_REALERT_HOURS`). Deliberately fails *open* — if the state file cannot be written
(exactly what a full disk causes) it alerts rather than going silent. `8 passed`.

### TC-9 — the "stalled analytics chain" was not a fault
Cron is healthy and the evening chain did run on 2026-08-18. The Aug 15→18 gap was Aug 16/17
falling outside the `* * 2-6` schedule plus the Aug 18 disk-full window. Run manually it completes
in ~1s and records normally:
```
[2026-08-19T02:00:46+05:30] starting analytics_refresh
[2026-08-19T02:00:47+05:30] analytics_refresh OK
 08-19 02:00:47 | OK | 0 |
```
No fix required; the earlier "6 daily jobs silently not firing" reading was wrong.

### TC-10 — regression
```
38 failed, 440 passed, 5 skipped, 21 warnings in 5.29s
```
Same 38 pre-existing failures as the recorded baseline. Passes rose 336 (session baseline) → 440;
94 new tests, all green:
```
  test_nse_fetcher_retry            6      test_bse_delivery_fallback      10
  test_shareholding_quarter_guard  14      test_indicator_source_awareness 12
  test_nsdl_fii_dii_parser         17      test_write_target_guard         10
  test_bse_bhavcopy_fallback        9      test_reap_stale_runs             8
  test_disk_monitor_throttle        8
```

## Not fixed — decisions that are not mine to make

- **🔴 Nothing is deployed.** Cron executes `/opt/nidp/dev-repo/nivesh.ai` (HEAD 86ff3d69); all this
  work is in `/app` (HEAD 72d7e1fd). `nsdl_parser.py`, `bse_fetcher.py`, `bse_parser.py` are absent
  from the deployed checkout. Verified by running everything with `PYTHONPATH=/app/backend`. Until
  this lands on the deployed branch, the scheduled runs keep failing exactly as before.
- **`nse_shareholding` BSE fallback — partial only.** Real endpoints found (previous report said
  none): `Corp_shpSec_shpqtrinfo_ng` returns the quarter list (`qtrid=130.00` = June 2026);
  `CorporatesSHPSecuritybeta` returns the A/B/C split with real data (RELIANCE: promoter 50.48%,
  public 49.52%); `Corp_ShpPromoters_ng` returns promoter names + pledge. But
  `Corp_shpSec_SHPPubShold_ng` — the one carrying "Institutions (Domestic)" / "(Foreign)", i.e. the
  DII/FII split this feed exists for — returns the category skeleton with **all values zero**, on
  every quarter tried (127–130). A fallback built on this would deliver promoter/public and not the
  FII/DII columns. Not built, on purpose.
- **`index_eod` / `mf_nav_daily` drift not reversed.** Converting the views to local tables would
  cut consumers off from **21.7M NAV rows and 12,350 index rows** currently read through FDW by at
  least 8 modules (sector_analysis, fund_performance, copilot backtest, …). The guard makes the
  failure honest; reversing the drift needs a backfill plan and an owner decision on the
  staging↔prod split.
- **Disk still at 93%** (6.1G free of 79G — under `disk_monitor`'s own 10% CRITICAL threshold).
  Build cache and journals are already reclaimed; the remaining 10.17GB is **locally-built** images
  (`nivesh/backend:laptop` 4.23GB, `nidp/runtime-ai:laptop` 2.51GB, `nidp-whisper:small` 2.33GB —
  the earnings-call transcription tier, `nidp-laptop-{query,daas}-api` 1.36GB each). Those need a
  rebuild, not a re-pull, so they were not deleted. ~1.7GB in registry-pullable images
  (`mongo:7`, `postgres:16-alpine`, `nginx:1.27-alpine`) is safely reclaimable on request.
- **`mf_holdings` AMC drift** unchanged — ~10 bespoke scrapers, per-site work.

## Verdict: PASS
