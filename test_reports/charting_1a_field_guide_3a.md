# Functionality verification — field guide (design artifact tab 3A)

Date: 2026-09-23
Branch: feat/charting-field-guide (off 92a1be79, so PR #153 is untouched)
Artifact: `frontend-v5/design/Nivesh charting · offline.html`, tab 3A "What every field on the screen means"

## Scope decision: 3A is documented for the screen we have, not the one the mock draws

3A in the artifact is one table covering all four designed screens. Counting its `dictGroups`:

| Group | Screen | Built? |
|---|---|---|
| TOP BAR | 2A | no |
| SIGNAL INBOX | 2A · LEFT | no |
| CHART OVERLAY | 2A · CENTRE | no |
| VOLUME PANE | 2A · CENTRE | no |
| SIGNAL PANEL | 2A · RIGHT | no |
| PATTERN LIBRARY | 2A · BELOW CHART | no |
| **S&R PANEL** | **1A · RIGHT** | **yes** |
| **SUB-PANES** | **1A · CENTRE** | **yes** |
| PAPER TRADING | 4A | no |

Only two of the nine groups describe a screen that exists. Shipping the other seven would document
signals, alert dedupe keys, signal scores, cost models and a paper-trading ledger that this product
does not have — a dictionary for a product we do not ship. So the guide covers **only fields the
Charts screen actually renders**: the two 1A groups, plus the 1A fields 3A grouped under 2A (status
chip, provenance strip, interval, preset catalogue, pattern states, nearest-level readout).

It is a panel on the existing Charts screen, not a new screen — the owner's "changes for existing
charting screen only" rule.

## Where the artifact and the code disagree, the code wins

3A defines STRENGTH as "touch count, reaction size and volume confirmation at the level".
`research/charting/geometry.py: level_strength()` and `docs/charting.md` §13.2 define it as
`0.30*touch + 0.20*recency + 0.20*rejection + 0.15*volume + 0.15*time`. "Reaction size" is not a
component; recency and time are. The guide states the engine's definition. TC-242 pins this both
ways — it asserts the five real components are present AND that "reaction size" is absent — so the
guide cannot silently drift back to the mock's wording.

## Test cases (authored before implementation)

| # | Case | Expectation |
|---|---|---|
| TC-240 | Opens, grouped by area, source per row | all five groups visible; header reads LABEL · MEANING · SOURCE; close works |
| TC-241 | Search narrows across label, meaning, source | "strength" keeps the levels group and drops provenance; a miss shows the empty state |
| TC-242 | Strength is documented as the engine computes it | the five real components present; "reaction size" absent; "never a probability" present |
| TC-243 | Never documents an unbuilt screen | no paper trade / slippage / brokerage / signal score / lifecycle / expectancy; says signals, alerts and paper trading are not built |

## Real output

```
$ npx tsc --noEmit -p tsconfig.json
tsc exit: 0
```

First run — 4 failed, all on the same locator:
```
    Error: locator.click: Test timeout of 30000ms exceeded.
    Call log:
      - waiting for getByTestId('chart-toolbar-more')
  4 failed
  1 passed (2.1m)
```

Cause found rather than retried: `chart-toolbar-more` renders only when `compact` is true. Hanging
the guide off the More menu alone would have shipped it **mobile-only** — a real defect the test
caught, not a test bug. A dedicated `chart-field-guide-open` button was added to the desktop cluster
beside fit / data view / full screen, and the More item kept for compact.

```
$ npx playwright test research-charts.spec.ts -g "TC-240|TC-241|TC-242|TC-243" --workers=1
  5 passed (12.6s)

$ npx playwright test research-charts.spec.ts research-charts-workspace.spec.ts \
    charting-workspace-logic.spec.ts --project=desktop-chrome --workers=1
  107 passed (2.3m)
```

## Not done

Tabs 2A (Signals & Alerts) and 4A (Paper Trading) are not built and are not attempted here. They are
not design work — they need a live signal engine, an alerts engine with an audit trail, and a paper
-trading engine with a versioned cost model. Their PRDs are filed at `docs/prd/`.

## Verdict: PASS
