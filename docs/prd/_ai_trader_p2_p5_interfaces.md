# AI Trader Phases 2–5 — module interface contract (frozen 2026-10-21)

Written so parallel work cannot collide. Do not change a signature here without saying so in your final report.
Everything lives under `backend/services/ai_trader/` (package exists; Phase 1 modules: evidence, context, sector,
timeframes, validation, calibration, _research). Route file: `backend/routes/ai_trader.py` (exists, prefix
`/api/ai-trader`, already registered in server.py).

## Already built this phase (DO NOT EDIT)
`config.py` — NiveshConfig, ConfigFrozenError, ConfigValidationError, BUILTINS, CODE_WRITABLE={"initial_capital"},
AI_DEFAULTS, SCHEMA_VERSION, `resolve(symbols, ui=None, strategy_info=None) -> NiveshConfig`.
`risk_governor.py` — `Limits`, `DEFAULT_LIMITS`, `Intent(symbol, quantity, entry_price, stop_price, target_price,
sector=None, avg_daily_value=None, event_blackout=False)`, `Position(symbol, quantity, price, sector=None)`,
`Portfolio(capital, positions=[], realized_pnl_today=0.0, drawdown_pct=None, kill_switch=False, halted=False)`,
`Market(vix=None, regime=None)`, `Reason(code, text, severity, value, limit)`,
`Decision(action, requested_qty, approved_qty, reasons, limits_version)` with `.to_dict()`,
`evaluate(intent, portfolio, market=Market(), limits=DEFAULT_LIMITS) -> Decision`.
Actions: approve|reduce|hedge|defer|reject|halt. Severities: halt|reject|defer|reduce|hedge|info.

## Phase 1 facts you may rely on
- `evidence.Evidence` frozen dataclass: skill, symbol, as_of, horizon, observation, interpretation, confidence,
  decision_impact, status ("OK"|"UNAVAILABLE"), reason_code, calibrated, contradictions, conditions, sources, data;
  `.to_dict()`; `evidence.unavailable(skill, symbol, as_of, horizon, what, reason, sources=None)`.
  Skills allowed: market_intelligence, fundamental, technical, fno, strategy, risk, execution.
- `context.market_context(as_of) -> List[Evidence]` — first item's `data["regime"]["value"]` is BULL|BEAR|SIDEWAYS
  when `status=="OK"`; `data["india_vix"]` on the VIX item.
- `calibration.calibration_report(iterable_of_(confidence, hit)) -> {n, bins, brier, calibration_error}`.
- `_research.load()` -> (context, regime, research_window, resample); `research_window.overlaps_sealed_gap(a, b)`,
  `.SEALED_GAP_START/END` = 2023-01-01 / 2024-07-31. `_research.ResearchUnavailable`.

## strategy.py (Phase 2) — owner: agent "strategy"
```python
STAGES = ("draft", "backtested", "paper", "assisted", "retired")
TEMPLATES_BY_REGIME = {"BULL": "momentum_breakout", "SIDEWAYS": "mean_reversion", "BEAR": "accumulation"}
GATES: dict           # {"backtested": [Gate...], "paper": [...], "assisted": [...]} ; Gate has code, label, threshold
class StrategyError(ValueError): ...        # bad input
class GateNotMet(ValueError): ...           # carries .unmet: list[dict]
class SealedWindowRefused(ValueError): ...
class HoldoutUsed(ValueError): ...

def load_template(name: str) -> dict                      # from services/strategy_engine/templates/<name>.json
def propose(market_evidence: list, *, symbols, ui_config=None, strategy_info=None) -> dict
    # -> {"spec": <DSL dict, passes strategy_engine.dsl.validate_strategy>, "config": cfg.to_dict(),
    #     "template": name, "regime": "BULL", "provenance": {...evidence refs...}}
    # raises StrategyError("regime_unavailable") when no OK regime evidence
def spec_version(spec: dict, config: dict) -> str          # stable sha256-based hash, 16 hex chars
def new_strategy(user_id: str, proposal: dict, name: str | None = None) -> dict   # Mongo doc, stage "draft"
def folds(from_date: date, to_date: date, n: int = 4) -> list[tuple[date, date]]
def evaluate_gates(target_stage: str, metrics: dict, *, walk_forward=None, paper_stats=None) -> list[dict]
    # one row per criterion: {code, label, value, threshold, passed}
def promote(doc: dict, target_stage: str, *, metrics=None, walk_forward=None, paper_stats=None) -> dict
    # one stage at a time; raises GateNotMet / StrategyError("invalid_stage"|"stage_skip")
async def run_backtest_for(doc, *, from_date, to_date, runner, holdout=False, pool=None) -> dict
    # refuses a window overlapping the sealed block unless holdout=True; HoldoutUsed if doc already used it;
    # returns {"metrics", "resolved_config", "window", "holdout", "walk_forward": [...]}
```
Gate thresholds (PRD assumption B3, keep as module constants): backtested needs a stored run; paper needs
trade_count>=100, profit_factor>=1.3, max_drawdown_pct>=-25, total_return_pct>0, walk-forward >=3 of 4 folds positive,
universe_basis in ACCEPTED_UNIVERSE_BASIS (see below); assisted needs paper closed_trades>=20, net expectancy>0,
profit_factor>=1.2, |paper win rate - backtest win rate|<=15.

Updated 2026-10-21 after the adversarial review, by the agent that owns strategy.py:
- `BANNED_UNIVERSE_BASIS` is replaced by `ACCEPTED_UNIVERSE_BASIS = ("point_in_time", "custom_universe")`. The gate is
  now an allowlist and fails closed: the provider can also report `present_day_fallback`, `latest_snapshot` and
  `unknown`, all of which carry membership look-ahead, and a denylist of one let the other two through.
- `_last_run` is replaced by private `_gate_runs(doc)` and `_gate_run(doc, target_stage)`. Gate evidence never
  defaults to the one-shot sealed-block holdout run, and for `assisted` it is the newest run that itself passed every
  paper criterion, so an exploratory run can neither flatter nor block the win-rate-gap comparison.
- New constant `PORTFOLIO_SIZING_BASIS`. The two portfolio-percentage gate rows (`total_return_pct`,
  `max_drawdown_pct`) now require `metrics["sizing_basis"] == "portfolio"` and otherwise report "not measured" and
  fail. Nothing emits that key today: see the open question in the PRD.
- `stage_history` entries gained an additive key `evidence_run = {"run_id", "window"}` or None, so a promotion can be
  traced to the run that justified it.

## execution.py (Phase 4/5) — owner: agent "execution"
```python
TICKET_STATUSES = ("awaiting_confirmation", "confirmed", "rejected", "expired", "executed_paper")
class ExecutionError(ValueError): ...
def intents_from_candidates(spec, config, candidates, *, as_of) -> list[Intent]
    # candidate rows look like the market-data provider's screen() output: {"symbol", "close", "atr14", ...}
    # entry = close; stop = entry*(1-exit.stoploss_pct/100); target = entry + (entry-stop)*exit.target_rr;
    # quantity sized from config["initial_capital"] and the governor's risk-per-trade limit
def new_ticket(user_id, strategy_doc, intent, decision, *, as_of, mode) -> dict   # mode "paper"|"assisted"
def ticket_text(ticket) -> str      # must contain symbol, qty, entry, stop, target and the line
                                    # "Place this order yourself at your broker; Nivesh sends nothing."
def outcome_pairs(tickets, closed_trades) -> list[tuple[float, bool]]   # feeds calibration_report
```
Routes to add to `routes/ai_trader.py` (keep the existing three untouched; same auth `Depends(get_current_user)`;
Mongo via `from deps import db`; collections `ai_trader_strategies`, `ai_trader_tickets`):
```
POST /strategies                      {symbols, as_of, name?, ui_config?}        -> 201 strategy doc
GET  /strategies                      -> list (own only)
GET  /strategies/{id}                 -> doc (404 if not yours)
POST /strategies/{id}/backtest        {from_date, to_date, holdout?}             -> run summary
POST /strategies/{id}/promote         {target_stage}                             -> doc | 409 {unmet:[...]}
POST /strategies/{id}/signals         {as_of, mode}                              -> {tickets:[...]} (409 if stage
                                       is draft/backtested; mode "live" -> 422)
GET  /tickets?status=&strategy_id=    -> list (own only)
POST /tickets/{id}/confirm            -> re-runs the governor; 409 if expired or now worse than approve/reduce
POST /tickets/{id}/reject             {reason?}                                  -> doc
GET  /strategies/{id}/journal         -> {calibration: {...}, paper_stats: {...}}
```
Paper trades: build with `services.desk_trading.new_trade(user_id, body)` and insert into `desk_trading.TRADES`
(source `{"kind": "ai_trader"}`, `strategy_version`, `rationale`). Never import any broker module.

## Shared rules (both agents)
- The repo's CONTEXT.md: no fabricated output, no silent mocks (label `# MOCK — not real data`), smallest change,
  match neighbouring style, docstring at the top of each module saying what it does and what it refuses to do.
- Comments explain *why*, not *what*. Prose in docstrings, plain words, no em dashes.
- Tests: `backend/tests/test_ai_trader_strategy.py` (strategy agent) and `backend/tests/test_ai_trader_execution.py`
  (execution agent). Nothing else may be edited by either agent except its own files.
- Run tests with:
  `sudo docker run --rm --network none -v /home/deploy/nivesh-ai-trader:/work:ro -w /work/backend
   -e PYTHONDONTWRITEBYTECODE=1 -e MONGO_URL=mongodb://localhost:27017 -e DB_NAME=unit_test
   -e OPENAI_API_KEY=unit-test-placeholder nivesh/backend:staging python -m pytest tests/<file> -q -p no:cacheprovider`
  The container mounts the tree READ-ONLY, so edit files on the host and re-run.
- No Postgres and no Mongo in tests: inject a fake runner for backtests, and a fake Mongo (dict-backed, equality
  filters) for routes, the way `backend/tests/test_desk_alerts.py` already does. Read that file first.
