# Functionality verification — 1A changes 05–09 from the design artifact

Date: 2026-09-23
Branch: feat/charting-indicator-catalogue
Artifact: `frontend-v5/design/Nivesh charting · offline.html` (1A `callouts`)

## Finding first: three of the five were already built

Checked against the code, not against the static screenshot I had been reading. The screenshot was
taken with no pointer over the chart, which is why two built features looked missing.

| # | Change | Verdict after checking the code |
|---|---|---|
| 05 | Crosshair with an OHLC readout | **already built** — `ChartCanvas.tsx` renders `chart-crosshair-tooltip` pinned at `crosshair.x + 14, crosshair.y - 8` with O/H/L/C, VOL and RSI, and mirrors into the legend. My screenshot had no hover, so nothing was pinned and I misread the legend as a missing tooltip. |
| 06 | Indicators live on the chart | **already built** — `Legend.tsx` renders one row per indicator with its value at the crosshair and inline hide / settings / provenance / remove. |
| 07 | S&R gets a real panel | **partly** — price, type, touches, distance in ₹ and %, HOLDING/BROKEN all present. **Strength was missing.** |
| 08 | On-chart level tags stop colliding | **gap** — levels are native `createPriceLine` with BOTH a `title` ("R 2940.00") and `axisLabelVisible: true` (axis "2940.00"), which is the doubling. No distance in the tag; broken levels drawn identically to live ones. |
| 09 | Stacked panes, collapsed strips | **partly** — 26px strips and sparklines present. **Current value was missing.** |

## 07: reversing a prior decision, deliberately and loudly

`contract.ts` carried:

> There is deliberately **no 1–5 strength score**: the S/R record carries `scores: null`, so a score
> would be an invention (§11/§16, decisions-log #114, design-1a-reference.md "Strength 1–5 is not in
> the data").

That reasoning looked at `scores` (the *pattern* score, genuinely null) and missed `rules`. Evidence
for reversing it, all in-repo:

- `SR_LEVEL_STRENGTH` is present in **154/154** S/R records across the snapshot, observed range
  0.3395–0.7598, median 0.5257.
- `research/charting/geometry.py: level_strength()` computes it from touches, recency, rejection,
  relative volume and time, each component in [0,1], combined by frozen weights.
- `docs/charting.md` line 1622 (§13.2) defines it: "each component in [0,1] and stored separately;
  descriptive, not a probability".
- `docs/charting.md` §38.19.2 line 3244 adopts, verbatim, "the S/R panel with price, type,
  **strength**, distance in ₹ and %, and HOLDING/BROKEN".
- Both cited contrary sources **do not exist in this repo**: there is no `design-1a-reference.md` and
  no decisions log containing #114 (`find` + `grep` returned nothing).

The one thing genuinely not in the data is the **1–5 bucketing**. That is mine, stated rather than
buried: `bucket = clamp(ceil(score * 5), 1, 5)` over the score's own [0,1] domain, and the raw score
is shown in the row's tooltip so the derived number is always inspectable. A band takes the **max**
strength of its records — "how strong is this band" is the strongest level in it.

OWNER: this reverses a previous deliberate decision. If you want it back out, it is one commit.

## Test cases (authored before implementation)

| # | Case | Expectation |
|---|---|---|
| TC-230 | Level card shows strength | `chart-sr-band-strength-<id>` reads `STRENGTH n/5` with n in 1..5 |
| TC-231 | Strength is derived from the engine, not invented | the row's `title` carries the raw `SR_LEVEL_STRENGTH` value |
| TC-232 | Strength bucketing is monotone | a record with a higher raw score never buckets lower |
| TC-233 | A band with no strength rule degrades | renders no strength chip, no crash, other fields intact |
| TC-234 | Level tag is not doubled | S/R price lines have `axisLabelVisible: false`; the axis shows no duplicate |
| TC-235 | Level tag carries label + distance | tag text matches `^(S\|R\|S/R) · [+-]\d+\.\d%$` |
| TC-236 | Broken levels are dashed and dimmed | broken band draws `LineStyle.Dashed` at 0.35 alpha; holding stays solid |
| TC-237 | Collapsed pane strip shows a current value | `chart-pane-value-<id>` present and non-empty when collapsed |
| TC-238 | Existing S/R behaviour unchanged | TC-27/TC-80/TC-81/TC-81b/TC-82 still pass (band counts, grouping, nearest readout) |
| TC-239 | Whole chart suite | `research-charts.spec.ts` + `research-charts-workspace.spec.ts` green |

## What was implemented

- **07** `contract.ts` gains `levelStrengthScore()` (reads the record's own `SR_LEVEL_STRENGTH` rule) and
  `levelStrengthBucket()` (the 1–5 presentation bucket). `SrBand` now carries `broken` and
  `strengthScore`; `LevelCard` carries `strength` and `strengthScore`. The panel renders the design's
  5-bar meter plus `STRENGTH n/5`, with the raw score in the row's `title`.
- **08** New `levelTagLayer.ts` (`LevelTagsPrimitive`, 137 lines) draws the tags itself in a right-hand
  lane, sorted by y and pushed apart when they would overlap, then walked back up if the run overflows
  the pane. The native price lines keep `axisLabelVisible: false` and `title: ""` — that pair is what
  produced "R 2940.00" on the line beside "2940.00" on the axis. Broken bands draw dashed at 0.35 alpha.
- **09** The collapsed pane strip renders the latest value next to its sparkline
  (`chart-pane-value-<id>`), volume through `fmtVol` and indicators through `fmtNum`.
- Fixture: the two RELIANCE S/R records were given `SR_LEVEL_STRENGTH` 0.62 and 0.41 — inside the real
  snapshot's observed range — so both buckets are exercised. Labelled MOCK in the spec header. The TCS
  fixture keeps `rules: []`, which is what TC-233 leans on.

## TC-177 was updated, not worked around

`research-charts-workspace.spec.ts` TC-177 asserted the sidebar never says "strength" — the test that
encoded the decision reversed above. It now asserts `STRENGTH n/5` is present. The change and its
reason are recorded in a comment above the test.

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
tsc exit: 0
```

New tests, first run — 2 failed:
```
  1) TC-230 change 07: each level band shows the engine's strength as 1–5
     Expected: 2   Received: 0
  2) TC-231 ... Error: element(s) not found
  2 failed
  5 passed (25.8s)
```
Cause found rather than retried: the sidebar's default tab is `patterns`, so the LEVELS panel was not
open. This also meant **TC-233 was passing trivially** (0 chips because no panel), so it was tightened
to assert RELIANCE's chips are visible first, then gone after switching to TCS.

```
$ npx playwright test research-charts.spec.ts -g "TC-230|TC-231|TC-233|TC-234|TC-236|TC-237" --workers=1
  7 passed (14.7s)
```

Full regression, all three chart suites:
```
$ npx playwright test research-charts.spec.ts research-charts-workspace.spec.ts \
    charting-workspace-logic.spec.ts --project=desktop-chrome --workers=1
  103 passed (2.1m)
```
(One intermediate run showed `1 failed` — TC-177, the assertion this change deliberately reverses.
It was updated, not deleted, and the final run above is clean.)

`--workers=1` is deliberate: a 2-worker run on this host kills the Vite dev server with
`net::ERR_CONNECTION_REFUSED`, which is a harness limit, not a product failure.

### Visual evidence

Screenshot at 1600x1000 with the levels tab open, the volume pane collapsed and the pointer over the
chart (scratchpad `final-charts.png`) shows all five:
- 05 glass tooltip pinned at the cursor: `2026-08-31 · O 2,948.00 H 2,952.90 L 2,944.80 C 2,948.40 · VOL 53,58,165 · RSI 51.50`
- 06 legend rows with O/H/L/C/Vol mirrored from the same bar
- 07 `₹2890.00 SUPPORT HOLDING · STRENGTH 4/5` and `₹2940.00 RESISTANCE BROKEN · STRENGTH 3/5`
- 08 right-lane tags reading `S · -3.2%` and `R · -1.5%`; the old doubled `R 2940.00 | 2940.00` is gone
- 09 `VOLUME` strip carrying a sparkline and `48,30,275`

## Not done

- **08 partial**: tags are right-aligned, deduplicated, collision-resolved and dimmed/dashed when
  broken. The design's exact tag typography was matched approximately, not pixel-for-pixel.
- The staging spec edit from the previous commit remains UNVERIFIED (needs a session token).

## Verdict: PASS
