# Functionality Verification Report — Smart trading desk (Copilot app, Trader tool)

- **Branch:** feat/copilot-trading-desk (worktree /home/deploy/nivesh-trading-desk, off origin/dev d8030d15)
- **Date:** 2026-10-14
- **Author:** Claude (FULL_STACK_DEVELOPER + DESIGN_ENGINEER + QA_ENGINEER)
- **Environment:** local production build with route-mocked APIs (Playwright); staging data checked read-only. Staging UI check waits on the merge.
- **Changed areas:** backend routes/services: no · frontend src: yes

## Summary
The user attached a design ("Smart Trading Desk") and asked for "a tool for the trader in new app". It is built as a new Trader tool in the one-screen Copilot app at `/app/trader/desk` ("Smart trading desk", first in the Trader rail), additive: the existing Trader desk, Options lab and every other screen are unchanged. Six tabs follow the design: Overview, AI scanner, Chart analysis (with the risk desk), Market intelligence, Portfolio & risk, Options & futures lab; a Copilot panel is docked at the right on wide screens. Every block reads an endpoint that already exists; a part of the design with no backend shows a "Not connected yet" block instead of sample numbers. No backend code changed.

Design → data map (from a survey of backend/routes on this branch):

| Design block | Endpoint(s) | Notes |
|---|---|---|
| Index tiles, breadth, FII/DII, USD/INR, crude | GET /api/markets/home | daily-close sparks; breadth from the bhavcopy universe or the Nifty-50 fallback |
| Market regime | GET /api/macro/today (BULL/NEUTRAL/BEAR = Nifty vs 50-DMA) + `verdict` from /home | no 3-state model exists; the definition is printed |
| Sector strength | GET /api/positional/market-dashboard `sector_heatmap` | "Today" when `source = nse_live`, else 5-day mean (EOD) |
| Opportunity scanner | GET /api/positional/watchlist + GET /api/positional/picks, merged by symbol | rules-based score (final_score × 100) |
| Move probability | GET /api/move-odds/latest?head=p_up5_1d | next-session model, flag `move_odds`; not a 20-session figure |
| Candles + indicators | GET /api/research/chart-live/{sym}/ohlcv | flag `charting`; EMA/RSI/ATR/RVOL/20-day VWAP computed in the browser from the daily bars |
| Market intelligence | GET /api/filings/feed, GET /api/filings/{id}/insights, GET /api/markets/fii-dii | classified NSE/BSE filings with sentiment and AI read |
| Portfolio & risk | GET /api/portfolio/holdings-enriched, /exposure/concentration, /risk-analytics; broker block reused | read-only |
| Options & futures | GET /api/fno/{sym}/expiries, /chain, /futures | EOD F&O bhavcopy, Black-76 estimates |
| Docked Copilot | POST /api/chat/stream (persona "trader") | its own thread; "Open full thread" goes to /app/t/{id} |

## Test Cases
> Authored up front — after the API + UI design, before implementation of the tabs. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Shell | Trader mode rail lists "Smart trading desk" first; click opens /app/trader/desk | e2e | screen-trading-desk visible, six tabs || PASS (copilot-app-desk.spec.ts) |
| TC-2 | Shell | Tab click updates `?tab=`; deep link `?tab=chart&sym=X` opens Chart with X | e2e | URL and selected tab agree || PASS |
| TC-3 | Shell | Unknown `?tab=zzz` | edge | falls back to Overview || PASS |
| TC-4 | Dock | ≥1400px: dock visible, shell ask box hidden; chip sends POST /api/chat/stream with persona "trader"; answer text shows in the dock; "Open full thread" → /app/t/{id} | e2e | as stated || PASS (+ scanner shows cards beside the dock) |
| TC-5 | Dock | <1400px: no dock, shell ask box present | e2e | as stated || PASS (+ scanner shows its table) |
| TC-6 | Dock | stream fails (500) | failure | error line in dock with retry, no crash || PASS |
| TC-7 | Responsive | 390px, every tab: no sideways page scroll; tab strip scrolls | e2e | scrollWidth ≤ clientWidth || PASS (shell + every tab, 4 specs) |
| TC-8 | Overview | Index tiles from /home: value, change, VIX tile; sparkline drawn from `spark` | e2e | figures equal the payload || PASS (copilot-app-desk-market.spec.ts) |
| TC-9 | Overview | Breadth counts and advancing share worked out from the payload | e2e | e.g. 2428 / (2428+1142+72) || PASS |
| TC-10 | Overview | Regime from /macro/today BULL → "Bullish" + definition; /home verdict shown | e2e | as stated || PASS (BULL, and uninitialised → not available) |
| TC-11 | Overview | Sector strength from market-dashboard; label "Today" for nse_live, "5-day" otherwise | e2e | label follows `source` || PASS |
| TC-12 | Overview | /home 500 | failure | error block with retry; other blocks still render || PASS |
| TC-13 | Scanner | Rows merged from watchlist + picks; ranked by score; status from bucket | e2e | order and status match payload || PASS (copilot-app-desk-scanner.spec.ts) |
| TC-14 | Scanner | Group chips filter by bucket; sort by R:R | e2e | row counts match || PASS |
| TC-15 | Scanner | Move odds final → P(+5% next session) per row + events n; 403 → "—" and a locked note | e2e | as stated || PASS (final, and 403) |
| TC-16 | Scanner | Row click → Chart tab with that symbol | e2e | `?tab=chart&sym=` || PASS |
| TC-17 | Scanner | Both routes fail → error; one fails → partial note | failure/edge | as stated || PASS (both fail; one fails) |
| TC-18 | Chart | Candles from chart-live bars; 1M/3M/6M changes the candle count | e2e | 22 / 63 / 126 (or fewer when history is short) || PASS |
| TC-19 | Chart | Indicator tiles equal values worked out from the fixture bars (EMA20, RSI14, ATR14, RVOL) | e2e | match to the shown precision || PASS (independent implementation in the spec) |
| TC-20 | Chart | Levels (entry/stop/target) from the pick; R:R = (T−E)/(E−S) | e2e | as stated || PASS |
| TC-21 | Chart | chart-live 403 → locked; 404 → no prices | edge | honest states || PASS (403, 404) |
| TC-22 | Risk desk | Sizing: qty = floor(capital × risk% ÷ (entry − stop)); toggles recompute; >25% of capital warns | e2e | as stated || PASS |
| TC-23 | Risk desk | Paper-trade and alert actions show "not connected" (no POST is made) | e2e | no write request || PASS (no POST/PUT/DELETE observed) |
| TC-24 | Intel | Feed rows from /filings/feed with sentiment; category chip changes the query; select → /filings/{id}/insights | e2e | as stated || PASS |
| TC-25 | Intel | Linked ticker in scanner → "In scanner" + opens Chart | e2e | as stated || PASS |
| TC-26 | Intel | FII/DII chip lists /markets/fii-dii daily rows | e2e | as stated || PASS |
| TC-27 | Intel | Empty feed / feed 500 | edge/failure | empty block / error block || PASS (empty, 500) |
| TC-28 | Portfolio | Holdings with weights, concentration warnings, risk analytics (beta, VaR) | e2e | figures from payload || PASS (copilot-app-desk-portfolio-fno.spec.ts) |
| TC-29 | Portfolio | Empty portfolio | edge | empty state with a link to connections || PASS (+ correlation not connected, paper evaluation 403) |
| TC-30 | F&O | NIFTY / BANKNIFTY cards from /fno chain summary: PCR, max pain, walls, expected move | e2e | figures from payload || PASS |
| TC-31 | F&O | Option-chain OI table for the selected underlying; ATM / R / S / MP tags | e2e | as stated || PASS |
| TC-32 | F&O | Stock ticker input loads its chain; 404 → "no F&O rows" | e2e/edge | as stated || PASS (stock chain, 404) |
| TC-33 | F&O | Cross-stock futures build-up scan shows "Not connected yet" | e2e | as stated || PASS |
| TC-34 | Build | `tsc --noEmit` clean; production `vite build` clean | build | clean || PASS (TSC CLEAN; vite build ✓ built in 21.44s) |
| TC-35 | Regression | Existing copilot-app specs (trader, options, markets, screens) still pass | e2e | all pass || PASS (all 17 existing copilot-app specs: 316 passed, 23 skipped, 0 failed) |
| TC-36 | Data | Staging tables behind the desk are populated and fresh (positional_signals, stock_technical_features, fno_bhavcopy, corporate_announcements, tpd runs, macro_state) | data | latest dates within a few sessions || PARTIAL — warehouse fresh; app-DB scanner tables empty; tpd_runs empty (see Data Correctness) |

## API / Endpoint Tests (staging)
No backend routes or services changed. (Read-only data checks are under Data Correctness.)

## UI / Playwright Tests
Local production build (`vite build`, base /v5/) served by `vite preview`, Playwright 1.47 in `mcr.microsoft.com/playwright:v1.47.0-jammy`, `--network none`, every /api route mocked in the specs (MOCK — not real data; payloads in the real routes' shapes). Config `pw.copilot-app.config.ts` (1280×800 default; specs set 1440, 1280, 390 where they test a width).

Desk specs (49 tests: shell 7, Overview + Intel 13, Scanner + Chart + risk desk 20, Portfolio + F&O 9), final run after the last change:
```
TSC CLEAN
vite build ok
✓ built in 21.44s

Running 49 tests using 3 workers

  ✓   2 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:214:3 › Smart trading desk — Overview › TC-8: the four index tiles equal the /home payload, VIX included, each with its daily-close line (1.4s)
  ✓   3 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:251:3 › Smart trading desk — Overview › TC-10: regime BULL reads Bullish with its definition; flows, rupee, crude and the rules-based read come from the backend (1.5s)
  ✓   1 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:233:3 › Smart trading desk — Overview › TC-9: breadth counts and the advancing share are worked out from the payload, with the universe named (1.9s)
  ✓   4 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:277:3 › Smart trading desk — Overview › TC-10: the macro route's uninitialised answer shows an honest not-available state, not a Neutral regime (1.1s)
  ✓   5 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:291:3 › Smart trading desk — Overview › TC-11: sector strength says Today for live sector-index rows and 5 days for end-of-day rows (1.7s)
  ✓   7 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:334:3 › Smart trading desk — Overview › an Ask chip hands its question to the Copilot (1.1s)
  ✓   8 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:346:3 › Smart trading desk — Market intelligence › TC-24: feed rows with sentiment; a chip sets the category query; selecting a row reads its insight (1.6s)
  ✓   9 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:418:3 › Smart trading desk — Market intelligence › TC-25: a linked stock in today's scanner shows its rank and opens its chart (1.3s)
  ✓   6 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:320:3 › Smart trading desk — Overview › TC-12: a failed market overview shows an error with retry while the regime and sectors still render (3.2s)
  ✓  11 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:454:3 › Smart trading desk — Market intelligence › TC-27: an empty feed shows an empty state (1.1s)
  ✓  10 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:436:3 › Smart trading desk — Market intelligence › TC-26: the FII / DII chip lists the latest ten sessions from /markets/fii-dii (1.2s)
  ✓  14 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:168:3 › Smart trading desk — Portfolio & risk › TC-28 positions with weights, a stock above 25% in amber, sector concentration, beta and VaR (1.2s)
  ✓  13 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:475:3 › Smart trading desk — Overview and Market intelligence at 390px › TC-7: no sideways scroll on either tab (1.7s)
  ✓  15 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:249:3 › Smart trading desk — Portfolio & risk › TC-28 over the shared fixtures: equity rows only, weights from the route, sector split with the rest folded (979ms)
  ✓  12 [copilot-app] › e2e/tests/copilot-app-desk-market.spec.ts:461:3 › Smart trading desk — Market intelligence › TC-27: a failed feed shows an error with retry (3.3s)
  ✓  16 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:303:3 › Smart trading desk — Portfolio & risk › TC-29 an empty portfolio shows the empty state, and its button opens broker connections (1.0s)
  ✓  17 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:416:3 › Smart trading desk — Options & futures lab › header, expiry choice and the eight stats come from the NIFTY chain and futures (1.2s)
  ✓  18 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:460:3 › Smart trading desk — Options & futures lab › TC-31 the chain table tags ATM, R, S and MP on the right strikes, with a read from the figures (1.2s)
  ✓  19 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:493:3 › Smart trading desk — Options & futures lab › TC-30 NIFTY and BANKNIFTY cards show each chain's PCR, max pain, walls and expected move (1.1s)
  ✓  21 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:566:3 › Smart trading desk — Options & futures lab › TC-33 OI build-up is not connected; strategies link to the Options lab and say paper strategies are not connected (1.1s)
  ✓  20 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:529:3 › Smart trading desk — Options & futures lab › TC-32 a ticker loads that stock's chain; a ticker with no F&O rows says so (1.3s)
  ✓  22 [copilot-app] › e2e/tests/copilot-app-desk-portfolio-fno.spec.ts:587:3 › Smart trading desk — Portfolio & risk and F&O at 390px › TC-7 no sideways scroll on the Portfolio & risk tab or the Options & futures lab (1.5s)
  ✓  23 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:259:3 › Smart trading desk · AI scanner › TC-13 merged rows are ranked by score, status follows the bucket, and the pick's plan wins (1.3s)
  ✓  24 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:293:3 › Smart trading desk · AI scanner › TC-14 group chips filter the list and Reward:risk re-ranks it (1.4s)
  ✓  25 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:318:3 › Smart trading desk · AI scanner › TC-15 published odds: P(+5% next session) and events per row, the model's record, and ranking by it (1.2s)
  ✓  26 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:340:3 › Smart trading desk · AI scanner › TC-15 odds 403: every probability is “—” and the account is told it is not enabled (1.1s)
  ✓  27 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:353:3 › Smart trading desk · AI scanner › TC-16 a row opens the Chart tab with that stock, and the selected stock's row is marked (1.2s)
  ✓  30 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:383:3 › Smart trading desk · AI scanner › an empty scan says so and names the scan date (745ms)
  ✓  29 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:373:3 › Smart trading desk · AI scanner › TC-17 one scanner route fails → the other's rows and a note naming the route (1.5s)
  ✓  31 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:395:3 › Smart trading desk · Chart analysis and risk desk › TC-18 1M / 3M / 6M draw 22 / 63 / 126 daily candles; the readout moves with the arrow keys (1.4s)
  ✓  32 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:426:3 › Smart trading desk · Chart analysis and risk desk › TC-19 indicator tiles equal the formulas worked out here from the bars (1.2s)
  ✓  28 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:364:3 › Smart trading desk · AI scanner › TC-17 both scanner routes fail → error with retry (3.8s)
  ✓  33 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:460:3 › Smart trading desk · Chart analysis and risk desk › TC-20 levels and reward : risk come from the pick, not the watchlist (986ms)
  ✓  34 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:505:3 › Smart trading desk · Chart analysis and risk desk › a stock with no events on record fails one gate check and its estimate is withheld from high-confidence display (935ms)
  ✓  36 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:535:3 › Smart trading desk · Chart analysis and risk desk › TC-21 chart-live 403 → charting locked for the account (1.0s)
  ✓  35 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:517:3 › Smart trading desk · Chart analysis and risk desk › a symbol that is not on the scanner shows the chart and indicators, and no levels (1.3s)
  ✓  37 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:545:3 › Smart trading desk · Chart analysis and risk desk › TC-21 chart-live 404 → no prices on record (1.0s)
  ✓  38 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:552:3 › Smart trading desk · Chart analysis and risk desk › TC-22 position size: the worked example from the pick, toggles recompute, and the 25% warning (1.3s)
  ✓  40 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:610:3 › Smart trading desk · Chart analysis and risk desk › Ask Copilot hands the setup question to the Copilot (1.1s)
  ✓  39 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:591:3 › Smart trading desk · Chart analysis and risk desk › TC-23 the paper-trade and alert actions are disabled, explained, and send nothing (1.8s)
  ✓  41 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:634:5 › Smart trading desk · scanner and chart at 390px › TC-7 scanner tab: no sideways page scroll (680ms)
  ✓  42 [copilot-app] › e2e/tests/copilot-app-desk-scanner.spec.ts:634:5 › Smart trading desk · scanner and chart at 390px › TC-7 chart tab: no sideways page scroll (846ms)
  ✓  43 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:104:3 › Smart trading desk — shell › TC-1: the Trader rail lists the Smart trading desk first and opens it with six tabs (1.1s)
  ✓  45 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:166:3 › Smart trading desk — shell › TC-3: an unknown ?tab= opens the Overview (940ms)
  ✓  47 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:225:3 › Smart trading desk — shell › TC-5: below 1400px there is no dock and the shell ask box is there (1.2s)
  ✓  46 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:174:3 › Smart trading desk — shell › TC-4: from 1400px the Copilot is docked, the shell ask box is hidden, and a chip is asked as a trader (2.5s)
  ✓  44 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:134:3 › Smart trading desk — shell › TC-2: a tab click sets ?tab=; a deep link opens that tab with that stock; a bad symbol is dropped (3.5s)
  ✓  48 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:238:3 › Smart trading desk — shell › TC-6: a failed answer shows an error line in the dock with a retry, and the desk stays up (1.3s)
  ✓  49 [copilot-app] › e2e/tests/copilot-app-desk.spec.ts:257:3 › Smart trading desk — shell › TC-7: at 390px there is no sideways page scroll and the tab strip scrolls inside itself (760ms)

  49 passed (25.6s)
```

Regression — every copilot-app spec (17 existing + 4 desk), same build, final run:
```
  23 skipped
  365 passed (4.2m)
```
(365 = 316 existing + 49 desk; the 23 skips are pre-existing: SHOT_DIR screenshot captures, LIVE_TOKEN_FILE / REPLAY_DIR live-staging specs, and the unregistered advisor SIP board.)

Layout check: screenshots at 1440 (docked Copilot), 1280 and 390 looked at during the work (temporary, not committed). Found and fixed: beside the dock the scanner's 8-column table (needs 920px) was cut; the scanner now shows its card list whenever its own box is narrower than that (asserted in TC-4 / TC-5).

## Not connected (design parts with no data source — each renders a "Not connected yet" block or is left out, never sample numbers)
| Design part | Why | What would connect it |
|---|---|---|
| Sector strength 1W / 1M | market-dashboard serves one period (today live, or 5-day EOD) | `ret_1d_pct` / `ret_20d_pct` on `sector_heatmap` |
| Bulk / block deals | only `GET /api/movers/candidates`, behind the move_odds flag | an open bulk/block-deal feed route |
| SEBI / exchange circulars | no feed exists | a circulars ingest + route |
| Scanner per-row 24-session sparkline, "liquid only" toggle | not in the watchlist/picks routes | closes + liquidity in the scanner response |
| Next support / resistance in Setup check | the watchlist route reads `resistance_level` / `support_level` but does not send them | add them to the watchlist response |
| Add to paper trades · Alert on trigger | paper trades are chosen by the model engine (no create route); no price-alert route | user paper-trade create route; price alerts |
| Correlated positions | correlations only inside recommendation_engine/orchestrator.py | a holdings correlation route |
| Market-cap allocation (large / mid / small) | no route | a cap-bucket split on holdings |
| OI build-up across F&O stocks | futures rows carry no previous close; no all-stocks scan | prev close / price change on futures + a scan route |
| One-click paper strategies | no rules engine, no create route | (links to the existing Options lab builder instead) |
| Move probability beyond the next session | the model has next-session heads only | multi-session heads |
| Intraday index sparks | /home sparks are daily closes | intraday index series |

## Data Correctness (staging)
Read-only queries run 2026-10-14 (app DB `nivesh-staging-postgres` / `portfolio_ingestion` inside `BEGIN READ ONLY … ROLLBACK`; warehouse via `~/.config/nivesh/nidp-psql.sh`, `BEGIN READ ONLY … ROLLBACK`).

App DB (backs the scanner, setup levels, risk desk, market-dashboard fallback):
```
positional_signals rows | 0
stock_technical_features rows | 0
chartink_scan_hits rows | 0
stock_ohlcv |  |  | 0 | 0
macro_state | 3 | 2026-10-13
macro_daily | 2
```
Warehouse (backs F&O, charts, filings, flows, move odds):
```
 fno_bhavcopy | 2026-10-13 | 37400 |   219
 prices_eod | 2026-10-13 |        3648
 prices_eod_adjusted | 2026-10-13 | 2025-10-01 |      2691
 RELIANCE sessions since 2026-01-01 |   192
 corporate_announcements | 2026-10-14 13:38:42+05:30 |    1248 |          1235
 fii_dii_flows | 2026-10-13 |    3
 tpd_runs: (0 rows)
```
Findings:
- **Scanner data is empty on staging.** The positional engine (`scripts.run_positional_engine`: bhavcopy → chartink scans → score) has never run on the CloudPe app VM: `deploy/nivesh-app/positional-engine.cron` targets the old GCP container `nivesh-backend` and is not installed (`/etc/cron.d` has only the research-watchlist refresh). The desk's Scanner, setup levels and risk desk will show their empty states on staging until it runs. Running it writes to shared staging, so it waits for the user's go-ahead.
- **Move odds are not published on staging** (`nidp.tpd_runs` empty): the nightly model runs in preview mode by the user's choice (2026-10-13), so every probability shows the "not published" state.
- F&O bhavcopy, adjusted daily prices (enough for 6-month candles + EMA50), classified filings and the regime (`macro_state`) are fresh. FII/DII has only 3 days stored, so the Intel FII/DII table shows 3 rows.
- TC-36 result: **partial** — 4 of 6 data sources fresh; scanner tables empty; move-odds runs empty by design.

## Inputs required from user
- Merge `feat/copilot-trading-desk` into `dev` (this session cannot push to dev); then the staging UI check can run on https://staging.niveshcopilot.com:8443/v5/app/trader/desk.
- Go-ahead (or not) to run the positional engine on staging (`python -m scripts.run_positional_engine` in `nivesh-staging-app-backend`, and/or install its cron): it writes `stock_ohlcv`, `chartink_scan_hits`, `stock_technical_features`, `positional_signals` on shared staging. Until then the scanner, setup levels and risk desk show their empty states there.

Status: the desk is built and VERIFIED on a local production build with mocked APIs (49/49 desk tests, all copilot-app specs 365 passed, 23 skipped, 0 failed, tsc clean). NOT verified on staging: the branch is not deployed (needs the user's merge), and the staging scanner tables are empty. Recorded in test_reports/OVERRIDE_copilot_trading_desk.md.

## Verdict: BLOCKED
