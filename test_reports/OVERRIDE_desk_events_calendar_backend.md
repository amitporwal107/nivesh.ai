# OVERRIDE — Desk events calendar backend (stock events) — STATUS: UNIT + DATA VERIFIED, STAGING HTTP NOT RUN

REASON: The two DaaS routes (/v1/desk/events-calendar, /history) and the two app routes (/api/markets/events-calendar, /history) are committed on feat/desk-events-calendar only. Staging HTTP verification is blocked until (1) the user merges the branch to dev (this session cannot push to dev) and (2) the user supplies a staging session token for the signed-in app routes.

Test cases (authored up front): test_reports/desk_events_calendar_backend_20261021.md. 56 new unit/route tests pass; the router's SQL was run read-only against the staging warehouse and returned real rows (counts and a TCS reaction table in that report). Verdict there: BLOCKED until the HTTP checks run.
