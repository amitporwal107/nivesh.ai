## Feature: AI Trader — Phase 1 (Evidence foundation)
**Status:** BUILT on branch, NOT deployed or verified on staging · **Author:** Claude (PRODUCT) · **Date:** 2026-10-21
**Source:** [AI_TRADER_BUSINESS_REQUIREMENT.md](../AI_TRADER_BUSINESS_REQUIREMENT.md), [STRATEGY_BUILDER_CONFIG_SPEC.md](../STRATEGY_BUILDER_CONFIG_SPEC.md)

> ASSUMPTIONS taken on "war footing" instruction, reversible, confirm or correct:
> A1. AI strategy target = existing JSON DSL (`backend/services/strategy_engine/dsl.py`), not a Python sandbox.
> A2. PRD scope = Phase 1 in detail; Phases 2–5 are outlined in §8 only.
> A3. Execution ceiling = backtest → paper → assisted. Brokers stay read-only. No autonomous live orders.
> A4. Code lands in the desk worktree `/home/deploy/nivesh-trading-desk` on a NEW branch off `feat/trading-desk-backend`; the worktree's 7 uncommitted files belong to another session and are not touched.

## 1. Problem
The platform has strong parts (PIT charting features, a strategy DSL, a cost model, paper tables) but no shared evidence record, so market, fundamental, technical and F&O views cannot be combined, challenged or calibrated. The repo's own data shows no validated edge yet. Before any AI strategy is created or executed, every claim the AI makes must be structured, point-in-time, and measured against outcomes.

## 2. Goals & non-goals
- **Goals:** (1) one `Evidence` record used by all skills; (2) one PIT market-context service (regime, breadth, VIX, sector rotation); (3) multi-timeframe conflict evaluator; (4) pattern validation v1 with calibration (reliability of stated confidence); (5) all outputs respect the sealed holdout 2023-01-01..2024-07-31.
- **Non-goals:** strategy generation, execution, risk governor, F&O skill, LLM narrative (Phases 2–5); any broker write; any change to existing charting thresholds (frozen).

## 3. User stories
- As a trader, I want each AI view to list observation, confidence, contradictions and invalidation so I can judge it.
- As a researcher, I want to know if "70% confidence" actually wins ~70% out of sample.
- As a reviewer, I want proof no feature used future or sealed data.

## 4. Requirements
**Functional**
- F1 `Evidence` dataclass + JSON schema: `skill, symbol, as_of, horizon, observation, interpretation, confidence(0–1), contradictions[], conditions[] (invalidation), sources[{name,timestamp}], decision_impact(supports|opposes|neutral|veto_candidate), status(OK|UNAVAILABLE), reason_code`.
- F2 `market_context(as_of)` returns regime (reuse `research/charting/regime.py`: `market_regime`, `trend_classification`, `india_vix_at`, `breadth_at`) as Evidence; no re-implementation.
- F3 `sector_rotation(as_of)` table: relative strength vs NIFTY 500 for sector indices (`research/index_history/data`), rank + 20/60-day change, as Evidence.
- F4 `timeframe_conflicts(symbol, as_of)`: daily/weekly/monthly trend states from existing bars; emits a contradiction Evidence when higher-timeframe opposes lower.
- F5 `pattern_validation(pattern, universe)`: per-pattern hit rate, sample size, expectancy net of costs (`research/costs/engine.py`), by regime; confidence is shrunk toward the base rate when n < 30.
- F6 `calibration_report`: reliability bins (0.5–1.0 in 0.1 steps), Brier score, per skill.
- F7 Any window touching the sealed block returns `UNAVAILABLE / SEALED_GAP` (as `regime.py` does); never an interpolated number.
- F8 REST under `/api/ai-trader`, signed-in users only: `GET /evidence?symbol=&as_of=`; `POST /calibration` and `POST /pattern-validation` (POST, not GET as first drafted, because Phase 1 stores no outcomes: the caller supplies the predictions or events). Nothing writes to a database or a broker.

**Non-functional:** deterministic for a given `as_of`; evidence request p95 < 2 s on staging for one symbol; no LLM in this phase; no secrets in logs.

## 5. Acceptance criteria (QA contract)
- [ ] Given a symbol and a date, `GET evidence` returns ≥1 Evidence per implemented skill with every F1 field present and `confidence` in [0,1].
- [ ] Given `as_of` in 2023-06-01 (sealed), market/sector/timeframe evidence is `UNAVAILABLE` with `reason_code=SEALED_GAP`, never a value.
- [ ] PIT: truncating all input bars after `as_of` leaves every output unchanged (property test over ≥50 random dates).
- [ ] Pattern with n=5 reports shrunk confidence and flag `LOW_SAMPLE`; n≥30 does not.
- [ ] Calibration: synthetic predictions with known 0.8 hit rate yield bin 0.8 observed ≈0.8 ±0.05 and a Brier score matching the hand calculation.
- [ ] Unknown symbol → 404 with error body; missing `as_of` → 422; unauthenticated → 401.
- [ ] Higher-timeframe bearish + daily bullish → one `opposes` contradiction naming both timeframes.
- [ ] Expectancy is reported net of costs; a zero-cost run differs from the costed run by the cost model amount.
- [ ] Data test: sector table row count equals the sector indices present in `index_history`, and latest date is within the feed's freshness band.

## 6. UX / design notes
Backend-only in Phase 1. A read-only JSON view; UI deferred to Phase 2 with the DESIGN role.

## 7. Technical notes
- New package `backend/services/ai_trader/` (evidence.py, context.py, sector.py, timeframes.py, validation.py, calibration.py) plus route `backend/routes/ai_trader.py`. It wraps `research/charting`; it does not copy it.
- No schema change in Phase 1 (calibration computed on demand); a persistence migration is proposed for Phase 2. Needs ADR if added.
- No new dependency.

## 8. Dependencies & sequencing (phases)
P1 this PRD → P2 Strategy Architect (DSL generation + NiveshConfig mapping, backtest only) → P3 independent Risk Governor with veto → P4 paper execution on `tpd_paper_*` → P5 assisted orders with per-order user confirmation. A strategy cannot advance a stage without clearing out-of-sample criteria (to be defined in the P2 PRD); the sealed block is for final validation only.

## 9. Risks
- Sealed-window gaps leave thin samples → report `UNAVAILABLE`, never fill.
- Overfit pattern stats → shrinkage, walk-forward, report n always.
- Worktree collision with another session → separate branch; confirm before first commit.
- Spec ambiguities in Strategy Builder (5 open questions) block P2, not P1.

## 10. Success metric & rollout
- **Measure:** calibration error (mean |observed − stated| over bins) ≤ 0.10 on held-out data; 100% PIT property tests pass.
- **Rollout:** read-only endpoints behind the existing desk auth; no flag needed; rollback = remove route.

## 10b. Built (2026-10-21), branch `feat/ai-trader-phase1` in `/home/deploy/nivesh-ai-trader`
Package `backend/services/ai_trader/` (evidence, context, sector, timeframes, validation, calibration), route `backend/routes/ai_trader.py`, 2 lines in `server.py`, tests `backend/tests/test_ai_trader.py`. Decisions made while building: uncalibrated evidence carries confidence 0.5 with `calibrated=false` (no invented probabilities); the trailing weekly/monthly bar is dropped as unfinished; if `as_of` is not a session of the symbol (sealed block, holiday) every timeframe is withheld; pattern trades enter at the next open and exit at the close `horizon` sessions later, costed on the current zerodha-equity-v1 delivery card (stated in each result's `cost_basis`). Pattern *detection* is not part of Phase 1: validation takes events from the caller.

## 11. Open questions
1. Confirm A1–A4 (owner: product owner).
2. Out-of-sample promotion criteria for P2 (owner: product owner + domain analyst).
3. Strategy Builder open questions (defaults, pyramiding-0, Indian charges, cross_over order, code-settable fields).
