# Functionality Verification Report — TrueData long price history + nightly TD_* macro refresh

- **Branch:** feat/truedata-price-history (from origin/dev)
- **Date:** 2026-11-03 (work 2 Nov 23:40 – 3 Nov ~01:00 IST)
- **Author:** Claude (full-stack + QA + domain data-trust)
- **Environment:** throwaway containers (`nivesh/backend:staging` image, `postgres:16-alpine`, no network) + STAGING
  warehouse READ ONLY (`nidp-psql.sh`, SELECT / `\copy … TO STDOUT` only) + TrueData read-only calls (73).
  **Nothing was migrated, loaded, deployed, scheduled or restarted on staging or prod.**
- **Changed areas:** backend NIDP services/migration/DaaS router: yes · frontend src: no
- **Test cases:** `test_reports/truedata_price_history_TESTCASES.md` (written before the code; TC-08b added after the
  first real-data run, reason stated there)

## Summary

Research Copilot category 20 (correlation & sensitivity) needs stock prices before 2024-04-01. This branch adds:
- migration **191**: `nidp.prices_eod_history` (own table, NOT `prices_eod_adjusted`), `nidp.prices_eod_history_stitch`
  (one row per symbol per run: status, factor, overlap, seam numbers), research-only view
  `nidp.v_prices_eod_long_research`;
- `python -m nidp.services.truedata_history` — backfill from the raw directory and/or TrueData, stitched to our basis
  (factor = our adj_close / TD close over our first 10 days, stable within TD's 0.05 rounding + 2 bp, >= 3 days; seam
  <= 7 days; TD basis unchanged since the raw fetch; factor in [0.5, 2] or up to 10 with a demerger recorded after our
  first day), one transaction per batch, run id, `--dry-run`, `--replace`, `--rollback RUN_ID`;
- `python -m nidp.services.truedata_macro` — nightly append of the 24 `TD_*` series in `nidp.fred_macro` (same ids,
  names, units, caveats as the 2 Nov load), new days only, never an unfinished MCX/index bar, `--rollback RUN_ID`;
  cron file `deploy/cloudpe/nidp/nidp-staging-truedata-macro.cron` (00:15 IST daily; NOT installed);
- DaaS `GET /v1/prices/research-long/{symbol}` reading the view.
Both jobs ask the market-data switch first: at `current` nothing calls TrueData and nothing is written (the macro job
records a SKIPPED run, like `truedata_crosscheck`); rollback works at any position.

## Test Cases

| ID | Scenario | Type | Result |
|----|----------|------|--------|
| TC-01 | duplicates collapse, disagreeing copies drop the date, bad rows dropped | unit | PASS |
| TC-02 | same basis with TD rounding → factor exactly 1 | unit | PASS |
| TC-03 | demerger basis → rescaled, seam = TD's own move | unit | PASS |
| TC-04 | ratio moves inside overlap → UNSTABLE | unit | PASS |
| TC-05 | < 3 overlap days → NO_OVERLAP | unit | PASS |
| TC-06 | seam > 7 days → SEAM_GAP | unit | PASS |
| TC-07 | TD basis changed / no common date → BASIS_CHANGED / NO_BASIS_CHECK | unit | PASS |
| TC-08 | factor outside [0.5, 2] without a recorded demerger → FACTOR_OUT_OF_RANGE | unit | PASS |
| TC-08b | factor > 2 with a demerger after our first day → LOADED; before it / < 0.5 / > 10 → flagged | unit + PG | PASS |
| TC-09 | history on/after our first day never emitted | unit | PASS |
| TC-10 | today's MCX bar dropped before 23:59, index before 16:00, future always | unit | PASS |
| TC-11 | switch at current (file / forced env): 0 TD calls, 0 writes; macro SKIPPED; rollback runs | unit | PASS |
| TC-12 | macro: new days only, up-to-date = no call, EMPTY ≠ failure, failure → PARTIAL, 24 ids/labels | unit + real dry run | PASS |
| TC-13 | migration 191 twice on fresh PG16; PK, CHECK; view prefers our prices | PG container | PASS |
| TC-14 | batches + run id, SKIPPED_EXISTING, --replace, exact rollback, failure in a batch leaves nothing | PG container | PASS |
| TC-15 | --dry-run writes nothing | PG container | PASS |
| TC-16 | macro insert-only, no rewrite, exact rollback, job_log rows | PG container | PASS |
| TC-17 | DaaS route: 401 without key, filters, pagination, 400 bad date, real view SQL | unit + PG container | PASS |
| TC-18 | 50 real symbols stitched against staging's first warehouse days | real data, read-only | PASS |
| TC-19 | no credential printed / written | check | PASS |
| TC-20 | regression: full `nidp/tests` tree vs origin/dev | unit | PASS (no new failure) |

## API / Endpoint and pytest evidence (real output)

- New suites, unit + real PostgreSQL 16 (`postgres:16-alpine --network none`, backend image joined with
  `--network container:tdh-pg`, `PG_TEST_DSN` set):
  - Command: `python -m pytest nidp/tests/services/test_truedata_history.py nidp/tests/services/test_truedata_history_pg.py -q -p no:cacheprovider`
  - Output: `28 passed, 2 warnings in 3.91s`
  - Verbose run (before the last TC-17 robustness edit) listed all 23 unit + 5 PG cases `PASSED`, e.g.
    `test_tc14_tc15_loader_batches_runs_skips_replaces_and_rolls_back_exactly PASSED`,
    `test_tc16_macro_inserts_only_new_days_never_rewrites_and_rolls_back_exactly PASSED`,
    `test_tc17_route_reads_the_real_view PASSED`.
  - A real bug the PG tests caught (fixed): the batch temp table `LIKE nidp.prices_eod_history` dropped the
    `ingested_at` default → `NotNullViolationError` on COPY; now `INCLUDING DEFAULTS`.
- Regression (TC-20), full tree, same container, branch vs `git archive origin/dev backend`:
  - Branch: `45 failed, 1510 passed, 5 skipped, 24 warnings, 5 errors in 28.94s`
  - origin/dev: `47 failed, 1480 passed, 5 skipped, 24 warnings, 5 errors in 24.65s`
  - Failures only on the branch: **none**. 50 common (pre-existing in this image: replay engine, AMFI, classifier,
    dynamic runner, MF AMC, pipeline stages, and MS-11 / SW-7 which assert the committed switch file is `current` while
    dev's says `shadow`: `AssertionError: assert ('shadow' == 'current'` on pristine origin/dev too). The 2 dev-only
    failures are cron-file tests that cannot see `deploy/` in a backend-only archive.
  - Order note: `test_daas_api.py` patches `pg.get_pool` on the pg module; a router imported earlier keeps whatever
    `get_pool` it bound. In default (alphabetical) order nothing breaks; TC-17 (PG) now pins `prices.get_pool` to the
    real pool so it no longer depends on order.
- Staging endpoint: **not run** (route not deployed, migration not applied — see UNVERIFIED).

## Data Correctness — real data (TC-18, read only)

Inputs: raw history files `/home/deploy/nivesh-truedata-raw/equity/eod` (fetch finished 23:56 IST, 3,033 files);
staging's first 10 `prices_eod_adjusted` days per symbol (`\copy … TO STDOUT`, 30,072 rows, 3,035 symbols) and its 44
demerger rows from `nidp.corporate_actions`; TrueData overlap bars for 50 symbols (one sequential call each, window
from 10 days before the last history bar to our 10th day: 18 bars each, 0 errors). The REAL CLI ran against a
throwaway PostgreSQL seeded with those staging rows:
`python -m nidp.services.truedata_history --raw-dir /raw --overlap-dir /chk/overlap --symbols-file /chk/sample50.txt`

Sample: RELIANCE TCS ITC HDFCBANK BAJFINANCE INFY SIEMENS RAYMOND NESTLEIND ABB SBIN + 39 drawn with a fixed seed
(20261102) from the 1,188 seam-OK symbols.

```
market_data_source = shadow
symbols = 50
status_counts = {'LOADED': 50}
rows_stitched = 125984
rows_inserted = 125984
factor_exactly_1 = 45
factor_min = 1.0
factor_max = 4.94681809
max_overlap_dev_pct = 0.150497
seam_vs_td_move_max_pct = 0.103448
job_status = OK
rescaled: ALLCARGO 3.2 (dev 0.094697%), DCMSRIND 3.37977682 (0.047396%), ITC 1.06000492 (0.004933%),
          RAYMOND 4.94681809 (0.005317%), SIEMENS 2.01000108 (0.000862%)   — all 10 overlap days
```
Stitch table (throwaway DB): 50 symbols, overlap days 10/10 for all, median overlap deviation 0.0000 %, max 0.150497 %
(VAISHALI, a low-priced stock where TD's 0.05 rounding dominates); history 2010-01-04 .. 2024-03-28, warehouse from
2024-04-01 for all 50; 2 duplicate dates (identical copies), 0 conflicting.
Seam continuity (our first adj_close vs the last stitched close, beside TrueData's own move over the same days):
**48/50 within 5 bp**; worst VAISHALI −0.1034 %, TFCILTD +0.0563 %, DCMSRIND −0.0248 %; RELIANCE −0.0017 %
(−0.072349 % vs TD −0.070667 %), ITC (−0.384731 % vs −0.383568 %), SIEMENS (1.653516 % vs 1.653171 %),
TCS and HDFCBANK identical.
ITC's factor 1.06000492 matches the 2 Nov measurement (426.70 / 402.55 = 1.05999).

The first run (before TC-08b) flagged SIEMENS 2.01, ALLCARGO 3.2, DCMSRIND 3.38, RAYMOND 4.95 FACTOR_OUT_OF_RANGE.
Staging, read only: each has a demerger after its first warehouse day (SIEMENS 2025-04-07, ALLCARGO 2025-11-12,
DCMSRIND 2025-12-26, RAYMOND 2024-07-11 + 2025-05-14) and our adjusted series shows the unadjusted one-day drop
(SIEMENS −42.93 % on 2025-04-07, ALLCARGO −61.97 %, DCMSRIND −71.50 %, RAYMOND −34.97 % / −60.42 %). Rule refined to
accept a factor > 2 (<= 10) only with such a record.
Rollback exercised on real rows: a setup slip (missing unique index in the throwaway schema) crashed one run after its
batches committed; `--rollback cbf13b29-…` returned `"deleted_rows": 114821, "deleted_stitch": 50` and both tables were
back to 0.
Size: 125,984 rows = 20 MB = 167.2 bytes/row (table + PK).

### Whole universe (no TrueData calls: seam rule only, branch's own `bars.py`)

| Class | Symbols | Meaning |
|---|---|---|
| SEAM_OK | 1,188 | history ends <= 7 days before our first day; loadable after the overlap check (2,818,187 rows, ~471 MB at 167 B/row; 1,188 TD calls ≈ 25 min) |
| SEAM_GAP | 962 | our adjusted series starts much later (gap min 11, median 552, max 1,735 days) |
| NO_HISTORY | 883 | 882 `EMPTY_RESPONSE` + 1 `IDENTIFIER_NOT_RESOLVED` (TATAMOTORS) |

F&O stocks (218 on the latest F&O day): 188 SEAM_OK, 9 no history (listed after Mar 2024: ATHERENERG ENRIN HYUNDAI
ICICILIFE PREMIERENE SAGILITY SWIGGY VMM WAAREEENER), 21 SEAM_GAP (ABCAPITAL ADANIENSOL ADANIGREEN AMBER DELHIVERY DMART
ETERNAL GMRAIRPORT GVT&D IDEA KAYNES LTF LTM MFSL NYKAA PAYTM POLICYBZR SUZLON TMPV UNITDSPR YESBANK).

**Warehouse finding (not this PR's to fix):** most SEAM_GAPs are our price adjuster's coverage, not TrueData's. Staging
`prices_eod` (raw, EQ) starts 2024-04-01 for ADANIGREEN, DMART, IDEA, YESBANK, PAYTM, ABCAPITAL, but their
`prices_eod_adjusted` starts 2025-10-01 (999 symbols start in Oct 2025; 995 of them have raw prices > 30 days earlier).
Re-running the adjuster over 2024-04-01..2025-09-30 would also fix every reader of `prices_eod_adjusted` in that window;
this loader can then be re-run for those symbols (they are not loaded, so no `--replace` needed).

### The 883 empty files, classified (warehouse evidence: raw span, series, ISIN under another symbol)

| Class | Symbols | Example |
|---|---|---|
| first traded after Mar 2024 (listing / relisting) — nothing to fetch | 822 | 3BBLACKBIO 2026-04-20.., AADHARHFC 2024-05-15.., AEROPLANE/AMIRCHAND (ISIN shared) |
| renamed: same ISIN has TrueData history under the NEW name | 56 | AKZOINDIA → JSWDULUX, AXISGOLD → GOLDAXIS, AXIS ETFs |
| renamed away, still empty | 1 | SABTNL → AQYLON |
| first raw row 2024-04-01..03 but effectively new / non-equity series | 4 | SRM (listed 2024-04-03), TATACAP (BL/N6/N8 debt series before its listing), LIQUIDADD, SILVER (ETFs) |

TrueData's own symbol-change history (9 calls) is keyed by the OLD name: AKZOINDIA → JSWDULUX 2026-04-15,
LTIM → LTM 2026-02-27, AXISGOLD → GOLDAXIS 2026-07-03, SABTNL → AQYLON 2026-02-11, TATAMOTORS → TMPV 2025-10-24;
querying the new names returns `[]`. Our warehouse starts each new name exactly on the rename date (LTM 2026-02-27,
GOLDAXIS 2026-07-03, JSWDULUX 2026-04-15, TMPV 2025-10-24), so their TrueData history is SEAM_GAP by design (flagged,
not bridged). Follow-up option: an ISIN / symbol-change chain that stitches the new name's history to the OLD name's
first warehouse day.

### Macro job, real dry run (TC-12; TrueData read-only, staging's last stored dates, nothing written)

`now_ist 2026-11-03T00:04+05:30`, `verdict DRY_RUN`, `calls 14`, `new_rows 14`, `rows_inserted 0`, `failed []`.
Each of the 14 MCX series: last stored 2026-10-30, fetched 2026-10-31..2026-11-02, 1 new day (2026-11-02; Sat/Sun
have no bar), no conflicting or unfinished dates. The 10 index series (last stored 2026-11-02): `UP_TO_DATE`, 0 calls.

### Secrets (TC-19)
`secret scan: 941 files, 2 credential values checked, 0 hits` (worktree changes, test reports, cron dir, scratch
outputs). Credentials were only read inside processes, never printed.

## UNVERIFIED (out of scope by rule: staging read-only, no deploy)
- Migration 191 is not applied on staging or prod; the view's plan on the staging hypertable (31+ chunks) is not
  measured (on PG16: grouped join, symbol filter pushed into the aggregate, 4.9 ms for ITC).
- No backfill run against staging; the 1,188-symbol load (~2.8 M rows, ~471 MB, ~25 min of TD calls) needs disk
  headroom checked on the NIDP VM first.
- `truedata_macro` not run with writes anywhere but the throwaway DB; cron file not installed. The NIDP VM needs
  `TRUEDATA_USERNAME` / `TRUEDATA_PASSWORD` in `nidp.env` (the switch counts env vars, not `TRUEDATA_CRED_FILE`).
- DaaS `/v1/prices/research-long/{symbol}` not deployed, not called on staging.
- MCX values: no independent reference (as on 2 Nov).

## Inputs required from user
- none

## Verdict: PASS
