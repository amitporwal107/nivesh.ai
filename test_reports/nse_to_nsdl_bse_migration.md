# Functionality Verification Report — migrating NSE-dependent feeds onto NSDL / BSE

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-18
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend routes/services: **yes** · frontend src: no
  - new: `nidp/shared/sources/{plain_http,bse_fetcher}.py`, `nidp/services/fii_dii/nsdl_parser.py`
  - changed: `nidp/shared/sources/nsdl_fetcher.py`, `nidp/services/fii_dii/{service,writer}.py`,
    `nidp/services/bhavcopy/{service,writer}.py`

## Summary
NSE's Akamai edge is 403-blocking this VM's egress IP (34.93.60.254) on every host, which
disabled four feeds. Two are now migrated onto sources that are reachable, as **fallbacks with
the primary source still preferred**, not replacements:

- **fii_dii (#1)** → NSDL FPI + DII "Daily Trends". Ran green with NSE blocked.
- **bhavcopy (#9)** → BSE SEBI-standard bhavcopy, as an ISIN-re-keyed **gap-fill** with NSE
  precedence. Closed the 2026-08-13/14 holes.

**delivery (#7)** source confirmed but not built. **nse_shareholding (#4)** has no working BSE
endpoint found — reported as blocked, not guessed at.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | nsdl | FPI equity-cash row matches the published grid | golden | 13756.70/12926.71/829.99 | PASS |
| TC-2 | nsdl | Rowspan inheritance ("Primary market & others") | golden | inherits Equity | PASS |
| TC-3 | nsdl | Parenthesised values parse negative | unit | (618.83) → −618.83 | PASS |
| TC-4 | nsdl | NSDL's own Sub-total/Total never stored | edge | absent | PASS |
| TC-5 | nsdl | net == buy − sell for every FPI row | data | consistent | PASS |
| TC-6 | nsdl | DII splits into Bank/Insurance/MF/AIF/Others | golden | 5 types, exact values | PASS |
| TC-7 | nsdl | Derived DII total == sum of the five types | data | 216.18 | PASS |
| TC-8 | nsdl | `*-total` rows excluded (not summable) | edge | excluded | PASS |
| TC-9 | nsdl | Only Equity/Stock-Exchange leg kept | edge | debt/bullion dropped | PASS |
| TC-10 | nsdl | Validator contract: FII **and** DII present | contract | both | PASS |
| TC-11 | nsdl | Empty body returns [] rather than raising | failure | [] | PASS |
| TC-12 | fii_dii | Live run with NSE blocked writes NSDL rows | e2e | status=OK | PASS |
| TC-13 | fii_dii | Provisional vs confirmed both retained | data | 2 sources, same day | PASS |
| TC-14 | bse | BSE file parses with the unmodified NSE parser | golden | rows parsed | PASS |
| TC-15 | bse | Every row has a close price (ClsPric vs ClsgPric) | edge | 0 missing | PASS |
| TC-16 | bse | ISIN present for identity re-keying | data | ≥80% | PASS |
| TC-17 | bse | Dual-listed tickers match NSE (TCS/INFY/HDFCBANK) | data | match | PASS |
| TC-18 | bse | OHLC invariants hold (low ≤ o/c ≤ high) | data | hold | PASS |
| TC-19 | bhavcopy | Live gap-fill of a day NSE missed | e2e | rows written | PASS |
| TC-20 | bhavcopy | Gap-fill re-keys onto NSE symbol/series | data | RELIANCE/EQ | PASS |
| TC-21 | bhavcopy | Day NSE already has → writes nothing | safety | 0 written | PASS |
| TC-22 | bhavcopy | No (date,symbol,series) has two sources | safety | 0 duplicates | PASS |
| TC-23 | bhavcopy | Correct no-op finalizes SKIPPED not FAILED | edge | SKIPPED | PASS |
| TC-24 | regression | Existing suite unchanged | regression | same baseline | PASS |

## Evidence

### TC-1..TC-11 — NSDL parsers (golden, real 2026-08-17 pages)
```
17 passed in 0.09s
```
Fixtures: `nidp/tests/fixtures/nsdl/{fpi,dii}_latest_20260817.html` (verbatim saved pages).

### TC-12 — fii_dii live run, NSE blocked
```
parsed_archive fii_dii/parsed/fii_dii/2026/08/887b9a5645c5.jsonl.gz rows=12
validation[fii_dii] target=None status=PASSED rules=3 failed=0 findings=0 duration=20ms
job_log[fii_dii] 1911bcfe-8eee-45ab-83c5-541b8ac0249b status=OK fetched=12 inserted=12 skipped=0
```
The passing rule set includes the CRITICAL/BLOCK `fii_dii.cash_rows_present`, which demands both
FII and DII EQUITY_CASH rows.

Rows landed (data test):
```
 as_of_date |   category    |      segment       | buy_value_cr | sell_value_cr | net_value_cr |  source
 2026-08-17 | DII           | EQUITY_CASH        |   14433.8000 |    14217.6100 |     216.1800 | NSDL_DII
 2026-08-17 | DII_BANK      | EQUITY_CASH        |     581.1300 |      193.7000 |     387.4300 | NSDL_DII
 2026-08-17 | DII_INSURANCE | EQUITY_CASH        |    2183.5800 |     2328.9000 |    -145.3200 | NSDL_DII
 2026-08-17 | DII_MF        | EQUITY_CASH        |   10685.8800 |    10799.8500 |    -113.9700 | NSDL_DII
 2026-08-17 | DII_AIF       | EQUITY_CASH        |     455.1800 |      786.2500 |    -331.0800 | NSDL_DII
 2026-08-17 | DII_OTHERS    | EQUITY_CASH        |     528.0300 |      108.9100 |     419.1200 | NSDL_DII
 2026-08-17 | FII           | EQUITY_CASH        |   13756.7000 |    12926.7100 |     829.9900 | NSDL_FPI
 2026-08-17 | FII           | EQUITY_PRIMARY     |    3282.0000 |        0.0000 |    3282.0000 | NSDL_FPI
 2026-08-17 | FII           | DEBT_GENERAL_LIMIT |     551.8500 |     1170.6800 |    -618.8300 | NSDL_FPI
 2026-08-17 | FII           | DEBT_VRR           |     796.1300 |      348.8700 |     447.2600 | NSDL_FPI
 2026-08-17 | FII           | DEBT_FAR           |    1059.8900 |      597.3500 |     462.5400 | NSDL_FPI
 2026-08-17 | FII           | HYBRID             |      47.1500 |       37.6700 |       9.4800 | NSDL_FPI
```

### TC-13 — provisional vs confirmed (PRD feed #2's reconciliation)
```
 category | nse_provisional | nsdl_confirmed |  delta_cr
 DII      |       5101.4600 |       216.1800 | -4885.2800
 FII      |      -2535.1000 |       829.9900 |  3365.0900
```
Both survive because `source` is part of the primary key.

### TC-14..TC-18 — BSE bhavcopy parsing
```
9 passed in 0.27s
```

### TC-19 / TC-20 — live gap-fill of 2026-08-13
```
NSE session primed: 403, 1 cookies
Retry 4/4 for https://nsearchives.nseindia.com/.../BhavCopy_NSE_CM_0_0_0_20260813_F_0000.csv.zip in 6.0s (HTTP 403 (NSE edge block))
gate=1 feed=bhavcopy date=2026-08-13 verdict=PASS severity=OK failed_checks=0
bse gapfill: 2754 row(s) to write, 0 skipped (NSE already has the day), 2218 skipped (ISIN not in NSE universe)
validation[bhavcopy] target=2026-08-13 status=PASSED rules=5 failed=0 findings=0
job_log[bhavcopy] f87fa725-07fd-44f8-8950-4733adda6ed0 status=OK fetched=4972 inserted=2754 skipped=0
```
(The `Retry 4/4 ... (HTTP 403 (NSE edge block))` line is the earlier `nse_fetcher` fix running in
production — the original code raised `_TerminalHttpError` on the second 403.)

Re-keyed onto NSE identity:
```
  symbol  | series |     isin     | open_price | high_price | low_price | close_price | volume  |    source
 HDFCBANK | EQ     | INE040A01034 |   727.9000 |   729.1000 |  724.4500 |    727.0000 | 3004507 | BSE_BHAVCOPY
 INFY     | EQ     | INE009A01021 |  1175.6000 |  1175.6000 | 1156.7500 |   1169.9000 |  710401 | BSE_BHAVCOPY
 RELIANCE | EQ     | INE002A01018 |  1329.0000 |  1329.0000 | 1307.1000 |   1316.4500 | 1535288 | BSE_BHAVCOPY
 TCS      | EQ     | INE467B01029 |  2349.7000 |  2375.0500 | 2332.4000 |   2372.9000 |  362339 | BSE_BHAVCOPY
```

### TC-21 / TC-22 — safety: NSE precedence, no double counting
```
bse gapfill: 0 row(s) to write, 4948 skipped (NSE already has the day), 0 skipped (ISIN not in NSE universe)

 duplicated_symbol_days
                      0
```

### TC-23 — correct no-op is SKIPPED
```
bhavcopy: NSE unreachable for 2026-08-12, but the day is already stored from NSE — nothing to back-fill
job_log[bhavcopy] 4c41972f-250f-4c30-a57b-c90a4415649b status=SKIPPED fetched=0 inserted=0 skipped=0
```
Before this guard the same run recorded `status=FAILED ... BLOCK validation: 1 finding(s)` —
a correct no-op counted as a feed failure.

### Gap closure
```
 as_of_date |    source    | rows
 2026-08-10 | NSE_BHAVCOPY | 3564
 2026-08-11 | NSE_BHAVCOPY | 3483
 2026-08-12 | NSE_BHAVCOPY | 3480
 2026-08-13 | BSE_BHAVCOPY | 2754
 2026-08-14 | BSE_BHAVCOPY | 2735
 2026-08-17 | NSE_BHAVCOPY | 3626
```

### TC-24 — regression
```
38 failed, 382 passed, 5 skipped, 21 warnings in 5.10s
```
Baseline before this work was `38 failed, 336 passed` — same 38 pre-existing failures; the
46 new tests all pass.

## Known limitations (must be read before relying on a fallback day)
- **BSE volume is BSE-only liquidity.** On a gap-filled day, OHLC tracks NSE closely but
  `volume`/`turnover` are an order of magnitude smaller (RELIANCE 1.54M on BSE vs ~10M on NSE).
  Volume-derived indicators — `vol_z20`, `deliv_pct_avg_20` — will read those days as a volume
  collapse. Rows are tagged `source='BSE_BHAVCOPY'` so consumers *can* discriminate, but no
  consumer does so today. Recommend making `vol_z20` source-aware before trusting fallback days.
- **Fallback breadth is ~78%** (2,754 of ~3,500 symbols): BSE-only scrips are dropped by design,
  and NSE-listed names not traded on BSE that day have no BSE row.
- **The derived `category='DII'` row is computed, not published.** It sums the five investor
  types' Equity/Stock-Exchange legs. That is sound because the instrument axis is pinned to
  Equity; NSDL's "sub-totals cannot be summed" warning concerns its `*-total` rows, which cross
  the instrument dimension where MF/AIF double-count. Documented in `_derived_dii_total`.
- **UNVERIFIED:** the NSE-preferred path (NSE succeeds → `drop_bse_gapfill_for` retires BSE rows)
  could not be exercised live because NSE is still blocked. The delete is covered by reading only.
  Re-run 2026-08-13 once NSE egress is restored to confirm the BSE rows are superseded.

## Not migrated
- **delivery (#7)** — source confirmed live: `https://www.bseindia.com/BSEDATA/gross/{yyyy}/SCBSEALL{ddmm}.zip`
  (HTTP 200, 5,142 rows, `DATE|SCRIP CODE|DELIVERY QTY|DELIVERY VAL|DAY'S VOLUME|DAY'S TURNOVER|DELV. PER.`).
  Keyed by BSE scrip code only, so it needs a scrip_code→ISIN bridge — which the BSE bhavcopy's
  `FinInstrmId` column now supplies. Builder not written this session.
- **nse_shareholding (#4)** — no working BSE endpoint found. `ShpPromoterNPublicHistory` and
  `ComShpPro` both 302 to `api.bseindia.com/error_Bse.html`. Needs real endpoint discovery
  rather than a guess.

## Verdict: PASS
