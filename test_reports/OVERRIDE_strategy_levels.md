# OVERRIDE: strategy_levels (branch feat/strategy-levels)

REASON: The new route is not deployed to staging and I have no session token on hand, so POST /api/desk/strategy/levels has not been called through the app. The engine it wraps (compute_payoff) was exercised for real on staging earlier today.

Evidence (this session, real output):
- pytest (staging image): tests/test_strategy_levels.py (10) + the existing strategy tests `334 passed`: hand-worked numbers for a bull call spread (D=3: stop 2.10, T1 3.90, T2 4.80, boundary 0, reward:risk 2.33), bear put spread, bull put spread (credit 2: stop 3.5, boundary 5, targets 1.0 / 0.4), iron butterfly, wrong-side walls, per-unit invariance across lots and lot size, scenario matrix, route 200/422.
- `tsc --noEmit` exit 0; build exit 0; Playwright lab spec `79 passed, 2 skipped` (4 new levels tests).
- Test cases: test_reports/strategy_levels_TESTCASES.md.

Found and fixed while testing: the payoff engine rejects undefined-risk structures (`undefined_risk_not_supported`), so the builder's Short Straddle and Short Strangle tiles could only produce an error; they are replaced by an Iron Butterfly (defined risk).
Stated limits: rule-based hypothetical levels from fixed research settings (strategy-levels-v1); no accuracy or hit rate is claimed; a stop is a theoretical level; no entry RANGE (needs bid/ask); no probabilities, so no expected P&L; IV rank/percentile not shown (no IV history stored); the Greek review rule thresholds (30% of entry delta; |delta| 0.20 for neutral) are research settings, not validated.
UNVERIFIED: the route and the card on the deployed build.
