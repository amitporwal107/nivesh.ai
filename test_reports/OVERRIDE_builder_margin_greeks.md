# OVERRIDE: Desk F&O builder margin wording, record pointer, per-leg Greeks, all charges

REASON: staging render needs merge to dev, frontend image rebuild, backend restart and a user session; local pytest/tsc/Playwright: backend 537 passed (test_strategy_*, test_regime_fit, test_fno_margin, test_chartink_picks, test_chartink_strategy, test_desk_strategy_trades, test_symbol_lookup); tsc --noEmit exit 0; Playwright 196 passed, 16 skipped (opt-in screenshot tests), 2 failed under 4 parallel workers and then passed 3 of 3 serially (7 passed, PW_EXIT=0).

Branch `fix/builder-margin-and-greeks` (base origin/dev 19263e08). Test cases: `test_reports/builder_margin_greeks_TESTCASES.md`.

## What changed
- Backend wording (`services/strategy_plan`): `engine.MARGIN_REASON` now says the payoff calculation does not estimate margin, and that margin for a structure comes only from Zerodha's margin calculator, which needs the platform's daily Kite login. `plan.MARGIN_CAVEAT` and the futures warning (`candidates.py`, plus `live_reads.OLD_FUTURES_WARNING`, which must match it exactly) say the plan does not estimate margin. `ideas.py` and `picks.py` use `plan.MARGIN_CAVEAT` instead of their own copy. The `regime_fit` docstring is corrected.
- PayoffSummary fallback: "the payoff calculation does not estimate margin" replaces "no margin source for this position". CandidateDetail: "The plan does not estimate margin." replaces "No margin source exists in this system." The builder's own override from PR #337 (the calculator's figure, or a pointer to the strip) is unchanged.
- FnoBuilder:
  - The dead "Record as paper trade" button is removed. The note says option structures are recorded from a plan in the full Strategy Builder ("Paper trade this" on a defined-risk candidate) and that the trades typed here are not carried over.
  - The margin strip shows SEBI and stamp duty, with all charges to the paisa and the calculator's own `charges.total`.
- PayoffChart: a per-leg Greeks table in the pre-expiry view only. It is captioned "model estimate (<model>, end-of-day inputs), not a quote" and has a net row from the answer. A missing leg or value prints "—". An empty list prints "Greeks per leg: — (not in this answer)."

## Commands and real output (2026-10-25)

Backend, `sudo docker run --rm --network none -v WT:/work:ro ... nivesh/backend:staging python -m pytest tests/test_strategy_*.py tests/test_regime_fit.py tests/test_fno_margin.py tests/test_chartink_picks.py tests/test_chartink_strategy.py tests/test_desk_strategy_trades.py tests/test_symbol_lookup.py -q -p no:cacheprovider`:
```
537 passed, 3 warnings in 19.91s
tests/test_strategy_payoff.py::test_margin_reason_points_to_the_margin_calculator_and_its_kite_login PASSED
tests/test_strategy_plan.py::test_margin_caveat_names_the_calculator_and_is_shared_by_ideas_and_picks PASSED
tests/test_strategy_plan.py::test_futures_long_buildup_with_cash_confirmation PASSED
tests/test_regime_fit.py::test_margin_is_never_estimated PASSED
```

Frontend typecheck (copy of frontend-v5 in the scratchpad, the WT is not mounted read-write), `npx tsc --noEmit -p tsconfig.json` in `mcr.microsoft.com/playwright:v1.60.0-jammy`:
```
TSC_EXIT=0
```

Playwright: build `VITE_USE_MOCK_API=false VITE_BASE=/v5/ VITE_STRATEGY_HARNESS=1 vite build`, then `vite preview`. Specs: copilot-app-desk-lab, -strategy-builder, -strategy-ideas, -strategy-top, -strategy-graphs. Every /api call is route-mocked (MOCK data in the specs):
```
BUILD_OK
  2 failed
    copilot-app-desk-lab.spec.ts:1626 › OI range walls › TC-5 wrong side ...      (desk-fno-oi-range not found in 5s)
    copilot-app-desk-strategy-graphs.spec.ts:663 › SG-7c futures: IV is disabled ... (payoff-svg not found in 5s)
  16 skipped
  196 passed (6.1m)
```
Neither failing screen is touched by this change. Re-run serially (`--workers=1 --repeat-each=3`):
```
  7 passed (25.6s)
PW_EXIT=0
```
The new and changed cases passed in the full run: TC-6 charges (₹59.40 with SEBI ₹0.01 and stamp duty ₹0.00), TC-6 and TC-9 503, TC-9 margin tile, TC-7 record pointer (opens view=strategy&src_kind=lab), TC-10 per-leg Greeks, TC-10 edge missing, TC-10 edge empty, TC-9 390px no overflow, panel TC-5 TC-6, SG-1c summary fallback, SG-1, SG-2 and SG-8 with the new mock reason.

## Not verified / not done
- UNVERIFIED on staging: nothing is deployed. It needs a merge to dev, a frontend image rebuild, a backend restart and a logged-in session to see the screens with real chain, payoff and margin answers.
- The recorded plan fixtures under `frontend-v5/e2e/fixtures/strategy-plan-*.json`, `desk-strategy-top.json` and `strategy-ideas-real.json` still carry the old backend text. They are old captured answers; specs that pass the text through (strategy-builder `margin`) still pass. They are left as recorded.
- This report is in the branch's `test_reports/`. The session's functionality gate reads `/home/deploy/nivesh.ai/test_reports/`, which this task must not touch.
