## Feature: AI Trader — Phases 2–5 (Strategy Architect, Risk Governor, Paper execution, Assisted trading)
**Status:** BUILDING · **Author:** Claude (PRODUCT) · **Date:** 2026-10-21
**Builds on:** [AI_TRADER_PHASE1.prd.md](AI_TRADER_PHASE1.prd.md), [AI_TRADER_BUSINESS_REQUIREMENT.md](../AI_TRADER_BUSINESS_REQUIREMENT.md) §10, [STRATEGY_BUILDER_CONFIG_SPEC.md](../STRATEGY_BUILDER_CONFIG_SPEC.md)

> **Hard boundary (owner decision 2026-10-21):** the ladder stops at *assisted*. No code path in this feature sends an order to a broker; brokers stay read-only. "Autonomous live" does not exist as a mode, a flag or a branch.

> **ASSUMPTIONS taken on the "complete all phases" instruction, all reversible and held as named constants so they can be changed in one place. The product owner has not confirmed them.**
> B1. Strategies are JSON DSL documents (`services/strategy_engine/dsl.py`). The AI picks and tunes one of the repo's six templates from the market regime; it does not free-write rules or code. Free-form rule invention and an LLM narrative layer are out of scope.
> B2. `NiveshConfig` is implemented as the spec's reference class. Spec open questions answered as: built-ins other than `initial_capital` are platform/UI-set only (Q1); AI strategies default `commission_pct=0.05` (per side, %) with `pyramiding=0` and `short_margin_pct=100` (Q2); pyramiding 0 = one entry per direction (Q3); the DSL backtester has its own cost model, so `commission_pct` is applied through it as a per-side cost and the Indian charge stack is used only in Phase 1's validation (Q4); `cross_over` is not used by the DSL path (Q5).
> B3. Promotion gates (all in `strategy.GATES`): draft→backtested needs a stored backtest run; backtested→paper needs ≥100 trades, profit factor ≥1.3, max drawdown no worse than −25%, positive return, and ≥3 of 4 walk-forward folds positive; paper→assisted needs ≥20 closed paper trades, net expectancy >0, profit factor ≥1.2, and paper win rate within 15 points of the backtest's. No gate can be skipped by the caller.
> B4. Backtest windows must not overlap the sealed 2023-01-01..2024-07-31 block. The block is opened once per strategy, by an explicit `holdout` run, which is recorded and can never be repeated.
> B5. Risk limits (all in `risk_governor.DEFAULT_LIMITS`): risk per trade ≤1% of capital; position ≤10%; ≤10 open positions; sector ≤30%; net exposure ≤80%; daily loss ≥3% halts the day; drawdown ≥15% halts until a human resets; reward:risk ≥1.5; stop required and ≤15% away; India VIX ≥25 halves size, ≥35 defers; position ≤5% of average daily traded value; BEAR market regime halves size.
> B6. "Assisted" = the AI prepares a ticket, the user confirms or rejects it. Confirming records a *paper-shadow* trade (so the outcome is tracked) and returns copy-ready text for the user to place at their own broker. Nothing is sent.

## 1. Problem
Phase 1 gives structured, point-in-time evidence. The requirement asks the AI to turn that into strategies, test them honestly, trade them on paper, and prepare orders for a person to approve, with an independent risk layer the AI cannot talk its way past. The repo's own data shows no validated edge, so the work must make it hard to promote a strategy and easy to see why one was held back.

## 2. Goals & non-goals
- **Goals:** P2 propose + validate + backtest + gate strategies (DSL, `NiveshConfig`); P3 a deterministic Risk Governor with veto; P4 paper execution through the existing desk paper-trade engine with full provenance; P5 assisted tickets with explicit user confirmation, plus an outcome journal that feeds calibration.
- **Non-goals:** any broker write; autonomous live; Python-sandbox strategies; options/F&O strategies; LLM-written rules; UI screens (API only; UI is a separate DESIGN-owned piece).

## 3. User stories
- As a trader, I want the AI to propose a strategy that fits today's market and show me why a strategy was or wasn't allowed to advance.
- As a trader, I want a risk layer that can refuse, shrink or defer any order and always says why.
- As a trader, I want to approve each assisted order myself, with nothing sent to a broker.
- As a researcher, I want every paper/assisted trade traced back to strategy version, evidence and risk decision, and outcomes fed back into calibration.

## 4. Requirements
**Phase 2 — Strategy Architect**
- F2.1 `NiveshConfig` per spec: freeze lifecycle, `CODE_WRITABLE={"initial_capital"}`, `ConfigFrozenError`, `ConfigValidationError`, `to_dict()` with `schema_version`.
- F2.2 `propose_strategy(market_evidence, config)` selects a template by regime (BULL→momentum_breakout, SIDEWAYS→mean_reversion, BEAR→accumulation) and records the choice and the evidence it used; output must pass `validate_strategy`.
- F2.3 Strategy record: id, version hash of spec+config, stage, created_by `"ai"`, provenance, stage history. Stages: `draft → backtested → paper → assisted`, plus `retired`. No other stage exists.
- F2.4 Backtest through an injected runner (production: `strategy_engine.backtest.run_backtest`); window refused if it overlaps the sealed block (except the one-shot holdout); resolved config stored with the run; metrics stored.
- F2.5 `evaluate_gates(stage, evidence)` returns pass/fail per criterion with the value and the threshold; `promote` moves exactly one stage and only when every criterion passes; `demote/retire` always allowed.
- F2.6 Walk-forward: the window is split into 4 equal date folds; each fold is run and reported.

**Phase 3 — Risk Governor** (`risk_governor.py`, pure, imports nothing from strategy/evidence/LLM code)
- F3.1 `evaluate(intent, portfolio, market, limits)` → `Decision{action, approved_qty, reasons[], limits_version}` with action ∈ approve|reduce|hedge|defer|reject|halt.
- F3.2 Precedence: halt > reject > defer > reduce > hedge > approve. Every reason has a code, the value, and the limit.
- F3.3 Limits come from configuration set by a person; no input from a strategy or the AI can raise them.
- F3.4 A reduction that leaves under 1 share becomes a reject.

**Phase 4 — Paper execution**
- F4.1 Signals come from the strategy's DSL via the market-data provider's `screen`; each candidate becomes an intent (entry = last close, stop from `exit.stoploss_pct`, target from `target_rr`, sized by risk per trade).
- F4.2 Each intent goes through the governor; approved/reduced intents open a paper trade with `desk_trading.new_trade` (source kind `ai_trader`, strategy version, rationale); every intent, approved or not, is stored as a ticket with the decision.
- F4.3 Only strategies at stage `paper` or `assisted` may produce signals; a `draft`/`backtested` strategy gets 409.
- F4.4 Idempotent: the same strategy, symbol and signal date never opens a second trade.

**Phase 5 — Assisted trading and learning**
- F5.1 A strategy at `assisted` produces tickets in status `awaiting_confirmation` (no paper trade yet) that expire at the end of the next session; expired tickets cannot be confirmed.
- F5.2 `confirm` re-runs the governor with the current portfolio before acting; if the decision is now worse than approve/reduce the ticket is refused. Confirmed → paper-shadow trade + copy-ready ticket text; `reject` records the reason.
- F5.3 No module under `services/ai_trader` imports a broker module; there is no live mode value (`mode=live` → 422).
- F5.4 Outcome journal: closed trades linked to tickets produce (stated confidence, hit) pairs → `calibration_report`; per-strategy paper stats feed the paper→assisted gate.

## 5. Acceptance criteria (the QA contract)
- [ ] NiveshConfig: defaults applied; `initial_capital` writable in `strategy_info` only; other built-ins raise `ConfigFrozenError`; writes after freeze raise; shadowing a built-in or a `_x` key is rejected; non-serialisable custom value fails validation; out-of-range values fail with the field named.
- [ ] A proposed strategy always validates against the DSL; the regime→template mapping holds for BULL/SIDEWAYS/BEAR; with regime evidence UNAVAILABLE, no strategy is proposed (409 `regime_unavailable`), never a default guess.
- [ ] A backtest window overlapping 2023-01-01..2024-07-31 is refused 422 `sealed_window`; a second holdout run is refused 409 `holdout_used`.
- [ ] Promotion: each gate criterion has a failing case and a passing case; a failing gate returns 409 with the unmet criteria; stages cannot be skipped; `live` as a target stage is 422.
- [ ] Governor: one test per reason code; precedence respected when several apply; `reduce` quantity satisfies every limit at once; reject when reduced qty <1; same inputs give the same decision; the module imports no strategy/evidence/LLM module (AST check).
- [ ] Paper: a `backtested` strategy cannot signal (409); a `paper` strategy's approved intent opens exactly one paper trade whose stop/target/qty match the decision; a rejected intent opens none but is stored with reasons; repeating the call opens no duplicate.
- [ ] Assisted: ticket awaits confirmation; confirm on an expired ticket → 409; confirm after the portfolio changed to breach a limit → refused with the new reasons; reject stores the reason; confirm returns text with symbol, qty, entry, stop, target and the line "Place this order yourself at your broker; Nivesh sends nothing."
- [ ] No-broker guarantee: AST scan finds no import of `services.brokers`, `broker_native`, `broker_connect` or any order-placing client in `services/ai_trader` or `routes/ai_trader.py`.
- [ ] Ownership: strategy/ticket of another user → 404. Unauthenticated → 401. Bad body → 422.
- [ ] Outcome journal: closed winning/losing shadow trades produce the expected (confidence, hit) pairs and a calibration report.

## 6. UX / design notes
API only. A screen for strategies, tickets and the confirm step is a separate DESIGN-owned task; the confirm step must show the governor's reasons and the "nothing is sent" line.

## 7. Technical notes
- New: `services/ai_trader/{config,strategy,risk_governor,execution}.py`; extend `routes/ai_trader.py`; Mongo collections `ai_trader_strategies`, `ai_trader_tickets` (indexes created lazily). Paper trades reuse `desk_paper_trades`.
- Backtest and screen need the NIDP Postgres pool (`pg_client.get_pool`) and run only where it exists; unit tests inject runners. This is a known limit: real backtests are UNVERIFIED until run on staging with data.
- No new dependency.

## 8. Dependencies & sequencing
P2 and P3 are independent and both feed P4; P5 needs P3 and P4. Order built: P2 → P3 → P4 → P5.

## 9. Risks
- **No validated edge exists.** Gates are strict by design; expect most proposals to stay at `backtested`. The system must make that visible, not hide it.
- Thin or biased backtests (survivorship, adjusted-price basis): metrics carry the provider's `price_basis`/`universe_basis`, and a `present_day_fallback` universe fails the gate.
- Gate numbers and limits are assumptions (B3, B5): owner must review before real use.
- Staging lacks bars/Postgres data for some paths: those stay UNVERIFIED until run there.

## 10. Success metric & rollout
- **Measure:** 100% of paper/assisted trades carry strategy version, evidence and decision; calibration error reported per strategy; zero broker calls (AST test).
- **Rollout:** behind existing auth; strategy stages start at `draft`; rollback = remove routes.

## 10c. What the adversarial review changed (2026-10-21)

A six-dimension adversarial review (45 agents; 39 findings, 31 confirmed by a second agent whose job was to refute
them, 8 refuted) found 5 critical defects in this branch, including two ways to read the sealed block more than once
and a path that stored a reduced order at full size. All are being fixed with a test written first. The review's
pattern was not wrong arithmetic but false confidence: safeguards that reported themselves as working while measuring
nothing. Full record in `test_reports/OVERRIDE_ai_trader_phases_2_5.md`.

**The finding the owner must decide on, because it blocks the paper stage entirely.** The shared backtester
`strategy_engine/backtest.py` has no position size anywhere: `pnl_abs` is `(exit - entry) - brokerage` for ONE share,
and that per-share rupee figure is added to an equity series that starts at `starting_capital`. So
`total_return_pct` and `max_drawdown_pct` are one-share rupees expressed as a percentage of a ten lakh account. A 6
per cent stop on a 1,400 rupee share moves the account by about 0.01 per cent, so the -25 per cent drawdown floor in
B3 cannot bind, and the return gate measures something close to nothing. This affects the existing Strategy Builder
too, not only the AI trader.

The gates now fail closed: a run must declare `metrics["sizing_basis"] == "portfolio"` before either row can pass,
and nothing emits that key today, so **on a real engine run no strategy can currently reach `paper`.** That is the
honest state, not a bug introduced here. The three ways forward, for the owner to choose:
1. Teach `strategy_engine.backtest` to size positions and report quantity-aware metrics. Correct, and it fixes the
   Strategy Builder's numbers too, but it changes a shared engine with other callers.
2. Accept an explicitly labelled unsized gate, knowing the drawdown and return criteria are then decorative.
3. Leave the gate closed and promote nothing to paper until option 1 is done.
I recommend option 1, and did not choose it on the owner's behalf. Also unfixed and related, in the same shared
engine: `win_rate` is computed from gross `pnl_pct` while `profit_factor` is computed from net `pnl_abs`, so the two
sit on different bases, and `_record_equity` is a no-op, so drawdown ignores open positions entirely.

## 11. Open questions
1. Confirm B1–B6 (owner: product owner), especially gate thresholds and risk limits.
2. Which universe and date range should the first AI backtests use (owner: product owner + domain analyst).
3. When is the Strategy Builder UI scheduled (owner: DESIGN)?
4. Position sizing in the shared backtester: option 1, 2 or 3 in section 10c (owner: product owner + domain analyst).
5. Should an unknown sector on a held position count against the sector allowance, as the governor now does, refusing
   new orders on a book above 30 per cent of capital with no sectors recorded (owner: product owner)?
6. Should a proposal's requested symbols drive the backtest universe? Today they configure NiveshConfig only and the
   backtest runs the template's index, because the DSL custom universe takes a stored universe id, not a symbol list.
