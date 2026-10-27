"""AI Trader (docs/prd/AI_TRADER_PHASE1.prd.md, docs/prd/AI_TRADER_PHASES_2_5.prd.md). Nothing here places an order.

Phase 1, read-only evidence:
    GET  /evidence?symbol=&as_of=YYYY-MM-DD   — {as_of, symbol, evidence: [Evidence], notes}: market regime, trend, VIX,
                                                breadth, the sector rotation table and (with `symbol`) the daily/weekly/
                                                monthly trend and any timeframe conflicts. Each item is an Evidence
                                                record or UNAVAILABLE with a reason_code; a value is never filled in.
    POST /calibration  {predictions: [{confidence, hit}]}
                                              — reliability bins, Brier score and calibration error.
    POST /pattern-validation {events: [{symbol, signal_date, direction?, regime?}], horizon_sessions?}
                                              — hit rate, shrunk hit rate and expectancy net of costs (long only).

Phases 2 to 5, strategies, paper execution and assisted tickets (every route is scoped to the signed-in user: a
strategy or ticket that is not yours answers 404, the same as one that does not exist):
    POST /strategies                 {symbols, as_of, name?, ui_config?}       → 201 {strategy} at stage draft
                                     409 `regime_unavailable` when the market regime is not readable for that date
    GET  /strategies                 — your strategies, newest first
    GET  /strategies/{id}            — one strategy with its runs and stage history
    POST /strategies/{id}/backtest   {from_date, to_date, holdout?}            → {run, strategy}
                                     422 `sealed_window` · 409 `holdout_used` · 503 `market_data_unavailable` ·
                                     409 `holdout_before_backtest` (the sealed block is not spent on a strategy that
                                     has no ordinary run yet)
    POST /strategies/{id}/promote    {target_stage}                            → {strategy}
                                     409 {code: "gate_not_met", unmet: [...]} · 409 `stage_skip` · 422 `invalid_stage`
                                     (there is no `live` stage, so "live" is 422)
    POST /strategies/{id}/signals    {as_of, mode: "paper"|"assisted"}         → {tickets, created, existing}
                                     Screens the strategy's DSL, sizes each candidate, puts every intent through the
                                     Risk Governor and stores a ticket for each one, approved or not. In paper mode an
                                     approved or reduced ticket opens a paper trade at the governor's quantity; any
                                     other decision opens none and the ticket carries the reason codes. Calling it
                                     twice for the same strategy, symbol and signal date creates nothing a second
                                     time. 409 `stage_cannot_signal` (draft/backtested) · 409 `mode_not_allowed_for_stage`
                                     · 422 on `mode: "live"` (the only modes are paper and assisted) · 422
                                     `as_of_in_the_future`, `sealed_window` (a date inside the sealed research block)
                                     or `as_of_too_old` · 503 `idempotence_index_unavailable`
    GET  /tickets?status=&strategy_id=
                                     — your tickets, newest first; an assisted ticket past its session is expired here
    POST /tickets/{id}/confirm       — re-runs the governor against your CURRENT book, then records a paper-shadow
                                       trade and returns the copy-ready order text. Nothing is sent to a broker.
                                     409 `ticket_expired` · 409 `ticket_not_awaiting_confirmation` ·
                                     409 {code: "risk_refused", decision: {...}} when the governor now refuses ·
                                     422 with the desk's own code when the paper trade cannot be written. The re-run
                                     can lower the size or refuse it; it never raises it above what was approved on
                                     the signal date.
    POST /tickets/{id}/reject        {reason?}                                 → {ticket}
    GET  /strategies/{id}/journal    — {calibration, paper_stats}: closed shadow trades scored against the confidence
                                       the strategy stated, and the paper tally the paper-to-assisted gate reads

Errors: 401 unauthenticated; 404 `unknown_symbol`, `strategy_not_found`, `ticket_not_found`; 422 on a missing or
invalid body, date or symbol; 503 `research_engine_unavailable` when the research package cannot be imported and
`market_data_unavailable` when the screen or backtest data cannot be read. When the bars source itself is missing the
symbol-level evidence items are returned UNAVAILABLE (BARS_SOURCE_MISSING) and `notes` says so.

No broker, by construction: this file imports no broker module and no order client, and the paper trades it writes are
`services/desk_trading.py` records. A test (tests/test_ai_trader_execution.py) parses the AST of this file and of every
module under services/ai_trader to keep it that way.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import re
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from pymongo.errors import DuplicateKeyError

from deps import db, get_current_user
from services import desk_trading as desk
from services import desk_strategy_trades as desk_strategy
from services import risk_controls as rc
from services import risk_gate
from services import risk_book
from services import pg_client
from services.ai_trader import _research, execution, strategy
from services.ai_trader.calibration import CalibrationError, calibration_report
from services.ai_trader.config import ConfigValidationError
from services.ai_trader.context import market_context
from services.ai_trader.evidence import unavailable
from services.ai_trader.risk_governor import Decision as GovDecision, Reason
from services.risk_gate import inputs as risk_inputs
from services.risk_gate import service as risk_service
from services.ai_trader.sector import sector_rotation
from services.ai_trader.timeframes import timeframe_evidence
from services.ai_trader.validation import evaluate_events
from services.strategy_engine.backtest import run_backtest
from services.strategy_engine.market_data import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/ai-trader", tags=["ai-trader"])

_SYMBOL = re.compile(r"^[A-Za-z0-9&_-]{1,20}$")
MAX_EVENTS = 500
MAX_PREDICTIONS = 100_000

_ID_MAX = 64
MAX_SYMBOLS = 500
MAX_STRATEGIES_LISTED = 200
MAX_TICKETS_LISTED = 1000
# A signal is acted on off the last session's close, so an older date is refused: a hindsight-picked past session
# would fill the paper record that gates `assisted` with trades nobody could have taken. Four days lets Friday's
# close still be signalled on Tuesday after a long weekend.
MAX_SIGNAL_AGE_DAYS = 4
NAME_MAX = 120
REASON_MAX = 500
UI_CONFIG_FIELDS = ("initial_capital", "commission_pct", "pyramiding", "short_margin_pct")
ORDERS_NOTE = "Nothing is sent to any broker. A paper trade is a record Nivesh keeps; you place real orders yourself."

_indexes_ready = False


def _as_of(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid_as_of")


def _engine():
    try:
        return _research.load()
    except _research.ResearchUnavailable:
        raise HTTPException(status_code=503, detail="research_engine_unavailable")


def _load_bars(symbol: str):
    """(bars | None, note | None). None with a note when the bars source is missing; HTTP 404 when it is there but the
    symbol is not."""
    from research.charting import bars as bars_mod
    folder = bars_mod.source_dir()
    if not folder.is_dir() or not bars_mod._part_files(folder):
        return None, "bars source not present on this host"
    df = bars_mod.load_symbol(symbol.upper())
    if df.empty:
        raise HTTPException(status_code=404, detail="unknown_symbol")
    return df, None


def _compute(symbol: Optional[str], as_of: str) -> Dict[str, Any]:
    _engine()
    items: List[Any] = []
    notes: List[str] = []
    items += market_context(as_of)
    items += sector_rotation(as_of)
    if symbol:
        bars, note = _load_bars(symbol)
        if bars is None:
            notes.append(note)
            for tf in ("daily", "weekly", "monthly"):
                items.append(unavailable("technical", symbol.upper(), as_of, tf, f"{symbol.upper()} {tf} trend",
                                         "BARS_SOURCE_MISSING"))
        else:
            items += timeframe_evidence(symbol.upper(), bars, as_of)
    return {"as_of": as_of, "symbol": symbol.upper() if symbol else None,
            "evidence": [e.to_dict() for e in items], "notes": notes}


@router.get("/evidence")
async def evidence(as_of: str = Query(...), symbol: Optional[str] = Query(None),
                   user: dict = Depends(get_current_user)):
    when = _as_of(as_of)
    if symbol is not None and not _SYMBOL.match(symbol):
        raise HTTPException(status_code=422, detail="invalid_symbol")
    return await asyncio.to_thread(_compute, symbol, when)


class Prediction(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)
    hit: bool


class CalibrationBody(BaseModel):
    predictions: List[Prediction] = Field(..., max_length=MAX_PREDICTIONS)


@router.post("/calibration")
async def calibration(body: CalibrationBody, user: dict = Depends(get_current_user)):
    try:
        return calibration_report((p.confidence, p.hit) for p in body.predictions)
    except CalibrationError as e:
        raise HTTPException(status_code=422, detail=str(e))


class Event(BaseModel):
    symbol: str = Field(..., pattern=_SYMBOL.pattern)
    signal_date: date
    direction: str = "long"
    regime: Optional[str] = None


class ValidationBody(BaseModel):
    events: List[Event] = Field(..., max_length=MAX_EVENTS)
    horizon_sessions: int = Field(5, ge=1, le=60)


def _validate(body: ValidationBody) -> Dict[str, Any]:
    _engine()
    bars_by_symbol = {}
    for sym in {e.symbol.upper() for e in body.events}:
        bars, _note = _load_bars(sym)
        if bars is not None:
            bars_by_symbol[sym] = bars
    events = [{"symbol": e.symbol.upper(), "signal_date": e.signal_date.isoformat(), "direction": e.direction,
               "regime": e.regime} for e in body.events]
    return evaluate_events(events, bars_by_symbol, body.horizon_sessions)


@router.post("/pattern-validation")
async def pattern_validation(body: ValidationBody, user: dict = Depends(get_current_user)):
    return await asyncio.to_thread(_validate, body)


# ── Phases 2 to 5: strategies, paper execution, assisted tickets ─────────────
async def _ensure_indexes(require_unique: bool = False) -> None:
    """Indexes for the per-user reads and for the idempotence check. Asked for once per process; a failure is logged
    and asked for again on the next call, the way services/desk_trading.py does it.

    The two read indexes are an optimisation and a failure is only logged. The unique ticket index is not: it is the
    only thing that stops one signal becoming two tickets, so a caller that is about to write a ticket passes
    `require_unique` and gets 503 rather than a write with the guarantee missing."""
    global _indexes_ready
    if _indexes_ready:
        return
    try:
        await db[execution.STRATEGIES].create_index([("user_id", 1), ("created_at", -1)])
        await db[execution.TICKETS].create_index([("user_id", 1), ("created_at", -1)])
    except Exception as exc:  # noqa: BLE001 — a read index is an optimisation; the routes work without one
        logger.warning("ai_trader: the read indexes could not be created: %r", exc)
    try:
        # Unique, so idempotence does not rest on a read-then-write: two requests racing for the same signal leave
        # one ticket and one paper trade, whatever the timing.
        await db[execution.TICKETS].create_index([("user_id", 1), ("strategy_id", 1), ("signal_date", 1),
                                                  ("symbol", 1)], unique=True)
    except Exception as exc:  # noqa: BLE001
        logger.error("ai_trader: the unique ticket index could not be created: %r", exc)
        if require_unique:
            raise HTTPException(status_code=503, detail="idempotence_index_unavailable")
        return
    _indexes_ready = True


def _today_ist() -> date:
    """Today in IST, read through the desk's clock so a session boundary is the same one the paper trades use."""
    return desk.utcnow().astimezone(desk.IST).date()


async def _own_strategy(uid: str, strategy_id: str) -> Dict[str, Any]:
    doc = await db[execution.STRATEGIES].find_one({"_id": strategy_id, "user_id": uid}) \
        if len(strategy_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="strategy_not_found")
    return doc


async def _own_ticket(uid: str, ticket_id: str) -> Dict[str, Any]:
    doc = await db[execution.TICKETS].find_one({"_id": ticket_id, "user_id": uid}) \
        if len(ticket_id) <= _ID_MAX else None
    if not doc:
        raise HTTPException(status_code=404, detail="ticket_not_found")
    return doc


def _public_strategy(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["_id"],
        "name": doc.get("name"),
        "stage": doc.get("stage"),
        "version": doc.get("version"),
        "template": doc.get("template"),
        "regime": doc.get("regime"),
        "created_by": doc.get("created_by"),
        "spec": doc.get("spec"),
        "config": doc.get("config"),
        "provenance": doc.get("provenance"),
        "runs": doc.get("runs") or [],
        "holdout_used": bool(doc.get("holdout_used")),
        "holdout_window": doc.get("holdout_window"),
        "paper_stats": doc.get("paper_stats"),
        "stage_history": doc.get("stage_history") or [],
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "stages": list(strategy.STAGES),
        "orders": ORDERS_NOTE,
    }


def _public_ticket(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in doc.items() if k not in ("_id", "user_id")}
    out["id"] = doc["_id"]
    # The copy-ready order exists only for a ticket the governor cleared; a refused one must not read like an order.
    # A confirm the governor has since refused leaves its refusal in `last_decision` while the ticket waits for the
    # book to free up, so the stale creation-time text is withheld until a later confirm clears it again.
    last = (doc.get("last_decision") or {}).get("action")
    cleared_now = doc.get("governor_cleared") and (last is None or last in execution.ACTIONABLE)
    out["text"] = execution.ticket_text(doc) if cleared_now else None
    return out


async def _closed_trades(uid: str) -> List[Dict[str, Any]]:
    """The user's closed paper trades, newest first. Equality filters only, so this works the same against Mongo and
    against the in-memory collection the tests use."""
    return await db[desk.TRADES].find({"user_id": uid, "status": "closed"}) \
        .sort("closed_at", -1).to_list(desk.MAX_CLOSED_LISTED)


async def _strategy_record(uid: str, strategy_id: str) -> tuple:
    """(every ticket of this strategy, oldest first; the closed paper trades those tickets opened). The link is the
    ticket's `trade_id`, so a trade is only counted for the strategy that actually produced it.

    The closed trades are selected by those ids rather than filtered out of the desk's newest-first page: a user with
    more than `desk.MAX_CLOSED_LISTED` closed desk trades would otherwise lose this strategy's older ones, and the
    paper record the assisted gate reads would be a slice presented as the whole."""
    tickets = await db[execution.TICKETS].find({"user_id": uid, "strategy_id": strategy_id}) \
        .sort("created_at", 1).to_list(MAX_TICKETS_LISTED)
    trade_ids = [t["trade_id"] for t in tickets if t.get("trade_id")]
    if not trade_ids:
        return tickets, []
    closed = await db[desk.TRADES].find({"user_id": uid, "status": "closed", "_id": {"$in": trade_ids}}) \
        .sort("closed_at", -1).to_list(len(trade_ids))
    return tickets, closed


def _governor_decision(decision: Dict[str, Any]) -> GovDecision:
    """The universal risk service's decision in the governor's shape the ticket stores (services/ai_trader/execution):
    block -> halt / reject / defer by its most severe reason, reduce -> reduce, allow -> approve."""
    reasons = [Reason(r["code"], r["message"], r["severity"], r.get("value"), r.get("limit")) for r in decision["reasons"]]
    sev = {r["severity"] for r in decision["reasons"]}
    if decision["outcome"] == "block":
        action = "halt" if "halt" in sev else "defer" if ("defer" in sev and not sev & {"reject", "block"}) else "reject"
    else:
        action = "reduce" if decision["outcome"] == "reduce" else "approve"
    return GovDecision(action, int(decision.get("requested_qty") or 0), int(decision.get("approved_qty") or 0), reasons,
                       limits_version=decision.get("limits_version") or risk_service.POLICY_VERSION)


def _risk_ids(decision: Dict[str, Any]) -> Dict[str, Any]:
    return {"correlation_id": decision["correlation_id"], "risk_decision_id": decision["decision_id"],
            "risk_reservation_id": decision.get("reservation_id"), "risk_policy_version": risk_service.POLICY_VERSION}


async def _capital_basis(uid: str, initial_capital: float) -> Dict[str, Any]:
    """The capital the strategy's intents are sized from: its `initial_capital` CAPPED at the account's paper equity
    (decision D1), so a strategy configured at Rs 100 crore cannot size against money the account does not have. The
    risk service then judges every intent against paper equity itself; with equity unknown it blocks every intent."""
    try:
        book = await risk_book.read(db, uid, sector_of=risk_inputs.sector_of)
        equity = book["equity"]["equity_rs"]
    except Exception as e:  # noqa: BLE001 — sized from the configured capital; the service still blocks on unknowns
        logger.warning("ai_trader: equity unreadable for %s (%s)", uid, type(e).__name__)
        equity = None
    used = min(float(initial_capital), float(equity)) if equity is not None else float(initial_capital)
    return {"initial_capital": float(initial_capital), "paper_equity_rs": equity, "sizing_capital_rs": round(used, 2),
            "capped": equity is not None and float(initial_capital) > float(equity)}


def _entry(user: Dict[str, Any], cid: str, uid: str, *, path: str, mode: str, symbol: str, quantity: int, entry: float,
           stop: Optional[float], target: Optional[float], trade_id: str) -> risk_service.EntryRequest:
    return risk_service.EntryRequest(correlation_id=cid, user_id=uid, actor_id=rc.session_actor(user), mode=mode, path=path,
                                     action="open", instrument="cash", symbol=symbol, quantity=quantity, entry_price=entry,
                                     stop_price=stop, target_price=target, trade_id=trade_id, store=desk.TRADES,
                                     cost_model=dict(desk.COST_MODEL))


async def _screen(spec: Dict[str, Any], as_of: date) -> List[Dict[str, Any]]:
    """The strategy's candidates for one session, through the strategy engine's market-data provider (direct SQL on
    co-located dev, the NIDP DaaS API on staging and prod). A fresh provider per call: a provider instance keeps
    per-universe state and must not be shared."""
    pool = await pg_client.get_pool()
    provider = get_provider(pool)
    await provider.prepare(spec, as_of, as_of)
    return await provider.screen(spec, as_of)


class StrategyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: List[str] = Field(..., min_length=1, max_length=MAX_SYMBOLS)
    as_of: date
    name: Optional[str] = Field(None, min_length=1, max_length=NAME_MAX)
    ui_config: Optional[Dict[str, Any]] = None


@router.post("/strategies", status_code=201)
async def create_strategy(body: StrategyBody, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Propose a strategy from the market evidence for `as_of` and store it at stage draft (PRD F2.2, F2.3)."""
    symbols = [s.strip().upper() for s in body.symbols]
    if any(not _SYMBOL.match(s) for s in symbols):
        raise HTTPException(status_code=422, detail="invalid_symbol")
    ui = dict(body.ui_config or {})
    if set(ui) - set(UI_CONFIG_FIELDS):
        # config.resolve ignores a key it does not know, so an unknown one is refused here rather than dropped.
        raise HTTPException(status_code=422, detail="unknown_ui_config_field")

    evidence = await asyncio.to_thread(_evidence_for, body.as_of.isoformat())
    try:
        proposal = strategy.propose(evidence, symbols=symbols, ui_config=ui or None)
    except strategy.StrategyError as exc:
        code = str(exc)
        raise HTTPException(status_code=409 if code in ("regime_unavailable", "unknown_regime") else 422, detail=code)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=422, detail=f"invalid_config: {exc}")
    doc = strategy.new_strategy(user["user_id"], proposal, body.name)
    await _ensure_indexes()
    await db[execution.STRATEGIES].insert_one(doc)
    logger.info("ai_trader: user %s created strategy %s (%s, %s)", user["user_id"], doc["_id"], doc["template"],
                doc["version"])
    return {"strategy": _public_strategy(doc)}


def _evidence_for(as_of: str) -> List[Any]:
    _engine()
    return market_context(as_of)


@router.get("/strategies")
async def list_strategies(user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    await _ensure_indexes()
    docs = await db[execution.STRATEGIES].find({"user_id": user["user_id"]}) \
        .sort("created_at", -1).to_list(MAX_STRATEGIES_LISTED)
    return {"strategies": [_public_strategy(d) for d in docs], "orders": ORDERS_NOTE}


@router.get("/strategies/{strategy_id}")
async def get_strategy(strategy_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    doc = await _own_strategy(user["user_id"], strategy_id)
    return {"strategy": _public_strategy(doc)}


class BacktestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    from_date: date
    to_date: date
    holdout: bool = False


@router.post("/strategies/{strategy_id}/backtest")
async def backtest_strategy(strategy_id: str, body: BacktestBody,
                            user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Run the window and its walk-forward folds through the DSL backtester and store the run on the strategy
    (PRD F2.4, F2.6). A window overlapping the sealed research block is refused unless `holdout` is set, and then
    only once per strategy and only for a strategy that already has an ordinary run to confirm. The seal is claimed
    in the database before the window is handed over, so a failed run spends it too: the block was already read."""
    doc = await _own_strategy(user["user_id"], strategy_id)
    try:
        pool = await pg_client.get_pool()
    except Exception as exc:  # noqa: BLE001 — a backtest without data is reported, never approximated
        logger.exception("ai_trader: no Postgres pool for a backtest: %r", exc)
        raise HTTPException(status_code=503, detail="market_data_unavailable")
    claimed_window: Optional[Dict[str, str]] = None
    if body.holdout:
        _ctx, _regime, rw, _rs = _engine()
        if rw.overlaps_sealed_gap(body.from_date, body.to_date):
            # The holdout is the final out-of-sample confirmation of a strategy that already has a record. Spent on a
            # strategy with no ordinary run it buys nothing and cannot be given back.
            if not any(isinstance(r, dict) and not r.get("holdout") for r in (doc.get("runs") or [])):
                raise HTTPException(status_code=409, detail="holdout_before_backtest")
            # The seal is spent in the database before any sealed data reaches the runner, so two requests racing on
            # the same strategy cannot both open the block and a run that fails half way cannot leave it looking
            # unused (PRD B4). The filter is the equality form because the claim has to be conditional on the stored
            # value, which `new_strategy` always writes as False.
            window = {"from_date": body.from_date.isoformat(), "to_date": body.to_date.isoformat()}
            claimed = await db[execution.STRATEGIES].update_one(
                {"_id": doc["_id"], "user_id": user["user_id"], "holdout_used": False},
                {"$set": {"holdout_used": True, "holdout_window": window,
                          "updated_at": desk.utcnow().isoformat()}})
            if not claimed.matched_count:
                raise HTTPException(status_code=409, detail="holdout_used")
            # `doc` keeps the pre-run value until the run returns: run_backtest_for's own one-shot guard reads it,
            # and the claim above is what makes the refusal durable.
            claimed_window = window
    try:
        run = await strategy.run_backtest_for(doc, from_date=body.from_date, to_date=body.to_date,
                                              runner=run_backtest, holdout=body.holdout, pool=pool)
    except strategy.SealedWindowRefused:
        raise HTTPException(status_code=422, detail="sealed_window")
    except strategy.HoldoutUsed:
        raise HTTPException(status_code=409, detail="holdout_used")
    except strategy.StrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai_trader: the backtest of %s failed: %r", strategy_id, exc)
        raise HTTPException(status_code=503, detail="market_data_unavailable")
    if claimed_window:
        doc["holdout_used"], doc["holdout_window"] = True, claimed_window      # what the claim stored, for the reply
    # The one run is pushed rather than the whole array rewritten from this request's snapshot, so a concurrent
    # backtest's run is not lost. The holdout stamp is owned by the claim above and is never written back from the
    # snapshot, which would undo it.
    await db[execution.STRATEGIES].update_one(
        {"_id": doc["_id"], "user_id": user["user_id"]},
        {"$push": {"runs": run}, "$set": {"updated_at": doc.get("updated_at")}})
    return {"run": run, "strategy": _public_strategy(doc)}


class PromoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_stage: str


@router.post("/strategies/{strategy_id}/promote")
async def promote_strategy(strategy_id: str, body: PromoteBody,
                           user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Move a strategy one stage, and only on a clean sheet (PRD F2.5). There is no live stage, so `live` is 422.
    A failing gate answers 409 with every unmet criterion, its value and its threshold."""
    uid = user["user_id"]
    doc = await _own_strategy(uid, strategy_id)
    if body.target_stage not in strategy.STAGES:
        raise HTTPException(status_code=422, detail="invalid_stage")
    _tickets, closed = await _strategy_record(uid, strategy_id)
    stats = execution.paper_stats(closed)
    try:
        updated = strategy.promote(doc, body.target_stage,
                                   paper_stats=stats if body.target_stage == "assisted" else None)
    except strategy.GateNotMet as exc:
        raise HTTPException(status_code=409, detail={"code": "gate_not_met", "target_stage": exc.target_stage,
                                                     "unmet": exc.unmet})
    except strategy.StrategyError as exc:
        code = str(exc)
        raise HTTPException(status_code=422 if code == "invalid_stage" else 409, detail=code)
    change = {"stage": updated["stage"], "stage_history": updated["stage_history"],
              "paper_stats": stats, "updated_at": updated["updated_at"]}
    await db[execution.STRATEGIES].update_one({"_id": doc["_id"], "user_id": uid}, {"$set": change})
    logger.info("ai_trader: user %s moved strategy %s to %s", uid, strategy_id, updated["stage"])
    return {"strategy": _public_strategy({**updated, **change})}


class SignalsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date
    # The only modes there are. "live" is refused here, which is why no live branch exists below.
    mode: Literal["paper", "assisted"]


@router.post("/strategies/{strategy_id}/signals")
async def strategy_signals(strategy_id: str, body: SignalsBody, request: Request,
                           user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Turn one session's screened candidates into tickets (PRD F4.1 to F4.4, F5.1).

    Only a strategy at stage paper or assisted may signal, and the mode must be its stage. Every intent is stored as
    a ticket with the governor's decision and reasons. In paper mode a cleared ticket opens one paper trade at the
    governor's approved quantity; in assisted mode it waits for the user. A symbol that already has a ticket for this
    strategy and signal date is left alone, so calling this twice changes nothing."""
    uid = user["user_id"]
    doc = await _own_strategy(uid, strategy_id)
    stage = doc.get("stage")
    if stage not in ("paper", "assisted"):
        raise HTTPException(status_code=409, detail="stage_cannot_signal")
    if body.mode != stage:
        raise HTTPException(status_code=409, detail="mode_not_allowed_for_stage")
    if body.as_of > _today_ist():
        raise HTTPException(status_code=422, detail="as_of_in_the_future")
    _ctx, _regime, rw, _rs = _engine()
    if rw.is_sealed_gap(body.as_of):
        # Screening a sealed session and opening trades from it is a research read of the block, which only the
        # one-shot holdout backtest may make (PRD B4). Refused before any provider call.
        raise HTTPException(status_code=422, detail="sealed_window")
    if body.as_of < _today_ist() - timedelta(days=MAX_SIGNAL_AGE_DAYS):
        raise HTTPException(status_code=422, detail="as_of_too_old")
    spec, config = doc.get("spec"), doc.get("config")
    if not isinstance(spec, dict) or not isinstance(config, dict):
        raise HTTPException(status_code=409, detail="strategy_incomplete")

    signal_date = body.as_of.isoformat()
    await _ensure_indexes(require_unique=True)
    stored = await db[execution.TICKETS].find(
        {"user_id": uid, "strategy_id": strategy_id, "signal_date": signal_date}).to_list(MAX_TICKETS_LISTED)
    seen = {t["symbol"] for t in stored}

    try:
        candidates = await _screen(spec, body.as_of)
    except Exception as exc:  # noqa: BLE001 — no candidates is reported, never guessed at
        logger.exception("ai_trader: the screen for %s on %s failed: %r", strategy_id, signal_date, exc)
        raise HTTPException(status_code=503, detail="market_data_unavailable")
    basis = await _capital_basis(uid, float(config["initial_capital"]))
    sized = {**config, "initial_capital": basis["sizing_capital_rs"]}
    try:
        intents = execution.intents_from_candidates(spec, sized, candidates, as_of=body.as_of)
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Every intent is judged by the universal risk service (services/risk_gate/service.py) against the account's
    # current book, BEFORE its ticket or trade is written; the decision is recorded in risk_decisions by the service.
    # In paper mode an allowed or reduced intent's risk is reserved atomically under the decision's id and the paper
    # trade is opened at the approved size; in assisted mode nothing is reserved until the user confirms. Each decision
    # sees the reservations of the ones before it, so a run can never overspend the open-risk or sector budget.
    cid = risk_gate.correlation_id(request)
    made: List[Dict[str, Any]] = []
    for intent in intents:
        if intent.symbol in seen:
            continue
        seen.add(intent.symbol)
        trade_id = str(uuid.uuid4())
        try:
            decision = await risk_service.enter(db, _entry(
                user, cid, uid, path="ai_trader_signal", mode=body.mode, symbol=intent.symbol,
                quantity=int(intent.quantity), entry=float(intent.entry_price), stop=intent.stop_price,
                target=intent.target_price, trade_id=trade_id), reserve=body.mode == "paper", accept_reduce=True)
        except risk_service.DecisionUnrecorded:
            raise risk_service.unrecorded(cid)
        ticket = execution.new_ticket(uid, doc, intent, _governor_decision(decision), as_of=signal_date, mode=body.mode)
        ticket.update(_risk_ids(decision))
        ticket["capital_basis"] = basis
        try:
            # The ticket is written before any trade, so a request that lost the race opens nothing.
            await db[execution.TICKETS].insert_one(ticket)
        except DuplicateKeyError:
            await risk_service.release_unused(db, uid, decision, reason="duplicate ticket")
            logger.info("ai_trader: %s already has a ticket for %s on %s", strategy_id, intent.symbol, signal_date)
            continue
        except Exception:
            await risk_service.release_unused(db, uid, decision, reason="ticket insert failed")
            raise
        if ticket["governor_cleared"] and body.mode == "paper":
            try:
                trade = await _open_paper_trade(uid, ticket, doc, decision, trade_id)
            except desk.DeskInputError as exc:
                # The desk refused the order, so this ticket is finished: recorded with the reason instead of left in
                # the transient "confirmed" state, and the loop goes on so the reply names every ticket written.
                await risk_service.release_unused(db, uid, decision, reason=f"desk refused: {exc.code}")
                ticket.update(await _reject_by_desk(uid, ticket, exc.code))
                made.append(ticket)
                continue
            change = execution.mark_executed(ticket, trade)
            await db[execution.TICKETS].update_one({"_id": ticket["_id"], "user_id": uid, "status": "confirmed"},
                                                   {"$set": change})
            ticket.update(change)
        elif decision.get("reservation_id"):
            await risk_service.release_unused(db, uid, decision, reason="ticket not cleared")
        made.append(ticket)
    logger.info("ai_trader: user %s took %d of %d candidates for strategy %s on %s (%s)", uid, len(made),
                len(intents), strategy_id, signal_date, body.mode)
    return {
        "strategy_id": strategy_id,
        "as_of": signal_date,
        "mode": body.mode,
        "candidates": len(intents),
        "created": len(made),
        "existing": len(stored),
        "tickets": [_public_ticket(t) for t in made + stored],
        "orders": ORDERS_NOTE,
    }


async def _open_paper_trade(uid: str, ticket: Dict[str, Any], strategy_doc: Dict[str, Any], decision: Dict[str, Any],
                            trade_id: str) -> Dict[str, Any]:
    """The paper trade a cleared ticket opens, through the desk's own validator so the document is a real desk trade
    (PRD F4.2), at the size the risk service approved, under the id its reservation was taken for. In assisted mode
    this is the shadow of the order the user places at their broker.

    The funds and the risk budget were reserved by the risk service (services/paper_account.reserve_entry); this writes
    the position only. A `desk.DeskInputError` or a failed insert is left to the caller, which gives the reservation
    back (risk_service.release_unused)."""
    rationale = (f"AI Trader {ticket['mode']} signal from {strategy_doc.get('name') or 'a strategy'} "
                 f"({strategy_doc.get('version')}) on {ticket['signal_date']}; risk decision "
                 f"{decision.get('outcome')} ({risk_service.POLICY_VERSION}).")
    trade = desk.new_trade(uid, execution.trade_body(ticket, rationale=rationale[:desk.NOTE_MAX]))
    trade["_id"] = trade_id
    risk_service.stamp(trade, decision)
    trade["paper_reserved_rs"] = float(decision["budget"].get("funding_rs") or 0.0)
    trade["open_key"] = desk.open_key(trade)
    try:
        await db[desk.TRADES].insert_one(trade)
    except DuplicateKeyError as exc:
        raise desk.DeskInputError("duplicate_open_trade") from exc
    return trade


async def _reject_by_desk(uid: str, ticket: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Record a ticket the desk's validator refused, so no ticket is left in the transient "confirmed" state with no
    paper trade behind it. Returns the change, which the caller also applies to its copy."""
    logger.error("ai_trader: ticket %s could not be turned into a paper trade: %s", ticket["_id"], code)
    stamp = desk.utcnow().isoformat()
    change = {"status": "rejected", "governor_cleared": False, "rejected_by": "desk", "reject_reason": code,
              "rejected_at": stamp, "updated_at": stamp}
    await db[execution.TICKETS].update_one({"_id": ticket["_id"], "user_id": uid, "status": "confirmed"},
                                           {"$set": change})
    return change


@router.get("/tickets")
async def list_tickets(status: Optional[str] = Query(None), strategy_id: Optional[str] = Query(None),
                       user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Your tickets, newest first. An assisted ticket whose session has passed is marked expired on this read, the
    way the desk applies its exit rule on a read."""
    uid = user["user_id"]
    if status is not None and status not in execution.TICKET_STATUSES:
        raise HTTPException(status_code=422, detail="invalid_status")
    query: Dict[str, Any] = {"user_id": uid}
    if strategy_id is not None:
        query["strategy_id"] = strategy_id
    await _ensure_indexes()
    docs = await db[execution.TICKETS].find(query).sort("created_at", -1).to_list(MAX_TICKETS_LISTED)
    docs = [await _expire_if_due(d) for d in docs]
    tickets = [_public_ticket(d) for d in docs if status is None or d["status"] == status]
    return {"status": status, "strategy_id": strategy_id, "statuses": list(execution.TICKET_STATUSES),
            "tickets": tickets, "orders": ORDERS_NOTE}


async def _expire_if_due(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Mark an unanswered assisted ticket expired once its session has passed (PRD F5.1). The status is part of the
    filter, so running this twice, or in two tabs, writes once."""
    if ticket.get("status") != "awaiting_confirmation" or not execution.is_expired(ticket):
        return ticket
    change = {"status": "expired", "updated_at": desk.utcnow().isoformat()}
    await db[execution.TICKETS].update_one(
        {"_id": ticket["_id"], "user_id": ticket["user_id"], "status": "awaiting_confirmation"}, {"$set": change})
    return {**ticket, **change}


@router.post("/tickets/{ticket_id}/confirm")
async def confirm_ticket(ticket_id: str, request: Request, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Confirm an assisted ticket (PRD F5.2). The universal risk service (the governor among its checks) re-judges it
    against the book as it stands now, not as it was when the ticket was made; only then is a paper-shadow trade
    recorded and the copy-ready order returned. Nothing is sent to a broker, whatever the answer."""
    uid = user["user_id"]
    ticket = await _expire_if_due(await _own_ticket(uid, ticket_id))
    if ticket["status"] == "expired":
        raise HTTPException(status_code=409, detail="ticket_expired")
    if ticket["status"] != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    doc = await _own_strategy(uid, ticket["strategy_id"])
    approved_at_signal = int(ticket["quantity"])
    # The risk service re-judges the ticket against the account's book as it stands NOW, starting from the size approved
    # on the signal date: it can lower the size or refuse, never raise it (PRD F5.2). Recorded by the service; the
    # reservation is taken under the decision's id before the ticket is claimed.
    trade_id = str(uuid.uuid4())
    cid = risk_gate.correlation_id(request)
    try:
        verdict = await risk_service.enter(db, _entry(
            user, cid, uid, path="ai_trader_confirm", mode=ticket.get("mode") or "assisted", symbol=ticket["symbol"],
            quantity=approved_at_signal, entry=float(ticket["entry_price"]),
            stop=float(ticket["stop_price"]) if ticket.get("stop_price") is not None else None,
            target=float(ticket["target_price"]) if ticket.get("target_price") is not None else None,
            trade_id=trade_id), reserve=True, accept_reduce=True)
    except risk_service.DecisionUnrecorded:
        raise risk_service.unrecorded(cid)
    decision = _governor_decision(verdict)
    stamp = desk.utcnow().isoformat()
    if verdict["outcome"] == "block" or decision.approved_qty < 1:
        # The ticket stays open until its session ends: the book may free up before then. The refusal is recorded.
        await risk_service.release_unused(db, uid, verdict, reason="refused at confirm")
        change = {"last_decision": decision.to_dict(), "last_decision_at": stamp, "updated_at": stamp,
                  "last_risk_decision_id": verdict["decision_id"]}
        await db[execution.TICKETS].update_one({"_id": ticket_id, "user_id": uid}, {"$set": change})
        raise HTTPException(status_code=409, detail={"code": "risk_refused", "decision": decision.to_dict(),
                                                    "reason_codes": [r.code for r in decision.reasons],
                                                    "risk": risk_service.public(verdict)})
    risk = _risk_ids(verdict)

    # Claim the ticket before anything is recorded, with the status in the filter: two confirms racing leave one
    # shadow trade, not two.
    claim = {"status": "confirmed", "quantity": decision.approved_qty, "decision": decision.to_dict(),
             "reason_codes": [r.code for r in decision.reasons], "last_decision": decision.to_dict(),
             "last_decision_at": stamp, "updated_at": stamp, **(risk or {})}
    res = await db[execution.TICKETS].update_one(
        {"_id": ticket_id, "user_id": uid, "status": "awaiting_confirmation"}, {"$set": claim})
    if not res.matched_count:
        await risk_service.release_unused(db, uid, verdict, reason="ticket claimed by another confirm")
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    confirmed = {**ticket, **claim}
    try:
        trade = await _open_paper_trade(uid, confirmed, doc, verdict, trade_id)
    except Exception as exc:  # noqa: BLE001 — the claim is released whatever went wrong, then the error stands
        await risk_service.release_unused(db, uid, verdict, reason="paper trade not written at confirm")
        # "confirmed" is a transient status no route can answer, so a failed write must not leave the ticket in it:
        # put it back to awaiting_confirmation with the size the governor approved on the signal date, where it can
        # be confirmed again or expire with its session.
        await db[execution.TICKETS].update_one(
            {"_id": ticket_id, "user_id": uid, "status": "confirmed"},
            {"$set": {"status": "awaiting_confirmation", "quantity": approved_at_signal,
                      "updated_at": desk.utcnow().isoformat()}})
        if isinstance(exc, desk.DeskInputError):
            raise HTTPException(status_code=422, detail=exc.code)
        raise
    executed = execution.mark_executed(confirmed, trade)
    confirmed.update(executed)
    await db[execution.TICKETS].update_one({"_id": ticket_id, "user_id": uid, "status": "confirmed"},
                                           {"$set": executed})
    logger.info("ai_trader: user %s confirmed ticket %s (%s x%s) as paper shadow trade %s", uid, ticket_id,
                confirmed["symbol"], confirmed["quantity"], trade["_id"])
    return {"ticket": _public_ticket(confirmed), "trade": desk.public_trade(trade),
            "text": execution.ticket_text(confirmed), "orders": ORDERS_NOTE}


class RejectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: Optional[str] = Field(None, max_length=REASON_MAX)


@router.post("/tickets/{ticket_id}/reject")
async def reject_ticket(ticket_id: str, body: Optional[RejectBody] = None,
                        user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Turn an assisted ticket down and record why (PRD F5.2)."""
    uid = user["user_id"]
    ticket = await _expire_if_due(await _own_ticket(uid, ticket_id))
    if ticket["status"] == "expired":
        raise HTTPException(status_code=409, detail="ticket_expired")
    if ticket["status"] != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    reason = (body.reason.strip() if body and body.reason else None) or None
    stamp = desk.utcnow().isoformat()
    change = {"status": "rejected", "rejected_by": "user", "reject_reason": reason, "rejected_at": stamp,
              "updated_at": stamp}
    res = await db[execution.TICKETS].update_one(
        {"_id": ticket_id, "user_id": uid, "status": "awaiting_confirmation"}, {"$set": change})
    if not res.matched_count:
        # A confirm that landed between the read and this write has the ticket; saying "rejected" would be a status
        # the database does not hold.
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    return {"ticket": _public_ticket({**ticket, **change})}


@router.get("/strategies/{strategy_id}/journal")
async def strategy_journal(strategy_id: str, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """The outcome journal of one strategy (PRD F5.4): every closed shadow trade scored against the confidence the
    strategy stated when the ticket was made, plus the paper tally the paper-to-assisted gate reads. Read-only."""
    uid = user["user_id"]
    doc = await _own_strategy(uid, strategy_id)
    tickets, closed = await _strategy_record(uid, strategy_id)
    try:
        report = calibration_report(execution.outcome_pairs(tickets, closed))
    except CalibrationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    counts: Dict[str, int] = {s: 0 for s in execution.TICKET_STATUSES}
    for t in tickets:
        if t.get("status") in counts:
            counts[t["status"]] += 1
    return {
        "strategy_id": strategy_id,
        "strategy_version": doc.get("version"),
        "stage": doc.get("stage"),
        "calibration": report,
        "paper_stats": execution.paper_stats(closed),
        "tickets": counts,
        "confidence_basis": "the strategy's own win rate (paper first, else its latest backtest); tickets without "
                            "one are left out of the report rather than scored against a guess",
        "orders": ORDERS_NOTE,
    }
