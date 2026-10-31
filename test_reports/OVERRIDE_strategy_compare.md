# OVERRIDE: strategy_compare (branch feat/strategy-compare, stacked on feat/strategy-levels = PR #332)

REASON: Frontend-only; it reads POST /api/desk/strategy/levels (PR #332, not yet deployed) and POST /api/fno/margin (deployed). No staging UI evidence: not deployed, no session token on hand.

Evidence (this session, real output): `tsc --noEmit` exit 0; build exit 0; Playwright lab + portfolio-fno `119 passed, 2 skipped` (5 new compare tests; the mock for the levels route is an independent vertical-spread calculation written for the spec). Test cases: test_reports/strategy_compare_TESTCASES.md.
Stated limits: NO ranking, score or "best" marker (needs a probability of profit and an expected-return model that do not exist, and weights no test has validated); sorting only by the column the user picks; figures per share from end-of-day closes; margin and charges are Zerodha's calculator for the platform account (a missing Kite login reads as such, other columns still show); Sell Put reads "not supported" because the payoff engine accepts defined-risk structures only.
UNVERIFIED: the view against the deployed routes; the latency of 4 levels calls + 4 margin calls per view.
