# Functionality Verification Report — Chart Analysis v2 backend (BE-1 daily futures series, BE-2 consolidated chain, BE-3 payoff scenarios)

- **Branch:** `feat/cav2-be` (worktree `/home/deploy/nivesh-wt-cav2-be`, from `feat/chart-analysis-v2`)
- **Date:** 2026-10-29
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** pytest in `nivesh/backend:staging` (no network); staging READ-ONLY in-process probe in `nivesh-staging-app-backend`
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
Contracts BE-1, BE-2, BE-3 of `test_reports/chart_analysis_v2_TESTCASES.md`, plus the coordinator's addition to BE-1
(`daily_windows`, case D4).

- **BE-1** `GET /api/fno/{symbol}/futures/oi-buildup?daily=N` (0 = off, default 0, max 250, >250 → 422). With N > 0 every
  `contracts[i]` and `consolidated` gain `daily_bars: [[day, close, volume, oi, oi_change, expiry]]` (last N bhavcopy
  sessions, oldest first) and `daily_windows` (the `windows` objects over those sessions, `window` sessions each). The answer
  also gains a top-level `daily` object (requested, sessions, window, source, the rules in words). daily=0: the answer is
  exactly as before (D3). Works in both modes (intraday and end_of_day: pytest D1/D3 and the staging probe).
  Read: only existing DaaS endpoints — `GET /v1/fno/{symbol}/expiries` once, then `GET /v1/fno/{symbol}/history?kind=future&expiry=E&start=S`
  (the read `services/desk_strategy_trades.py` marks legs with). The expiry list cannot say which expiries carry futures
  (its `futures_count` counts rows with a NULL option_type, and the live bhavcopy marks futures `"FUT"`: TVSMOTOR shows
  futures_count 0 for every expiry), and "the last expiry of each month" is WRONG for indices (NIFTY March 2026: futures
  expired 30 Mar, an options-only expiry on 31 Mar). So per calendar month the listed expiries are tried latest first until
  one answers with futures rows. Calls: ≈ one per month of the window (TVSMOTOR daily=60: its real expiry list has one expiry in each of the 7 months
  Jul 2026–Jan 2027 in range, so 7 history reads; counted from the list, not measured), at most 4 at a
  time, cached 10 minutes per (symbol, N). Verified on staging against a full scan of every listed expiry (identical for
  TVSMOTOR 250, NIFTY 250, BANKNIFTY 60). A failed read is 502, never an answer without the daily series.
- **daily_windows** (coordinator addition): aligned so the LAST window ends on the latest session; a partial first window is
  **dropped**. Every figure of a slot's window is ONE contract's: the contract of the slot's last bar in the window, against
  its own row on the session before the window (no row there → price_change, oi_change and label null). Label =
  `fno_oi_windows.buildup_label`, the same rule as `windows`. Each window also carries `expiry` (an addition) naming that
  contract; `index` = position (0 = oldest window sent); `complete` always true.
- **BE-2** `GET /api/fno/{symbol}/chain/consolidated?around=N` (new; login required; around 1..500, default 40): the `/expiries`
  list, one DaaS `/fno/{symbol}/chain?expiry=E` read per expiry (4 at a time), summed per strike; summary from
  `summarise_chain` over the sums. An expiry read for another day than the list (or with no strikes) is dropped and logged;
  a failed read is 502 (never a partial sum); no options → 404 "No option contracts are listed for {SYM}"; no F&O at all →
  404 "No F&O data for {SYM}". `expiries` is a list of ISO date strings (the expiries actually summed).
- **BE-3** `POST /api/desk/strategy/payoff`: with both `pre_expiry` and `scenarios`, `pre_expiry.scenarios =
  [{name, underlying_price, gross, net, greeks:{delta,gamma,theta,vega,rho}|null}]`, priced by the same helper as the
  pre-expiry curve (refactored into `_value_at` / `_position_greeks`, used by both). A leg that cannot be priced → every
  scenario's gross/net/greeks null, reason in the existing `unavailable`. A leg at expiry on the evaluation date → greeks null,
  gross/net priced (as the curve). Without scenarios the answer has no `pre_expiry.scenarios` key (unchanged).
  Side effect to note: the plan engine's `run_payoff` (services/strategy_plan/candidates.py) sends both, so plan candidates'
  `payoff.pre_expiry` also gains `scenarios` (additive; all 1421 existing tests still pass).

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| D1 | BE-1 | daily=60, both modes: per-slot continuous series, expiry per bar, roll keeps the new contract's own OI change; options-only expiry tried and skipped | unit/api | values, expiry | PASS |
| D2 | BE-1 | consolidated daily sums over the day's expiries; missing days absent; a null OI leaves the sum null | unit/api | sums | PASS |
| D3 | BE-1 | daily=0 / absent → identical answer, no history read; daily=251, -1, x → 422 before any read; failed history read → 502 | api/failure | shape | PASS |
| D4 | BE-1 | daily_windows: roll inside the last window → one contract (November) vs its own baseline; far month with no baseline → null label; window=7 drops the partial first window | unit/api | values | PASS |
| K1 | BE-2 | 3 expiries summed per strike; PCR / max pain / walls / totals over the sums (hand-worked); around window; an expiry read for another day is dropped | api | numbers | PASS |
| K2 | BE-2 | strike in one expiry only; figure null everywhere stays null; no options → 404; no F&O → 404; failed read → 502; no login → 401 | api/edge/failure | values / 404 | PASS |
| G1 | BE-3 | 11 scenarios + 61-point grid: scenario greeks = the model at that price; +0% = pre_expiry.greeks; gross/net = curve; nothing else changes; route answers | unit/api | equal | PASS |
| G2 | BE-3 | unpriceable leg → scenario gross/net/greeks null, reason listed, expiry payoff unchanged; at-expiry date → greeks null | unit/edge | null | PASS |
| S1 | staging | TVSMOTOR daily=60: latest-day current-slot OI = `/futures` near-month OI (all slots, consolidated); roll-day oi_change = bhavcopy change_in_oi | data | equal | PASS |
| S2 | staging | TVSMOTOR consolidated: ATM strike's OI / Δ / volume = sum of the 3 `/chain` answers; totals = sum of `/chain` summaries | data | equal | PASS |
| S3 | staging | TVSMOTOR bull call spread 4300/4400 CE, 11 scenarios: +0% scenario greeks = pre_expiry.greeks | data | equal | PASS |
| S4 | staging | deployed Chart Analysis screen | e2e | screenshot | NOT IN THIS SCOPE (frontend, not deployed) |

Mutation check (scratch copy, not committed): (1) oi_change from the slot's previous bar → D1 fails; (2) null summed as 0 →
K2 fails; (3) scenario greeks at the reference price → G1 fails; (4) window baseline from the slot's previous contract → D4
fails. Each test detects the bug it targets.

## API / Endpoint Tests

**pytest — new file** (`backend/tests/test_chart_analysis_v2_backend.py`):
```
$ sudo docker run --rm --network none -v /home/deploy/nivesh-wt-cav2-be:/work:ro -w /work/backend ... nivesh/backend:staging python -m pytest tests/test_chart_analysis_v2_backend.py -q -p no:cacheprovider
..........................                                               [100%]
26 passed, 2 warnings in 7.16s
```

**pytest — every existing test file that imports a changed module** (42 files: test_fno_routes, test_desk_live_chart,
test_live_chart_fno_series, test_strategy_payoff, test_strategy_plan, test_strategy_levels, test_payoff_cost_card,
test_prd_worked_examples, test_trade_plan, test_strategy_ideas, … and the new file):
```
1421 passed, 1 skipped, 3 warnings in 93.55s (0:01:33)
```
`test_fno_routes.py::test_the_router_is_read_only` lists the router's paths; `/api/fno/{symbol}/chain/consolidated` was
added to that list (the only edit to an existing test).

**Staging (READ ONLY).** The changed modules are not deployed. They were copied into a fresh overlay dir in
`nivesh-staging-app-backend` (`/tmp/ov_cav2`: my routes/fno.py, services/fno_oi_windows.py, services/strategy_plan/, plus the
branch versions of modules staging's older commit #382 lacks — research_chart_intraday, kite_live_feed, fno_options_intraday,
fno_iv_history, fno_forward). The route functions were called in-process (fake user; nothing written, nothing restarted). The
probe files were deleted from the container afterwards. Real data: nidp.fno_bhavcopy through DaaS, and Kite through the
platform session (read only).

```
$ sudo docker exec -w /app/backend nivesh-staging-app-backend python /tmp/probe_s123_cav2.py TVSMOTOR
module routes.fno -> /tmp/ov_cav2/routes/fno.py
module services.fno_oi_windows -> /tmp/ov_cav2/services/fno_oi_windows.py
module services.strategy_plan.pre_expiry -> /tmp/ov_cav2/services/strategy_plan/pre_expiry.py
module services.kite_live_feed.intraday -> /tmp/ov_cav2/services/kite_live_feed/intraday.py
module routes.strategy_plan -> /app/backend/routes/strategy_plan.py

=== S1 TVSMOTOR oi-buildup daily=60: mode=intraday kite_reason=None took 3.02s
daily: {'requested': 60, 'sessions': 60, 'window': 4, 'source': "NSE F&O bhavcopy (nidp.fno_bhavcopy), end of day, through the data platform's contract history", 'slot_rule': 'per day: the futures listed whose expiry is on or after the day, nearest first (current, next, far)', 'oi_change': "the same contract's OI minus its OI on the previous session in the data; null when it had no row then", 'windows': 'aligned to end on the latest session; a partial first window is dropped; one contract per window'}
slots: [('current', '2026-11-23', 60, 15), ('next', '2026-12-29', 60, 15), ('far', '2027-01-25', 60, 15)]
current first bar: ['2026-08-04', 4369.9, 4513, 8928325, -318150, '2026-08-25']
current last 3 bars:
  ['2026-10-27', 4065.6, 7674, 889700, -418425, '2026-10-27']
  ['2026-10-28', 4229.7, 17381, 7382550, 219450, '2026-11-23']
  ['2026-10-29', 4305.2, 15543, 6787725, -594825, '2026-11-23']
current-slot roll bars (first bar of each new contract):
  ['2026-08-26', 4462.2, 3179, 7897750, -66675, '2026-09-29']
  ['2026-09-30', 4143.5, 3485, 7463400, 114975, '2026-10-27']
  ['2026-10-28', 4229.7, 17381, 7382550, 219450, '2026-11-23']
current last 3 daily_windows:
  {'day': '2026-10-16', 'index': 12, 'start': '2026-10-13', 'end': '2026-10-16', 'bars': 4, 'close': 4090.8, 'price_change': 147.8, 'price_change_pct': 3.75, 'oi': 7158900, 'oi_change': -204750, 'oi_change_pct': -2.78, 'volume': 12963, 'label': 'short_covering', 'complete': True, 'expiry': '2026-10-27'}
  {'day': '2026-10-23', 'index': 13, 'start': '2026-10-19', 'end': '2026-10-23', 'bars': 4, 'close': 3960.6, 'price_change': -130.2, 'price_change_pct': -3.18, 'oi': 3434550, 'oi_change': -3724350, 'oi_change_pct': -52.02, 'volume': 32422, 'label': 'long_unwinding', 'complete': True, 'expiry': '2026-10-27'}
  {'day': '2026-10-29', 'index': 14, 'start': '2026-10-26', 'end': '2026-10-29', 'bars': 4, 'close': 4305.2, 'price_change': 323.3, 'price_change_pct': 8.12, 'oi': 6787725, 'oi_change': 2574250, 'oi_change_pct': 61.1, 'volume': 60166, 'label': 'long_buildup', 'complete': True, 'expiry': '2026-11-23'}
consolidated last bar: ['2026-10-29', 4305.2, 16045, 7005775, -566475, '2026-11-23']
consolidated last daily_window: {'day': '2026-10-29', 'index': 14, 'start': '2026-10-26', 'end': '2026-10-29', 'bars': 4, 'close': 4305.2, 'price_change': 323.3, 'price_change_pct': 8.12, 'oi': 7005775, 'oi_change': -746375, 'oi_change_pct': -9.63, 'volume': 82981, 'label': 'short_covering', 'complete': True, 'expiry': '2026-11-23'}

independent /futures route: as_of 2026-10-29
   {'expiry': '2026-11-23', 'close': 4305.2, 'oi': 6787725, 'change_in_oi': -594825, 'volume': 15543}
   {'expiry': '2026-12-29', 'close': 4332.2, 'oi': 206675, 'change_in_oi': 24500, 'volume': 419}
   {'expiry': '2027-01-25', 'close': 4349.6, 'oi': 11375, 'change_in_oi': 3850, 'volume': 83}
S1 current 2026-11-23 day 2026-10-29 | daily_bars close 4305.2 vol 15543 OI 6787725 oi_change -594825 | /futures close 4305.2 vol 15543 OI 6787725 change_in_oi -594825 | equal=True
S1 next    2026-12-29 day 2026-10-29 | daily_bars close 4332.2 vol 419 OI 206675 oi_change 24500 | /futures close 4332.2 vol 419 OI 206675 change_in_oi 24500 | equal=True
S1 far     2027-01-25 day 2026-10-29 | daily_bars close 4349.6 vol 83 OI 11375 oi_change 3850 | /futures close 4349.6 vol 83 OI 11375 change_in_oi 3850 | equal=True
S1 consolidated OI 7005775 vs sum /futures OI 7005775 equal=True; volume 16045 vs 16045 equal=True; oi_change -566475 vs sum change_in_oi -566475 equal=True
S1 roll 2026-08-26 current=2026-09-29: computed oi_change -66675 vs bhavcopy change_in_oi -66675 equal=True
S1 roll 2026-09-30 current=2026-10-27: computed oi_change 114975 vs bhavcopy change_in_oi 114975 equal=True
S1 roll 2026-10-28 current=2026-11-23: computed oi_change 219450 vs bhavcopy change_in_oi 219450 equal=True
S1 latest-day equality across slots: True
search vs full scan TVSMOTOR n=250: book days 265, per-month search found 16 futures expiries in 0.52s; full scan of all 16 listed expiries finds 16; identical=True
search vs full scan NIFTY n=250: book days 265, per-month search found 16 futures expiries in 2.66s; full scan of all 75 listed expiries finds 16; identical=True
search vs full scan BANKNIFTY n=60: book days 75, per-month search found 7 futures expiries in 0.36s; full scan of all 10 listed expiries finds 7; identical=True

=== S2 TVSMOTOR chain/consolidated took 0.19s: as_of 2026-10-29 expiries ['2026-11-23', '2026-12-29', '2027-01-25'] spot 4280.0 strikes 29 basis 'summed over the listed expiries' read_only True
summary: {'atm_strike': 4300, 'pcr': 0.7157, 'max_pain': 4200, 'put_wall': {'strike': 4000, 'oi': 215950}, 'call_wall': {'strike': 4500, 'oi': 373100}, 'total_call_oi': 2005675, 'total_put_oi': 1435525, 'total_call_oi_change': -444500, 'total_put_oi_change': 174300}
  /chain 2026-11-23: as_of 2026-10-29 strikes 29 total call OI 1976975 put OI 1402800
  /chain 2026-12-29: as_of 2026-10-29 strikes 25 total call OI 28700 put OI 32025
  /chain 2027-01-25: as_of 2026-10-29 strikes 11 total call OI 0 put OI 700
S2 strike 4300 call.oi: per-expiry /chain [254625, 8925, 0] -> sum 263550 | consolidated 263550 | equal=True
S2 strike 4300 call.change_in_oi: per-expiry /chain [-136150, 2800, 0] -> sum -133350 | consolidated -133350 | equal=True
S2 strike 4300 call.volume: per-expiry /chain [15812, 30, 0] -> sum 15842 | consolidated 15842 | equal=True
S2 strike 4300 put.oi: per-expiry /chain [113750, 0, 0] -> sum 113750 | consolidated 113750 | equal=True
S2 strike 4300 put.change_in_oi: per-expiry /chain [52675, 0, 0] -> sum 52675 | consolidated 52675 | equal=True
S2 strike 4300 put.volume: per-expiry /chain [2500, 0, 0] -> sum 2500 | consolidated 2500 | equal=True
S2 total_call_oi: sum of /chain summaries 2005675 | consolidated 2005675 | equal=True
S2 total_put_oi: sum of /chain summaries 1435525 | consolidated 1435525 | equal=True
S2 total_call_oi_change: sum of /chain summaries -444500 | consolidated -444500 | equal=True
S2 total_put_oi_change: sum of /chain summaries 174300 | consolidated 174300 | equal=True
S2 all equal: True

=== S3 TVSMOTOR bull call spread 4300/4400 CE 2026-11-23, lot 175, entries 115.65/74.75 (chain close 2026-10-29), ref 4280.0
valid True problems [] pre_expiry.unavailable []
pre_expiry.assumptions.legs [{'leg': 0, 'time_to_expiry_days': 25, 'iv_pct': 26.2211, 'iv_source': 'solved from the entry premium at 2026-10-29 (carried-spot forward)'}, {'leg': 1, 'time_to_expiry_days': 25, 'iv_pct': 26.3482, 'iv_source': 'solved from the entry premium at 2026-10-29 (carried-spot forward)'}]
pre_expiry.greeks {'delta': 22.9206, 'gamma': 0.0121, 'theta': -32.449, 'vega': 36.3298, 'rho': 62.2896}
scenarios (name, underlying, gross, net, greeks):
   -10% 3852.0 -6460.79 -6609.76 {'delta': 5.6423, 'gamma': 0.0357, 'theta': -52.4246, 'vega': 94.4089, 'rho': 14.4092}
   -8% 3937.6 -5833.58 -5986.46 {'delta': 9.1593, 'gamma': 0.0459, 'theta': -72.0202, 'vega': 126.7564, 'rho': 23.7957}
   -6% 4023.2 -4873.43 -5033.05 {'delta': 13.3403, 'gamma': 0.0505, 'theta': -84.7339, 'vega': 145.0933, 'rho': 35.1963}
   -4% 4108.8 -3548.76 -3719.01 {'delta': 17.5488, 'gamma': 0.0462, 'theta': -83.6562, 'vega': 137.6786, 'rho': 46.9151}
   -2% 4194.4 -1891.38 -2077.12 {'delta': 20.9787, 'gamma': 0.0325, 'theta': -65.4247, 'vega': 99.6047, 'rho': 56.6624}
   +0% 4280.0 0.0 -206.72 {'delta': 22.9206, 'gamma': 0.0121, 'theta': -32.449, 'vega': 36.3298, 'rho': 62.2896}
   +2% 4365.6 1979.27 1745.81 {'delta': 23.0082, 'gamma': -0.01, 'theta': 7.6636, 'vega': -37.7761, 'rho': 62.5397}
   +4% 4451.2 3888.09 3622.39 {'delta': 21.3245, 'gamma': -0.0285, 'theta': 45.2126, 'vega': -105.162, 'rho': 57.4479}
   +6% 4536.8 5592.48 5289.6 {'delta': 18.3313, 'gamma': -0.0401, 'theta': 72.2224, 'vega': -151.8345, 'rho': 48.23}
   +8% 4622.4 7007.62 6663.54 {'delta': 14.6784, 'gamma': -0.044, 'theta': 84.97, 'vega': -171.6556, 'rho': 36.7699}
   +10% 4708.0 8104.62 7716.18 {'delta': 10.9912, 'gamma': -0.0413, 'theta': 84.2891, 'vega': -166.6877, 'rho': 24.9894}
S3 scenario +0% underlying 4280.0 greeks == pre_expiry.greeks: True
S3 scenario +0% gross/net 0.0/-206.72 vs curve at grid[30]=4280.0: 0.0/-206.72 equal=True
expiry.scenarios unchanged shape: [['gross', 'name', 'net', 'underlying_price']]
```

S1 in end_of_day mode (in that probe process only, the Kite reader was stubbed to answer `token_missing` — MOCK of Kite
availability; every figure is the real bhavcopy):
```
mode end_of_day kite_reason token_missing snapshot_at 2026-10-29
current 2026-11-23 windows[0].oi 6787725 | daily_bars 60 last ['2026-10-29', 4305.2, 15543, 6787725, -594825, '2026-11-23'] | daily_windows 15
next 2026-12-29 windows[0].oi 206675 | daily_bars 60 last ['2026-10-29', 4332.2, 419, 206675, 24500, '2026-12-29'] | daily_windows 15
far 2027-01-25 windows[0].oi 11375 | daily_bars 60 last ['2026-10-29', 4349.6, 83, 11375, 3850, '2027-01-25'] | daily_windows 15
consolidated windows[0].oi 7005775 daily last ['2026-10-29', 4305.2, 16045, 7005775, -566475, '2026-11-23']
EOD window OI == daily last OI (current): True
```

## Data Correctness (staging)
- S1: the computed `daily_bars` (DaaS history reads) agree with an independent read, the existing `/futures` route, on the
  latest session (2026-10-29) for all three slots and consolidated: close, volume, OI, and oi_change = the bhavcopy's own
  `change_in_oi` column. On all three current-slot roll days in the window (2026-08-26, 2026-09-30, 2026-10-28) the computed
  OI change equals the exchange's `change_in_oi` for the new contract (e.g. 28 Oct: +219,450, not the jump from October's
  889,700 to November's 7,382,550). PASS.
- S2: strike 4300 call OI 263,550 = 254,625 + 8,925 + 0 over the three `/chain` reads; every field and all four totals
  equal. PASS.
- S3: the +0% scenario (4280.0 = the chain spot) greeks equal `pre_expiry.greeks` exactly
  (delta 22.9206, gamma 0.0121, theta −32.449, vega 36.3298, rho 62.2896) and its gross/net equal the curve at grid[30]. PASS.

## UNVERIFIED
- UNVERIFIED: the routes over real HTTP on staging (auth middleware, query parsing in the deployed app): the code is not
  deployed (no deploy/restart allowed in this task). Query validation is covered by pytest through FastAPI's TestClient.
- UNVERIFIED: S4 (the Chart Analysis screen) — frontend scope, built in parallel.
- Timing: TVSMOTOR daily=60 took 3.02 s in the probe including the Kite intraday read; NIFTY daily=250 took 2.66 s for the
  history reads alone (cold cache). Not measured under load.

## Inputs required from user
- none

## Verdict: PASS
Scope of this PASS: the three backend contracts (BE-1 incl. daily_windows, BE-2, BE-3) in pytest and against real staging
data in-process. Not deployed; S4 not in scope.
