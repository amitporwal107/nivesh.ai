# Functionality verification — Charts screen layout alignment to the shared design (tab 1A)

Date: 2026-09-23
Branch: feat/charting-indicator-catalogue
Scope: `frontend-v5/src/pages/Research/charts/ChartsScreen.tsx`,
       `frontend-v5/src/pages/Research/charts/workspace/Toolbar.tsx`

## Why this change

The owner shared a "Charting View Redesign" mockup and reported the built screen "is not matching
at all". A screenshot of the built screen confirmed the structural cause: the page rendered a 26px
serif "Charts" headline, a two-line description paragraph and **two stacked full-width banners**
before the chart, then capped the workspace at `min(620px, calc(100vh - 250px))`. Roughly 190px of
chrome sat above a chart that then got under half the viewport. The design is a terminal in which
the chart owns the viewport and the price is the headline.

The mockup is NOT in the repo. `frontend-v5/design/` holds four other Nivesh mockups (Sep 20) and a
README stating the convention: an artifact lands in `design/`, and `src/` is a port of it. The
charting mockup only ever existed as a chat attachment, so there was nothing to port from and
nothing to A/B against — see "Root cause" below.

## Changes

1. `Shell` — dropped the serif headline + description paragraph; padding `pt-5 pb-10` -> `pt-3 pb-4`,
   gap 12 -> 8. The error/empty states that also use `Shell` carry their own `<h3>`, so they are
   unaffected.
2. The two full-width banners became **one compact provenance strip** carrying an `<h2 class="nv-eyebrow">Charts</h2>`
   plus both notices as pills. Wording is unchanged and still in the DOM, plus a `title` on each
   pill; the red pill makes the synthetic-data warning more prominent, not less.
3. Workspace height `min(620px, calc(100vh - 250px))` -> `calc(100vh - 132px)`, `maxHeight: 900`.
4. `Toolbar` — price is now the headline (17px -> 23px, weight 600) and the symbol steps back
   (17px -> 14.5px, `--c-ink-2`). Previously both were 17px so the eye had nothing to land on.

No API, contract, snapshot or catalogue change. No testid was added, renamed or removed.

## Test cases

| # | Case | Expectation |
|---|---|---|
| TC-15..TC-28, TC-70..TC-87 | Full `research-charts.spec.ts` chart surface, S/R, status chips, indicators, drawing tools, data view, mobile, W0 patterns | unchanged behaviour after the layout rework |
| TC-16 | fixture banner still loud | `chart-banner-fixture` visible, contains "SYNTHETIC DEVELOPMENT DATA" and "not real market data" |
| TC-176..TC-218 | Full `research-charts-workspace.spec.ts` — workspace shell, saved layouts, indicator dialog, reference bands | unchanged behaviour |
| — | `charting-workspace-logic.spec.ts` | unchanged behaviour |
| — | typecheck | `tsc --noEmit` clean |
| — | visual | chart area grows; one provenance strip replaces two banners; price reads as the headline |

## Real output

### Typecheck
```
$ npx tsc --noEmit -p tsconfig.json
tsc exit: 0
```

### `research-charts.spec.ts` (includes TC-16 fixture banner)
```
$ npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome
  39 passed (1.9m)
```

### `research-charts-workspace.spec.ts` + `charting-workspace-logic.spec.ts`
```
$ npx playwright test e2e/tests/research-charts-workspace.spec.ts e2e/tests/charting-workspace-logic.spec.ts --project=desktop-chrome
  1 failed
    [desktop-chrome] › research-charts-workspace.spec.ts:434:3 › TC-179 keyboard: Alt+T / Alt+H pick a tool, Escape cancels, Ctrl+Z undoes
  58 passed (1.8m)
```

TC-179 investigated rather than retried blindly — it is flaky under load (that run was 59 tests in
one worker on a host sharing CPU with live NIDP OCR), not a regression:

```
$ npx playwright test e2e/tests/research-charts-workspace.spec.ts --project=desktop-chrome -g "TC-179"
  2 passed (16.8s)

$ npx playwright test e2e/tests/research-charts-workspace.spec.ts --project=desktop-chrome
  35 passed (50.9s)
```

### Visual evidence
Before/after screenshots captured this session at 1600x1000 with the standard mocked harness
(scratchpad `current-charts.png` / `after-charts.png`). Measured from the screenshots: the chart
plot area grows from ~400px to ~700px tall; the chrome above the toolbar drops from ~190px to ~28px.

## Root cause (so it does not recur)

`frontend-v5/design/README.md` defines the repo's own convention — design artifact lands in
`frontend-v5/design/`, `src/` is a port of it, and the artifact is kept "for A/B comparing the
production output against the canonical design". The charting mockup was never added there, so the
screen was built from the written spec (`docs/charting.md` §38) alone. §38 specifies behaviour and
structure, not composition, which is exactly the axis that diverged. **Action for the owner: drop
the "Charting View Redesign" HTML into `frontend-v5/design/` so it is a durable reference.**

## Follow-up: worked from the artifact's own 11 numbered changes

With the file in the repo I could read 1A's `callouts` array instead of guessing. Mapping:

| # | Change | State |
|---|---|---|
| 01 | One 56px top bar | already built |
| 02 | Price is the headline | built; sizes corrected to the artifact's own (price 20px/500, symbol 17px/600) |
| 03 | Disabled states explain themselves in place | **done here** |
| 04 | Vertical drawing rail | already built |
| 05 | Crosshair with an OHLC readout | gap |
| 06 | Indicators live on the chart legend | gap |
| 07 | S&R gets a real panel (strength 1-5, distance in Rs and %) | gap |
| 08 | On-chart level tags stop colliding | gap |
| 09 | Stacked panes, collapsed as 26px sparkline strips | gap |
| 10 | Range selector on the time axis | already built |
| 11 | Detected patterns draw themselves | already built |

### 02 correction

My first pass made the price 23px/600 and shrank the symbol to 14.5px. The artifact specifies
price 20px/500 mono-tabular, change 12px, and keeps the symbol at 17px/600. Corrected to match --
shrinking the symbol was my invention, not the design's.

### 03 in full

Change 03 reads: *"Weekly and Monthly stay in the interval group, dimmed, with the reason on hover.
A sentence of grey spec text sitting beside the buttons is not a control state."* with
`REPLACES: "WEEKLY / MONTHLY DISABLED - NEEDS LONGER HISTORY (SPEC G-6)"`.

The dimmed-with-`title` half already existed. The half that did not: `Toolbar.tsx` also rendered a
`chart-timeframe-reason` span beside the group -- exactly the grey sentence the artifact names.
Removed, along with the now-unused `disabledInterval` lookup.

Two tests asserted that span. Both were updated to assert the reason **in place** on the disabled
control, which is what the change actually asks for:
- `research-charts.spec.ts` TC-18b -> `chart-timeframe-weekly` has `title` matching `/coming with W2/`
- `staging-research-charts.spec.ts` TC-18 -> `chart-timeframe-weekly` has a non-empty `title`

UNVERIFIED: the staging spec edit has not been run -- it needs a session token I do not have.

### Real output (follow-up)

```
$ npx tsc --noEmit -p tsconfig.json
tsc exit: 0

$ npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome
  17 failed
  22 passed (2.6m)
```

Investigated rather than retried blindly. The failures were
`net::ERR_CONNECTION_REFUSED at http://localhost:5174` -- Playwright picked 2 workers and the Vite
dev server fell over on a host shared with live NIDP OCR. Not a code regression:

```
$ npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome --workers=1
  39 passed (2.4m)
```

## Not addressed in this change (remaining gaps vs the mockup)

Changes 05, 06, 07, 08 and 09 above. In the artifact's own terms:
1. (05) Crosshair legend is a large floating panel; the design pins a glass tooltip at the hovered bar and mirrors it into the legend.
2. Pattern labels collide ("Higher highs / higher lows · formed" over "Rectangle · confirmed").
3. Level tags are doubled against the price scale (`R 2940.00` next to `2940.00`).
4. Collapsed PRICE / VOLUME pane strips are empty grey rows, not sparkline strips.
5. Bottom bar uses a raw unstyled `mm/dd/yyyy` browser date input.
6. Disabled controls (Alert, Compare, ADJ) give no reason for being disabled.
7. TradingView attribution sits mid-chart.

Adopting the mockup's own token set (`--bg-0`, mint `#6AF0A8`, Instrument Serif) is a separate
decision from the §38 functionality and is not part of this change.

## Verdict: PASS
