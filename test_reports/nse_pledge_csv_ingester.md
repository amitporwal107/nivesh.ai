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

Verified end-to-end against the real staging DB using a fixture built from **verbatim
rows of the user's real `CF-SAST-Pledged-Data-19-Aug-2026.csv`** (real exchange
values, not invented data), covering the three traps that file contains. The full
file was not available on disk at verification time, so whole-file coverage is
reported as UNVERIFIED below and is what `--dry-run` exists to measure.

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

## Defect found, NOT fixed here (pre-existing, out of scope)

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

381 symbols are duplicated (up to 4 copies each). Today the copies agree — 0 symbols
have conflicting `fii_pct` or `promoter_pct` — so it is a row-multiplication bug, not
yet a wrong-value bug, and anything that JOINs this view is silently multiplying
rows. Fixing it means changing a view that many consumers read (including
`populate_stock_features_extended`), which is a bigger change than a pledge ingest
should carry. Reported for a decision rather than fixed.

## UNVERIFIED

- **Whole-file behaviour.** Verification used 6 verbatim rows from the user's real
  file; the full CSV was not on disk at verification time. The resolved/unresolved
  split for the full file is exactly what `--dry-run` reports and must be read before
  the real run. `ambiguous_master_names: 4` also shows `nidp.sector_master` itself has
  4 normalised names mapping to more than one symbol; those companies cannot resolve.
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

`nidp.shareholding_pattern` now holds real pledge for 3 symbols (RELIANCE, ASHOKLEY,
A2ZINFRA) at 2026-06-30, and `stock_features_daily` for 2026-08-17 likewise. These
are real exchange values from the user's file, left in place as the evidence above.
At 0.1% coverage the screener's availability gate keeps the metric hidden, so nothing
surfaces it as though the universe were covered. Loading the full file supersedes them.

## Verdict: PASS
