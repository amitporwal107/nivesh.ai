# Functionality Verification Report — Live chart ticket (LC-8) and the two-column layout

- **Branch:** fix/desk-live-chart-ticket (from origin/dev 5d5466c1, after #388)
- **Date:** 2026-10-28
- **Author:** Claude (full-stack developer + QA)
- **Environment:** mocked-UI Playwright on the app VM; staging nginx log read-only
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
The staging check of #388 (`test_reports/desk_live_chart_staging_20261028.md`, case LC-8) found this: for HDFCBANK, which has no plan today, the ticket stayed on "Looking for this stock's plan" after 45 s. Meanwhile `risk/profile` and `paper-trades` were aborted again and again.

**Cause, from the staging nginx log of 00:10–00:14 UTC.** The Live chart fired two heavy POSTs:
- `POST /api/desk/strategy/ideas` (~16 s), used by the ticket to find the plan;
- `POST /api/desk/strategy/top` (12–16 s), used by the F&O card's candidate structure.

The light GETs that started alongside them did not answer in time. The browser closed them, and nginx logged 499 for `risk/profile` and `paper-trades?status=all`. The same reads answer in about 1.4 s by curl when nothing heavy runs. The ticket's no-plan state waited on the ideas POST, which never finished while the page was open; the owner's own session shows the ideas and top POSTs closed as 499 again and again.

**Fix:**
1. The plan comes from `?tp=`, else the stored AI watchlist day (`GET /api/desk/ai-watchlist`, one fast read). That day holds the job's plans, which every user can read. Last comes the ideas board, used only when it is already in the cache.
2. The candidate structure reads the stored day's F&O list the same way.
3. The Live chart fetches neither board.
4. A symbol with no plan says so, naming the list's date.
5. The chart card and the ticket sit side by side when the panel is at least 1,000 px wide, and stack below that. The frame is unchanged; desk width is audit chunk F2.

## Test Cases
| ID | Scenario | Type | Expected | Result |
|----|----------|------|----------|--------|
| LC-8a | HDFCBANK (not on the stored day) while the ideas route takes 20 s | e2e | "No plan for HDFCBANK today, so there is no order to place (HDFCBANK is not on the AI watchlist of 19 Oct 2026)" within 10 s | PASS |
| LC-8b | the same load, watched 8 s more | e2e | no failed request for risk/profile or paper-trades; at most 2 requests each; ideas and top POSTs requested 0 times | PASS |
| LC-9 | 2560 px window (panel ≥ 1,000 px) and 1440 px | e2e | side by side at ≥ 1,000 px, stacked below; a 2560 window gives the panel ≥ 1,000 px | PASS |
| TC-20 | ICICIBANK without `?tp=` | e2e | the stored day's plan, so quantity 666 (the risk service's `account_size`) | PASS |
| TC-22 | the candidate structure | e2e | the stored day's F&O idea "Bear put spread 1360/1380" | PASS |
| CH-1/CH-2 | the trade-desk cases on the Live chart ticket | e2e | unchanged expectations (the CH-1 page now mocks the stored day) | PASS |

## UI / Playwright Tests
- **Command:** `PWEXTRA="--workers=1" run-fe.sh <worktree> … e2e/tests/copilot-app-desk-live-chart.spec.ts e2e/tests/copilot-app-desk-trade-desk.spec.ts e2e/tests/copilot-app-desk-shell.spec.ts`
- **Output:** `tsc: clean` · `✓ built in 36.18s` · `85 passed (3.2m)` · `exit 0`. That is 13 live-chart tests plus 72 trade-desk and shell tests.
- **An earlier run with `--workers=2` gave `1 failed, 84 passed`:** desk-shell SH-4 timed out at 31.5 s on `risk/controls`, a view this change does not touch, while other sessions' Playwright containers were running. It did not repeat in the run above.
- **Result:** PASS.

## Data Correctness (staging)
- Read-only: the staging nginx log for 28 Oct 00:10–00:14 UTC (quoted in the summary).
- The fix itself is not deployed. See `test_reports/OVERRIDE_desk_live_chart_lc8.md`.

## Inputs required from user
- The merge of this PR, then a re-check on staging of `?tab=trade&view=chart&sub=live&sym=HDFCBANK`.

## Verdict: BLOCKED
The mocked UI and the request counts pass. Staging after the merge is still to be checked: the no-plan text within a few seconds, and no 499 for `risk/profile` or `paper-trades` in the nginx log.
