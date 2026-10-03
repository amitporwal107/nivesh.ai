# OVERRIDE — Top Movers: live verification substantial, three items still open

REASON: The v4 port is deployed and verified live on staging (movers_live_20261003.md, addendum: live Playwright pass, all endpoints 200,
no console errors, pin/mode/range interactions, API additions confirmed over HTTP). No PASS verdict is claimed because:
1. the 403 for a non-allowlisted user is untested on the live path (no second account);
2. pixel-level fidelity vs the design was measured on an in-app mocked render at 1440px, not on the live page;
3. the owner's real top-movers list has not been compared.
Clear this file when those are done and the report ends with `## Verdict: PASS`.
