# Verification report: test hygiene (broken or flaky tests and test tooling)

- **Branch:** chore/test-hygiene (based on origin/dev 19263e08)
- **Date:** 2026-10-24 (runs finished 2026-10-25)
- **Author:** Claude (QA engineer)
- **Environment:** throwaway containers on the staging app VM, all with `--network none`. Backend tests run in
  `nivesh/backend:staging` (Python 3.11.17, pytest 9.0.3, anyio 4.13.0, trio 0.34.0, no pytest-asyncio).
  Frontend tests run in `mcr.microsoft.com/playwright:v1.47.0-jammy`, with the `wl-fe-node-modules` and
  `pw-browsers-1223` volumes.
- **Changed areas:** backend routes or services: no. Frontend src: no. Only test files, one new test-runner
  script, and these reports.
- **Test cases:** `test_reports/test_hygiene_TESTCASES.md` (written before the fixes).

## Summary

Four test or tooling defects were fixed without changing product code or adding a dependency:

1. `backend/tests/test_copilot_backtest.py`: 8 coroutine tests never ran.
2. `backend/nidp/services/copilot_agent/tests/test_risk_tools.py`: the result depended on test order.
3. Playwright TC-F3 in `copilot-app-desk-smart-money.spec.ts`: the result depended on the date.
4. `copilot-app-desk-strategy-graphs.spec.ts`: the script that builds its test-only harness was missing.

"Before" runs use the `origin/dev` copy of each changed file, either mounted over the edited file (backend) or
from a `git archive origin/dev` copy (frontend). "After" runs use the branch.

Backend command prefix for every run below (shown once):

```
sudo docker run --rm --network none -v <worktree>:/work:ro -w /work/backend -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPYCACHEPREFIX=/tmp/pyc -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test \
  -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest <files> -q -p no:cacheprovider
```

## Item 1: async tests in test_copilot_backtest.py (TC-1 to TC-5)

**Cause.** Eight tests are `async def` functions marked `@pytest.mark.asyncio`. pytest-asyncio is not
installed in the image or listed in `backend/requirements.txt`, so pytest ignored the marker ("Unknown
pytest.mark.asyncio") and failed each test with "async def functions are not natively supported". The test
bodies never ran.

**Fix (test file only).** The markers are now `@pytest.mark.anyio`. anyio's pytest plugin ships inside anyio
(`anyio==4.13.0` is already pinned) and loads automatically. The image lists these pytest11 entry points:

```
pytest11: langsmith_plugin langsmith.pytest_plugin
pytest11: anyio anyio.pytest_plugin
```

trio is also importable, and the plugin's default `anyio_backend` is parametrised over
`('asyncio', 'trio')`. A module-level `anyio_backend` fixture therefore pins the backend to asyncio, so each
test runs once.

This option was chosen over a `conftest.py` hook because it is confined to the one file. A hook in
`backend/tests/conftest.py` would also start running 19 currently failing tests in 5 other files, which changes
other suites' behaviour.

**TC-1. Before:**
```
FAILED tests/test_copilot_backtest.py::test_resolve_instruments_equal_weight
FAILED tests/test_copilot_backtest.py::test_resolve_instruments_explicit_weight_normalised
FAILED tests/test_copilot_backtest.py::test_engine_end_to_end_stock_and_fund
FAILED tests/test_copilot_backtest.py::test_benchmark_unavailable_degrades - ...
FAILED tests/test_copilot_backtest.py::test_engine_flags_insufficient_history
FAILED tests/test_copilot_backtest.py::test_engine_no_instruments - Failed: a...
FAILED tests/test_copilot_backtest.py::test_engine_no_price_data_returns_error
FAILED tests/test_copilot_backtest.py::test_engine_data_call_failure_degrades_not_crashes
8 failed, 20 passed, 8 warnings in 0.44s
```

**TC-1. After:** PASS
```
28 passed in 0.42s
```

**TC-3 (once each, asyncio only):** PASS
```
28 tests collected in 0.35s
tests/test_copilot_backtest.py::test_resolve_instruments_equal_weight PASSED [ 46%]
tests/test_copilot_backtest.py::test_resolve_instruments_explicit_weight_normalised PASSED [ 50%]
tests/test_copilot_backtest.py::test_engine_end_to_end_stock_and_fund PASSED [ 53%]
tests/test_copilot_backtest.py::test_benchmark_unavailable_degrades PASSED [ 57%]
tests/test_copilot_backtest.py::test_engine_flags_insufficient_history PASSED [ 60%]
tests/test_copilot_backtest.py::test_engine_no_instruments PASSED        [ 64%]
tests/test_copilot_backtest.py::test_engine_no_price_data_returns_error PASSED [ 67%]
tests/test_copilot_backtest.py::test_engine_data_call_failure_degrades_not_crashes PASSED [ 71%]
```
The output has no `[asyncio]` or `[trio]` ids, and the collected count is unchanged.

**TC-4 (has teeth):** PASS. A scratch copy flips line 315 (`assert not res.ok` becomes `assert res.ok`) and is
mounted over the file:
```
FAILED tests/test_copilot_backtest.py::test_engine_no_instruments - Assertion...
1 failed, 27 passed in 0.46s
```

**TC-2 (scope):** PASS. The diff touches no requirements or conftest file:
```
 .../copilot_agent/tests/test_risk_tools.py         | 11 ++++++++-
 backend/tests/test_copilot_backtest.py             | 26 +++++++++++++++-------
 2 files changed, 28 insertions(+), 9 deletions(-)
```

**TC-5 (other asyncio-marked files in backend/tests, untouched):** PASS, with identical counts.

Before:
```
19 failed, 44 passed, 1 skipped, 19 warnings in 6.44s
```
All 19 failures are "async def functions are not natively supported" (`grep -c` gives 19). After:
```
19 failed, 44 passed, 1 skipped, 19 warnings in 7.41s
```

## Item 2: order dependence in test_risk_tools.py (TC-6 to TC-9)

**Cause.** `_run()` called `asyncio.get_event_loop().run_until_complete(coro)`. When an earlier test calls
`asyncio.run()`, it leaves the thread's current loop unset. After that, Python 3.11 raises "There is no current
event loop in thread 'MainThread'" from `get_event_loop()`. Several backend desk and F&O test files do this:
when run on their own before `test_risk_tools.py`, `test_desk_alerts`, `test_desk_copilot_prompt`,
`test_desk_overview_backend`, `test_desk_strategy_trades`, `test_desk_trading` and `test_fno_forward` each
broke it.

**Fix (test file only).** `_run()` now creates a private loop per call, runs the coroutine on it and closes it.
It never calls `set_event_loop`. `asyncio.run()` was rejected because it unsets the current loop afterwards,
which would move the same failure onto the files that run after this one.

**TC-6. Reproducing invocation:** the backend desk, F&O and smart-money files, then the NIDP desk, F&O and
smart-money files, then `test_risk_tools.py`. Before:
```
     42 /usr/local/lib/python3.11/asyncio/events.py:681: RuntimeError: There is no current event loop in thread 'MainThread'.
      1 44 failed, 855 passed, 4 warnings in 36.72s
     42 FAILED nidp/services/copilot_agent/tests/test_risk_tools.py
      2 FAILED tests/test_desk_paper_sim.py
```
After, same invocation: PASS
```
      1 2 failed, 897 passed, 4 warnings in 35.34s
      2 FAILED tests/test_desk_paper_sim.py
```
The 2 `test_desk_paper_sim.py` failures are assertion failures in a file that another PR owns. They are the
same before and after, and not related to this change.

**TC-7 (alone):** PASS. Before: `44 passed in 0.19s`. After: `44 passed in 0.17s`.

**TC-8 (later files keep their results):** PASS. Order: predecessors, then `test_risk_tools.py`, then
`test_tax_engine_integration.py`, then `test_recommendation_engine.py`. Before:
```
      1 82 failed, 654 passed, 5 warnings in 40.99s
     31 FAILED nidp/services/copilot_agent/tests/test_recommendation_engine.py
     42 FAILED nidp/services/copilot_agent/tests/test_risk_tools.py
      7 FAILED nidp/services/copilot_agent/tests/test_tax_engine_integration.py
      2 FAILED tests/test_desk_paper_sim.py
```
After:
```
      1 40 failed, 696 passed, 5 warnings in 56.12s
     31 FAILED nidp/services/copilot_agent/tests/test_recommendation_engine.py
      7 FAILED nidp/services/copilot_agent/tests/test_tax_engine_integration.py
      2 FAILED tests/test_desk_paper_sim.py
```
The later files show 31 and 7 failures both before and after.

**TC-9 (whole copilot_agent directory after the NIDP desk, F&O and smart-money files):** PASS, identical before
and after.
Before:
```
      1 27 failed, 376 passed, 2 warnings, 17 errors in 18.16s
     17 ERROR nidp/services/copilot_agent/tests/test_agent_graph.py
      2 FAILED nidp/services/copilot_agent/tests/test_agent_graph.py
     21 FAILED nidp/services/copilot_agent/tests/test_e2e_agents.py
      4 FAILED nidp/services/copilot_agent/tests/test_tax_engine_integration.py
```
After:
```
      1 27 failed, 376 passed, 2 warnings, 17 errors in 24.53s
     17 ERROR nidp/services/copilot_agent/tests/test_agent_graph.py
      2 FAILED nidp/services/copilot_agent/tests/test_agent_graph.py
     21 FAILED nidp/services/copilot_agent/tests/test_e2e_agents.py
      4 FAILED nidp/services/copilot_agent/tests/test_tax_engine_integration.py
```
These failures happen with the directory run alone too (`27 failed, 132 passed, 1 warning, 17 errors`), so they
do not depend on order and are out of scope.

## Item 3: Playwright TC-F3 clock (TC-10, TC-11)

**Cause:** the assertion expects "51d ago" for a disclosure dated 1 Sept 2026. That is true only on 2026-10-22, and the spec never froze the browser clock.

**Fix:** before `goto`, the test calls `page.clock.setFixedTime(new Date("2026-10-22T12:00:00+05:30"))`.

**Before** (clean `origin/dev` copy, standard recipe, smart-money and strategy-graphs specs together):
```
Expected pattern: /…51d ago/
Received string: "…Disclosed 1 Sept 2026 · 53d ago…"
  32 failed
  32 passed
```

**After** (same recipe, branch copy; log `fe-after.log`, section AFTER 1):
```
✓   3 [copilot-app] › e2e/tests/copilot-app-desk-smart-money.spec.ts:247:3 › Smart trading desk · 06 Smart Money Movement › TC-F3: the disclosure date is shown, not the compute date (7.2s)
  31 failed
  33 passed (3.3m)
```
Every one of the 31 remaining failures is in `copilot-app-desk-strategy-graphs.spec.ts`: a grep of the failure lines finds no other spec. Those tests need the harness build (item 4), so failing in a normal build is expected.

## Item 4: strategy-graphs harness runner (TC-12 to TC-15)

**Cause:** the spec opens `?tab=more&view=strategy-graphs`, a test-only page that is compiled in only when the build sets `VITE_STRATEGY_HARNESS=1` (`TradingDesk.tsx:74`). The spec header pointed at `fe-run-stgraph.sh`, which did not exist in the repo, so the standard recipe always failed all 31 tests.

**Fix:** new `frontend-v5/e2e/fe-run-stgraph.sh`, which:
- builds with the flag into a temp directory (never `dist/`) and fails if the harness chunk is missing;
- starts `vite preview` on a strict port and checks that the server is serving this build;
- runs only this spec, then cleans up.

The spec header now points at the script, and the script header documents the docker command for a host without Node. A normal build contains `0` harness chunks, so the harness stays out of normal builds.

**After: the script** (section AFTER 2):
```
fe-run-stgraph: building with VITE_STRATEGY_HARNESS=1 into /tmp/tmp.QmoT6lJ1VD
fe-run-stgraph: build ok, harness chunk StrategyGraphsHarness-BCEn72yG.js
fe-run-stgraph: vite preview serving the harness build on :5174
  31 passed (21.2s)
script exit=0
```

**Guard check: another server already holds :5174** (section AFTER 3). The script refuses to test the wrong build:
```
Error: Port 5174 is already in use
fe-run-stgraph: vite preview on :5174 is not serving the harness build (port taken, or it failed to start)
script exit=1
```

## Follow-ups noted, not changed (outside this PR's four items)

- `test_tax_engine_integration.py` and `test_recommendation_engine.py` in the same copilot_agent directory use
  the same `asyncio.get_event_loop().run_until_complete` helper. After the desk and F&O predecessors they fail
  with the same error: `38 ... RuntimeError: There is no current event loop in thread 'MainThread'.` The same
  four-line `_run` fix applies. `test_agent_graph.py` and `test_e2e_agents.py` use the same pattern inline.
- 19 tests in 5 other `backend/tests` files are still marked `@pytest.mark.asyncio` and never run. The files are
  `test_chat_insight_card`, `test_copilot_portfolio_compare`, `test_copilot_symbol_resolution`,
  `test_recommendation_engine/test_ac_coverage` and `test_recommendation_engine/test_orchestrator`. Converting
  them to `anyio` the same way is a separate change: their bodies have not run in this image, so they may expose
  real failures.
- `backend/tests/conftest.py` sets default test-account tokens and emails in source. This predates this PR and
  is unchanged here. The values are not repeated in this report.

## Data correctness

No data path changed: the diff touches only test files, a test-runner script and reports. No database, feed or
API behaviour was involved, so no data test applies.

## Inputs required from user

none

All four items were verified with real before and after runs. The scope is test files and test tooling only: no product code changed.

## Verdict: PASS
