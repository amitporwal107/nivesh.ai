# Functionality Verification Report — Trade levels on the Charts workspace

Date: 2026-09-30 · Branch: `feat/chart-trade-levels` · Base: `origin/dev` @ 7f9394ea

## Ask

"First we need to show charts like this and show entry/s/l/exit/target level in this chart" —
the full Charts workspace, with a paper trade's levels drawn on it.

## The blocker this had to solve

`ChartsScreen` is snapshot-bound by design; its docstring promises it reads *"no DB, no network"*.
That snapshot holds 50 large caps. The paper engine selects for volatility (ATR ≈ 7% of price), so:

```
charting snapshot ...... 50 symbols
paper picks observed ... 10
overlap ................ 0
```

Disjoint by construction — the workspace returns `404 unknown_symbol` for essentially every paper
trade. So the workspace needed a second, clearly separated data path.

## Changes

| file | change |
|---|---|
| `backend/routes/research_chart_live.py` | NEW — CA-adjusted daily bars for any symbol, proxying DaaS `/prices/adjusted/{symbol}` |
| `backend/server.py` | import + register the router |
| `charts/contract.ts` | `TradeLevel`, `tradeZones()`, and a live fallback inside `chartApi.ohlcv` |
| `charts/ChartCanvas.tsx` | optional `tradeLevels` prop: price lines, axis tags, shaded zones, autoscale |
| `charts/ChartsScreen.tsx` | reads the trade from the URL, passes it to the canvas |
| `Research/index.tsx` | `?screen=` so another page can deep-link in |
| `Research/PaperTradesScreen.tsx` | "Open … in Charts with these levels" link |
| `backend/tests/test_research_chart_live.py` | NEW — 14 cases |
| `e2e/tests/research-chart-trade-levels.spec.ts` | NEW — TC-TL1..TC-TL7 |

Two design decisions worth recording:

- **Live bars are a separate router, not an addition to `research_chart.py`.** That module's
  snapshot guarantee is what makes a research chart reproducible; adding a DB read to it would make
  its own docstring false and the `PIT_VALIDATED` badge misleading. Live bars carry
  `pit_status: PIT_UNVERIFIED` and `source_mode: live`, and never claim the frozen run.
- **`TradeLevel` is not an `SrBand`.** An `SrBand` carries `records: Pattern[]` because it is a
  *detected* feature with evidence; a trade level is a *pre-registered decision* with none. Reusing
  `SrBand` would have meant inventing `Pattern` objects, which the pattern filters and the
  nearest-level readout would then count as real detections.

## Test cases (authored before implementation)

| id | case | result |
|---|---|---|
| TC-TL1 | `?screen=charts` deep link lands on the workspace with that symbol | PASS |
| TC-TL2 | all four levels drawn | PASS |
| TC-TL3 | tag lane carries E / SL / T1 / T2 beside S/R | PASS |
| TC-TL4 | a level never set is not drawn | PASS |
| TC-TL5 | `entry=0` / `stop=abc` refused, not drawn at the axis floor | PASS |
| TC-TL6 | non-snapshot symbol falls back to the live source | PASS |
| TC-TL7 | no NaN/undefined leaks | PASS |
| backend | gate, oldest-first ordering, adjusted-not-raw, provenance, 4 impossible-bar shapes, empty page, bad shape, date range, bad symbol | 14 PASS |

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
(no output)

$ npx playwright test e2e/tests/research-chart-trade-levels.spec.ts --reporter=line
  8 passed (18.4s)

$ npx playwright test research-charts research-charts-workspace charting-workspace-logic \
                      research-paper-trades research-paper-trade-chart --reporter=line
  125 passed (2.5m)

$ PYTHONPATH=. pytest tests/test_research_chart.py tests/test_charting_feature_flag.py \
                      tests/test_paper_trades_routes.py tests/test_research_chart_live.py -q
  58 passed in 2.01s
```

`tests/test_research_chart_layouts.py` errors on a missing `MONGO_URL`. That is pre-existing and
environmental — `git diff origin/dev` shows this branch touches neither that test nor its route.

## Visual check

Screenshotted and inspected twice. The first screenshot caught a real defect: **the levels were
drawn outside the visible price range and were invisible**, with only the stop's tag clamped to the
axis edge. The price scale auto-fits to the bars and ignored the levels, so a chart with a stop on
it looked like a chart with no stop — the dangerous reading. Fixed with an `autoscaleInfoProvider`
that widens the range to span the levels; re-screenshotted and confirmed entry, stop, both targets
and both shaded zones now render on scale.

Tradeoff introduced by that fix: widening the scale compresses the candles. It looks severe in the
fixture only because the TCS fixture spans ~11 points (0.3%); real volatility will not.

## Scope and limits

- **UNVERIFIED on staging.** All of the above is the mocked layer plus unit tests. The live route
  has never been called against real staging data, so the shape of a real
  `/prices/adjusted/{symbol}` response is assumed from the DaaS source, not observed.
- The live fallback is **daily only**. 1W/1M keep the `not_found`, because serving daily bars for a
  weekly request would misdate every candle.
- Indicators and patterns remain snapshot-only, so a live symbol charts with bars and trade levels
  but no indicators and no detected patterns.

## Verdict: PASS
