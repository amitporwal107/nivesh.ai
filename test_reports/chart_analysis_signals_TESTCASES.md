# Chart Analysis — timeframes, chart tools and bar signals: test cases (written before the code)

Branch `feat/chart-analysis-signals` (from `origin/dev` 19d8d974). Owner asks, 3 Nov 2026: build the "Signals Chart
(standalone)" design into the existing Trade Desk › Chart Analysis, and "we specifically need 5 min, 1 hour like candles
changes". Everything already on the screen (stats, walls, max pain, RVOL, trade lines, futures OI, OI Δ, build-up strip,
strike ladder, option chain, basket) stays.

## Contracts

`GET /api/desk/live-chart/{sym}?interval=&sessions=` (backend/routes/desk_live_chart.py)
- `interval` ∈ 1m 3m 5m 15m 30m 60m (Kite candles; daily fallback with the reason when Kite cannot answer, as today),
  `1d` (end-of-day bars, no Kite read, no reason), `1w` (weekly bars built from the daily bars). Anything else: 400.
- `sessions` 1–10 (was 1–5). 422 outside.
- New field `sma20` (aligned to `bars`, warm-up bars not sent, like `ema20`).
- `timeframe.label`: 1M 3M 5M 15M 30M 1H DAILY WEEKLY. The fallback's `reason_text` names the interval asked for
  ("Kite login needed for 5m candles").
- `1w`: a bar per ISO week of trading days, time = the week's first session, open = first open, high = max, low = min,
  close = last close, volume = sum. EMA 20 / SMA 20 / RVOL on the weekly bars. Conditions stay on the daily bars; WATCH /
  READY / CONFIRMED / RVOL markers point at the week bar holding their day (the text keeps the day).

`GET /api/fno/{sym}/futures/oi-buildup?interval=` (backend/routes/fno.py): `interval` adds 1m and 3m; `sessions` 1–10.
Kite intervals (services/kite_live_feed/intraday.py): adds 1m (`minute`, 60 days) and 3m (`3minute`, 100 days).

## Screen (frontend-v5 …/tabs/trade-desk/analysis)

Toolbar under the readout: symbol · 1m 3m 5m 15m 1h 1D 1W · Candles Line Area · SMA 20 · "NSE · <label> · IST".
Sessions asked per timeframe: 1m 1, 3m 2, 5m 3, 15m 2 (unchanged), 1h 10. `?tf=` keeps the choice in the URL.
Left tool rail (not on a phone): crosshair, trend line, horizontal line, vertical line, rectangle, Fib retracement,
measure, undo, clear. Drawings are kept per timeframe while the page is open.
Panes: price · VOLUME (new) · FUTURES OI · OI Δ PER BAR · BUILD-UP. Wheel over the price pane zooms; dragging pans; a
"Latest" button returns to the newest bars.
Bar signals (pills after the existing seven, triangles on the bars): Long build-up, Short covering, Volume spike,
Breakout (up, under the bar); Breakdown, Short build-up (down, over the bar). Rules, said on screen:
- build-up: the selected futures slot's price change and OI change on that bar (the desk board's rule) and the bar's OI
  change at least 2× the mean size of the 20 bars before it; never across a contract roll
- volume spike: the route's RVOL ≥ 2
- breakout / breakdown: close above the highest high / below the lowest low of the 20 bars before it

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| B1 | live-chart | `interval=5m&sessions=3` with Kite bars | api (pytest) | read_intraday asked for 5m, 3 + 2 warm-up sessions; label 5M; `sma20` aligned |
| B2 | live-chart | `interval=60m&sessions=10` | api (pytest) | 200, label 1H, sessions accepted |
| B3 | live-chart | `interval=1d` | api (pytest) | no Kite read; interval 1d, reason null, up to 120 bars |
| B4 | live-chart | `interval=1w` | api (pytest) | weekly OHLCV correct; bar time = first session of the week; markers moved to the week bar |
| B5 | live-chart | `interval=2h` → 400; `sessions=11` → 422 | edge (pytest) | as stated |
| B6 | live-chart | Kite down, `interval=5m` | failure (pytest) | daily fallback; reason_text "Kite login needed for 5m candles…" |
| B7 | live-chart | SMA 20 values | unit (pytest) | mean of the last 20 closes, None before 20 |
| B8 | oi-buildup | `interval=1m`, `sessions=10` | api (pytest) | accepted; 3m too; Kite asked for `minute` |
| B9 | regression | the existing live-chart, oi-buildup, Kite intraday tests | regression (pytest) | all pass |
| F1 | toolbar | seven timeframe pills; 15m pressed by default | e2e | as stated |
| F2 | 5m | click 5m | e2e | live-chart asked `interval=5m&sessions=3`; oi-buildup `interval=5m&sessions=3`; header 5M; URL `tf=5m` |
| F3 | 1h | click 1h | e2e | `interval=60m&sessions=10` on both; header 1H |
| F4 | 1D / 1W | click 1D, then 1W | e2e | `interval=1d`; then `interval=1w` and oi-buildup `daily=250&window=5`; weekly futures OI drawn |
| F5 | chart type | Line, Area, Candles | e2e | line path / area path drawn and no candles; back to candles |
| F6 | SMA 20 | toggle | e2e | `ca-sma` drawn when on, gone when off |
| F7 | volume pane | default | e2e | one volume bar per candle in view |
| F8 | bar signals | default pills (Long build-up, Volume spike on) on mocked bars | e2e | triangles where the rule holds and only there; each pill hides / shows its own |
| F9 | drawing | H line (1 click), trend (2 clicks, dashed preview), undo, clear | e2e | drawings added and removed |
| F10 | drawing | Fib and measure | e2e | 7 Fib levels; the measure label shows change, % and bars |
| F11 | crosshair | hover the price pane | e2e | horizontal line and the price tag in the gutter |
| F12 | pan / zoom | wheel over the price pane, drag, Latest | e2e | fewer bars after zoom-in; drag moves the window; Latest returns |
| F13 | regression | the existing chart-analysis specs (header, chips, ladder, expiry, daily, KC, levels, phone, cash, lab redirects, wording) | regression e2e | all pass |
| F14 | phone | 390 px | e2e | timeframe pills there, no tool rail, no sideways scroll |
| F15 | wording | the card text | e2e | no buy / sell / stop loss / target / entry / pick / recommend in the NEW strings |
| S1 | staging | after merge: PETRONET 5m and 1h on staging | post-deploy | real Kite candles, futures OI per bar, signals drawn |
