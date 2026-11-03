# OVERRIDE — Trade Desk › Chart Analysis › Live chart (feat/desk-live-chart-design)

REASON: staging runs `dev`, so the two new read-only routes (`GET /api/fno/{symbol}/futures/oi-buildup`, `GET /api/desk/live-chart/{symbol}`) cannot be called over HTTP on staging until this PR is merged and the backend process restarts; and the platform Kite session was not logged in on 28 Oct (`TokenException, AUTH_EXPIRED`), so the intraday paths (15m candles, futures OI per 4-bar window, 15m conditions) could not be read on real data. Everything else is verified: pytest (31 new + touched suites 193 passed; CI allowlist 6779 passed, 3 known network-only failures), Playwright (live-chart 11 + regressions, 116 passed after the fix; 308 passed in the wider run before it), and a read-only staging check of the real shapes (NFO list, bhavcopy futures, chain, signals, trade_plans) — see `test_reports/desk_live_chart_2026-10-28.md`.

To close after merge (read-only):
1. Probe `GET /api/desk/live-chart/HDFCBANK` and `GET /api/fno/HDFCBANK/futures/oi-buildup` with a signed-in session: 200, `timeframe.interval: "1d"` with the Kite reason while Kite is not logged in, `mode: "end_of_day"`.
2. After the day's Kite login: the same two calls give `timeframe.interval: "15m"` and `mode: "intraday"` with three months (or two plus `missing_slots`), and the consolidated OI change of a window equals the sum of the three.
3. Open `/v5/app/trader/desk?tab=trade&view=chart&sub=live&sym=HDFCBANK` and capture desktop and 390 px screenshots.
