# OVERRIDE — Create Strategy from Copilot-Chat Stock Screener

REASON: Staging API + data + Playwright verification (TC-8, TC-9, TC-10) cannot run this session — the change is not yet deployed to dev/staging (app staging redeploys from origin/dev) and I do not have a valid `session_token` cookie for the authenticated `/api/strategy-builder/*` endpoints or the chat UI. I asked the user for a staging deploy + session token; not provided yet. Per `.claude/VERIFICATION_PROTOCOL.md`, this is the sanctioned loud, recorded skip — the feature is **NOT** claimed complete/verified.

- **Slug:** screener_to_strategy
- **Branch:** feat/copilot-backtest
- **Date:** 2026-07-07
- **Changed areas:** backend routes/services (yes) · frontend src (yes)
- **Companion report:** `test_reports/screener_to_strategy.md` (test cases authored up front)

## What this change does
Adds a "Create strategy" action to the existing copilot-chat stock-screener widget that turns the current screen (filters + sector) into a saved STOCK strategy via a new `POST /api/strategy-builder/from-screen`. Backend maps each screener primitive to its `nidp.stock_features_daily` column under the `feature.*` DSL namespace (the columns already exist on that table — no new ingesters), enables the `sector` predicate in the stock compiler, and attaches default exit/ranking/rebalance. The Phase-2 `fundamental.*` namespace stays intentionally unwired (backward-compatible).

## Verified locally THIS SESSION (real output)
- Backend unit tests: `python3 -m pytest backend/tests/test_screen_to_strategy.py backend/tests/test_strategy_engine.py backend/tests/test_strategy_screen.py -q` → **`34 passed in 0.22s`** (12 new bridge tests + 22 existing regression). Covers TC-1..TC-7, TC-12.
- Backend syntax: `py_compile` of the 4 changed backend files → **OK**.
- Frontend typecheck: `npx tsc --noEmit` (frontend-v5/) → **exit 0, clean**. Covers TC-11.

## NOT verified (blocked — require staging deploy + session token)
- **TC-8** `POST /api/strategy-builder/from-screen` on staging → expect HTTP 200 + strategy id.
- **TC-9** Data: created rows in `strategies` + `strategy_versions` with the built definition.
- **TC-10** Playwright: chat → run a stock screen → click "Create strategy" → inline success confirmation.

## To clear this OVERRIDE
1. Deploy this branch to origin/dev (staging redeploys from dev).
2. Provide a valid `session_token` cookie for staging.
3. Then run TC-8 (curl), TC-9 (SQL query), TC-10 (`npx playwright test`), paste real output into `screener_to_strategy.md`, and flip its final line to `## Verdict: PASS`.

## Status
IN PROGRESS — code complete and locally verified (unit + typecheck); staging/UI functional verification PENDING. Not done, not claimed done.
