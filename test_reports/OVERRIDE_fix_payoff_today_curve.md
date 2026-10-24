# OVERRIDE: fix_payoff_today_curve (branch fix/payoff-today-curve)

REASON: Staging UI evidence needs the deployed build and a session token (not on hand). Frontend-only change on top of the existing payoff route (which already supports pre_expiry).

Evidence (this session, real output):
- Real payoff engine on staging, run with the broker screenshot's own prices (buy 100 PE 0.89, sell 98 PE 0.36, lot 4,525): expiry max profit 6,651.75, max loss -2,398.25, breakeven 99.47 = the broker's chart. T+0 at 24 Oct: 5578 4783 3719 2470 1182 13 -921 -1578 -1988 -2213 against the broker's 5560 4750 3680 2430 1140 -24 -949 -1600 -2000 -2220 (within ~1%); delta -1062.5 vs -1050.6, gamma 240.5 vs 243.4, vega 43.4 vs 44.2; theta -171.9 vs -107.5 does NOT match (convention not established).
- `tsc --noEmit` exit 0; build exit 0; Playwright lab + portfolio-fno `111 passed, 2 skipped` (1 new test TC-1/TC-2).
- copilot-app-desk-strategy-graphs.spec fails here as on clean origin/dev (measured earlier, unrelated); so the PayoffChart change is NOT covered by that spec: covered only by the new builder test.
- Test cases: test_reports/fix_payoff_today_curve_TESTCASES.md.
Not built: a Greeks table across -5%..+5% moves (the payoff route returns Greeks at the reference price only), and a range selector.
UNVERIFIED: the chart on the deployed build.
