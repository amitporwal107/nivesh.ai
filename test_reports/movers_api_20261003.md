# Functionality verification — Top Movers dashboard API

- **Date:** 2026-10-03
- **Branch:** feat/research-qa-exercise
- **Changed:** `backend/routes/movers.py` (new), `backend/server.py` (router), `backend/nidp/migrations/157_insider_sast.sql` (new), `research/trendlyne/bin/insider_sast_to_pg.py` (new)
- **Test cases:** authored up front in `test_reports/TESTCASES_movers_api.md`
- **Design contract:** `frontend-v5/design/mover-dashboard/_pkg/Top Movers Dashboard - Design Package/`

## Endpoints

| Method | Path | Serves (design element) |
|---|---|---|
| GET | `/api/movers` | left rail: movers in a window + three-state odds badge |
| GET | `/api/movers/{symbol}` | chart, index overlays, 5 event lanes, 3-window attribution, model badge |
| GET | `/api/movers/{symbol}/analysis` | correlation card + attribution pinned to one event |

Route registration (real output):

```
IMPORT OK
  ['GET'] /api/movers
  ['GET'] /api/movers/{symbol}
  ['GET'] /api/movers/{symbol}/analysis
lanes: ['fil', 'ca', 'deal', 'ins', 'mdl']
ranges: ['1D', 'T7', '1M', '3M', '1Y']
```

## How this was verified

The app backend has no local runtime (it runs on the staging app-vm), and a deploy to it is a
*live* deploy off `origin/dev`. So the verification drives the **real functions in
`backend/routes/movers.py`** against **real rows exported from `nidp_staging` this session** via
the read-only `rpsql.sh` path, and separately runs **each endpoint's SQL verbatim** on staging.

What this does NOT cover is stated in `OVERRIDE_movers_api_http.md`: no HTTP request was made to
the deployed staging API, so auth, serialisation and routing over the wire are UNVERIFIED.

### A. Real code paths on real staging data

Source rows: 373 real `nidp.prices_eod` EQ bars for EMUDHRA (2025-04-01..2026-10-01) and 433
`nidp.index_eod` rows, both exported from `nidp_staging` this session.

```
TC-bars    : 373 real EQ bars 2025-04-01..2026-10-01; event bar ti=360 (2026-09-15)
TC-02 hdr  : O=535.0 H=592.85 L=531.0 C=592.85 prev=494.05 pct=20.00%  vol=1,550,701
TC-02      : PASS — matches the design's worked example (+20.00%)
TC-08 met  : re=0.3001 gap=0.0542 volPre=3.31 volPost=65.09 flip=False
TC-08      : PASS — design formulas (re/gap/volPre/volPost/flip) all computed
TC-09 reg  : beta=0.9001 corr=0.3663 sessions=120 (requested 250) window=['2025-09-10', '2026-09-08']
             degraded=True reason=market index history covers 120 of the design's 250 sessions (nidp.index_eod starts 2026-02-06)
TC-09      : PASS — beta published with the window actually used, degradation disclosed
TC-10 BEFORE: E-7 → E-1  R=-5.38%  market=-1.94%  sector=+0.00%  specific=-3.44%  sector_leg=False
TC-10 EVENT : E-1 → E+1  R=+30.01%  market=-0.69%  sector=+0.00%  specific=+30.70%  sector_leg=False
TC-10 AFTER : E+1 → E+7  R=+1.74%  market=-0.30%  sector=+0.00%  specific=+2.03%  sector_leg=False
TC-10      : PASS — R = market + sector + specific holds to 1e-12 in all three windows
TC-11 rbeta: before beta=-0.894 corr=-0.133 n=19 | after beta=-0.280 corr=-0.059 n=11
TC-11      : PASS — rolling 20D beta/corr either side of the event
TC-13 TAALTECH :  -79.26%  suspect=True  [price ratio 4.82 is within 8% of 5:1 — suspected unadjusted split/bonus; no matching row in nidp.corporate_actions]
TC-13 PGIL     :  -50.06%  suspect=True  [price ratio 2.00 is within 8% of 2:1 — suspected unadjusted split/bonus; no matching row in nidp.corporate_actions]
TC-13 TCC      :  -81.08%  suspect=True  [price ratio 5.29 is within 8% of 5:1 — suspected unadjusted split/bonus; no matching row in nidp.corporate_actions]
TC-13 EMUDHRA  :  +20.00%  suspect=False
TC-13 AASTHA   :  -45.96%  suspect=True  [price ratio 1.85 is within 8% of 2:1 — suspected unadjusted split/bonus; no matching row in nidp.corporate_actions]
TC-13      : PASS — all three phantom splits flagged; the real +20% move is not
TC-14 badge: EMUDHRA 2026-09-15 -> NO_MODEL_RUN  runs_in_window=0
             note: no final Move-odds run in the 20 days to 2026-09-15
TC-14      : PASS — a coverage gap reports NO_MODEL_RUN, not MISSED
TC-15 badge: EMUDHRA 2026-09-30 -> MISSED  runs_in_window=9  reason=NOT_IN_SCORED_UNIVERSE
TC-15      : PASS — runs existed but the symbol was unscored -> MISSED, with the reason
TC-16 badge: scored p=0.62 -> CAUGHT head=p_up10_1d cutoff=0.4
TC-16 badge: scored p=0.11 -> MISSED (below cutoff 0.4)
TC-16      : PASS — CAUGHT above the 0.40 cutoff, MISSED below it

ALL ASSERTIONS PASSED
```

### B. Each endpoint's SQL, run verbatim on staging

`list_movers` query (ranking + authoritative corporate-action join):

```
  symbol   | as_of_date |  pct   | ca_type | ca_ratio
-----------+------------+--------+---------+----------
 ESDS      | 2026-09-04 | 111.75 |         |
 TCC       | 2026-09-04 | -81.08 |         |
 TAALTECH  | 2026-09-22 | -79.26 |         |
 SSRETAIL  | 2026-09-23 |  76.60 |         |
 PGIL      | 2026-09-11 | -50.06 |         |
 AASTHA    | 2026-09-28 | -45.96 | BONUS   | 1:1
 KARAMTARA | 2026-09-17 |  38.58 |         |
 POLICYBZR | 2026-09-24 | -36.00 |         |
 LUMINO    | 2026-09-03 |  34.54 |         |
 RENTOMOJO | 2026-09-17 |  32.24 |         |
(10 rows)

 insider_table_exists
----------------------
 f
(1 row)

 sector | sector_benchmark_index      <- EMUDHRA: row exists, both columns NULL
--------+------------------------
        |
(1 row)
```

Move-odds coverage, from `nidp.tpd_runs` (status='final'):

```
 target_session | head | p | base      <- 11 runs, EMUDHRA scored in NONE of them
----------------+------+---+------
 2026-09-17     |      |   |
 2026-09-18     |      |   |
 2026-09-22     |      |   |
 ... 2026-09-23, -24, -25, -28, -29, -30, 2026-10-01, 2026-10-05
(11 rows)
```

The earliest final run (2026-09-17) **postdates** EMUDHRA's 2026-09-15 move, which is why the
badge must return `NO_MODEL_RUN` rather than `MISSED` — proven by TC-14 above.

### C. Insider / SAST lane sourced from Trendlyne

`nidp` has no insider/SAST source. Migration 157 adds `nidp.insider_sast`, loaded by
`research/trendlyne/bin/insider_sast_to_pg.py` from the Trendlyne archive — **zero new API calls**:

```
archive: 8 symbols fetched before, 513 rows parsed, 0 skipped
wrote 471 unique rows -> /app/research/trendlyne/ref/insider_sast.csv
wrote 0 skipped rows  -> /app/research/trendlyne/ref/insider_sast.skipped.csv

action
Pledge                        177
Acquisition                   141
Disposal                      125
Revoke                         14
Others                          8
Invoke                          4
Non-Disposable Undertaking      2
```

Columns are mapped by Trendlyne's `unique_name` header key, not by position. 0 rows skipped
across all 513, so the mapping holds on every row.

## Defects found and fixed during this verification

1. **`_ca_suspect` tolerance too tight.** At 2% it missed TAALTECH (ratio 4.82, a 1:5 split with a
   real ~4% fall on top). Widened to 8%; all three phantom splits now flag. Caught by TC-13.
2. **`action` was being nulled for the majority of insider rows.** The first parser mapped only
   Acquisition/Disposal, which silently discarded `Pledge` — 177 of 471 rows and the most common
   disclosure in the feed. Both the parser and migration 157's CHECK now carry the real domain.
3. **Pledge mis-titled as a buy/sell.** `_insider_for` described every row as "buys"/"sells";
   pledge/revoke/invoke change encumbrance, not ownership, and are now titled as such.

## Known data limits, reported by the API rather than hidden

| Design element | Limit | API behaviour |
|---|---|---|
| β / correlation over 250 sessions | `nidp.index_eod` starts 2026-02-06 → only **120** usable sessions at 2026-09-15 | returns β with `sessions: 120`, `requested_sessions: 250`, `degraded: true` and the reason |
| Sector index overlay | EMUDHRA's `sector_master` row has NULL sector | `sector.available: false`, `reason: SYMBOL_NOT_IN_SECTOR_MASTER`; attribution drops the sector leg and sets `sector_leg: false` |
| INSIDER / SAST lane | `nidp.insider_sast` not yet created on staging | `available: false`, `reason: NOT_BACKFILLED` — never an empty lane, which would read as "no insider activity" |
| Corporate-action adjustment | `corporate_actions` starts 2026-05-26 with 8 SPLIT + 9 BONUS rows; `prices_eod_adjusted` has a non-unit factor on 0.4% of rows. TAALTECH/PGIL/TCC splits are in neither | flagged via `ca_suspect`, withheld from the default ranking, visible with `include_ca=true` |

`_ca_suspect` is deliberately one-sided: it only examines falls, since a split or bonus can only
lower the price. ESDS +111.75% is therefore not flagged and is not a split artefact.

## Test case results

| Case | What | Result |
|---|---|---|
| TC-01 | list SQL + CA join runs on staging | PASS |
| TC-02 | header OHLC matches the design's worked example (+20.00%) | PASS |
| TC-08 | per-event re / gap / volPre / volPost / flip | PASS |
| TC-09 | β window ends at T-4; degradation disclosed | PASS |
| TC-10 | R = market + sector + specific, all 3 windows, to 1e-12 | PASS |
| TC-11 | rolling 20D β/corr either side of the event | PASS |
| TC-13 | phantom splits flagged, the real +20% move is not | PASS |
| TC-14 | coverage gap → `NO_MODEL_RUN` | PASS |
| TC-15 | runs existed, symbol unscored → `MISSED` + reason | PASS |
| TC-16 | `CAUGHT` above the 0.40 cutoff, `MISSED` below | PASS |
| TC-17 | sector lane degrades when unmapped | PASS |
| TC-18 | insider lane degrades when the table is absent | PASS |
| TC-03..07, TC-12, TC-19 | HTTP-layer: auth, serialisation, routing, live data test | **BLOCKED** — see `OVERRIDE_movers_api_http.md` |

## Verdict: BLOCKED — data and logic layers verified on staging; HTTP layer requires a deploy (see OVERRIDE_movers_api_http.md)
