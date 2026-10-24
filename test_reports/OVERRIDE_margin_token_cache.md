# OVERRIDE: margin_token_cache (branch fix/margin-token-cache)

REASON: Not deployed yet; the fix is verified by unit tests, and the bug was observed for real on staging.
Evidence (this session, real output):
- Staging with the user's session token, 2026-10-24: `POST /api/fno/margin` answered 503 (builder strip: "not logged in to Kite today") while the platform token in Mongo was valid until 2026-10-25 06:00 IST and the Compare table, on the same page, received margins (e.g. ₹8,609 and ₹27 charges for Buy Call): different workers gave different answers.
- Cause: `ps` in the staging backend container shows `uvicorn server:app --workers 4`; `platform_token.cached_token()` is per process and only the feed leader refreshes it from Mongo (platform_token docstring).
- Fix: the margin route reloads the stored token into the worker (`platform_token.refresh_cache(db)`) before building the calculator; a failed reload leaves the route working with what the worker held.
- pytest (staging image): tests/test_fno_margin.py + test_fno_routes.py + test_kite_live_feed.py `158 passed` (new test pins the order refresh -> calculator -> Kite and a failed reload).
Not verified: the deployed route after a restart. Other routes that read `default_token()` outside the feed leader (for example quotes in other workers) may have the same stale-worker behaviour; not investigated here.
