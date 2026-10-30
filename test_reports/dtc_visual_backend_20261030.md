# Functionality Verification Report — Daily Trader Copilot visual answer (backend, Release 1)

- **Branch:** feat/dtc-visual-backend
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging (in-process inside `nivesh-staging-app-backend`, real NIDP warehouse / Mongo / app Postgres; read only)
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
Built the backend of the Copilot's visual answer (contract `visual-answer-v1`,
`docs/daily_trader_copilot/VISUAL_ANSWER_CONTRACT.md`):
- `backend/services/copilot_visual/`: a deterministic resolver for the 7 Release-1 intents, one builder per intent reading
  existing services in-process (`readers.py`), the payload assembly with per-source freshness, a contract check that
  mirrors the frontend zod schema, and the facts block for the engine.
- A delimited pre-step in `routes/chat.py stream_chat`. It emits one `visual_answer` widget, which is also saved on the
  message. It passes the facts as a `visual_answer` data block and pins the explaining node.
- `copilot_trade_idea.TradeIdea` now keeps the built `plan` and `sized`, so the plan is built once.

Verified here:
- unit, integration and contract tests (no network);
- the existing chat and trade-idea suites against the untouched base;
- each of the 7 builders run in-process inside the staging backend container against real staging data (read only).

Not verified: the deployed `/api/chat/stream` endpoint (the branch is not deployed) and the LLM's narrative.

## Test Cases
> Authored up front (after reading the contract and the frontend schema, before implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R-1 | resolver | "What is the market view today?", "Is the market trending?", "Nifty and Bank Nifty view" | unit | market_view | PASS |
| R-2 | resolver | "Where is smart money moving?", "FII DII flows this week", "Which F&O stocks show long build-up today?" | unit | smart_money | PASS |
| R-3 | resolver | "Today's top 5 opportunities", "top 10 trade ideas today" | unit | top_opportunities, N parsed (5 / 10) | PASS |
| R-4 | resolver | "Which breakouts are confirmed?", "stocks breaking out today" | unit | breakouts | PASS |
| R-5 | resolver | "Which stocks have unusual volume?", "volume spike stocks" | unit | unusual_volume | PASS |
| R-6 | resolver | "Is RELIANCE a buy now?", "entry, target and stop-loss for INFY", "entry and SL for infy", "Trade plan for TVSMOTOR", "Is the TCS breakout confirmed?"; investor-persona "Is RELIANCE a buy now?" → None | unit | stock_decision with the symbol | PASS |
| R-7 | resolver | "Is this stock a buy now?" with last_symbol TVSMOTOR; without last_symbol | unit | stock_decision TVSMOTOR; None | PASS |
| R-8 | resolver | "What is the expected move in Nifty?", "Bank Nifty expected move", "NIFTY PCR and max pain" | unit | expected_move NIFTY / BANKNIFTY | PASS |
| R-9 | resolver (neg) | "What are my open trades doing?", "Which F&O setups are attractive?", "Should I book profits or hold TCS?", "Show the FIXCO chart", "What is the PCR?" with stock words | unit | None (R2 / not ours); PCR, F&O, P&L, GIFT, IV, OI, ATM, VIX, NIFTY never a stock | PASS |
| R-10 | resolver | last_symbol from the thread: a saved visual_answer / trade_plan widget, else the newest user message naming a stock | unit | the newest symbol | PASS |
| B-1 | market_view | all sources fresh (stubbed) | unit | kpis (Nifty, Bank Nifty, VIX, breadth, FII, DII), candles NIFTY 60 bars + EMA20/50 + walls + max pain + band, heatmap; data_quality fresh; payload validates | PASS |
| B-2 | market_view | chain read fails, sector route stale | failure | no band / walls; notice + data_quality.missing for the chain; stale sector source → stale=true + notice; no invented number | PASS |
| B-3 | smart_money | fresh | unit | bars FII + DII (10 sessions, oldest first), heatmap 1-week, quadrant, ranked long buildup / short covering | PASS |
| B-4 | smart_money | FII/DII missing, buildup stale (404 from the route) | failure | notices + missing; other blocks still built | PASS |
| B-5 | top_opportunities | stored day fresh | unit | ranked top N with plan_id per row, trade_plan block for the first plan_id | PASS |
| B-6 | top_opportunities | no stored day / stale day | edge | notice; stale day flagged; no ranked invented | PASS |
| B-7 | breakouts | bucket with rows | unit | ranked + candles of the first with breakout + stop levels + bars volume × | PASS |
| B-8 | breakouts | empty bucket | edge | info notice "no stock met the rule on <date>", no fake rows | PASS |
| B-9 | unusual_volume | snapshot rows | unit | only eligible vol_z20 ≥ 2, ranked by vol_z20; bars rvol; delivery column dated; stale delivery flagged | PASS |
| B-10 | stock_decision | plan status plan / wait / no_trade / insufficient_data | unit | decision setup_ready / wait / avoid / no_setup with the fixed labels; trade_plan block only with a plan_id; kpis from the risk service sizing | PASS |
| B-11 | stock_decision | plan could not be built | failure | no decision, warn notice, missing entry | PASS |
| B-12 | expected_move | chain fresh | unit | kpis ATM IV, ± move, PCR, max pain, expiry; candles with band and walls | PASS |
| B-13 | expected_move | chain stale (route 404) | failure | notice + missing, no kpis invented | PASS |
| C-1 | contract | every built payload passes `validate()` (mirror of the frontend zod schema) | unit | [] problems | PASS |
| C-2 | contract | the REAL capture `frontend-v5/e2e/fixtures/contract-visual-answer.json` validates for all 7 intents | unit | [] problems | PASS |
| F-1 | facts | facts block carries the headline, KPI values, dates and missing list; stock_decision's first upper-case token is the symbol (stock node resolves it) | unit | as stated | PASS |
| CH-1 | chat | a market question: one `visual_answer` widget frame before tokens, saved on the message, facts passed as `visual_answer` data block, pin market_analyst, no trade-idea build | integration | as stated | PASS |
| CH-2 | chat | stock_decision: trade idea built ONCE, visual widget only (no separate trade_plan card), TRADE_PLAN + visual facts both passed, pin stock_analyst | integration | as stated | PASS |
| CH-3 | chat | a question with no intent | integration | exactly today's path (existing tests stay green) | PASS |
| CH-4 | chat | builder raises | failure | today's path, no widget from the visual step | PASS |
| CH-5 | chat | a position question / a client pin | edge | visual step skipped | PASS |
| S-1 | staging | each of the 7 builders in-process on staging with real data | api (in-process) | payload per intent, real numbers with as_of, validates | PASS |
| REG | regression | tests/test_copilot_trade_idea.py, tests/test_chat*.py, tests/test_broker_contract_chart.py | unit | no new failure against the untouched base (same 37 pre-existing failures/errors) | PASS |

## API / Endpoint Tests (staging)

### pytest (backend image, `--network none`)
Command, from `/home/deploy/nivesh-wt-dtc-be`:
`sudo docker run --rm --network none -v "$PWD/backend":/app/backend -v "$PWD/frontend-v5/e2e/fixtures":/app/frontend-v5/e2e/fixtures -w /app/backend -e MONGO_URL=mongodb://placeholder:27017 -e DB_NAME=placeholder -e OPENAI_API_KEY=placeholder nivesh/backend:staging python -m pytest <files> -q -p no:cacheprovider`

| Run | Files | Output (last line) |
|---|---|---|
| New tests, including C-2 on the real capture | `tests/test_copilot_visual.py tests/test_copilot_visual_chat.py tests/test_copilot_trade_idea.py` | `112 passed, 2 warnings in 8.21s` |
| Regression on this branch | `tests/test_copilot_trade_idea.py tests/test_broker_contract_chart.py tests/test_desk_copilot_prompt.py tests/test_chat*.py` | `15 failed, 204 passed, 11 warnings, 22 errors in 34.89s` |
| The same suites on the untouched base (`git archive 21c8ae13`) | as above | `15 failed, 204 passed, 11 warnings, 22 errors in 35.20s` |

The failing and erroring tests are the same 37 on the branch and on the base. `diff fail_base.txt fail_new.txt` printed
`SAME_FAILURES_AS_BASE`. They are not caused by this branch:

| File | Failed | Errors |
|---|---|---|
| `test_chat_copilot_priyanka.py` | 3 | 19 |
| `test_chat_no_plan_factual.py` | 0 | 3 |
| `test_chat_advisor_mode.py` | 3 | 0 |
| `test_chat_insight_card.py` | 9 | 0 |

Before the TI-9 update, the branch had 2 more failures than the base: the two `test_ti9_*` tests in
`test_copilot_trade_idea.py`.
- **Cause:** by design, a stock decision's one card is now `visual_answer`, which carries the plan as a `trade_plan`
  block. It used to be a separate `trade_plan` card.
- **Fix:** both tests now assert the new design. The plan is built once, there is one card, the engine still receives
  `TRADE_PLAN`, and the turn is pinned to `stock_analyst`.

### Staging, in-process
`/api/chat/stream` was not called on staging: the branch is not deployed. Instead, each builder ran in-process inside the
running staging backend:
- Container: `nivesh-staging-app-backend`, with `PYTHONPATH=/app/backend`.
- Overlay: the branch's `services/copilot_visual/` and `services/copilot_trade_idea.py` were copied to
  `/tmp/ov_dtc/services`, and the script inserted that folder at the front of `services.__path__`.
- Script: `/tmp/claude-1002/-home-deploy-nivesh-ai/3d5d2da4-dd5c-4e4e-9753-e2b535562f89/scratchpad/dtc_capture.py`.

Stubs, and nothing else:
- **Sign-in:** the 5 loaded route/service modules whose `get_current_user` is `deps.get_current_user` return a real
  staging user who has a paper account. The user is printed only as a hash: `user a5530afb31`.
- **Writes:** `routes.strategy_plan.store_trade_plans` records and stores nothing (stock_decision).

Every data read was real. No container was restarted. `/tmp/ov_dtc` was removed afterwards
(`ls: cannot access '/tmp/ov_dtc'`).

Output excerpts, unedited (questions asked as the Trader persona, 30 Oct 2026 ~12:00 IST, data of the 29 Oct session):

```
== market_view  (0.7s)  q='What is the market view today?'  contract_problems=[]
  as_of 2026-10-29 | headline: Nifty 50 rose 1.05% to 22,936.75; 60% of stocks advanced; India VIX 15.12.
  source fresh   2026-10-29  NSE index closes (nidp.index_eod)
  source fresh   2026-10-29  NIDP market snapshot (breadth, FII/DII cash)
  source fresh   2026-10-29  NSE FII/DII cash (nidp.fii_dii_flows)
  source fresh   2026-10-29  Desk regime (desk-regime-v1)
  source fresh   2026-10-29  NSE F&O bhavcopy · NIFTY option chain
  source fresh   2026-10-29  NSE sector indices (desk sector returns)
  kpis: Nifty 50=22,936.75 (+1.05% on 29 Oct); Bank Nifty=54,909.65 (+1.18% on 29 Oct); India VIX=15.12 (−6.94% on the day); Breadth=1,995 up · 1,275 down (60% of 3,339 stocks advanced); FII cash=−₹943.60 Cr (net, 29 Oct); DII cash=+₹1,924.41 Cr (net, 29 Oct); Regime=Mixed (desk-regime-v1 · 29 Oct)
  candles NIFTY: 60 bars 2026-08-04..2026-10-29 last close 22936.75 ema20 22823.99 levels [('wall_call', 23500.0), ('wall_put', 22000.0), ('max_pain', 22900.0)] band {'low': 22657.9, 'high': 23215.6, 'label': 'Expected move to 3 Nov 2026 (ATM straddle ±278.85)'}
  heatmap sectors: Power 3.21, Realty 2.75, FMCG 2.34, PSU Banks 2.2, Private Banks 1.24, Telecom 1.19, Banks 1.18, Consumer Durables 1.18, Financial Services 1.17, Media 1.1

== smart_money  (0.2s)  q='Where is smart money moving?'  contract_problems=[]
  as_of 2026-10-29 | headline: FIIs sold a net ₹943.60 Cr and DIIs bought a net ₹1,924.41 Cr in cash on 29 Oct; 74 F&O stocks show long buildup and 103 short covering.
  source fresh   2026-10-29  NSE FII/DII cash (nidp.fii_dii_flows)
  source fresh   2026-10-29  NSE F&O bhavcopy · futures build-up
  source fresh   2026-10-29  NSE sector indices (desk sector returns)
  kpis: FII cash · 29 Oct=−₹943.60 Cr; FII · 10 sessions=−₹4,110.69 Cr (sum of the daily nets); DII cash · 29 Oct=+₹1,924.41 Cr; DII · 10 sessions=+₹14,527.60 Cr (sum of the daily nets); Long buildup=74 (of 218 F&O stocks); Short covering=103 (of 218 F&O stocks); Short buildup=27 (of 218 F&O stocks); Long unwinding=14 (of 218 F&O stocks)
  bars fii: 15 Oct -5285.37, 16 Oct 1165.92, 19 Oct -1148.64, 21 Oct 1022.32, 22 Oct -3458.7, 23 Oct 887.65, 26 Oct -1462.49, 27 Oct 4240.39, 28 Oct 871.83, 29 Oct -943.6
  quadrant: 40 points, first [{'label': 'COROMANDEL', 'x': -0.3, 'y': 394.0, 'quadrant': 'Short buildup'}, {'label': 'DATAPATTNS', 'x': 0.4, 'y': 106.84, 'quadrant': 'Long buildup'}, ...]
  list: ['BANKNIFTY: short covering', 'FINNIFTY: short covering', 'MIDCPNIFTY: long buildup', 'NIFTY: short covering']

== top_opportunities  (0.0s)  q="Which are today's top 5 opportunities?"  contract_problems=[]
  as_of 2026-10-29 | headline: 4 of the scanner's top 5 on 29 Oct have a setup with levels; 1 wait for confirmation.
  source fresh   2026-10-29  AI scanner watchlist (Top 10, stored nightly)
     {'rank': 1, 'symbol': 'PNB', 'setup': 'Wait for breakout confirmation', 'status': 'Setup ready', 'entry': 125.35, 'stop': 120.67, 'target': 134.71, 'rr': 2.0, 'score': 75.6} plan_id tp_3fd429c9f6c6e921
     {'rank': 2, 'symbol': 'LAURUSLABS', 'setup': 'Breakout', 'status': 'Setup ready', 'entry': 2244.0, 'stop': 2151.16, 'target': 2429.68, 'rr': 2.0, 'score': 75.1} plan_id tp_3df58bc61b6bad4f
     ... IIFLCAPS 'status': 'Wait' ...
  trade_plan: tp_3fd429c9f6c6e921
top_opportunities plan ids stored in trade_plans : 5 of 5

== breakouts  (2.6s)  q='Which breakouts are confirmed?'  contract_problems=[]
  as_of 2026-10-29 | headline: 1 stock closed just above the breakout level on at least 1.5× the usual volume on 29 Oct.
  source fresh   2026-10-29  Positional scanner watchlist (breakout_confirmed)
  source fresh   2026-10-29  NSE prices, split/bonus adjusted (prices_eod_adjusted)
     {'symbol': 'LAURUSLABS', 'level': 2244.0, 'close': 2244.0, 'above': 0.0, 'volx': 1.66, 'stop': 2151.16}
  candles LAURUSLABS: 60 bars 2026-08-04..2026-10-29 last close 2244.0 ema20 2060.45 levels [('resistance', 2244.0), ('stop', 2151.16)] band None

== unusual_volume  (1.4s)  q='Which stocks have unusual volume?'  contract_problems=[]
  as_of 2026-10-29 | headline: 65 eligible stocks traded with unusually high volume on 29 Oct; VGUARD led at 82.5× its 20-day average.
  source fresh   2026-10-29  Stock features + NSE bhavcopy (scan snapshot)
  source fresh   2026-10-29  NSE delivery (nidp.delivery_data)
     {'symbol': 'VGUARD', 'close': 284.85, 'chg': 7.9, 'rvol': 82.47, 'deliv': '12.04%'}
     {'symbol': 'EQUITASBNK', 'close': 57.17, 'chg': -12.22, 'rvol': 49.28, 'deliv': '41.45%'}

== stock_decision  (3.8s)  q='Is PNB a buy now?'  contract_problems=[]
  as_of 2026-10-29 | headline: PNB: the desk's rules find a setup — Covered call (shares + short call), net premium ₹23,760.00, stop ₹120.67, first target ₹130.36.
  source fresh   2026-10-29  Desk trade plan (StrategyPlan + TradePlan, end of day)
  source fresh   2026-10-29  NSE prices, split/bonus adjusted (prices_eod_adjusted)
  missing: ['Account sizing: the risk service would refuse this plan on your account (not_sizable)']
  decision: setup_ready | Covered call (shares + short call): net premium ₹23,760.00, stop ₹120.67 (underlying). | plan_id tp_16af164648ee9112
  candles PNB: 60 bars 2026-08-04..2026-10-29 last close 123.9 ema20 118.89 levels [('stop', 120.67), ('target', 127.02), ('target', 130.36), ('target', 133.59)] band None
stock_decision TradePlans NOT stored (store stubbed): 4

== expected_move  (0.2s)  q='What is the expected move in Nifty?'  contract_problems=[]
  as_of 2026-10-29 | headline: The Nifty options price a move of about ±278.85 points (±1.22%) to the 3 Nov 2026 expiry; PCR 1.44, max pain 22,900.00.
  kpis: Expected move=±278.85 pts (±1.22% · ATM straddle); ATM IV=12.99% (Black-76 on the ATM strike, end of day); PCR=1.44 (put OI ÷ call OI, whole expiry); Max pain=22,900.00; Expiry=3 Nov 2026 (5 days from 29 Oct); Spot=22,936.75 (close 29 Oct)
```

The first capture run found a real defect, fixed in commit "fix(copilot): visual stock decision reads option plans…":
- **Defect:** PNB's preferred plan is an options TradePlan. Its entry has no price (`net_premium_rs` instead), so the
  headline read "entry None". A ready setup also listed other candidates' "would change if" lines as unmet conditions.
- **Fix:** test B-10 (options) was added, and the capture above is the re-run.

The real capture is `frontend-v5/e2e/fixtures/contract-visual-answer.json`: `{about, payloads}` with all 7 intents.
Test C-2 validates it.

## Data Correctness (staging)
- **Market figures:** checked against agent C's direct warehouse queries of the same morning
  (`.../scratchpad/q15/C_data_freshness.md`, `nidp.index_eod` and `nidp.fii_dii_flows`, 04:21 IST). They are identical:

  | Figure | Captured | C's query |
  |---|---|---|
  | Nifty 50 | 22,936.75 (+1.05%) | 22,936.75 (+1.05%) |
  | Nifty Bank | 54,909.65 (+1.18%) | 54,909.65 (+1.18%) |
  | India VIX | 15.12 (−6.94%) | 15.12 (−6.94%) |
  | FII cash | −943.60 Cr | −943.60 Cr |
  | DII cash | +1,924.41 Cr | +1,924.41 Cr |

- **Freshness:** every source in every payload is `fresh` (29 Oct = T-1; `market_freshness.window` floor 29 Oct).
  - `delivery_data` had already loaded 29 Oct by the capture time (~12:00 IST). Before ~10:30 IST it is the 28 Oct day
    and is shown as `stale` with its date; test B-9 covers that path.
- **Stored plans:** the top_opportunities `plan_id`s exist in Mongo `trade_plans`: `5 of 5`, a read-only `count_documents`.
- **Not stored:** the stock_decision `plan_id` (`tp_16af164648ee9112`) is NOT stored, because the store was stubbed. The
  fixture's `about` says so.
- **Data gaps seen:**
  - `nidp.security_reference_daily does not exist` on the staging warehouse. It was logged twice by
    `research_chart._reference_row` during the PNB plan build, so the plan's tradability evidence lacks that reference.
  - The risk service answered `not_sizable` for the PNB covered call on the chosen account. The payload says so and shows
    no size.
- **Not used:** the analytics.* layer (frozen at 12 Oct).

## Not verified (UNVERIFIED)
- **`POST /api/chat/stream` on staging:** the branch is not deployed. A deploy plus a session cookie is needed. The route
  wiring is covered by tests CH-1 … CH-5 on the real route with a fake engine.
- **The specialist LLM's prose with the VISUAL_ANSWER block:** tests use a fake engine and there is no LLM call. Not
  checked:
  - whether market_analyst explains the list intents well;
  - whether stock_analyst quotes only the figures.
- **The real capture against the frontend zod schema itself:** no Node toolchain or `node_modules` with zod is on this
  host. `payload.validate` mirrors the schema's required parts. The frontend spec should load
  `contract-visual-answer.json`.
- **Live mode:** every Release-1 answer is `mode: "eod"`. No Kite live overlay is used.

## Inputs required from user
- none

## Verdict: PASS
Every case in scope ran green:
- the resolver, the builders, the contract and facts tests, and the chat pre-step tests;
- the regression suites, with the same failures as the untouched base;
- all 7 builders on real staging data, with contract problems `[]`.

The deployed endpoint and the LLM prose are outside this run and are listed above.
