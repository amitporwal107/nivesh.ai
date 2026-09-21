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
| TC-2 | API run | `GET /api/research/chart/run`, allowlisted | api | 200; `config_hash` == `research.charting.config.config_hash()`; `fixture` present | **PASS on staging** (API verifier) |
| TC-3 | API symbols | `GET /symbols` | api | equals `manifest.symbols` | **PASS on staging** (API verifier) |
| TC-4 | API ohlcv | `GET /{symbol}/ohlcv` | api + data | bars ascending, unique dates; served file sha256 == manifest | **PASS on staging** (API verifier) |
| TC-5 | API ohlcv | unknown symbol | failure | 404 `unknown_symbol` | **PASS on staging** (API verifier) |
| TC-6 | API ohlcv | symbol with illegal chars (`../x`, lowercase, 40 chars) | edge | 422, no file read | **PASS on staging** (API verifier) |
| TC-7 | API | snapshot missing / malformed / wrong schema_version | failure (unit) | 503 `snapshot_unavailable`, never partial | PASS (local) |
| TC-8 | API indicators | `?ids=sma_20,rsi_14`; unknown id | api/failure | only those ids; unknown → 400 `unknown_indicator` | **PASS on staging** (API verifier) |
| TC-9 | Data | served indicator values vs independent recomputation from served bars | data | match to 1e-9 | **PASS on staging** (API verifier) |
| TC-10 | API patterns | symbol with no patterns | edge | 200 `{patterns: []}` | **PASS on staging** (API verifier) |
| TC-11 | Drawings | POST trendline | api | 201; `user_id` = caller; `drawing_id` uuid | **PASS on staging** (API verifier) |
| TC-12 | Drawings | GET `?symbol=` | api | only caller's drawings for that symbol | **PASS on staging** (API verifier) |
| TC-13 | Drawings | user B GET/PATCH/DELETE user A's drawing | failure | 404; A's `updated_at` unchanged | PASS (local) |
| TC-14 | Drawings | invalid `drawing_type` / <2 anchors for TRENDLINE | edge | 422 | **PASS on staging** (API verifier) |
| TC-15 | UI | open Research → Charts, pick a symbol | e2e | candles + volume render from API (non-empty canvas, `data-testid` present) | **PASS on staging** (after PRs #135 + #136) |
| TC-16 | UI | snapshot `fixture: true` | e2e | loud "synthetic data — not real" banner | **PASS on staging** |
| TC-17 | UI | status chip | e2e | one chip, precedence BLOCKED>INVALID>PIT_UNVERIFIED>STALE>PARTIAL>VALID; drawer shows both fields | **PASS on staging** |
| TC-18 | UI | weekly / monthly timeframe | e2e | visibly disabled with reason (spec G-6), daily works | **PASS on staging** |
| TC-19 | UI | toggle an indicator | e2e | price-pane overlay or new pane appears/disappears | **PASS on staging** |
| TC-20 | UI | 403 from API | e2e | explicit "not enabled for your account" state, no crash | PASS (local, mocked) |
| TC-21 | UI | attribution | e2e | TradingView attribution visible (spec G-9) | **PASS on staging** |
| TC-22 | Build | Charts tab code-split | build | separate chunk for the chart workspace in `vite build` output; main chunk not grown by lightweight-charts | PASS (build: ChartsScreen 219.69 kB separate chunk; main bundle unchanged) |
| TC-23 | UI | draw trendline, reload page | e2e | drawing persists and renders distinct from system overlays | **PASS on staging** |
| TC-24 | Data | bars served for 3 symbols vs raw Kite gz parts read independently | data | identical OHLCV for every date | **PASS on staging** (API verifier) |

## FINAL staging verification (2026-09-22, dev at 3412a763 = PR #136 merged; bundle index-BliwZeWX.js)

Fresh owner session token (admin, `features.charting: true`), held only in 0600 scratchpad files, deleted after the run.

- **API:** `STAGING_COOKIE_HEADER=<0600 file> python3 -m research.charting.tools.verify_staging_api` → **`17/17 checks passed`** (exit 0)
  — TC-2, TC-3, TC-4 ×3, TC-5, TC-6, TC-8, TC-9, TC-10, TC-11, TC-12, TC-14, TC-11/cleanup, TC-24 ×3.
- **UI:** `STAGING_SESSION_FILE=<0600 file> npx playwright test staging-research-charts --project=desktop-chrome`
```
  ✓  1 [auth-setup] › e2e/auth.setup.ts:23:1 › auth setup — inject dark-theme localStorage (3.4s)
  ✓  2 [desktop-chrome] › staging-research-charts.spec.ts:38:1 › TC-15/16/17/21 real staging: symbols, candles, status chip and patterns equal the payloads (1.6s)
  ✓  3 [desktop-chrome] › staging-research-charts.spec.ts:70:1 › TC-18 real staging: weekly and monthly are disabled with a reason; daily is active (1.5s)
  ✓  4 [desktop-chrome] › staging-research-charts.spec.ts:78:1 › TC-19 real staging: bollinger draws exactly its three plotted fields from the real payload (1.6s)
  ✓  5 [desktop-chrome] › staging-research-charts.spec.ts:86:1 › TC-23 real staging: a horizontal line persists through reload and is deleted again (2.5s)
  5 passed (14.4s)
```
- **Scope of the PASS — stated, not implied:** TC-1 (non-allowlisted → 403) and TC-13 (cross-user drawings → 404) need a second
  account; TC-7 (malformed snapshot → 503) would require corrupting the live snapshot; TC-20 (403 UI state) needs a non-allowlisted
  session. These four are verified with real LOCAL evidence only (FastAPI TestClient; mocked Playwright), not on staging.
  TC-22 is a build-output check (separate chart chunk), verified locally.
- **Defects found and fixed during staging verification:** (1) `/symbols` wrapper vs UI bare-array assumption → crash (PR #135);
  (2) RouteErrorBoundary dropped the `/v5` base → nginx 404 (PR #135); (3) provenance drawer `[object Object]` (PR #136).
  Each fix shipped with a test that failed first.
- **UNVERIFIED:** prod `nivesh-mongo` restart count and app-vm disk after the #136 deploy — GCP token expired (`/api/healthz` on
  prod is 200). The #134 deploy coincided with prod Mongo restarting (177 → 180).

## Staging re-run after PR #135 (2026-09-22, dev at 1ffd7697, new bundle index-DBmw1M2i.js)

- **API:** `verify_staging_api` → `17/17 checks passed` (exit 0).
- **UI:** `npx playwright test staging-research-charts --project=desktop-chrome`
  - TC-15/16/17/21 test: the #134 crash is FIXED — symbols, candles, no fixture banner, one status chip whose drawer shows the
    served data_quality/pit fields, pattern rows = served patterns, and attribution all passed. It **FAILED only on the final
    visible-text check**: the provenance drawer renders manifest `source.files` (a list of `{name, sha256}` objects) as
    `"[object Object],[object Object],…"` (`ChartsScreen.tsx:555`, generic `txt(v)` = `String(v)`). The same formatter bug hits
    `String(contract.warmup_period)` for multi-output indicators (`ChartsScreen.tsx:569`, e.g. macd's per-output dict).
  - TC-18, TC-19, TC-23 (run separately with `-g`, since serial mode skipped them): `4 passed` (incl. auth-setup) —
    weekly/monthly disabled with reason; bollinger draws exactly bb_mid/bb_upper/bb_lower from the real payload; a horizontal
    line persists through reload and is deleted via the API.
- **Defect FIXED locally, owner-approved ("fix the defect but do not pick new tasks") — PR #136, awaiting merge:** `txt()` formats
  lists/objects; warmup row uses it; fixtures carry the real nested `source` shape; new regression test failed before the fix
  (reproduced `files[object Object],[object Object]`) and passes after. Local: Playwright 90 passed / 5 skipped, backend 38 passed.
  **Staging re-verification pending:** needs the #136 deploy and a fresh session token.

## API / Endpoint Tests (staging)
**RUN ON STAGING 2026-09-21 after PR #134 merged (merge commit ec32d53d; ab81e3dc in origin/dev).**
Pre-checks: `/api/healthz` 200 · `/api/research/chart/run` 200 (404 before the deploy) · `auth/me` → `features.charting: true`.

- Command: `STAGING_COOKIE_HEADER=<0600 file> python3 -m research.charting.tools.verify_staging_api`
- Output (second run, unedited):
```
PASS  TC-2   HTTP 200; served config_hash 0b169afaa276 vs local 0b169afaa276; fixture=False
PASS  TC-3   HTTP 200; 50 symbols served vs 50 in the committed manifest
PASS  TC-4   RELIANCE: HTTP 200; 1417 bars, ascending+unique=True, identical to committed snapshot=True
PASS  TC-4   TCS: HTTP 200; 1417 bars, ascending+unique=True, identical to committed snapshot=True
PASS  TC-4   HDFCBANK: HTTP 200; 1417 bars, ascending+unique=True, identical to committed snapshot=True
PASS  TC-5   HTTP 404 'unknown_symbol | RES-001 | NOT_FOUND'
PASS  TC-6   lowercase → 422; 40 chars → 422
PASS  TC-8   ids filter → ['rsi_14', 'sma_20']; unknown id → HTTP 400 'unknown_indicator: not_an_indicator | VAL-001 | BAD_REQUEST'
PASS  TC-9   sma_20 @ 2026-09-18: served 1284.705000 vs independent 1284.705000
PASS  TC-10  HTTP 200; 16 patterns served vs 16 in the committed manifest
PASS  TC-11  HTTP 201; drawing_id=set
PASS  TC-12  HTTP 200; new drawing listed=True; 1 listed
PASS  TC-14  bad type → 422; TRENDLINE with 1 anchor → 422
PASS  TC-11/cleanup DELETE → 200; GET after delete → 404
PASS  TC-24  RELIANCE: 1417 raw rows vs 1417 served, mismatches 0
PASS  TC-24  TCS: 1417 raw rows vs 1417 served, mismatches 0
PASS  TC-24  HDFCBANK: 1417 raw rows vs 1417 served, mismatches 0
NOT TESTED  TC-1   needs a non-allowlisted account (covered by local TestClient suite)
NOT TESTED  TC-13  needs a second user (covered by local TestClient suite)

17/17 checks passed
```
- **Disclosure — TC-8 failed on the first run.** The route returns `unknown_indicator: <ids>`; the check demanded exactly `unknown_indicator`. Behaviour was correct (400, offending id named), so the contract was updated to "code token before an optional `: <detail>`" and the check now matches the token. The first run's output (16/17) is kept at the orchestrator's scratchpad `staging_api_run.txt`.

### Earlier local evidence
**NOT RUN on staging** — see `OVERRIDE_charting_v1_app_surface.md`. Local evidence only:

- **pytest (local, FastAPI TestClient):** `cd backend && /opt/nidp/venv/bin/python3 -m pytest tests/test_research_chart.py tests/test_research_drawings.py tests/test_charting_feature_flag.py tests/test_research_feature_flags.py -q`
  - Output: `37 passed in 1.55s`
  - Caveat: `/opt/nidp/venv` has fastapi 0.115.14 / pydantic 2.13.4 vs the backend pins 0.110.1 / 2.12.5 (no backend-pinned venv on this host).
- **Router mount (real app import):** 7 routes under `/api/research/` mounted — chart `run`, `symbols`, `{symbol}/ohlcv`, `{symbol}/indicators`, `{symbol}/patterns`; drawings `/`, `/{drawing_id}`.
- **Research engine:** `python3 -m pytest research/charting/tests -q` → `386 passed in 15.13s`.

## UI / Playwright Tests
**STAGING RUN 2026-09-21 — FAIL (real defect found):**
- Command: `STAGING_SESSION_FILE=<0600 file> npx playwright test staging-research-charts --project=desktop-chrome`
- Output: `1 failed · 3 did not run` (TC-15 timed out; serial mode stopped the rest). Re-run: same.
- **Root cause (traced in a real browser):** clicking Charts → `/run` 200, `/symbols` 200, then `TypeError: as.find is not a function`
  in ChartsScreen. The API returns `{"symbols": [...]}`; the UI expected a bare array — and the hand-written mock fixture was a
  bare array too, so every mocked test agreed with the wrong assumption. The route error boundary then did
  `window.location.replace("/dashboard")` without the `/v5` base path → nginx 404 (pre-existing bug, `RouteErrorBoundary.tsx:74`).
- **Fix (local, NOT yet deployed):** `contract.ts` unwraps `{symbols}` and returns an error — never a crash — on any other shape;
  fixture corrected to the real shape; new backend contract test `test_ui_fixtures_have_the_real_api_top_level_shape` compares every
  UI fixture with the real API response — proven to FAIL on the old fixture (`API returns dict, fixture is list`). Local: build OK,
  mocked suite 21 passed.

### Earlier local evidence
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

## Verdict: PASS
