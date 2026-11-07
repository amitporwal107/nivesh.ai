# Functionality Verification Report — Real-time paper P&L dashboard

- **Branch:** feat/paper-pnl-dashboard (worktree /home/deploy/nivesh-wt-paper-pnl, from origin/dev 50a53a8b)
- **Date:** 2026-11-04 (market open; runs 09:31–09:45 IST)
- **Author:** Claude (Full Stack Developer + QA + Design Engineer)
- **Environment:** staging (CloudPe app VM: `nivesh-staging-app-backend` container, its Mongo, Redis quote cache, Kite feed, data platform)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner's spec (`nivesh_realtime_pnl_dashboard_spec.md`, 4 Nov) built as Trade Desk › Paper Trading › **P&L dashboard**
(`?tab=trade&view=paper&sub=pnl`), paper only, standard trading words allowed on this screen (owner answers, 4 Nov ~09:00 IST).
Backend: `GET /api/desk/pnl`, `/api/desk/pnl/stream` (SSE), `/api/desk/pnl/timeseries`, all read-only, on a weighted-average P&L
engine fed by the existing paper ledger (no second store). Frontend: header with feed/connection state, filters, KPI cards,
segments, intraday P&L chart, positions table (structures grouped with legs, fills on expand, CSV), pending entries, risk panel and
alerts, closed trades and analytics; phone layout with cards. Design: docs/paper_pnl_dashboard/DESIGN.md.

Scope verified here: the BRANCH code on staging's real data (inside the staging backend container) and the branch frontend build
with mocked APIs plus the real staging payload rendered. **Not yet verified: the deployed app after merge** (see Unverified).

## Test Cases
Authored up front: test_reports/paper_pnl_dashboard_TESTCASES.md (written before implementation, 09:20 IST).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-001 | engine | Buy 100 @ 500, LTP 510 | unit | +1,000 | PASS |
| TC-002/003 | engine | Sell 40 @ 520; 60 left at 530 | unit | realized +800, unrealized +1,800 | PASS |
| TC-004 | engine | Buy 100 @ 500, sell 150 @ 490 | unit | −1,000, short 50 @ 490 | PASS |
| TC-005 | engine | Short 100 @ 500, LTP 490 | unit | +1,000 | PASS |
| TC-006 | engine | Two option legs | unit | strategy = sum of legs, not added twice | PASS |
| TC-007 | engine | Duplicate execution id | unit | counted once | PASS |
| TC-008 | prices | Delayed quote in session; feed not connected | unit | DELAYED + STALE_PRICE; FEED critical | PASS |
| TC-009 | engine | Same instrument, two trades | unit | two positions | PASS |
| TC-010 | recon | Closed strategy per leg | unit | equals stored realized | PASS |
| TC-011 | recon | Stored ≠ engine | unit | RECONCILIATION_MISMATCH | PASS |
| TC-012 | charges | Charge change | unit | net moves, gross does not | PASS |
| TC-013 | engine | Fills at different prices | unit | weighted average | PASS |
| TC-014 | prices | No price | unit | null, complete=false, CRITICAL alert, never 0 | PASS |
| TC-015 | prices | After 15:30 | unit | Kite close (provisional) | PASS |
| TC-016 | prices | Contract off the feed; T-1 last trade; older | unit | REST LIVE; T-1 DELAYED no day figure; older → EOD | PASS |
| TC-017 | ledger | Waiting entry | unit | not a position; pending list | PASS |
| TC-018 | risk | Stop hit / near / target | unit | statuses + alerts, "evening check" wording | PASS |
| TC-019 | risk | EOD exit not yet written | unit | EXIT_DUE | PASS |
| TC-020 | risk | Expiry today | unit | EXPIRY alert | PASS |
| TC-021 | filters | Segment / period / bad values | unit | filtered sums; ValueError | PASS |
| TC-022 | analytics | +3000 / −1000 / −1000 | unit | 33.3 %, PF 1.5, DD −2,000 | PASS |
| TC-023 | day P&L | Held vs opened today | unit | prev-close vs avg basis | PASS |
| TC-024 | curve | Carry forward, missing | unit | as computed by hand | PASS |
| TC-025 | read-only | Dashboard reads | unit + staging | no writes (fake DB count; staging docs unchanged) | PASS |
| TC-026 | api | No session (GET and stream) | staging | 401 | PASS |
| TC-027 | api | Owner's real book | staging | 200; avg/qty = stored fills; rows sum = summary | PASS |
| TC-028 | api | Stream | staging | event-stream, rising sequence | PASS |
| TC-029 | api | Timeseries | staging | points today, missing listed | PASS |
| TC-030 | api | segment=FOO | staging | 422 | PASS |
| TC-031 | data | LTP vs Redis cache | staging | equal | PASS |
| TC-032 … TC-039 | e2e | Sub-view, cards, filters, fills, CSV, stream → polling, phone, errors | Playwright | as specified | PASS |
| TC-040 | wording | No recommend / pick / suggested | unit + e2e | none | PASS |

## API / Endpoint Tests (staging)
Harness (scratchpad `pnl_staging_check.py`): the branch's `routes/desk_pnl.py` + `services/paper_pnl/` loaded ahead of the deployed
copy INSIDE `nivesh-staging-app-backend` (real Mongo, Redis, Kite feed status, Kite REST with the platform token, data platform).
TC-026 uses the REAL `get_current_user`. For the owner's data the harness sets the user id (`user_845232f38371`); no session token
was read or used. Files removed from the container afterwards. Real output, final code, 09:43 IST:
```
TC-026 no session -> HTTP 401 {"detail":"Not authenticated"}
TC-026 stream no session -> HTTP 401
TC-030 segment=FOO -> HTTP 422 {"detail":"invalid_segment"}
TC-027 owner GET /api/desk/pnl?period=ALL -> HTTP 200 in 2.33s, 22,646 bytes
   warm calls (book cached, Redis + REST cache): HTTP 200, ms [10, 9, 8, 7, 7]
  SYNGENE    LONG qty 941.0 avg 405.8 ltp 409.45 prev 406.6 [LIVE Kite live at 2026-11-04T09:43:48.223000+05:30 age 1.0s]
     TC-031 Redis SYNGENE ltp 409.45
  MSUMI      LONG qty 11922.0 avg 38.81 ltp 39.2 prev 38.93 [LIVE Kite live at 2026-11-04T09:43:45.229000+05:30 age 4.0s]
     TC-031 Redis MSUMI ltp 39.2
  SONACOMS   LONG qty 44.0 avg 879.45 ltp 901.2 prev 900.0 [LIVE Kite live at 2026-11-04T09:43:48.464000+05:30 age 0.7s]
     TC-031 Redis SONACOMS ltp 901.2
  COFORGE    LONG qty 18.0 avg 2010.81 ltp 2068.0 prev 2060.8 [LIVE Kite live at 2026-11-04T09:43:45.227000+05:30 age 4.0s]
     TC-031 Redis COFORGE ltp 2068.0
  ICICIBANK  LONG qty 35.0 avg 1413.21 ltp 1430.0 prev 1424.5 [LIVE Kite live at 2026-11-04T09:43:46.216000+05:30 age 3.0s]
     TC-031 Redis ICICIBANK ltp 1430.0
  DRREDDY    LONG qty 625.0 avg 1369.5 ltp 1372.0 prev 1368.3 [LIVE Kite live at 2026-11-04T09:43:45.226000+05:30 age 4.0s]
     TC-031 Redis DRREDDY ltp 1372.0
  DRREDDY 23 Nov 2026 1360 PE LONG qty 625.0 avg 21.85 ltp 20.25 prev 26.55 [LIVE Kite quote (contract off the live feed) at 2026-11-04T09:43:33+05:30 age 16.2s]
  SONACOMS 23 Nov 2026 900 CE LONG qty 1225.0 avg 28.4 ltp 26.9 prev 26.15 [DELAYED Kite quote (contract off the live feed) at 2026-11-04T09:41:57+05:30 age 112.2s]
  SONACOMS 23 Nov 2026 1020 CE SHORT qty -1225.0 avg 1.6 ltp 1.8 prev 1.6 [DELAYED Kite quote (contract off the live feed) at 2026-11-04T09:40:42+05:30 age 187.2s]
  alert WARNING STALE_PRICE 4 position(s) are not priced live: BOSCHLTD 23 Nov 2026 49500 CE, LAURUSLABS 23 Nov 2026 2680 CE, SONACOMS 23 Nov 2026 1020 CE, SONACOMS 23 …
  DATA rows sum unrealized 12727.05 == summary 12727.05; rows net 5553.74 == summary net 5553.74
TC-028 stream -> HTTP 200 text/event-stream; charset=utf-8 in 9.1s: 3 snapshot events, heartbeats 0, sequences rising True
    1793765629210 {'SYNGENE': 409.45, 'MSUMI': 39.2, 'SONACOMS': 1.8, 'COFORGE': 2068.0, 'ICICIBANK': 1430.0, 'DRREDDY': 20.25, …}
    1793765632225 {'SYNGENE': 409.45, 'MSUMI': 39.19, 'SONACOMS': 1.8, 'COFORGE': 2067.7, 'ICICIBANK': 1430.0, 'DRREDDY': 20.25, …}
    1793765635279 {'SYNGENE': 409.3, 'MSUMI': 39.19, 'SONACOMS': 1.8, 'COFORGE': 2068.0, 'ICICIBANK': 1429.9, 'DRREDDY': 20.6, …}
TC-029 timeseries 5m -> HTTP 200 in 6.3s: date 2026-11-04 is_today True points 6 baseline 5867.61 used [14 positions] missing [1]
TC-025 on staging: owner's trade documents unchanged by the dashboard reads: True (10 docs)
```
(The "TC-031 Redis" lines also printed the cache's `exchange_ts`, e.g. `2026-11-04T04:13:47+05:30` at 09:43 IST — see Findings.)

pytest (throwaway `nivesh/backend:staging` container, branch tree read-only, `--network none`), final code:
```
$ python -m pytest tests/test_paper_pnl.py tests/test_desk_trading.py tests/test_desk_strategy_trades.py tests/test_paper_account.py tests/test_desk_paper_sim.py tests/test_paper_fills_pnl.py -q -p no:cacheprovider
272 passed, 2 warnings in 14.85s
$ python -c "import server; …"   ->  routes ['/api/desk/pnl', '/api/desk/pnl/stream', '/api/desk/pnl/timeseries']
```

## UI / Playwright Tests
Production build (`VITE_BASE=/v5/ vite build` + `vite preview`), `pw.copilot-app.config.ts`, Playwright 1.60 / Chromium 1223,
`--network none`, every `/api/*` route-mocked (MOCK — not real data) except the two scratch cases, which serve the REAL staging
payload captured above (not committed):
```
== tsc
TSC_EXIT=0
== build
BUILD_EXIT=0
bundles with pnl-kpis: 1
== playwright
Running 42 tests using 3 workers
✓ copilot-app-desk-pnl.spec.ts › TC-032 Paper Trading has a third sub-view, P&L dashboard; it opens with sub=pnl and the four-deep crumb, without the paper-trades read
✓ copilot-app-desk-pnl.spec.ts › TC-033 header, KPI cards, segments, positions with the strategy and its legs, waiting entries, alerts, chart
✓ copilot-app-desk-pnl.spec.ts › TC-033b a structure with a share leg stays one group; a leg without a price makes the structure incomplete
✓ copilot-app-desk-pnl.spec.ts › TC-034 segment and period go to the route; search, profit/loss and status filter the rows
✓ copilot-app-desk-pnl.spec.ts › TC-035 a row expands to its fills; a leg too
✓ copilot-app-desk-pnl.spec.ts › TC-036 CSV export: one line per shown position or leg, never a strategy total; follows the filters
✓ copilot-app-desk-pnl.spec.ts › TC-037 the stream fails → polling; a newer snapshot updates the rows, an older one is dropped
✓ copilot-app-desk-pnl.spec.ts › TC-037b the stream's problem event: the last snapshot stays, with a quiet warning
✓ copilot-app-desk-pnl.spec.ts › TC-038 390 px: summary first, position cards instead of the table, cards expand; no sideways scroll
✓ copilot-app-desk-pnl.spec.ts › TC-039 the route fails: a problem with Retry, no figures; a missing price is said, never 0
✓ copilot-app-desk-pnl.spec.ts › TC-039b a contract error (no positions list) is a problem, not an empty dashboard
✓ copilot-app-desk-trade-desk.spec.ts › (29 regression cases, all ✓)
✓ copilot-app-zz-realshape.spec.ts › real staging payload renders at 1280px
✓ copilot-app-zz-realshape.spec.ts › real staging payload renders at 390px
  42 passed (28.9s)
REAL 1280px OK; … | Real-time P&L | PAPER | Market feed live | Polling every 3 s | … | NET P&L | −₹972.45 | …
```
Screenshots of the real payload (scratchpad pw-me/real-1280.png, real-390.png, real-table.png, real-chart.png) checked by eye:
structures above their legs, LIVE / DELAYED badges with times, the T-1 leg "DELAYED 3 Nov 15:03", the chart with its baseline.

## Data Correctness (staging)
- Mongo `desk_paper_trades` (owner): every one of the 15 positions' average price and quantity equals the stored fill — the
  POSITION_OPEN transition's `fill_price` for share trades (SONACOMS 879.45, a gapped break-above fill, not the 868.87 reference),
  and `entry_price` × side × lots × lot size for each structure leg (`match True` × 10). PASS
- Redis `nivesh:quote:NSE:<SYM>`: the six live stock prices equal the cache at the same moment. PASS
- Read-only: the owner's 10 trade documents (id, status, updated_at) identical before and after all reads. PASS

## Findings on real data (fixed in this branch unless noted)
1. **Feed timestamp bug (NOT fixed here, separate):** the live feed's `exchange_ts` is the container's UTC clock labelled +05:30
   (`04:13:47+05:30` at 09:43 IST). The dashboard measures freshness from the feed's `received_at` instead; any other screen that
   ages a quote by `exchange_ts` would be 5 h 30 m off.
2. A non-leader worker kept the previous day's Kite token (REST `TokenException`): fixed by reloading it (`platform_token.refresh_cache`, at most once a minute), as other modules do.
3. An illiquid leg not yet traded today: its previous session's last trade is used (owner's T-1 rule), DELAYED, with no day figure.

## Unverified
- UNVERIFIED: the deployed route through nginx and the deployed frontend, because nothing is merged. After a merge to dev: probe
  `GET /api/desk/pnl` (404 → 401 once the backend restarts) and grep the served bundle for `pnl-kpis`; then open the screen in a
  signed-in browser.
- UNVERIFIED: the owner's session through the real auth on the owner's data (the harness set the user id; the 401 path ran through the real auth).
- Load: one REST `quote()` per worker per 5 s per contract set; fine for staging's one user, not load-tested for many users.

## Inputs required from user
- none

## Verdict: PASS
