# OVERRIDE: fix_index_tape_eod_day (branch fix/index-tape-eod-day)

REASON: Staging HTTP/UI evidence needs the user's staging session_token cookie, which I do not have. The backend change adds one field (`as_of`) to each tile of GET /api/markets/home; the frontend change reads it. Nothing else changed.

Evidence (this session, real output):
- pytest (staging image): `43 passed` (tests/test_index_tape_as_of.py: 2 new; tests/test_desk_overview_backend.py unchanged and passing).
- In-process call of the real route (auth stubbed) earlier today: 200 in 7.9 s cold; breadth dated 2026-10-23.
- `tsc --noEmit` exit 0; build exit 0; Playwright desk-market + markets specs `56 passed` (3 new Overview tile tests TC-3..TC-5).
- Test cases: test_reports/fix_index_tape_eod_day_TESTCASES.md.

UNVERIFIED: the Overview against the deployed staging build (needs the staging deploy and a session token); Yahoo's own daily-bar timing for each ticker.
