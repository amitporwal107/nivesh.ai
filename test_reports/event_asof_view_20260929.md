# Functionality Verification Report — nidp.v_event_asof (migration 156)

- **Branch:** feat/event-asof-view (off origin/dev 5a9b9411)
- **Date:** 2026-09-29
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER), event-state owner
- **Environment:** staging (nidp_staging)
- **Changed areas:** backend routes/services: no (migration only: 2 SQL functions + 1 view) · frontend src: no

## Summary
One as-of interface to event state, so the chart and event halves never re-apply the timing rule.
Per filing: timing_type, known_at_open_session, known_by_close_session, primary_row (NSE/BSE double-count
guard), taxonomy_era, raw labels, lifecycle join, and the sealed-block flag. The session calendar comes
from prices_eod's traded dates, projected past the latest bhavcopy by weekday and NSE CM holidays, and is
NULL before coverage.

## Test Cases
| ID | Scenario | Expected | Result |
|----|----------|----------|--------|
| TC-1 | 09:00 on session day | pre-market; known at open that day | PASS |
| TC-2 | 15:29:59 vs 15:30:00 | intraday vs after_close | PASS |
| TC-3 | Saturday | non_session → next session | PASS (2026-09-26 → 09-28) |
| TC-4 | holiday 2024-08-15 | non_session → 2024-08-16 | PASS |
| TC-5 | beyond latest bhavcopy | projection skips weekend + Gandhi Jayanti | PASS (10-01 → 10-05; 10-02 not a session) |
| TC-6 | before calendar coverage (2021) | NULL, never guessed | PASS |
| TC-7 | as-of invariants over every row | 0 violations | PASS |
| TC-8 | equals research rule (event_panel.py) on all NSE rows | 0 mismatches | PASS |
| TC-9 | session calendar vs independent Kite NIFTY 50 (2024-08-01..2026-09-22) | identical | PASS (532/532, 0 diff) |
| TC-10 | performance | full scan < 2 min; one symbol-month a few s | PASS (51.9 s / 1.86 s) |

## API / Endpoint Tests (staging)
No endpoint. SQL against staging inside BEGIN … ROLLBACK, then applied:
```
538824|477385|0|0|0|0          rows | primary | close<event | open<event | open<close | timing NULL
Time: 51908.182 ms
418575|0|0                     NSE rows | mismatches vs research rule | research-future
RAYMOND|09-23 13:12|intraday|2026-09-24|2026-09-23|t|NSE_ANN
RAYMOND|09-23 13:15|intraday|2026-09-24|2026-09-23|f|BSE_ANN
holiday 2024-08-15|f|2024-08-16      before coverage 2021||
2026-09-28|2026-10-05|f              latest bhavcopy | session after 10-01 | 10-02 is session
```
Applied: `156_event_asof.sql|2026-09-29 16:20:59` in nidp.schema_migrations.

## Data Correctness (staging)
Timing mix — NSE: after_close 244,991 · intraday 124,362 · non_session 46,366 · pre_market 4,396;
BSE: 85,379 / 30,594 / 1,811 / 925. primary_row: all 420,115 NSE rows; 57,270 of 118,709 BSE rows.
Twin measurement behind primary_row (2026-09-01..22, 7,136 BSE filings by NSE-listed companies): an NSE
filing by the same company within 2 min 20%, within 10 min 64%, same IST day 85%.

## UNVERIFIED
- Muhurat/special-session hours are not modelled (session days are; hours are not).
- primary_row drops a BSE-only filing on a day its company also filed something else on NSE; not measured.
- Calendar before 2024-05-31 is NULL until older sessions are loaded.

## Inputs required from user
none

## Verdict: PASS
