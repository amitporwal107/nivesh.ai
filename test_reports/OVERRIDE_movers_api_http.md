# OVERRIDE — Top Movers: live verification substantial, three items still open

REASON: The v4 port is deployed and verified live on staging (movers_live_20261003.md, addendum: live Playwright pass, all endpoints 200,
no console errors, pin/mode/range interactions, API additions confirmed over HTTP). No PASS verdict is claimed because:
1. the 403 for a non-allowlisted user is untested on the live path (no second account);
2. pixel-level fidelity vs the design was measured on an in-app mocked render at 1440px, not on the live page;
3. the owner's real top-movers list has not been compared. It cannot come from Trendlyne: its MCP server exposes no screener and no
   date parameter (12 tools; `get_stock_parameter_values` takes only stock codes + parameter tokens and returns latest values), and the website
   screener shows only the latest day. The independent check that DOES exist is the Kite cross-check (movers_kite_crosscheck_20261003.md:
   top-20 overlap 91.8% over 17 sessions; 297 of 297 shared names within 0.75pp on the 16 full sessions). A third-source comparison
   needs a list for specific days supplied by the owner (any source they trust).
Clear this file when those are done and the report ends with `## Verdict: PASS`.

## v5 addendum (2026-10-03)
REASON: v5 (EMA/RSI/ADX overlay, round-trip lane, technical-state card) is built and verified against the REAL staging NIDP Postgres
through the real DaaS handlers (59 pytest, 39 mocked Playwright), but NOT deployed: a dev push is a live deploy and was not requested.
Not yet verified over HTTP on staging or in the live UI. Not built by choice: the round trip x score experiment card (needs a population endpoint).
Real-data facts: delivery_data has 581 sessions (2024-05-31..2026-10-01), ~2,650 EQ symbols/day, so delivery % is real, not Kite/Trendlyne.
