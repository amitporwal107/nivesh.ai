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

## Verdict: PASS
