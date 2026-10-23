# Keep and show the Kite closing quotes

- Branch: feat/screener-live-futures (PR #308) · Date: 2026-10-23 · Environment: local; backend tests in the staging image, Playwright on a production build with mocked /api
- Test cases: live_quotes_market_close_TESTCASES.md (written before implementation)

## What changed
- The final snapshot after the close (the feed's one REST read of every subscribed symbol, futures included) is also saved as a per-day document `kite_live_close` (id = the IST trading day, one year TTL). It outlives the `latest` snapshot, which is overwritten at the next open and expires after 72 h.
- New `GET /api/live/close?date=&symbols=`: the newest saved close (or that day), mode "closed", final true, the day in `date`; 404 `no_saved_close` when none; 422 on a malformed date; signed-in only.
- Futures hook: a closing snapshot is now `kind: "close"`, each quote carries its day; the build-up table shows "Close fut / Close OI" while that day is newer than the bhavcopy it sits beside, and drops them once the bhavcopy catches up.
- F&O spot, Smart-money rail, Reversal detail and Setups to watch now pass their own end-of-day day, so Kite's closing quote shows (labelled "Close · date · Kite" / "Kite close") until their end-of-day data catches up. The shared overlay already applied the same rule on the other screens.

## Real output (this session)
- Backend: `python -m pytest tests/test_kite_live_feed.py tests/test_kite_intraday.py tests/test_kite_platform_login.py -q` (staging image, --network none) -> `84 passed` (77 before, 7 new: close doc saved with futures, repeat-day replace and next-day keep, no doc intraday, failed write logged not raised and only the class name logged, read_close newest / by day / none, /close route shape + 404 + 422, 401 signed out).
- Typecheck: `tsc_exit=0`.
- Playwright (desk-lab, smart-money, reversal, workspace, desk-scanner, screener, research): `222 passed`, `4 skipped` (screenshot specs), `1 failed`. The failure is `copilot-app-desk-smart-money.spec.ts:243 TC-F3` ("51d ago" vs "52d ago": date-dependent, pre-existing, untouched). New cases all pass: close columns shown / dropped, spot, rail, reversal detail, setups column, each with a newer and an older closing day.

## UNVERIFIED
- The saved close on staging: it is written at the next close after this code is deployed and the backend restarted (tomorrow 15:31 IST at the earliest); no `kite_live_close` document exists yet. Today's close (15:30) was published by the previous code, so it is only in `latest` until the next open overwrites it.
- GET /api/live/close through the deployed app (needs a session token).
- Behaviour when the backend is down at the close: no final snapshot is built, so nothing is saved (the feed only reads after the close from a running process).
