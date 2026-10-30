# Functionality Verification Report — Daily Trader Copilot visual answer (backend, Release 1)

- **Branch:** feat/dtc-visual-backend
- **Date:** 2026-10-30
- **Author:** Claude (FULL_STACK_DEVELOPER + QA_ENGINEER)
- **Environment:** staging (in-process inside `nivesh-staging-app-backend`, real NIDP warehouse / Mongo / app Postgres; read only)
- **Changed areas:** backend routes/services: yes · frontend src: no

## Summary
_(filled after the runs)_

## Test Cases
> Authored up front (after reading the contract and the frontend schema, before implementation).

| ID | Area | Scenario | Type | Expected | Result |
|----|------|----------|------|----------|--------|
| R-1 | resolver | "What is the market view today?", "Is the market trending?", "Nifty and Bank Nifty view" | unit | market_view | |
| R-2 | resolver | "Where is smart money moving?", "FII DII flows this week", "Which F&O stocks show long build-up today?" | unit | smart_money | |
| R-3 | resolver | "Today's top 5 opportunities", "top 10 trade ideas today" | unit | top_opportunities, N parsed (5 / 10) | |
| R-4 | resolver | "Which breakouts are confirmed?", "stocks breaking out today" | unit | breakouts | |
| R-5 | resolver | "Which stocks have unusual volume?", "volume spike stocks" | unit | unusual_volume | |
| R-6 | resolver | "Is RELIANCE a buy now?", "entry, target and stop-loss for INFY", "trade plan for tvsmotor"? (lower-case non-curated) | unit | stock_decision with the symbol (curated lower-case resolves; a non-curated lower-case name does not invent one) | |
| R-7 | resolver | "Is this stock a buy now?" with last_symbol TVSMOTOR; without last_symbol | unit | stock_decision TVSMOTOR; None | |
| R-8 | resolver | "What is the expected move in Nifty?", "Bank Nifty expected move", "NIFTY PCR and max pain" | unit | expected_move NIFTY / BANKNIFTY | |
| R-9 | resolver (neg) | "What are my open trades doing?", "Which F&O setups are attractive?", "Should I book profits or hold TCS?", "Show the FIXCO chart", "What is the PCR?" with stock words | unit | None (R2 / not ours); PCR, F&O, P&L, GIFT, IV, OI, ATM, VIX, NIFTY never a stock | |
| R-10 | resolver | last_symbol from the thread: a saved visual_answer / trade_plan widget, else the newest user message naming a stock | unit | the newest symbol | |
| B-1 | market_view | all sources fresh (stubbed) | unit | kpis (Nifty, Bank Nifty, VIX, breadth, FII, DII), candles NIFTY 60 bars + EMA20/50 + walls + max pain + band, heatmap; data_quality fresh; payload validates | |
| B-2 | market_view | chain read fails, sector route stale | failure | no band / walls; notice + data_quality.missing for the chain; stale sector source → stale=true + notice; no invented number | |
| B-3 | smart_money | fresh | unit | bars FII + DII (10 sessions, oldest first), heatmap 1-week, quadrant, ranked long buildup / short covering | |
| B-4 | smart_money | FII/DII missing, buildup stale (404 from the route) | failure | notices + missing; other blocks still built | |
| B-5 | top_opportunities | stored day fresh | unit | ranked top N with plan_id per row, trade_plan block for the first plan_id | |
| B-6 | top_opportunities | no stored day / stale day | edge | notice; stale day flagged; no ranked invented | |
| B-7 | breakouts | bucket with rows | unit | ranked + candles of the first with breakout + stop levels + bars volume × | |
| B-8 | breakouts | empty bucket | edge | info notice "no stock met the rule on <date>", no fake rows | |
| B-9 | unusual_volume | snapshot rows | unit | only eligible vol_z20 ≥ 2, ranked by vol_z20; bars rvol; delivery column dated; stale delivery flagged | |
| B-10 | stock_decision | plan status plan / wait / no_trade / insufficient_data | unit | decision setup_ready / wait / avoid / no_setup with the fixed labels; trade_plan block only with a plan_id; kpis from the risk service sizing | |
| B-11 | stock_decision | plan could not be built | failure | no decision, warn notice, missing entry | |
| B-12 | expected_move | chain fresh | unit | kpis ATM IV, ± move, PCR, max pain, expiry; candles with band and walls | |
| B-13 | expected_move | chain stale (route 404) | failure | notice + missing, no kpis invented | |
| C-1 | contract | every built payload passes `validate()` (mirror of the frontend zod schema) | unit | [] problems | |
| C-2 | contract | the REAL capture `frontend-v5/e2e/fixtures/contract-visual-answer.json` validates for all 7 intents | unit | [] problems | |
| F-1 | facts | facts block carries the headline, KPI values, dates and missing list; stock_decision's first upper-case token is the symbol (stock node resolves it) | unit | as stated | |
| CH-1 | chat | a market question: one `visual_answer` widget frame before tokens, saved on the message, facts passed as `visual_answer` data block, pin market_analyst, no trade-idea build | integration | as stated | |
| CH-2 | chat | stock_decision: trade idea built ONCE, visual widget only (no separate trade_plan card), TRADE_PLAN + visual facts both passed, pin stock_analyst | integration | as stated | |
| CH-3 | chat | a question with no intent | integration | exactly today's path (existing tests stay green) | |
| CH-4 | chat | builder raises | failure | today's path, no widget from the visual step | |
| CH-5 | chat | a position question / a client pin | edge | visual step skipped | |
| S-1 | staging | each of the 7 builders in-process on staging with real data | api (in-process) | payload per intent, real numbers with as_of, validates | |
| REG | regression | tests/test_copilot_trade_idea.py, tests/test_chat*.py, tests/test_broker_contract_chart.py | unit | all pass | |

## API / Endpoint Tests (staging)
_(filled after the runs)_

## Data Correctness (staging)
_(filled after the runs)_

## Inputs required from user
- none

## Verdict: BLOCKED
