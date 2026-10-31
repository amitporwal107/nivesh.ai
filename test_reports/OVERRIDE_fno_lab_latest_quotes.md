# OVERRIDE: fno_lab_latest_quotes (latest quotes on the Candidates cards and the index card, branch feat/fo-lab-latest-quotes)

REASON: Staging HTTP/UI evidence needs the user's staging session_token cookie, which I do not have. No backend change and no new route: the change reads the existing GET /api/live/snapshot (cash and universe=futures) that other lab screens already use.

Evidence (this session, real output):
- `tsc --noEmit` exit 0; production build exit 0.
- Playwright (production build, mocked API): lab + portfolio-fno + desk specs `107 passed, 2 skipped` (10 new latest-quote tests TC-1..TC-9 incl. closed/delayed/expired/not-connected and a failed snapshot).
- Test cases: test_reports/fno_lab_latest_quotes_TESTCASES.md.
- Feed state read from staging Mongo (read-only): platform token valid to 2026-10-24 06:00 IST; feed leader lease live; final snapshot of 834 quotes saved 2026-10-23 16:32 IST; kite_live_close has 2026-10-23.

UNVERIFIED: the screens against the live staging feed; behaviour during market hours (the 30 s refresh was exercised only against mocks).
