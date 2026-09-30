# Functionality Verification Report — Pre-entry context on the paper trade chart

Date: 2026-09-30 · Branch: `feat/paper-chart-pre-entry` · Base: `origin/dev` @ e42c6707

## Ask

"Why not show for forward trade … just T-5 snapshot. If it's a new entry today leave it, but if
trade exists in T-5 history then please show it."

## The problem, measured on staging

The paper page defaults to today's frozen portfolio, and that portfolio is always *pending* — so
the chart's empty state is the first thing anyone sees:

| prediction date | trades | entered | bars | chartable (>=2) |
|---|---|---|---|---|
| 29 Sep (today) | 5 | 0 | 0 | 0 |
| 28 Sep (T-1) | 5 | 5 | 5 | 0 |
| 25 Sep (T-2) | 5 | 5 | 10 | 5 |
| 24 Sep | 5 | 5 | 15 | 5 |
| 23 Sep | 5 | 5 | 20 | 5 |

Today is genuinely empty. Backtracking to T-2 and earlier already worked via the date selector —
the default just lands on the one date that cannot render.

## Change

A trade with no observations now plots the sessions **up to and including its prediction date**,
read from `/api/research/chart-live/{symbol}/ohlcv` (the route added in #189), with its levels
drawn over them.

Correctness points, each load-bearing:

- **The prediction date's own session is included.** That close is the last information the model
  had before freezing, and entry is the *next* session's open — so it is pre-entry, and it is the
  single most relevant bar. My first implementation used `date < prediction_date` and dropped it;
  a test caught it (4 bars where 5 were expected).
- **Context is never mixed with the record.** An entered trade plots only its own observations and
  never fetches a second price source — asserted by TC-PC14, which fails if any `chart-live` call
  is made. Mixing sources in one series would make it impossible to say which candles the engine
  is accountable for.
- **Outcome markers are suppressed** on context bars: a trade that has not started cannot have
  touched a level.
- **It is labelled, not just drawn** — an amber note, a dashed border, `data-context="1"`, and an
  aria-label saying none of these candles is part of the trade's record.
- **Degrades quietly**: the live route sits behind the `charting` flag while this page sits behind
  `move_odds`. An account with one and not the other still gets the page, minus the context.

## Test cases

| id | case | result |
|---|---|---|
| TC-PC10 | pending trade shows sessions up to and including the prediction date | PASS (caught the off-by-one above) |
| TC-PC11 | context is labelled and carries no outcome markers | PASS |
| TC-PC12 | levels still drawn over context bars | PASS |
| TC-PC13 | genuinely no prior history -> explicit empty state | PASS |
| TC-PC14 | an entered trade never requests context bars | PASS |

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
(no output)

$ npx playwright test e2e/tests/research-paper-trade-chart.spec.ts --reporter=line
  15 passed (29.9s)

$ npx playwright test research-paper-trades research-paper-trade-chart \
                      research-charts research-chart-trade-levels --reporter=line
  79 passed (2.2m)
```

## Verified against real staging data

The `chart-live` route — UNVERIFIED in #189 — was called against staging with an owner session:

```
RSYSTEMS   200  bars=20  pit=PIT_UNVERIFIED  src=live
              last  ['2026-09-29', 290.0, 305.98, 285.2, 298.69, 67292815.0]
AHCL       200  bars=20  pit=PIT_UNVERIFIED  src=live
TCS        200  bars=20  pit=PIT_UNVERIFIED  src=live
```

The shape assumed in #189 is the shape staging returns, and RSYSTEMS has a bar on its own
prediction date — so the pending trade in the owner's screenshot will render context once deployed.
Cross-check: its registered stop of 274.79 is exactly 298.69 x 0.92, the 8% cap, confirming the
entry basis from two independent directions.

Screenshot taken with those real bars and the trade's real levels; the amber note, dashed border,
`S -8.0%` and `R +5.0%` tags all render. No entry line appears, correctly — `entry_price` is null
until the open, and a missing level is omitted rather than invented.

## Limits

- The staging run exercised the **deployed** bundle, so it confirmed the current empty-state bug
  rather than this fix. This change is verified locally plus against the real API response shape;
  it is **UNVERIFIED as rendered on staging** until merged and deployed.
- T-1 trades hold a single session. They render one candle, which is thin but not wrong.

## Verdict: PASS
