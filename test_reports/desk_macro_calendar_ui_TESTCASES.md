# Functionality Verification Report — Desk Events calendar: Macro releases (UI)

- **Branch:** feat/desk-macro-calendar
- **Date:** 2026-10-21
- **Author:** Claude (macro frontend fork)
- **Environment:** mocked API (Playwright, production build, docker). NOT run against staging or the real backend: the backend routes are built concurrently and are not deployed.
- **Changed areas:** backend routes/services: no (frontend fork) · frontend src: yes (`tradingdesk/EventsTab.tsx`, `tradingdesk/events-data.ts`)

## Summary
The Macro switch in the desk Events tab becomes a working view on `GET /api/markets/macro-calendar` and `/history`:
country (India, US) and impact (High, Medium, Low) chips, calendar and timeline views with short-name chips, a day panel,
an event panel with PREVIOUS / ESTIMATE / ACTUAL tiles and Nifty 50 price behaviour for past releases, and a phone
week strip with a sheet. Free sources carry no consensus, so ESTIMATE is shown as "—" with a note and the surprise tag is hidden unless
both estimate and actual exist.

## Test Cases (authored before implementation)

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| M-1 | switch | Macro switch shows the month's macro count from the API (not "—"); stock count unchanged | e2e | `MACRO 4` style count, headline names high-impact releases | PASS |
| M-2 | grid | Macro calendar: chips show the short name and country; busy day folds into VIEW ALL; Nifty tint/holiday stay | e2e | chip text `CPI`, `US`; `VIEW ALL n →` | PASS |
| M-3 | filters | Country chip off hides that country's events; impact chip off hides that impact; query string unchanged (all selected, filtered on the client) | e2e | counts change, no refetch loop | PASS |
| M-4 | panel | Event with actual: PREVIOUS / ESTIMATE / ACTUAL tiles; ESTIMATE is "—" with "no free consensus source"; no surprise tag | e2e | tiles and note visible, `events-macro-surprise` absent | PASS |
| M-5 | surprise | A fixture with both estimate and actual shows the tag and signed difference | e2e | `ABOVE ESTIMATE`, `+0.2 vs estimate` (unit-less PMI) | PASS |
| M-6 | future | Upcoming release: ACTUAL "—" with "DUE <date> · <time>" | e2e | text present | PASS |
| M-7 | history | Macro history: n, coverage_from, avg/min/max strips on Nifty 50, past-release table with actual; own-move ring from the first Nifty session after the release | e2e | figures equal the payload | PASS |
| M-8 | history edge | n = 0 history says there is nothing to plot; history 500 shows error + Retry | e2e/failure | text present | PASS |
| M-9 | india gap | India has no events and a gap names it: the India chip carries the reason; gaps list shown | e2e/edge | `events-country-gap` text | PASS |
| M-10 | failure | Macro calendar 502: error with Retry, no chips | e2e/failure | `events-error` | PASS |
| M-11 | timeline | Macro timeline rows show `HH:MM IST · name · country · period · actual/estimate`, expand in place | e2e | row text, expanded panel | PASS |
| M-12 | phone | Macro on 390px: week strip dots in impact colours, agenda rows, sheet with tiles, no sideways scroll | e2e | sheet visible, scrollWidth ≤ clientWidth | PASS |
| M-13 | regression | Existing stock-mode specs (TC-1…TC-12) still pass; TC-9 ("source pending") is removed: superseded by M-1…M-12 | e2e | all pass | PASS |
| M-T | types | `tsc --noEmit` clean | unit | exit 0 | PASS |
| M-14 | contract | IST date (`date_ist`) places the chip; the first Nifty session after an after-close release is its own-move ring; no ring when that close is not on file | e2e/edge | chip in the 31 Oct cell; ring absent | PASS |

## API / Endpoint Tests (staging)
Not applicable to this fork (frontend only). The backend fork owns them. UNVERIFIED here: the live contract. The client was checked by reading the
backend fork's uncommitted `backend/routes/macro_calendar.py` and `daas_api/routers/desk_macro.py` in the same worktree (fields `code`, `date_ist`,
`time_basis`, numeric `previous`/`actual`, `estimate` always null, history keyed by `code`, first-session reaction); no HTTP call was made.

## UI / Playwright Tests
Command (docker, production build served by `vite preview`, `--network none`, every /api/* route-mocked):
`bash /runpw.sh "copilot-app-desk-macro|copilot-app-desk-events"` (build + preview + `npx playwright test`)

```
Running 21 tests using 3 workers
  ✓ copilot-app-desk-events.spec.ts  TC-1, TC-2/3/10, TC-4, TC-5, TC-6, TC-7, TC-8, TC-11, TC-12   (9 stock-mode tests)
  ✓ copilot-app-desk-macro.spec.ts   M-1/M-2, M-3, M-4/M-7, M-5, M-6, M-8, M-9, M-10, M-11, M-13, M-14, M-12 (phone)  (12 macro tests)
  21 passed (15.3s)
```
Earlier, before the last contract adaptation (IST date, per-event time basis, reaction-session ring, strip labels), the whole desk spec set
(`copilot-app-desk*.spec.ts`, 321 tests) ran: `305 passed`, `16 skipped` (skips are in other desk specs, e.g. strategy-graphs), 0 failed.
That 321-test run was NOT repeated after the final edit; the 21 events+macro specs and tsc were.

`tsc --noEmit -p tsconfig.json` (docker): `tsc_exit=0`.

Screenshots viewed (git-ignored, `frontend-v5/e2e/screenshots/desk-events/`): macro-desktop-calendar, macro-desktop-panel, macro-desktop-timeline,
macro-phone-agenda, macro-phone-sheet. They show real layout with mocked values.

## Data Correctness (staging)
Not done: this fork has no real macro data to read.

## Gaps / UNVERIFIED
- Live backend contract and real data (needs the backend deployed to staging and a session token).
- Investor wording, light mode, and month navigation beyond October fixtures are not tested for macro.
- India values: the backend says India CPI/IIP/GDP/PLFS show dates only, so their ACTUAL tile shows "—" ("NOT IN SOURCE YET" for past dates).

## Verdict: IN PROGRESS (UI verified on mocks only; not PASS against the real API)


## Inputs required from user
none
