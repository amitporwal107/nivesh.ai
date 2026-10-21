# Desk "Results today & tomorrow" board — test cases (authored before implementation)

- **Branch:** feat/desk-results-today (from dev 007c8b34)
- **Date:** 2026-10-21
- **Author:** Claude (full stack + QA)
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Status:** IN PROGRESS (this file lists the cases; results are recorded in desk_results_today_20261021.md)

## Design (fixed before code)
- Batch endpoint `GET /v1/desk/events-calendar/expectations?from=&to=&universe=fno|n50|all` (DaaS) and `GET /api/markets/events-calendar/expectations` (app): RESULTS meetings in [from,to], range at most 3 days, each event summarised with the same maths as the single-event endpoint, one shared method/by_metric block.
- "Today" is the IST date. The existing `_today()` used the server date; it becomes IST so 00:00-05:30 IST is not a day behind.
- Status per event: `declared` when the target quarter's figures are stored, OR the meeting date is before today, OR the meeting is today AND an exchange filing dated the meeting day (subject "Outcome of Board Meeting" or containing "result") is on file; otherwise `upcoming`. `filed_state` = `figures` (figures stored) | `pending` (declared, figures not stored) | null.
- Finding that drives this (measured 2026-10-21 17:07 IST): the stored quarterly figures come from Screener/Trendlyne a day or more after the filing (19 Oct: 21 of 25 stored; 20 Oct: 0 of 2; 21 Oct: 0 of 26, 18 of 26 already have a filing). So "pending" is common for today; the cell says so and never shows a number we do not hold.
- UI board above calendar/timeline in stock mode: one row per company, per metric the expected range + midpoint, and the filed value with inside/above/below + % vs midpoint when stored; declared first (figures, then pending), then awaited; header label, track-record footer from by_metric; row click opens the existing event panel; hidden in macro mode and when no results today/tomorrow.

## Test cases
| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | DaaS | range from=to=today returns only RESULTS meetings of that date | unit | no BOARD/DIVIDEND rows, dates in range |
| TC-2 | DaaS | span of 3 days accepted, 4 days -> 400 | unit | 400 on >3 days |
| TC-3 | DaaS | from > to, bad date format, bad universe -> 400 | unit/failure | 400 |
| TC-4 | DaaS | universe fno / n50 / all filter the events; names and sector filled | unit | counts match the universe sets |
| TC-5 | DaaS | declared with stored target quarter: filed value, vs_mid_pct, within_band, expectation computed from data known BEFORE the filing (no leakage) | unit | same numbers as the single endpoint |
| TC-6 | DaaS | meeting today, no stored figures, filing seen -> status declared, filed_state pending, filing subject/time returned, filed null | unit | no invented numbers, gap explains the lag |
| TC-7 | DaaS | meeting today, no filing -> upcoming, expectation present, filed null | unit | status upcoming |
| TC-8 | DaaS | meeting tomorrow -> upcoming; a filing dated today for a tomorrow meeting is ignored | unit/edge | upcoming |
| TC-9 | DaaS | IST boundary: 00:10 IST on 22 Oct is "today" 22 Oct although the UTC date is 21 Oct | unit/edge | today = IST date |
| TC-10 | DaaS | filing filed 23:50 IST on the meeting day counts; filing at 00:05 next day does not | unit/edge | window = meeting day IST |
| TC-11 | DaaS | ordering: declared+figures, declared+pending, upcoming; ties by date then symbol | unit | stable order |
| TC-12 | DaaS | thin-history / unreliable symbol keeps reliable=false with note in the batch (HAVELLS-like) | unit | null expected, note kept |
| TC-13 | DaaS | single endpoint and batch agree for the same symbol/date (status, expected, filed) | unit | identical |
| TC-14 | App | route validates dates (422), forwards, 502 on upstream failure, 404 not used | unit | per pattern of the existing routes |
| TC-15 | Real data | latency for today+tomorrow on staging data (F&O and all-NSE), measured | api | recorded |
| TC-16 | Real data | today's companies: how many have real actuals stored vs filing seen vs awaited | data | recorded honestly |
| TC-17 | UI | board shows today+tomorrow rows with range, midpoint; declared row shows filed value + inside/above/below + % vs midpoint | e2e (mock) | visible |
| TC-18 | UI | pending row says "Filed result not loaded yet ..." and shows no number | e2e (mock) | text present, no figure |
| TC-19 | UI | ordering declared first, awaited after; chips DECLARED / AWAITED | e2e (mock) | order |
| TC-20 | UI | board follows universe, sector and search filters | e2e (mock) | rows filtered |
| TC-21 | UI | row click opens the event panel for that company | e2e (mock) | panel title |
| TC-22 | UI | hidden in macro mode and when there are no results today/tomorrow | e2e (mock) | absent |
| TC-23 | UI | no beat/miss/bullish/bearish wording; label + compared_with + track-record footer present | e2e (mock) | text checks |
| TC-24 | UI | one network request for the board (batch), error state with retry; malformed payload -> error not numbers | e2e (mock) | single request |
| TC-25 | UI | phone (390px): cards, no horizontal scroll | e2e (mock) | no overflow |
