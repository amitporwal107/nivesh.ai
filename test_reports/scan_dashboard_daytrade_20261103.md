# Scan dashboard — second tab "Day trade" (Chartink 503347) — functionality report

Session fae0f691, 3 Nov 2026. Branch `feat/scan-dashboard-daytrade` (worktree `/home/deploy/nivesh-wt-scan-daytrade`, from origin/dev d8cfff7d).

## Ask
Owner, 3 Nov ~17:15 IST: "We already have a chartlink scan now please add another chartlink scan in another tab
https://chartink.com/dashboard/225969". 225969 is private on Chartink (no widget definitions served to anyone but its owner);
the owner made a public copy, https://chartink.com/dashboard/503347 ("Copy day trade", 20 widgets). Owner decision: the
"15 minute Stock Breakouts" widget (Chartink segment {57960}, not published) runs on F&O stocks.

## Design (written before the code)
- `GET /api/scan-builder/market-dashboard?dashboard=atlas|daytrade` (default atlas = 247498; unknown key → 422
  `unknown_dashboard`). Same payload plus `dashboard {key,title,chartink_id}` and `dashboards [...]`. One computation per
  dashboard per CACHE_S per worker.
- 20 widgets of 503347 from their Chartink definitions only (no Chartink data). Mapping notes:
  {33489} = F&O stocks (as for 247498); "earning per share[eps]" = EPS latest year; "yearly pe ratio" = Close ÷ EPS latest
  year; net profit[quarter]/[yearly] = latest quarter / latest year; N months/weeks ago = monthly/weekly candles.
- Honest limits: 12 Year High Breakout needs 3,000 sessions (we hold 639, from April 2024) → not computed; Multiyear
  breakout: the 3- to 10-year legs cannot add a stock the 520-session leg misses → computed; Stocks Under 300: the
  200-week SMA cannot be computed → partial, that line not applied; High Momentum Stocks: "RSI(14) > highest RSI(14) of the
  last 3 days" can never hold → always empty (on Chartink too), said on screen.
- Intraday: RSI VWAP intraday and 15 minute Stock Breakouts on Kite 15-minute candles (30-minute RSI from pairs of
  15-minute candles; VWAP from today's 15-minute candles); 10x volume first 5 min = the 247498 widget's rule.
- Compliance renames: "RSI VWAP INTRADAY BUY" → "RSI VWAP intraday"; "Swing trade breakout strategy 10-20% gains" →
  "Swing trade breakout"; "Copy - Strong stocks" → "Strong stocks".
- Frontend: tabs "Atlas fresh | Day trade" on the Scan dashboard page, `dash=daytrade` in the URL; a response for another
  dashboard (old backend) is never shown under the Day trade tab.

## Test cases (authored up front)
| # | Area | Case | Expected |
|---|---|---|---|
| TC-1 | BE unit | 503347 definitions | 20 widgets, the 20 Chartink ids, unique ids, layout order |
| TC-2 | BE unit | Criteria text from the definitions | e.g. "Close > 1 day ago Highest high of 240", "High = Highest high of 260", "Close < 1 month ago Close × 0.9" |
| TC-3 | BE unit | Not-computable parts | 12-year → not_computed with reason; Under 300 → partial, 200-week line applied=false; High Momentum → empty + reason |
| TC-4 | BE unit | Intraday maths | max/min, session VWAP, 30-minute regrouping equal hand-computed values |
| TC-5 | BE unit | RSI VWAP + 15m breakouts decide on candles | pass/fail per hand-made candles; partial when candles missing |
| TC-6 | BE unit | Route | `?dashboard=daytrade` answers the 20 widgets + `dashboard.key`; default = atlas (17); unknown → 422 typed |
| TC-7 | BE unit | Cache per dashboard | atlas and daytrade cached separately (no cross-serving) |
| TC-8 | BE unit | No barred words | no "buy", "stop loss", "target" in titles/criteria/notes |
| TC-9 | BE regression | Existing scan builder + dashboard suites | all pass |
| TC-10 | BE live (staging container, real data) | compute daytrade on today's data | 20 widgets, statuses as designed; spot-check 3 stocks against Kite quote / warehouse |
| TC-11 | FE Playwright (mocked) | tab default, switch, URL param, reload, old-backend guard | pass |
| TC-12 | FE typecheck + build | tsc, vite build | 0 errors |

## Results (3 Nov 2026, ~20:00–21:00 IST, this session)

| # | Result | Evidence |
|---|---|---|
| TC-1 | PASS | `test_the_twenty_widgets_of_dashboard_503347_in_layout_order` |
| TC-2 | PASS | `test_criteria_are_written_from_the_definitions` |
| TC-3 | PASS | `test_the_day_trade_dashboard_answers_its_twenty_widgets_with_honest_statuses`, live run below |
| TC-4 | PASS | `test_regroup_…`, `test_vwap_max_and_regrouped_rsi_equal_hand_computed_values` |
| TC-5 | PASS | `test_rsi_vwap_and_15_minute_breakouts_decide_on_the_candles` |
| TC-6 | PASS | `test_route_picks_the_dashboard_and_refuses_an_unknown_one` (422 `unknown_dashboard`, never computed) |
| TC-7 | PASS | `test_cache_is_kept_per_dashboard` |
| TC-8 | PASS | `test_no_barred_trading_words_on_the_day_trade_tab` |
| TC-9 | PASS | all scan-builder suites + kite live feed: **306 passed** |
| TC-10 | PASS | live compute in the staging backend container on today's real data (below) + 3 independent spot checks |
| TC-11 | PASS | Playwright **36 passed** (mocked, labelled MOCK), incl. TC-DE11a–i |
| TC-12 | PASS | `TSC_EXIT=0`, `BUILD_EXIT=0` |

Backend (staging image, tree read-only, no network):
```
$ python -m pytest tests/test_scan_builder_*.py tests/test_kite_live_feed.py -q
306 passed, 2 warnings in 9.11s
```

TC-10 — branch code (copied to /tmp/dt in nivesh-staging-app-backend; the running app untouched), `compute(dashboard="daytrade")`
on real data after the close (Kite close of 3 Nov over NSE EOD to 2 Nov; DaaS fundamentals/results; Kite 15-minute candles):
```
=== round 2: 4.7s basis="Kite close of 03 Nov 2026 (provisional …), over NSE end-of-day bars to 02 Nov 2026 …" counts={'cash': 2698, 'fno': 217, 'nifty50': 49, 'no_today_bar': 58}
- 5518231 RSI VWAP intraday            ok           n=  69 · 15-minute candles to 2026-11-03T15:00:00+05:30
- 5518232 Explosive movement           ok           n=   7
- 5518234 Strong stocks                ok           n=  71
- 5518237 Multiyear breakout           ok           n= 500   (cut at the row limit: now noted on screen)
- 5518230 12 Year High Breakout        not_computed n=   0   "needs about 12 years of daily highs …"
- 5518245 Stocks under 300             partial      n=   0   "200-week moving-average condition cannot be checked …"
- 5518229 High momentum stocks         ok           n=   0   "Always empty, on Chartink too …"
- 5518247 10x volume first 5 min       partial      n=  53   (TrueData trade side not applied: login refused, AUTH_EXPIRED)
- 5518246 15 minute stock breakouts    ok           n=  26 · 15-minute candles to 2026-11-03T15:00:00+05:30
answer: dashboard={'key': 'daytrade', 'title': 'Day trade', 'chartink_id': '503347'}, dashboards=['atlas', 'daytrade'], 20 widgets
```
Spot checks against sources other than our output (Kite `quote()` today; warehouse `nidp.prices_eod_adjusted`):
- MCX in *52 week high breakout*: Kite last 3,490.10 (prev close 3,249 → +7.42 %, as shown); highest adj_high of the 240 sessions
  to 2 Nov = 3,481.40 < 3,490.10. Holds.
- MARICO in *RSI VWAP intraday*: Kite last 878.40, 2 Nov high 805.60 → close > 1 day ago high; Kite's own VWAP
  (average_price) 856.10 < 878.40. Holds.
- AYMSYNTEX in *Strong stocks*: closes 27 Oct–2 Nov 234.95 < 242.75 < 245.65 < 247.50 < 262.66, today 276.64 (Kite). Holds.

Frontend (playwright:v1.47.0-jammy, wl-fe-node-modules, pw-browsers-1223, --network none):
```
TSC_EXIT=0
BUILD_EXIT=0
✓ built in 26.55s
PLAYWRIGHT_EXIT=0
  36 passed (21.4s)      # copilot-app-desk-scan-dashboard.spec.ts + copilot-app-desk-market.spec.ts
```
The frontend agent also checked that the old-backend guard tests fail with the guard disabled (TC-DE11d/e: 2 failed).

## Found on the way (not changed here)
- Kite's 1-minute candles for all 218 F&O stocks end at 15:14 on 3 Nov (raw `historical_data`, re-read and confirmed); other
  stocks run to 15:29. The F&O 15-minute widgets on both tabs therefore stop at the 15:00 candle in the last 15 minutes.
- TrueData login refused (AUTH_EXPIRED) since ~17:40: the 10x widget says the trade-side ticks are "loading" — misleading
  wording in the existing §8 code path; the owner should know the TrueData session/subscription is the cause.

## UNVERIFIED (needs the merge + deploy)
- The HTTP route on staging (`/api/scan-builder/market-dashboard?dashboard=daytrade`: 404 → 401 probe after the backend
  restart) and the page in a real browser (needs the owner's staging session).
- The live 15-minute refresh age while the Day trade tab is open in market hours (218 F&O reads share ≤ 1.5 Kite calls/s).

## Verdict: PASS
