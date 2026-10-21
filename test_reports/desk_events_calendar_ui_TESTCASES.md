# Functionality Verification Report — Desk Events calendar (UI)

- **Branch:** feat/desk-events-calendar
- **Date:** 2026-10-21
- **Author:** Claude (frontend fork)
- **Changed areas:** frontend src: yes (tradingdesk/EventsTab.tsx, events-data.ts, TradingDesk.tsx, context.tsx, IntelTab.tsx) · backend: no (other fork)

## Summary
Desk Events calendar tab (frontend only). Verified against MOCKED API fixtures (labelled in the spec); the real backend route was built by another fork and is NOT exercised here. UNVERIFIED: live data on staging, real `percent` units of history fields, F&O universe flag.

## Test Cases (authored before implementation; results after run)
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Nav | `?tab=events` opens Events panel; More lists "Events calendar"; Intel has "Events calendar" button | e2e | panel `desk-panel-events` renders; both entry points navigate | PASS |
| TC-2 | Calendar | Month grid for mocked month: chips per day, >3 events folds to "VIEW ALL n", weekends narrow | e2e | chip counts match payload | PASS |
| TC-3 | Tint | Past day with index close >0 mint / <0 danger tint; holiday shows description | e2e | data-tone attrs match payload | PASS |
| TC-4 | Day panel | Click VIEW ALL opens day panel, search filters, prev/next moves between events | e2e | list narrowed; position "k / n" | PASS |
| TC-5 | Filters | Type chip hides events of that type; sector multi-select; universe change refetches with universe= param | e2e | request URL carries universe=n50 | PASS |
| TC-6 | History | Event panel calls /history with symbol+type; shows avg/min/max, "based on N occurrences since DATE", past table | e2e | values equal payload | PASS |
| TC-7 | History empty | n=0 -> says no price history, no dots | edge | text shown | PASS |
| TC-8 | Failure | calendar 502 -> error state with retry, no fake data | failure | error text; no chips | PASS |
| TC-9 | Macro | MACRO switch count "—", "Macro calendar source not connected yet" | e2e | text shown, no events | PASS |
| TC-10 | Gaps | `gaps[]` rendered | e2e | text visible | PASS |
| TC-11 | Timeline | Timeline view expands a row in place | e2e | history block appears | PASS |
| TC-12 | Phone | 390px: week strip, day agenda, sheet; no horizontal page scroll | e2e | scrollWidth<=clientWidth | PASS |
| TC-13 | Types | `tsc --noEmit` clean | unit | no errors | PASS |

## Real output (docker, playwright:v1.47.0-jammy, Chromium build 1223, production build, mocked APIs)
```
tsc exit 0
build exit 0
copilot-app-desk-events.spec.ts: 10 passed (8.3s)   [first run]
npx playwright test --config pw.copilot-app.config.ts copilot-app-desk   [events spec + existing desk specs, after panel-overlay change and More-list label update]
  2 skipped
  160 passed (2.2m)
```
Existing spec copilot-app-desk.spec.ts MORE_ITEMS/MORE_LABELS updated for the new More entry (it failed once before that, 1 failed / 159 passed).
Screenshots (git-ignored): frontend-v5/e2e/screenshots/desk-events/*.png, viewed.

## Verdict
## Verdict: PASS
