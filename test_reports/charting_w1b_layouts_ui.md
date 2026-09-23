# Functionality Verification Report — Charting: the saved-layout menu (§38.8, AC 9)

- **Branch:** feat/charting-layouts-ui (worktree `/app/.claude/worktrees/charting`), on dev `314006bd`
- **Date:** 2026-09-23
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** local `tsc -b` + `vite build` + local Playwright against mocked API fixtures. Staging NOT run
  from this session — see `test_reports/OVERRIDE_charting_w1b_layouts_ui.md`.
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**
  (`frontend-v5/src/pages/Research/charts/**` only)

## Summary

Closes the one gap left open by `charting_w1b_workspace_wiring.md`: the saved-layout API had no UI. The top bar
now carries a Layouts menu with **Save, Save as…, Rename…, Delete** and the recent layouts to reopen, the open
layout's name with a dot when it has unsaved changes, and a **debounced autosave** once a layout is open
(§38.8: "users can save, save as, rename, delete and reopen recent layouts. Layouts autosave after changes. A new
chart is 'Unnamed' until it is saved").

A layout stores what §38.8 lists: symbol, interval, chart type, indicator instances, pane order/heights/collapse,
visible range, drawing visibility and sidebar state. No theme — the chart follows the app (D-6).

## One integration bug found before a line of UI was written

The API persists the OHLC-bar chart type as **`bars`** (`research_chart_layouts.py` CHART_TYPES, already tested),
while the screen called it `ohlc_bars`. Every save would have been rejected with
`chart_type: must be one of [...]`. The screen now uses the API's id, so a layout round-trips with no translation
table in between.

## Test Cases

| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| TC-190 | A chart is "Unnamed" until saved; Save captures symbol, chart type, indicators and panes | e2e | POST body matches the workspace; the price pane is not in `panes` | PASS |
| TC-191 | Reopening a layout restores symbol, chart type, indicators, pane order, collapse and sidebar tab | e2e | pane ids and series type follow the stored layout | PASS |
| TC-192 | A change after saving autosaves; applying a layout does NOT write it back | e2e | 0 PATCH on apply, exactly 1 after an edit | PASS |
| TC-193 | Rename and delete act on the open layout; both are disabled before the first save | e2e | disabled with a reason, then PATCH/DELETE | PASS |
| TC-194 | A failed save shows the API's reason and leaves the chart unnamed | e2e/failure | reason code shown, name stays "Unnamed" | PASS |

## Verify

**Type-check:**
```
$ cd frontend-v5 && npx tsc -b
tsc exit 0
```

**All chart suites, one run, final code:**
```
$ npx playwright test e2e/tests/research-charts-workspace.spec.ts e2e/tests/research-charts.spec.ts \
    e2e/tests/charting-workspace-logic.spec.ts --project=desktop-chrome --reporter=line
[53/91] ... TC-194 a failed save is shown and the layout stays dirty
[85/91] ... TC-77 AC21: forming, confirmed, failed and invalidated read as 4 distinct categories
  91 passed (1.3m)
```
91 = the 86 from the previous package + the 5 new layout cases.

## Three real defects the tests caught, all mine

1. **The screen crashed outright** (`layouts.map is not a function`, every browser test failed with the screen
   absent). `layoutsApi.list` trusted the response to be an array; an unmocked route returns the dev server's
   HTML. Fixed the way `chartApi.symbols` already does it: shape-check, and return an error result rather than
   letting a screen crash on `.map`. This would have bitten in production too, since a proxy or an error page can
   answer 200 with something that is not a list.
2. **Applying a layout wrote it straight back.** The suppression was a ref cleared on a timer, and the applied
   state lands on the *following* commit. Replaced with a signature that is primed on the pass after the apply
   commits — no timers.
3. **Choosing a layout whose symbol already matched never applied at all.** The pending layout lived in a ref, so
   the apply effect's dependencies never changed. It is state now.

## Deliberate choices

- **The price pane is not stored.** It is always first and the API requires a height above zero, while the price
  pane's height is simply whatever the others leave.
- **`preset_id` is `"default"`** on every indicator instance. There is no preset catalogue yet (§38.5, W2); every
  indicator is drawn with the parameters the snapshot's own contract fixes, and "default" names exactly that. It
  is not a placeholder for missing data.
- **Drawing visibility** records every current drawing as hidden when hide-all is on, since the rail hides them
  all at once rather than one by one. A drawing added after the save is not in the map and the chart opens with
  drawings shown — visible, never silently missing.
- **The name is excluded from the autosave signature.** Renaming is its own call; including it would make a
  rename look like a workspace edit.

## Not done

- The **indicator preset catalogue** (§38.5, AC 3) is the remaining W2 item and is not started.

## Inputs required from user

- A staging session token, to verify the menu against the real API after deploy.

## Verdict: PASS
