# Real-time paper P&L dashboard — test cases (authored before implementation, 4 Nov 2026)

Design: docs/paper_pnl_dashboard/DESIGN.md. Spec: owner's nivesh_realtime_pnl_dashboard_spec.md §13.2 (TC-001…TC-012 kept
with their numbers), plus the cases this repo needs. Backend unit = `backend/tests/test_paper_pnl.py`; API = staging (branch
router inside the staging backend container, owner's session); e2e = `frontend-v5/e2e/tests/copilot-app-desk-pnl.spec.ts`.

| ID | Area | Case | Type | Expected |
|---|---|---|---|---|
| TC-001 | engine | Buy 100 @ 500, LTP 510 | unit | unrealized +1,000 |
| TC-002 | engine | Buy 100 @ 500, sell 40 @ 520 | unit | realized +800, net qty 60, avg 500 |
| TC-003 | engine | Remaining 60, LTP 530 | unit | unrealized +1,800, gross +2,600 |
| TC-004 | engine | Buy 100 @ 500, sell 150 @ 490 | unit | realized −1,000, short 50 @ 490 |
| TC-005 | engine | Short 100 @ 500, LTP 490 | unit | unrealized +1,000 |
| TC-006 | engine | Two option legs (buy call, sell call) | unit | strategy P&L = sum of legs; not added twice to totals |
| TC-007 | engine | Same execution id twice | unit | counted once |
| TC-008 | prices | Session open, quote older than the stale limit | unit | price_status DELAYED, STALE_PRICE alert, summary.stale_positions 1 |
| TC-009 | engine | Same instrument in two paper trades | unit | two positions, separate ids, separate P&L |
| TC-010 | engine | Closed strategy: exit marks per leg | unit | realized per leg reconciles with stored realized_pnl_rs |
| TC-011 | recon | Stored realized ≠ engine realized | unit | RECONCILIATION_MISMATCH alert with both figures |
| TC-012 | charges | Charges change | unit | net changes, gross does not |
| TC-013 | engine | Multiple fills at different prices | unit | weighted average |
| TC-014 | prices | No price at all for an open position | unit | P&L null, summary.complete false, unpriced_positions 1; never 0 |
| TC-015 | prices | After 15:30 with a saved Kite close | unit | price_status CLOSE, source "Kite close" |
| TC-016 | prices | Contract not on the feed, REST quote available | unit | priced from the REST quote, LIVE |
| TC-017 | ledger | Waiting conditional entry | unit | not a position; listed in pending_entries |
| TC-018 | risk | Long below its stop / within 1 % / above target | unit | STOP_LOSS_HIT (CRITICAL), NEAR_STOP_LOSS (WARNING), TARGET_REACHED |
| TC-019 | risk | EOD exit fired but not yet written (persist=False) | unit | status EXIT_DUE + alert |
| TC-020 | risk | Option leg expiring today | unit | EXPIRY alert |
| TC-021 | filters | segment=OPTIONS / period=1W | unit | only those positions / closed trades counted in the summary |
| TC-022 | analytics | Closed trades +3000, −1000, −1000 | unit | win rate 33.3 %, profit factor 1.5, max drawdown −2,000 |
| TC-023 | day P&L | Held from before today vs opened today | unit | (LTP − prev close) × qty vs (LTP − avg) × qty |
| TC-024 | timeseries | Two symbols, one missing a candle | unit | carried forward; a symbol with no candles in `missing` |
| TC-025 | read-only | Building the dashboard | unit | no Mongo write (exits run with persist=False) |
| TC-026 | api | GET /api/desk/pnl without a session | api (staging) | 401 |
| TC-027 | api | GET /api/desk/pnl, owner (3 real open trades) | api (staging) | 200; 3 positions; avg = stored fill; summary sums the rows; data test vs Mongo |
| TC-028 | api | GET /api/desk/pnl/stream | api (staging) | text/event-stream; ≥ 2 `snapshot` events with rising `sequence` |
| TC-029 | api | GET /api/desk/pnl/timeseries | api (staging) | 200; points for the session or `missing` with reasons |
| TC-030 | api | Bad filter (segment=FOO) | api (staging) | 422 |
| TC-031 | data | Live LTP vs Kite quote cache in Redis | data (staging) | equal to the cached ltp at the same moment (± one tick) |
| TC-032 | e2e | Paper Trading shows a third sub-view "P&L dashboard" | e2e | chip visible; URL sub=pnl |
| TC-033 | e2e | KPI cards, positions table, strategy legs, alerts render from the mock | e2e | figures as in the MOCK payload |
| TC-034 | e2e | Segment filter and search | e2e | rows filtered; request carries segment |
| TC-035 | e2e | Expand a position → executions | e2e | fills listed |
| TC-036 | e2e | CSV export | e2e | download with the filtered rows |
| TC-037 | e2e | Stream fails → polling fallback; stale price badge | e2e | "Polling" state, rows still update |
| TC-038 | e2e | Phone 390 px | e2e | cards instead of table, no horizontal overflow |
| TC-039 | e2e | Error from the API | e2e | problem block with retry, no fake numbers |
| TC-040 | wording | Compliance lint over new strings | unit | only the owner-approved words for this screen |
