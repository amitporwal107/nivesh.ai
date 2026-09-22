# Functionality Verification Report — Charting W0: patterns on the chart (§38.15)

- **Branch:** fix/charting-symbols-contract (worktree `/app/.claude/worktrees/charting`)
- **Date:** 2026-09-23
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER) — continuing a prior agent's session that was interrupted
  twice by host restarts; this report replaces and corrects `test_reports/charting_w0_patterns_on_chart.md`'s prior
  draft (see "Corrections to the prior draft" below — that draft's PASS claims were written while the pattern
  primitive was never actually attached to the chart, and while the priority-defect test (TC-23) was already failing).
- **Environment:** local Playwright (mocked API fixtures). Staging spec extended but NOT run this session (needs a
  session token — `STAGING_SESSION_FILE`, see `staging-research-charts.spec.ts`).
- **Changed areas:** backend routes/services: no · frontend src: yes (`frontend-v5/src/pages/Research/charts/`)

## Summary
Finishes W0 "patterns on the chart" (docs/charting.md §38.15, AC18–24) on the existing Research → Charts screen:
every detected chart pattern is auto-drawn over its own dates (rectangle box / HH-HL polyline / breakout+invalidation
segments / pivot+event markers / a "Known" marker) by `PatternsPrimitive` (`patternLayer.ts`), styled by status
(`patternStyle.ts`); filter chips (All/Active/Confirmed/Failed/Invalidated + per-family); click-to-select from either
a chart shape or a list row (zoom-to-window, dim-others, Previous/Next through overlaps); an on-chart empty state; a
§20.3 pattern-details card (`PatternDetails.tsx`) with rules + event timeline; near-duplicate S/R grouping into bands
with click-to-list; and a nearest-level readout. This session found and fixed two real defects left by the
interrupted prior session (see below), then completed verification.

## Defects found and fixed this session

1. **Pattern primitive was never attached to the chart (functional gap, not just untested).**
   `ChartCanvas.tsx` created `patternsPrimitive` but its `candle.attachPrimitive(patternsPrimitive)` call was
   commented out (`// candle.attachPrimitive(patternsPrimitive); // DEBUG: temporarily disabled`). Because
   `ISeriesPrimitiveBase.attached()` was consequently never invoked, `patternsPrimitive.chart`/`.series` stayed
   `null` forever, so (a) `draw()` was never part of the chart's render pipeline — patterns were computed but never
   actually painted on the canvas — and (b) `hitTestPatterns()` always returned `[]`, so clicking a pattern's shape
   on the chart could never select it. The prior draft report's own "Known limitations" section had noted "canvas
   pixels are not independently sampled" as a general convention — it did not know this specific path was fully
   dead. **Fixed** by re-enabling the `attachPrimitive` call and removing the stray `console.log("DEBUG
   clickHandler fired", …)` left in the same file's click handler. Verified for real, not just by re-enabling:
   `research-charts.spec.ts` TC-74/76/83 performs an actual `page.mouse.click()` at a real canvas pixel and requires
   a genuine two-pattern overlap hit (asserts `chart-pattern-next` is visible) — this is only satisfiable through
   the attached primitive's real `series.priceToCoordinate()` hit-testing, and it now passes (see run below).

2. **Priority defect, TC-23 ("a trendline needs two clicks…") — root cause and fix.**
   Root cause (found by instrumenting native DOM events + `getBoundingClientRect()` in a scratch spec, since
   deleted): W0 added a "Nearest level" readout (§38.15 item 9) inline in the header row that also holds the
   symbol name, status chip and Fit/Full screen/Data view buttons. At the drawing-tools describe block's fixed
   1280×800 viewport, that extra content made the row wrap onto two lines, which pushed `chart-canvas`'s
   `getBoundingClientRect().top` down to **544.5px** (measured). The test's existing second click at
   `box.height * 0.6` (≈286.8px into the canvas) then landed at page-y ≈ 831, **below the 800px viewport** — the
   native `click` event's target was `<html>` (empty page area), not the chart's `<canvas>`, so
   `chart.subscribeClick`'s handler never fired for that point and 0 drawings were ever posted. Confirmed via a
   native-event listener: the first click showed `NATIVE click … CANVAS`, the second `NATIVE click … HTML`.
   Fixed two ways:
   - **App fix** (`ChartsScreen.tsx`): moved the nearest-level readout out of the shared header row into its own
     dedicated row. This is a real, independent correctness fix — before it, that header row would non-deterministically
     wrap depending on symbol-name length, status text and viewport width, which is a genuine layout bug regardless
     of this test.
   - **Test fix** (`research-charts.spec.ts`, TC-23): the second click's y-fraction changed from 0.6 to 0.5. Even
     with the app fix above, canvas.top only drops to ~537.5px (the readout still legitimately costs one row of
     height — moving it doesn't remove it), so 0.6×478 ≈ 287 would still land at ≈824.5, over the 800px fold. 0.5
     lands at ≈776.5 — comfortably inside the fold — and stays clearly distinct from the first click's y=0.35.
     Documented inline in the test with the exact reasoning.
   Re-verified: `research-charts.spec.ts:382` now passes (see run below), along with all other tests in the same
   describe block (horizontal line, Escape-cancels, select+Delete).

3. **`staging-research-charts.spec.ts` (not run this session, no token) — a correctness gap fixed by inspection.**
   TC-15's S/R assertion compared `data-rendered-levels` (the number of lines `ChartCanvas.tsx` actually draws,
   which since AC24 is the GROUPED **band** count) against the raw served S/R **record** count. On real staging
   data where `atr_14` groups near-duplicate levels, this assertion would fail even though the app is behaving
   correctly. Fixed by reimplementing the same 0.35×ATR chain-grouping locally in the test (not imported from
   `contract.ts`, to avoid depending on the `@/...` alias resolution the Playwright/e2e module loader does not
   configure) and asserting against the computed band count instead. **UNVERIFIED against live staging** — no
   `STAGING_SESSION_FILE` available this session; `--list` confirms the file still parses/loads correctly and
   `tsc -b` is clean.

4. Deleted the stray `frontend-v5/e2e/tests/zz-debug-trendline.spec.ts` left on disk by the interrupted prior
   session (used transiently during defect #2's root-cause investigation, then removed).

## Test Cases
> One row per case. TC-70 upward, matching the actual test titles in `research-charts.spec.ts`'s
> `"Charts — W0 patterns on the chart (§38.15, TC-70..87)"` describe block (built on the `PATTERNQA` fixture: 6
> chart patterns — 2 overlapping RECTANGLEs, 1 confirmed HH_HL, 1 forming RECTANGLE, 1 FAILED RECTANGLE, 1
> INVALIDATED HH_HL — plus 4 SUPPORT_RESISTANCE records forming 2 near-duplicate bands at `atr_14`=8.0).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-70 | AC18 | every chart pattern auto-drawn, default filter All | e2e | `chart-pattern-filter-all` pressed; 6 rows; `data-rendered-patterns`=6 | PASS |
| TC-71 | item 4 | filter chips narrow list + drawn count | e2e | Confirmed→3, Failed→1 (with the right pattern id), Invalidated→1, Active→4, family HH_HL→2, back to All→6 | PASS |
| TC-72/84 | AC20, §20.3 | row click opens details, rules, events | e2e | all 15 §20.3 fields present with correct values; rule click opens provenance with PASS; event row shows date+type; switching pattern replaces fields; a pattern with no events shows `chart-pattern-events-empty` | PASS |
| TC-73 | AC20 | selecting a pattern zooms | e2e | visible-range end moves off the full-range end, into the FAILED pattern's own formation+event window | PASS |
| TC-75 | AC20 | Esc / close button clear selection | e2e | `chart-pattern-details` disappears on both Escape and the close button | PASS |
| TC-77 | AC21 | 4 distinct status categories | e2e | confirmed/forming/failed/invalidated `data-category` values differ; manual-drawings namespace stays empty (0 `chart-drawing-row-*`) | PASS |
| TC-78 | AC22 | symbol with no chart patterns | e2e | on-chart text exactly "No chart patterns detected — checked: support/resistance, rectangle, higher-high/higher-low" (TCS fixture) | PASS |
| TC-79 | AC23 | "Known" marker date | e2e | equals `max(pivot confirmed_date)` per pattern (3 patterns checked against hand-computed expected dates) | PASS |
| TC-80/81 | AC24, item 8 | S/R near-duplicate grouping | e2e | 4 raw records (490/491.5 support, 512/513 resistance; ATR 8.0, tolerance 2.8) → 2 bands; clicking a band lists exactly its 2 records | PASS |
| TC-81b | item 8 regression | RELIANCE/TCS S/R unaffected | e2e | band count stays 2/2 with the new `atr_14` series served (tolerances 7 and 3.5, both well under the 50/5 level gaps) | PASS |
| TC-82 | item 9 | nearest-level readout | e2e | role=Resistance, price ₹505.00, distance ₹0.00, 0.00 ATR (engineered exact-match case) | PASS |
| TC-74/76/83 | AC20, item 5 | **real pixel click** selects, overlap Previous/Next, hover | e2e | mouse-move over a shape shows the hover tooltip; a real click inside both overlapping RECTANGLEs opens details AND shows Previous/Next (proves a genuine multi-hit, not a soft skip); Next changes the shown fields, Prev restores them | PASS — **this is the test that would have failed under defect #1** (see above) |
| TC-85 | regression | full local suite unaffected | e2e | every pre-existing test (access/surface/S-R/status/indicators/drawing-tools/data-view/mobile, TC-15..29 equivalents) still passes alongside the new W0 tests | PASS (38/38, see run below) |
| TC-86 | build | typecheck + bundle | build | `tsc -b` clean; `vite build` succeeds; `ChartsScreen` stays a separate lazy chunk | PASS |
| TC-87 | **priority defect** | TC-23 trendline two clicks | e2e | root-caused and fixed (see "Defects found and fixed" #2); `research-charts.spec.ts:382` passes | PASS |
| TC-88 | staging spec correctness | S/R band-count assertion fixed to match grouped (not raw) count | code review + `--list` | file still parses/loads; `tsc -b` clean | PASS (code-level) — **staging run itself NOT RUN, no session token** |

## UI / Playwright Tests

- **Spec:** `frontend-v5/e2e/tests/research-charts.spec.ts` (full file, including the new TC-70..87 block)
  - Command: `npx playwright test e2e/tests/research-charts.spec.ts --project=desktop-chrome --reporter=list`
  - Real output (this session, after all fixes above):
    ```
    Running 38 tests using 2 workers
      ✓   1 [auth-setup] › e2e/auth.setup.ts:23:1 › auth setup — inject dark-theme localStorage (3.4s)
      ✓   2 … Charts — access › TC-20 a 403 from the API shows the explicit not-enabled state, no crash, no canvas (2.3s)
      ✓   3 … Charts — access › without the charting feature the rail item is absent (2.6s)
      ✓   4 … Charts — access › a 503 from the API shows the unavailable state with a retry, no crash (2.3s)
      ✓   5 … TC-15 picking a symbol renders candles + volume from the API (non-empty canvas) (2.6s)
      ✓   6 … TC-16 fixture:true shows the loud synthetic-data banner (2.2s)
      ✓   7 … TC-21 TradingView attribution is visible in the chart area (2.2s)
      ✓   8 … TC-18 weekly/monthly are visibly disabled with the spec G-6 reason; daily works (2.2s)
      ✓   9 … empty patterns render cleanly (TCS — detectors not built yet) (2.4s)
      ✓  10 … a pattern's levels, rules and scores render, with the 'not a probability' label (2.5s)
      ✓  11 … TC-25 the Patterns panel lists chart patterns only — no support/resistance rows (2.0s)
      ✓  12 … TC-26 a symbol with only levels shows an empty Patterns panel (2.4s)
      ✓  13 … TC-27 Support & resistance is ticked by default, draws every level (both kinds), and untick removes them (2.6s)
      ✓  14 … TC-28 labels come from status: formed is not confirmed (2.2s)
      ✓  15 … PIT_UNVERIFIED outranks PARTIAL, and the drawer shows both raw fields (2.2s)
      ✓  16 … VALID shows when both fields are clean (2.1s)
      ✓  17 … a price-pane overlay toggles without adding a pane; a dedicated-pane indicator adds/removes one (2.6s)
      ✓  18 … multi-output indicators draw every plotted field, and only those (bollinger bands, macd signal + hist) (2.4s)
      ✓  19 … provenance drawers format nested values — no [object Object] (files list, multi-output warmup) (2.4s)
      ✓  20 … an indicator's info button opens its provenance (warmup, calculation version) (2.2s)
      ✓  21 … a horizontal line is placed with one click and listed (2.4s)
      ✓  23 … Escape cancels a pending trendline's first anchor (2.5s)
      ✓  22 … a trendline needs two clicks, persists through reload, and is visually distinct from pattern overlays (4.7s)
      ✓  24 … select + Delete removes a drawing via the API (2.8s)
      ✓  25 … a keyboard-reachable data-view table lists visible bars and patterns (2.6s)
      ✓  26 … the mobile tab bar carries Charts and the surface renders without horizontal scroll (2.0s)
      ✓  27 … TC-70 AC18: every chart pattern is auto-drawn with no click; default filter is All (2.2s)
      ✓  28 … TC-71 item 4: filter chips narrow both the list and the drawn count (3.0s)
      ✓  29 … TC-72/84 AC20 + §20.3: selecting a row opens the details card, rules and event timeline (2.8s)
      ✓  30 … TC-73 AC20: selecting a pattern zooms the visible range to its own window (2.5s)
      ✓  31 … TC-75 AC20: Esc and an empty-chart click clear the pattern selection (3.3s)
      ✓  32 … TC-77 AC21: forming, confirmed, failed and invalidated read as 4 distinct categories (2.8s)
      ✓  33 … TC-78 AC22: a symbol with no chart patterns says so on the chart itself (2.9s)
      ✓  34 … TC-79 AC23: the 'Known' marker date is on/after every pivot's own confirmation date (2.6s)
      ✓  35 … TC-80/81 AC24 + item 8: near-duplicate S/R records group into bands, click lists every record (2.8s)
      ✓  36 … TC-81b item 8 regression: RELIANCE/TCS S/R band counts are unaffected by the new atr_14 series (2.5s)
      ✓  37 … TC-82 item 9: nearest-level readout — an exact-match case (distance ₹0.00 / 0.00 ATR) (2.6s)
      ✓  38 … TC-74/76/83 AC20 + item 5: click-on-chart selects, overlap Previous/Next, hover tooltip (2.7s)
      38 passed (54.7s)
    ```
  - Result: **PASS (38/38, including TC-23 — the priority defect)**

- **Staging spec:** `frontend-v5/e2e/tests/staging-research-charts.spec.ts`
  - Command: `npx playwright test e2e/tests/staging-research-charts.spec.ts --project=desktop-chrome --list`
  - Output: `Total: 5 tests in 2 files` (lists cleanly; confirms the fix in defect #3 above did not break parsing/loading)
  - Result: listing PASS; **execution NOT RUN — `STAGING_SESSION_FILE` not set this session**

## Build

- Command: `npx tsc -b`
  - Output: (empty — clean exit)
  - Result: PASS
- Command: `npx vite build`
  - Output (tail):
    ```
    dist/assets/ChartsScreen-ABl3GC8z.js                 232.46 kB │ gzip:  71.99 kB │ map:   665.05 kB
    ...
    ✓ built in 19.55s
    ```
  - `ChartsScreen` is still its own lazy chunk (`ChartsScreen-ABl3GC8z.js`), separate from the main bundle — code-split
    behaviour unchanged.
  - Result: PASS

## Data Correctness (fixtures, not live)
No backend/DB was touched this session (`backend/` and `research/` are out of scope per this task's instructions —
their pending, unrelated diffs from other in-flight work were left untouched). All W0 test data is in
`frontend-v5/e2e/fixtures/research-chart-*-PATTERNQA.json` (isolated per-test via a `symbols` override, never the
shared default RELIANCE/TCS fixtures) plus an additive `atr_14` series on the existing RELIANCE/TCS indicator
fixtures. No existing fixture record was edited or removed (confirmed by TC-81b / TC-85 passing unmodified).

## Files changed this session
- `frontend-v5/src/pages/Research/charts/ChartCanvas.tsx` — re-enabled `candle.attachPrimitive(patternsPrimitive)`;
  removed a leftover debug `console.log` in the click handler.
- `frontend-v5/src/pages/Research/charts/ChartsScreen.tsx` — moved the "Nearest level" readout (§38.15 item 9) into
  its own row instead of sharing the symbol/status header line, fixing an unpredictable layout wrap.
- `frontend-v5/e2e/tests/research-charts.spec.ts` — TC-23's second trendline click: `box.height * 0.6` →
  `box.height * 0.5`, with an inline comment explaining exactly why (see defect #2).
- `frontend-v5/e2e/tests/staging-research-charts.spec.ts` — TC-15's S/R assertion now compares against a locally
  computed grouped-band count (matching `contract.ts` `groupSrBands`'s 0.35×ATR rule) instead of the raw served
  record count; also captures the `indicators` response in `openCharts()`.
- `frontend-v5/e2e/tests/zz-debug-trendline.spec.ts` — deleted (stray scratch file from root-causing defect #2).
- `test_reports/charting_w0_patterns_on_chart.md` — this report (replaces the prior, inaccurate draft).

Unmodified this session (inherited from the prior agent, already correct on inspection — see code review notes in
"Summary" above): `frontend-v5/src/pages/Research/charts/{contract.ts, PatternDetails.tsx, patternLayer.ts,
patternStyle.ts, DataView.tsx}`, `frontend-v5/e2e/fixtures/research-chart-*-PATTERNQA.json`. Not touched (belongs to
the parallel W1a package per this task's instructions): `charts/theme.ts`, `charts/workspace/`.

## Inputs required from user
- A staging session token (`STAGING_SESSION_FILE`) to actually run `staging-research-charts.spec.ts` (TC-15/16/17/21,
  TC-18, TC-19, TC-23) against real data — including the newly-fixed S/R band-count assertion (defect #3), which is
  code-reviewed and parses/typechecks but has not executed against a live payload.

## Known limitations / NEEDS-INPUT (carried over, still true)
- **AC19 exact shape geometry** is verified at the data level (TC-73/TC-72's own-window checks) plus code review of
  `patternLayer.ts` (`toXY` calls use each pattern's own `formation_start`/`formation_end`/pivot dates, never a
  chart-wide line), and — new this session — by one REAL pixel click in TC-74/76/83 that must land inside a specific
  overlapping pair of boxes to pass. Full box/polyline boundaries are not exhaustively pixel-sampled beyond that one
  point; the `data-rendered-patterns`/`data-known-markers` hooks exist for the rest, per this codebase's convention
  that a `<canvas>` cannot otherwise be inspected.
- **Filter persistence "saved with the layout"** (§38.15) is out of W0 scope — no saved-layout mechanism exists yet
  anywhere on this screen; `patternFilter` resets to "All" per symbol switch, consistent with the rest of the
  screen's existing behaviour (indicators, drawings, etc. all reset the same way already).
- **ATR / relative_volume "at the last bar"** convention (not point-in-time-at-formation) — documented in
  `contract.ts` (`lastIndicatorValue`) and `PatternDetails.tsx`; used for the S/R grouping tolerance, the
  nearest-level ATR distance, and the §20.3 ATR/relative_volume fields, since the snapshot carries no per-pattern-date
  indicator value.
- **pattern_version** (§20.3) is shown as the run's `engine_version` — no dedicated per-pattern version field exists
  in the snapshot.
- No 1–5 strength score anywhere (confirmed by grep — not in the data, per design-1a-reference.md §31–38). No
  buy/sell/target wording anywhere (confirmed by grep — only incidental HTML `target="_blank"` attributes exist).

## Verdict: PASS
