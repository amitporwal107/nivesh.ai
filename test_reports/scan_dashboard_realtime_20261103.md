# Functionality Verification Report — Realtime scan dashboard (Market Desk › Screener › Scan dashboard)

- **Branch:** feat/scan-builder (worktree /home/deploy/nivesh-wt-scan-builder)
- **Date:** 2026-11-03
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER + DESIGN_ENGINEER), session fffb64a1
- **Environment:** staging (app VM containers; DaaS on the NIDP VM; Kite platform session)
- **Changed areas:** backend routes/services: yes · frontend src: yes
- **Contract:** docs/scan_builder/DESIGN.md §8

## Summary
Owner, 3 Nov 09:15–09:20 IST: "put this data in a simpler v5 dashboard with realtime data from kite or true data … nothing fancy",
"updated with today's data", "with each widget criteria", "All data should be real time". The 17 widgets of Chartink dashboard
247498 (definitions only) computed on our data: Kite live candle over NSE EOD bars, NIDP fundamentals, company results from DaaS,
15-minute / 1-hour conditions from Kite intraday candles; refreshed every 10 s while the market is open; each widget shows its
criteria, written from its own definition.

## Test Cases
> Written 3 Nov ~09:40 IST, after the contract (DESIGN.md §8, 09:30) and WHILE the implementation was under way — not before it,
> as the protocol asks; the owner's request arrived at market open and the build started at once.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-M1 | backend | 17 widgets = the 17 Chartink ids; unique ids | unit | exact | |
| TC-M2 | backend | Criteria text written from each definition (operators, offsets, weekly/monthly, nested any/all, notes) | unit | exact strings | |
| TC-M3 | backend | No barred words (buy/sell/target/stop loss/SL/pick/recommend/entry/exit) in titles, criteria, columns, notes | unit | none | |
| TC-M4 | backend | Market-cap bands: rank 1–100 / 101–250 / 251+ over the whole market; no cap → no band | unit | exact | |
| TC-M5 | backend | Results not loaded → results widgets `pending`; intraday missing → `partial` with applied=false lines; intraday present → conditions decide | unit | per rule | |
| TC-M6 | backend | One widget failing → that widget `error`, the rest computed | unit | isolation | |
| TC-M7 | backend | Shared cache: two viewers → one computation; refresh after CACHE_S; failed refresh serves the last answer ≤ STALE_OK_S, then 503 | unit | exact counts | |
| TC-M8 | api | GET /market-dashboard 200; flag off → 403; DaaS down → typed 503 | api | as contract | |
| TC-R1 | backend | Results loader: consolidated preference, consecutive-quarter rules, TTM rule, file cache across workers, pending then ready | unit | per rule | |
| TC-R2 | data | Results loader vs the SQL extract of nidp.nse_financials_quarterly for 30 random companies | data | equal | |
| TC-K1 | backend | Day's Kite token reloaded from Mongo before Kite REST/historical calls on a non-leader worker | unit | refresh once, throttled | |
| TC-I1 | backend | Intraday indicators equal the daily indicator module on the same candles; first_high; offsets; rate limit; no token | unit | exact | |
| TC-L1 | staging | Full computation on today's live data in the staging backend container: basis live, stocks with today's candle, all 17 widgets, warm refresh time | data | live, < 3 s warm | |
| TC-L2 | staging | Intraday values for 5 Nifty 50 (15 min) and 5 F&O (1 hour) stocks vs Kite quote | data | consistent | |
| TC-L3 | staging | Sample rows recomputed independently (one widget per kind) | data | equal | |
| TC-E1 | e2e | Market Desk › Screener sub-views with the flag; only Screener without; legacy view=scanbuilder → sub=builder | e2e | as contract | |
| TC-E2 | e2e | Cards: titles, criteria (dimmed not-applied lines), rows, statuses, sort, chart link | e2e | rendered | |
| TC-E3 | e2e | Market open → GET every 10 s; closed → no repeat | e2e | request counts | |
| TC-E4 | e2e | No barred words on the page | e2e | none | |
| TC-S1 | staging | After merge + deploy: GET /api/scan-builder/market-dashboard with the owner's session; page renders | api/e2e | live data | |

## Results
(filled in below as each step runs)

### Results so far (3 Nov, IST)
- **TC-M1…M8** (09:31): `tests/test_scan_builder_market_dashboard.py` — `11 passed, 2 warnings in 5.90s` (staging image, --network none).
- **TC-L1** (09:24, staging backend container, today's live market, my code with company results from the SQL extract and the
  intraday step stubbed): basis "Kite live at 09:24:13 IST … stocks outside the live feed use Kite quotes read at most 30 s ago";
  2,513 cash stocks / 217 F&O / 49 Nifty 50 with today's candle (243 without: not traded yet); runs 7.22 s cold, 1.27 s and 1.28 s
  warm; all 17 widgets computed (3 partial = the intraday ones while stubbed; 1 not computed = 10x volume first 5 min).
  First attempt at 09:23 without reloading the day's Kite token: Kite REST quote() refused (TokenException) → only the ~500
  live-feed stocks had today's candle (bug TC-K1, fix in data.py by fork R).
- **TC-L3 (partial)** (09:27:13): dashboard rows vs Kite day_quotes read right after — MARICO 5.63 % (843.50) vs Kite 5.73 %
  (844.30, a few ticks later); 360ONE 4.28 vs 4.35; ASHOKLEY 3.82 vs 3.83; INDIGO 3.67 vs 3.70; FIVESTAR 3.06 = 3.06;
  IOC 2.61 vs 2.59; SHRIRAMFIN 2.44 = 2.44; MRPL 2.27 vs 2.16 (REST quote, up to 30 s older). Previous closes identical
  (MARICO 798.55, IOC 134.59, SHRIRAMFIN 863.35).
