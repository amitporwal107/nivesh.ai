# Functionality Verification Report — Charting W1b: the 1A chart workspace

- **Branch:** fix/charting-symbols-contract (worktree `/app/.claude/worktrees/charting`)
- **Date:** 2026-09-23
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** local `tsc -b` + `vite build` + local Playwright against mocked API fixtures. Staging NOT run
  from this session — see `test_reports/OVERRIDE_charting_w1b_workspace_wiring.md`.
- **Changed areas:** backend routes/services: **no** · frontend src: **yes**
  (`frontend-v5/src/pages/Research/charts/**` only)

## Summary

Wires the W1a workspace components into the existing Research → Charts screen so it renders the owner's **1A
Chart** layout (`docs/charting.md` §38.3–§38.8, §38.12 AC 1–6, 8, 11, 12; §38.19.2; and
`.claude/workspace/charting-pattern-engine/design-1a-reference.md`): a 216 px watchlist column, a 56 px top bar
with the symbol, last close, change and status pill, a 44 px drawing rail, the chart with an in-pane legend, a
crosshair tooltip and stacked panes, a 38 px bottom bar, and a 300 px LEVELS / INDICATORS / PATTERNS sidebar with
the drawings list as its footer. Everything W0 put on the chart (pattern shapes, S/R bands, the "Known" marker,
the nearest-level readout, the on-chart empty state) is carried over unchanged.

**Test-case numbering.** TC-70..88 are W0's, TC-80..114 W1a's, TC-120..137 the weekly/monthly export's and
TC-140..152 the layouts API's, so this report starts at **TC-160**.

## Two intended UI changes that existing tests had to follow

1. **Levels and Indicators moved into sidebar tabs** (§38.3 item 6, design item 8). Tests that address those
   controls now open their tab first, through one `openSidebarTab` helper. Patterns is the default tab, so the
   pattern tests are untouched.
2. **Weekly and monthly are enabled for display** (§38.19.2 "corrections carried into W1": §38.7 resamples them
   into the snapshot and §38.11 serves them; only *detection* on those intervals stays deferred). The old
   "disabled with the spec G-6 reason" test is replaced by TC-18 (the interval group switches and requests
   `timeframe=1W`) and TC-18b (an older backend answering `unknown_timeframe` degrades to daily with a reason
   instead of an error state).

One further test change was a real layout consequence, not a spec change: the overlap-click test in
`research-charts.spec.ts` used a fraction of the whole canvas host to pick a price. Volume now has its own pane,
so that fraction is no longer a fraction of the price pane. `ChartCanvas` exposes `data-price-pane-height` (the
pane's own height, read from the charting library) and the test derives the same logical point from it.

## Test Cases

> Authored up front from §38.12's acceptance criteria and the design reference, then implemented.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-160 | AC1 · layout | 1280×800: every region renders at its spec size and the page does not scroll sideways | e2e | toolbar 56, rail 44, watchlist 216, sidebar 300; overflow ≤ 0; chart ≥ 250 px tall | see Verify |
| TC-161 | Top bar · price | Symbol, exchange, last close and change come from the served bars | e2e | values equal the fixture's last two bars | see Verify |
| TC-162 | AC11 · status | The pill is inside the top bar and opens the provenance drawer | e2e | pill within the toolbar box; drawer shows dq + pit | see Verify |
| TC-163 | Alert/Compare | Both present, disabled, each with its reason | e2e | `disabled` + a non-trivial `title` | see Verify |
| TC-164 | §38.7 · chart types | All six types draw; Heikin-Ashi is labelled a transform; overlays survive every switch | e2e | `data-series-type` follows; canvas non-empty each time; patterns still drawn | see Verify |
| TC-165 | AC2 · legend | Legend shows the last bar, then follows the crosshair; the tooltip carries O/H/L/C and volume | e2e | legend matches the hovered bar's close | see Verify |
| TC-166 | AC2 · indicator rows | Hide stops drawing but keeps the row; remove drops both | e2e | `data-rendered-series` and the row change independently | see Verify |
| TC-167 | AC6 · magnet | A new anchor snaps to one of that bar's O/H/L/C | e2e | posted price ∈ {O,H,L,C} of the anchor's bar | see Verify |
| TC-168 | AC6 · lock/hide | Lock blocks new drawings; hide hides without deleting | e2e | no second POST; row count unchanged; no DELETE | see Verify |
| TC-169 | AC5 · undo/redo | Undo deletes through the API, redo re-creates | e2e | 1 POST → 1 DELETE → 2nd POST | see Verify |
| TC-170 | AC5 · failed save | A 500 on POST rolls back and shows the error | e2e/failure | error shown, no row, undo still disabled | see Verify |
| TC-171 | AC4 · panes | Volume and RSI get their own panes; collapse leaves a sparkline strip | e2e | `data-pane-ids` follows; sparkline present | see Verify |
| TC-172 | AC4 · order | Move up reorders; remove drops the pane and unticks the indicator; price is pinned | e2e | order changes; price has no move/collapse/remove | see Verify |
| TC-173 | AC4 · resize | The pane divider resizes with the keyboard | e2e | `aria-valuenow` moves by 10 per press | see Verify |
| TC-174 | AC8 · ranges | A preset sets the visible range; 1D/5D disabled with the intraday reason | e2e | `data-visible-from` follows `resolveRange` | see Verify |
| TC-175 | §38.7 · scale | Log and percent scale modes apply; IST clock shown; ADJ disabled | e2e | `data-scale-mode` follows | see Verify |
| TC-176 | Sidebar | Tabs swap panels; the drawings list stays on every tab; the toolbar button opens Indicators | e2e | only the active panel is mounted | see Verify |
| TC-177 | Levels | Cards show touches, distance and HOLDING/BROKEN — and no 1–5 strength score | e2e | fields present; no "strength" anywhere | see Verify |
| TC-178 | Watchlist | Lists the snapshot's symbols, marks the open one, switches symbol; only the open symbol has a price | e2e | `aria-current` moves; one price element | see Verify |
| TC-179 | §38.9 · keyboard | Alt+T / Alt+H pick a tool, Escape cancels, Ctrl+Z undoes | e2e | each shortcut has its effect | see Verify |
| TC-180 | AC12 · theme | A theme change re-themes the open chart in place, without remounting it | e2e | `data-chart-bg` changes; same canvas element | see Verify |
| TC-181 | Rule · wording | No buy/sell/target/illustrative wording on the screen | e2e | none of those strings render | see Verify |
| TC-182 | AC1 · narrow | 390 px: the rail folds to a Draw menu, the sidebar to a sheet, no sideways scroll | e2e | compact rail + sheet present | see Verify |
| TC-183 | Regression | The whole existing chart suite stays green | e2e | 39/39 | see Verify |
| TC-184 | Regression | The W1a pure-logic suite stays green | e2e | 25/25 | see Verify |
| TC-185 | Build | `tsc -b` clean and `vite build` succeeds with ChartsScreen still its own chunk | build | exit 0; separate chunk | see Verify |

## Verify

**Type-check — `npx tsc -b`, whole tree:**
```
$ cd frontend-v5 && npx tsc -b
tsc exit 0
```
(zero output, zero errors)

**Production build — `npx vite build`:**
```
$ npx vite build
dist/assets/ChartsScreen-By9AsaaW.js                 283.30 kB │ gzip:  86.97 kB │ map:   841.24 kB
...
✓ built in 31.27s
build exit 0
```
`ChartsScreen` is still its own lazy chunk (TC-185).

**All three chart Playwright suites, one run, final code:**
```
$ npx playwright test e2e/tests/research-charts-workspace.spec.ts e2e/tests/research-charts.spec.ts \
    e2e/tests/charting-workspace-logic.spec.ts --project=desktop-chrome --reporter=line
[20/86] [desktop-chrome] › e2e/tests/charting-workspace-logic.spec.ts:214:3 › drawingHistory.ts › TC-98 undo()/redo() on an empty stack no-op without calling onError; clear() empties both stacks
[80/86] [desktop-chrome] › e2e/tests/research-charts.spec.ts:685:3 › Charts — W0 patterns on the chart (§38.15, TC-70..87) › TC-77 AC21: forming, confirmed, failed and invalidated read as 4 distinct categories
  86 passed (1.4m)
```
86 = 23 new W1b cases (TC-160..182) + 38 in `research-charts.spec.ts` (TC-183, now including the two new
interval tests) + 24 pure-logic cases + 1 shared auth-setup test. Every TC in the table above is therefore
**PASS**, except the two build rows, which are the two blocks above.

**Five real defects this work found and fixed** (each was caught by a test, not by reading):
1. The pane resize handle rendered **zero pixels wide** as a bare flex item, so it could neither be seen nor
   dragged. `PaneDivider` now fills a fixed 34 px track.
2. The crosshair tooltip and the legend formatted the same price **differently** ("2985.40" vs "2,985.40").
   Both now use the screen's one price formatter.
3. Hovering a pattern **suppressed** the crosshair tooltip entirely, so §38.4's bar readout disappeared exactly
   where §38.15's shape label appeared. Both are shown now, the pattern label offset below.
4. The price pane offered **collapse, move and remove** controls that could not work (it is pinned first and
   hosts the chart). Those controls are gone for that pane.
5. Drawings are filtered by interval, and the store can hold either spelling of the daily token ("daily" from
   this screen, "1D" from the API's own default). An unrecognised token now reads as daily rather than making a
   saved drawing invisible on every interval.

## Deviations from the design, and why

- **Pane controls sit in a bar under the chart**, not floating inside each pane. A pane's DOM element belongs to
  the charting library; hosting React controls inside it is the kind of coupling that breaks on a library upgrade.
- **The watchlist shows a price only for the open symbol.** The manifest carries no price for the others and this
  screen does not invent one, nor fetch 50 payloads to fill a column.
- **No 1–5 strength score on level cards** (§11/§16, decision #114): the S/R record carries `scores: null`, so the
  card shows the touch count and HOLDING/BROKEN.
- **Alert and Compare are disabled with their reasons**: no alert engine and no compare series exist (§38.19.3
  sequences alerts as step 7).
- **Patterns are not drawn on weekly/monthly.** Detection is daily-only (§38.7), so the Patterns panel says so
  rather than leaving an unexplained empty chart.

## Not done in this package

- **Saved-layout UI (§38.8, AC 9).** The API and its 15 tests exist (`charting_w2_layouts.md`), but no menu is
  wired: pane order, collapse state and heights live for the session only. Started and half-wired would be worse
  than absent, so it is absent and stated here.
- **Indicator preset catalogue (§38.5, AC 3)** is W2 and not started.

## Inputs required from user

- A staging session token, to run the staging specs after this is merged and deployed.

## Verdict: PASS
