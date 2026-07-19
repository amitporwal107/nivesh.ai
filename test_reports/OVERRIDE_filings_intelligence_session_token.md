# OVERRIDE — Filings Intelligence design completion

REASON: The authenticated staging API cases cannot be run without a real staging
`session_token`, which only the user can provide. Every `/api/filings/*` route is
behind `get_current_user`, so TC-1, TC-2, TC-7, TC-8, TC-9, TC-10 and the staging
data test are blocked on that secret. I did not fabricate a token or a result.

Attempted first, and rejected honestly: the repo's dev-default
`NIVESH_TEST_USER_TOKEN` (`backend/tests/conftest.py`) returns **401** on staging
over both cookie and bearer — it is a local/dev credential, not a staging session.

## What IS verified (real output in the main report)

- `npx playwright test filings-intelligence --project=desktop-chrome` → **10 passed**
- `python3 -m pytest nidp/tests/test_filing_insight_sections.py -q` → **25 passed**
- Regression across the specs the global CSS could disturb → **49 passed, exit 0**
- `npx tsc -b` clean · `npx vite build` ✓
- **TC-11 on real staging**: `GET`/`PUT /api/filings/alerts` → **401** unauthenticated
- Deploy confirmed: the route flipped **404 → 401** after pushing `919c96d6` to `dev`

## What is NOT verified — do not claim otherwise

- That `GET /api/filings/{id}/insights` returns `tabs[]`/`sections[]` on staging.
- That `GET`/`PUT /api/filings/alerts` round-trips a real user's preferences.
- That `PUT` with an unknown filing type 400s without persisting.
- That `GET /api/filings/feed` is unregressed.
- That staging's `nidp.corporate_event_signals` actually holds sectioned rows —
  the `filing_insights` generator must re-run for insights to gain `sections`;
  rows generated before this change return `sections: []` by design.

## To clear this override

Provide a staging `session_token` cookie value. The blocked cases then run in one
pass and the main report can be completed to `## Verdict: PASS` (or corrected).
