# Functionality Verification Report — Point-in-time BSE scrip master (Phase 0.1)

- **Branch:** feat/bse-scrip-master (off origin/dev)
- **Date:** 2026-09-25
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (nidp_staging on nidp-stack-vm)
- **Changed areas:** backend routes/services: **yes** (`nidp/services/bhavcopy/parser.py`, new `nidp/services/bse_scrip_master/`) · frontend src: **no**

## Summary

Half the announcement corpus cannot be joined to a price series. Measured on nidp_staging:
of 219,504 `corporate_announcements` rows, 110,270 carry `ticker_symbol` + `isin` (NSE-sourced),
109,188 carry `scrip_code` (BSE-sourced), and **0 carry both**. `ref.security_master.bse_code`
exists for exactly this and is populated for 0 of 4,924 equities.

`parse_bse_scrip_isin()` already builds `{scrip_code → ISIN}` from each day's BSE bhavcopy for the
delivery gap-fill, then discards it. This change persists it, dated, with three extra columns that
only make sense point-in-time (BSE ticker, trading/surveillance group, company name as filed).

Scope verified here: migration 153 applied, parser extended without regression, one trading day
ingested end-to-end on staging, and the resolution lift measured.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | parser | Keeps ticker, group and name for a known scrip | unit | RELIANCE/A/INE002A01018 | PASS |
| TC-2 | parser | Every row carries the full 5-key shape | unit | no missing keys | PASS |
| TC-3 | parser | Strict superset of `parse_bse_scrip_isin` | unit/regression | no scrip lost, no ISIN changed | PASS |
| TC-4 | parser | Deduplicates repeated scrip codes | unit | len == len(set) | PASS |
| TC-5 | parser | Drops F&O rows | unit/edge | only the CM/STK row | PASS |
| TC-6 | parser | Keeps a row whose ISIN is missing | unit/edge | isin=None, row retained | PASS |
| TC-7 | parser | Degrades to `[]` on a non-SEBI layout | unit/failure | `[]`, not wrong mappings | PASS |
| TC-8 | regression | Existing delivery-fallback suite still green | unit | 10 passed | PASS |
| TC-9 | migration | 153 applies cleanly to nidp_staging | data | table + 2 indexes + 2 views | PASS |
| TC-10 | service | One trading day ingests end-to-end | e2e | 4,999 rows written | PASS |
| TC-11 | data | Resolver returns exactly one row per (date, scrip) | data | no ISIN-duplication | PASS |
| TC-12 | data | Resolution lift on the Phase-1 families | data | material improvement | PASS |

## Unit tests

```
$ /app/research/tpd3_forward/venv/bin/python -m pytest \
    nidp/tests/services/test_bse_scrip_master.py \
    nidp/tests/services/test_bse_delivery_fallback.py -q
.................                                                        [100%]
17 passed in 0.11s
```

7 new + 10 pre-existing. TC-3 is the regression guard: the delivery gap-fill depends on
`parse_bse_scrip_isin`, so the new function must not drop a scrip it maps nor disagree on an ISIN.

## Migration (staging)

```
$ docker exec -i nidp-postgres-staging psql -U nidp_staging -d nidp_staging \
    -v ON_ERROR_STOP=1 < nidp/migrations/153_bse_scrip_master_daily.sql
SET
CREATE TABLE
COMMENT
COMMENT
CREATE INDEX
CREATE INDEX
CREATE VIEW
COMMENT
```
Result: PASS

## Service run (staging)

```
$ PYTHONPATH=... /opt/nidp-staging/venv/bin/python -m nidp.services.bse_scrip_master --date 2026-09-24
2026-09-25 13:38:27,740 INFO NIDP pg pool initialized
2026-09-25 13:38:29,028 INFO bse_scrip_master 2026-09-24: {'days_written': 1,
  'days_skipped_present': 0, 'days_no_file': 0, 'days_failed': 0,
  'rows_written': 4999, 'suspect_days': []}
```
Result: PASS — 4,999 scrips for one trading day, no failures, no suspect days.

## Data correctness (staging)

**Resolver returns exactly one row per key** (TC-11) — 7 ISINs in `sector_master` carry two symbols
each (company renames such as `LYPSAGEMS`→`AURUS`, `SILLYMONKS`→`CRESTO`, `GUJGASLTD`→`GUJENERGY`,
plus one EQ/BE pair), so a naive ISIN join doubles those rows:

```
 view_rows | uniq_keys | nse_listed
-----------+-----------+------------
      4999 |      4999 |       2405
```

**Resolution lift on the announcement corpus** (TC-12):

```
   family    | filings | before_ticker_only | after_with_master | lift_x | uniq_syms
-------------+---------+--------------------+-------------------+--------+-----------
 F1 takeover |     473 |                 47 |               198 |    4.2 |        55
 F3 buyback  |     154 |                 79 |               152 |    1.9 |        34
 F4 QIP/pref |     505 |                 67 |               280 |    4.2 |       151
```

F3 buyback reaches **152/154 = 98.7%**, clearing the Phase-0 exit gate of >=95%.

**Ceiling, stated honestly:** of 4,999 BSE scrips on that day, 2,405 resolve to an NSE symbol and
**2,594 do not** — those are BSE-only companies with no NSE listing, hence no NSE price series.
They are outside an NSE-traded universe by construction, not a defect in this mapping. This is why
F4 stops at 55.4%.

## Inputs required from user

- none

## Not yet done (explicitly out of scope for this report)

- **Backfill Jun-2024 → present has NOT been run.** Only 2026-09-24 is loaded. The per-scrip
  lifetime view `v_bse_scrip_coverage` and the delisting proxy need the full range to be meaningful.
- `ref.security_master.bse_code` is still unpopulated; backfilling `corporate_announcements`
  identifiers is Phase 0.2.
- Not wired into any scheduler — no cron entry added.

---

# Phase 0.2 — announcement resolution + security_master.bse_code

## Additional test cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-13 | backfill | Jun-2024 -> Sep-2026 completes | e2e | ~570 trading days | PASS |
| TC-14 | migration | 154 applies; view resolves as-of filing date | data | 4 resolution classes | PASS |
| TC-15 | data | BSE announcements gain a symbol | data | material lift | PASS |
| TC-16 | sync | ref.security_master.bse_code populated | data | >0 equities, 1:1 | PASS |
| TC-17 | edge | ISIN changes do not violate the unique index | failure | no UniqueViolation | PASS |
| TC-18 | edge | "#" one-day settlement series never chosen | data | 0 securities | PASS |

## Backfill (staging)

```
"days_written": 573, "days_failed": 32, "rows_written": 2660810, "suspect_days": []

 days |  rows   |    min     |    max
------+---------+------------+------------
  573 | 2665809 | 2024-06-03 | 2026-09-24
```
The 32 "failed" are exchange holidays: BSE answers a non-trading day with its landing page and
HTTP 200, not a 404. Fixed in commit de35253e (`looks_like_html`), which the running backfill
predated — no bad data was written either way. ~14 holidays/year over 28 months is the expected count.

## Announcement resolution (TC-15)

```
       resolution        |   n    | syms
-------------------------+--------+------
 exchange_symbol         | 110356 | 2421     NSE-supplied, unchanged
 bse_scrip_isin_bridge   |  69085 | 2462     <-- resolved by this work
 bse_only_no_nse_listing |  37351 |    0     no NSE listing, out of universe
 scrip_not_in_master     |   2752 |    0     residual gap
```

**69,085 BSE announcements that previously had no symbol at all now resolve**, across 2,462 NSE
symbols. Before the full backfill this was 61,817 with 12,600 unresolved; completing the range cut
the residual by 78%.

## security_master.bse_code (TC-16/17/18)

```
 entity_type |   n   | with_bse | pct
-------------+-------+----------+------
 EQUITY      |  5743 |     3948 | 68.7
 MF_SCHEME   | 14544 |       88 |  0.6

  symbol   | bse_code |     isin
-----------+----------+--------------
 HDFCBANK  | 500180   | INE040A01034
 INFY      | 500209   | INE009A01021
 POLICYBZR | 543390   | INE417T01026
 RAYMOND   | 500330   | INE301A01014
 RELIANCE  | 500325   | INE002A01018
 TCS       | 532540   | INE467B01029

 securities_pointing_at_a_hash_series
--------------------------------------
                                    0
```

Two defects were found by spot-checking and fixed before this result:

1. **UniqueViolation on `ux_security_master_bse`.** 288 scrips carry more than one ISIN over time
   (890236 was IN90I0M01014 in Apr-May 2026, IN90I0M01022 in Jul), so matching on ISIN alone handed
   one scrip to two securities. Fixed by taking the newest ISIN per scrip, then one scrip per ISIN,
   then one security per ISIN.
2. **Wrong scrip chosen for the largest names.** The first run gave RELIANCE `100325` and TCS
   `132540`. BSE lists a one-day "#" settlement series beside the real listing — 500325 RELIANCE
   (573 days) vs 100325 RELIANCE# (1 day). Ordering by scrip code preferred the wrong one. Fixed by
   preferring the scrip that actually traded the most days. 34 ISINs were affected.

## Point-in-time design validated on real data

```
scrips_that_changed_group | scrips_renamed | scrips_isin_changed | scrips_seen
                     2024 |            357 |                 249 |        7274

SUPHA       B -> T -> X -> Z
BBOX        A -> B -> T
HINDMOTORS  B -> T -> X
```

**28% of scrips changed trading group** over the window. A current-state master would have silently
rewritten all of it, making any historical tradability judgement wrong for more than a quarter of
the universe — on the single field that gates executability.

## Known gaps (not defects in this change)

- `scrip_not_in_master` = 2,752 filings. Scrips absent from the master across the whole range —
  delisted before 2024-06, or non-equity segments.
- 88 MF_SCHEME rows received a bse_code. Listed ETFs/InvITs legitimately carry BSE scrip codes;
  not separately verified.
- BSE announcements stop at **2026-09-22** while NSE reaches 09-25 — BSE ingestion is 3 days
  behind. Pre-existing, unrelated to this change.
- Still not wired into any scheduler.

## Verdict: PASS
