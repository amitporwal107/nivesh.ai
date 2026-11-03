# Functionality Verification Report — TrueData long price history + nightly TD_* macro refresh

- **Branch:** feat/truedata-price-history (from origin/dev)
- **Date:** 2026-11-03 (work 2 Nov 23:40 – 3 Nov ~01:00 IST)
- **Author:** Claude (full-stack + QA + domain data-trust)
- **Environment:** throwaway containers (`nivesh/backend:staging` image, `postgres:16-alpine`, no network) + STAGING
  warehouse READ ONLY (`nidp-psql.sh`, SELECT / `\copy … TO STDOUT` only) + TrueData read-only calls (73).
  **Nothing was migrated, loaded, deployed, scheduled or restarted on staging or prod.**
- **Changed areas:** backend NIDP services/migration/DaaS router: yes · frontend src: no
- **Test cases:** `test_reports/truedata_price_history_TESTCASES.md` (written before the code; TC-08b added after the
  first real-data run; TC-21 … TC-24 added for the 3 Nov owner rules before the gate code, reasons stated there)
- **PRs:** #455 (merged into dev on 3 Nov, head fa9a7e8a, WITHOUT the staging-only gate) and the follow-up PR with the
  gate (commit 77ea7508 + this report). dev → main (prod) has not happened for either.

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

## Follow-up, 3 Nov — owner rules (staging only, CI, wording)

**1. Staging only** (owner: "keep on staging.. on prod please use our snapshot data"). New `nidp.shared.deploy_env`,
using the repo's existing split rather than a new flag:
- **Deciding signal:** the database being written to. `nidp_staging` is staging (read-only on staging just now:
  `current_database() = nidp_staging`, `current_user = nidp_staging`). `nidp` is production (`deploy/cloudpe-prod`:
  `NIDP_PG_DB` defaults to `nidp`; its README notes that tools hardcoding `nidp_staging` do not work on prod).
- **Any production signal refuses:** database `nidp`, `NIDP_HOME=/opt/nidp` (the prod `run_service.sh` and the prod
  cron, which `deploy-nidp.sh` generates from `nidp-staging.cron` by rewriting the paths), or `NIDP_ENV`/`APP_ENV` =
  prod/production.
- **Fails closed:** anything else is refused (unknown database, odd `NIDP_HOME`, conflicting signals, a failing
  query). `NIDP_ENV=staging` alone never allows, because prod's `nidp.env` was generated from staging's.

`truedata_history` and `truedata_macro` ask the gate after the switch and before any TrueData client, fetch or write.
When refused, the verdict is `NOT_STAGING`, there are 0 TrueData calls and 0 data rows, and a real run records a
SKIPPED `job_log` row (`NOT_STAGING`); a dry run writes nothing. Rollbacks are not gated. The cron file is documented as
staging-only: prod's cron is built from `nidp-staging.cron` alone, so it never reaches prod. The DaaS route stays; on
prod the history table is simply empty and the view and route still answer (TC-22).

**2. CI "Backend unit tests (allowlist)".** GitHub records this check as **failure** on #449, #450, #455, #456 and
#457 alike (API conclusions; logs not readable). The workflow's exact allowlist (`.github/workflows/backend-tests.yml`,
296 files on dev; 298 on the branch, which adds this work's two suites) was run in the same image
(`nivesh/backend:staging`, `--network none`, the workflow's env), on full-tree archives
(backend, deploy, docs, scripts, tools, .github, frontend-v5/e2e/fixtures, research):

| Tree | Allowlist | Result |
|---|---|---|
| origin/dev 5142f906 (base of #455's check) | dev's 296 | `6 failed, 8109 passed, 34 skipped` |
| 5142f906 + this branch (merge tree 94836b32) | branch's 298 | `6 failed, 8152 passed, 42 skipped` |
| origin/dev 19d8d974 (now: #455, #456, #457 merged) | dev's 296 | `6 failed, 8148 passed, 34 skipped` |
| 19d8d974 + this follow-up (merge tree 460449e6) | branch's 298 | `6 failed, 8191 passed, 42 skipped` |

The failure sets are **identical** on both sides of both pairs (`comm` of the sorted FAILED lists: 0 only-PR,
0 only-dev, 6 common). The +43 passed / +8 skipped are exactly the two added suites (43 unit tests; 8 PostgreSQL
tests that skip without `PG_TEST_DSN`). The 6 failures already exist on dev:
- `nidp/tests/shared/test_market_data_source.py::test_ms11_committed_file_is_current` and
  `nidp/tests/shared/test_truedata_client.py::test_sw7_shipped_switch_keeps_truedata_off`: they assert the committed
  switch file says `current`, but dev's says `shadow` since 30 Oct (`AssertionError: assert ('shadow' == 'current'`).
  These fail on any runner, which is why every PR fails the check.
- `tests/test_cas_api_client.py` ×2: `Sandbox call failed — check network / keys`.
- `tests/test_move_odds_filing_analysis.py::test_tc10_tc11_route_gate_validation_and_payload`: `IndexError`.
- `tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`: tries to reach www.nseindia.com.

This branch adds no failure. The check will stay red until MS-11 / SW-7 are updated for the `shadow` switch, which
belongs to the switch owner and is outside this PR.

**3. Wording** (owner: "do not use words like buy, stop loss, target"). Every line the branch adds (2,574 lines vs
the merge-base, plus `deploy_env.py`) and both PR bodies were scanned for buy / sell / stop loss / target / entry / exit
/ accumulate / upside / downside / recommend / tips / bullish / bearish / outperform / advice. There are no
user-visible hits. The only matches were process exit codes in CLI docstrings (renamed "Exit codes:"), a Python
variable `entry` (renamed `info`), and the owner's quoted rule and the scan's own word list inside the test-case file.
User-visible strings are the 24 series names (e.g. "MCX crude oil, near-month continuous future, close", caveat "use
weekly returns") and the route note ("RESEARCH ONLY (returns, correlation, sensitivity) … not quoted prices").

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
| TC-21 | staging-only gate: matrix (12 cases) + both jobs refuse off staging (0 calls, 0 rows, SKIPPED NOT_STAGING), also on real databases named `nidp` / `nidp_unknown_env`; staging runs | unit + PG container | PASS |
| TC-22 | empty history table on a prod-named database: view + route answer 200 (`[]` / our prices only) | PG container | PASS |
| TC-23 | CI allowlist side-by-side, same image | unit | PASS (identical 6 pre-existing failures) |
| TC-24 | wording scan of every added line and both PR bodies | check | PASS (none user-visible) |

## API / Endpoint and pytest evidence (real output)

- New suites, unit + real PostgreSQL 16 (`postgres:16-alpine --network none`, backend image joined with
  `--network container:tdh-pg`, `PG_TEST_DSN` set):
  - Command: `python -m pytest nidp/tests/services/test_truedata_history.py nidp/tests/services/test_truedata_history_pg.py -q -p no:cacheprovider`
  - Output (3 Nov follow-up, with the gate): `51 passed, 2 warnings in 6.11s` (43 unit + 8 PostgreSQL; the PG tests
    run on databases named `nidp_staging`, `nidp` and `nidp_unknown_env`). Before the gate: `28 passed`.
  - Mutation check: with `truedata_load_gate` forced to allow, the unit file gives `6 failed, 37 passed` (every
    off-staging job case fails), so the tests catch a missing gate.
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
- **#455 is merged into dev without the gate.** Until the follow-up PR merges, dev's jobs have only the switch. Both
  must be in place before any dev → main release. Nothing is scheduled or loaded today.
- The gate on the real VMs: staging's database name is verified (`nidp_staging`). Prod's `nidp` comes from the prod
  deploy files and runbook; it was not queried, because there was no prod access in this task. Since any of four
  production signals refuses and unknown also refuses, a different prod name still refuses.
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
