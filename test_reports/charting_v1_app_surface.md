# Functionality Verification Report — Charting v1 app surface (chart API, drawings, Charts tab)

- **Branch:** feat/charting-pattern-engine
- **Date:** 2026-09-21
- **Author:** Claude (orchestrator; QA_ENGINEER + FULL_STACK_DEVELOPER + DESIGN_ENGINEER)
- **Environment:** staging (staging.niveshcopilot.com) — owner-only behind `require_feature("charting")`
- **Changed areas:** backend routes/services: yes · frontend src: yes

## Summary
Read-only chart API over a committed snapshot (`research/charting/SNAPSHOT_SCHEMA.md`), user-scoped drawings API
(Mongo), and a lazy-loaded "Charts" tab on the V5 Research page using TradingView Lightweight Charts 5.2.1.
Kite-derived data, so owner-only (NI-1). Test cases below were authored BEFORE implementation.

## Test Cases
> Authored UP FRONT — after API + UI design, before implementation. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | API gate | any chart endpoint, account NOT on `charting` allowlist | api/failure | 403 `feature_not_enabled` (admins included) | PASS (local) |
| TC-2 | API run | `GET /api/research/chart/run`, allowlisted | api | 200; `config_hash` == `research.charting.config.config_hash()`; `fixture` present | PASS (local) |
| TC-3 | API symbols | `GET /symbols` | api | equals `manifest.symbols` | PASS (local) |
| TC-4 | API ohlcv | `GET /{symbol}/ohlcv` | api + data | bars ascending, unique dates; served file sha256 == manifest | PASS (local) |
| TC-5 | API ohlcv | unknown symbol | failure | 404 `unknown_symbol` | PASS (local) |
| TC-6 | API ohlcv | symbol with illegal chars (`../x`, lowercase, 40 chars) | edge | 422, no file read | PASS (local; `../x` → 404 route-level, lowercase/over-length → 422; zero file reads either way) |
| TC-7 | API | snapshot missing / malformed / wrong schema_version | failure (unit) | 503 `snapshot_unavailable`, never partial | PASS (local) |
| TC-8 | API indicators | `?ids=sma_20,rsi_14`; unknown id | api/failure | only those ids; unknown → 400 `unknown_indicator` | PASS (local) |
| TC-9 | Data | served indicator values vs independent recomputation from served bars | data | match to 1e-9 | PASS (local) |
| TC-10 | API patterns | symbol with no patterns | edge | 200 `{patterns: []}` | PASS (local) |
| TC-11 | Drawings | POST trendline | api | 201; `user_id` = caller; `drawing_id` uuid | PASS (local) |
| TC-12 | Drawings | GET `?symbol=` | api | only caller's drawings for that symbol | PASS (local) |
| TC-13 | Drawings | user B GET/PATCH/DELETE user A's drawing | failure | 404; A's `updated_at` unchanged | PASS (local) |
| TC-14 | Drawings | invalid `drawing_type` / <2 anchors for TRENDLINE | edge | 422 | PASS (local) |
| TC-15 | UI | open Research → Charts, pick a symbol | e2e | candles + volume render from API (non-empty canvas, `data-testid` present) | PASS (local, mocked) |
| TC-16 | UI | snapshot `fixture: true` | e2e | loud "synthetic data — not real" banner | PASS (local, mocked) |
| TC-17 | UI | status chip | e2e | one chip, precedence BLOCKED>INVALID>PIT_UNVERIFIED>STALE>PARTIAL>VALID; drawer shows both fields | PASS (local, mocked) |
| TC-18 | UI | weekly / monthly timeframe | e2e | visibly disabled with reason (spec G-6), daily works | PASS (local, mocked) |
| TC-19 | UI | toggle an indicator | e2e | price-pane overlay or new pane appears/disappears | PASS (local, mocked; incl. multi-output regression test) |
| TC-20 | UI | 403 from API | e2e | explicit "not enabled for your account" state, no crash | PASS (local, mocked) |
| TC-21 | UI | attribution | e2e | TradingView attribution visible (spec G-9) | PASS (local, mocked) |
| TC-22 | Build | Charts tab code-split | build | separate chunk for the chart workspace in `vite build` output; main chunk not grown by lightweight-charts | PASS (build: ChartsScreen 219.69 kB separate chunk; main bundle unchanged) |
| TC-23 | UI | draw trendline, reload page | e2e | drawing persists and renders distinct from system overlays | PASS (local, mocked) |
| TC-24 | Data | bars served for 3 symbols vs raw Kite gz parts read independently | data | identical OHLCV for every date | PASS (local: RELIANCE/TCS/HDFCBANK 1417/1417 rows, 0 mismatches vs raw gz) |

## API / Endpoint Tests (staging)
**NOT RUN on staging** — see `OVERRIDE_charting_v1_app_surface.md`. Local evidence only:

- **pytest (local, FastAPI TestClient):** `cd backend && /opt/nidp/venv/bin/python3 -m pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py tests/test_research_feature_flags.py -q`
  - Output: `37 passed in 1.55s`
  - Caveat: `/opt/nidp/venv` has fastapi 0.115.14 / pydantic 2.13.4 vs the backend pins 0.110.1 / 2.12.5 (no backend-pinned venv on this host).
- **Router mount (real app import):** 7 routes under `/api/research/` mounted — chart `run`, `symbols`, `{symbol}/ohlcv`, `{symbol}/indicators`, `{symbol}/patterns`; drawings `/`, `/{drawing_id}`.
- **Research engine:** `python3 -m pytest research/charting/tests -q` → `386 passed in 15.13s`.

## UI / Playwright Tests
**LOCAL only, mocked API** (contract-shaped fixtures in `e2e/fixtures/research-chart-*.json`, labelled MOCK):

- **Spec:** `frontend-v5/e2e/tests/research-charts.spec.ts` + neighbouring Research specs (regression)
  - Command: `npx playwright test research-charts research-move-odds research-paper-trades research-access research-qa --project=desktop-chrome`
  - Output: `89 passed (1.8m), 1 skipped`
- **Build:** `npx tsc -b && npx vite build` → `✓ built in 14.87s`; `ChartsScreen-*.js 219.69 kB` separate chunk.
- Integration bug found and fixed during verification: multi-output indicators (bollinger, macd) rendered only their first output; fixed via `plot_fields` in the contract + one series per plotted field; regression test asserts the exact drawn series.

## Data Correctness (local snapshot — real Kite data)
Snapshot `run_id=chart_20260921T172937Z`, 50 symbols, 513 patterns, 10.33 MB, `config_hash` == `config_hash()`.

- 513/513 patterns carry every contract key and exactly the 7 component statuses.
- 0 patterns with any date after their symbol's last bar; 0 pivots confirmed before they occur.
- TC-24: 3 symbols × 1417 bars match raw Kite gz parts read independently (0 mismatches).
- Determinism: two exports → identical sha256 per symbol file.
- **Open data defect (T13):** TMPV 2025-10-14 Tata Motors demerger shows a −12% open gap (400.00 vs 454.95) not flagged by the ratio-based CA rule; 3 TMPV support/resistance patterns span it. Not fixed in this build.

## Inputs required from user
- Admin `session_token` (staging cookie) for authenticated API + Playwright runs — requested, not yet provided.
- Owner account on the `charting` allowlist — satisfied by default (`default_allowlist: [aporwal107@gmail.com]`).
- App-vm free disk ≥ 6 GB confirmed before the `dev` push that deploys this to staging.

## Verdict: BLOCKED
