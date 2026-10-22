# Functionality verification — Sensibull FII/DII ingest

**Date** 2026-10-22 · **Target** staging (NIDP VM 45.64.105.224)
**Changed code** `backend/nidp/services/sensibull_fii_dii/{__init__,__main__,service}.py` (new service)
**Test cases** authored before implementation: `test_reports/sensibull_fii_dii_TESTCASES.md`

No API routes and no frontend were touched, so there is no endpoint test and no Playwright run.
Verification is three real staging executions against the real warehouse and the live source.

## Real staging output

```
cd /opt/nidp/tl-run/backend && \
  /opt/nidp-staging/venv/bin/python -m nidp.services.sensibull_fii_dii
```
```
sensibull_fii_dii: anonymous platform token minted
sensibull_fii_dii: key_list ['2026-April','2026-May','2026-June','2026-July','2026-August',
                             '2026-September','2026-October']; fetching 7 month(s)
sensibull_fii_dii[2026-April]: 300 rows      ... [2026-October]: 315 rows
sensibull_fii_dii: monthly series 196 rows
coverage[SENSIBULL]:         2026-04-01..2026-10-21  138 date(s) held, 138 session(s) in span, 0 MISSING
coverage[SENSIBULL_MONTHLY]: 2018-09-01..2026-10-01   98 date(s) held, monthly series, no session gaps expected
coverage[NSE_FII_DII]:       2026-10-09..2026-10-21    8 date(s) held, 8 session(s) in span, 0 MISSING
{"months_available":7,"months_fetched":7,"months_failed":0,
 "daily_rows":2190,"monthly_rows":196,"rows_written":2386}
```

## What landed

```
      source       |    segment     | rows | cats |   first    |    last
-------------------+----------------+------+------+------------+------------
 NSE_FII_DII       | EQUITY_CASH    |   16 |    2 | 2026-10-09 | 2026-10-21
 SENSIBULL         | EQUITY_CASH    |  276 |    2 | 2026-04-01 | 2026-10-21
 SENSIBULL         | FUT_BANKNIFTY  |  138 |    1 | 2026-04-01 | 2026-10-21
 SENSIBULL         | FUT_FINNIFTY   |  138 |    1 | 2026-04-01 | 2026-10-21
 SENSIBULL         | FUT_MIDCPNIFTY |  138 |    1 | 2026-04-01 | 2026-10-21
 SENSIBULL         | FUT_NIFTY      |  138 |    1 | 2026-04-01 | 2026-10-21
 SENSIBULL         | FUT_NIFTYNXT50 |  138 |    1 | 2026-04-01 | 2026-10-21
 SENSIBULL         | INDEX_FUTURES  |  552 |    4 | 2026-04-01 | 2026-10-21
 SENSIBULL         | INDEX_OPTIONS  |  552 |    4 | 2026-04-01 | 2026-10-21
 SENSIBULL_MONTHLY | EQUITY_CASH    |  196 |    2 | 2018-09-01 | 2026-10-01
```

## Case-by-case result

- **T1 PASS** — token minted; the service raises and writes nothing if the cookie is absent.
- **T2 PASS** — the no-param call ran first and `key_list` drove the 7 months. No hard-coded list.
- **T3 PASS** — requests show `?year_month=2026-April` … the month-name form throughout.
- **T4 PASS** — `Origin` is in `_HEADERS`; removing it reproduces `access denied`.
- **T5 PASS** — 276 `EQUITY_CASH` rows = 138 dates × 2 categories, buy/sell/net populated.
- **T6 PASS** — `net = buy − sell` on every cash row: **0 violations** across all three sources,
  worst absolute discrepancy **0.0001** (float precision).
- **T7 PASS** — 196 monthly rows = 98 months × 2 categories, earliest **2018-09-01**.
- **T8 PASS** — monthly carries its own `source` (`SENSIBULL_MONTHLY`), so the two granularities
  are separable by a column that every read already filters on.
- **T9 PASS, measured properly** — snapshot → third run → diff:
  ```
   before_rows | after_rows | rows_that_changed_or_vanished
  -------------+------------+-------------------------------
          2266 |       2266 |                             0
  ```
  Also 0 primary-key duplicates. Re-running changes nothing but `ingested_at`/`source_run_id`.
- **T10 PASS** — the 16 `NSE_FII_DII` rows are unchanged; `source` is in the PK so they cannot be
  overwritten by another provider.
- **T11 PASS, and stronger than the tolerance it was written against** — on all 16 overlapping
  observations Sensibull and NSE agree **exactly**:
  ```
   as_of_date | category | sensibull_net |  nse_net | abs_diff
  ------------+----------+---------------+----------+----------
   2026-10-09 | FII      |      -3568.90 | -3568.90 |     0.00
   2026-10-21 | DII      |       1614.32 |  1614.32 |     0.00
   ... 16 of 16 at 0.00
  ```
- **T12 PASS** — coverage shows **138 dates held vs 138 trading sessions in span, 0 missing**, and
  a set-difference against the `prices_eod` calendar confirms it both ways:
  `held_but_not_a_session 0`, `session_but_not_held 0`.
- **T13 PASS** — `INDEX_FUTURES`/`INDEX_OPTIONS` populated for all four categories (FII, DII, PRO,
  CLIENT). Per-index `FUT_*` rows carry `net_contracts` for **FII only** and `open_interest` NULL,
  because the feed supplies per-index fields for FII alone and gives no outstanding-OI
  counterpart. That is the source's shape, not a dropped field, and is documented in the service.
- **T14 PASS** — sequential month requests with a 1.5 s gap.
- **T15 PASS** — a month failure is counted in `months_failed`, logged with its exception, and the
  job row still finalises. 0 failures this run.

## Defects found and fixed during verification

1. **Garbled coverage log.** The format arguments were in the wrong order, printing
   `coverage[2026-04-01]: 2026-10-21..138  138 dates, 0 sessions in span, SENSIBULL MISSING`.
   On a project whose rule is that output must be trustworthy, a log line that misreports its own
   fields is a real defect, not cosmetics. Fixed and re-verified.
2. **Meaningless missing-session count for the monthly series.** Comparing monthly observations to
   the trading calendar reported `239 sessions missing`. A monthly observation is not a session;
   the count is now suppressed for monthly sources.
3. **Row arithmetic did not add up** — 2,190 daily rows parsed but only 2,070 distinct in the
   table. Investigated rather than assumed benign: the **current month's key returns a rolling
   window, not a calendar month**. `2026-October` returns 21 sessions starting **2026-09-21**,
   overlapping `2026-September` by exactly 8 sessions, so 146 date-entries cover 138 distinct
   dates. The upsert absorbs it and T9 proves no drift, but anything counting rows per month or
   concatenating payloads without de-duplicating will double-count those 8 sessions. Now
   documented in the service docstring.

## Not verified / out of scope

- **No evaluator rerun, and none is warranted.** `nidp.fii_dii_flows` is not an input to
  `smart_money_study/evaluator.py` (grep: no match). Market-wide flows cannot add a formation
  date; the ceiling is `stock_features_daily` starting 2025-12-29. The B-vs-C gate stays
  **INCONCLUSIVE** on the same 9 dates with the same CI.
- **1Y daily remains short.** Daily is a ~7-month rolling window (138 sessions) against 248
  needed. The 1Y chart must use the monthly series as a labelled lower-frequency fallback, never
  mixed into a daily aggregate.
- **ScanX is not ingested.** It stays an independent reconciliation feed.
- **UNVERIFIED: long-run stability of the endpoint.** This is a public app's internal app-state
  endpoint with an undocumented anonymous token. It can change shape without notice. The service
  fails loudly on a missing token or a missing `key_list` rather than writing partial data, but
  nothing here proves it will still work next month.

## Verdict: PASS
