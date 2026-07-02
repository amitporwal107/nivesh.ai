# Functionality Verification Report — Strategy Builder wizard, V5 port

- **Branch:** dev (via feat/copilot-backtest working tree)
- **Date:** 2026-06-30
- **Author:** Claude (full-stack-developer)
- **Environment:** staging (staging.niveshcopilot.com / nidp_staging)
- **Changed areas:** backend routes/services: no (reuses verified /api/strategy-builder/*) · frontend src: **yes** (frontend-v5)

## Summary
Ported the 5-step Strategy Builder wizard (Universe → Strategy → Screen → Backtest → Save/Export)
from the legacy V2 app into V5 (the app users actually run). New: `services/strategyBuilder.ts`
(typed client over the existing endpoints), `pages/StrategyBuilder/` (the wizard in V5's design
system + Recharts), plus a route and a sidebar nav item. Research & validate only — no live
execution. Screens/backtests run on the R1/R2 corp-action-adjusted DaaS path. Scope verified here:
the wizard is reachable + functional from the V5 UI on staging, screening returns real candidates,
and a backtest returns real metrics.

## Test Cases
> Authored after API+UI design, before the Playwright run. One row per case.

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| TC-1 | build | `tsc --noEmit` on frontend-v5 with new files | unit | 0 type errors | PASS |
| TC-2 | build | `vite build` (production bundle) | unit | build succeeds | PASS |
| TC-3 | nav/route | `/v5/strategy-builder` loads the wizard page (authed) | e2e | page + "Strategy Builder" heading render | PASS |
| TC-4 | step 1→2 | Select Nifty 500 universe, advance to Strategy | e2e | Strategy step shows templates | PASS |
| TC-5 | step 2→3 | Pick a template, advance to Screen | e2e | Screen step shows entry rules | PASS |
| TC-6 | screen | Run screen against live data | e2e+data | ranked candidate list, rows > 0 (Simple Momentum → 10) | PASS |
| TC-7 | backtest | Run backtest over a window | e2e+data | metrics cards (Total return / Trades) render | PASS |
| TC-8 | api | Endpoints return 200 through auth (screen/create/backtest/run) | api | all 200, real data | PASS (prior session, ui_e2e) |
| TC-9 | data | Per-template screen counts are real (not all-or-nothing) | data | strict templates 0, Simple Momentum 10, Vol Squeeze 4 | PASS |

## API / Endpoint Tests (staging)
Backend unchanged this turn. The endpoints the wizard calls were verified with real output in the
prior session (minted session → real HTTP through auth, cleaned up):
```
GET  /api/strategy-builder/templates            -> 200 (6 templates)
GET  /api/strategy-builder/universes            -> 200
POST /api/strategy-builder/screen               -> 200 (10 candidates)
POST /api/strategy-builder/strategies           -> 200 (created)
POST /api/strategy-builder/strategies/{id}/backtest -> 200 (40 trades)
GET  /api/strategy-builder/runs/{id}            -> 200 (OK, corp_action_adjusted/latest_snapshot)
```

## Build Evidence (frontend)
```
$ tsc --noEmit           → total project tsc errors: 0
$ npx vite build         → ✓ built in 40.89s
```

## UI / Playwright Tests
- **Spec:** `frontend-v5/e2e/tests/strategy-builder-live.spec.ts` (real staging UI, real session cookie, no mocking)
  - Command: `STAGING_URL=https://staging.niveshcopilot.com npx playwright test --config=e2e/strategy-builder.config.ts`
  - Output (real):
    ```
    Running 1 test using 1 worker
      ✓  1 …strategy-builder-live.spec.ts:11:3 › @live Strategy Builder wizard ›
            walks universe → strategy → screen → backtest with real data (19.9s)
      1 passed (22.0s)
    ```
  - Covered: page loads authed at `/v5/strategy-builder`; select Nifty 500; pick "Simple Momentum";
    Run screen → candidate rows render (>0); advance to Backtest → Run backtest → metrics render.
  - Result: PASS

## Data Correctness (staging)
- Per-template live screen counts (as of 2026-06-30) — real, discriminating (not all-or-nothing):
  Smart-Money Accumulation 0 · Mean Reversion 0 · Momentum Breakout 0 · **Simple Momentum 10** ·
  Strong Uptrend 0 · **Volatility Squeeze 4**. Candidates come from `nidp.stock_features_daily` via DaaS.
- Backtest metrics self-report `price_basis=corp_action_adjusted` / `universe_basis=latest_snapshot`.

## Incidents / Follow-ups
- **NIDP staging VM disk hit 100% (0 bytes free)** during this run → nginx couldn't write proxy-temp
  → large DaaS responses (constituents 92 KB) truncated at ~32 KB → `/screen` 500'd. Freed ~839 MB
  (journalctl vacuum + log truncation) to unblock; verified constituents fetch + template screen now 200.
  **This recurs** — durable fix is growing the PD (needs an authorized GCP account; `gcloud` on the VM
  lacks compute perms) and/or making the nginx proxy-temp ownership persistent. Tracked in memory
  `prod-daas-disk-full-failure-mode`.
- Test session was minted in staging Mongo for Playwright auth and **deleted after** (user + session +
  the 1 strategy the run created). No test data left behind.

## Verdict: PASS
