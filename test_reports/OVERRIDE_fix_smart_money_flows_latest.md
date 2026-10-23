# OVERRIDE: fix_smart_money_flows_latest (branch fix/smart-money-flows-latest)

REASON: (1) Staging HTTP evidence needs the user's session_token cookie, which I do not have. (2) The NIDP data service (daas-api) cannot be restarted from this session (the restart is classifier-denied), so the market-pulse SQL change in nidp/services/daas_api/routers/market_pulse.py stays inert on staging until the user restarts it. The app-route change (markets_smart_money.py) deploys with the app backend.

Evidence (this session, real output):
- pytest (staging image): `4 passed` (tests/test_smart_money_flows_tail.py).
- Warehouse (read-only SQL): NSE_FII_DII vs SENSIBULL over 16 overlapping rows: all within 0.5 cr, max difference 0.0011 cr; NSE has 22 and 23 Oct, Sensibull ends 21 Oct.
- The new de-duplicated daily SQL, run read-only: 21 Oct FII net 1022.32 / DII net 1614.32 (the market-pulse route returned 2044.64 / 3228.64 before: double counted); 22 Oct -3458.70 / 2891.32; 23 Oct 887.65 / 3235.36. The new monthly SQL runs and returns one value per month.
- Test cases: test_reports/fix_smart_money_flows_latest_TESTCASES.md.

UNVERIFIED: the Smart Money screen and the market-pulse change against the deployed stack; the DaaS change needs a daas-api restart by the user.
