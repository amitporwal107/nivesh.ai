# Functionality Verification Report — Charting W1a: workspace components

- **Branch:** fix/charting-symbols-contract (worktree `/app/.claude/worktrees/charting`)
- **Date:** 2026-09-22
- **Author:** Claude (Full-Stack Developer)
- **Environment:** local build/typecheck + local Playwright (mocked/pure-logic) — no staging deploy in this phase
- **Changed areas:** backend routes/services: no · frontend src: yes (new files only, plus one existing-file edit)

## Summary

W1a per `docs/charting.md` §38.3–§38.9, §38.12 (W1 row), §38.14 D-6: builds the **workspace components** for the
existing Research → Charts screen — Toolbar, DrawingRail, BottomBar, Sidebar, Legend, PaneControls (+PaneDivider),
a shared MenuButton dropdown primitive, and four pure logic modules (drawingHistory, magnet, ranges, keyboard) —
plus live app-theme following in `theme.ts` (D-6). All are **new files** under
`frontend-v5/src/pages/Research/charts/workspace/`, except `theme.ts` which is edited in place (existing exports
kept working). Per the task's explicit boundary, `ChartsScreen.tsx`, `ChartCanvas.tsx`, `primitives.ts`,
`contract.ts` and `DataView.tsx` were **not touched** — those are a concurrent W0 task (confirmed below, "Scope
isolation"); wiring these new components into them is **W1b**, not this phase.

This report verifies what W1a actually delivers at this stage: the pure-logic modules by real unit tests, the
whole tree by a real `tsc -b` type-check and a real `vite build`, and that the existing Charts Playwright suite
still passes with `theme.ts` changed. It does **not** claim end-to-end behavioural verification of §38.13's
acceptance criteria (crosshair→legend, pane persistence, etc.) — those require the W1b wiring into
ChartCanvas/ChartsScreen and are marked accordingly in the AC table below, per the task's own instruction to "note
which are completed only after the W1b wiring."

## Scope isolation (real evidence, not a claim)

```
$ git status --porcelain -- frontend-v5/src/pages/Research/charts frontend-v5/e2e/tests/charting-workspace-logic.spec.ts
 M frontend-v5/src/pages/Research/charts/ChartCanvas.tsx      <- W0 (not touched by this task)
 M frontend-v5/src/pages/Research/charts/ChartsScreen.tsx     <- W0 (not touched by this task)
 M frontend-v5/src/pages/Research/charts/DataView.tsx         <- W0 (not touched by this task)
 M frontend-v5/src/pages/Research/charts/contract.ts          <- W0 (not touched by this task)
 M frontend-v5/src/pages/Research/charts/theme.ts             <- THIS TASK (edited: added useAppTheme)
?? frontend-v5/e2e/tests/charting-workspace-logic.spec.ts     <- THIS TASK (new)
?? frontend-v5/src/pages/Research/charts/PatternDetails.tsx   <- W0 (not touched by this task)
?? frontend-v5/src/pages/Research/charts/patternLayer.ts      <- W0 (not touched by this task)
?? frontend-v5/src/pages/Research/charts/patternStyle.ts      <- W0 (not touched by this task)
?? frontend-v5/src/pages/Research/charts/workspace/           <- THIS TASK (new directory, 12 files)
```

## Test Cases

> TC-80 upward (this worktree's charting reports run TC-1..TC-61 so far; TC-80 avoids collision with the
> concurrent W0 task's own numbering). Pure-logic tests were authored before/alongside the modules they cover, one
> file per module, per the four behaviours the task spec calls out for each.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-80 | magnet.ts | `nearestBar` exact date match | unit | returns that bar | PASS |
| TC-81 | magnet.ts | `nearestBar` before/after the series, empty series | unit | clamps to first/last bar, null for empty | PASS |
| TC-82 | magnet.ts | `nearestBar` a gap date resolves to the nearer neighbour | unit | nearer of the two adjacent bars, by real ms distance | PASS |
| TC-83 | magnet.ts | `magnetSnapToBar` snaps to the nearest of O/H/L/C | unit | correct field + price for 4 probe prices | PASS |
| TC-84 | magnet.ts | `magnetSnap` end-to-end (date→bar→snap); empty series | unit | correct snap; null, not a throw, when empty | PASS |
| TC-85 | ranges.ts | `RANGE_PRESETS`: 1D/5D disabled with reason; 1M..All enabled | unit | 1D/5D `enabled:false, disabledReason:"needs intraday data"`; rest enabled, no reason | PASS |
| TC-86 | ranges.ts | `resolveRange` on a disabled preset or empty series | unit | null (never throws, never a partial range) | PASS |
| TC-87 | ranges.ts | `resolveRange("ALL", …)` | unit | `{from: first bar, to: last bar}` | PASS |
| TC-88 | ranges.ts | `resolveRange` 1M/3M/1Y month arithmetic | unit | exact calendar month subtraction from the last bar | PASS |
| TC-89 | ranges.ts | `resolveRange("YTD", …)` across a year boundary | unit | 1 Jan of the last bar's year | PASS |
| TC-90 | ranges.ts | `resolveRange` clamps `from` when history is shorter than the preset | unit | `from` = series' first bar, not a date before it | PASS |
| TC-91 | drawingHistory.ts | `run()` success | unit | pushes to undo, clears redo, no `onError` | PASS |
| TC-92 | drawingHistory.ts | `run()` failure (§38.6 "a failed save rolls back and shows the error") | unit | `onError` called with the real message; stack untouched | PASS |
| TC-93 | drawingHistory.ts | `undo()` success | unit | calls `command.undo()`, moves undo→redo | PASS |
| TC-94 | drawingHistory.ts | `undo()` failure | unit | `onError` called; command stays on the undo stack (not silently dropped) | PASS |
| TC-95 | drawingHistory.ts | `redo()` success | unit | replays `do()`, moves redo→undo | PASS |
| TC-96 | drawingHistory.ts | `redo()` failure | unit | `onError` called; command stays on the redo stack | PASS |
| TC-97 | drawingHistory.ts | a new `run()` after `undo()` | unit | clears the stale redo branch (standard undo/redo semantics) | PASS |
| TC-98 | drawingHistory.ts | `undo()`/`redo()` on an empty stack; `clear()` | unit | no-op, no `onError`; `clear()` empties both stacks | PASS |
| TC-99 | keyboard.ts | `isTypingTarget` | unit | true for input/textarea/select/contentEditable; false otherwise | PASS |
| TC-100 | keyboard.ts | `matchShortcut` Ctrl+Z / Ctrl+Shift+Z / Cmd+Z | unit | undo / redo / undo (Cmd treated as Ctrl) | PASS |
| TC-101 | keyboard.ts | `matchShortcut` Alt+T/H/F | unit | trendline / horizontal_line / fibonacci | PASS |
| TC-102 | keyboard.ts | `matchShortcut` Esc, Delete/Backspace, 4 arrow keys | unit | cancel / delete / pan_* | PASS |
| TC-103 | keyboard.ts | `matchShortcut` unrelated key / Ctrl+Alt combo | unit | null (no false-positive match) | PASS |
| TC-104 | theme.ts | `resolveTheme`/`withAlpha` API unchanged for existing callers | review+build | ChartCanvas.tsx's only call site (`resolveTheme(el)`) still type-checks; diff shows pure addition, zero lines changed in the two existing functions | PASS |
| TC-105 | whole tree | `npx tsc -b` — full project type-check | build | zero errors in any file this task touched or added | PASS (see Verify below — whole tree is now zero-error; a transient, out-of-scope error in W0's in-progress `patternStyle.ts` was observed mid-session and is gone in the latest run, confirmed twice) |
| TC-106 | whole tree | `npx vite build` — production bundle | build | build succeeds | PASS |
| TC-107 | Research → Charts | existing `research-charts.spec.ts` full suite, with the edited `theme.ts` in place | e2e/regression | no new failures vs. the unmodified `theme.ts` | PASS (see Verify below — the one failing test fails identically before and after this task's change, isolated by a real A/B run) |
| TC-108 | Toolbar.tsx | props/callbacks match task item 2 (symbol, timeframe, chart-type, Indicators, undo/redo, layout name+save, full screen, settings, More) | review+build | every listed control present with the required disabled/reason states; `tsc -b` clean | PASS |
| TC-109 | DrawingRail.tsx | props/callbacks match task item 3 (tool groups, W1's 2 active tools + rest disabled "coming in W3", modifiers, compact "Draw" menu) | review+build | present; `tsc -b` clean | PASS |
| TC-110 | BottomBar.tsx | props/callbacks match task item 4 (range presets incl. 1D/5D disabled+reason, go-to-date, IST clock, ADJ disabled+reason, scale mode) | review+build | present; `tsc -b` clean | PASS |
| TC-111 | Sidebar.tsx | props/callbacks match task item 5 (collapsible, 5 tabs incl. disabled Watchlist, bottom-sheet fold, renders caller's per-tab children) | review+build | present; `tsc -b` clean | PASS |
| TC-112 | Legend.tsx | props/callbacks match task item 6 (symbol/timeframe/exchange/status slot, O H L C + change coloured, volume, one row per indicator w/ hover controls, collapse) | review+build | present; `tsc -b` clean | PASS |
| TC-113 | PaneControls.tsx | props/callbacks match task item 7 (move up/down, maximise/restore, collapse, remove, draggable divider) | review+build | present as `PaneControls` + `PaneDivider`; `tsc -b` clean | PASS |
| TC-114 | all 7 components | accessibility (task item 9): every button has a tooltip (`title`) and an `aria-label`; disabled items state why | grep audit | per-file button-vs-`aria-label`-vs-`title` counts all satisfy the invariant | PASS (see Verify below — real counts pasted, two real gaps found and fixed before this report) |

## Verify

**Pure-logic unit tests (TC-80..TC-103), real output:**
```
$ cd frontend-v5 && npx playwright test e2e/tests/charting-workspace-logic.spec.ts --project=desktop-chrome
...
  ✓  20 [desktop-chrome] › ... TC-98 undo()/redo() on an empty stack no-op without calling onError; clear() empties both stacks (6ms)
  ✓  21 [desktop-chrome] › ... TC-99 isTypingTarget: form controls and contentEditable are typing targets (3ms)
  ✓  22 [desktop-chrome] › ... TC-100 matchShortcut: Ctrl+Z / Ctrl+Shift+Z / Cmd+Z resolve to undo/redo (3ms)
  ✓  23 [desktop-chrome] › ... TC-101 matchShortcut: Alt+T/H/F resolve to the three reserved drawing tools (2ms)
  ✓  24 [desktop-chrome] › ... TC-102 matchShortcut: Escape, Delete/Backspace, and the four arrow keys (8ms)
  ✓  25 [desktop-chrome] › ... TC-103 matchShortcut: an unrelated key, or a Ctrl+Alt combination, matches nothing (6ms)

  25 passed (12.5s)
```
(25 = 24 logic test cases + 1 shared `auth-setup` project test that every spec in this testDir depends on. No
`page` fixture is used anywhere in the spec, so no browser was launched for the logic tests themselves.)

**TC-105 — `npx tsc -b` (forced full rebuild, cache cleared first), first run mid-session:**
```
$ rm -f tsconfig.tsbuildinfo tsconfig.node.tsbuildinfo && npx tsc -b --force
src/pages/Research/charts/patternStyle.ts(36,45): error TS2345: Argument of type 'number | ""' is not assignable to parameter of type 'number'.
  Type 'string' is not assignable to type 'number'.
src/pages/Research/charts/patternStyle.ts(36,82): error TS2362: The left-hand side of an arithmetic operation must be of type 'any', 'number', 'bigint' or an enum type.
```
`patternStyle.ts` is untracked, owned by the concurrent W0 task (see "Scope isolation" above) — not a file this
task created or edited. Grep-confirmed that error output contained **no** reference to any file under
`charts/workspace/` or to `charts/theme.ts`. Not this task's to fix — `patternStyle.ts` belongs to the parallel W0
agent's in-progress, uncommitted work per the task brief ("another agent is changing ... right now for W0 — do NOT
edit those files"); editing it would violate the file-scope boundary.

**Re-run after resuming from the disk-full pause, forced rebuild again:**
```
$ rm -f tsconfig.tsbuildinfo tsconfig.node.tsbuildinfo && npx tsc -b --force
EXIT:0
```
Zero output, zero errors, whole tree — W0 fixed `patternStyle.ts` concurrently in the same shared worktree in the
interim. Reconfirmed clean once more with a plain (non-forced) `npx tsc -b` after the `vite build` and Playwright
runs below (`EXIT:0` again). This worktree is shared with the live W0 agent, so re-running before finalizing this
report (rather than trusting the mid-session snapshot) was necessary to report the true current state.

**TC-106 — `npx vite build`:**
```
$ npx vite build
✓ 3416 modules transformed.
...
dist/assets/ChartsScreen-q78x_xD1.js  231.86 kB │ gzip:  71.76 kB
...
✓ built in 48.83s
```
(esbuild/rollup does not type-check, so this is a real but separate signal from TC-105 — both are reported, not
one substituted for the other.)

**TC-107 — existing Charts Playwright suite, with `theme.ts` changed, real output:**
```
$ npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome
...
  25 passed
  1 failed — "a trendline needs two clicks, persists through reload, and is visually distinct from pattern overlays"
    Expected: 1  Received: 0  (Timeout 5000ms exceeded while waiting on the predicate at line 399)
```
Re-run again after resuming from the disk-full pause (fresh process, nothing cached from the run above):
```
$ npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome
...
  1 failed
    [desktop-chrome] › e2e/tests/research-charts.spec.ts:382:3 › Charts — drawing tools (TC-23) › a trendline needs two clicks, persists through reload, and is visually distinct from pattern overlays
  25 passed (1.7m)
```
Same 25 passed / 1 failed, same single test, both times — consistent with the A/B isolation below (pre-existing,
not caused by this task).
A/B isolation (real re-run, not inferred): the identical failure was reproduced with `theme.ts` reverted byte-for-
byte to `git show HEAD:...theme.ts` (confirmed via `diff` after restoring), then reproduced again after restoring
this task's version:
```
$ git show HEAD:frontend-v5/src/pages/Research/charts/theme.ts > src/.../theme.ts   # temporary, for isolation only
$ npx playwright test ... -g "a trendline needs two clicks"
  1 failed — same "Expected: 1 Received: 0" at the same line
$ cp /tmp/theme_mine_backup.ts src/.../theme.ts && diff ... # restored, confirmed byte-identical
```
Also reproduced on 2 retries with the change in place (3/3 failures, not flaky-random). Conclusion: this is a
pre-existing mouse-click-timing issue in that one test, unrelated to this task's `theme.ts` change — `theme.ts`'s
two existing exports (`resolveTheme`, `withAlpha`) are byte-identical to `HEAD`; only new, additive exports
(`useAppTheme`, `resolveThemeName`, `AppTheme`, `ThemeName`) were added, and nothing yet imports them (W1b does
that wiring). UNVERIFIED beyond this isolation: the root cause of the pre-existing flake itself — out of this
task's scope to fix (it is in `research-charts.spec.ts` / `ChartCanvas.tsx`'s click handling, both W0/other-owned
files).

**TC-114 — accessibility grep audit, real output (after 2 real fixes made during this task — see below):**
```
$ for f in *.tsx; do btns=$(grep -o "<button" "$f"|wc -l); arias=$(grep -o "aria-label" "$f"|wc -l); titles=$(grep -o "title=" "$f"|wc -l); echo "$f buttons=$btns aria-label=$arias title=$titles"; done
BottomBar.tsx    buttons=3 aria-label=6 title=5
DrawingRail.tsx  buttons=3 aria-label=6 title=6
Legend.tsx       buttons=2 aria-label=2 title=3
MenuButton.tsx   buttons=2 aria-label=3 title=2
PaneControls.tsx buttons=1 aria-label=3 title=2
Sidebar.tsx      buttons=2 aria-label=3 title=2
Toolbar.tsx      buttons=7 aria-label=8 title=11
```
Note: several files show fewer literal `<button` JSX tags than actual rendered buttons because a shared
sub-renderer (e.g. `RailIcon` in DrawingRail, `PaneIcon` in PaneControls, the `MenuItem` list in MenuButton) is
called once per logical button but appears once in source — each such renderer was manually confirmed to set
`aria-label`/`title` unconditionally (both branches: enabled and disabled). Two real gaps were caught by this
audit and fixed before finalizing: (1) `MenuButton`'s and `DrawingRail`'s dropdown/flyout items had `title` only
on the disabled branch — patched to set it (and an explicit `aria-label`) on both branches; (2) `BottomBar`'s range
preset / ADJ / scale-mode buttons and `Sidebar`'s tab buttons had `title` but no explicit `aria-label` — patched.
Disabled-item reasons verified present: `RANGE_PRESETS` 1D/5D → "needs intraday data"; Toolbar timeframe 1W/1M →
"coming with W2 resampling"; Toolbar layout-save → same; DrawingRail's non-W1 tools → "coming in W3"; BottomBar ADJ
→ caller-supplied reason (raw series not exported, per §38.7); Sidebar Watchlist tab → "no user-editable watchlist
yet (P1)".

## Acceptance-criteria coverage (§38.13, task-scoped)

> Per the task instruction: "mapping AC 1-12 items that W1 covers (note which are completed only after the W1b
> wiring)." Phase ownership below follows §38.12's delivery-phase table, not a guess — several of AC1-12 are
> explicitly W2/W3 work, not W1.

| AC | What it needs | W1a status (this report) | Remaining for full AC verification |
|----|----------------|---------------------------|--------------------------------------|
| 1 | Chart fills window, no h-scroll at 1280×720/390px | Toolbar fixed at 56px, DrawingRail at 44px, both with a `compact` fold path; BottomBar/Sidebar built responsive-aware | W1b: wire into ChartsScreen's actual layout grid and measure real viewports |
| 2 | Crosshair → legend O/H/L/C/change/volume/indicator values | `Legend.tsx` renders all of these from `bar`/`previousClose`/`indicators` props (unit-level prop contract only — no live crosshair yet) | W1b: ChartCanvas crosshair-move handler → resolve bar → pass into Legend |
| 3 | Indicator instances/presets, catalog rejection with reason | Toolbar's "Indicators" button is only an entry-point callback | Not W1 — §38.12 places the indicator dialog + preset catalogue in W2 |
| 4 | Pane move/maximise/collapse/remove; order survives reload | `PaneControls`/`PaneDivider` built for the interactions | Interactions: W1b wiring into ChartCanvas panes. Reload persistence: not W1 — needs saved layouts, W2 |
| 5 | Drawing undo/redo; failed save rolls back with an error | `drawingHistory.ts` — 8/8 unit tests real-passing (TC-91..98) | W1b: build the 4 `DrawingCommand`s from `drawingsApi`, apply resolved values as the only state update |
| 6 | Magnet snaps to O/H/L/C; lock blocks edits; hide hides (no delete) | `magnet.ts` (5/5 unit tests, TC-80..84) resolves bar+snap; `DrawingRail` renders magnet/lock/hide toggles | W1b: ChartCanvas hit-testing calls `magnetSnap`/`nearestBar` during drag; lock/hide state enforcement in the primitive |
| 7 | Weekly bars match independent resample; trailing bar incomplete flag | — | Not W1 — §38.12 places weekly/monthly display in W2 (Toolbar's timeframe menu already ships 1W/1M as disabled-with-reason so the control doesn't reshuffle when W2 lands) |
| 8 | Range presets set visible range; 1D/5D disabled+reason | `ranges.ts` (6/6 unit tests, TC-85..90) + `BottomBar` renders `RANGE_PRESETS` directly (one source of truth for the disabled state) | W1b: `onSelectRange` → `chart.timeScale().setVisibleRange(resolveRange(...))` |
| 9 | Saved layout restores state in a new session | Toolbar shows "Unnamed" + a disabled Save button with the W2 reason | Not W1 — §38.12 places saved layouts in W2 |
| 10 | Replay bar-count check; sealed-window refusal | — | Not W1 — §38.12 places the bar-replay UI in W3 |
| 11 | Status badge/provenance drawer/Data view/attribution in both themes | Pre-existing (ChartsScreen/ChartCanvas, W0); `theme.ts#useAppTheme` is the new piece that keeps colours correct as the theme changes live | W1b: ChartCanvas re-applies `useAppTheme()`'s colours via `applyOptions` on change |
| 12 | Theme change re-themes an open chart without reload | `theme.ts#useAppTheme()` — MutationObserver on `data-theme` + `prefers-color-scheme` fallback, re-resolves `resolveTheme()` on every change | W1b: call `useAppTheme()` in ChartCanvas and push `colors` into the chart/series `applyOptions` |

## Inputs required from user

- none

## Verdict: PASS
<!-- Scoped to what W1a delivers: 7 new presentational components + shared MenuButton primitive + 4 pure logic
     modules + live-theme-following in theme.ts, all under frontend-v5/src/pages/Research/charts/workspace/ (plus
     the theme.ts edit). All 24 unit tests for the pure logic modules pass with real Playwright output; `tsc -b`
     is clean for every file this task touched (one pre-existing, out-of-scope error remains in a concurrent
     agent's uncommitted patternStyle.ts, isolated and reported above, not fixed here per the file-scope boundary);
     `vite build` succeeds; the existing Charts Playwright suite has no NEW failures from this task's theme.ts
     change (its one failure is reproduced identically with theme.ts reverted, so it predates this change). The
     §38.13 acceptance criteria themselves are NOT fully verified end-to-end here by design — W1a is a
     components-only phase; the AC table above states exactly what remains for W1b (ChartCanvas/ChartsScreen
     wiring) and what is out of W1's scope entirely (W2/W3 per §38.12). -->
