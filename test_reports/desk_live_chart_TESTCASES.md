# Test cases — Trade Desk › Chart Analysis › Live chart (the owner's design, 28 Oct)

Authored up front, after the API and UI design and before the implementation. Branch `feat/desk-live-chart-design`.
Results go in `test_reports/desk_live_chart_<date>.md`.

## API design

| Route | What it answers | Source |
|---|---|---|
| `GET /api/fno/{symbol}/futures/oi-buildup?interval=15m&window=4&sessions=2` (new, read only) | For the current / next / far month futures AND consolidated (the three summed): per 4-bar window the price change, OI change, volume, OI at the window's end and the build-up class, plus the snapshot time. `mode` = `intraday` (Kite) or `end_of_day` (bhavcopy fallback, one window = the day) with `kite_reason`. | Kite `historical_data(oi=1)` per NFO future with the platform token; fallback `nidp.fno_bhavcopy` via DaaS (the same rows as `/api/fno/{symbol}/futures`) |
| `GET /api/desk/live-chart/{symbol}?plan_id=&interval=15m&sessions=2` (new, read only) | The chart's candles (15m Kite, or daily with the reason), EMA 20 and RVOL per bar (server-side, one source), the levels (plan or scanner signal), the signal conditions with status met / waiting / not met / not hit / n/a and value, the signal markers (WATCH / READY / CONFIRMED from the signal's stages and dates, RVOL from the bars), the validity. | Kite intraday (`IntradayService`) or `nidp.prices_eod_adjusted`; Mongo `trade_plans`; Postgres `positional_signals` (+ `_history`) |

Build-up classes (the desk board's rule, `nidp desk_market.buildup_label`): price↑ OI↑ long build-up, price↓ OI↑ short build-up,
price↑ OI↓ short covering, price↓ OI↓ long unwinding, either flat neutral, either missing null. Consolidated = the near
month's price change with the OI and volume summed over the three expiries (the board's own consolidation).

## Test cases

| ID | Area | Scenario | Type | Expected |
|----|------|----------|------|----------|
| TC-1 | classifier | the four quadrants, flat, missing | unit | labels equal `nidp...desk_market.buildup_label` for every case (parity) |
| TC-2 | OI windows | 2 sessions of 15m bars, window 4 | unit | windows by TIME from 09:15 (09:15–10:15, 10:15–11:15, …); price change = window close − previous window close; OI change = OI at the end − OI at the previous end; volume summed; last window `complete: false` when it has < 4 bars |
| TC-3 | OI windows | first window of the series | unit | no baseline → the baseline session is fetched and dropped; the first SHOWN window has a baseline |
| TC-4 | consolidated | three contracts | unit | consolidated OI change = sum of the three contracts' OI changes per window; volume = sum; price change = the near month's |
| TC-5 | consolidated | far month with no trade in a window | unit | its OI carries forward (OI changes only by a trade), its volume counts 0 |
| TC-6 | route | Kite session present | api (mock Kite) | `mode: intraday`, contracts current/next/far with expiries, `consolidated`, `snapshot_at`, `read_only: true` |
| TC-7 | route | no Kite session (token missing / expired) | api (mock) | `mode: end_of_day`, `kite_reason` set, one window per contract from the bhavcopy rows, labels by the same rule, consolidated summed |
| TC-8 | route | read only | api | only GET; Kite surface used is `instruments` + `historical_data`; no order/GTT method exists on `ReadOnlyKite` |
| TC-9 | live-chart | Kite 15m candles | api (mock) | `timeframe.interval: 15m`, `source: Kite intraday`, EMA 20 per bar equals the indicator engine's EMA formula, RVOL = volume ÷ mean of the previous 20 bars |
| TC-10 | live-chart | no Kite session | api (mock) | daily bars, `timeframe.interval: 1d`, `timeframe.reason` says the Kite login is needed |
| TC-11 | conditions | plan with break_above entry | unit | close vs EMA 20 met; volume ≥ 1.3×; trigger "15m close above entry" waiting until a completed bar closes above; invalidation "close below stop" not hit / hit |
| TC-12 | conditions | in-progress bar | unit | the evaluation uses the last COMPLETED bar only |
| TC-13 | markers | signal stages over dates | unit | ACCUMULATION → WATCH, EARLY_BREAKOUT → READY, BREAKOUT → CONFIRMED, placed at the last bar of the signal's session; a date outside the chart → no marker; DB unavailable → `markers_error`, no marker |
| TC-14 | live-chart | plan of another symbol | api | 400; plan not found → 404 |
| TC-15 | UI | the chart card | e2e (mocked) | header `SYMBOL [state] NSE · CASH · 15M · SIGNAL … · DETECTOR …`, LAST price + time; toggles PATTERN · CONFIRMATION · VOLUME · F&O hide/show their markers |
| TC-16 | UI | chart marks | e2e | entry band/line, STOP, T1, T2, EMA 20, the last-price open circle, "VALID UNTIL" at the right edge, signal pills, F&O markers below |
| TC-17 | UI | futures OI strip | e2e | "FUTURES OI · BUILD-UP BY 4-BAR WINDOW", SNAPSHOT time, coloured bars per window, OI line; selector Current / Next / Far / Consolidated switches the series |
| TC-18 | UI | no Kite session | e2e | "Kite login needed for 15m candles", the chart falls back to the daily candles with the timeframe labelled; the strip says "end of day" |
| TC-19 | UI | legend + headline | e2e | legend with "NO FILL YET" when there is no fill; headline in plain words from the real numbers |
| TC-20 | UI | paper order ticket | e2e | `SYMBOL [LONG] from …`; entry policy chips; RISK PER TRADE read-only from the profile with a link to Risk Desk › Policy & runtime; NO slider (`input[type=range]` count 0); quantity = `account_size.quantity`; position value, risk at stop, R:R to T1, est. costs; the entry-is-not-a-fill text; Place paper order → allow / reduce / block answer; footer with feed, daily loss, open risk, "No broker order is sent." |
| TC-21 | UI | place paper order body | backend contract | the POST body the ticket sends passes the paper-trade route's validator (plan_ref, entry rule) — the existing `planCashBody` reused |
| TC-22 | UI | F&O setup | e2e | CHAIN n MIN OLD / day; tagged lines (build-up, CALL WALL, PUT WALL); OI by strike bars (put left, call right); PCR · ATM IV · IV PCTILE (stale/unavailable) · EXP. MOVE; "CANDIDATE STRUCTURE" (never "suggested"); link to Trade Desk › Strategy Lab |
| TC-23 | UI | signal conditions | e2e | ✓ / ○ / — rows with values and the note "Touching the range does not create a fill…" |
| TC-24 | UI | 390 px | e2e | no horizontal page scroll; the two columns stack |
| TC-25 | regression | desk shell, trade desk, lab, decision cards specs | e2e | still pass |
