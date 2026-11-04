# Functionality Verification Report — P&L dashboard v2 (the owner's "Real-Time PnL Dashboard" design)

- **Branch:** feat/paper-pnl-dashboard-v2 (17c3b3e3 docs · 8039bd05 PATCH levels · 95fd61e5 P&L backend · c869a6a5 screen), from origin/dev e27f8f4e
- **Date:** 2026-11-04
- **Author:** Claude (Full Stack Developer + Design Engineer + QA)
- **Environment:** staging (branch code loaded inside nivesh-staging-app-backend: real Mongo, Redis feed quotes and scan signals, Kite REST/historical, the owner's broker accounts read-only)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner pasted "Real-Time PnL Dashboard (standalone).html" and asked to change the P&L dashboard to it. Decisions (AskUserQuestion,
~14:50 IST): Live = read-only broker NET positions; Modify risk = edit the stop loss / target of an open paper share trade, in force
from the next session. Built: `GET /api/desk/pnl(+stream)` with `mode`/`account`, `accounts`, `modes`, live rows; per-trade curve and
mode curve on `/timeseries`; `GET /api/desk/pnl/journal/{id}` (the Scan dashboard's entry-day signal); `PATCH /api/desk/paper-trades/{id}/levels`;
the screen in the design's order (rows open to breakdown, fills, actions, Chart Analysis candles with the levels, the journal, the trade
curve). Contract: docs/paper_pnl_dashboard/DESIGN.md "v2". Verified here: unit + CI allowlist, staging API on the owner's account with
two MOCK paper share trades on real symbols (removed afterwards), Playwright mocked + a render of the real staging answers.

## Test Cases
Authored before implementation: test_reports/paper_pnl_dashboard_v2_TESTCASES.md (V2-01..V2-28).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| V2-01 | api | mode=PAPER/LIVE/ALL; mode=XYZ | unit + staging | filtered; 422 invalid_mode | PASS |
| V2-02 | api | account=paper / not the user's | unit + staging | filtered; 422 invalid_account | PASS |
| V2-03 | api | accounts with states whatever the filters | unit + staging | paper OK; Zerodha + ICICI Direct SIGN_IN with the broker's note | PASS |
| V2-04 | api | modes.PAPER / modes.LIVE unfiltered | unit + staging | both present | PASS |
| V2-05 | live | broker rows: signed qty, resolver LTP, unrealized, realized null, broker_pnl | unit | as stated | PASS (unit only: both sessions expired) |
| V2-06 | live | broker read fails | unit + staging | SIGN_IN, snapshot 200, LIVE unavailable with reason | PASS |
| V2-07 | live | read cached ≤ 60 s; STALE after 2×TTL | unit | as stated | PASS |
| V2-08 | live | contract unmappable / no price | unit | MISSING, out of totals | PASS |
| V2-09 | live | no stop/target/journal; editable_levels false | unit + e2e | as stated | PASS |
| V2-10 | timeseries | mode curve; trade curve since entry; unknown → 404 | unit + staging | as stated | PASS |
| V2-11 | journal | strong / scored / none / old / structure / not the user's | unit + staging | strong 74/100 (BHARTIARTL), scored 64 (RELIANCE), 404 | PASS |
| V2-12 | levels | valid PATCH | unit + staging | 200, level_changes v1, pending from 2026-11-05 | PASS |
| V2-13 | levels | simulator: day D's bar keeps the old stop | unit | no hindsight | PASS |
| V2-14 | levels | target likewise; trail from the new stop | unit | as stated | PASS |
| V2-15 | levels | 404/409/422 codes, unknown field, no change, 401 | unit + staging | as stated | PASS |
| V2-16 | levels | Idempotency-Key replay; the screen's exact body | unit + staging | replayed, one change | PASS |
| V2-17 | levels | audit row; only level_changes/level_version/updated_at change | unit + staging | as stated | PASS |
| V2-18 | read-only | P&L reads write no trade | unit + staging | trade docs unchanged | PASS |
| V2-19..V2-26 | e2e | order, filters, row detail, Modify risk, exits, Pause, 390 px, wording | e2e (mocked) | as stated | PASS |
| V2-27 | staging | real data end to end + cleanup | staging | consistent; restored | PASS |
| V2-28 | e2e | real staging answers rendered at 1280 + 390 px | e2e | renders, no errors, no sideways scroll | PASS |

## API / Endpoint Tests (staging)
Script: scratchpad/pnl2_staging_check.py, run inside nivesh-staging-app-backend (`docker exec … python /tmp/pnl2_staging_check.py`),
4 Nov 15:41 IST (market closed; today's Kite close not yet saved, so prices are the 3 Nov end-of-day marks, labelled EOD — the v1
price rule). 401 is the real auth; the owner's data with `get_current_user` returning the owner. MOCK trades: BHARTIARTL ×10 and
RELIANCE ×5 created through the real create route (risk gate included), BHARTIARTL's opened_at moved to 09:20 IST (MOCK only) so
its since-entry curve meets today's candles. Real output, unedited except the two broker account ids masked (log lines filtered):

```
V2-01 no session GET /api/desk/pnl?mode=LIVE -> HTTP 401
V2-01 no session GET /api/desk/pnl/journal/x -> HTTP 401
V2-15 no session PATCH levels -> HTTP 401
watched collections: {'desk_chartink_hits': 773, 'paper_account_ledger': 1, 'risk_controls': 1, 'audit_log': 89, 'broker_sync_snapshots': 47, 'risk_control_audit': 15, 'desk_chartink_sources': 1, 'ai_trader_strategies': 2, 'risk_decisions': 41, 'paper_accounts': 1, 'desk_price_alerts': 2, 'position_snapshots': 1, 'action_plans': 4}
V2-01/03 GET pnl mode=ALL (empty paper book) -> HTTP 200 in 0.01s
  mode ALL filters {'segment': 'ALL', 'period': 'TODAY', 'from': '2026-11-04', 'to': '2026-11-04', 'mode': 'ALL', 'account': 'ALL'}
  account {'account_id': 'paper', 'name': 'Paper account', 'mode': 'PAPER', 'state': 'OK', 'state_note': None, 'open_positions': 0, 'net_pnl': 0.0, 'capital': 10000000.0}
  account {'account_id': 'ba_<masked>', 'name': 'ICICI Direct', 'mode': 'LIVE', 'state': 'SIGN_IN', 'state_note': 'Your ICICI Direct session has ended. Reconnect the account to continue.', 'open_positions': 0, 'net_pnl': None, 'capital': None}
  account {'account_id': 'ba_<masked>', 'name': 'Zerodha', 'mode': 'LIVE', 'state': 'SIGN_IN', 'state_note': 'Your Zerodha session has ended. Reconnect the account to continue.', 'open_positions': 0, 'net_pnl': None, 'capital': None}
  modes PAPER {'net_pnl': 0.0, 'open_positions': 0, 'available': True, 'note': None, 'capital': 10000000.0}
  modes LIVE {'net_pnl': 0.0, 'open_positions': 0, 'available': False, 'note': 'No broker account could be read: ICICI Direct: Your ICICI Direct session has ended. Reconnect the account to continue.; Zerodha: Your Zerodha session has ended. Reconnect the account to continue.', 'capital': None}
V2-01/02 GET pnl {'mode': 'XYZ'} -> HTTP 422 {"detail":"invalid_mode"}
V2-01/02 GET pnl {'account': 'not-mine'} -> HTTP 422 {"detail":"invalid_account"}
last completed sessions {'BHARTIARTL': (datetime.date(2026, 11, 3), 2065.0), 'RELIANCE': (datetime.date(2026, 11, 3), 1307.9)}
MOCK create BHARTIARTL @ 2065.0 stop 1970.84 target 2245.82 -> HTTP 201 
MOCK create RELIANCE @ 1307.9 stop 1268.66 target 1425.61 -> HTTP 201 
  ids {'BHARTIARTL': 'b4e0beb6-f5b5-4ecd-857e-fab363d50b95', 'RELIANCE': 'd16b7449-8f91-4a68-815c-4b082df77bba'}
  MOCK BHARTIARTL opened_at moved from 2026-11-04T10:11:41.848882+00:00 to 09:20 IST
V2-01 GET pnl mode=PAPER -> HTTP 200 in 0.07s summary {'net_pnl': -182.1, 'gross_pnl': 0.0, 'unrealized_pnl': 0.0, 'realized_pnl': 0, 'charges_estimated': 182.1, 'open_positions': 2, 'exposure_rs': 27189.5, 'complete': True}
  row {'mode': 'PAPER', 'account_id': 'paper', 'instrument': 'RELIANCE', 'side': 'LONG', 'net_quantity': 5.0, 'avg_price': 1307.9, 'ltp': 1307.9, 'price_status': 'EOD', 'unrealized_pnl': 0.0, 'charges_estimated': 68.3, 'net_pnl': -68.3, 'stop_loss': 1268.66, 'target': 1425.61, 'risk_used_pct': 0.0, 'exposure_rs': 6539.5, 'editable_levels': True, 'pending_levels': None, 'status': 'ACTIVE'}
  row {'mode': 'PAPER', 'account_id': 'paper', 'instrument': 'BHARTIARTL', 'side': 'LONG', 'net_quantity': 10.0, 'avg_price': 2065.0, 'ltp': 2065.0, 'price_status': 'EOD', 'unrealized_pnl': 0.0, 'charges_estimated': 113.8, 'net_pnl': -113.8, 'stop_loss': 1970.84, 'target': 2245.82, 'risk_used_pct': 0.0, 'exposure_rs': 20650.0, 'editable_levels': True, 'pending_levels': None, 'status': 'ACTIVE'}
  risk.margin {'used_pct': 0.27, 'basis': 'Paper: capital blocked by open trades, not exchange margin.'} risk.exposure_rs 27189.5
V2-01 GET pnl mode=LIVE -> HTTP 200 in 0.00s summary {'net_pnl': 0, 'gross_pnl': 0, 'unrealized_pnl': 0, 'realized_pnl': 0, 'charges_estimated': 0, 'open_positions': 0, 'exposure_rs': 0, 'complete': True}
  risk.margin {'used_pct': None, 'basis': 'Not read from brokers.'} risk.exposure_rs 0
V2-01 GET pnl mode=ALL -> HTTP 200 in 0.00s summary {'net_pnl': -182.1, 'gross_pnl': 0.0, 'unrealized_pnl': 0.0, 'realized_pnl': 0, 'charges_estimated': 182.1, 'open_positions': 2, 'exposure_rs': 27189.5, 'complete': True}
  row {'mode': 'PAPER', 'account_id': 'paper', 'instrument': 'RELIANCE', 'side': 'LONG', 'net_quantity': 5.0, 'avg_price': 1307.9, 'ltp': 1307.9, 'price_status': 'EOD', 'unrealized_pnl': 0.0, 'charges_estimated': 68.3, 'net_pnl': -68.3, 'stop_loss': 1268.66, 'target': 1425.61, 'risk_used_pct': 0.0, 'exposure_rs': 6539.5, 'editable_levels': True, 'pending_levels': None, 'status': 'ACTIVE'}
  row {'mode': 'PAPER', 'account_id': 'paper', 'instrument': 'BHARTIARTL', 'side': 'LONG', 'net_quantity': 10.0, 'avg_price': 2065.0, 'ltp': 2065.0, 'price_status': 'EOD', 'unrealized_pnl': 0.0, 'charges_estimated': 113.8, 'net_pnl': -113.8, 'stop_loss': 1970.84, 'target': 2245.82, 'risk_used_pct': 0.0, 'exposure_rs': 20650.0, 'editable_levels': True, 'pending_levels': None, 'status': 'ACTIVE'}
  risk.margin {'used_pct': 0.27, 'basis': 'Paper: capital blocked by open trades, not exchange margin.'} risk.exposure_rs 27189.5
  market {'session': 'closed', 'feed': 'closed', 'feed_age_seconds': 715.9, 'notes': []}
V2-02 account=paper -> HTTP 200 rows 2
V2-18 trade documents unchanged by the reads: True
V2-10 timeseries mode=PAPER -> HTTP 200 points 24 used ['d16b7449-8f91-4a68-815c-4b082df77bba', 'b4e0beb6-f5b5-4ecd-857e-fab363d50b95'] missing [] last {'t': '2026-11-04T15:00:00+05:30', 'unrealized_pnl': -2.0, 'realized_pnl': 0.0, 'gross_pnl': -2.0, 'net_pnl': -184.1, 'change_since_baseline': 788.5}
V2-10 timeseries mode=LIVE -> HTTP 200 points 0 Kite intraday candles (raw prices), each candle's close; a candle an instrument did not trade in carries its last close 
V2-10 trade curve BHARTIARTL -> HTTP 200 since_entry True from 2026-11-04T09:30:00+05:30 points 23 last {'t': '2026-11-04T15:00:00+05:30', 'gross_pnl': -40.0, 'net_pnl': -153.8}
   basis: Kite intraday candles (raw prices), each candle's close, against the position's average price; net = gross − the estimate for closing it now, held constant. Drawn from the entry. | notes: [] | missing: [] | date 2026-11-04
V2-10 trade curve RELIANCE -> HTTP 200 since_entry True from None points 0 last {}
   basis: Kite intraday candles (raw prices), each candle's close, against the position's average price; net = gross − the estimate for closing it now, held constant. Drawn from the entry. | notes: [] | missing: [{'position_id': 'd16b7449-8f91-4a68-815c-4b082df77bba', 'reason': 'no intraday candles for this instrument since the entry'}] | date 2026-11-04
V2-10 trade curve unknown -> HTTP 404 {"detail":"trade_not_found"}
V2-11 journal BHARTIARTL -> HTTP 200 found True day 2026-11-04 why None
   {'kind': 'strong', 'score': 74, 'parts': {'quality': 24, 'trend': 19, 'reason': 14, 'size': 15, 'participation': 2, 'penalty': 0}, 'entry': 2062.5, 'stop_loss': 1970.84, 'target_1': 2245.82, 'target_2': 2429.14, 'rr_1': 2.0, 'rr_2': 4.0, 'plan_ok': True}
   reasons ['Turning up from the 52-week low (₹1,726.30), above its 50-day average', 'RSI(14) 73', 'Above 8 of 8 daily averages (5 to 200 day)', 'Quality 24/30: ROCE 18.5 %, ROE 16.3 %, debt/equity 0.74, margin 14.0 %, promoter 50.1 %', 'Size 15/15: Nifty 50, market cap ₹1,083,862 cr', 'Volume 1.1× its usual by now', 'In 1 positional-pattern list(s) today'] lists [{'id': 'dt_strong', 'title': 'Strong stocks'}, {'id': 'triple_bottom', 'title': 'Triple bottom'}]
V2-11 journal RELIANCE -> HTTP 200 found True day 2026-11-04 why None
   {'kind': 'scored', 'score': 64, 'parts': {'quality': 14, 'trend': 17, 'reason': 14, 'size': 15, 'participation': 4, 'penalty': 0}, 'entry': None, 'stop_loss': None, 'target_1': None, 'target_2': None, 'rr_1': None, 'rr_2': None, 'plan_ok': False}
   reasons ['Turning up from the 52-week low (₹1,152.20), above its 50-day average', 'RSI(14) 67', 'Above 7 of 8 daily averages (5 to 200 day)'] lists [{'id': 'long_buildup', 'title': 'Long Build Up (fresh)'}, {'id': 'dt_multiyear', 'title': 'Multiyear breakout'}, {'id': 'dt_breakout_15m', 'title': '15 minute stock breakouts'}, {'id': 'dt_rsi_vwap', 'title': 'RSI VWAP intraday'}, {'id': 'triple_bottom', 'title': 'Triple bottom'}]
V2-11 journal unknown -> HTTP 404 {"detail":"journal_not_available"}
Modify risk on the MOCK RELIANCE trade
V2-15 PATCH stop above the last close -> HTTP 422 {"detail":{"code":"stop_not_below_price","message":"The stop loss ₹1,334.06 must be below the last close ₹1,307.90 (2026
V2-15 PATCH no change -> HTTP 422 {"detail":{"code":"no_change","message":"These are already the trade's levels; nothing was changed."}}
V2-15 PATCH unknown field -> HTTP 422 {"detail":"unknown_field"}
V2-12 PATCH valid {'stop_price': 1255.97, 'target_price': 1439.87, 'note': 'MOCK edit from the staging check'} -> HTTP 200
   replayed False level_changes [{'version': 1, 'at': '2026-11-04T10:11:44.542579+00:00', 'session': '2026-11-04', 'stop_price': 1255.97, 'target_price': 1439.87, 'prev_stop': 1268.66, 'prev_target': 1425.61, 'changed': ['stop', 'target'], 'note': 'MOCK edit from the staging check'}] current_stop 1268.66 current_target 1425.61 pending_levels {'stop_loss': 1255.97, 'target': 1439.87, 'from_session': '2026-11-05', 'version': 1}
V2-16 replay same key -> HTTP 200, replayed True, changes now 1
V2-17 trade fields changed by the edit: ['level_changes', 'level_version', 'updated_at']
V2-17 owner documents added since the start: {'paper_account_ledger': 2, 'desk_paper_trades': 2, 'risk_decisions': 3}
V2-12 P&L row after the edit: {'stop_loss': 1268.66, 'target': 1425.61, 'pending_levels': {'stop_loss': 1255.97, 'target': 1439.87, 'from_session': '2026-11-05', 'version': 1}, 'editable_levels': True}
stream -> HTTP 200 text/event-stream; charset=utf-8
   retry: 3000
   snapshot 1 at +0.0s mode ALL seq 1793787106729 positions 2 accounts 3
   snapshot 2 at +30.0s mode ALL seq 1793787136745 positions 2 accounts 3
cleanup: {'paper_account_ledger': 2, 'desk_paper_trades': 2, 'risk_decisions': 3, 'paper_accounts': 1}
owner documents identical to before the run: True
```

Run 3 (15:40 IST, same script before the opened_at step) — the PATCH refusals and the journal of a scored-only stock:

```
V2-15 no session PATCH levels -> HTTP 401
V2-11 journal RELIANCE -> HTTP 200 found True day 2026-11-04 why None
   {'kind': 'scored', 'score': 64, 'parts': {'quality': 14, 'trend': 17, 'reason': 14, 'size': 15, 'participation': 4, 'penalty': 0}, 'entry': None, 'stop_loss': None, 'target_1': None, 'target_2': None, 'rr_1': None, 'rr_2': None, 'plan_ok': False}
V2-15 PATCH stop above the last close -> HTTP 422 {"detail":{"code":"stop_not_below_price","message":"The stop loss ₹1,334.06 must be below the last close ₹1,307.90 (2026
V2-15 PATCH no change -> HTTP 422 {"detail":{"code":"no_change","message":"These are already the trade's levels; nothing was changed."}}
V2-15 PATCH unknown field -> HTTP 422 {"detail":"unknown_field"}
```

- **pytest (combined, both backend parts):** `docker run --rm --network none … nivesh/backend:staging python -m pytest tests/test_paper_pnl.py tests/test_paper_pnl_live.py tests/test_desk_levels_edit.py tests/test_desk_trading.py … (27 files) -q`
```
    warnings.warn(message, FutureWarning)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
830 passed, 2 warnings in 29.40s
```
- **Full CI allowlist** (328 files from .github/workflows/backend-tests.yml, now including test_paper_pnl.py, test_paper_pnl_live.py, test_desk_levels_edit.py):
```
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
FAILED tests/test_cas_api_client.py::test_sandbox_parse_and_map - AssertionEr...
FAILED tests/test_cas_api_client.py::test_convenience_helper_returns_list - a...
FAILED tests/test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches - a...
3 failed, 9527 passed, 52 skipped, 16 warnings in 266.80s (0:04:26)
```
  The 3 failures are pre-existing: the same three fail on a clean `git archive origin/dev` in the same container
  (`3 failed, 19 passed`), outside this change.

## UI / Playwright Tests
Container mcr.microsoft.com/playwright:v1.47.0-jammy, `--network none`, vite build with VITE_BASE=/v5/, pw.copilot-app.config.ts, on the
committed tree c869a6a5:

```
TSC_EXIT=0
BUILD_EXIT=0
  ✓  27 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:317:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-19 the page in the design's order: header, filters, hero + KPIs, mode cards, chart, positions, risk + supervisor, footer, folded extras (1.2s)
  ✓  26 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:301:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › TC-032 Paper Trading's third sub-view opens the dashboard with sub=pnl, without the paper-trades read (2.3s)
  ✓  28 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:406:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-20 mode, account and segment go to the route; search filters the table only (1.8s)
  ✓  29 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:455:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-21 a paper share row opens to breakdown, fills, actions, the candle chart with its levels, the journal and the trade P&L (1.2s)
  ✓  31 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:526:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-21c a live row on the broker's last read is stale and keeps its contract problem; a contract expiring today says so (1.1s)
  ✓  30 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:501:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-21b a live row is read-only: no levels, no journal, the broker's own figure, today's fills note; a structure leg charts the underlying (1.2s)
  ✓  32 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:543:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-22 Modify risk sends only the changed level with an idempotency key; a refusal is shown in words (1.5s)
  ✓  33 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:593:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-23 Simulate exit asks first, then closes through the paper close; Initiate exit on a live row places nothing (1.8s)
  ✓  36 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:666:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › TC-036 CSV export: one line per shown row (paper and live), never a structure total; follows the search (747ms)
  ✓  37 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:685:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-25 390 px: the same order, position cards that open to the same detail, no sideways scroll (740ms)
  ✓  34 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:619:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-24 Pause stops the updates and Resume restarts them; the feed pill says so (5.4s)
  ✓  38 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:703:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › TC-039 the route fails: a problem with Retry, no figures; a missing price is said, never 0 (854ms)
  ✓  40 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:755:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › TC-034 the folded section: the period goes to the route; closed trades, analytics, waiting entries, by segment (1.2s)
  ✓  39 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:729:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › V2-26 Live unavailable (every session expired): the Live card and the hero say why; contract error is a problem (1.8s)
  ✓  35 [copilot-app] › e2e/tests/copilot-app-desk-pnl.spec.ts:642:3 › MOCK — not real data: Paper Trading › P&L dashboard v2 › TC-037 the stream fails → polling; a newer snapshot updates, an older one is dropped; the stream path delivers too (11.1s)
  69 passed (50.0s)
```

Real staging answers rendered (scratch spec, not committed: every `/api/desk/pnl*`, `/journal`, `/timeseries` and `/live-chart` request
answered with the bodies the staging run above returned; desktop and 390 px; expands BHARTIARTL; switches to Live):

```
BUILD_EXIT=0
REAL 390px OK; requests: /api/desk/pnl/stream, /api/desk/pnl, /api/desk/pnl/timeseries, /api/desk/pnl/journal/b4e0beb6-f5b5-4ecd-857e-fab363d50b95
  ✓  1 [copilot-app] › e2e/tests/copilot-app-zz-pnl-real.spec.ts:17:3 › real staging P&L v2 renders at 390px (5.5s)
REAL 1280px OK; requests: /api/desk/pnl/stream, /api/desk/pnl, /api/desk/pnl/timeseries, /api/desk/pnl/journal/b4e0beb6-f5b5-4ecd-857e-fab363d50b95
  ✓  2 [copilot-app] › e2e/tests/copilot-app-zz-pnl-real.spec.ts:17:3 › real staging P&L v2 renders at 1280px (5.7s)
  2 passed (6.6s)
```

The builder's wider regression (31 specs touching Paper Trading): `670 passed, 14 skipped (existing test.skip), 0 failed`.
Screenshots: scratchpad/pnl2-pw/pnl2-real-1280*.png, pnl2-real-390*.png.

## Data Correctness (staging)
- MOCK BHARTIARTL row: avg 2,065.00 = the at-once fill at the 3 Nov close; LTP 2,065.00 EOD 3 Nov; est. charges 113.80; net −113.80;
  stop/target 1,970.84 / 2,245.82 = what was recorded. Its curve at 15:00: gross −40.00 = (2,061.00 − 2,065.00) × 10 against the real
  15:00 candle close 2,061.0 (live-chart answer); net −153.80 = −40 − 113.80. PASS.
- Journal BHARTIARTL = the Scan dashboard's strong record of 4 Nov 14:45:59 (score 74, plan 1,970.84 / 2,245.82 / 2,429.14), read
  separately from Redis before the run. PASS.
- Modify risk: `level_changes` v1 {stop 1,255.97, target 1,439.87, prev 1,268.66 / 1,425.61, session 2026-11-04}; the P&L row keeps the
  levels in force (1,268.66 / 1,425.61) and shows the pending change from 2026-11-05; only `level_changes`, `level_version`,
  `updated_at` changed on the trade; 3 risk_decisions rows over the run (2 creates + the edit). PASS.
- Broker accounts: Zerodha and ICICI Direct SIGN_IN with the broker's own note (both sessions expired) — matches the owner's state.
- After the run every owner document in the watched collections is identical to before (script check `True`); afterwards
  desk_paper_trades = 0, paper account cash 1,00,00,000 with 0 blocked, 1 ledger row (the 12:18 top-up adjust). PASS.

## Not verified (said, not hidden)
- Real broker positions in Live mode: both sessions are expired, so live rows were tested with fakes (unit) and mocks (e2e) only.
- The evening exit cron (`scripts/check_desk_alerts.py`) with a level change: its function `apply_trade_exits` is unit-tested.
- The deployed screen and routes (not merged; a merge deploys the frontend, the backend needs its restart).
- In-session live prices on v2: this run was after the close; the live path is v1's resolver, unchanged, verified on 4 Nov 09:31.

## Inputs required from user
- none

## Verdict: PASS
