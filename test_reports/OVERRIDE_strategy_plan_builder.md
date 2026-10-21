# OVERRIDE — Strategy plan builder (branch `feat/strategy-plan`, wave 2 backend)

REASON: Not deployed to staging (the branch is stacked on `feat/strategy-calc`, unpushed, and this agent may not push or write to staging), and the routes need a signed-in session token this agent does not have. Verified instead: 60 new unit tests plus the neighbouring payoff, F&O and scenario tests (235 passed, runner output below) with every source mocked and labelled MOCK. NOT verified: the real source readers in `services/strategy_plan/sources.py` against live DaaS and the app database. Read-only warehouse checks only confirmed that the columns the evidence uses exist (stock_features_daily pe_ttm, pb, roe_pct, roce_pct, debt_to_equity, market_cap_cr, fundamentals_source; index_constituents.industry; event_calendar) and are populated on 2026-10-19 (pe_ttm 1672 of 2480 rows, pb 2073, roe_pct 2072).

To finish: merge the stack, deploy, then as a signed-in user `POST /api/desk/strategy/plan` with `{"underlying":"RELIANCE","direction":"bullish"}` and read every `source_snapshots[].ok`.

```
$ py-run-stplan.sh tests/test_strategy_plan.py tests/test_strategy_payoff.py tests/test_fno_routes.py tests/test_positional_scenario.py
235 passed in 8.81s
```
