# Chart Analysis drawing tools — gestures: test cases (written before the code)

Branch `fix/chart-drawing-gestures` (from `origin/dev` 6d30a7f7). Owner, 3 Nov 2026: "None of the drawing tools are working".

## What staging showed (deployed #463, PETRONET, real data, Chromium)
- Click gestures work: H / V by one click, trend / rect / Fib / measure by two clicks (8 of 8 drawn, screenshot shows them),
  also at 1366×768 and across the 60 s live refresh.
- **Press, drag, release draws nothing** with trend / rect / Fib / measure: the release only counts as the first click
  (`B trend by drag: drawings 1->1 preview=1`). That is the usual way to draw on a chart.
- After the first click nothing shows until the mouse moves (the dashed preview needs a hover point).
- On a touch screen wide enough for the tool rail, a drag scrolls the page (`touch-action: pan-y`) instead of drawing.
- Checked and ruled out: after a drag, jittery clicks still draw on staging (`selected chars=0`, 3 of 3 drawn), and
  the page does not scroll on a press. So the failure is the drag gesture, not the clicks.

## Change
Drawing moves from the price pane's click handler to the chart's pointer events (as in the owner's standalone design):
- a press on the price pane with a drawing tool starts a gesture (pointer captured, so a release outside still counts)
- release without moving = a click: H / V draw there; two-point tools take it as the first point, then the second
- press, drag, release = a two-point drawing from the press to the release (H / V draw at the release)
- the first point of a two-point tool shows a dot at once; the dashed preview follows the pointer, also while dragging
- with a drawing tool on, touch drags draw instead of scrolling; the crosshair tool keeps pan and page scroll as today
- the chart's text cannot be selected, and a drawing press blocks the browser's default action: with pointer capture, a
  drag selected chart text and the next press on it started a native drag (`pointercancel`), found while testing G2
- the tooltips and the hint say "click two points or drag"

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| G1 | drag | trend: press, drag, release | e2e (mocked) | one trend drawing; no preview left behind |
| G2 | drag | rect, Fib, measure by drag | e2e (mocked) | one drawing each; Fib has 7 levels; measure label shows the bars between press and release |
| G3 | click | trend by two clicks (still) | e2e (mocked) | dot after the first click, before any mouse move; one drawing after the second |
| G4 | click | H and V by one click; H by a short drag | e2e (mocked) | one drawing each |
| G5 | outside | press in the price pane, release past the plot's right edge | e2e (mocked) | the drawing ends at the last bar in view (pointer captured) |
| G6 | cursor | crosshair tool: drag pans, click on a cash-only stock still sets the entry | regression e2e | as before |
| G7 | escape | Esc after the first click | e2e (mocked) | dot and preview gone, nothing drawn |
| G8 | regression | the Chart Analysis specs (F1–F15 and the 41 older cases) | regression e2e | all pass |
| G9 | staging | after merge: PETRONET, every tool by click and by drag, real mouse events | live Playwright | each tool draws; screenshot |
