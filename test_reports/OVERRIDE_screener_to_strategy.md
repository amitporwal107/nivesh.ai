# OVERRIDE — Create Strategy from Copilot-Chat Stock Screener

REASON: The **creation** path is verified on real staging (TC-8/TC-9 PASS). But staging verification of the created strategy's **execution** (screening/backtesting) revealed two gaps, now fixed in code but **not yet re-verifiable this session** because the fixes require (a) a new app deploy to dev/staging and (b) a **separate DaaS API service redeploy** (for `features.py` column additions) — neither has happened yet, and the fixes are not committed/pushed pending user go-ahead. Playwright (TC-10) is also not yet run. Per `.claude/VERIFICATION_PROTOCOL.md` this is the sanctioned loud, recorded skip — the feature is **NOT** claimed complete/verified.

- **Slug:** screener_to_strategy
- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-07
- **Changed areas:** backend routes/services (yes) · frontend src (yes)
- **On origin/dev:** commit `6a47ce34` = FIRST version only (creation works; the two execution gaps below are present on dev/staging right now). The fixes are NOT on dev.

## What works — VERIFIED on real staging (session as aporwal107@gmail.com)
- **TC-8** `POST /api/strategy-builder/from-screen` → HTTP 200, created strategy `dd0b4d4c-ebfc-4cfe-a5e4-a1ffd714a902`. Correct mappings (`roe→roe_pct`, `de→debt_to_equity`, `pe→pe_ttm`, `promoterPledge→promoter_pledged_pct`), `_min→>=` / `_max→<=`, default exit/ranking/rebalance applied, unmappable `bogus_min` returned in `dropped_filters`. **PASS**
- **TC-9** `GET /api/strategy-builder/strategies/{id}` → definition persisted correctly in the DB (read-back matches). **PASS**

## Gaps found by staging verification (TC-8b: does the created strategy actually screen?)
1. **Sector predicate → HTTP 400** `"namespace 'sector' not supported"`. The DaaS/staging path uses the Python evaluator, which lacked sector support (I'd only added it to the SQL compiler). → **FIXED** in `services/strategy_engine/evaluator.py` this session.
2. **Fundamental predicates → 0 matches** (even `pe_ttm ≤ 100000`). The DaaS `/features/bulk` payload (`_FEATURE_COLS` in `nidp/services/daas_api/routers/features.py`) omitted `sector` + all fundamental columns, so the evaluator saw them as null. → **FIXED** by adding those columns (bulk + per-symbol SELECT) this session.

## Fixes — VERIFIED locally this session (real output)
- `py_compile` of `evaluator.py` + `features.py` → **OK**.
- `pytest tests/test_strategy_screen.py tests/test_strategy_engine.py tests/test_screen_to_strategy.py -q` → **`34 passed`** (evaluator sector change caused no regression).
- Inline evaluator check: `sector in [Banking]`→`[HDFCBANK]`, `sector not_in [Banking]`→`[INFY]` (nulls excluded, matches SQL), `feature roe_pct>=15`→`[A]`. **PASS**
- `features.py` column additions **cannot** be unit-tested locally (needs the NIDP Postgres) — verifiable only on staging after the DaaS redeploy.

## NOT verified — still pending
- Re-run TC-8b on staging (fundamental screen returns stocks; sector screen returns 200) — needs the app **and** DaaS redeploys.
- **TC-10** Playwright: chat → run screen → click "Create strategy" → success state. Not run.
- New evaluator sector unit tests were **not** added (user paused that edit).

## To clear this OVERRIDE
1. Commit + push the two fixes to origin/dev (app redeploy).
2. Redeploy the **DaaS API** service (for `features.py`) on nidp-stack-vm.
3. Re-run TC-8b (fundamental + sector screens return correctly), TC-10 (Playwright), paste real output into `screener_to_strategy.md`, flip its final line to `## Verdict: PASS`.

## Status
IN PROGRESS — creation verified on staging; execution-path fixes made + locally verified; staging re-verification of the fixes and Playwright PENDING (need app + DaaS redeploys). Not done, not claimed done.
