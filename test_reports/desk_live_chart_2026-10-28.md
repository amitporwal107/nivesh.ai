# Functionality Verification Report — Trade Desk › Chart Analysis › Live chart (the owner's design, 28 Oct)

- **Branch:** feat/desk-live-chart-design (from origin/dev 48556220)
- **Date:** 2026-10-28
- **Author:** Claude (full-stack developer + design engineer + QA)
- **Environment:** unit and mocked-UI runs in containers on the app VM; read-only data check inside `nivesh-staging-app-backend` (staging runs `dev`, so the new routes themselves are not deployed)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
`?tab=trade&view=chart&sub=live` now renders the owner's Live chart in place of the old ChartTab + ticket. The full research
chart stays on Market Desk › Stock Research.
- **Left column:** the chart card. Its parts:
  - the header and the plain-words headline;
  - the PATTERN / CONFIRMATION / VOLUME / F&O toggles;
  - the 15m candles with the WATCH / READY / CONFIRMED / RVOL pills, entry, STOP, T1, T2, EMA 20, the last-price circle, VALID UNTIL and the F&O markers;
  - the futures OI strip by 4-bar window, with a Current / Next / Far / Consolidated selector;
  - the legend with NO FILL YET.
- **Right column:** the PAPER ORDER TICKET. There is no slider. The quantity is `account_size`. Risk per trade is the profile's own figure, read-only, with a link to Risk Desk › Policy & runtime. Place sends the existing paper-trade POST and shows the allow / reduce / block answer.
- **Below:** the F&O SETUP card and the SIGNAL CONDITIONS card. The structure is labelled "CANDIDATE STRUCTURE" and links to Trade Desk › Strategy Lab.

Two new read-only routes:
- `GET /api/fno/{symbol}/futures/oi-buildup`. It uses Kite candles with OI per expiry. Without a Kite session it falls back to the bhavcopy day.
- `GET /api/desk/live-chart/{symbol}`. It returns candles, EMA 20, RVOL, levels, conditions and markers.

## Test Cases
Authored up front: `test_reports/desk_live_chart_TESTCASES.md`.

| ID | Area | Result | Evidence |
|----|------|--------|----------|
| TC-1 | classifier = the board's `buildup_label` (9 cases) | PASS | pytest |
| TC-2/3 | windows by time from 09:15, the baseline session dropped, last window ends 15:30, in-progress flag | PASS | pytest |
| TC-4/5 | consolidated OI change = sum of the three; a month with no trade carries its OI; null until every month has OI | PASS | pytest |
| TC-6 | route, Kite mode: current/next/far + consolidated, one extra session read as baseline | PASS | pytest |
| TC-7 | route, no Kite (token_missing / token_expired / upstream) → end of day per expiry | PASS | pytest |
| TC-8 | GET only; `ReadOnlyKite` gains only `historical_data_oi` (oi=True); no order surface | PASS | pytest (+ test_kite_live_feed) |
| TC-9 | EMA 20 = the indicator engine's `_ema_series`; RVOL over the previous 20 bars | PASS | pytest |
| TC-10 | no Kite → daily bars with "Kite login needed for 15m candles"; a 404 symbol says so | PASS | pytest + Playwright |
| TC-11/12 | conditions on the last COMPLETED bar; trigger waiting → met; pullback_to touch; invalidation hit; validity counts holidays | PASS | pytest |
| TC-13 | stage markers ACCUMULATION→WATCH, EARLY_BREAKOUT→READY, BREAKOUT→CONFIRMED; runs broken by gaps | PASS | pytest |
| TC-14 | plan of another symbol 400, missing plan 404, signal DB down → `markers_error` | PASS | pytest |
| — | Kite's NFO list with two months (after expiry) is re-read; the answer names the missing month | PASS | pytest (added after the staging check) |
| TC-15–24 | the UI cases | PASS | Playwright, 11 tests |
| TC-21 | the Place body is `planCashBody` (the Strategy Lab ticket's body, pinned against the real route by test_decision_card_contract) | PASS | Playwright compares it with the contract's `sent` body. The only difference is that `source` has no `signal_date` (the fixture plan's `setup.signal_date` is null). UNVERIFIED against the real POST from this screen. |
| TC-25 | regressions | PASS | Playwright: desk-shell, trade-desk, lab, decision-cards, scanner, symbol-search, desk |

## API / Endpoint Tests
- **pytest (new and touched suites):** `python -m pytest tests/test_desk_live_chart.py tests/test_fno_routes.py tests/test_kite_intraday.py tests/test_kite_live_feed.py -q`
  - Output: `193 passed, 2 warnings in 9.45s`. Then `tests/test_desk_live_chart.py`: `31 passed, 2 warnings in 6.09s`. That is 30 tests plus the NFO re-read test.
  - Result: PASS
- **Full backend CI allowlist** (255 files, the workflow's own list):
  - Output: `3 failed, 6779 passed, 28 skipped, 15 warnings in 238.03s`.
  - The 3 failures are network-only: `test_cas_api_client.py::test_sandbox_parse_and_map`, `::test_convenience_helper_returns_list` and `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches`. The run uses `--network none`, and their errors are DNS failures for nseindia.com and the CAS sandbox.
  - Result: PASS, with the known network-only failures.
- **Staging HTTP calls to the new routes:** NOT DONE. Staging runs `dev`, so the routes do not exist there until this PR is merged and the backend restarts. See the OVERRIDE.

## UI / Playwright Tests
- **Run 1:** the new spec alone. Command: `run-fe.sh <worktree> … e2e/tests/copilot-app-desk-live-chart.spec.ts` (tsc, then the production build, then Playwright with `--workers=2`).
  - Output: `tsc: clean` · `✓ built in 23.23s` · `10 passed (7.1s)`.
- **Run 2:** regressions across desk-shell, desk-trade-desk, desk-lab, desk-decision-cards, desk-scanner, desk-symbol-search and desk.
  - Output: `3 failed, 2 skipped, 308 passed (7.2m)`.
  - All 3 failures were old ChartTab tests that open `?tab=chart`, which now shows the Live chart. They are scanner TC-16, scanner TC-7 chart@390 and symbol-search SS-9.
  - Fix: TC-7 and SS-9 now point at Market Desk › Stock Research, where ChartTab lives. TC-16 now asserts the Live chart's symbol. The Live chart also gained a plain "No prices on record" answer for a 404.
- **Run 3:** live-chart (now 11 tests), scanner and symbol-search.
  - Output: `tsc: clean` · `116 passed (2.4m)` · `exit 0`.
- Result: PASS.

## Data Correctness (staging, read-only)
A subagent ran these at 04:57 IST on 28 Oct inside `nivesh-staging-app-backend`. It loaded the branch's new modules by file path, wrote nothing and printed no credentials.
- **Platform Kite session: NOT logged in today.** `futures bars: kite call failed (TokenException, AUTH_EXPIRED)` gives `availability: token_expired` for HDFCBANK and NIFTY. Cash 15m candles failed the same way. So the intraday OI windows and the 15m conditions are **UNVERIFIED on real Kite data**, and so is whether `oi` is present on every candle.
- **Kite's NFO list:** `name` = 'HDFCBANK', `expiry` is a `date`, lot 650. After the 27 Oct expiry it still listed the expired month, and January was not listed yet. Only 2 futures pass `expiry >= today`. The fix: the reader re-reads the list (at most every 30 min) while fewer than three are listed, and the answer names the missing month.
- **End-of-day fallback** (HDFCBANK, 2026-10-27, spot 680.2):

  | Expiry | Change | OI change | Label |
  |---|---|---|---|
  | 10-27 | −7.75 | −38,621,050 | long unwinding |
  | 11-23 | −7.8 | +38,107,550 | short build-up |
  | 12-29 | −7.5 | +2,860,000 | short build-up |

  `eod_answer` consolidated: price −7.75, OI 406,337,750, OI change +2,346,500, volume 163,520, `short_buildup`. The labels agree with `shape_futures`' own `oi_buildup`.
- **Option chain:** the default nearest expiry was the one expiring that day (`days_to_expiry 0`), so ATM IV and the expected move were null. The F&O card therefore asks for the first expiry with days left (Playwright pins this). With 2026-11-23: PCR 0.6324, call wall 700, put wall 650, ATM IV 24.16, expected move 35.85 (5.27%).
- **IV history:** 0 sessions recorded for HDFCBANK, so the card shows "not recorded".
- **`positional_signals`:**
  - HDFCBANK's latest signal is 2026-09-25 EARLY_BREAKOUT (entry 750.05, stop 729.06, T 792.04).
  - Stages in the last 10 days: ACCUMULATION 1973, EARLY_BREAKOUT 80, BREAKOUT 6. These are the three the markers map; WEAK and EXTENDED never occur.
  - The conditions on the real daily bars:

    | Condition | Status | Value |
    |---|---|---|
    | ema20 | not_met | 680.20 ≤ 706.03 |
    | volume | met | 1.3× on 10-27 |
    | trigger | waiting | — |
    | validity | expired | — |
    | invalidation | hit | 2026-09-28 |

- **`trade_plans`:** the field names match what the route reads: `entry.desk_entry_rule`, `entry.valid_for_sessions`, `stop.price`, `targets[].name/price/r_multiple` and `setup.signal_date`. That last one is present on every break_above and pullback_to plan; at_once plans often lack it, and the route then uses the latest signal's date.

## Known limits (said on screen)
- **Entry is a single level.** The plan has no entry range, so no band is drawn; the ticket says "One level: the plan sets no range". The chart component draws a band only when it is given a real low and high.
- **Entry policies.** The paper engine's rules are break above, pull back to and at once, and it fills on END-OF-DAY bars. So "Retest of range" and "Next open" are shown, labelled as not engine rules yet. "Range touch" is pull back to. The plan's own rule is the highlighted chip.
- **Signal id.** There is no "S-2041"-style id. The header shows the signal's day and revision ("Signal 25 SEP r1") and the engine version as the detector.
- **CHAIN age.** The chain is end of day, so the card says "Chain end of day · <day>", not "n min old".

## Inputs required from user
- **Kite login.** The day's platform Kite login is needed to see the 15m candles, the intraday OI windows and the 15m conditions on real data.
- **Merge.** A merge of this PR to `dev` and a backend restart (bind mount) are needed to call the new routes on staging.

## Verdict: BLOCKED
Unit, contract and mocked-UI tests pass, and the data shapes were checked read-only on staging. Two things are not yet checked: the new routes over HTTP on staging (not deployed) and the Kite intraday paths (no Kite session today). See `test_reports/OVERRIDE_desk_live_chart.md`.
