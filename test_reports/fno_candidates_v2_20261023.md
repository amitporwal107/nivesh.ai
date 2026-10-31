# F&O candidates v2 and live OI snapshot persistence

- Branch: feat/fo-candidates-v2 (on top of origin/dev) · Date: 2026-10-23 · Environment: backend tests in the staging image (--network none), no real services
- Test cases: fno_candidates_v2_TESTCASES.md (written before the engine rewrite)

## What changed
- Engine v2 (`backend/services/fno_candidates`): Signal Strength with the PRD weights (30/20/15/15/10/10), no redistribution of a missing input (the 100-point denominator is kept, coverage and the missing inputs with their weights are returned, the score is marked incomplete), a configurable minimum coverage before a candidate is ranked (otherwise it is listed under `unranked` with the reason), Tradeability as its own score, Strategy Quality `unavailable` with reasons, fundamentals as a context panel and not an input, a research-status block (`research_setting_not_validated`) on every response.
- `GET /api/fno/scan/candidates?per=&date=`: read-only; joins the build-up scan with one bulk features read; degrades when the features fail (candidates unranked, said plainly).
- Feed: every 5 minutes of an open session, one `kite_live_intraday` document with the near-month futures and NIFTY 50 / NIFTY BANK price, OI and volume; TTL index; a failed write is logged without the error text and retried.

## Real output (this session)
- `python -m pytest tests/test_fno_candidates.py tests/test_fno_routes.py tests/test_kite_live_feed.py -q -p no:cacheprovider` (staging image) -> `175 passed, 1 warning in 8.62s`
- Earlier in the session the first v2 run failed 17 tests because the rewritten test file had not been written (the Write was refused until the file was re-read); after the rewrite all passed. The hand-worked scores (75.7, 56.7, 66.7, 60.7 after removing one input) match the code.
- Kite historical check (read-only, platform token): daily continuous futures with OI, 1,240 sessions from 25 Oct 2021 for INFY, NIFTY and BANKNIFTY; 15-minute and 60-minute candles carry OI for the active contract (details in docs/FO_THRESHOLD_RESEARCH_PLAN.md).

## NOT done / UNVERIFIED
- No frontend: the candidate screen shell and the NIFTY / BANKNIFTY workspaces are not built.
- No research runner: no threshold has been evaluated. Every setting stays `research_setting_not_validated`; nothing in this branch may be presented as validated.
- Nothing ran against the real data platform or staging: the route was exercised with invented fixtures only, and the first real call will show how many candidates reach the minimum coverage with real features.
- The snapshot collection starts filling only after deploy and a backend restart; no `kite_live_intraday` document exists yet.
