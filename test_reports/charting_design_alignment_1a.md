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

## Not addressed in this change (remaining gaps vs the mockup)

Visible in `after-charts.png`, each a separate change:
1. Crosshair legend is a large floating panel over the chart; the design wants a thin OHLC readout strip.
2. Pattern labels collide ("Higher highs / higher lows · formed" over "Rectangle · confirmed").
3. Level tags are doubled against the price scale (`R 2940.00` next to `2940.00`).
4. Collapsed PRICE / VOLUME pane strips are empty grey rows, not sparkline strips.
5. Bottom bar uses a raw unstyled `mm/dd/yyyy` browser date input.
6. Disabled controls (Alert, Compare, ADJ) give no reason for being disabled.
7. TradingView attribution sits mid-chart.

Adopting the mockup's own token set (`--bg-0`, mint `#6AF0A8`, Instrument Serif) is a separate
decision from the §38 functionality and is not part of this change.

## Verdict: PASS
