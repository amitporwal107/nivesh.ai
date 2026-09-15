# Functionality Verification Report — migrating `delivery` (#7) onto BSE

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-18
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend routes/services: **yes** · frontend src: no
  - new: `nidp/services/delivery/bse_parser.py`
  - changed: `nidp/services/delivery/{service,writer}.py`, `nidp/services/bhavcopy/parser.py`
    (added `parse_bse_scrip_isin`)

## Summary
`delivery` was the third NSE-dependent feed. BSE publishes an equivalent daily delivery-position
file, but identifies rows by **BSE scrip code only** — no ISIN, no ticker — so it cannot be joined
to `nidp.delivery_data` (keyed on NSE symbol/series) directly. The migration bridges it in two
hops: `scrip_code -> ISIN` from the *same day's* BSE bhavcopy (`FinInstrmId` + `ISIN` columns),
then `ISIN -> NSE (symbol, series)` from the existing NSE universe in `prices_eod`. Same
gap-fill-with-NSE-precedence semantics as the bhavcopy migration.

Four stale days (2026-08-12/13/14/17) were filled; `delivery_data` went from stale-at-08-11 to
current, and `prices_eod.deliv_pct` coverage rose from 26.66% to 28.85%.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | parser | Header row not parsed as data | edge | excluded | PASS |
| TC-2 | parser | DDMMYYYY date becomes ISO | unit | 2026-08-17 | PASS |
| TC-3 | parser | Zero-padded quantities stripped to int | unit | 195097 | PASS |
| TC-4 | parser | Zero-padded percentage keeps its value | edge | "051.04" → 51.04 | PASS |
| TC-5 | parser | Deliverable never exceeds traded | data | invariant holds | PASS |
| TC-6 | parser | deliv_pct == deliverable/traded | data | column order proven | PASS |
| TC-7 | parser | Percentages within 0..100 | data | in range | PASS |
| TC-8 | parser | Short/blank/garbage lines skipped | failure | [] | PASS |
| TC-9 | bridge | scrip_code → ISIN resolves | golden | 500325→INE002A01018 | PASS |
| TC-10 | bridge | Non-SEBI layout yields empty bridge, not wrong data | failure | {} | PASS |
| TC-11 | e2e | Bridge covers the whole delivery file | data | 5142/5142 | PASS |
| TC-12 | e2e | Live BSE gap-fill of a stale day | e2e | rows written | PASS |
| TC-13 | e2e | Propagation to prices_eod fires automatically | data | deliv_pct filled | PASS |
| TC-14 | safety | Day NSE already covers → SKIPPED, 0 rows | safety | SKIPPED | PASS |
| TC-15 | safety | No (date,symbol,series) with two sources | safety | 0 | PASS |
| TC-16 | regression | Existing suite unchanged | regression | same baseline | PASS |

## Evidence

### TC-1..TC-10 — parser + bridge unit/golden tests
```
10 passed in 0.06s
```
Fixtures: `nidp/tests/fixtures/bse/{delivery_20260817_slice.txt,bhavcopy_20260817_slice.csv}`.

TC-6 is the important one: it recomputes `100 * deliverable/traded` from columns 3 and 5 and
asserts it matches the file's own column 7. That proves the pipe-column mapping is right, which a
shape-only test would not.

### TC-11 — bridge coverage on the full real files
```
delivery rows: 5142
scrip->isin pairs: 5142
  500325 -> INE002A01018   532540 -> INE467B01029
delivery rows with an ISIN bridge: 5142/5142
```

### TC-12 / TC-13 — live runs (NSE blocked throughout)
```
gate=1 feed=delivery date=2026-08-17 verdict=PASS severity=OK failed_checks=0
bse delivery gapfill: 2794 row(s) to write, 0 skipped (NSE has the day), 0 no scrip->ISIN bridge, 2348 ISIN not in NSE universe
bse delivery gapfill: wrote 2794 row(s)
prices_eod delivery columns updated for 2768 row(s) over 1 day(s)
validation[delivery] target=2026-08-17 status=PASSED rules=4 failed=1 findings=1 duration=62ms
job_log[delivery] 2a46e924-35a8-4186-a5d9-3bbccf181f34 status=OK fetched=5142 inserted=2794 skipped=0
```
Remaining days:
```
### 2026-08-12   wrote 2746 row(s) · prices_eod updated 2555 · status=OK
### 2026-08-13   wrote 2754 row(s) · prices_eod updated 2754 · status=OK
### 2026-08-14   wrote 2735 row(s) · prices_eod updated 2735 · status=OK
```
The single validation finding is `delivery.cross_check_prices_eod_present` (WARN, non-blocking):
26 of 2,794 rows are for ISINs in the NSE universe that did not trade on NSE that day. That is the
validator working correctly, not a defect.

### TC-14 — NSE precedence
```
delivery: NSE unreachable for 2026-08-11, but the day is already stored from NSE — nothing to back-fill
job_log[delivery] 5d1c91d2-e165-48d6-9e2e-ed620b12abc4 status=SKIPPED fetched=0 inserted=0 skipped=0
```

### TC-15 — no double counting
```
          check           | n
 delivery dup symbol-days | 0

 as_of_date |      source      | rows
 2026-08-10 | NSE_SEC_BHAVDATA | 3361
 2026-08-11 | NSE_SEC_BHAVDATA | 3310
 2026-08-12 | BSE_DELIVERY     | 2746
 2026-08-13 | BSE_DELIVERY     | 2754
 2026-08-14 | BSE_DELIVERY     | 2735
 2026-08-17 | BSE_DELIVERY     | 2794
```

### Coverage gain (data test)
```
 deliv_pct_filled_pct | rows_filled | days
                28.85 |      123402 |   42
```
(26.66% / 112,590 / 38 days before this change.)

### TC-16 — regression
```
38 failed, 392 passed, 5 skipped, 21 warnings in 5.37s
```
Same 38 pre-existing failures as the recorded baseline; passes rose 382 → 392 with the 10 new tests.

### Feed status after the work
```
 ingester | last_run_status |   last_success_at   | cf
 delivery | SKIPPED         | 2026-08-18 11:30:25 |  0
 fii_dii  | OK              | 2026-08-18 10:46:04 |  0
 bhavcopy | SKIPPED         | 2026-08-18 10:50:34 |  1
```
`delivery` consecutive_failures went 22 -> 0. `bhavcopy`'s cf=1 is a leftover from the pre-guard
test run at 10:50 that recorded FAILED on a correct no-op; the next OK run clears it.

## Known limitations
- **BSE delivery reflects BSE trading only.** `traded_qty` is BSE volume, so a gap-filled day's
  `deliv_pct` is BSE's delivery ratio, not NSE's. The ratio is the more transferable of the two
  figures (it is a proportion, not a level), but it is still a different order book. Rows carry
  `source='BSE_DELIVERY'` so consumers can discriminate; none do today.
- **Breadth ~2,750 of ~3,500 symbols** on fallback days: BSE-only scrips are dropped by design
  (2,348 per day), and NSE names not traded on BSE that day have no row.
- **Two BSE fetches per fallback run** (delivery TXT + bhavcopy for the bridge). A bridge failure
  is treated as fatal and re-raises the original NSE error rather than writing unmapped rows.
- **UNVERIFIED:** `drop_bse_delivery_gapfill_for` (retiring BSE rows once NSE delivers a day)
  could not be exercised live because NSE is still blocked. Covered by reading only.

## Verdict: PASS
