# Functionality Verification Report — Chart Analysis drawing gestures (and the 1m / 3m staging check after #465)

- **Branch:** fix/chart-drawing-gestures (from origin/dev 6d30a7f7) · commit 88655a14 + this report · PR to dev
- **Date:** 2026-11-03
- **Author:** Claude (full stack developer + QA)
- **Environment:** staging as deployed (dev 6d30a7f7, real data, read only: page loads, pointer gestures, GETs with the
  staging session cookie); branch tests in the Playwright container (Chromium 1223, every `/api/*` route-mocked, MOCK)
- **Changed areas:** backend: no · frontend src: yes (analysis/AnalysisChart.tsx, analysis/ChartAnalysis.tsx)

## Summary
Owner: "None of the drawing tools are working". On staging, clicks drew but **press, drag, release drew nothing** with the
trend / rectangle / Fib / measure tools (the release counted as the first of two clicks). Drawing now runs on the chart's
pointer events and takes both gestures; the first point shows at once; touch drags draw while a tool is on; the chart's
text cannot be selected (with pointer capture a drag selected it, and the next press started the browser's own drag,
which cancelled the pointer). Test cases first: test_reports/chart_drawing_gestures_TESTCASES.md.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| G1 | drag | trend by press-drag-release | e2e (mocked) | one trend; preview while dragging; none left | PASS (FAIL on old code) |
| G2 | drag | rect, Fib, measure by drag, right after G1 | e2e (mocked) | one each; 7 Fib levels; measure bars > 10 | PASS |
| G3 | click | trend by two clicks | e2e (mocked) | dot after the first click; drawing after the second | PASS |
| G4 | click | H, V by a click; H by a short drag | e2e (mocked) | one each | PASS |
| G5 | outside | release past the plot's right edge | e2e (mocked) | ends on the last bar in view (x within 0.5 px) | PASS |
| G6 | cursor | crosshair: drag pans, Reset view; cash click sets the entry | regression e2e (F12, cash spec) | as before | PASS |
| G7 | escape | Esc after the first click | e2e (mocked) | no dot, no preview, nothing drawn | PASS |
| G8 | regression | the three Chart Analysis specs | regression e2e | all pass | PASS |
| G9 | staging | after merge: every tool by click and by drag on PETRONET | live Playwright | each tool draws | NOT RUN (needs the merge) |
| S1e | staging | PETRONET 1m and 3m after #465 | post-deploy API | Kite candles | PASS |

## Staging findings (before the fix; deployed code, PETRONET, real data)
- Clicks: `h: drawings 0->1->2 · v: 2->3->4 · trend: 4->4->5 (preview after 1st click=1) · rect 5->5->6 · fib 6->6->7 · measure 7->7->8`,
  every click landing on `rect[ca-price-hit]`, no page errors; the screenshot shows the drawings.
- 1366×768, chart partly in view: `A h-line click: drawings=1`, no scroll; **`B trend by drag: drawings 1->1 preview=1`**;
  `C after 70 s (one live refresh): drawings 1->2 tool=trend`.
- Ruled out: `after one drag: selected chars=0; 3 wobble clicks -> drawings 4 (expect 4 if fine); events ["click","click","click"]`.

## UI / Playwright Tests (branch, MOCK data)
- **Old code** (`git checkout origin/dev --` the two chart files, the new spec kept), `-g "G1–G7"`:
  `Expected: 1 Received: 0` at `await expect(page.getByTestId("ca-draw-preview")).toHaveCount(1)` (the first drag) · `1 failed`
- **With the fix, first try:** `55 passed, 1 failed` — G2's rect drag: browser events `["pointerdown@542,271 btn=0 tgt=ca-price-hit","pointercancel@0,0","lostpointercapture@0,0"]`
  (G1's drag had selected chart text; the press on it started a native drag). Fixed with `user-select: none`, `preventDefault`
  on a drawing press and clearing the selection.
- **With the fix:** `npx tsc --noEmit -p tsconfig.json` → `tsc EXIT 0`; `vite build` → `build EXIT 0`;
  `npx playwright test --config pw.copilot-app.config.ts copilot-app-desk-chart-analysis.spec.ts copilot-app-chart-analysis-chain.spec.ts copilot-app-chart-analysis-basket.spec.ts`
  → `56 passed (1.8m)`
  - Result: PASS

## API / Endpoint Tests (staging, #465 deployed: backend restarted 07:06:40Z after the file landed 07:06:27Z)
- `python3 -I scratchpad/s1/s1_api.py`, checked at 2026-11-03T16:43:56+05:30:
  - `live-chart 1m s=1 -> HTTP 200 tf=1m/1M source='Kite intraday' reason=None bars=360 days=1 first=2026-11-03T09:15 last=2026-11-03T15:14` · `sma20 check: route 304.02 vs mean(last 20 closes) 304.0175 -> MATCH`
  - `live-chart 3m s=2 -> HTTP 200 tf=3m/3M source='Kite intraday' reason=None bars=240 days=2 first=2026-11-02T09:15 last=2026-11-03T15:12` · `sma20 302.81 vs 302.8150 MATCH`
  - Result: PASS (this was the 1m / 3m daily fallback #465 fixed)

## Unverified / Follow-ups
- UNVERIFIED: G9 on staging, because this branch is not merged. After the merge and the frontend image rebuild: the
  staging drawing specs (scratchpad/s1/s1-draw-staging.spec.ts, s1-draw2-staging.spec.ts) by click and by drag.
- Not known: how the owner was drawing. Clicks already worked on staging in Chromium; if clicks also failed for them, the
  browser / device is needed to look further.

## Verdict: PASS
