# OVERRIDE — Top Movers: live verification partial (supersedes the 2026-10-03 morning version)

REASON: The endpoints and screen are now deployed and verified live on staging (see movers_live_20261003.md: 6 endpoints 200,
error paths, live Playwright pass), but three things are NOT yet verified or built, so no PASS verdict is claimed:
1. the 403 for a non-allowlisted user on the live path (no second account);
2. design fidelity: the v4 header tiles, Copilot event-analysis panel, event/deal log and "Odds move model" panel are not built as
   designed, and the calibration axis labels overlap;
3. the per-case TC-M/TC-V matrix was spot-checked, not re-walked live.
Clear this file when those are done and the report ends with `## Verdict: PASS`.
