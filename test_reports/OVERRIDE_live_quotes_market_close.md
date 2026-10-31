# Override: keep and show the Kite closing quotes

REASON: tested locally (backend 84 passed in the staging image; tsc clean; Playwright 222 passed, 1 failed on a date-dependent test unrelated to the change; see live_quotes_market_close_20261023.md). Not deployed: the PR must be merged, the frontend image rebuilt and the backend restarted, and the first saved close appears only after the next market close. The signed-in staging check of GET /api/live/close needs a session token from the user, which has not been provided.
