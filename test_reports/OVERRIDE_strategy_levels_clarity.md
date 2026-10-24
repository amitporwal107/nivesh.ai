# OVERRIDE: strategy_levels_clarity (branch feat/strategy-levels-clarity, stacked on feat/strategy-levels = PR #332)

REASON: Not deployed; no session token on hand. Frontend/backend change to the levels route (itself not deployed until #332 merges).
Evidence (this session, real output): pytest `tests/test_strategy_levels.py` 12 passed (thesis levels solved so the value at them equals the planned stop and targets within 0.02; 12 hand-worked cases); levels computation takes 0.023 s; `tsc` exit 0; build exit 0; Playwright lab + portfolio-fno `115 passed, 2 skipped`.
Real defect found by checking the screenshot: the underlying stop was the call wall (30,000, 14% above a 26,299 spot, beyond both strikes). Fixed: it is now the underlying price at which the structure reaches its planned stop; the wall is shown as a reference only. Existing tests that pinned the wall behaviour were rewritten on purpose.
Stated limits: the solved levels are model estimates for the data date; structures whose value turns back (butterfly, condor) keep the wall range; triggers (touch/close) are not defined; no executable per-leg price (no live option quotes); emergency risk stop not built.
UNVERIFIED: the card and route on the deployed build.
