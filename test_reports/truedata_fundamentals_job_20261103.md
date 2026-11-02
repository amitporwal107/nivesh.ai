# Functionality Verification Report — TrueData fundamentals NIDP job

- **Branch:** `feat/truedata-fundamentals-job` (base `origin/dev` fb66b6d0)
- **Date:** 2026-11-03 (work started 2 Nov 23:00 IST)
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DOMAIN_EXPERT_ANALYST for data trust)
- **Environment:** local throwaway containers (`postgres:16-alpine`, and `timescale/timescaledb:2.26.4-pg16` = staging's
  version); staging warehouse READ-ONLY for references and comparison; a handful of live TrueData calls.
- **Changed areas:** backend routes/services (`backend/routes`, `backend/services`): **no** · NIDP job
  (`backend/nidp/services/truedata_fundamentals`, `backend/nidp/shared/sources/truedata.py`, migration 190): yes ·
  frontend src: no

## Summary
The supervised 2 Nov loads (scratchpad scripts) are now a reviewed NIDP job: corporate methods on the TrueData client,
a pure transform (dedupe, period end, units, mapping, identity checks), load planning + loader (one transaction,
fill-only, durable provenance in `nidp.truedata_fundamentals_fills`, `--dry-run`, exact `--rollback RUN_ID`), a CLI,
an incremental raw cache, the market-data switch gate, rate limiting with a run deadline, a quarterly finance-costs
pass, and a cron file (not installed). Test cases were written first:
`test_reports/truedata_fundamentals_job_TESTCASES.md`.

There is no HTTP endpoint in this change (a NIDP batch job). The job cannot run on the staging NIDP VM until the PR is
merged, migration 190 is applied by the deploy and the owner installs the cron file — see **UNVERIFIED** below.

## Test Cases

| ID | Area | Scenario | Type | Result |
|----|------|----------|------|--------|
| TC-01 | client | `result_list` → corporate host, Bearer, Records | unit | PASS |
| TC-02 | client | JSON failure answers (HTTP 200) classified, never data | unit | PASS |
| TC-03 | client | one-line text / HTML / non-JSON / HTTP errors | unit | PASS |
| TC-04 | client | statement params, 401 refresh once, per-host gate | unit | PASS |
| TC-05 | client | no password / token in errors, repr, logs | unit | PASS |
| TC-06 | transform | duplicate ids → one filing; > 45 days → two | unit | PASS |
| TC-07 | transform | `&amp;` decode, NOTLISTED/None → BSE map, unknown dropped | unit | PASS |
| TC-08 | transform | consolidated preferred, standalone only without consolidated | unit | PASS |
| TC-09 | transform | period end (FY, Apr-FY H1, Dec-FY H1, SME, stated date) | unit | PASS |
| TC-10 | transform | TCS-like crore (ratio 1), lakh (ratio 100, 4 quarters) | unit | PASS |
| TC-11 | transform | RADICO-like 3.475 → share-capital anchor → crore; 1.5x limit | unit | PASS |
| TC-12 | transform | rounding text "Lakhs" → lakh; nothing → REFUSED | unit | PASS |
| TC-13 | transform | CL = Liabilities − NCL when CL is 0; lakh → crore | unit | PASS |
| TC-14 | transform | bank-format balance sheet skipped | unit | PASS |
| TC-15 | transform | identity rejections (BS + CF); capital guard (10x refused, 5x bonus allowed) | unit | PASS |
| TC-16 | transform | FY cash flow offered (capex negative); H1 never | unit | PASS |
| TC-17 | transform | finance costs: quarter offer; bank skip; not-a-quarter / negative / revenue mismatch rejected | unit | PASS |
| TC-18 | loader (PG) | BS fill-only on every row of the date; non-NULL never overwritten | integration | PASS |
| TC-19 | loader (PG) | FY with no row → one `annual`/`truedata` row; H1 never; no share capital | integration | PASS |
| TC-20 | loader (PG) | cash flow insert when none; existing row NULL-only fill | integration | PASS |
| TC-21 | loader (PG) | finance costs only on NULL quarterly rows | integration | PASS |
| TC-22 | loader (PG) | provenance row per write: columns, values, inserted, unit, filing id | integration | PASS |
| TC-23 | loader (PG) | dry run: tables unchanged; counts = real run's, key for key | integration | PASS |
| TC-24 | loader (PG) | rollback → tables identical to before; another writer's later value kept; 2nd rollback no-op | integration | PASS |
| TC-25 | loader (PG) | same input twice → 0 new writes | integration | PASS |
| TC-26 | loader (PG) | error mid-load → nothing written | failure | PASS |
| TC-27 | migration | 190 applied twice on a fresh DB (idempotent) — in every PG test | integration | PASS |
| TC-28 | job | `current` → no call, only a SKIPPED job_log row; `shadow` runs; rollback ignores switch | unit | PASS |
| TC-29 | job | cache: no refetch; last 3 days' lists refetched; empty cached, failures not; rate limit; deadline; refused login | unit | PASS |
| TC-30 | job | CLI parsing and return codes 0/1/2 | unit | PASS |
| TC-31 | real data | transform on real raw files vs the 2 Nov staging rows | data | PASS (identical or each difference explained) |
| TC-32 | real data | `InterestExpense` = finance costs? vs our own figures | data | PASS (scoped below) |
| TC-33 | live | 6 real calls through the new client methods | app | PASS |
| TC-34 | regression | existing TrueData / switch / DQ-suite tests | unit | PASS — no new failure; 2 failures pre-exist on origin/dev (below) |

## Tests (real output)

New suites, no database (the Postgres tests skip without a DSN):
```
$ docker run --rm --network none -v <worktree>:/work:ro -w /work/backend ... nivesh/backend:staging \
    python -m pytest nidp/tests/shared/test_truedata_corporate.py nidp/tests/services/test_truedata_fundamentals_transform.py \
    nidp/tests/services/test_truedata_fundamentals_service.py nidp/tests/services/test_truedata_fundamentals_pg.py -q -p no:cacheprovider
78 passed, 8 skipped in 0.66s
```
Postgres suite on a throwaway `postgres:16-alpine` (`--network none`; `NIDP_TDF_PG_DSN` set):
```
test_tc18_to_tc22_fill_only_inserts_provenance PASSED
test_tc23_dry_run_writes_nothing_and_matches_the_real_run PASSED
test_tc24_rollback_restores_exactly_and_is_idempotent PASSED
test_tc24_rollback_keeps_a_value_another_writer_set_since PASSED
test_tc24_rollback_refuses_a_non_uuid PASSED
test_tc25_same_input_twice_writes_nothing_new PASSED
test_tc26_error_mid_load_leaves_nothing PASSED
test_read_references_shares_from_market_cap_and_close_on_its_date PASSED
8 passed in 1.38s
```
Same 8 on `timescale/timescaledb:2.26.4-pg16` with `nse_financials_quarterly` created as a hypertable
(`NIDP_TDF_TIMESCALE=1`; staging runs TimescaleDB 2.26.4, PG16.13, 24 uncompressed chunks — read from staging's
catalog), proving `SELECT … FOR UPDATE OF q`, `ON CONFLICT` and the exact rollback on a hypertable:
```
8 passed in 2.24s          (hypertable check: nidp.nse_financials_quarterly|1)
```
Regression (existing suites):
```
$ python -m pytest nidp/tests/shared/test_truedata_client.py nidp/tests/shared/test_market_data_source.py \
    tests/test_truedata_adapter.py tests/test_truedata_live.py tests/test_market_data_switch_live_feed.py \
    nidp/services/quality_gate/tests/test_dq_suites.py -q
FAILED nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off
FAILED nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current
2 failed, 119 passed, 2 warnings in 8.31s
```
The same two fail on a pristine `git archive origin/dev` (fb66b6d0) extract — they assert the committed switch is
`current`, but dev ships `shadow` since 30 Oct. Not touched here:
```
FAILED nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off
FAILED nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current
2 failed, 61 passed in 0.47s
```

## API / Endpoint Tests (staging)
None: no route or app service changed. The job's staging run is UNVERIFIED (see below).

## UI / Playwright Tests
Not applicable: no frontend change.

## Data Correctness

### TC-31 — the job's transform on the real raw files vs the staging rows of the 2 Nov loads (read-only)
Inputs: `/home/deploy/nivesh-truedata-raw` (855 day lists, statements fetched so far), staging rows exported read-only
(`source = 'truedata'` cash flows; rows tagged `raw_data.truedata_balance_sheet`). Run twice: with the 2 Nov reference
snapshots, and with references freshly exported from staging using the job's own queries. Both runs:
```
CASH FLOW staging rows: identical 419, different 0, no offer 0
BALANCE SHEET staging rows: identical 990, different 3, no offer 1; columns compared 8677
   ('bs diff', ('balance_sheet', '360ONE', '2025-03-31', True), 'annual', [('filing id', '2203868', 2203870)])
   ('bs diff', ('balance_sheet', '360ONE', '2025-09-30', True), 'quarterly', [('filing id', '2203862', 2203864)])
   ('bs diff', ('balance_sheet', 'ABCAPITAL', '2025-03-31', True), 'annual', [('filing id', '2191828', 2191830)])
   ('bs missing', ('balance_sheet', 'SWIGGY', '2024-09-30', True), 'quarterly', '2218681')
```
Every differing case explained:
- The 3 "bs diff" rows have **identical values in every filled column**; only the recorded filing id differs. Each pair
  is one filing listed twice (same symbol, file time, label, nature — e.g. 2191828 / 2191830 ABCAPITAL
  2025-05-13T20:55:00 Yearly Consolidated); wave 1 ran before the dedupe patch.
- SWIGGY 2024-09-30 is refused by the job's new per-filing unit guard: that pre-IPO filing's share capital is 13,440
  (incl. preference capital) against 261 in the anchoring FY26 P&L (51x). Its own rounding text says "Millions" while
  its values are crore-consistent with later filings — exactly the ambiguity the guard exists for. The guard refuses
  only ratios >= 6.67x (10/1.5); bonus issues pass (BAJFINANCE 5.0x, PATANJALI 3.0x were initially refused at 3x and
  the threshold was set from this evidence).

### TC-31 (end to end) — the real CLI, real raw files, rebuilt pre-load warehouse
The user's 10-company TC-05 sample (RADICO, UNITDSPR, TCS, INFY, RELIANCE, LT, MARUTI, SUNPHARMA, DLF, HAL) — staging's
rows exported read-only with the 2 Nov fills NULLed back per their tags — loaded into a throwaway DB; then
`python -m nidp.services.truedata_fundamentals --offline --raw-dir <raw> --days 1000 --anchor-days 0 --symbols …`
`--dry-run`, the load, and `--rollback RUN_ID`. Output (TimescaleDB 2.26.4 hypertable; identical on plain PG16):
```
hypertable: 1
seeded quarterly rows: 179 cash-flow rows: 0
DRY RUN rc 0 status OK load {'dry_run': True, 'would_write_rows': 75, 'balance_sheet_columns_written': 493, 'balance_sheet_fill_rows': 55, 'cash_flow_columns_written': 100, 'cash_flow_insert_rows': 20, 'balance_sheet_half_year_no_row': 6}
  after dry run: tables unchanged: True ; job_log rows: 0 ; provenance rows: 0
LOAD rc 0 status OK run 0bd72bbe-6cab-4cdc-881b-e778cbba5533
  universe {'symbols': 10, 'bse_codes': 0, 'with_shares': 10} fetch {'needed': 195, 'calls': 0, 'filings_in_window': 98}
  transform {"offers": {"balance_sheet": 48, "cash_flow": 20}, "rejects": 0, "counts": {"cf_half_year_not_loaded": 29, "fc_not_fetched": 87, "filings": 98, "superseded_by_later_filing": 1}, "units": {"crore": 10}, "units_how": {"revenue anchor": 8, "share-capital anchor": 2}, "reject_reasons": {}}
  load {'dry_run': False, 'planned_rows': 75, 'balance_sheet_half_year_no_row': 6, 'balance_sheet_columns_written': 493, 'balance_sheet_fill_rows': 55, 'cash_flow_columns_written': 100, 'cash_flow_insert_rows': 20, 'cashflow_insert_conflicts': 0, 'rows_written': 75}
  job_log: {'status': 'OK', 'rows_inserted': 75, 'rows_skipped': 0}
QUARTERLY rows vs staging now: identical 179, different 0, extra rows from the job 0
CASH FLOW rows: staging 20, job 20, identical 20, missing [], extra []
PROVENANCE fills vs staging tags: equal 55 of 55; job-only []
ROLLBACK rc 0 {'rollback_of': '0bd72bbe-6cab-4cdc-881b-e778cbba5533', 'columns_changed_since_kept': 0, 'columns_reset_to_null': 493, 'inserted_rows_deleted': 20, 'provenance_rows': 75, 'rows_reset': 55}
  after rollback: tables identical to the pre-load state: True
```
(`fc_not_fetched 87`: the quarter-only P&Ls are phase 2 of the background fetch, not on disk yet; offline mode fetches
nothing.)

### TC-32 — is `Expenses.NonOperating.InterestExpense` the finance-cost line?
FY P&L (cumulative) InterestExpense, unit-converted by the job's own unit inference, vs our `finance_costs_cr` on the
same fiscal-year row (`screener_in_annual`), every company with both (final code, references fresh from staging):
```
FY pairs by |TrueData/ours - 1|: {'<=1%': 181, '<=20%': 18, 'no pair': 175, '<=5%': 30, 'both zero': 4, '>20%': 20, 'one side zero': 2}
   ('TATAINVEST', '2026-03-31', 0.57, 1.0, 'screener_in_annual')
   ('HAVELLS', '2026-03-31', 37.3, 79.0, 'screener_in_annual')
   ('OFSS', '2026-03-31', 2.5, 2.0, 'screener_in_annual')
   ('IGL', '2026-03-31', 15.44, 35.0, 'screener_in_annual')
   ('FSL', '2026-03-31', 181.47, 230.0, 'screener_in_annual')
   ('TRENT', '2026-03-31', 168.35, 233.0, 'screener_in_annual')
   ('RAILTEL', '2026-03-31', 3.78, 5.0, 'screener_in_annual')
   ('CGPOWER', '2026-03-31', 12.17, 25.0, 'screener_in_annual')
   ('LT', '2026-03-31', 2848.82, 10056.0, 'screener_in_annual')
   ('INTELLECT', '2026-03-31', 6.31, 10.0, 'screener_in_annual')
   ('HONAUT', '2026-03-31', 9.7, 16.0, 'screener_in_annual')
   ('BHEL', '2026-03-31', 756.41, 986.0, 'screener_in_annual')
   ('BEL', '2026-03-31', 6.73, 10.0, 'screener_in_annual')
   ('CLEAN', '2026-03-31', 0.35, 1.0, 'screener_in_annual')
   ('GVT&D', '2026-03-31', 14.75, 35.0, 'screener_in_annual')
   ('KEC', '2026-03-31', 663.6, 872.0, 'screener_in_annual')
   ('NAUKRI', '2026-03-31', 27.43, 42.0, 'screener_in_annual')
   ('ENGINERSIN', '2026-03-31', 2.12, 5.0, 'screener_in_annual')
   ('CONCORDBIO', '2026-03-31', 0.28, 1.0, 'screener_in_annual')
   ('ITCHOTELS', '2026-03-31', 7.93, 55.0, 'screener_in_annual')
```
211 of 255 pairs agree within 5 % (181 within 1 %); 4 are zero on both sides. Of the 20 pairs beyond 20 %, several
are tiny figures where Screener's whole-crore rounding dominates (TATAINVEST 0.57 vs 1, OFSS 2.5 vs 2, CLEAN 0.35 vs 1,
CONCORDBIO 0.28 vs 1); LT is definitional (TrueData carries the filed "Finance costs" line; Screener's "Interest" adds
the financial-services subsidiary's interest). The remaining large gaps (HAVELLS, IGL, TRENT, CGPOWER, ITCHOTELS, …)
were NOT individually verified: for those companies TrueData's filed line and Screener's annual "Interest" differ, so a
TTM mixing the two sources would be inconsistent. The job only fills quarters that have NO finance cost, and refuses a
quarter whose TrueData revenue is > 5 % from our row's revenue. Quarterly, live (cumulative=false, Jul–Sep 2026):
INFY 115.0 vs ours 115 (screener_in), MARUTI 67.7 vs 68.

### TC-33 — live calls (real TrueData, 6 HTTP calls incl. the token, 1.5 s gate)
```
configured: True
result_list 2026-10-23: 157 records; 2 Nov cache: 157 ; INFY Q2 consolidated id present: True
balance_sheet 2331914 keys: ['AllAssets', 'AllLiabilities', 'GeneralInfo'] ; equal to 2 Nov cache: True
cash_flow 2331914 summary keys: 8 ; equal to 2 Nov cache: True
pnl(cumulative=false) INFY 2331914: period 2026-07-01..2026-09-30 type 'Main/Ind'; InterestExpense 115.0 vs ours (screener_in) 115.0; revenue 49244.0; offer: {'finance_costs_cr': Decimal('115.0')}
pnl(cumulative=false) MARUTI 2332310: period 2026-07-01..2026-09-30 type 'Main/Ind'; InterestExpense 67.7 vs ours (screener_in) 68.0; revenue 53355.5; offer: {'finance_costs_cr': Decimal('67.7')}
HTTP calls: 6 ( token, getResultList, getResultALById, getCashFlowDetailById, getPnLById, getPnLById )
secret absent from output and logs: True
```

### Migration 190
Applied twice to a fresh database at the start of every PG test (PG16 and TimescaleDB 2.26.4) without error; the
provenance assertions read from it. NOT applied to staging (that happens on deploy).

### DQ suite
Not changed. `quality_gate` (22:30 IST) already runs `nse_financials_cashflow_suite` on the table nightly; the job's
own row checks (identities, unit guard, quarter revenue) are stricter and run before anything is written.

## Inputs required from user
- none

## UNVERIFIED (after merge — not part of this verdict)
- The job running on the staging NIDP VM: needs the merge, the deploy (applies migration 190 and puts the code in the
  NIDP checkout) and the owner installing `deploy/cloudpe/nidp/nidp-staging-truedata-fundamentals.cron`. First check:
  `run_service.sh truedata_fundamentals --days 10 --dry-run`, then a real run, then
  `SELECT status, rows_inserted, metadata FROM nidp.job_log WHERE ingester = 'truedata_fundamentals' ORDER BY started_at DESC LIMIT 1;`
  and `SELECT kind, count(*) FROM nidp.truedata_fundamentals_fills GROUP BY 1;`.
- First staging run's cost: an empty raw cache means ~400 list calls (anchor window) plus statements; it will stop at
  `--max-minutes 75` with status PARTIAL and carry on the next night. Optional: seed the cache by copying the 2 Nov
  raw directory to `$NIDP_RAW_DIR/truedata_fundamentals/` (same layout).
- The quarterly finance-costs pass has run only on synthetic data, 8 cached quarter P&Ls and 2 live ones; its real
  volume and reject rate are unknown until the quarter-only P&Ls are fetched.
- The 2 Nov supervised loads are not in the provenance table (made before it existed); their record stays the three
  manifests in `/home/deploy/nivesh-truedata-raw/manifests/`.

## Verdict: PASS
