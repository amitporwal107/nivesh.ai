# OVERRIDE — Pipeline panel: trading-day-aware freshness (remove weekend false alarm)

- **Branch:** `fix/pipeline-trading-day-freshness` (worktree off `origin/dev`, NOT merged, NOT deployed)
- **Date:** 2026-07-19
- **Changed areas:** backend `nidp/services/query_api/routers/pipeline.py`: **yes** · frontend: **no**

## REASON: the staging leg cannot be run this session. `gcloud compute ssh nidp-stack-vm --tunnel-through-iap` was denied by the Claude Code auto-mode permission classifier, and I have no DaaS `/query` bearer token, so `GET /pipeline/stages` could not be called against real staging data. I did NOT fabricate a staging result. Everything below is real local output. The change is unmerged and undeployed, so nothing is live on the strength of this report.

## What changed and why

Two bugs in the same freshness rule, pulling in opposite directions:

1. **False RED (the reported symptom).** Ingesters run `*/10 9-23 * * 1-5` (weekdays only). Friday 23:50 → Sunday 17:51 is 41.9h wall-clock against a 24h budget, so Ingest/Classify/Discover went `stale` every weekend. Observed on staging 2026-07-19: `0 healthy · 3 lagging · 3 stale`.
2. **False GREEN (found while fixing #1).** `corporate_announcements/writer.py:30-44` does `ON CONFLICT ... DO UPDATE SET ingested_at = NOW()`, so `max(ingested_at)` advances on every **re-seen** row. The Ingest tile was measuring "the cron touched a row", not "new data arrived" — a feed weeks behind on filings read healthy indefinitely.

Fix: market-driven stages (Ingest/Classify/Discover) measure **trading time**, discounting weekends and `nidp.nse_holidays`. Ingest additionally keys off `max(filed_at)` vs the last NSE close (`nidp.compute_last_trading_day_ist()`) instead of `max(ingested_at)` vs `now()`. Parse/Chunk/Embed keep wall-clock budgets — they grind 7 days a week.

Rejected: raising `_LAG_BAD_H` 24h→72h. It clears the weekend red and makes the false green permanent. Pinned as a test (`test_a_72h_threshold_would_have_missed_it`).

## Test cases (authored against the observed staging state, then run locally)

| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TF-1 | Ingest, current through Friday, evaluated Sunday | healthy, 0 trading days behind | **PASS** |
| TF-2 | Classify idle all weekend (41.2h wall) | not stale → `backlog` (16,389 pending) | **PASS** |
| TF-3 | Discover idle all weekend (31.8h wall) | healthy | **PASS** |
| TF-4 | All six stages at the screenshotted moment | `stale` count == 0 | **PASS** |
| TF-5 | Feed dead Mon 09:00 → Wed 17:00 | still `stale` (detection preserved) | **PASS** |
| TF-6 | A 72h threshold on TF-5 | would read healthy — why it was rejected | **PASS** |
| TF-7 | One / two missed trading sessions | `lagging` / `stale` | **PASS** |
| TF-8 | Feed 51 days behind on filed_at, fresh ingested_at | `stale`, not healthy (false-green guard) | **PASS** |
| TF-9 | NSE holiday mid-span | holiday hours/days not counted | **PASS** |
| TF-10 | Naive / UTC / future / epoch timestamps | UTC-assumed, IST-bucketed, no negative, terminates | **PASS** |
| EP-1 | Full `pipeline_stages()` — no swallowed exception | `db_error is None`, 6 stages | **PASS** |
| EP-2 | Weekend state end-to-end | `summary.stale == 0` | **PASS** |
| EP-3 | Ingest state not driven by `ingested_at` | `age_hours` would be stale; `state == healthy` | **PASS** |
| EP-4 | Parse/Embed unchanged | still `lagging` at 7.5h | **PASS** |
| EP-5 | `nidp.nse_holidays` missing | degrades to weekday-only, panel not blank | **PASS** |

`EP-*` drive the real `pipeline_stages()` through a stubbed connection. This matters because the endpoint wraps its body in `except Exception` — a `NameError` in my edit would be swallowed into `db_error` and helper-level tests would still pass. Every `EP-*` assertion is gated on `db_error is None`.

## Real output

```
$ /opt/nidp/venv/bin/python -m pytest nidp/tests/test_pipeline_freshness.py \
      nidp/tests/test_pipeline_stages_endpoint.py -q
............................                                             [100%]
28 passed in 1.13s
```

Regression check — full `nidp/tests/` suite, my branch vs pristine `origin/dev`:

```
with changes:  29 failed, 277 passed, 5 skipped, 16 warnings in 21.18s
baseline:      29 failed, 249 passed, 5 skipped, 16 warnings in 17.57s   (git stash push -u)
```

Same 29 failures both sides (`test_dynamic_runner`, `test_mf_amc_robustness`, `test_failing_feeds_golden`, `test_feed_registry_drift` — all pre-existing, none touch this module). Delta is +28 passing = the new tests. **Zero regressions introduced.**

## NOT verified — do not treat as done

- **UNVERIFIED: no staging call.** `GET /pipeline/stages` was never hit against real data. The stub encodes what I believe the rows look like; it is not proof the live SQL returns them.
- **UNVERIFIED: `nidp.compute_last_trading_day_ist()` and `nidp.nse_holidays` were read from migration `023_nidp_market_session.sql`, not queried.** If `nse_holidays` is unpopulated on staging, the fallback silently degrades to weekday-only — correct behaviour, but it means holidays would go unnoticed. Worth one query to confirm the table has rows.
- **UNVERIFIED: no Playwright run.** No frontend file changed — `PipelinePanel.tsx` reads `s.state` and `s.age_hours`, both preserved, and the new fields (`trading_days_behind`, `trading_age_hours`, `last_close`, `latest_filed`) are additive. That is from reading the component, not from running it.
- The 7.5h `lagging` on Parse/Chunk/Embed is **unchanged and unexplained** — likely the 2,228 in-window pending cycling into the 2,632 failed-retrying pool. Separate issue, not addressed here.

## Next step to close this out properly

Run against staging once access is available:

```
GET /pipeline/stages   →  expect summary.stale == 0 on a weekend,
                          ingest.trading_days_behind == 0,
                          ingest.age_hours > 24 (display unchanged)
```

Then re-check on a Tuesday to confirm weekday detection still fires.
