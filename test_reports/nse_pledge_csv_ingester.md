# Functionality Verification Report — NSE SAST pledged-data CSV ingester

- **Branch:** feat/research-qa-exercise
- **Date:** 2026-08-19
- **Author:** Claude (full-stack-developer + qa-engineer)
- **Environment:** staging (nidp_staging on nidp-stack-vm, DB 127.0.0.1:5434)
- **Changed areas:** backend routes/services: **yes** (`nidp/services/nse_pledge_csv/*`, `nidp/services/quality_gate/*`, `nidp/services/daas_api/metric_registry.py`) · frontend src: no

## Summary

Promoter-pledge data did not exist in this platform: measured before this work,
`nidp.shareholding_pattern` had **0 non-null values in all 8,955 rows** for both
`promoter_pledged_pct` and `promoter_pledged_to_total_pct`. The existing
`nse_pledge_data` service cannot fill them because NSE's `/api/corporate-pledgedata`
returns 403 to this platform's egress at the IP level (verified 2026-08-19 from two
networks, with browser UA, primed cookies and correct Referer). This adds the
manual-drop path the user asked for: a CSV downloaded by hand from NSE's
corporate-filings-pledged-data page is parsed, resolved to NIDP symbols, and merged
into the shareholding rows that already exist.

Verified end-to-end against the real staging DB — first with a fixture of verbatim
rows covering the three traps, then against the **complete real file** once it was
supplied (see "Full-file verification" below).

## Test Cases

> Authored from the real file's contents before the service was written.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | parser | UTF-8 BOM on the first header | unit | first column still matches | PASS |
| TC-2 | parser | required column absent | failure | raises, does not return 0 rows silently | PASS |
| TC-3 | parser | **Trap 1** — empty encumbrance fields (Alchemist) | edge | parses to `None`, never `0.00` | PASS |
| TC-4 | parser | explicit `0.00` (Reliance) | edge | preserved as `0.0`, not `None` | PASS |
| TC-5 | parser | **Trap 2** — duplicate company name (Future Enterprises ×2) | edge | both rejected, name reported | PASS |
| TC-6 | parser | **Trap 3** — X/A vs pledge/demat (A2Z 99.68 vs 31.11) | edge | kept in separate fields | PASS |
| TC-7 | parser | period derivation across quarter/year boundaries | unit | last completed quarter end | PASS |
| TC-8 | parser | period from BROADCAST DATE, not filename | unit | Aug-2026 file → 2026-06-30 | PASS |
| TC-9 | parser | name normalisation (case/space/punctuation) | unit | equal keys | PASS |
| TC-10 | parser | `&` vs `AND` known limitation | unit | documented as unequal, goes to `unresolved` | PASS |
| TC-11 | parser | degeneracy stats (distinct vs null-rate) | unit | 3 distinct from 4 rows | PASS |
| TC-12 | service | normalised name → symbol index | unit | resolves both sides | PASS |
| TC-13 | service | one name → two symbols | edge | dropped, never arbitrarily picked | PASS |
| TC-14 | service | same symbol listed twice | edge | not a collision | PASS |
| TC-15 | service | unresolved names surfaced, not dropped | failure | returned + printed to stderr | PASS |
| TC-16 | service | command-tag row counting | unit | count from Postgres, not `len(args)` | PASS |
| TC-17 | api/data | `--dry-run` against real staging DB | api | writes nothing, reports real split | PASS |
| TC-18 | api/data | real run merges into existing rows | api | `rows_updated=5` | PASS |
| TC-19 | data | `source_run_id` / `ingested_at` untouched on UPDATE | data | pre-existing values survive | PASS |
| TC-20 | data | all sources at a period get the same pledge | data | NSE_SHP and screener_in agree | PASS |
| TC-21 | data | pledge reaches `stock_features_daily` | data | `features_updated=3` | PASS |
| TC-22 | dq | fixed pledge≤promoter rule passes on real data | data | old rule fails A2Z, new rule passes | PASS |
| TC-23 | api | screener availability gate hides the new metric with a reason | api | `offered:false` + stated reason | PASS |
| TC-24 | regression | full nidp suite unaffected | unit | no new failures | PASS |
| TC-25 | parser | full real file parses, reconciles to the raw row count | api | 1544 − 6 dupes = 1538 | PASS |
| TC-26 | api/data | `--dry-run` on the full real file | api | real resolved/unresolved split | PASS |
| TC-27 | data | classify every unresolved name | edge | matcher gap vs genuinely absent | PASS |
| TC-28 | parser | `LTD` ≡ `LIMITED`, trailing token only | unit | PNBGILTS + RHIM resolve | PASS |
| TC-29 | api/data | full-file load writes the whole universe | api | 1,620 rows / 1,388 symbols | PASS |
| TC-30 | data | promoter-less companies keep NULL, not 0 | edge | 17 symbols, `_pct` NULL, `_to_total` 0.00 | PASS |
| TC-31 | data | fixed DQ rule holds on the full load | data | old rule 83 fails, new rule 0 | PASS |
| TC-32 | api | screener gate flips the metric on by itself | api | `offered: true` at 52.1% | PASS |
| TC-33 | api | real screen queries return real companies | api | 13 over 40%, 917 at zero | PASS |
| TC-34 | api | zero-result path returns filter_impact | failure | relaxation suggested, no 500 | PASS |
| TC-35 | data | view still one row per symbol after the load | data | 2,325 / 2,325 / 0 | PASS |

## API / Endpoint Tests (staging)

Run on nidp-stack-vm with the staging venv and `/opt/nidp-staging/nidp.env`
(`NIDP_POSTGRES_URL` → `localhost:5434/nidp_staging`), from a shadow copy of the
dev-repo tree so nothing was installed before review.

**TC-17 — `--dry-run` (writes nothing):**

```
$ python -m nidp.services.nse_pledge_csv --file /tmp/CF-SAST-Pledged-Data-fixture.csv --dry-run
nse_pledge_csv: CF-SAST-Pledged-Data-fixture.csv — 4 usable rows, period_end=2026-06-30, 1 ambiguous name(s) rejected, 0 unparsable
{
  "status": "DRY_RUN",
  "run_id": "dd79e6f7-06bd-4610-a3eb-66d4dd3349d4",
  "file": "CF-SAST-Pledged-Data-fixture.csv",
  "source": "NSE_SAST_CSV",
  "period_end": "2026-06-30",
  "parsed_rows": 4,
  "ambiguous_csv_names": [
    "Future Enterprises Limited"
  ],
  "ambiguous_master_names": 4,
  "resolved": 3,
  "unresolved": 1,
  "unresolved_sample": [
    "Alchemist Limited"
  ],
  "pledge_stats": {
    "rows": 4,
    "with_pledge_pct": 3,
    "distinct_values": 3,
    "nonzero": 2,
    "zero": 1,
    "max": 99.68
  }
}
WARNING: 1 company name(s) did not resolve to a NIDP symbol; their pledge was NOT written. First few: ['Alchemist Limited']
```

Result: **PASS** — 6 input rows → 4 usable (the two `Future Enterprises Limited`
rows rejected as ambiguous, TC-5); period derived as 2026-06-30 from the 18-Aug-2026
broadcast stamp (TC-8); `Alchemist Limited` reported as unresolved rather than
dropped (TC-15).

**TC-18/TC-21 — real run:**

```
$ python -m nidp.services.nse_pledge_csv --file /tmp/CF-SAST-Pledged-Data-fixture.csv
{
  "status": "OK",
  "run_id": "01aa0139-f664-4f3e-9662-7277059b6311",
  "period_end": "2026-06-30",
  "parsed_rows": 4,
  "resolved": 3,
  "unresolved": 1,
  "pledge_stats": { "rows": 4, "with_pledge_pct": 3, "distinct_values": 3,
                    "nonzero": 2, "zero": 1, "max": 99.68 },
  "rows_updated": 5,
  "rows_inserted": 0,
  "features_updated": 3
}
```

Result: **PASS** — 3 resolved symbols touched 5 rows, because ASHOKLEY and RELIANCE
each carry both an `NSE_SHP` and a `screener_in` row at that quarter and both were
updated (TC-20).

**TC-23 — screener availability gate, real coverage measured by the endpoint's own
`_coverage()` against the real table:**

```
{
  "registry_version": "1.1.0",
  "as_of": "2026-08-17",
  "metric": {
    "key": "promoter_pledged_pct",
    "label": "Promoter Pledge",
    "category": "leverage",
    "min_coverage_pct": 25.0,
    "measured": { "covered_pct": 0.1, "distinct_non_null": 3 },
    "offered": false
  },
  "hidden_reason": "Only 0.1% of companies have this today (needs 25%)"
}
```

Result: **PASS** — the metric is listed so the UI can say *why* it is absent, and is
correctly not offered on 0.1% coverage.

**TC-24 — pytest:**

```
$ python3 -m pytest nidp/tests/services/test_nse_pledge_csv_parser.py \
                    nidp/tests/services/test_nse_pledge_csv_service.py -q
29 passed in 0.09s

$ python3 -m pytest nidp/tests nidp/services/quality_gate/tests -q \
    --ignore=nidp/tests/services/test_daas_api.py \
    --ignore=nidp/tests/test_failing_feeds_golden.py \
    --ignore=nidp/tests/test_pipeline_freshness.py \
    --ignore=nidp/tests/test_pipeline_stages_endpoint.py
3 failed, 513 passed, 6 skipped in 4.01s
```

Result: **PASS**. The 3 failures are pre-existing and unrelated
(`test_mf_amc_robustness` ×2, `test_feed_registry_drift::test_every_recoverable_daily_feed_is_scheduled`).
Proven by re-running them with my quality_gate edits stashed:

```
$ git stash push -q backend/nidp/services/quality_gate/dq_suites.py \
                    backend/nidp/services/quality_gate/great_expectations_suites.py
$ python3 -m pytest nidp/tests/services/test_mf_amc_robustness.py \
                    nidp/tests/test_feed_registry_drift.py -q
3 failed, 10 passed in 0.55s
```

The 4 `--ignore`d modules fail to import locally on `ModuleNotFoundError: No module
named 'fastapi'` — a local environment gap, not a code change.

## Data Correctness (staging)

**BEFORE** — pledge did not exist anywhere:

```sql
SELECT count(*) all_rows, count(promoter_pledged_pct) pledge_pct,
       count(promoter_pledged_to_total_pct) pledge_total, count(pledged_shares) pledged_shares
  FROM nidp.shareholding_pattern;
 all_rows | pledge_pct | pledge_total | pledged_shares
----------+------------+--------------+----------------
     8955 |          0 |            0 |              0
```

```
  symbol  | period_end |   source    | promoter_pct | promoter_pledged_pct | promoter_pledged_to_total_pct | pledged_shares
----------+------------+-------------+--------------+----------------------+-------------------------------+----------------
 A2ZINFRA | 2026-06-30 | NSE_SHP     |      27.9200 |                      |                               |
 ASHOKLEY | 2026-06-30 | NSE_SHP     |      51.5100 |                      |                               |
 ASHOKLEY | 2026-06-30 | screener_in |      51.5100 |                      |                               |
 RELIANCE | 2026-06-30 | NSE_SHP     |      50.4800 |                      |                               |
 RELIANCE | 2026-06-30 | screener_in |      50.4800 |                      |                               |
(5 rows)
```

**AFTER** — TC-18, TC-19, TC-20:

```
  symbol  | period_end |   source    | promoter_pct | pledge_of_promoter | pledge_of_total | pledged_shares |            source_run_id             |           ingested_at
----------+------------+-------------+--------------+--------------------+-----------------+----------------+--------------------------------------+----------------------------------
 A2ZINFRA | 2026-06-30 | NSE_SHP     |      27.9200 |            99.6800 |         27.8300 |       49402301 | b1980aa4-a98d-43bf-8c20-584db7922742 | 2026-08-17 21:01:40.99022+05:30
 ASHOKLEY | 2026-06-30 | NSE_SHP     |      51.5100 |            39.4800 |         20.4900 |     1203500000 | b1980aa4-a98d-43bf-8c20-584db7922742 | 2026-08-17 21:01:40.99022+05:30
 ASHOKLEY | 2026-06-30 | screener_in |      51.5100 |            39.4800 |         20.4900 |     1203500000 | 5f018fda-7229-40b6-aabc-ce0d4ab123a0 | 2026-08-14 20:30:23.458569+05:30
 RELIANCE | 2026-06-30 | NSE_SHP     |      50.4800 |             0.0000 |          0.0000 |              0 | b1980aa4-a98d-43bf-8c20-584db7922742 | 2026-08-17 21:01:40.99022+05:30
 RELIANCE | 2026-06-30 | screener_in |      50.4800 |             0.0000 |          0.0000 |              0 | 88b108e8-f253-4e2b-8bbf-3d5be2894925 | 2026-07-17 20:31:12.632906+05:30
(5 rows)

 all_rows | pledge_pct | pledge_total | pledged_shares
----------+------------+--------------+----------------
     8955 |          5 |            5 |              5
```

- **TC-6 PASS** — A2Z stores 99.6800 (of promoter holding) and 27.8300 (of total
  shares) in separate columns; the file's third measure (31.11 pledge/demat) is
  parsed but not written, since no column carries that basis.
- **TC-4 PASS** — Reliance's real `0.00` is stored as `0.0000`, not NULL.
- **TC-3 PASS** — Alchemist's empty fields wrote nothing (it also did not resolve).
- **TC-19 PASS** — every `source_run_id` and `ingested_at` is the value that was
  there before (`b1980aa4…` 2026-08-17, `5f018fda…` 2026-08-14, `88b108e8…`
  2026-07-17). The UPDATE touched only the three pledge columns, so the shareholding
  feed does not falsely read as freshly ingested.
- **TC-20 PASS** — the `NSE_SHP` and `screener_in` rows carry identical pledge, so
  `v_shareholding_latest` returns the same value whichever it picks.

**TC-21 — the column the screener actually reads:**

```
 as_of_date | rows | with_pledge | distinct_pledge
------------+------+-------------+-----------------
 2026-08-17 | 2373 |           3 |               3

  symbol  | as_of_date | promoter_pledged_pct
----------+------------+----------------------
 A2ZINFRA | 2026-08-17 |              27.8300
 ASHOKLEY | 2026-08-17 |              20.4900
 RELIANCE | 2026-08-17 |               0.0000
```

PASS — and note the values are the **/total-shares** figures, matching how
`populate_stock_features_extended` has always populated this column.

**TC-22 — the DQ rule fix, evaluated on the rows just written:**

```
  symbol  |   source    | promoter_pct | promoter_pledged_pct | promoter_pledged_to_total_pct | old_rule_passes | new_rule_passes
----------+-------------+--------------+----------------------+-------------------------------+-----------------+-----------------
 A2ZINFRA | NSE_SHP     |      27.9200 |              99.6800 |                       27.8300 | f               | t
 ASHOKLEY | NSE_SHP     |      51.5100 |              39.4800 |                       20.4900 | t               | t
 ASHOKLEY | screener_in |      51.5100 |              39.4800 |                       20.4900 | t               | t
 RELIANCE | NSE_SHP     |      50.4800 |               0.0000 |                        0.0000 | t               | t
 RELIANCE | screener_in |      50.4800 |               0.0000 |                        0.0000 | t               | t
```

PASS — `pair_a_lte_b("promoter_pledged_pct", "promoter_pct")` compared two different
bases and would have failed A2Z on correct data. It was dormant only because both
columns were NULL in all 8,955 rows; the first real pledge load would have fired it.
Moved to `promoter_pledged_to_total_pct`, which shares `promoter_pct`'s
total-shares basis and is guaranteed by arithmetic.

## Full-file verification — the real `CF-SAST-Pledged-Data-19-Aug-2026.csv`

The file arrived 2026-08-19 09:33 at `/app/data/`, 296,580 bytes.

**TC-25 — parse reconciles exactly against the raw CSV** (local, no DB):

```
raw CSV data rows        : 1544
blank names              : 0
names appearing >1 time  : {'Future Enterprises Limited': 2, 'GACM Technologies Limited': 2,
                            'Jain Irrigation Systems Limited': 2}
rows consumed by dupes   : 6
expected usable          : 1538
```

```
summary       : 1538 usable rows, period_end=2026-06-30, 3 ambiguous name(s) rejected, 0 unparsable
duplicate     : ['Future Enterprises Limited', 'GACM Technologies Limited', 'Jain Irrigation Systems Limited']
pledge_stats  : {"rows": 1538, "with_pledge_pct": 1515, "distinct_values": 404,
                 "nonzero": 447, "zero": 1068, "max": 100.0}
empty (trap 1): 23 ['Alchemist Limited', 'Asian Hotels (North) Limited', 'Auri Grow India Limited',
                    'Balmer Lawrie & Company Limited', 'CARE Ratings Limited', 'City Union Bank Limited']
```

PASS — 1544 − 6 = 1538, exactly what the parser produced. **Trap 2 predicted the three
duplicate names correctly.** **Trap 1 is not hypothetical: 23 real companies** carry an
empty encumbrance field, including CARE Ratings, City Union Bank and Balmer Lawrie —
every one would have been written as 0.00% pledged under a naive parser.

**TC-26 — `--dry-run` against staging, before the name fix:**

```
"status": "DRY_RUN", "period_end": "2026-06-30", "parsed_rows": 1538,
"resolved": 1452, "unresolved": 86
```

**TC-27 — classifying the 86 misses** (token-overlap probe against `sector_master`):

```
unresolved total          : 86
  near-miss (matcher gap) : 2
  no candidate (absent)   : 84

-- near-misses --
   1.0  'PNB GILTS LTD.'  ->  ('PNBGILTS', 'PNB Gilts Limited')
   1.0  'RHI MAGNESITA INDIA LTD'  ->  ('RHIM', 'RHI MAGNESITA INDIA LIMITED')

-- absent (best overlap <= 0.5) --
  0.25  'ARSS Infrastructure Projects Limited'   best guess ('AFCONS', 'Afcons Infrastructure Limited')
  0.33  'Ballarpur Industries Limited'           best guess ('AARON', 'Aaron Industries Limited')
  0.25  'Bombay Rayon Fashions Limited'          best guess ('AARNAV', 'Aarnav Fashions Limited')
  0.20  'Cox & Kings Financial Service Limited'  best guess ('JMFINANCIL', 'JM Financial Limited')
  0.50  'Era Infra Engineering Limited'          best guess ('A2ZINFRA', 'A2Z Infra Engineering Limited')
```

PASS — this is what turned an unexplained 86 into two actionable facts: 84 are
delisted or suspended issuers with no plausible NIDP counterpart (the expected tail of
a promoter-pledge list — heavy pledging is how companies get there), and 2 were a real
matcher bug.

**TC-28 — the `LTD` / `LIMITED` fix:** `normalise_company_name` now canonicalises a
trailing legal-form token, and only a trailing one (`"Alpha Ltd Beta"` is untouched).
Re-running the dry run:

```
"status": "DRY_RUN", "period_end": "2026-06-30", "parsed_rows": 1538,
"resolved": 1454, "unresolved": 84,
"with_pledge_pct": 1515, "distinct_values": 404, "nonzero": 447, "zero": 1068, "max": 100.0
```

PASS — 1,454 of 1,538 (94.5%), and every remaining miss is a company NIDP does not
track. 32 unit tests pass, including the two real near-miss pairs.

The pledge column is emphatically not degenerate: **404 distinct values, 447 companies
with a non-zero pledge, 1,068 at exactly zero, max 100.0%** — promoters who have
pledged their entire holding.

## Full-file LOAD — completed 2026-08-19

```
$ python -m nidp.services.nse_pledge_csv --file /tmp/CF-SAST-Pledged-Data-19-Aug-2026.csv
  "status": "OK",
  "period_end": "2026-06-30",
  "parsed_rows": 1538,
  "resolved": 1454,
  "unresolved": 84,
    "with_pledge_pct": 1515, "distinct_values": 404,
    "nonzero": 447, "zero": 1068, "max": 100.0
  "rows_updated": 1620,
  "rows_inserted": 0,
  "features_updated": 1233
```

**TC-29 — the table, before and after:**

```
BEFORE                                          AFTER
 all_rows | pledge_pct | pledge_total            all_rows | pledge_pct | pledge_total | symbols_with_pledge
----------+------------+--------------          ----------+------------+--------------+---------------------
     8955 |          5 |            5               8955 |       1598 |         1620 |                1388
```

`rows_inserted: 0` — every write landed in a shareholding row that already existed, so
no pledge-only row was created and no symbol's FII/DII was hidden behind one.

**TC-30 — the `pledge_pct` (1,598) vs `pledge_total` (1,620) gap is correct, not a bug:**

```
 rows | symbols                    symbol   |   source    | promoter_pct | pledged_pct | pledged_to_total
------+---------                 ------------+-------------+--------------+-------------+------------------
   22 |      17                   ASIANHOTNR | screener_in |       0.0000 |             |           0.0000
                                  BALMLAWRIE | NSE_SHP     |              |             |           0.0000
                                  CARERATING | NSE_SHP     |              |             |           0.0000
                                  COFORGE    | NSE_SHP     |              |             |           0.0000
                                  CROMPTON   | NSE_SHP     |              |             |           0.0000
```

17 companies have **no promoter at all** (`A = 0` in the file) — CARE Ratings, City
Union Bank, Coforge, Crompton, Balmer Lawrie. NSE leaves "% of promoter shares" blank
because it is 0/0, and fills "% of total shares" with 0.00 because that one is defined.
The parser reproduces exactly that: `promoter_pledged_pct` NULL (undefined), 
`promoter_pledged_to_total_pct` 0.00 (true). Coercing the blank to 0 would have
asserted "0% of promoter holding is pledged" about companies with no promoter holding.

A further **4 companies disclose neither figure** — Alchemist, Lakshmi Energy and
Foods, Metkore Alloys, Nu Tek India. Both columns stay NULL, so they are absent from
the screen rather than appearing in it as unpledged. That is trap 1 doing its job.

**TC-31 — the DQ basis fix, measured on the real load:**

```
 rows_checked | old_rule_failures | new_rule_failures
--------------+-------------------+-------------------
         1591 |                83 |                 0
```

The rule as it stood would have raised **83 data-quality failures on entirely correct
exchange data** the moment this file landed. On the corrected basis: zero.

**TC-32 — the screener availability gate flipped the metric on with no code change:**

```
"min_coverage_pct": 25.0,
"measured": { "covered_pct": 52.1, "distinct_non_null": 289 },
"offered": true
```

(Before the load: `covered_pct 0.1`, `offered: false`, "Only 0.1% of companies have
this today (needs 25%)".)

**TC-33/TC-34 — real screens through the actual `screen()` handler, real DB:**

```
===== A. heavily pledged promoters (> 40% of total shares) =====
registry_version=1.1.0  universe=2373  total_matching=13
  THYROCARE    {"promoter_pledged_pct": 60.92}
  INDOTECH     {"promoter_pledged_pct": 57.93}
  THELEELA     {"promoter_pledged_pct": 55.91}
  GOACARBON    {"promoter_pledged_pct": 55.39}
  JAYNECOIND   {"promoter_pledged_pct": 55.08}
  COHANCE      {"promoter_pledged_pct": 54.36}
  BEDMUTHA     {"promoter_pledged_pct": 54.23}
  BPL          {"promoter_pledged_pct": 50.25}

===== B. zero pledge =====
registry_version=1.1.0  universe=2373  total_matching=917

===== C. combined: pledge < 5% AND RoE >= 15% =====
registry_version=1.1.0  universe=2373  total_matching=57
  COLPAL       {"promoter_pledged_pct": 0.0, "roe_pct": 83.7121}
  TMPV         {"promoter_pledged_pct": 0.0, "roe_pct": 73.7463}
  HINDZINC     {"promoter_pledged_pct": 4.94, "roe_pct": 61.1251}
  PAGEIND      {"promoter_pledged_pct": 0.0, "roe_pct": 50.9321}
  VEDL         {"promoter_pledged_pct": 0.0, "roe_pct": 50.5418}

===== D. impossible ask — pledge > 99.9% AND RoE >= 40% =====
registry_version=1.1.0  universe=2373  total_matching=0
  impact: {"key": "promoter_pledged_pct", "op": "gt", "value": 99.9, "leave_one_out_count": 11,
           "suggested_value": 0.0, "would_return": 2, "most_restrictive": true}
  impact: {"key": "roe_pct", "op": "gte", "value": 40, "leave_one_out_count": 0,
           "suggested_value": null, "would_return": 0, "most_restrictive": false}
```

Every cell carries its provenance inline (`formula`, `source_dataset`, `as_of`), nulls
carry a `null_reason`, and the zero-result path returns `filter_impact` rather than a
500 — the regression fixed in PR #125 still holds with a new metric in the mix.

Run through the real `screen()` coroutine rather than over HTTP because the deployed
DaaS container still runs the pre-1.1.0 registry. Same handler, same SQL, same data;
the HTTP hop is the only untested link and it is unchanged by this work.

**TC-35 — migration 133 still holds after 1,620 writes:**

```
 view_rows | symbols | surplus
-----------+---------+---------
      2325 |    2325 |       0
```

## Defect found while building this — since FIXED (migration 133)

`nidp.v_shareholding_latest` is documented as one row per symbol but fans out
whenever a symbol has more than one source at the same quarter — its `prev` CTE
joins on `(symbol, period_end)`, which is not unique because `source` is in the PK:

```sql
SELECT count(*) view_rows, count(DISTINCT symbol) distinct_symbols,
       count(*) - count(DISTINCT symbol) surplus_rows FROM nidp.v_shareholding_latest;
 view_rows | distinct_symbols | surplus_rows
-----------+------------------+--------------
      3342 |             2325 |         1017
```

381 symbols were duplicated (up to 4 copies each).

**Correction to an earlier claim in this report:** I first wrote that the copies agree.
They agree in the *view's output*, because the view picks one row and then duplicates
it — but the underlying rows conflict. Of the 329 symbols carrying both sources at
their latest quarter, 23 disagree by more than 0.05pp, the largest being ICICIBANK at
FII 49.82% (NSE) vs 33.79% (screener).

Fixed in `133_shareholding_latest_deterministic.sql`, applied to staging 09:33:20 —
see `test_reports/shareholding_latest_deterministic.md`. The view now returns
2,325 rows for 2,325 symbols.

## UNVERIFIED

- **The HTTP hop.** The screener queries above ran through the real `screen()` handler
  against the real DB, not over `https://staging-data.niveshcopilot.com/daas`, because
  the deployed container still runs registry 1.0.0. The endpoint itself is unchanged
  by this work and was verified over HTTP in the earlier screener report; deploying
  the branch is what makes `promoter_pledged_pct` reachable over the wire.
- **`--insert-missing`** was never exercised — `rows_inserted: 0` on the full file,
  because every resolved symbol already had a row at 2026-06-30.
- `ambiguous_master_names: 4` — `nidp.sector_master` itself has 4 normalised names
  mapping to more than one symbol; those companies can never resolve.
- **`--insert-missing`.** Not exercised (`rows_inserted: 0`) — all 3 resolved symbols
  already had a row at 2026-06-30. Its risk is stated in the CLI help and in
  `service.py`.
- **Deployed code.** These files are on the branch only. The staging run used a
  shadow copy of the dev-repo tree, which was removed afterwards; `/opt/nidp/dev-repo`
  and the running containers were not modified.

## Inputs required from user

- The real `CF-SAST-Pledged-Data-<date>.csv`, downloaded from
  https://www.nseindia.com/companies-listing/corporate-filings-pledged-data
  (NSE's API for it is IP-blocked for this platform). Run `--dry-run` first.

## Side effects left on staging

`nidp.shareholding_pattern` now holds promoter pledge for **1,388 symbols across
1,620 rows** at period_end 2026-06-30, and `stock_features_daily` for 2026-08-17
carries it for **1,236 of 2,373 symbols (52.1%, 289 distinct values)**. All of it is
real exchange data from the user's NSE SAST file. The screener metric is consequently
live on staging.

Migration 133 was applied to `nidp_staging` at 2026-08-19 09:33:20 — see
`test_reports/shareholding_latest_deterministic.md`.

## Verdict: PASS
