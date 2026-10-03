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

## v5 live result (2026-10-03, after dev deploy 7f7a7dde; all 3 workflows succeeded)
Staging HTTP: /api/movers/CUBEXTUB (tech True, score 10/10 EXTREME, round trip True, 1 RT, delivery 67/67), ATALREAL (101 RTs, 0/10 WEAK, delivery 81/81),
/analysis tech_state anchored 2026-09-23 with 6 groups. Live Playwright on :8443: PASS, no non-200, no page errors; mv-ema20/50, mv-rsi/adx, mv-lane-rt, mv-tech* present.
Still open: pixel check of v5 against the design on the live page; the experiment card (not built).

## Forward lists + labelled preview (2026-10-03)
Owner asked for a new-model Monday list. tpd_model.publish refuses preview/non-counting snapshots by design, so it is NOT published as official:
migration 158 (nidp.tpd_preview_*) + tpd_preview_loader + GET /movers/forward + a "NEW-UNIVERSE PREVIEW · NOT GRADED" card beside run 13.
nidp.tpd_runs untouched (11 rows before and after). Verified: 61 pytest, 43 mocked Playwright, endpoint against staging PG. Live HTTP/UI: see next section once deployed.

Live (deploy 83783215, all 3 workflows success): GET /api/movers/forward -> official run 13 (997) + preview (1418, graded False, counts False); tpd_runs still 11 rows.
Live Playwright: forward card visible, badge "NEW-UNIVERSE PREVIEW · NOT GRADED", 15 + 15 rows, no page errors.
