# Functionality Verification Report — Desk events calendar (stock events) backend

- **Branch:** feat/desk-events-calendar (worktree /home/deploy/nivesh-desk-events, off feat/trading-desk-backend)
- **Date:** 2026-10-21
- **Author:** Claude (full-stack, backend fork)
- **Environment:** unit tests local; data checks read-only against staging warehouse (nidp_staging) via ~/.config/nivesh/nidp-psql.sh
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
DaaS `GET /v1/desk/events-calendar` and `/v1/desk/events-calendar/history` (nidp/services/daas_api/routers/desk_events.py) and the app routes `GET /api/markets/events-calendar` and `/history` (routes/events_calendar.py). Stock events only (macro is a separate, unbuilt source). Real tables: nidp.event_calendar, nidp.corporate_actions, nidp.nse_holidays, nidp.index_eod, nidp.index_constituents, nidp.security_reference_daily, nidp.prices_eod.

## Test Cases (authored before implementation)

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | return math | event_day = close/prev_close−1 on the event session; d1 = close(t+1)/close(t)−1; w1 = close(t+5)/close(t)−1, 2 dp | unit | hand-worked numbers match | PASS (unit) |
| TC-2 | return math | event date is not a session (weekend) → first session on/after it; too few later bars → d1/w1 null, never 0 | edge | null, not 0 | PASS (unit) |
| TC-3 | return math | occurrences with no price coverage (before first price) are dropped; `n` counts only covered; `coverage_from` = first price date | edge | n excludes them | PASS (unit) |
| TC-4 | stats | avg/min/max over non-null values only; empty → nulls | unit | | PASS (unit) |
| TC-5 | merge | board_meeting row same symbol+date as a RESULTS row is dropped; duplicate calendar rows (differing period) collapse | unit | one row | PASS (unit) |
| TC-6 | merge | calendar dividend row (board meeting date) and CA dividend (ex-date) stay separate: timings `board` vs `ex`; CA record date is its own `rec` row | unit | 3 rows | PASS (unit) |
| TC-7 | merge | INTEREST_PAYMENT / DISTRIBUTION / OTHER actions and event_type 'other' are excluded and named in `gaps` | unit | | PASS (unit) |
| TC-8 | month bounds | month=2026-10 → 2026-10-01..2026-10-31; December and February (leap/non-leap) correct | unit | | PASS (unit) |
| TC-9 | params | bad month (2026-13, "abc") → 400; bad universe → 400; bad type → 400 | failure | 400 | PASS (unit) |
| TC-10 | universe | n50 only keeps Nifty 50; fno keeps security_reference_daily.fno_eligible; fno source empty → `universe.fno` null on rows, filter returns none, gap stated | unit | | PASS (unit) |
| TC-11 | holidays | CM holidays in month; description with `*` is flagged `muhurat: true` | unit | | PASS (unit) |
| TC-12 | index closes | Nifty 50 pct_change per day in month | unit | | PASS (unit) |
| TC-13 | app route | forwards month/universe unchanged; history forwards symbol/type uppercase; 502 upstream_unavailable on DaasError / non-200 / not configured; signed-out → 401 | unit | | PASS (unit) |
| TC-14 | data | real staging October 2026: counts per type; DaaS SQL runs; Muhurat 2026-11-08 present | data | | PASS (data) |
| TC-15 | HTTP on staging | endpoints through staging | api | | UNVERIFIED (see Verdict) |

## Evidence

### pytest (throwaway container from nivesh/backend:staging, tree mounted read-only)
```
nidp/tests/services/test_daas_desk_events.py + tests/test_events_calendar_routes.py  → 56 passed, 1 warning in 6.98s
neighbours: test_daas_desk_market.py + test_desk_market_routes.py                   → 65 passed, 1 warning in 7.27s
import check: DaaS app routes ['/v1/desk/events-calendar', '/v1/desk/events-calendar/history'];
              server.app routes ['/api/markets/events-calendar', '/api/markets/events-calendar/history']
```

### Data correctness (read-only SQL on the staging warehouse, 2026-10-21; the router's SQL, run by hand)
```
event_calendar, Oct 2026 (excl. 'other'): quarterly_results 535 · board_meeting 15 · dividend 8 · buyback 2 · agm 1 · bonus 1 · rights 1
corporate_actions, Oct 2026 ex/record, equity types: DIVIDEND 19 · BONUS 5 · SPLIT 5 · RIGHTS 4 · DEMERGER 3 · BUYBACK 3
CM holidays Nov 2026: 2026-11-08 "Diwali Laxmi Pujan*" (→ muhurat true) · 2026-11-10 · 2026-11-24
Nifty 50 pct_change 2026-10-12..19: -0.70, 1.60, -0.44, 1.66, 0.65, -1.11 (no rows for 10-20 holiday / 10-21 today)
universe: Nifty 50 = 50 · F&O eligible (2026-10-21 master) = 213
Oct results meetings: all 532 · in F&O 115 · in Nifty 50 31
board_meeting rows shadowing a results row same symbol+day (dropped): 2
sector found for 285 of 529 results symbols (index_constituents industry) → sector is null for the rest
TCS RESULTS history (rule of reaction()): prices 2025-10-01..2026-10-19 (258 bars); 8 results dates, 5 covered:
  2026-10-08  event_day -0.21  d1  3.85  w1 13.20
  2026-07-09  event_day -0.39  d1  0.95  w1  7.39
  2026-04-09  event_day  1.16  d1 -2.50  w1 -0.29
  2026-01-12  event_day  0.99  d1  0.88  w1 -4.24
  2025-10-09  event_day  1.14  d1 -1.09  w1 -2.97
  (2025-07-10, 2025-04-10, 2025-01-09 precede the prices: not counted, per coverage_from)
INFY DIVIDEND ex-dates in the warehouse: 2026-06-10, 2025-10-27 (both on or after the prices start; history n counts only price-covered occurrences)
```
Result: PASS — real rows exist for every event class; the SQL runs. The Python merge/return code was NOT run against these live rows (no DB reachable from the test container); it was run on fixtures.

## API / Endpoint Tests (staging)
- NOT RUN. The branch is not on staging (this session cannot push to dev; the staging DaaS bind-mounts the dev checkout) and no session token was supplied.

## Inputs required from user
- Merge feat/desk-events-calendar to dev so the DaaS and app backends on staging get the routes; a staging session token (`session_token` cookie) for `curl /api/markets/events-calendar?month=2026-10&universe=fno` and `/history?symbol=TCS&type=RESULTS`.

## Verdict: BLOCKED
UNVERIFIED: both endpoints over HTTP on staging (TC-15). VERIFIED: unit/route behaviour (56 tests) and the underlying data (SQL). See OVERRIDE_desk_events_calendar_backend.md.
