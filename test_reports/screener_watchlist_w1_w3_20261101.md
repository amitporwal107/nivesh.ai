# Screener + Watchlist in the Copilot — slices W1, W2, W3 (1 Nov 2026)

Plan: `docs/plans_20261031/SCREENER_WATCHLIST_PLAN.md`. Test cases: `test_reports/screener_watchlist_TESTCASES.md` (authored before the code of each slice).
Branch `feat/screener-watchlist` (from dev 33d266fd). Status: **IN PROGRESS** — W1–W3 built and verified on mocks plus one real-data read; the chat slices W4–W7 are not built; nothing is on staging.

## What was built
- **W1** Trader rail rows "Screener" and "Watchlists" (`lib/views.ts`, `shell/Rail.tsx`, `index.tsx`); the rail lights the row whose query matches (`isNavCurrent`), so the desk row no longer stays lit.
- **W2** `services/screener_run.py` (the body of `POST /api/screeners/run`, moved unchanged); `POST /api/watchlists/{id}/symbols/bulk`; every list write answers 403 while an advisor views a client.
- **W3** Screener page: a checkbox per result row, "Select the first 100", and an "Add to a list" bar (`screener/AddToList.tsx`) with existing-list or new-list choice, a result that names what was added / already there / refused, and the label "Keep this screen (re-runs daily)" on the rules saver. `writeFailure` now also shows a 403's own sentence.

## Real output (this session)
Backend, unit (in-memory Mongo stand-in, no network), `nivesh/backend:staging` image:
```
tests/test_screeners_run.py tests/test_screener_contract.py tests/test_screen_to_strategy.py   → 80 passed, 1 skipped   (test_screeners_run.py NOT edited: the move is behaviour-neutral)
tests/test_watchlists.py tests/test_screeners_run.py                                          → 116 passed
tests/test_watchlists.py (after the 3 mutations were reverted)                                → 69 passed
```
Mutation checks (each change reverted and the file diffed identical afterwards):
```
guard disabled everywhere  → 1 failed: test_every_list_write_is_refused_while_an_advisor_views_a_client
100-stock limit removed    → 1 failed: test_bulk_refuses_what_does_not_fit_by_name_and_never_exceeds_the_limit
503 stop removed           → 1 failed: test_bulk_when_the_instrument_list_cannot_be_checked_adds_nothing
```
Frontend, production build + Playwright 1.47 (`TSC_EXIT=0`, `BUILD_EXIT=0`):
```
copilot-app-trader-rail + desk-shell + copilot-app                                   → 69 passed
copilot-app-screener-add (AL-1..AL-12) + screener + workspace + trader-rail          → 64 passed
copilot-app-ai-watchlist + copilot-app-watchlists + watchlist-unauth                 → 35 passed
```
A first run of the new spec had one failure, AL-8: the screen showed "this account does not have access" for the advisor's 403 instead of the server's sentence. That was a real defect, fixed in `writeFailure`; the re-run passed.
Earlier Playwright runs while the machine load average was 44–190 showed timeouts in `copilot-app-desk-shell` (SH-15, SH-22); the same specs passed on a quiet machine (load 2) with no change to the code.

## Real data, read-only (staging backend container, nothing written)
The new `services/screener_run.py` and `_names_for` loaded from /tmp into the staging backend container and run against real data (overlay removed afterwards; `ls /tmp/ov_scr` → no such directory):
```
large cap, ROE over 15 : as_of 2026-10-30, matched 103, checked 100, known 100, refused 0, blank names 0, screen 0.3 s, 100 look-ups 1.6 s
any size, P/E under 25 : as_of 2026-10-30, matched 908, checked 100, known 100, refused 0, blank names 0, screen 0.3 s, 100 look-ups 1.4 s
```
This answers the plan's open question (section 9): a real 100-row screen is not refused by the instrument list.

## UNVERIFIED
- The bulk route and the Screener bar have **not** run against the deployed staging app: the route does not exist there until this branch is merged, the backend restarted and the frontend rebuilt. The real check (a throwaway list on the owner's own test account, one bulk add, then delete the list) is still to do.
- The Trader-rail highlight was tested on the mocked desk only.
- Phone layout was asserted (no sideways scroll, a 44 px button) but not looked at as a screenshot.
- W4–W7 (chat) are not built.
