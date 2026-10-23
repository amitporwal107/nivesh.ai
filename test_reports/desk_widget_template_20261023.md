# Functionality Verification Report — Smart Trading Desk widget template (collapse + resize)

- **Branch:** feat/desk-widget-template (from origin/dev 74a20627)
- **Date:** 2026-10-23
- **Author:** Claude (full-stack + design engineer)
- **Environment:** local production build (vite build, VITE_BASE=/v5/) served by `vite preview`, every /api route-mocked (MOCK — not real data); NOT staging
- **Changed areas:** backend: no · frontend src: yes

## Summary
One `<Widget>` template (tradingdesk/widget.tsx) replaces the hand-rolled `cp-card` + four divergent `CardHead` implementations. Every module card on all desk tabs (Overview, Scanner, Intel, Chart, Portfolio, Smart Money, Events, F&O lab, More; desktop and phone variants) now has the same header, a collapse chevron and a corner resize handle. Collapsed state and size persist per widget id in localStorage. Stat tiles, KPI tiles, list-row cards, the chat dock and strategy tiles are deliberately not widgets.

## Test Cases (authored: spec copilot-app-desk-widgets.spec.ts)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | all tabs | every `section[data-widget]` has a toggle + resize handle, ids unique per tab | e2e | none missing/duplicate, >8 widgets | PASS |
| TC-2 | collapse | collapse hides body, keeps header, survives reload, expand clears storage | e2e | as stated | PASS |
| TC-3 | header control | sector period switch works and does not toggle | e2e | pressed, still expanded | PASS |
| TC-4 | resize | keyboard arrows change h/w, persist across reload, Escape resets | e2e | as stated | PASS |
| TC-5 | resize | corner drag resizes, double-click resets | e2e | as stated | PASS (after fixing a spec bug: handle off-screen) |
| TC-6 | edge | cannot go below 220x96 or wider than its column | edge | clamped | PASS |
| TC-7 | failure | localStorage throws: widget renders, collapses for the visit | failure | no crash | PASS |
| TC-8 | phone | 390px: collapse works, no sideways scroll | e2e | as stated | PASS |
| REG | existing desk specs | all `copilot-app-desk*` specs | regression | no new failures vs origin/dev | PASS (see below) |

## UI / Playwright Tests
Command (docker, playwright v1.47 image, chromium build 1223): `tsc --noEmit`, `vite build`, `vite preview`, `npx playwright test --config pw.copilot-app.config.ts copilot-app-desk`

Real output, final run on this branch:
```
tsc exit=0
✓ built in 27.36s
  32 failed
    [copilot-app] › e2e/tests/copilot-app-desk-smart-money.spec.ts:247:3 › ... TC-F3: the disclosure date is shown, not the compute date
  (+31 in copilot-app-desk-strategy-graphs.spec.ts, filtered from this listing)
  16 skipped
  482 passed (6.8m)
```
Baseline, untouched origin/dev, same build and config: strategy-graphs `31 failed`; smart-money TC-F3 fails (`1 failed`). So the 32 failures are identical to the baseline set and pre-existing (not caused by this change).

First run on this branch had 5 real regressions, all fixed: scanner detail ×2 (my toggle testId collided with existing `-toggle` selectors → renamed `-collapse`), lab TC-30 (title lost its flex gap → "NIFTY 27"), portfolio §7 (test read the title's parent as the header bar; now grandparent), and my own TC-5.

## Data Correctness
Not applicable: no data path changed; mocked APIs only.

## UNVERIFIED
- Not run against staging / real data / a real session.
- No visual review (screenshots) done: day-card titles on the Events tab now render in the standard eyebrow style, not the old display font; the 31+1 baseline failures were not investigated.
- Width-resize leaves empty space beside a shrunk card (no reflow); intended, not user-confirmed.
- Resized/collapsed state is per browser, not synced.

## Inputs required from user
none

## Verdict: PASS
(scoped to the mocked local build above; staging and visual review remain UNVERIFIED)
