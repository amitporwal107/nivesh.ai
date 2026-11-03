# Functionality Verification Report — Scan dashboard: "10x volume first 5 min" on Kite + TrueData, and per-stock strategy ideas

- **Branch:** feat/scan-dashboard-10x-volume (from origin/dev 6d30a7f7, after PR #464)
- **Date:** 2026-11-03
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER), session fffb64a1
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Contract:** docs/scan_builder/DESIGN.md §8 (10x volume paragraph); strategy ideas: `ideas` / `ideas_meta` on GET /api/scan-builder/market-dashboard

## Summary
Owner 3 Nov ~12:40 IST (screenshot of the "Not computed" card): "Please fix this using kite or true data". Then ~12:58: "provide
the best AI recommended strategies for each of the stocks wherever the risk reward are favorable" — built as STRATEGY IDEAS from
the existing strategy builder (owner's compliance wording rules of 25 Oct and 3 Nov), only where its reward : risk rule passes.

## Test Cases
> Written 3 Nov ~12:58 IST, after the design and DURING implementation (the owner's requests arrived mid-session, market open).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-V1 | backend | first_volume = volume of the latest session's first candle; 5-minute candles read as ("5m", 15 sessions); 5-minute cache TTL 1 day | unit | exact | |
| TC-V2 | backend | 10x widget: daily part → 5-minute test (first volume > 10 × SMA(volume, 1000) as of the candle before) → TrueData only for survivors | unit | calls + rows | |
| TC-V3 | backend | no ticks / no TrueData login → Partial, trade-side line not applied with the reason | unit | as rule | |
| TC-V4 | backend | 5-minute candles not in yet → TrueData never asked; Partial | unit | no call | |
| TC-V5 | backend | candles read but < 1,000 of them → not Partial, note "too little history" | unit | as rule | |
| TC-T1 | backend | tick classification (quote rule, mid, tick test, auction print, 1-share markers), incremental reads, cross-worker cache, spacing | unit | exact | |
| TC-T2 | data | SBIN ticks 09:15–12:50 classified by tick_flow vs independent code on the same rows | data | equal | |
| TC-K1 | data | a stock's first 5-minute candle volume and 1,000-candle mean vs Kite's own 5-minute candles | data | equal | |
| TC-L1 | staging | the 10x widget end to end on today's live data (staging backend container, process-local caches) | data | rows + all criteria applied | |
| TC-I1 | backend | attach_ideas: every shown stock once, symbol rows only; None = not favorable; absent = being built; plan_inputs not sent | unit | exact | |
| TC-I2 | backend | ideas failing → dashboard still answers | unit | isolation | |
| TC-I3 | backend | strategy_ideas: favorable kept / unfavorable None / failure None; cache across workers; staleness; wording | unit | per rule | |
| TC-I4 | staging | ideas for 8 of today's dashboard stocks with the real builder (read-only) | data | ideas or None with reasons | |
| TC-E1 | e2e | idea column: favorable / none / being built states and tooltip; header line + caveat; no column on group/index widgets | e2e | rendered | |
| TC-E2 | e2e | no barred words (buy, sell, target, stop loss, pick, recommend, entry, exit) on the page | e2e | none | |
| TC-S1 | staging | after merge + deploy: the route answers with `ideas`; the page in a browser with the owner's session | api/e2e | live | |

## Results
(filled in as each step runs)
