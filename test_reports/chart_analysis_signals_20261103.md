# Functionality Verification Report — Chart Analysis: timeframes, chart tools and bar signals

- **Branch:** feat/chart-analysis-signals (from origin/dev 19d8d974; commits 13927581, 8866391d, c93a0e2b, this report 28d72b25,
  510230b8 Research chart route kept at 5m–60m) · PR #463 to dev
- **Date:** 2026-11-03
- **Author:** Claude (full stack developer + design engineer + QA)
- **Environment:** branch tests in containers (staging backend image, Playwright 1.60 + Chromium 1223, mocked routes);
  staging read of the routes as deployed today (real Kite data, read only)
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
The owner's "Signals Chart (standalone)" design is built into the existing Trade Desk › Chart Analysis, on real data, with
everything already on the screen kept (stats, walls, max pain, RVOL, trade lines, futures OI, OI Δ, build-up strip, strike
ladder, option chain, basket). New: timeframe pills 1m 3m 5m 15m 1h 1D 1W (the owner: "we specifically need 5 min, 1 hour like
candles changes"), Candles / Line / Area, SMA 20, a drawing-tool rail (crosshair, trend, horizontal, vertical, rectangle, Fib,
measure, undo, clear), a VOLUME pane, a crosshair price tag, wheel zoom / drag pan / Reset view, and six bar-signal pills with
triangles on the bars. Backend: the live-chart route serves 1m/3m (new Kite intervals), 1d and 1w (weeks built from the daily
bars) and SMA 20; the futures OI route takes 1m/3m and up to 10 sessions. Test cases were written first:
test_reports/chart_analysis_signals_TESTCASES.md.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| B1 | live-chart | 5m, 3 sessions | api (pytest) | Kite asked 5m, 3+2 sessions; label 5M; sma20 aligned | PASS |
| B2 | live-chart | 60m, 10 sessions; 1m 3m 30m accepted | api (pytest) | 200, label 1H | PASS |
| B3 | live-chart | 1d | api (pytest) | no Kite read; reason null; 120 bars | PASS |
| B4 | live-chart | 1w + weekly aggregation with a missing day | api + unit (pytest) | OHLCV per ISO week; READY marker on its week | PASS |
| B5 | live-chart | 2h → 400; sessions 11 / 0 → 422 | edge (pytest) | as stated | PASS |
| B6 | live-chart | Kite down at 5m / 60m | failure (pytest) | daily fallback; "Kite login needed for 5m / 1h candles" | PASS |
| B7 | service | SMA 20 values | unit (pytest) | mean of the last 20 closes | PASS |
| B8 | oi-buildup | 1m and 3m, sessions 10; Kite `minute` | api (pytest) | accepted; 2m 400; sessions 11 422 | PASS |
| B9 | regression | live-chart, oi-buildup, options intraday (keeps 5m–60m), Research chart route (keeps 5m–60m), fno routes, the whole CI allowlist | regression (pytest) | all pass | PASS (2 CAS-client tests fail the same on untouched dev: they call an outside sandbox) |
| F1–F3 | toolbar | 15m default; 5m and 1h ask both routes; ?tf= deep link | e2e | interval/sessions as designed | PASS |
| F4 | 1D / 1W | end-of-day bars; 1W asks daily=250 window=5, futures summed per week | e2e | as stated | PASS |
| F5, F7 | chart type, volume | Line / Area / Candles; one volume bar per candle | e2e | as stated | PASS |
| F6 | SMA 20 | the route's sma20 drawn, toggle hides it | e2e | as stated | PASS |
| F8 | bar signals | triangles only where the rule holds; each pill toggles its own | e2e | LB bar 31, SC bar 30, breakouts 25–26, volume spike bar 28 (5m) | PASS |
| F9–F10 | drawing | H line, trend with preview, Fib (7 levels), measure, undo, clear; per timeframe | e2e | as stated | PASS |
| F11–F12 | crosshair, view | price tag on hover; wheel zoom, drag pan, Reset view | e2e | as stated | PASS |
| F13 | regression | the 41 existing Chart Analysis cases (3 specs) | regression e2e | all pass | PASS |
| F14 | phone | 390 px: pills, no rail, no sideways scroll | e2e | as stated | PASS |
| F15 | wording | the new controls and rules | e2e | no buy / sell / stop loss / target / entry / exit / pick / recommend | PASS |
| S1 | staging | after the merge: 1m 3m 1D 1W and SMA 20 on staging | post-deploy | needs the merge (staging runs dev) | NOT RUN |

## API / Endpoint Tests

- **pytest** (staging backend image `nivesh/backend:staging`, the branch mounted read only, network off):
  - Command: `docker run --rm --network none -v /home/deploy/nivesh-dev-worktree:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest tests/test_desk_live_chart.py tests/test_chart_analysis_v2_backend.py tests/test_live_chart_fno_series.py tests/test_fno_routes.py -q -p no:cacheprovider`
  - Output: `188 passed, 2 warnings in 8.53s`
  - Result: PASS
- **Research chart route kept as it was** (510230b8): Kite's service now also serves 1m and 3m, so
  `/api/research/chart-intraday` got its own fixed set (5m 15m 30m 60m). Without it `tests/test_kite_intraday.py::
  test_availability_follows_the_feed_state` (in the CI allowlist) failed, and that route would have accepted 1m with up to 30 sessions.
  - Command: `… python -m pytest -q -p no:cacheprovider tests/test_kite_intraday.py tests/test_desk_live_chart.py tests/test_live_chart_fno_series.py`
  - Output: `76 passed, 2 warnings in 6.52s`
- **The whole CI allowlist** (`.github/workflows/backend-tests.yml`, 136 files) on the branch, same container:
  - Output: `2 failed, 4532 passed, 21 skipped, 13 warnings in 153.86s` — the 2 are `tests/test_cas_api_client.py::test_sandbox_parse_and_map`
    and `::test_convenience_helper_returns_list`.
  - Same file on untouched `origin/dev` (git archive, same container): `2 failed, 3 passed` with the same assertions (`assert 0 > 0`):
    they call an outside sandbox and this run has no network. Not caused by this change; CI has network.
  - Result: PASS
- **Staging, the routes as deployed today** (real Kite data, read only, GET with the staging session cookie). 5m and 60m were
  already accepted by the deployed code, so the two timeframes the owner named can be checked on real data now:
  - `GET /api/desk/live-chart/PETRONET?interval=5m&sessions=3` → `HTTP 200 0.726231s` · `timeframe 5m 5M Kite intraday reason None` · `bars 216 first 2026-10-29T09:15:00+05:30 last ['2026-11-02T15:10:00+05:30', 299.95, 300.25, 299.65, 299.65, 110549.0]` · `rvol max 11.72`
  - `GET /api/desk/live-chart/PETRONET?interval=60m&sessions=5` → `HTTP 200 0.196694s` · `timeframe 60m 60M Kite intraday reason None` · `bars 30 first 2026-10-27T09:15:00+05:30 last ['2026-11-02T14:15:00+05:30', 299.4, 300.4, 298.7, 299.65, 1304578.0]`
  - `GET /api/fno/PETRONET/futures/oi-buildup?interval=5m&window=4&sessions=3` → `HTTP 200` · `mode intraday interval 5m kite_reason None` · `current 2026-11-23 bars 232 last ['2026-11-02T15:35:00+05:30', 302.45, 148200, 27565200] windows 60`
  - `GET /api/fno/PETRONET/futures/oi-buildup?interval=60m&window=4&sessions=5` → `HTTP 200` · `current 2026-11-23 bars 36 last ['2026-11-02T15:15:00+05:30', 302.45, 305900, 27565200] windows 10`
  - `GET /api/desk/live-chart/PETRONET?interval=1d` → `HTTP 400` (the deployed code does not have 1d yet: expected until the merge)
  - Result: PASS for 5m / 1h on real data; 1m, 3m, 1d, 1w and sma20 are S1 (post-deploy).

## UI / Playwright Tests

- **Typecheck:** `npx tsc --noEmit -p tsconfig.json` → `tsc EXIT 0`
- **Specs:** `e2e/tests/copilot-app-desk-chart-analysis.spec.ts` (14 new cases F1–F15 + 12 existing), `copilot-app-chart-analysis-chain.spec.ts`, `copilot-app-chart-analysis-basket.spec.ts`
  - Command: `VITE_USE_MOCK_API=false VITE_BASE=/v5/ npx vite build --outDir /tmp/cp-dist` · `vite preview --port 5174` · `npx playwright test --config pw.copilot-app.config.ts <the three specs> --reporter=line` (container `--network none`; every `/api/*` route-mocked, labelled MOCK in the spec)
  - Output: `55 passed (27.1s)`
  - First run: `2 failed, 53 passed` — F9 and F11 moved the mouse to coordinates measured before the page scrolled the chart
    into view (1280×720 viewport). Fixed in the test (`scrollIntoViewIfNeeded()` before measuring), then 55 passed.
  - Result: PASS

## Data Correctness (staging)

- 5m and 1h candles for PETRONET are Kite's own (source "Kite intraday", reason null), sessions 29 Oct–2 Nov (3) and
  27 Oct–2 Nov (5): the T-1 snapshot before today's open, as the stale-data rule allows. Futures OI per bar is the current
  month contract (23 Nov 2026), OI 2,75,65,200 at the 2 Nov close, matching the "FUT OI 275 L" on the owner's screenshot.
- Found, not caused by this change: the CASH candles end at 15:10 (5m) / 14:15 (1h), so the last 15 minutes (15:15–15:30)
  are missing, while the futures candles run to the close. Same on 30 Oct. Our bar filter
  (services/kite_live_feed/intraday.py `_bar`) does not drop by time, and the Research chart route shows the same.
  **Settled at the source:** Kite's own `historical_data` for PETRONET (NSE cash) on 2 Nov, read in the staging backend with the
  platform login (read only), returns `minute 360 first 09:15 last 15:14`, `5minute 72 last 15:10`, `15minute 24 last 15:00`,
  `60minute 6 last 14:15`, last close 299.65. So the gap is in Kite's cash candles, not in our code; the futures candles are
  a different instrument. Nothing to fix on our side; the chart shows what Kite sends.

## Inputs required from user
- none (the staging session cookie file already on the VM was used for read-only GETs; never printed)

## Verdict: PASS
Branch scope (pytest, typecheck, Playwright, real-data reads of the deployed 5m / 1h routes). S1, the post-deploy check of
1m, 3m, 1D, 1W and SMA 20 on staging, runs after the PR is merged.
