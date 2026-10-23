# Functionality Verification Report — MF Holdings Canonical Dedupe + Measured Coverage

- **Branch:** fix/mf-holdings-dedupe (from feat/provider-foundations @ 8dc09801)
- **Date:** 2026-10-23
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST)
- **Environment:** nidp_staging warehouse (CloudPe, **READ-ONLY** for this session) + a throwaway
  local Postgres 16 for the DDL, + CI-runnable pytest
- **Changed areas:** backend services: yes (`mf_holdings_deltas`, `smart_money_scores`,
  new `mf_holdings/canonical.py`) · migrations: yes (182, 183) · frontend src: no
- **Test cases authored up front:** `test_reports/mf_holdings_dedupe_TESTCASES.md` (2026-10-23,
  before implementation)

## Summary

Two INDEPENDENT data-quality defects were measured, fixed and reconciled SEPARATELY. They are
reported separately on purpose: they partly cancel, and any single "net" figure hides both.

1. **DUPLICATION — fixed at the canonicalisation layer.** `nidp.mf_holdings_monthly` stores one
   holding once per plan/option `scheme_code`. 2026-09: **156,683 equity-leg rows collapse to
   38,318 canonical (fund x ISIN) rows = 4.089x**, and every month from 2025-09 to 2026-09 sits
   between 3.687x and 4.312x. The fan-out is **AMC-specific** (UTI 1.00x, ABSL 3.40x, TATA 6.00x
   on HAL), so summing `scheme_code` rows also biases any breadth measure toward houses that run
   more plan variants.
2. **COVERAGE — measured and explained, NOT closed.** After dedupe we see a **median 0.560** of
   the mutual-fund holding each company discloses (Nifty 500, 2026-09, n=408). That is the honest
   figure for a book that indexes **11 of the 56 AMCs** in `nidp.mf_amc_master`. It is now a
   stored, per-stock measurement with a stated basis, replacing a `coverage_pct` column that was
   the constant 100.00 on all 25,313 rows.

**Explicitly not claimed.** "Deduplication fixed" does not mean coverage improved, and coverage is
not improved by this change at all — the numerator fell. Removing duplicates cannot add a missing
AMC, and indexing a new AMC will re-introduce fan-out unless it goes through the canonical layer.
The product identity in the brief (2.18 ~= 4.03 x 0.54) holds only loosely at the median
(4.089 x 0.560 = 2.29 against a measured median naive ratio of 2.102) because medians are not
multiplicative and because the pre-fix sum also nets short-futures legs against cash legs.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | canonical key | Axis Children's Fund, 8 plan/option rows | unit | one base scheme, one canonical row | **PASS** |
| TC-2 | canonical key | trailing plan, no option | unit | plan stripped, Direct==Regular | **PASS** |
| TC-3 | canonical key | option-only names | unit | collapse to the fund | **PASS** |
| TC-4 | canonical key | case-only difference | unit | same key | **PASS** |
| TC-5 | canonical key | plan/option word mid-name | unit | NOT truncated | **PASS** |
| TC-6 | canonical key | two sources for one AMC-month (quant) | unit+data | one canonical row, 2 sources | **PASS** |
| TC-7 | leg class | short futures, written options, unmarked negatives | unit | derivative; excluded AND reported | **PASS** |
| TC-8 | data trust | implied price vs EQ/BE close | data | >=99% within 0.3%, none beyond 5% | **PASS** (99.10% / 100.00%) |
| TC-9 | AMC validation | per-source median implied/close | data | 1.0000 for every source | **PASS** |
| TC-10 | coverage | measured coverage per stock | data | median in [0.40,0.75], not 100.00 | **PASS** (0.560) |
| TC-11 | coverage | company discloses neither input | edge | NULL + stated basis, never 0 | **PASS** |
| TC-12 | coverage | quantified explanation of the gap | data | AMC + scheme panel quantified | **PARTIAL** — count and named sizable absentees measured; rupee-weighted AMC gap **UNVERIFIED** (only 10 of 56 AMCs carry an AUM figure) |
| TC-13 | reconciliation (CI) | deduped vs disclosed per stock | unit (CI) | >=90% within 1.05x | **PASS** (15/15 fixture, 408/408 staging) |
| TC-14 | reconciliation (CI) | same assertion on the naive sum | regression | must FAIL | **PASS** (fails: 12.5% staging) |
| TC-15 | provenance | canonical row keeps provenance | data | sources, urls, period, published/observed, ingested | **PASS** |
| TC-16 | restatement | a backfill changes a published quantity | unit+data | logged old->new with run id | **PASS** (local PG) |
| TC-17 | restatement | re-ingest writes the same value | edge | nothing logged | **PASS** (local PG) |
| TC-18 | deltas | deltas at canonical grain | data | one row per fund x ISIN | **UNVERIFIED on staging** — SELECT half run on real data (41,217 rows / 665 funds / 4.175x); the INSERT cannot run read-only |
| TC-19 | deltas | constant panel vs growing panel | edge | panel entries carry no direction | **PASS for the rule** (DB constraint rejects it, local PG) + **UNVERIFIED** for the stored rows |
| TC-20 | deltas | naive figure retained for audit | data | naive_* columns populated | **UNVERIFIED on staging** (same reason); computed in the verified SELECT |
| TC-21 | migration | apply 182/183 twice | idempotency | second run a no-op | **PASS** (local PG) |
| TC-22 | no regression | `v_smart_money_coverage_by_date` after the relabel | data | reads subsignal_coverage_pct | **PASS** (local PG) |

## THE EVIDENCE TABLE

### 1. Raw records — original row count and source provenance

```
$ echo "SELECT source, count(*) AS rows, count(DISTINCT scheme_code) AS schemes,
         min(as_of_month) AS mn, max(as_of_month) AS mx
    FROM nidp.mf_holdings_monthly GROUP BY 1 ORDER BY 2 DESC;" | ~/.config/nivesh/nidp-psql.sh

              source              |  rows  | schemes |     mn     |     mx
----------------------------------+--------+---------+------------+------------
 NIPPON_DISCLOSURE_ADVISORKHOJ    | 358026 |     462 | 2025-09-01 | 2026-09-01
 ICICI_PRU_DISCLOSURE_ADVISORKHOJ | 351220 |     487 | 2025-09-01 | 2026-09-01
 KOTAK_DISCLOSURE_ADVISORKHOJ     | 234272 |     356 | 2025-09-01 | 2026-09-01
 TATA_DISCLOSURE_ADVISORKHOJ      | 205867 |     329 | 2025-09-01 | 2026-09-01
 ABSL_DISCLOSURE_ADVISORKHOJ      | 199432 |     275 | 2025-09-01 | 2026-09-01
 AXIS_DISCLOSURE_ADVISORKHOJ      | 101610 |     312 | 2026-05-01 | 2026-09-01
 FRANKLIN_DISCLOSURE_ADVISORKHOJ  |  90678 |     187 | 2025-09-01 | 2026-09-01
 SBI_DISCLOSURE_ADVISORKHOJ       |  39019 |     351 | 2026-07-01 | 2026-08-01
 UTI_MF_PORTFOLIO_ZIP             |  30962 |      53 | 2025-10-01 | 2026-09-01
 SBI_MF_PORTFOLIO_XLSX            |  24737 |     457 | 2026-09-01 | 2026-09-01
 QUANT_DISCLOSURE_ADVISORKHOJ     |  24460 |     116 | 2025-10-01 | 2026-09-01
 PPFAS_DISCLOSURE_ADVISORKHOJ     |  21080 |      26 | 2025-09-01 | 2026-09-01
 QUANT_MF_PORTFOLIO_XLSX          |   5784 |      48 | 2026-01-01 | 2026-09-01
 NIPPON_MF_PORTFOLIO_XLSX         |     33 |       1 | 2025-11-01 | 2026-09-01
(14 rows)
```

14 adapters over 11 AMCs. Three AMCs are ingested from TWO sources each (sbi, quant, nippon) —
the AMC's own file plus the third-party index — which is a second duplication axis, handled below.
Every source maps to exactly one `amc_id` (`distinct_amc_ids = 1`, 14/14), which is what makes the
source-derived AMC fallback safe.

### 2 + 3. Canonical records, and WHICH records were removed and why

`nidp.v_mf_holdings_dedupe_audit`, run as a read-only CTE chain generated from migration 182
(timing is the real cost of the view):

```
 as_of_month | source_rows | equity_rows | derivative_rows | no_quantity_rows | no_isin_rows | canonical_rows | duplication_factor | groups_qty_conflict | pct_qty_conflict | groups_scheme_unresolved
-------------+-------------+-------------+-----------------+------------------+--------------+----------------+--------------------+---------------------+------------------+--------------------------
 2025-09-01  |      109217 |       88847 |            1304 |            19066 |            0 |          20604 |              4.312 |                   0 |            0.000 |                        0
 2025-10-01  |      114008 |       93901 |            1484 |            18623 |            0 |          23552 |              3.987 |                   0 |            0.000 |                        0
 2025-11-01  |       85650 |       71503 |            1602 |            12545 |            3 |          19391 |              3.687 |                   0 |            0.000 |                        0
 2025-12-01  |      116321 |       96181 |            1583 |            18557 |            3 |          23984 |              4.010 |                   1 |            0.004 |                        0
 2026-01-01  |      115059 |       95184 |            1478 |            18396 |          478 |          23949 |              3.974 |                   1 |            0.004 |                        0
 2026-02-01  |      111674 |       92840 |            1255 |            17579 |            3 |          23778 |              3.904 |                   1 |            0.004 |                        0
 2026-03-01  |      114674 |       95238 |            1750 |            17685 |          478 |          24422 |              3.900 |                   0 |            0.000 |                        0
 2026-04-01  |      118308 |       97302 |            1732 |            19273 |          478 |          24609 |              3.954 |                   1 |            0.004 |                        0
 2026-05-01  |      133999 |      113212 |            1666 |            19121 |            3 |          28189 |              4.016 |                   1 |            0.004 |                        0
 2026-06-01  |      136486 |      114990 |            1676 |            19819 |          478 |          29127 |              3.948 |                   2 |            0.007 |                        0
 2026-07-01  |      152110 |      131039 |            1638 |            19433 |            3 |          33257 |              3.940 |                   0 |            0.000 |                        0
 2026-08-01  |      185918 |      151695 |            2091 |            32131 |          478 |          37719 |              4.022 |                   0 |            0.000 |                        0
 2026-09-01  |      193756 |      156683 |            2946 |            34125 |         2863 |          38318 |              4.089 |                  36 |            0.094 |                      698
(13 rows)
Time: 64960.519 ms (01:04.961)
```

Which rows were removed, 2026-09, and why:

```
                       reason                        | source_rows_removed | canonical_rows_kept
-----------------------------------------------------+---------------------+---------------------
 collapsed: identical copies, one source             |              115565 |               37663
 collapsed: same fund from two sources               |                2799 |                 654
 collapsed: variants disagreed (max positive kept)   |                   1 |                   1
 excluded: derivative legs (expiry/option/negative)  |                2946 |
 excluded: no ISIN (cannot be tied to an instrument) |                2863 |
 excluded: no quantity disclosed (cash/receivables)  |               34125 |
(6 rows)
Time: 59696.734 ms (00:59.697)
```

156,683 - (115,565 + 2,799 + 1) = **38,318 canonical rows**, which is the figure in the audit table.
Nothing is deleted from the fact table; the collapse happens in a view.

* **115,565** rows were exact copies of a fund's holding under another plan/option `scheme_code`
  (99.906% of groups carry ONE distinct quantity, so these are copies, not share-class splits).
* **2,799** were the same fund arriving from two sources. Example: `quant BFSI Fund` appears under
  AMFI codes from AdvisorKhoj and under its own NAME from `QUANT_MF_PORTFOLIO_XLSX` — 2,544 rows of
  that adapter resolve to no `mf_scheme_master` row at all, so without deriving the AMC from the
  source they looked like a 12th AMC and quant's book was counted twice.
* **1** group's variants disagreed within a single source; 36 groups disagree in total (0.094%),
  and every one inspected is a long-futures leg the source name does not mark, e.g. quant BFSI Fund
  holding Manappuram at both 2,453,969 shares (implied price 315.85 = the EQ close) and 159,000
  (implied 318.40 = the futures basis). `qty_variants` exposes them.
* **2,946 derivative legs excluded, not netted.** 1,788 short and 495 long expiry-named futures
  plus 647 plain-named negatives including written options (`Kotak Mahindra Bank Ltd. (CALL Option)`,
  -10,208,000). A short future is not ownership; netting it against the cash leg would erase a real
  holding. They are reported per canonical row (`derivative_rows`, `derivative_legs`,
  `derivative_net_quantity`) — and deduplicated the same way, so the reported short is not 4x.
* **34,125 rows carry no quantity** (cash/receivables/TREPS) and **2,863 no ISIN**. Both are
  excluded from a share count and counted, never read as zero.

### 4. Coverage — expected universe vs actual

```
 amcs_registered | amcs_indexed | amcs_with_aum_figure | absentees_with_aum_figure
-----------------+--------------+----------------------+---------------------------
              56 |           11 |                   10 |                         2

 amc_id |        amc_name         | aum_inr_crore
--------+-------------------------+---------------
 hdfc   | HDFC Mutual Fund        |     920000.00
 mirae  | Mirae Asset Mutual Fund |     215000.00
```

**11 of 56** registered AMCs are indexed. Of the 45 absentees only **two** can be sized from the
warehouse at all — HDFC (9.2 lakh crore) and Mirae (2.15 lakh crore); the other 43 carry no AUM
figure, and `nidp.mf_amc_master.aum_inr_crore` is populated for only 10 rows (the top 10 by AUM),
so **there is no industry denominator in the warehouse**. A rupee-weighted "we cover X% of the
industry" is therefore NOT computed here — computing it off a 10-AMC denominator would have
produced a flattering 81.5% that means nothing. UNVERIFIED, and what it needs: AMFI's AUM-by-AMC
series ingested into `mf_amc_master`.

The scheme panel inside those AMCs, per month (`nidp.v_mf_holdings_canonical`):

```
 as_of_month | amcs | base_schemes | canonical_fund_isin_rows | source_equity_rows | duplication_factor | rows_scheme_unresolved | derivative_legs
-------------+------+--------------+--------------------------+--------------------+--------------------+------------------------+-----------------
 2025-09-01  |    7 |          345 |                    20604 |              88847 |              4.312 |                      0 |             325
 2025-10-01  |    9 |          412 |                    23552 |              93901 |              3.987 |                      0 |             364
 2025-11-01  |    8 |          353 |                    19391 |              71503 |              3.687 |                      0 |             377
 2025-12-01  |    9 |          422 |                    23984 |              96181 |              4.010 |                      0 |             387
 2026-01-01  |    9 |          428 |                    23949 |              95184 |              3.974 |                      0 |             349
 2026-02-01  |    8 |          403 |                    23778 |              92840 |              3.904 |                      0 |             338
 2026-03-01  |    9 |          438 |                    24422 |              95238 |              3.900 |                      0 |             382
 2026-04-01  |    9 |          435 |                    24609 |              97302 |              3.954 |                      0 |             413
 2026-05-01  |    9 |          465 |                    28189 |             113212 |              4.016 |                      0 |             443
 2026-06-01  |   10 |          499 |                    29127 |             114990 |              3.948 |                      0 |             365
 2026-07-01  |   10 |          546 |                    33257 |             131039 |              3.940 |                      0 |             410
 2026-08-01  |   11 |          631 |                    37719 |             151695 |              4.022 |                      0 |             466
 2026-09-01  |   11 |          665 |                    38318 |             156683 |              4.089 |                    698 |             577
(13 rows)
Time: 57957.231 ms (00:57.957)
```

The panel nearly doubles over the year: **7 AMCs / 345 base schemes (2025-09) -> 9 / 435 (2026-04)
-> 11 / 665 (2026-09)**. (The brief's 9/492 -> 11/746 used the plan-suffix regex only; the
canonical key collapses further — option-only names, case differences and cross-source copies — so
the base-scheme counts are lower. The direction and the consequence are identical.)

Within the indexed AMCs the scheme coverage is also incomplete and very uneven. Active schemes in
`mf_scheme_master` (counted at the plan-variant grain, which is how the master stores them) that
disclosed holdings in 2026-09:

```
       amc_id       | master_schemes | with_sep_holdings | pct_covered
--------------------+----------------+-------------------+-------------
 icici_pru          |           2505 |               475 |        19.0
 nippon             |           1870 |               459 |        24.5
 uti                |           1364 |                52 |         3.8
 kotak              |            939 |               352 |        37.5
 sbi                |            493 |               457 |        92.7
 absl               |            414 |               267 |        64.5
 axis               |            409 |               299 |        73.1
 tata               |            407 |               311 |        76.4
 franklin_templeton |            309 |               169 |        54.7
 quant              |            133 |               133 |       100.0
 ppfas              |             28 |                26 |        92.9
(11 rows)
```

That denominator includes debt/liquid/closed plans that hold no equity, so it is an upper bound on
what is missing, not a coverage figure — but UTI at 3.8% (52 schemes from a single ZIP) is a real
second-order gap on top of the 45 missing houses.

**So the 0.56 decomposes into:** 45 of 56 AMC houses not indexed (dominant, two of them sized at
9.2 and 2.15 lakh crore AUM, the rest unsized in-warehouse) + incomplete scheme coverage inside
the 11 indexed houses (UTI the worst) + 698 scheme codes in 2026-09 we hold under a name rather
than a resolvable master row. It does NOT decompose into anything that would be fixed by changing
the numerator.

### 5. Holdings reconciliation — source totals vs aggregated Nivesh totals

Per-stock, Nifty 500, 2026-09, against each company's OWN shareholding filing
(`total_shares x mf_pct`), via `nidp.v_mf_stock_coverage`:

```
 n_names | median_coverage | mean_coverage | median_naive_ratio | mean_naive_ratio | dedup_within_bound | pct_dedup_within_bound | naive_within_bound | pct_naive_within_bound | agg_coverage | agg_naive
---------+-----------------+---------------+--------------------+------------------+--------------------+------------------------+--------------------+------------------------+--------------+-----------
     408 |           0.560 |         0.534 |              2.102 |            2.166 |                408 |                  100.0 |                 51 |                   12.5 |        0.605 |     2.267
(1 row)
Time: 64732.242 ms (01:04.732)
```

* **Deduplicated: 408 of 408 names (100.0%)** are within the stated bound (<= 1.05x of the
  disclosed mutual-fund holding). Median 0.560.
* **Pre-fix: 51 of 408 (12.5%)** were within that bound; the median name claimed **2.102x** the
  company's disclosed MF holding, which is arithmetically impossible.

HAL, the worked example, every month we hold:

```
 symbol | as_of_month |   mf_shares   | naive_mf_shares | funds | amcs | expected_mf_shares | coverage_ratio | naive_ratio |               coverage_basis                | disclosure_period_end | disclosed_mf_pct
--------+-------------+---------------+-----------------+-------+------+--------------------+----------------+-------------+---------------------------------------------+-----------------------+------------------
 HAL    | 2025-09-01  |  9627144.0000 |   39876540.0000 |    64 |    7 |                    |                |             | company_discloses_no_mf_pct_or_total_shares |                       |
 ...
 HAL    | 2026-08-01  | 26708248.0000 |  108325242.0000 |   135 |   11 |                    |                |             | company_discloses_no_mf_pct_or_total_shares |                       |
 HAL    | 2026-09-01  | 25923551.0000 |  105279151.0000 |   132 |   11 |           44941680 |         0.5768 |      2.3426 | measured                                    | 2026-09-30            |           6.7200
(13 rows)
```

25,923,551 canonical against 44,941,680 disclosed = **0.5768**; the pre-fix sum of 105,279,151 was
**2.3426x** the disclosed holding. Twelve of HAL's thirteen months have NO expected side at all
(`NSE_SHP` holds one filing for HAL), and they are reported as NULL with the reason, not as 0 or 1.

Second, independent expected side — the vendor's all-AMC MF share count
(`nidp.trendlyne_ownership`), which agrees with the filings and not with our old sum:

```
  n  | median_dedup_over_vendor | median_raw_over_vendor | agg_dedup_over_vendor | agg_raw_over_vendor
-----+--------------------------+------------------------+-----------------------+---------------------
 481 |                    0.567 |                  2.072 |                 0.621 |               2.153
(1 row)
```

0.567 against the vendor, 0.560 against the filings: two unrelated sources, same answer. The 2x was
ours.

### 6. Historical integrity — do backfills alter published snapshots?

Before this change the answer was **unknowable**, and that is the finding:

```
 as_of_month |  rows  | ingest_runs | first_ingest | last_ingest | days_between_first_and_last | rows_written_after_first_observation
-------------+--------+-------------+--------------+-------------+-----------------------------+--------------------------------------
 2025-09-01  | 109217 |           3 | 2026-10-22   | 2026-10-22  |                           0 |                                    0
 ...
 2026-08-01  | 185918 |           5 | 2026-10-22   | 2026-10-22  |                           0 |                                    0
 2026-09-01  | 193756 |           5 | 2026-10-12   | 2026-10-22  |                          10 |                                    0
(13 rows)

 amc_months_with_multiple_runs
-------------------------------
                             1
```

One (source, month) pair has already been written by more than one run, and 2026-09 was re-touched
ten days after its first ingest — but `writer.py` upserts `quantity = EXCLUDED.quantity`, so no
before-image was ever kept and **whether any published number changed cannot be recovered for the
past**. Migration 183 makes it recordable from now on. Verified in a throwaway Postgres 16 with
both migrations applied to stub tables and real seed rows:

```
=== TC-16: the trigger logs a restated quantity ===
UPDATE 1
 scheme_code | as_of_month |  field   |  old_value  |  new_value  |           restated_by_run
-------------+-------------+----------+-------------+-------------+--------------------------------------
 135762      | 2026-09-01  | quantity | 145772.0000 | 150000.0000 | 00000000-0000-0000-0000-00000000beef
(1 row)

=== TC-17: an unchanged re-ingest logs nothing ===
UPDATE 1
 restatement_rows_after_noop_update
------------------------------------
                                  1
(1 row)

=== restatement summary view ===
 as_of_month |  field   | restatements | schemes_affected | securities_affected | filled_from_null | cleared_to_null | mean_abs_rel_change
-------------+----------+--------------+------------------+---------------------+------------------+-----------------+---------------------
 2026-09-01  | quantity |            1 |                1 |                   1 |                0 |               0 |              0.0290
```

A real change is logged with the run that made it; a re-ingest writing the same value logs nothing.

### 7. Monthly consistency — is the same instrument counted the same way across periods?

The duplication factor is stable (3.687x–4.312x) across all thirteen months, so the fan-out is
structural and not a one-month artefact. The panel, however, is NOT constant (section 4), and that
changes the sign of the monthly flow. Both months below are the delta service's own SQL, run
read-only with its INSERT replaced by an aggregate over the same relation:

```
2026-09 (panel grew 10 -> 11 AMCs, 546 -> 665 base schemes)
 delta_rows | funds | representative_codes | source_rows_collapsed | duplication_factor | constant_panel_rows | panel_entry_rows | new_positions | possible_exits | net_shares_delta_constant_panel | naive_net_shares_delta | net_if_panel_ignored | pit_safe_rows
------------+-------+----------------------+-----------------------+--------------------+---------------------+------------------+---------------+----------------+---------------------------------+------------------------+----------------------+---------------
      41217 |   665 |                  690 |                172088 |              4.175 |               40737 |              480 |          3072 |           2899 |                -2024089171.9395 |       28935385864.6980 |      2706537880.6433 |         31613
Time: 60722.117 ms (01:00.722)

2026-06 (panel grew 9 -> 10 AMCs)
 delta_rows | funds | representative_codes | source_rows_collapsed | duplication_factor | constant_panel_rows | panel_entry_rows | new_positions | possible_exits | net_shares_delta_constant_panel | naive_net_shares_delta | net_if_panel_ignored | pit_safe_rows
------------+-------+----------------------+-----------------------+--------------------+---------------------+------------------+---------------+----------------+---------------------------------+------------------------+----------------------+---------------
      31377 |   499 |                  500 |                126451 |              4.030 |               31097 |              280 |          2222 |           2250 |                -2789195273.9299 |      -1564222699.3444 |     -2788877801.9299 |         17508
Time: 65506.228 ms (01:05.506)
```

For 2026-09 the three figures are:

| basis | net share flow, 2026-09 |
|---|---|
| canonical funds, CONSTANT panel (the fix) | **-2,024,089,172** (net selling) |
| canonical funds, panel ignored | **+2,706,537,881** (net buying) |
| plan-variant sums, constant panel (pre-fix) | **+28,935,385,865** |

The constant-panel guard **flips the sign** in a month when the panel expands: 480 panel-entry rows
are newly indexed funds, and counting their holdings as purchases turns 2.0bn shares of net selling
into 2.7bn of net buying. In 2026-06, where the panel grew less, the sign agrees (-2.789bn vs
-2.789bn) but the pre-fix figure is still wrong by 1.8x (-1.564bn). Both are reported, so the
difference is always visible.

### 8. AMC-level figures — can the aggregation be reproduced independently?

HAL, 2026-09, per AMC (`nidp.v_mf_holdings_canonical`):

```
       amc_id       | funds | canonical_shares | naive_shares  | naive_inflation_x | source_rows | derivative_legs | funds_from_two_sources
--------------------+-------+------------------+---------------+-------------------+-------------+-----------------+------------------------
 icici_pru          |    24 |     7024810.0000 | 26278317.0000 |              3.74 |          88 |               0 |                      0
 nippon             |    21 |     5339405.0000 | 26624230.0000 |              4.99 |          93 |               0 |                      0
 franklin_templeton |    13 |     5017641.0000 | 20256564.0000 |              4.04 |          56 |               0 |                      0
 sbi                |    14 |     3235326.0000 | 13189991.0000 |              4.08 |          53 |               0 |                      0
 absl               |    14 |     1939907.0000 |  6593168.0000 |              3.40 |          41 |               0 |                      0
 axis               |    18 |     1771487.0000 |  7102242.0000 |              4.01 |          78 |               0 |                      0
 kotak              |    12 |     1002628.0000 |  3932527.0000 |              3.92 |          36 |               4 |                      0
 uti                |    10 |      334120.0000 |   334120.0000 |              1.00 |          10 |               0 |                      0
 ppfas              |     3 |      225510.0000 |   790140.0000 |              3.50 |          10 |               0 |                      0
 quant              |     1 |       18450.0000 |    92250.0000 |              5.00 |           5 |               1 |                      1
 tata               |     2 |       14267.0000 |    85602.0000 |              6.00 |          12 |               0 |                      0
(11 rows)
Time: 56786.664 ms (00:56.787)
```

The eleven AMC figures sum to **25,923,551**, exactly the stock-level `mf_shares` in section 5 —
the aggregation is reproducible from the per-AMC parts with no residual. The per-AMC
`naive_inflation_x` column is the bias migration 177 warned about, now measurable: **UTI 1.00x**
(its ZIP adapter writes one row per fund) through **TATA 6.00x**. Raw `scheme_code` counts would
have made Tata look six times as convinced as UTI about the same decision.

Independent reproduction against an AMC's OWN published total is **NOT possible in-warehouse**:
nothing ingests AMC-level or scheme-level published aggregates (AUM, total shares held per scheme).
The two independent checks available were used instead — the company-side filing and the vendor's
all-AMC count (section 5) — plus the implied-price check below.

### Data-trust cross-checks (TC-8 / TC-9)

Implied price (`market_value_inr / quantity`) against the EQ/BE close on the month's last session —
the house rule that `prices_eod` aggregates filter `series IN ('EQ','BE')` is applied (55 series
share symbol+date):

```
 rows  | within_0_1pct | within_0_3pct | within_1pct | within_5pct | beyond_5pct |   p50   |   p99
-------+---------------+---------------+-------------+-------------+-------------+---------+---------
 98818 |         97.33 |         99.10 |       99.92 |      100.00 |        0.00 | 1.00000 | 1.00175

              source              | rows_checked | median_implied_over_close | pct_within_5pct
----------------------------------+--------------+---------------------------+-----------------
 ABSL_DISCLOSURE_ADVISORKHOJ      |        10155 |                    1.0000 |           100.0
 AXIS_DISCLOSURE_ADVISORKHOJ      |        12530 |                    1.0000 |           100.0
 FRANKLIN_DISCLOSURE_ADVISORKHOJ  |         5240 |                    1.0000 |           100.0
 ICICI_PRU_DISCLOSURE_ADVISORKHOJ |        20828 |                    1.0000 |           100.0
 KOTAK_DISCLOSURE_ADVISORKHOJ     |        13944 |                    1.0000 |           100.0
 NIPPON_DISCLOSURE_ADVISORKHOJ    |        17046 |                    1.0000 |           100.0
 PPFAS_DISCLOSURE_ADVISORKHOJ     |          860 |                    1.0000 |           100.0
 QUANT_DISCLOSURE_ADVISORKHOJ     |         2724 |                    1.0000 |           100.0
 QUANT_MF_PORTFOLIO_XLSX          |          693 |                    1.0000 |           100.0
 SBI_MF_PORTFOLIO_XLSX            |        14798 |                    1.0000 |           100.0
(10 rows)
```

Every source's own valuation reproduces the traded close: the QUANTITIES in the fact table are
sound, which is what makes the 2x a pure duplication artefact rather than bad data. TATA and UTI are
absent from this check because they publish NO market value at all (16,639 and 3,836 rows of
2026-09 with `market_value_inr` NULL) — reported, not filled in.

## Unit / CI tests

```
$ sudo docker run --rm -v <worktree>:/repo -w /repo/backend python:3.11-slim bash -lc \
  'pip install -q pytest==8.3.3 fastapi pydantic httpx asyncpg openpyxl beautifulsoup4;
   python -m pytest nidp/tests/services/test_daas_smart_money.py nidp/services/mf_holdings/tests \
     nidp/tests/services/test_mf_holdings_pct_overflow.py \
     nidp/tests/services/test_mf_holdings_reconciliation.py -q'

93 passed, 1 warning in 1.94s
```

`nidp/tests/services/test_mf_holdings_reconciliation.py` is the reconciliation deliverable: 35 of
those tests. It runs with no database, on a committed extract of **3,183 real staging holdings rows**
for 15 Nifty 500 names (chosen by `ntile(15)` over the per-stock fund count, 12 to 147 funds) plus
each company's own filing — `backend/nidp/tests/fixtures/mf_holdings_recon_202609.json`.

It asserts, with the tolerance stated in the file:
* every stock's deduped count is within **1.05x** of the disclosed MF holding, for **>= 90%** of
  names (15/15 in the fixture);
* the **naive** sum FAILS that same assertion (it must, or the test proves nothing);
* median coverage stays in **[0.40, 0.75]** — an upper bound as well as a lower one, so "fixing"
  coverage by inflating the numerator fails the test;
* the duplication factor is 3–6x and the naive/canonical ratio > 3;
* a stock with no disclosed inputs yields `None`, never 0;
* and — the one that keeps the two implementations honest — the Python mirror reproduces
  `nidp.v_mf_stock_shares_monthly`'s staging numbers **to the share** for all 15 names
  (canonical shares, naive shares and fund counts).

That last assertion already caught a real defect during development: deriving the source->AMC map
from a 15-stock subset instead of the whole table split quant in two and silently restored part of
the duplication (+18 funds and +16,498,902 shares on ADANIENT alone). The map is now carried in the
fixture and passed in explicitly.

## Migration tests (local Postgres 16, throwaway container)

```
$ psql -v ON_ERROR_STOP=1 -f 00_stubs.sql -f 10_seed.sql \
       -f 182_mf_holdings_canonical_dedupe.sql -f 183_mf_deltas_constant_panel_and_coverage.sql
APPLY1 exit=0
$ psql -v ON_ERROR_STOP=1 -f 182_... -f 183_...        # TC-21, second application
APPLY2 (re-run, idempotency) exit=0        # 17 lines of output, all "already exists, skipping"
```

Behaviour on real seeded rows:

```
=== TC-1/TC-6/TC-7: canonical grain ===
 amc_id |     base_scheme      | security_isin |    shares     | variant_rows | variant_scheme_codes_n | qty_variants | naive_sum_quantity | derivative_rows | derivative_net_quantity | n_sources | representative_scheme_code |      key_basis
--------+----------------------+---------------+---------------+--------------+------------------------+--------------+--------------------+-----------------+-------------------------+-----------+----------------------------+---------------------
 axis   | axis children's fund | INE296A01024  |   145772.0000 |            8 |                      8 |            1 |       1166176.0000 |               0 |                         |         1 | 135759                     | master_scheme_name
 kotak  | kotak arbitrage fund | INE090A01021  | 23751000.0000 |            4 |                      4 |            1 |      95004000.0000 |              12 |          -23751000.0000 |         1 | 105967                     | master_scheme_name
 quant  | quant bfsi fund      | INE522D01027  |  2453969.0000 |            4 |                      3 |            2 |       7520907.0000 |               0 |                         |         2 | quant BFSI Fund            | scheme_code_as_name
 quant  | quant gilt fund      | IN0020230085  |     5000.0000 |            1 |                      1 |            1 |          5000.0000 |               0 |                         |         1 | 151228                     | master_scheme_name
(4 rows)

=== TC-10/TC-11: measured coverage, and NULL where undisclosed ===
   symbol   | security_isin |   mf_shares   | naive_mf_shares | funds | amcs |  expected_mf_shares   | coverage_ratio | naive_ratio |               coverage_basis
------------+---------------+---------------+-----------------+-------+------+-----------------------+----------------+-------------+---------------------------------------------
            | IN0020230085  |     5000.0000 |       5000.0000 |     1 |    1 |                       |                |             | isin_not_listed_eq_be
 ICICIBANK  | INE090A01021  | 23751000.0000 |   95004000.0000 |     1 |    1 | 30000000.000000000000 |         0.7917 |      3.1668 | measured
 BAJFINANCE | INE296A01024  |   145772.0000 |    1166176.0000 |     1 |    1 |  1000000.000000000000 |         0.1458 |      1.1662 | measured
 MANAPPURAM | INE522D01027  |  2453969.0000 |    7520907.0000 |     1 |    1 |                       |                |             | company_discloses_no_mf_pct_or_total_shares
(4 rows)

=== TC-22: coverage_pct relabelled, not invented ===
 as_of_date |   symbol   | coverage_pct | subsignal_coverage_pct | coverage_basis
------------+------------+--------------+------------------------+----------------
 2026-10-22 | BAJFINANCE |              |                 100.00 | not_measured

=== 183: legacy delta rows labelled, flow view reads only canonical rows ===
 scheme_code | current_month |  computed_basis   | panel_status | canonical_fund_key
-------------+---------------+-------------------+--------------+--------------------
 135762      | 2026-09-01    | plan_variant_rows |              |
 flow_rows_before_recompute = 0

=== panel_entry rows may not carry a direction (constraint) ===
ERROR:  new row for relation "mf_holdings_deltas" violates check constraint
        "mf_holdings_deltas_panel_entry_unknown_chk"
```

Four seeded holdings become four canonical rows; the Kotak arbitrage cash leg survives at
23,751,000 with its three short futures legs reported (and deduplicated: -23,751,000, not
-95,004,000 — a fully hedged book, which is what an arbitrage fund is); the quant fund arrives from
two sources and becomes ONE row; a government bond ISIN is reported as `isin_not_listed_eq_be`
rather than forced onto a symbol; `coverage_pct` is NULL with `coverage_basis = 'not_measured'`
while its old value is preserved under its true name; and the database itself refuses a
panel-entry row that claims a direction.

## Data Correctness (staging) — what is NOT verified

- **The migrations are NOT applied to staging.** The warehouse is read-only for this session. Every
  view body in migration 182 was verified by running the identical SQL as a read-only CTE chain,
  generated mechanically from the migration file (so no SQL was retyped), against real staging
  data — that is the source of every staging number above. Apply with
  `python -m nidp.cli migrate` on the NIDP VM.
- **`nidp.mf_holdings_deltas` is NOT rewritten.** The service's new SQL was verified by running its
  SELECT half (section 7). The INSERT, the legacy-row cleanup and the `panel_status` columns need
  `python -m nidp.services.mf_holdings_deltas --all` after the migration. Until then
  `nidp.v_mf_stock_flow_monthly` is empty **by design** (it reads only
  `computed_basis = 'canonical_fund'` rows) rather than silently mixing two grains.
- **`smart_money_scores` has not been re-run**, so `coverage_pct` on staging is NULL for all 25,313
  existing rows after migration 183 (the honest state: no measured coverage was computed when they
  were written) until the scorer runs.
- **Performance is real and measured.** The canonical view costs ~57–65s for an all-months
  aggregate. Its CTEs are marked `NOT MATERIALIZED` so a single-month filter reaches the base-table
  index — the per-month path is what production uses. An earlier structure that re-read the keyed
  view per branch exceeded 10 minutes and was restructured.
- **UNVERIFIED: the Smart Money scorer's runtime after the change.** It now LEFT JOINs
  `nidp.v_mf_stock_coverage`, whose all-months cost is ~60s; the join is one row per
  (ISIN, month) so it cannot fan the result out, but the scorer cannot be run from here to time it.
  Watch its job_log duration on the first run after deployment.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Resolve the 4.03x duplication at the source/canonicalisation layer | **MET** — 4.089x -> 1.000x at the canonical grain, measured every month, fact table untouched |
| 2 | EXPLAIN (quantify) the 0.54x coverage, do not inflate it | **PARTIALLY MET** — measured per stock (median 0.560) and decomposed into 45 of 56 AMCs missing + uneven scheme coverage + 698 unresolved scheme codes. The rupee-weighted AMC share is **NOT** computable in-warehouse (10 of 56 AMCs carry an AUM figure); stated, not estimated |
| 3 | Validate AMC-level holdings against source disclosures | **MET for the quantities** — 99.10% of priced rows reproduce the EQ/BE close within 0.3%, median 1.0000 for every source. TATA/UTI publish no market value, so they cannot be checked this way |
| 4 | Reconcile scheme-level holdings without double-counting share classes or duplicates | **MET** — share classes, duplicate scheme codes, cross-source copies and derivative legs each handled and separately counted |
| 5 | Confirm aggregates are consistent with published AMC totals where available | **NOT MET as stated** — no published AMC/scheme-level totals are ingested anywhere in NIDP, so there is nothing in-warehouse to reconcile against. Substituted: the company-side filing (408/408 within bound) and the vendor's independent all-AMC count (0.567 vs 0.560). Per-AMC figures are internally reproducible (sum to the stock total exactly) |
| 6 | Preserve source provenance, reporting period, ingestion timestamp | **MET** — canonical rows carry `sources[]`, `source_urls[]`, `as_of_month`, `published_at`, `source_observed_at_min/max`, `ingested_at`, `known_from`/`known_from_basis`, `variant_scheme_codes[]`, `key_basis` |
| 7 | Historical backfills must not alter published snapshots without an auditable correction | **MET going forward, NOT retroactively** — `mf_holdings_restatements` + trigger verified; the past is unrecoverable because no before-image was kept, and one AMC-month has already been re-ingested |

## Inputs required from user

- Write access (or an operator) to apply migrations 182/183 on the NIDP VM and to run
  `mf_holdings_deltas --all` and the Smart Money scorer. Everything else is verified here.
- For criterion 2's rupee weighting: AMFI AUM-by-AMC ingested into `nidp.mf_amc_master`
  (currently 10 of 56 rows).

## Verdict: BLOCKED
<!-- BLOCKED, not PASS: TC-18 and TC-20 are UNVERIFIED on staging because this session has
     read-only access to the warehouse, so the migrations cannot be applied and
     nidp.mf_holdings_deltas cannot be rewritten. All logic behind them was verified against real
     staging data (SELECT half) and in a local Postgres 16. See test_reports/OVERRIDE_mf-holdings-dedupe.md -->
