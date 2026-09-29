# Functionality Verification Report — Paper trade swing chart

Date: 2026-09-30 · Branch: `feat/paper-trade-charts` · Base: `origin/dev` @ 79618650

## Ask

Put the charts already built for these trades into the paper trading UI.

## What was found first (this changed the scope)

The obvious route — reuse `/api/research/chart/{symbol}/ohlcv` — **cannot work**. The charting
snapshot holds 50 large caps; the paper engine selects for volatility (ATR ≈ 7% of price) and lands
on small/mid caps. Measured overlap against every paper symbol on record:

```
charting snapshot ...... 50 symbols
paper picks observed ... 10   (PNCINFRA DELTACORP RPEL KPEL AEROENTER
                               ALOKINDS QUADFUTURE MOTISONS CAMLINFINE RATNAVEER)
overlap ................ 0    []
```

The universes are disjoint by construction, so that API 404s `unknown_symbol` for essentially every
paper trade.

**No new data source was needed, though.** `nidp.tpd_paper_trade_daily_observations` already stores
`open_price, high_price, low_price, close_price, volume, adjustment_factor` per session;
`/trades/{trade_id}` already returns them; the frontend adapter already parses them; and
`PaperTradesScreen` already renders them — as a table of numbers. The candles were in the browser
the whole time, only unrendered. So this is a **frontend-only** change: no endpoint, no `prices_eod`
query, and no corporate-action risk, since the bars are the engine's own adjusted record.

## Changes

| file | change |
|---|---|
| `frontend-v5/src/pages/Research/PaperTradeChart.tsx` | NEW — daily candles + the three legs, reusing `BandsPrimitive`, `LevelTagsPrimitive`, `theme` |
| `frontend-v5/src/pages/Research/PaperTradesScreen.tsx` | +2 lines: import, and render above the path table |
| `frontend-v5/src/pages/Research/paperTrades.css` | swing-chart styles |
| `frontend-v5/e2e/tests/research-paper-trade-chart.spec.ts` | NEW — TC-PC1..TC-PC9 |

`ChartCanvas` itself was **not** embedded: it takes ~40 props of pane/indicator/drawing state owned
by `ChartsScreen` and would be unusable inside a trade row. The three standalone primitives it is
built from are what got reused.

## Test cases (authored before implementation)

| id | case | result |
|---|---|---|
| TC-PC1 | one candle per recorded session | PASS |
| TC-PC2 | all three legs drawn, each with its price | PASS (caught my own wrong expectation: page formats `₹2,627.25`, not `2627.25`) |
| TC-PC3 | stop below entry, targets above, in order; risk % shown | PASS |
| TC-PC4 | canvas has a text alternative naming symbol and legs | PASS |
| TC-PC5 | sessions that touched a level are marked | PASS |
| TC-PC6 | no sessions → explicit empty state, no canvas | PASS |
| TC-PC7 | existing path table untouched | PASS |
| TC-PC8 | no NaN/undefined leaks, no advice language | PASS |
| TC-PC9 | a null level is omitted, not defaulted to a wrong line | PASS |

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
(no output)

$ npx playwright test e2e/tests/research-paper-trade-chart.spec.ts \
                     e2e/tests/research-paper-trades.spec.ts --reporter=line
  19 passed (34.6s)
```

19 = 9 new chart tests + 9 pre-existing paper tests + auth setup. The pre-existing suite includes
TC-P28 (no horizontal scroll at phone width) and TC-P25 (the path table), both still green.

## Visual check

Screenshot taken and inspected (`/tmp/paper-swing-chart.png`, then `/tmp/paper-swing-2.png`). Two
defects were visible and fixed:

1. Three labels collided at the entry price (`S/R` tag + `entry` price-line label + axis price). The
   entry tag was removed; it already has a price line. **Fixed, re-screenshotted, confirmed.**
2. A bar-spacing cap I added to widen the wicks **never fired** — `timeScale().options().barSpacing`
   returns the configured option, not the value `fitContent()` computed. On re-inspection the wicks
   are in fact drawn, so the defect was overstated; the dead code was removed rather than made to
   fire.

## Scope and limits

- **UNVERIFIED on staging.** Everything above is the mocked layer against captured fixtures
  (`paper-trade-532.json`, MPSLTD). The staging contract layer was not run.
- The chart shows what the frozen rules did; it recommends nothing. The engine's own record stands:
  −0.19%/trade after costs over 402 sessions, failing its pre-registered test.
- `PaperIntradayChart` is unchanged and still shows the live session's 5-minute bars. The two charts
  answer different questions and both are kept.

## Verdict: PASS
