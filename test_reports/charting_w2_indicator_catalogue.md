# Functionality Verification Report — Charting W2: the indicator preset catalogue (§38.5, AC 3)

- **Branch:** feat/charting-indicator-catalogue (worktree `/app/.claude/worktrees/charting`), on dev `314006bd`
- **Date:** 2026-09-23
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** local research suite + backend pytest + a real snapshot re-export from the Kite daily bars at
  `/app/research/kite_history/day_2021`. Staging verification is a separate step.
- **Changed areas:** backend routes/services: **yes** · frontend src: (a later increment)

## Summary

The last W2 item in `docs/charting.md` §38.12. §38.5 with decision D-3 says users pick from a **controlled preset
catalogue** and cannot type arbitrary parameters; the catalogue is versioned, hashed with the snapshot, and every
preset is **precomputed at export**, because the chart API only reads the snapshot and computes nothing (the Sim
Lab rule).

This increment builds the catalogue and serves it. The indicator dialog that consumes it follows.

Initial catalogue per §38.5: the 8 series already in the snapshot, plus SMA and EMA 10/20/50/100/200,
RSI 7/14/21, Bollinger 20×2, MACD 12/26/9 and ATR 14.

## Test Cases

> Authored before implementation.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-200 | catalogue | Every §38.5 preset is present: SMA/EMA 10/20/50/100/200, RSI 7/14/21, Bollinger 20×2, MACD 12/26/9, ATR 14, relative volume | unit | 17 presets across 7 indicators |
| TC-201 | catalogue | Each indicator carries id, name, category, default pane, output fields and calculation version | unit | every field non-empty; categories ⊆ {trend, momentum, volatility, volume} |
| TC-202 | catalogue | Preset ids are unique, and so are the series ids they map to | unit | no duplicates |
| TC-203 | back-compat | The 8 series ids already in the snapshot keep their exact ids and panes | unit | sma_20, sma_50, ema_20, bollinger (price); rsi_14, macd, atr_14, relative_volume (own pane) |
| TC-204 | versioning | The catalogue has a version and a stable content hash; the hash changes when a preset changes and not otherwise | unit | deterministic sha256 over the normalised catalogue |
| TC-205 | export | Every catalogue preset appears in an exported symbol's `indicators`, with the same contract shape as today | unit | 17 keys, each with contract/pane/values |
| TC-206 | export | A preset's series equals the same `series.*` helper called directly — no second calculation path | unit | element-wise equal for SMA 100 and RSI 21 on real bars |
| TC-207 | export | Weekly and monthly carry the same preset set as daily | unit | `timeframes.1W/1M` indicator keys == daily keys |
| TC-208 | frozen | Re-exporting does not change detected patterns or `config_hash` | data | patterns byte-identical to the pre-change snapshot; config_hash unchanged |
| TC-209 | API | `GET /api/research/chart/catalogue` serves the catalogue behind the charting flag | api | 200 with version, hash and indicators; 403 without the flag |
| TC-210 | API | An unknown indicator id on the indicators route is still rejected with its reason code | api | 400 `unknown_indicator: <id>` |
| TC-211 | API | The catalogue the API serves matches the one the snapshot was built with | api | served hash == manifest hash |
| TC-212 | size | The re-exported snapshot stays a sane size for the repo | data | report actual bytes before and after |
| TC-213 | dialog | The toolbar opens a dialog listing the catalogue grouped by category | e2e | 4 groups, 17 presets |
| TC-214 | dialog | Search narrows across preset name, id and category | e2e | "200" → 2, "momentum" → 4, "zzz" → empty state |
| TC-215 | dialog | Adding a preset draws it and marks it added; adding again removes it | e2e | `data-rendered-series` follows |
| TC-216 | dialog | Two presets of one indicator coexist as overlays; a preset the snapshot lacks is disabled with its reason | e2e | sma_20 + sma_50 drawn, no new pane; sma_200 disabled "NOT IN THIS SNAPSHOT" |
| TC-217 | bands | An oscillator draws the reference bands its catalogue entry defines, and one without them draws none | e2e | `data-band-levels` = [["rsi_14",[30,70]]] then [] |
| TC-218 | dialog | A catalogue that cannot be read shows the reason and the chart still works | e2e/failure | reason shown, no error state |

## Verify

**Catalogue unit tests (TC-200..207):**
```
$ python -m pytest research/charting/tests/test_indicator_catalogue.py -q
........                                                                 [100%]
8 passed in 6.17s
```

**Backend, including the catalogue endpoint (TC-209..211):**
```
$ cd backend && pytest tests/test_research_chart.py tests/test_research_chart_layouts.py \
    tests/test_research_drawings.py tests/test_charting_feature_flag.py -q
...............................................................          [100%]
63 passed in 3.07s
```

**Whole research suite — the export path and every frozen guard:**
```
$ pytest research/charting/tests -q
1042 passed, 2 warnings in 127.14s (0:02:07)
```

**Re-export against the real Kite daily bars, then diffed against the previous snapshot (TC-208, TC-212):**
```
symbol files: 50 -> 50 | same set: True
TC-208 patterns differing: 0 of 50
         bars differing: 0 of 50
indicator series total: 400 -> 850
TC-212 symbols on disk: 13.47 MB -> 20.85 MB  (1.55x)
config_hash unchanged: True
new manifest catalogue hash: 6c263d64f462362e
```

**Frontend (TC-213..218) — all three chart specs in one run:**
```
$ npx tsc -b
tsc exit 0
$ npx playwright test e2e/tests/research-charts-workspace.spec.ts e2e/tests/research-charts.spec.ts \
    e2e/tests/charting-workspace-logic.spec.ts --project=desktop-chrome --reporter=line
  97 passed (3.3m)
$ npx vite build
dist/assets/ChartsScreen-BGLmVfbq.js                 298.67 kB | gzip:  90.86 kB
build exit 0
```
97 = the 91 from the previous package + the 6 new catalogue cases. Every TC in the table above is **PASS**.

## One defect this work introduced, and the fix

The dialog offered all 17 presets regardless of what a symbol actually carries, so clicking one the snapshot
lacks would have done **nothing at all**. Those are now offered disabled with the reason — "not in this
snapshot", or "needs more history" when warmup produced no rows. It surfaced because the e2e fixture carries 5
series while the catalogue offers 17, which is exactly the mismatch an older snapshot produces in production.

## Two existing tests changed meaning, deliberately

- The toolbar's Indicators button now opens the catalogue dialog rather than switching the sidebar tab, which is
  what §38.5 specifies. The tab remains the quick on/off list for what the symbol carries.
- A test asserted the full indicator set as a hand-written list of eight. It now asserts against the catalogue
  itself, so adding a preset (a new catalogue version plus a re-export) will not fail a test that was never
  about the count.

## Deliberate choices

- **The eight pre-catalogue series ids are frozen**, with their panes, so no saved layout or cited research run
  needs migrating. New presets take the `<key>_<period>` form.
- **The whole catalogue is written into the manifest**, not just its version, so the endpoint serves the dialog
  straight off the snapshot and can never describe a preset differently from the series actually computed.
- **Reference bands come from the catalogue**, never from a level chosen in the browser.
- **The snapshot grows 13.5 MB to 20.9 MB** in the repo. That is the cost of precomputing every preset, which is
  what D-3 requires; the alternative is an on-demand compute endpoint, which §38.5 rules out.

## Inputs required from user

- A staging session token, to verify the dialog against the deployed catalogue after merge.

## Verdict: PASS
