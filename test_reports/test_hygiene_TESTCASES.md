# Test cases: test hygiene (broken or flaky tests and test tooling)

- **Branch:** chore/test-hygiene (based on origin/dev 19263e08)
- **Date:** 2026-10-24
- **Author:** Claude (QA engineer)
- **Scope:** test files and test tooling only. No product code changes.
- **Environment:** throwaway containers on the staging app VM, with `--network none`.
  - Backend tests run in `nivesh/backend:staging` (Python 3.11.17, pytest 9.0.3, anyio 4.13.0, no pytest-asyncio).
  - Frontend tests run in `mcr.microsoft.com/playwright:v1.47.0-jammy`, with `@playwright/test` from the
    `wl-fe-node-modules` volume and Chromium from the `pw-browsers-1223` volume.

Written before the fixes. Each case states the before result measured on the clean tree and the after result
that counts as PASS.

| ID | Item | Scenario | Type | Expected after the fix |
|----|------|----------|------|------------------------|
| TC-1 | 1 | `pytest tests/test_copilot_backtest.py`. Before: 8 failed with "async def functions are not natively supported", 20 passed. | unit | 28 passed. The 8 coroutine tests actually run their bodies. |
| TC-2 | 1 | The fix adds no dependency (`backend/requirements.txt` is unchanged) and only touches `test_copilot_backtest.py`. | tooling | Diff shows no requirements or conftest change. |
| TC-3 | 1 | Coroutine tests run on asyncio only, not also on trio. trio 0.34.0 is installed in the image, so anyio's default `anyio_backend` would add a trio run of each test. | edge | Collected count stays at 28 (8 async tests, each once), with no `[trio]` ids. |
| TC-4 | 1 | The fix has teeth: a deliberately broken assertion inside one coroutine test fails. | edge | A throwaway copy with one flipped assertion reports 1 failed. |
| TC-5 | 1 | No regression in the other asyncio-marked files under `backend/tests` (`test_chat_insight_card`, `test_copilot_portfolio_compare`, `test_copilot_symbol_resolution`, `test_recommendation_engine/test_ac_coverage`, `test_recommendation_engine/test_orchestrator`). Before: 19 failed, 44 passed, 1 skipped. | regression | Identical counts: 19 failed, 44 passed, 1 skipped. They are untouched; noted as a follow-up. |
| TC-6 | 2 | `test_risk_tools.py` run after the backend desk, F&O and smart-money files in one invocation. Before: 42 failed with "There is no current event loop". | regression | All 44 risk-tools tests pass in that same invocation. |
| TC-7 | 2 | `test_risk_tools.py` alone. Before: 44 passed. | unit | 44 passed. |
| TC-8 | 2 | The fix does not change global event-loop state for later files: `test_tax_engine_integration.py` and `test_recommendation_engine.py`, which use the same `get_event_loop()` pattern, run after it. | regression | Their results are the same as on the clean tree in the same order. |
| TC-9 | 2 | The whole `nidp/services/copilot_agent/tests` directory after the NIDP desk, F&O and smart-money files. Before: 27 failed, 376 passed, 17 errors (the failures are in other files and are not order-dependent). | regression | No new failure. The risk-tools part stays green. |
| TC-10 | 3 | Playwright TC-F3 in `copilot-app-desk-smart-money.spec.ts` on 2026-10-24. Before: expected `51d ago`, got `53d ago`. | e2e | Passes with the browser clock fixed at 2026-10-22 12:00 IST. |
| TC-11 | 3 | The rest of the smart-money spec is unaffected, because only TC-F3 freezes the clock. | regression | Whole spec passes. |
| TC-12 | 4 | `copilot-app-desk-strategy-graphs.spec.ts` through the standard recipe (normal build). Before: 31 failed. | e2e | Still fails the same way on a normal build, which shows the harness is not compiled in by default. |
| TC-13 | 4 | `copilot-app-desk-strategy-graphs.spec.ts` through the new `frontend-v5/e2e/fe-run-stgraph.sh`. | e2e | 31 passed. |
| TC-14 | 4 | The script builds into a separate output directory, never `frontend-v5/dist`, and normal builds stay harness-free. | tooling | After a normal build, the bundle contains no `StrategyGraphsHarness` chunk or `__STRATEGY_FIXTURE__` string. The harness build contains both. |
| TC-15 | 4 | The spec header points at the script that now exists in the repo. | doc | `grep fe-run-stgraph` finds the header line and the script. |
