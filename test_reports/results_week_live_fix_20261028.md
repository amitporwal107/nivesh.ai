# Results This Week — fixes from the live check after #381/#384 (functionality report)

- **When:** 2026-10-28 01:05 IST · **Branch:** fix/results-week-live (from origin/dev 1d6546e8)
- **Found live on staging (28 Oct ~01:00 IST):** (1) the results file's "after" was empty after midnight — it read up to the
  calendar day (28 Oct, no data yet) instead of the latest loaded session; (2) the build hit the DaaS rate limit (HTTP 429), so
  the exchange-filings read failed and BAJAJ-AUTO's first reaction fell back to 28 Oct (labelled as a gap); (3) a cold results
  file took 9–13 s against the screen's default 15 s wait.

## Test cases
| TC | What | Result |
|---|---|---|
| TC-L1 | a 429 from DaaS is retried with back-off (1, 2, 4 s) and the answer returned | PASS |
| TC-L2 | after the retries a 429 is returned as before (the caller labels the gap) | PASS |
| TC-L3 | the results file reads up to the latest loaded session (prices) and the "after" uses the latest session with F&O rows | PASS (staging dry run) |
| TC-L4 | the screen waits up to 45 s for a results file | PASS (tsc; results specs) |

## Real output
```
pytest tests/test_results_stock.py tests/test_results_week.py tests/test_results_signal.py tests/test_desk_paper_safety.py
148 passed, 2 warnings in 8.99s
tsc: OK (no errors)
✓ built in 25.70s
2 skipped
17 passed (11.5s)
```
Staging dry run (read-only overlay, day 2026-10-28):
```
week 2026-10-28 in 9.8s; 429/exchange gaps: []  (only the standing "no news feed" note)
  MANKIND: first reaction 2026-10-26 | last track session 2026-10-27 | after: rollover 92.6 % vs its usual 93.6 % (normal) | 0.4s
  BAJAJ-AUTO: first reaction 2026-10-27 | last track session 2026-10-27 | after: rollover 79.8 % vs its usual 86.0 % (lower than usual) | 0.2s
```

## UNVERIFIED
- The deployed route after this merge (re-run the live checks).


## Addendum (01:13 IST): Results This Week moved to the top of the Watchlist page
The owner could not find the block: on Trade Desk › Watchlists it sat ~5,679 px down, under the AI scanner watchlist's plan cards
(live probe). It is now the first block of the Watchlist page (same page on the sidebar and on Trade Desk › Watchlists).
```
tsc: OK (no errors)
✓ built in 24.75s
2 skipped
78 passed (52.8s)
```

## Verdict: PASS
