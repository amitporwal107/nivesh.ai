# OVERRIDE — NSE egress fix implemented, NOT proven end-to-end

REASON: The fix requires an egress that is not the blocked IP. Both ways of
supplying one need the user's authorisation, and both were denied this turn:
(1) starting a proxy listener on `nivesh-app-vm` was blocked by the permission
classifier — reasonably, since that host serves the live application; (2) swapping
`nidp-stack-vm`'s reserved static IP would change the Cloudflare origin for
`staging-data.niveshcopilot.com`, which is not mine to do unasked. The code change is
complete, unit-tested, and verified not to regress the direct path.

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-19
- **Changed:** `backend/nidp/shared/config.py`, `backend/nidp/shared/sources/nse_fetcher.py`,
  `backend/nidp/tests/services/test_nse_fetcher_proxy.py` (new)

## Root cause — proven, not inferred

NSE blocks by SOURCE IP. Identical request, identical headers, two VMs in the same
region and project, seconds apart:

```
nidp-stack-vm   egress 34.93.60.254   403  https://www.nseindia.com/api/allIndices
                                      403  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18082026.csv
nivesh-app-vm   egress 34.47.250.214  200  https://www.nseindia.com/api/allIndices
                                      200  https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_18082026.csv
```

The block covers the whole NSE estate — `www`, `nsearchives`, and `niftyindices.com`
all 403 — while `www.bseindia.com` returns 200 from the same host. So no UA, cookie,
Referer or retry work can fix it, and there is no NSE URL that can be substituted.
One egress change fixes all the NSE-dependent feeds at once.

## What IS verified

- 14 unit tests pass (`test_nse_fetcher_proxy.py`), holding the property that matters:
  the proxy reaches NSE hosts and **never** BSE, RBI, AMFI or NSDL. BSE is the
  fallback that keeps prices and delivery flowing while NSE is blocked; routing it
  through a proxy would put a single point of failure in front of the escape hatch.
- Default is unset = direct, so the change is a no-op until deliberately configured.
- No regression on the direct path, run on staging with the change in place:

```
"msg":"bse delivery gapfill: wrote 2733 row(s)"
"msg":"job_log[delivery] ce9d8c2a-… status=OK fetched=4929 inserted=2733 skipped=0 duration=14363ms"
```

## What is NOT verified

- **No request has yet been proven to reach NSE through the proxy**, because no proxy
  was allowed to run. The path is untested against a live NSE response.
- `NSE_MIN_REQUEST_INTERVAL_S` (default 0.35s) is unit-tested but has not run against
  NSE, so whether that rate keeps a fresh IP unblocked is unknown.

## Corrections to the earlier feed triage

- **`delivery` is not broken.** Its BSE fallback works — 2,733 rows for 2026-08-18.
  Its FAILED status is the run for *today*, whose BSE file is not published yet.
- **`bhavcopy` is green** daily via the same fallback, which is why `prices_eod` and
  `delivery_data` stay ~1 day fresh while their NSE feeds show red.
- Genuinely broken and needing NSE: `bulk_deals`, `block_deals`, `fno_bhavcopy`,
  `index_close`, `corporate_announcements_nse`.
- `index_close` (259 failures) and `amc_urls_drift_check` (130) have never once
  succeeded — `last_success_at` is NULL for both. `index_close` cannot be fixed by a
  BSE fallback at all: BSE does not publish the Nifty family.

## To clear this override

Choose an egress and say so, then this is a config flip plus one verification run:

1. **Proxy on nivesh-app-vm** — no IP or DNS change; risk is that the live app's IP
   earns the same block, since the block was almost certainly earned by request volume.
2. **New static IP for nidp-stack-vm** — clean separation, but the Cloudflare origin
   for `staging-data.niveshcopilot.com` must be repointed in the same maintenance window.
3. **A dedicated small egress VM** — costs a little, keeps both the app IP and the
   staging origin untouched. My recommendation.
