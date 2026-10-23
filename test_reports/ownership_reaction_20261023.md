# Functionality Verification Report — Historical Smart Money Movement (ownership change vs quarter price/volume action)

- **Branch:** feat/historical-ownership-reaction (from feat/provider-foundations @ 8dc09801)
- **Date:** 2026-10-23
- **Author:** Claude (full-stack developer + QA engineer, with domain-expert review of the data legs)
- **Environment:** staging warehouse `nidp_staging` (READ-ONLY) for the data leg; pytest and Playwright in containers
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary

A DESCRIPTIVE, retrospective screen: for the latest disclosed quarter (`period_end` 2026-09-30, i.e.
Jul–Sep 2026), each Nifty-500 name's FII/DII percentage-point ownership change set beside that same
quarter's price return, volume ratio, delivery-percentage shift and 52-week position, plus the desk
status taxonomy. It is never worded as a signal: the Jul–Sep shareholding pattern was filed with NSE
between 2026-10-01 and 2026-10-22 (real `broadcast_at` timestamps), so the price move it sits beside
was over before the ownership figure existed.

New files only, except a 6-line mount in `SmartMoneyTab.tsx`:

- `backend/nidp/services/daas_api/routers/ownership.py` — `GET /v1/desk/ownership/reaction`
- `backend/routes/markets_ownership.py` — `GET /api/markets/ownership/reaction` (thin proxy)
- `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/ownership-reaction-data.ts`
- `frontend-v5/src/pages/CopilotApp/screens/tradingdesk/OwnershipReactionPanel.tsx`
- `backend/tests/test_ownership_reaction.py`, `frontend-v5/e2e/tests/copilot-app-desk-ownership-reaction.spec.ts`
- registered in `daas_api/app.py`, `daas_api/routers/catalog.py`, `backend/server.py`

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. TC-23..TC-42 were added when the
> coordinator extended scope mid-task (status taxonomy, provenance, reconciliation); they too were
> written before the code they cover.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | reaction | `ret >= p80` and `vol >= p50` | unit | `strong_positive`, corroborated | PASS |
| TC-2 | reaction | CROMPTON −24.05% @ 0.771 | unit | `negative`, corroborated | PASS |
| TC-3 | reaction | ANGELONE −17.13% @ 0.606 / TARIL −23.13% @ 0.381 | unit | `neutral` + note naming the unconfirmed leg | PASS |
| TC-4 | reaction | ICICIPRULI −9.05% mid-band | unit | `neutral`, no note | PASS |
| TC-5 | reaction | below the session floor | edge | reaction/bands `null`, never `neutral`, never 0 | PASS |
| TC-6 | trust | ICICIBANK end to end | unit | same-source +0.89pp served, +16.65pp artifact exposed, trust `unusable` | PASS |
| TC-7 | trust | spread material but smaller than the change | unit | `contested` | PASS |
| TC-8 | trust | spread null/<0.5 → `ok`; no delta → `none` | unit | as stated | PASS |
| TC-9 | divergence | exactly ONE definition of divergence | unit | `view=divergence` delegates to the status | PASS |
| TC-10 | trust | cross-source basis | unit | never better than `contested` | PASS |
| TC-11 | absent≠0 | ANGELONE has no MF/Banks-FI split | edge | `null`, `split_is_level` true, DII not decomposed | PASS |
| TC-12 | api | proxy forwards view/reaction/status/basis/sort/limit, passes body through | api | identical JSON, params forwarded | PASS |
| TC-13 | api | upstream unreachable / unconfigured | failure | 502 `upstream_unavailable`, never an empty list | PASS |
| TC-14 | api | 200 without a `rows` list | failure | 502 contract guard | PASS |
| TC-15 | api | `sort=score`, `status=strong_buy`, `view=momentum`, `limit=501` | failure | HTTP 422 over real requests | PASS |
| TC-16 | e2e | reduced view renders real rows and PRINTS its cut-points | e2e | rows + p20/p80/vol-median/488 + cohort p75 visible | PASS |
| TC-17 | e2e | states co-occurrence and non-prediction; no signal wording | e2e | note present; no banned phrase in the panel | PASS |
| TC-18 | e2e | undisclosed vs genuine zero | e2e | "not disclosed"/"not recorded"; a real 0.00% still shows | PASS |
| TC-19 | e2e | every denominator is the eligible cohort | e2e | "89 of 500", 65/24 split, 429 never a delta denominator | PASS |
| TC-20 | e2e | divergence view; contested figure | e2e | NUVOCO renders; ICICIBANK reads "sources differ", no number | PASS |
| TC-21 | e2e | no score column; sorting by measured columns | e2e | no Score/Rank/Conviction header; no `sort=score` chip | PASS |
| TC-22 | data | staging SQL reproduces every served figure | data | shipped SQL + shipped derivation, output below | PASS |
| TC-23 | unit | Python percentile == Postgres `percentile_cont` | unit | identical interpolation | PASS |
| TC-24 | status | CANFINHOME | unit | `distribution_risk`, reason names legs AND cut-points | PASS |
| TC-25 | status | adding into weakness | unit | `reversal_watch`, never `distribution_risk` | PASS |
| TC-26 | status | KARURVYSYA | unit | `breakout_watch` | PASS |
| TC-27 | status | accumulation needs all four legs | unit | KARURVYSYA fails on delivery only; 0 of 89 pass | PASS |
| TC-28 | status | NUVOCO ownership down / price up | unit | `divergence`; sub-median legs excluded | PASS |
| TC-29 | status | the 3 contested names | unit | `insufficient_data`, not a neutral status | PASS |
| TC-30 | status | unmeasurable tape | unit | `insufficient_data`, distinct from `none` | PASS |
| TC-31 | e2e | status chips carry REAL counts including zero | e2e | Accumulation 0 … Insufficient data 3 | PASS |
| TC-32 | e2e | empty classification is a first-class result | e2e | names real siblings; "not relaxed to fill a tab" | PASS |
| TC-33 | e2e | Distribution Risk is the only red one | e2e | risk and watch chips differ in border colour | PASS |
| TC-34 | e2e | real filing timestamp, after-close flagged | e2e | 2026-10-22 "after close — next session" | PASS |
| TC-35 | e2e | cohort percentile is not a benchmark | e2e | "10th in cohort"; no "vs Nifty 500", no "TRI" | PASS |
| TC-36 | e2e | panel failure is its own | failure | host tab still renders; panel shows an error, not an empty table | PASS |
| TC-37 | e2e | trend gating | e2e | trend note states 340 single-quarter / 91 with ≥4 | PASS |
| TC-38 | e2e | uncorroborated sharp move | e2e | ANGELONE "Neutral" + "volume did not confirm" | PASS |
| TC-39 | unit | status buckets reconcile to the eligible cohort | unit | 0+1+0+4+7+3+74 = 89; exactly one status per row | PASS |
| TC-40 | unit | `insufficient_data` is not folded into `none` | unit | distinct buckets | PASS |
| TC-41 | e2e | DISPLAYED counts reconcile | e2e | "= 89 of 89 eligible", no MISMATCH, chips sum to 89 | PASS |
| TC-42 | e2e | missing ownership history is visible | e2e | "411 names have no second comparable quarter" | PASS |
| TC-43 | isolation | the `deps` stub does not leak into other test modules | unit | stub present inside the fixture, gone outside it | PASS |

## API / Endpoint Tests

### pytest — the derivation and the proxy (32 cases)

Command:

```
sudo docker run --rm -v <worktree>:/repo -w /repo/backend python:3.11-slim bash -lc \
  'pip install -q fastapi "pydantic>=2" httpx "pytest==8.3.3" asyncpg motor; \
   python -m pytest tests/test_ownership_reaction.py -q'
```

Real output:

```
................................                                         [100%]
=============================== warnings summary ===============================
tests/test_ownership_reaction.py::test_tc15_unknown_filter_values_are_rejected_over_http
  /usr/local/lib/python3.11/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
32 passed, 1 warning in 0.72s
```

Result: **PASS**

### A bug this verification caught in its own test suite

The first draft stubbed `deps` in `sys.modules` at MODULE scope (copying the pattern in
`tests/test_alternative_finder.py`). Running the new file together with its neighbours exposed the
consequence:

```
FAILED tests/test_desk_market_routes.py::test_desk_market_routes_need_a_signed_in_user[/api/markets/sector-returns]
FAILED tests/test_desk_market_routes.py::test_desk_market_routes_need_a_signed_in_user[/api/markets/deals]
FAILED tests/test_desk_market_routes.py::test_buildup_scan_needs_a_signed_in_user
FAILED tests/test_desk_market_routes.py::test_sector_heatmap_needs_a_signed_in_user
4 failed, 101 passed, 1 warning in 1.40s
```

A module-scope stub leaks for the whole session, so those modules imported a permissive
`get_current_user` and their auth assertions changed meaning. Fixed by moving the stub into a
per-test `route_mod` fixture (`monkeypatch.setitem`, plus dropping the route module from the import
cache on teardown) and guarded by TC-43. After the fix the two neighbouring modules fail at their
own genuine collection barrier instead — see the note below — which is the correct behaviour.

> UNVERIFIED (pre-existing, not caused by this change): `tests/test_markets_home_daas.py` and
> `tests/test_desk_market_routes.py` cannot be COLLECTED in a credential-free container at all.
> `deps.py` constructs an `AIEngine` at import time, so importing them requires `MONGO_URL` and a
> real `OPENAI_API_KEY`:
> `openai.OpenAIError: Missing credentials. Please pass an api_key ... or set the OPENAI_API_KEY environment variable.`
> No credentials were supplied, so those two modules were not run. The new suite is independent of
> them: it never imports the real `deps`.

### Wiring — the router and both registrations

```
=== the ownership router itself ===
routes: [('/desk/ownership/reaction', ['GET'])]
statuses: ('accumulation', 'breakout_watch', 'reversal_watch', 'distribution_risk', 'divergence', 'insufficient_data', 'none')
views: ('all', 'reduced', 'raised', 'divergence')
=== app.py references it (parsed, not executed) ===
ownership imported in app.py : True
ownership router included   : True
=== server.py registers the proxy (parsed) ===
proxy imported : True
proxy included : True
=== import the proxy router ===
proxy routes: ['/api/markets/ownership/reaction']
```

Result: **PASS**

> UNVERIFIED: the full `nidp.services.daas_api.app` module could not be imported in the container —
> it fails on a PRE-EXISTING unrelated dependency, `nidp/services/dq_ai/llm.py` importing `openai`,
> which is not installed in the test image and which this change does not touch. The router, both
> registrations and the proxy were each verified directly instead (above). The endpoint has NOT been
> exercised against a running DaaS service, because the DaaS API runs on the NIDP VM where the
> service restart is classifier-denied for this session. The SQL and the derivation were instead run
> against the real warehouse end to end — see **Data Correctness**.

## UI / Playwright Tests

Command (build, serve, run):

```
VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build
VITE_BASE=/v5/ npx vite preview --port 5174 --strictPort &
npx playwright test --config pw.copilot-app.config.ts copilot-app-desk-ownership-reaction
```

Real output:

```
Running 16 tests using 3 workers

  ✓   3 … TC-17: it says it explains the past, and never reads as a buy/sell signal (1.7s)
  ✓   2 … TC-18: an undisclosed figure reads 'not disclosed'/'not recorded', never 0 (1.9s)
  ✓   1 … TC-16: the reduced view renders real rows and PRINTS its measured cut-points (2.0s)
  ✓   4 … TC-19: every denominator is the ELIGIBLE cohort, never 429 and never the index (1.7s)
  ✓   6 … TC-21: no score column anywhere, and sorting is by a measured column (1.6s)
  ✓   5 … TC-20: divergence renders, and a contested figure reads 'sources differ' with no number (1.8s)
  ✓   7 … TC-31: status chips carry their REAL counts, including a zero (1.4s)
  ✓   8 … TC-32: an empty classification is a first-class RESULT naming its real siblings (1.5s)
  ✓   9 … TC-41: the DISPLAYED classification counts reconcile to the eligible cohort (1.5s)
  ✓  12 … TC-34: the filing timestamp is shown as the real publication date, after-close flagged (1.3s)
  ✓  11 … TC-33: Distribution Risk is the only red status; Reversal Watch is not red (1.4s)
  ✓  10 … TC-42: the count of names with no ownership history is VISIBLE, not implied (1.8s)
  ✓  15 … TC-37: a row without enough quarters says so instead of implying a trend (1.3s)
  ✓  13 … TC-35: the cohort percentile is never labelled as a benchmark comparison (1.8s)
  ✓  16 … TC-38: an uncorroborated sharp move is not called Negative (781ms)
  ✓  14 … TC-36: this panel's failure is its own, and never blanks the tab (3.3s)

  16 passed (11.2s)
```

Result: **PASS**

### TypeScript

`npx tsc --noEmit -p tsconfig.json` — clean, no output.  Result: **PASS**

### Pre-existing failure in the neighbouring spec (NOT caused by this change)

`copilot-app-desk-smart-money` runs **28 passed, 1 failed**. The failure is `TC-F3: the disclosure
date is shown, not the compute date`, which asserts the literal string `51d ago` against
`breadth.disclosureAsOf = 2026-09-01`. 2026-09-01 → 2026-10-23 is **52** days; the assertion was
correct on 2026-10-22, the date that spec's header records its figures from. It is a stale
time-dependent assertion.

Evidence it is not mine: this change's entire diff to `SmartMoneyTab.tsx` is six added lines —

```
+import OwnershipReactionPanel from "./OwnershipReactionPanel";
+
+      {/* Retrospective companion to the scanner above: … */}
+      <OwnershipReactionPanel />
```

— none of which touch the `ScreenHeader` pill that renders the disclosure age, and the new panel
emits no "Disclosed … d ago" text. Not fixed here: that spec belongs to another session's work and
changing it is outside this task's scope.

## Data Correctness (staging)

The app test and the data test are the same run here: the SQL constants were extracted from the
SHIPPED router by AST (so what ran is byte-for-byte the endpoint's SQL, not a retyped copy), executed
against `nidp_staging`, and the output piped through the SHIPPED Python derivation
(`classify_row` → `cohort_cuts` → `classify_status`).

### Dataset facts established by query (each one re-measured, none assumed)

```
 period_end | rows | fii  | dii  |  mf  | bankfi | ins | govt
------------+------+------+------+------+--------+-----+------
 2026-09-30 | 2156 | 1895 | 1877 | 1321 |   1094 |   0 |    0
 2026-06-30 | 1325 |  202 |  191 |    0 |      0 |   0 |    0
 2026-03-31 |  229 |  202 |  190 |    0 |      0 |   0 |    0
```

`mf_pct` / `bank_fi_pct` exist for ONE quarter → a LEVEL, never a change. `insurance_pct` and
`govt_holding_pct` are 0 everywhere → LIC invisible, DII not decomposed.

Sources per quarter — **NSE_SHP carries ZERO FII rows at the prior quarter**:

```
 period_end |   source    | fii_rows | rows
------------+-------------+----------+------
 2026-09-30 | NSE_SHP     |     1740 | 1996
 2026-09-30 | screener_in |      155 |  160
 2026-06-30 | NSE_SHP     |        0 | 1117
 2026-06-30 | screener_in |      202 |  208
```

ICICIBANK, the whole trap in four rows:

```
  symbol   | period_end |   source    | fii_pct | dii_pct | mf_pct
-----------+------------+-------------+---------+---------+---------
 ICICIBANK | 2026-09-30 | NSE_SHP     | 50.4400 | 41.7800 | 29.3900
 ICICIBANK | 2026-09-30 | screener_in | 34.6800 | 41.7700 |
 ICICIBANK | 2026-06-30 | NSE_SHP     |         |         |
 ICICIBANK | 2026-06-30 | screener_in | 33.7900 | 42.3200 |
```

Cross-source reads +16.65pp; same-source (screener_in) reads +0.89pp. Of the 65 names where both
bases exist: 33 agree to 0.01pp, 3 differ by ≥0.5pp, **2 flip sign**, worst gap 15.77pp.

HAL — the externally validated level comes from NSE_SHP (FII 9.42 / MF 6.72, matching Trendlyne
exactly) and it has **no prior quarter at all**, which is why the validated source cannot produce a
change:

```
 symbol | period_end | source  | fii_pct | dii_pct | mf_pct | bank_fi_pct
--------+------------+---------+---------+---------+--------+-------------
 HAL    | 2026-09-30 | NSE_SHP |  9.4200 | 12.5600 | 6.7200 |      0.0200
```

Split adjustment is not optional — measured on the raw bhavcopy over this exact window:

```
   symbol   | ret_unadj | ret_adj | last_event_cur | in_89_cohort
------------+-----------+---------+----------------+--------------
 TDPOWERSYS |    -36.52 |   26.96 | SPLIT          | f
 PFOCUS     |     42.98 |    9.42 |                | f
```

TDPOWERSYS's raw quarter return is **63.48pp wrong and the sign flips**. Neither name is in today's
cohort, but both sit in the tails the percentile cut-points are derived from, so the price leg was
moved to `nidp.prices_eod_adjusted` (`adj_close` / `adj_volume`). Delivery stays on `prices_eod`
because it is a same-day ratio no split can distort.

Coverage (`_COVERAGE_SQL`, shipped):

```
 universe_total | with_current_quarter | trend_renderable | single_quarter_only
----------------+----------------------+------------------+---------------------
            500 |                  429 |               91 |                 340
```

`index_constituents` holds 501 rows at its newest snapshot; one is the `DUMMYHEG` placeholder, so
the tradable universe is **500**. Reported as 500, with the exclusion named.

`broadcast_at`, the real NSE publication timestamp:

```
 period_end | rows | have_bcast | first_bcast | last_bcast | pct_after_close
------------+------+------------+-------------+------------+-----------------
 2026-09-30 | 2156 |       1996 | 2026-10-01  | 2026-10-22 |            48.5
 2026-06-30 | 1325 |          0 |             |            |
```

52-week position at the quarter end: 493 of 500 Nifty-500 names carry `dist_52w_high_pct` /
`dist_52w_low_pct` in `nidp.stock_features_daily` at `as_of_date = 2026-09-30`.

### Reaction bands — `_CUTS_SQL` (shipped) against staging

```
 ref_n | ret_p20 | ret_p80 | ret_p50 | vol_p50 | deliv_p50
-------+---------+---------+---------+---------+-----------
   488 |  -13.54 |    7.66 |   -5.53 |   0.757 |      3.34
```

The median Nifty-500 name's volume FELL (ratio 0.757) and its delivery share ROSE (+3.34pp), so a
fixed "1.0× = expansion" rule would fire on ~22% of names and "delivery up = accumulation" on
nearly all of them. Both legs are judged against the market, and the cut-points are printed on screen.

### Cohort percentiles — shipped `cohort_cuts()` over the 89

```
  n             89.0
  inst_p25      -0.05      ret_p25       -13.75     vol_p25     0.59      deliv_p25   1.32
  inst_p50      0.15       ret_p50       -6.77      vol_p50     0.761     deliv_p50   3.66
  inst_p75      0.77       ret_p75       3.42       vol_p75     0.972     deliv_p75   5.94
  high_p50      -22.17     low_p25       6.508      abs_inst_p50 0.42     abs_ret_p50 11.05
```

These independently reproduce the coordinator's measured distribution on every tape leg
(return −13.7/−6.8/+3.4, volume 0.60/0.76/0.97, delivery +1.3/+3.7/+5.9). The ownership leg differs
by design: `inst_p75` is **+0.77pp** here against the coordinator's +0.87pp, because that figure was
measured on the cross-source dedupe basis while this endpoint prefers the same-source delta. The
deltas and the percentile come from the same basis, so the rule is internally consistent.

### Status counts over the eligible 89 — shipped `classify_status()`

```
  accumulation        0
  breakout_watch      1
  reversal_watch      0
  distribution_risk   4
  divergence          7
  insufficient_data   3
  none                74
                     ---
                      89   (reconciles exactly)
```

```
  KARURVYSYA breakout_watch     inst  +1.06pp ret  +9.69% vol  1.063 dlv +1.57pp 52wH  -9.44%
  IGIL       distribution_risk  inst  -0.74pp ret -11.05% vol  1.035 dlv +8.08pp 52wH -18.65%
  KEI        distribution_risk  inst  -0.82pp ret -17.92% vol  1.141 dlv +4.91pp 52wH -24.48%
  CANFINHOME distribution_risk  inst  -1.79pp ret -17.14% vol  1.137 dlv +6.60pp 52wH -25.97%
  TATAELXSI  distribution_risk  inst  -2.90pp ret -19.34% vol  1.126 dlv +3.73pp 52wH -48.09%
  CREDITACC  divergence         inst  +2.35pp ret -14.60% vol  0.528 dlv +4.70pp 52wH -22.15%
  ADANIENSOL divergence         inst  +1.27pp ret -11.85% vol  0.795 dlv +8.28pp 52wH -26.52%
  TEJASNET   divergence         inst  +0.77pp ret -20.62% vol  0.358 dlv +7.66pp 52wH -24.59%
  ABSLAMC    divergence         inst  +0.73pp ret -13.80% vol  0.519 dlv +0.53pp 52wH -18.74%
  YESBANK    divergence         inst  +0.73pp ret -13.36% vol  0.495 dlv +8.06pp 52wH -18.74%
  LTF        divergence         inst  +0.57pp ret -14.72% vol  1.021 dlv +2.60pp 52wH -21.74%
  NUVOCO     divergence         inst  -0.43pp ret +11.47% vol  2.907 dlv -2.37pp 52wH -23.20%
```

```
=== insufficient_data rows, with the reason ===
  AXISBANK   The two sources disagree about this quarter's FII holding by as much as the change itself…
  ICICIBANK  The two sources disagree about this quarter's FII holding by as much as the change itself…
  WIPRO      The two sources disagree about this quarter's FII holding by as much as the change itself…
```

**Accumulation is a measured 0.** KARURVYSYA is the only near-miss and it fails on one leg only:
delivery +1.57pp against the cohort median +3.66pp. The thresholds were not relaxed to populate the
tab; the empty state names its real siblings instead.

### The user's headline view — institutions reduced, price/volume reacted

```
symbol     basis            fii    dii   inst    ret%   volr    dlv  reaction        trust         mf%
TATAELXSI  cross_source   -1.85  -1.05  -2.90  -19.34  1.126   3.73  negative        contested    1.15
ICICIPRULI cross_source   -0.96  -1.05  -2.01   -9.05  0.942   1.32  neutral         contested    9.30
ANGELONE   same_source    -1.25  -0.75  -2.00  -17.13  0.606   5.61  neutral         ok            n/d
CANFINHOME cross_source   -0.72  -1.07  -1.79  -17.14  1.137   6.60  negative        contested   14.99
CROMPTON   cross_source   -0.69  -0.66  -1.35  -24.05  0.771   3.66  negative        contested   54.15
HINDPETRO  same_source    -0.51  -0.74  -1.25  -11.18  0.693   5.56  neutral         ok          17.48
TARIL      same_source    -0.82  -0.35  -1.17  -23.13  0.381   7.08  neutral         ok           1.12
KEI        same_source    -1.18   0.36  -0.82  -17.92  1.141   4.91  negative        ok          23.00
IGIL       same_source    -0.70  -0.04  -0.74  -11.05  1.035   8.08  neutral         ok           3.86
POLYCAB    cross_source   -0.94   0.28  -0.66  -19.43  0.875   4.67  negative        contested    5.21
```

10 names reduced by >0.5pp; **5** are price-and-volume corroborated `negative`; 2 (ANGELONE, TARIL)
fell hard on CONTRACTING volume and are therefore `neutral` with the unconfirmed leg named rather
than being called negative on one leg. ANGELONE's MF/Banks-FI split is `n/d` — not disclosed, not 0.

Result: **PASS**

## Inputs required from user

- none

## Verdict: PASS
