# OVERRIDE — Screener + Watchlist (slices W1–W3 built; chat slices not built)

REASON: The new bulk route and the Screener "Add to a list" bar cannot be run against the deployed staging app until the owner merges the PR and staging is redeployed (backend restart + frontend image). Verified so far: backend unit tests (116 passed, 3 mutation checks), Playwright on mocked APIs (64 + 69 + 35 passed), and a read-only real-data run of the new service on staging data (2 screens × 100 symbols, 0 refused). Not verified: a real bulk add on staging, a real signed-in Screener session, W4–W7.

OWNER ACTION: merge the PR, let staging redeploy, then give a staging session token (or run it signed in) so the throwaway-list check in `test_reports/screener_watchlist_w1_w3_20261101.md` can be done.

Not a PASS. See `test_reports/screener_watchlist_w1_w3_20261101.md`.
