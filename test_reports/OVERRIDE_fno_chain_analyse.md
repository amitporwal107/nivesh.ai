# OVERRIDE: fno_chain_analyse (branch feat/fno-chain-analyse, stacked on feat/fno-margin = PR #328)

REASON: Staging UI evidence needs the deployed build and a session token (not on hand). Frontend-only; it reads the existing chain route, POST /api/desk/strategy/payoff and POST /api/fno/margin (PR #328, not yet deployed).

Evidence (this session, real output): `tsc --noEmit` exit 0; build exit 0; Playwright lab + portfolio-fno + desk specs `136 passed, 2 skipped` (8 new Analyse tests; the older chain tests unchanged and passing). Test cases: test_reports/fno_chain_analyse_TESTCASES.md.
Stated limits: no order button anywhere (Nivesh places no orders); recording option structures as paper trades stays disabled; not built: intrinsic/time-value columns, OI change % and LTP change % as chain columns, IV chart/IVP (no IV history). The browser computes no payoff, Greek, cost or margin figure.
UNVERIFIED: the panel on the deployed build; drag behaviour on real touch devices.
