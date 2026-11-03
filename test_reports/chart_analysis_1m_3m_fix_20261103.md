# Functionality Verification Report — Chart Analysis 1m / 3m fix, and the post-merge staging check of #463

- **Branch:** fix/chart-analysis-1m-3m (from origin/dev d1c682c3 = #463 merged) · commit b7fc430f · PR #465 to dev
- **Date:** 2026-11-03
- **Author:** Claude (full stack developer + QA)
- **Environment:** branch tests in the staging backend image (no network); staging = dev d1c682c3 as deployed
  (backend restarted 05:56:38 UTC after the files landed 05:56:21 UTC; frontend image 11:28:51 IST, the bundle has the
  `ca-tf-` pills), real Kite / NIDP data, read only (GETs and page loads with the staging session cookie)
- **Changed areas:** backend routes: yes · frontend src: no

## Summary
#463 (Chart Analysis timeframes, tools, bar signals) was merged and deployed. The post-merge staging check (S1) found that
cash **1m and 3m fell back to daily bars** (`reason intraday_refused`). Cause: the live-chart route read Kite candles by
calling the Research chart's route handler, which keeps its own 5m–60m set (510230b8), so it answered 400. The unit tests
stubbed that read. Fix: the Research route's body is now `read_bars` (all Kite intervals, 1m–60m); the route keeps its own
check; the live-chart route calls `read_bars`. Everything else on staging checked out on real data.

## Test Cases

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R1 | read path | live-chart's real read for every interval it accepts (1m 3m 5m 15m 30m 60m) | api (pytest, only Kite / feed / token stubbed) | served, no 400 | PASS (FAIL without the fix: the staging error) |
| R2 | research route | `/api/research/chart-intraday` 1m | api (pytest) | 400 as before; 5m served | PASS |
| R3 | regression | chart tests + whole CI allowlist | regression (pytest) | pass | PASS (3 network-only failures, see below) |
| S1a | staging API | PETRONET 5m 15m 1h 1D 1W | post-deploy | Kite / EOD candles, sma20 aligned | PASS |
| S1b | staging data | SMA 20 and weekly bars against the raw bars | data | SMA 20 = mean of last 20 closes; weeks = daily rebuilt | PASS |
| S1c | staging API | futures OI 1m 3m 1h, and 1W's 250 bhavcopy sessions | post-deploy | Kite per bar; bhavcopy T-1 | PASS |
| S1d | staging UI | pills 5m 15m 1h 1D 1W on PETRONET | live Playwright | pill pressed, candles + volume + futures OI + signals, SMA toggle, all 200, no page errors | PASS |
| S1e | staging API | PETRONET 1m and 3m | post-deploy | Kite candles | FAIL on #463 → this PR; re-run after merge: NOT RUN |

## API / Endpoint Tests

- **R1 / R2 without the fix** (route changes stashed, new tests kept):
  - Command: `docker run --rm --network none -v <worktree>:/work:ro -w /work/backend … nivesh/backend:staging python -m pytest -q -p no:cacheprovider tests/test_desk_live_chart.py -k "real_read or research_route_keeps"`
  - Output: `E fastapi.exceptions.HTTPException: 400: interval must be one of 5m, 15m, 30m, 60m` · `1 failed, 1 passed, 44 deselected`
- **With the fix:**
  - Command: `… python -m pytest -q -p no:cacheprovider tests/test_desk_live_chart.py tests/test_kite_intraday.py tests/test_chart_analysis_v2_backend.py tests/test_live_chart_fno_series.py tests/test_fno_routes.py`
  - Output: `203 passed, 2 warnings in 9.23s`
  - Result: PASS
- **Whole CI allowlist** (301 files from .github/workflows/backend-tests.yml, same container, no network):
  - Output: `3 failed, 8873 passed, 29 skipped, 15 warnings in 247.63s` — `test_cas_api_client.py::test_sandbox_parse_and_map`,
    `::test_convenience_helper_returns_list` ("Sandbox call failed — check network / keys") and
    `test_nidp_stamp_broadcast_at.py::test_run_commits_in_batches` (`Cannot connect to host www.nseindia.com:443 … Temporary failure in name resolution`).
    All three need the internet; none is in code this PR touches. CI on GitHub has network.
  - Result: PASS
- **Staging, #463 as deployed** (`python3 -I scratchpad/s1/s1_api.py`, checked at 2026-11-03T11:29:35+05:30, PETRONET):
  - `live-chart 5m s=3 -> HTTP 200 tf=5m/5M source='Kite intraday' reason=None bars=171 days=3 last=2026-11-03T11:25 sma20 aligned nonnull=171` · `sma20 check: route 296.66 vs mean(last 20 closes) 296.6625 -> MATCH`
  - `live-chart 15m s=2 -> HTTP 200 tf=15m/15M Kite intraday bars=33` · sma20 `298.39 vs 298.3900 MATCH`
  - `live-chart 60m s=10 -> HTTP 200 tf=60m/1H Kite intraday bars=57 days=10 first=2026-10-21` · sma20 `292.63 vs 292.6275 MATCH`
  - `live-chart 1d -> HTTP 200 tf=1d/DAILY source='nidp.prices_eod_adjusted (end of day)' reason=None bars=120 first=2026-05-13 last=2026-11-03` · sma20 MATCH
  - `live-chart 1w -> HTTP 200 tf=1w/WEEKLY bars=104 first=2024-11-11 last=2026-11-02` · sma20 `285.67 vs 285.6675 MATCH` ·
    `weekly vs daily rebuild: 25 weeks match, 0 differ (of 25 full weeks in the daily window)`
  - `oi-buildup 1m -> mode=intraday interval=1m kite_reason=None current 2026-11-23 bars=136 last 11:29` · `3m bars=175` · `60m s=10 bars=67 windows=19`
  - `oi-buildup daily=250&window=5 -> daily_bars=250 daily_last=['2026-11-02', 301.85, …] daily_windows=50` (bhavcopy, T-1)
  - `live-chart interval=2h -> HTTP 400` · `interval=5m&sessions=11 -> HTTP 422`
  - **`live-chart 1m s=1 -> HTTP 200 tf=1d/DAILY reason='intraday_refused'`, same for 3m → the bug this PR fixes.**
  - Baseline before the merge (05:43 UTC): 1m / 3m / 1d / 1w → 400, sessions=10 → 422, so the 200s above are #463's code.

## UI / Playwright Tests

- **S1d, live staging** (`scratchpad/s1/s1-chart-staging.spec.ts`, deployed app at staging.niveshcopilot.com:8443, session
  cookie from a file, page loads and pill clicks only), `S1_TFS=5m,15m,1h,1D,1W`:
  - `5m  meta "NSE · CASH · 5M"  bars 61 (112–173 of 173)  candles 61  vol 61  futOi 1  signals 9  sma 1  fallback 0`
  - `15m meta "NSE · CASH · 15M" bars 34  candles 34  vol 34  futOi 1  signals 11`
  - `1h  meta "NSE · CASH · 1H"  bars 57  candles 57  vol 57  futOi 1  signals 11`
  - `1D  meta "NSE · CASH · DAILY" bars 61 (59–120)  futOi 1  signals 3` · `1W meta "NSE · CASH · WEEKLY" bars 61 (43–104)  futOi 1  signals 6`; readout "Week of 2 Nov 2026"
  - `S1 SMA toggle: ca-sma 1 -> 0` · network: every live-chart and oi-buildup call `200` (1W asked `daily=250&window=5`) · `S1 PAGE ERRORS []`
  - Output: `1 passed (12.5s)` · Result: PASS
- Frontend source is unchanged by this PR.

## Data Correctness
- SMA 20 recomputed from the route's own closes on all five working timeframes: match to the cent.
- Weekly bars recomputed from the daily answer (first open, max high, min low, last close, summed volume, ISO week): 25/25.
- Candles are today's live session (last 5m bar 11:25 IST) and futures bhavcopy T-1 (2 Nov): within the no-stale-data rule.

## Unverified / Follow-ups
- UNVERIFIED: 1m / 3m Kite candles on staging, because this fix is not merged. After the merge and the backend restart:
  `python3 -I scratchpad/s1/s1_api.py` (expect `tf=1m/1M source='Kite intraday'`) and the S1 spec with all seven pills.

## Verdict: PASS
