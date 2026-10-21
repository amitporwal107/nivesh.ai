# Functionality Verification Report — AI Trader Phase 1 (Evidence foundation)

- **Branch:** feat/ai-trader-phase1 (worktree /home/deploy/nivesh-ai-trader, off feat/trading-desk-backend)
- **Date:** 2026-10-21
- **Author:** Claude (PRODUCT_MANAGER + QA_ENGINEER)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: YES · frontend src: no

## Summary
Test cases authored up front per VERIFICATION_PROTOCOL, from docs/prd/AI_TRADER_PHASE1.prd.md §5. Implemented; 43 unit/route tests run in a throwaway container from the staging image (code mounted read-only, no network). NOT run against the real staging API: the branch is not deployed and no session token was available. Index data used is the real files in research/index_history/data; stock bars and auth in route tests are mocked and labelled MOCK in the test file.

## Test Cases
| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | Evidence | Schema: all F1 fields present, confidence in [0,1] | unit | validates | PASS (unit) |
| TC-2 | Evidence | GET evidence for valid symbol/date returns ≥1 per skill | api | 200, schema-valid | PASS (TestClient, mocked bars+auth; staging NOT run) |
| TC-3 | Sealed | as_of=2023-06-01 → UNAVAILABLE/SEALED_GAP | api+unit | no numeric value | PASS (unit+route) |
| TC-4 | PIT | Truncate bars after as_of → outputs unchanged (≥50 dates) | unit/property | identical | PASS (50 random dates, real index files; stock bars synthetic) |
| TC-5 | Validation | n=5 pattern: shrunk + LOW_SAMPLE; n≥30 not | unit | as stated | PASS (unit) |
| TC-6 | Calibration | Synthetic 0.8 hit-rate → bin ≈0.8±0.05; Brier matches hand calc | unit | match | PASS (unit) |
| TC-7 | Errors | unknown symbol 404; missing as_of 422; no auth 401 | failure | codes | PASS 404/422/401 (TestClient) |
| TC-8 | Timeframes | HTF bearish + daily bullish → one opposes contradiction | unit | emitted | PASS (unit) |
| TC-9 | Costs | Expectancy net of costs differs from zero-cost by cost-model amount | unit | match | PASS (unit) |
| TC-10 | Data | Sector rows == sector indices on disk; latest date in freshness band | data | match | PASS (files in repo; warehouse not queried) |
| TC-11 | Perf | p95 < 2 s for one symbol on staging | api | <2 s | NOT RUN |

## API / Endpoint Tests (staging)
NOT RUN on staging (UNVERIFIED). Run so far, in a container from the staging image:

- `python -m pytest tests/test_ai_trader.py -q -p no:cacheprovider` -> `43 passed, 1 warning in 42.80s`
- `python -m pytest tests/test_desk_trading.py tests/test_desk_alerts.py -q` -> `104 passed, 1 warning in 8.13s` (neighbouring suites, no regression)
- `import server` registers `['/api/ai-trader/evidence', '/api/ai-trader/calibration', '/api/ai-trader/pattern-validation']`

Defects the tests caught and that were fixed before this report: timeframe evidence answered from an older bar when `as_of` fell in the sealed block (now withheld, SEALED_GAP); the point-in-time test first flagged a reason-code difference (BEFORE_COVERAGE vs NO_DATA_FOR_DATE on an emptied file) and a last-digit float difference, both test artifacts, no look-ahead found.

## UI / Playwright Tests
Not applicable (backend-only phase).

### Real staging run, 2026-10-21 08:23 UTC (after PR #263 deployed; session token supplied by the user)
- `GET /api/ai-trader/evidence?as_of=2026-10-20` (no cookie) -> `401`; with cookie -> `503 research_engine_unavailable` (also with `symbol=RELIANCE`, and with an unknown symbol, where TC-7 expects 404).
- `GET /evidence` (no as_of) -> `422`; `as_of=bad` -> `422`.
- `POST /calibration` with two 0.8 predictions (one hit) -> `200`, `brier 0.34` (hand calc (0.04+0.64)/2 = 0.34, correct).
- Cause (checked in the running container): `nivesh-staging-app-backend` mounts only `/opt/nivesh-staging/repo/backend:/app/backend` and `/app/data`; `/app/research` does not exist. Fix on branch: read-only mount of `repo/research` in `deploy/nivesh-staging/docker-compose.staging.yml`. Needs a deploy; TC-2, TC-3 (route), TC-11 and the 404 half of TC-7 stay UNVERIFIED on staging until then. Kite daily bars (`/app/research/kite_history/day_2021`) are not in the repo, so symbol-level evidence will still be UNAVAILABLE / BARS_SOURCE_MISSING on staging unless that data is provided.

## Data Correctness (staging)
Not run against the warehouse. Sector rows vs index files and file freshness checked locally (TC-10).

## Inputs required from user
- Deploy of the branch to staging (push + merge to dev is the user's step) and a staging `session_token`, to run TC-2, TC-7, TC-11 against the real API.
- Whether the Kite daily-bars directory exists on staging (`CHARTING_KITE_DAILY_DIR`); if not, symbol-level evidence returns UNAVAILABLE / BARS_SOURCE_MISSING.

## Verdict: BLOCKED
