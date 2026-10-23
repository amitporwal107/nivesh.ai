# F&O ranking backtest, Stage A (2026-10-23): test cases, authored before implementation

Ask (user): back-test the ranking of the candidates for each session of the last year, to establish an approximation of the ranking logic.

Design (point in time, honest about limits):
- For every session D the production engine (`services/fno_candidates`, v2) is run on what was knowable at the close of D: the build-up scan for D
  (DaaS `/desk/fno-buildup?date=D`, the same classification the Lab shows) and, per symbol, the newest feature row with `as_of_date <= D`.
  Fundamentals are not a score input, so a stale quarterly figure cannot leak.
- Outcome: enter at the OPEN of the next session (the first executable price after an end-of-day signal), exit at the close of D+h for
  h = 1, 3, 5, 10, 20 sessions, on split/bonus-adjusted cash prices as a proxy for the near-month future. Direction-adjusted. Costs applied.
- Variants compared (a fixed list, counted): production ranking (Signal Strength points, top 5), OI-only top 5, price-only top 5, and the pool average
  (the expectation of a random pick from the same pool). Plus the rank correlation (IC) of the total score and of each input with the outcome.
- Splits by session: discovery 60%, validation 20%, untouched test 20%, by entry session, requiring the whole forward window inside the split.
- Limit: the features table starts on 29 Dec 2025, so sessions before that are reported as "not evaluable", not scored with missing inputs.
- This is Stage A (discovery). Nothing here is `validated`; the strongest status it can reach is `research_result`.

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | outcome | entry is the next session's open and exit the close h sessions later; direction-adjusted for a short; worked numbers | unit | return |
| TC-2 | outcome | a missing price, a halted symbol or too few later sessions gives no outcome (None), never 0 | unit | None |
| TC-3 | costs | round-trip cost in percent is subtracted from every trade, net = gross - cost; the cost parameters are returned in the report | unit | net |
| TC-4 | point in time | the features used for session D are the newest row dated <= D; a row dated after D is never used | unit | no look-ahead |
| TC-5 | point in time | the scan and features of later sessions cannot change session D's candidates (re-running D with future data appended gives the same candidates) | unit | equal |
| TC-6 | splits | sessions are assigned discovery / validation / test in time order 60/20/20; a trade whose forward window crosses a split boundary is excluded from that split | unit | counts |
| TC-7 | stats | session-level mean, Newey-West standard error with lag h-1, t-stat; worked example; a series too short gives None | unit | numbers |
| TC-8 | stats | Spearman IC per session and its mean; ties handled; fewer than 4 candidates gives no IC | unit | IC |
| TC-9 | variants | production, OI-only, price-only and pool-average top-5 are built from the same ranked pool each session; the pool average equals the mean of all pool outcomes | unit | equal |
| TC-10 | report | every variant x category x horizon x split is counted (`tested_configurations`); the experiment id and report hash are identical for identical inputs and differ when an input changes | unit | hash |
| TC-11 | verdict | status is `insufficient_evidence` below the session minimum in the test split, otherwise `research_result`; never `validated` | unit | status |
| TC-12 | real run | the backtest on the staging data platform produces a report; the findings are reported as they are, including a negative or inconclusive result | real data | report |
