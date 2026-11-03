# Functionality Verification Report — Daily Trader Copilot visual answer (backend, Release 2)

- **Branch:** feat/dtc-r2-answers (based on feat/daily-trader-copilot, PR #419)
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** unit tests in a `nivesh/backend:staging` container; real-data capture run in-process inside the
  running `nivesh-staging-app-backend` container (read-only, no restart)
- **Changed areas:** backend routes/services: yes (`backend/services/copilot_visual/`) · frontend src: no (covered by
  `dtc_r2_visual_frontend_20261030.md`)

## Summary
Release 2 adds 5 more visual answers to the engine built in Release 1
(`docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md`), each reusing an existing desk service read-only and one of
R1's existing block types (kpis, ranked, candles, trade_plan, list, notice) — no new block type, no new data model:
`open_trades` (Q13), `fno_setups` (Q10), `trade_validity` (Q8), `exit_options` (Q9), `position_size` (Q12). Intent
routing is the same deterministic regex resolver R1 uses (`backend/services/copilot_visual/intents.py`), extended
with 5 new patterns and a "most specific pattern wins" dispatch when a stock is named.

## Test Cases
> Authored up front (after the contract and R1's own test cases, before the new builders).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R11-R15 | intents | each of the 5 new questions, named-stock and thread-symbol forms | unit | resolves to the right intent, not swallowed by `_NOT_OURS` or a stock_decision/trade-word false match | PASS |
| R16 | intents | a named-stock question that also carries validity/exit/position words | unit | the most specific pattern wins over plain `stock_decision` | PASS |
| R17 | intents | thread-symbol fallback | unit | `trade_validity`/`exit_options` also resolve from the thread's last stock, not only `stock_decision` | PASS |
| B14-B15b | open_trades | real trades, an empty book, a read failure | unit | KPI summary + ranked table with a per-row "ask"; empty/failure shown as a notice/missing, never invented | PASS |
| B16-B17 | fno_setups | a populated board, unbounded sides, an empty board | unit | ranked table, unbounded max loss/profit shown as `None` never a fake number, "no valid payoff" notice when empty | PASS |
| B18-B19c | position_size | account budget only, a named stock that sizes, one that doesn't, equity unknown | unit | limits + usage KPIs; a named stock adds its own sizing from the same risk service `stock_decision` uses; unknown equity shown as missing, not guessed | PASS |
| B20-B23 | trade_validity | nothing changed, direction+stop changed, no earlier plan, no setup today though one was recorded | unit | a `changes` list block states exactly what changed, or that nothing did; the decision block always reflects today's fresh read | PASS |
| B24-B26 | exit_options | an open trade, no open trade in that stock, a read failure | unit | the trade's own entry/last/P&L/distance-to-stop/distance-to-target; never a hold/exit instruction | PASS |
| B27 | fno_top storage | `fno_setups`' plan ids must be openable | unit (regression) | `readers.fno_top` calls `store_trade_plans` itself, matching what the `/top` route does, after a staging capture showed 0 of 5 ids stored | PASS |
| C1 | contract | the real 12-intent staging capture | contract | every payload passes `payload.validate()` with zero problems | PASS |
| F1 | compliance | a follow-up or ranked-row "ask" must never read "buy now" | unit (regression, found this session) | 3 of the 5 new builders generated `"Is {sym} a buy now?"` / `"Is this stock a buy now?"` as a suggested follow-up/ask — the exact phrase `payload.py`'s own facts-block instruction forbids the engine from saying; fixed to `"What's the setup for {sym}?"` | PASS (after fix) |

## API / Endpoint Tests (staging)
No new route: the 5 answers are reached through the existing chat pre-step (`routes/chat.py` → `copilot_visual.prepare`),
already covered by R1's chat-integration tests. Verified instead by running the builders themselves in-process against
real staging data (below), which exercises every real reader (`routes.desk_trading.list_paper_trades`,
`services.strategy_plan.regime_fit.build_top`, `services.risk_profile.read`, `services.risk_book.read`, Mongo
`trade_plans`) the same way the route does.

- **pytest (targeted):** `python -m pytest tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_trade_idea.py -q`
  (container `nivesh/backend:staging`, `--network none`)
  - Output: `162 passed, 1 skipped, 2 warnings in 7.59s`
  - Result: PASS
- **pytest (full CI allowlist, regression):** all 284 files GitHub Actions actually runs (`.github/workflows/backend-tests.yml`)
  - Output: `17 failed, 7426 passed, 34 skipped, 15 warnings in 206.88s`
  - The 17 failures are the same 17 pre-existing failures as an untouched `origin/dev` checkout (cron-schedule/fixture
    tests unrelated to this branch — confirmed by name, not just count, in an earlier run this session before the
    compliance-text fix; the fix touched only 3 literal strings in `builders.py`, re-confirmed clean on this run)
  - Result: PASS, zero new regressions

## Real staging capture (read-only, in-process inside `nivesh-staging-app-backend`)
All 12 intents (7 from R1 + 5 from R2) built against the real NIDP warehouse, Mongo and app Postgres for a real
staging user with 3 open paper trades (SONACOMS, COFORGE, ICICIBANK). Stubbed: auth (an internal request as that
user) and `routes.strategy_plan.store_trade_plans` (records what it would store; writes nothing). Every other read is
real.

```
== open_trades  (0.1s)  q='What are my open trades doing?'  contract_problems=[]
  as_of 2026-10-30 | headline: 3 open paper trades, unrealised ₹1,101.62.
  kpis summary: Open=3; Unrealised P&L=₹1,101.62 (net of estimated costs); Not yet triggered=1

== fno_setups  (2.9s)  q='Which F&O setups are attractive?'  contract_problems=[]
  as_of None | headline: 5 F&O setups fit today's regime (Bearish).
  source stale   None  Desk F&O board (StrategyPlan, fit to today's regime)
  ranked fno: BANKNIFTY Bear put spread 53100/54700, maxloss -14406.0, maxprofit 33594.0, rr 2.31 (+4 more)
  ask: What's the setup for BANKNIFTY?   # fixed from "Is BANKNIFTY a buy now?" — see Test F1

== trade_validity  (2.1s)  q='Is my trade in PNB still valid?'  contract_problems=[]
  headline: PNB: the setup recorded earlier still holds under today's rules.
  list: ['The recorded plan is still the one in force today.']

== exit_options  (0.1s)  q='Should I book profits or hold SONACOMS?'  contract_problems=[]
  headline: SONACOMS: unrealised ₹486.20, ₹890.50 against stop ₹824.60, target ₹957.41.
  notice[info]: Ideas to review, not advice: this shows your trade's own levels and today's price; it does not tell
  you to exit or hold.

== position_size  (1.8s)  q='How much should I risk in PNB?'  contract_problems=[]
  kpis limits: Per trade=0.5% of equity; Max open risk=3%; One position=10%; One sector=25%; Min reward:risk=1.5×
  kpis usage: Paper equity=₹1,000,764.01; Used of today's loss limit=0.00% (limit 2%); Open risk reserved=₹6,914.96
  notice[warn]: PNB does not size on your account: The smallest valid size (one lot per leg) exceeds the per-trade
  budget.

fno_setups plan ids stored in trade_plans: 5 of 5
```
All 12 payloads (not only these 5) had `contract_problems=[]`. `fno_setups`' own source read stale this run (the
desk regime read a null date) — shown honestly as stale, not guessed; this is the real state of that data this run,
not a defect of the answer.

## Data Correctness (staging)
- `open_trades`: the 3 trades shown (SONACOMS 44 qty entry 868.87, COFORGE 18 qty entry 2010.81, ICICIBANK 35 qty
  entry 1413.21) match a direct, read-only count of this account's open rows in `desk_paper_trades` via
  `routes.desk_trading.list_paper_trades`, the same function the desk's own Paper Trades screen calls.
- `fno_setups`: `fno_setups plan ids stored in trade_plans: 5 of 5` — a direct Mongo count
  (`db.trade_plans.count_documents({"plan_id": {"$in": ids}})`) confirms the card's plan_id is a real, openable
  TradePlan, not the pre-fix 0 of 5.
- Result: PASS

## Inputs required from user
- none

## Verdict: PASS
Scope: the backend builders/readers/intents for the 5 Release 2 visual answers, verified by unit tests (162 passed,
targeted; 7426 passed / 17 pre-existing failures, full allowlist — same as `origin/dev`) and a real 12-intent staging
capture with zero contract violations. A SEBI-sensitive wording regression ("buy now" in a system-generated
follow-up/ask) was found via the frontend's compliance regex (see `dtc_r2_visual_frontend_20261030.md`) and fixed
here; the fix is covered by the same unit tests and re-confirmed on a fresh real capture.
