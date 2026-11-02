# TrueData long price history + nightly TD_* macro refresh — test cases (written before the code)

- **Branch:** feat/truedata-price-history (from origin/dev)
- **Date:** 2026-11-02
- **Why:** Research Copilot category 20 (correlation & sensitivity: stock vs crude, rupee proxy, G-Sec, VIX) needs
  stock prices before 2024-04-01, where `nidp.prices_eod_adjusted` starts. TrueData supplies adjusted daily bars from
  2010 (fetched to disk on 2 Nov, `/home/deploy/nivesh-truedata-raw/equity/eod`), and the 24 `TD_*` macro series
  loaded into `nidp.fred_macro` on 2 Nov need a nightly refresh.

## Design (decided before the code)

- **Own table** `nidp.prices_eod_history` (migration 191), never `prices_eod_adjusted`: many readers scan that table
  without a date floor and their outputs would silently change. Plus `nidp.prices_eod_history_stitch` (one row per
  symbol per run: status, factor, overlap, seam numbers — where a flagged symbol is recorded) and a research-only view
  `nidp.v_prices_eod_long_research` (history only before the symbol's first `prices_eod_adjusted` date, then ours).
- **Stitching to our basis.** TrueData adjusts for demergers, our adjuster does not (ITC 2024-04-01: TD 402.55, ours
  426.70). factor = our `adj_close` / TD close on the symbol's first warehouse days (TD bars for those days are fetched
  per symbol, one call, or read from an overlap file). The factor must be stable across >= 3 overlap days within
  TrueData's 0.05 rounding (+2 bp); a factor indistinguishable from 1 is stored as exactly 1. The seam must be short
  (history's last bar within 7 calendar days of our first bar), and TrueData's own close on history dates in the
  overlap window must equal the raw file's (the basis did not change since the raw fetch). Anything else: the symbol is
  flagged with a status and NOT loaded.
- **Bars hygiene.** Dedupe by date; a date whose duplicate rows disagree is dropped; rows without a positive close are
  dropped; a bar for today is dropped unless its segment is final (MCX after 23:59 IST, indices after 16:00 IST);
  future-dated bars are dropped.
- **Switch.** Every path that calls TrueData asks `market_data_source.truedata_is_on()` first. A load (any write of
  TrueData data) also needs the switch on. At `current`: zero TrueData calls, zero data writes; the nightly job records
  a SKIPPED run (SWITCHED_OFF) like `truedata_crosscheck`. `--rollback RUN_ID` works at any switch position.

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-01 | bars | exact duplicate dates collapse; disagreeing duplicates drop the date (counted); null / <= 0 close dropped | unit | one bar per date, conflicting dates listed, bad rows counted |
| TC-02 | stitch | same basis with TrueData's 0.05 rounding (RELIANCE-like 1484.80 vs 1484.775) | unit | LOADED, factor exactly 1, history = TD values |
| TC-03 | stitch | demerger basis (ITC-like ours 426.70 vs TD 402.55) | unit | LOADED, factor = median ratio; stitched last close x TD's own seam move = our first close (within tolerance) |
| TC-04 | stitch | ratio moves beyond tolerance across overlap days | unit/edge | UNSTABLE, 0 rows |
| TC-05 | stitch | fewer than 3 overlap days | unit/edge | NO_OVERLAP, 0 rows |
| TC-06 | stitch | our first date is > 7 calendar days after history's last bar (renamed symbol / late adjuster coverage) | unit/edge | SEAM_GAP, 0 rows |
| TC-07 | stitch | TD close on a history date in the overlap window differs from the raw file; or no common date | unit/failure | BASIS_CHANGED / NO_BASIS_CHECK, 0 rows |
| TC-08 | stitch | factor outside [0.5, 2] (one side missed a split/bonus) | unit/edge | FACTOR_OUT_OF_RANGE, 0 rows |
| TC-09 | stitch | history rows on/after our first warehouse date | unit/edge | never emitted (the warehouse wins) |
| TC-10 | bars | today's MCX bar before 23:59 IST; today's index bar before/after 16:00 IST; a future-dated bar | unit | MCX today dropped, index today dropped before / kept after, future dropped |
| TC-11 | switch | switch at `current` (file, and forced by env) | unit | loader and macro job make 0 TrueData calls (transport fails the test if called) and write no data; macro job records SKIPPED / SWITCHED_OFF; rollback still runs |
| TC-12 | macro | refresh fetches only new days (start = last stored + 1); an up-to-date series makes no call; EMPTY_RESPONSE = no new data, not a failure; a failing series makes the run PARTIAL and exit 1; series ids / labels / caveats / -I and -II pairs identical to the 24 loaded on 2 Nov | unit | as stated |
| TC-13 | migration | 191 on a fresh PostgreSQL 16, applied twice | PG container | re-runnable; PK, checks; view = history before the symbol's first prices_eod_adjusted date, then warehouse rows |
| TC-14 | loader | batch transaction with run id; re-run without --replace writes nothing (SKIPPED_EXISTING); --replace rewrites; --rollback RUN_ID deletes exactly that run's rows + stitch rows; failure inside a batch leaves nothing of that batch | PG container | as stated |
| TC-15 | loader | --dry-run | PG container | no row written anywhere |
| TC-16 | macro | insert of new days only (ON CONFLICT DO NOTHING), rollback deletes exactly the run's rows | PG container | as stated |
| TC-17 | api | DaaS `GET /v1/prices/research-long/{symbol}`: key required, start/end filters, pagination, `basis_source` per row, 400 on a bad date; its SQL runs on the real view | unit + PG container | as stated |
| TC-18 | data | ~50 symbols from the raw files stitched against STAGING `prices_eod_adjusted` (read-only), TD overlap bars fetched for those symbols only (sequential, after the running fetch ends) | real data, read-only | status counts, factor distribution, max deviation, seam continuity (last stitched close vs first warehouse close vs TD's own move) reported; large caps LOADED with factor 1, ITC ~1.06; symbols starting Oct 2025 flagged SEAM_GAP |
| TC-19 | secrets | every command, log, file and test output | check | no credential, token or password printed |
| TC-20 | regression | existing switch, TrueData client, cross-check and DaaS prices/macro suites | unit | still pass |

## Amendment after the first real-data run (TC-18, 3 Nov 00:00 IST)

The first run of TC-18 flagged 4 of 50 symbols FACTOR_OUT_OF_RANGE: SIEMENS 2.01, ALLCARGO 3.2, DCMSRIND 3.38,
RAYMOND 4.95. Staging (read only) shows each has a demerger in `nidp.corporate_actions` AFTER its first warehouse day
(SIEMENS 2025-04-07, ALLCARGO 2025-11-12, DCMSRIND 2025-12-26, RAYMOND 2024-07-11 and 2025-05-14) and the matching
one-day drop in our adjusted series (-43 %, -62 %, -71.5 %, -35 % / -60 %): real demergers, not missed splits. Rule
refined: a factor above 2 (up to 10) is accepted only with a demerger recorded on or after the symbol's first warehouse
day; below 0.5, above 10, or without that record it stays flagged.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-08b | stitch | factor 2.01 with a demerger after our first day; factor 5 with a demerger only BEFORE it; factor 0.2 or 12 with a demerger | unit + PG container | first LOADED with the ex-date in the reason; the others FACTOR_OUT_OF_RANGE |

## Not in scope (stated now, reported as UNVERIFIED later)

Applying migration 191 on staging, running the backfill or the nightly job against staging, installing the cron line,
and hitting the DaaS route on staging: this task is read-only on staging by rule.
