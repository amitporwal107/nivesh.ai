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
from services import trade_lifecycle as lifecycle
from services import paper_account as pacct
from services import risk_equity as req
from services import pg_client
from services.ai_trader import _research, execution, strategy
from services.ai_trader.calibration import CalibrationError, calibration_report
from services.ai_trader.config import ConfigValidationError
from services.ai_trader.context import market_context
from services.ai_trader.evidence import unavailable
from services.ai_trader.risk_governor import (DEFAULT_LIMITS, Intent, Market, Portfolio, Position, Reason, evaluate)
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


async def _portfolio(uid: str, capital: float) -> Portfolio:
    """The book the governor judges an intent against: the capital the strategy's config was resolved with, the
    user's open cash paper trades as positions, and today's realised P&L.

    The desk stores no sector on a trade, so the sector of a position is read back from the ticket that opened it.
    A position with no ticket (a trade the user opened by hand on the desk) carries no sector, and the governor then
    counts its value against the sector allowance and reports it as SECTOR_EXPOSURE_UNKNOWN rather than measuring the
    unknown part as zero. The desk keeps no equity curve either, so drawdown is None and the governor says the
    drawdown halt could not be checked."""
    open_docs = await db[desk.TRADES].find({"user_id": uid, "status": "open"}) \
        .to_list(desk.MAX_OPEN_TRADES * 2)
    tickets = await db[execution.TICKETS].find({"user_id": uid}).to_list(MAX_TICKETS_LISTED)
    sector_of = {t["trade_id"]: t.get("sector") for t in tickets if t.get("trade_id")}
    # Cash trades carry a quantity and an entry price; a multi-leg strategy (kind="strategy") carries legs
    # instead, so it is measured once as an upper bound on its loss (desk_strategy_trades.exposure_rs) and
    # entered as a single unit. Strategies used to be filtered out of this list entirely, which meant every
    # F&O position was invisible to the governor: the position count, the duplicate-symbol check and the
    # exposure sum all ran against a book that excluded the most leveraged thing the desk can open.
    positions: List[Position] = []
    for d in open_docs:
        kind = d.get("kind")
        if kind in (None, "cash"):
            positions.append(Position(symbol=d["symbol"], quantity=int(d["quantity"]),
                                      price=float(d["entry_price"]), sector=sector_of.get(d["_id"])))
            continue
        if kind == desk_strategy.KIND:
            value = desk_strategy.exposure_rs(d)
            if value is None:
                # A leg is missing a field the bound needs. Counting it as zero would hide it, so it is
                # entered at the whole capital: the governor then refuses to add risk rather than
                # measuring an unknown position as harmless.
                logger.warning("ai_trader risk book: strategy %s has no computable exposure; counting it "
                               "against the full capital", d.get("_id"))
                value = capital
            positions.append(Position(symbol=d.get("underlying") or d.get("symbol"), quantity=1,
                                      price=float(value), sector=sector_of.get(d["_id"])))
    today = _today_ist()
    realized = 0.0
    for d in await _closed_trades(uid):
        pnl = d.get("realized_pnl_rs")
        if pnl is None or not d.get("closed_at"):
            continue
        if desk.ist_date(d["closed_at"]) == today:
            realized += float(pnl)
    # The governor has enforced `kill_switch` and `halted` since it was written
    # (risk_governor.py:112-115) and this call never passed them, so they held their dataclass
    # defaults of False on every evaluation: the enforcement was correct and could never fire.
    # They now carry the user's stored controls. `drawdown_pct` is still None and still honestly
    # reported as DRAWDOWN_UNKNOWN — the desk keeps no equity curve to measure a drawdown against,
    # and a threshold that cannot be computed must not be presented as enforced.
    controls = await rc.read(db, uid)
    equity = await _equity(uid, capital, open_docs)
    return Portfolio(capital=capital, positions=positions, realized_pnl_today=round(realized, 2),
                     drawdown_pct=equity.get("drawdown_pct"),
                     kill_switch=bool(controls.get("kill_switch")),
                     halted=bool(controls.get("halted")))


async def _equity(uid: str, capital: float, open_docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Equity, its high-water mark and the drawdown, for the governor's DRAWDOWN_HALT.

    Marks the open cash positions at their last close and reuses desk_trading's own `summarize`, so
    realised and unrealised P&L have ONE definition in the product. It deliberately does NOT call
    `apply_trade_exits`: that writes exits, and a risk read must not close a position as a side
    effect of being asked a question.

    An open STRATEGY (multi-leg F&O) position is counted as unmarked, which makes equity and the
    drawdown unknown rather than wrong: those positions are marked by a different path
    (desk_strategy_trades.apply_exits) that also writes. Named here as a gap instead of being
    silently valued at zero.
    """
    cash_open = [d for d in open_docs if d.get("kind") in (None, "cash")]
    strategy_open = len(open_docs) - len(cash_open)
    try:
        starts = desk.fetch_starts(cash_open, "opened_at")
        bars, errors = await desk.fetch_bars_many(starts) if starts else ({}, {})
        public = [desk.public_trade(d, *desk.mark_for(d["symbol"], bars, errors)) for d in cash_open]
        public += [desk.public_trade(d) for d in await _closed_trades(uid)]
        summary = dict(desk.summarize(public, partial=False))
    except Exception as e:  # noqa: BLE001 — an unreadable mark leaves the drawdown unknown, not zero
        logger.warning("ai_trader: equity could not be computed for %s (%s)", uid, type(e).__name__)
        return {"drawdown_pct": None, "equity": None,
                "unknown_reason": f"the marks could not be read ({type(e).__name__})"}
    summary["unmarked_open"] = int(summary.get("unmarked_open") or 0) + strategy_open
    return await req.snapshot(db, uid, capital, summary)


def _market(as_of: str) -> Market:
    """India VIX and the market regime for one date, from the Phase 1 evidence. An UNAVAILABLE item leaves the value
    unknown: the governor then names the rule it skipped instead of treating the unknown as calm."""
    try:
        items = market_context(as_of)
    except _research.ResearchUnavailable as exc:
        logger.warning("ai_trader: no market context for %s: %s", as_of, exc)
        return Market()
    vix: Optional[float] = None
    regime: Optional[str] = None
    for item in items:
        if item.status != "OK":
            continue
        data = item.data or {}
        label = data.get("regime")
        if isinstance(label, dict) and label.get("status") == "OK" \
                and label.get("value") in ("BULL", "BEAR", "SIDEWAYS"):
            regime = label["value"]
        if isinstance(data.get("india_vix"), (int, float)) and not isinstance(data.get("india_vix"), bool):
            vix = float(data["india_vix"])
    return Market(vix=vix, regime=regime)


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
    try:
        intents = execution.intents_from_candidates(spec, config, candidates, as_of=body.as_of)
    except execution.ExecutionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # The F&O risk gate, when on for this user, judges every new intent that could open a position BEFORE
    # anything is written (the book read below can write the equity high-water mark): one block refuses the
    # whole run with 409, so a run never stops half-written. It is in addition to the governor, which still
    # sizes and judges each intent below; the gate sees the size asked for, never less than the governor's.
    risk_ids: Dict[str, Dict[str, str]] = {}
    if await risk_gate.enabled_for(db, user):
        cid = risk_gate.correlation_id(request)
        for intent in intents:
            if intent.symbol in seen or intent.symbol in risk_ids or intent.quantity < 1:
                continue
            decision = await risk_gate.enforce(db, risk_gate.cash_request(
                user, cid, path="ai_trader_signal", mode=body.mode, action="open", symbol=intent.symbol,
                quantity=intent.quantity, capital_at_risk_rs=intent.quantity * intent.entry_price))
            risk_ids[intent.symbol] = {"correlation_id": decision.correlation_id,
                                       "risk_decision_id": decision.decision_id}

    market = await asyncio.to_thread(_market, signal_date)
    portfolio = await _portfolio(uid, float(config["initial_capital"]))
    made: List[Dict[str, Any]] = []
    for intent in intents:
        if intent.symbol in seen:
            continue
        seen.add(intent.symbol)
        decision = evaluate(intent, portfolio, market, DEFAULT_LIMITS)
        # The decision used to live only on the ticket document, which is mutable and overwritten in
        # place; it could not be reconstructed or proved afterwards. This is the append-only record.
        await rc.record_decision(
            db, uid, action="ai_trader_ticket",
            outcome="allowed" if decision.approved_qty > 0 else "refused",
            symbol=intent.symbol, requested_qty=decision.requested_qty,
            approved_qty=decision.approved_qty,
            reasons=[dataclasses.asdict(r) for r in decision.reasons],
            limits_version=decision.limits_version, correlation_id=strategy_id,
            detail={"as_of": signal_date, "mode": body.mode})
        ticket = execution.new_ticket(uid, doc, intent, decision, as_of=signal_date, mode=body.mode)
        ticket.update(risk_ids.get(intent.symbol, {}))
        try:
            # The ticket is written before any trade, so a request that lost the race opens nothing.
            await db[execution.TICKETS].insert_one(ticket)
        except DuplicateKeyError:
            logger.info("ai_trader: %s already has a ticket for %s on %s", strategy_id, intent.symbol, signal_date)
            continue
        if ticket["governor_cleared"] and body.mode == "paper":
            try:
                trade = await _open_paper_trade(uid, ticket, doc, risk_ids.get(intent.symbol))
            except desk.DeskInputError as exc:
                # The desk refused the order, so this ticket is finished: recorded with the reason instead of left in
                # the transient "confirmed" state, and the loop goes on so the reply names every ticket written.
                ticket.update(await _reject_by_desk(uid, ticket, exc.code))
                made.append(ticket)
                continue
            change = execution.mark_executed(ticket, trade)
            upd, after = _ticket_change(ticket, lifecycle.OPEN, change, reason=f"Paper trade {trade['_id']} recorded.",
                                        actor="ai_trader", fill_price=trade.get("entry_price"))
            await db[execution.TICKETS].update_one({"_id": ticket["_id"], "user_id": uid, "status": "confirmed"}, upd)
            ticket.update(after)
            # The book the next intent is judged against includes the position just opened, with the sector the
            # ticket already carries, so the governor's sector limit sees it.
            portfolio = Portfolio(capital=portfolio.capital,
                                  positions=list(portfolio.positions) + [Position(
                                      symbol=ticket["symbol"], quantity=ticket["quantity"],
                                      price=ticket["entry_price"], sector=ticket.get("sector"))],
                                  realized_pnl_today=portfolio.realized_pnl_today,
                                  drawdown_pct=portfolio.drawdown_pct, kill_switch=portfolio.kill_switch,
                                  halted=portfolio.halted)
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


def _ticket_change(ticket: Dict[str, Any], to: str, change: Dict[str, Any], *, reason: str, actor: Optional[str] = None,
                   **fields: Any) -> tuple:
    """(the Mongo update, the ticket as it will stand) for a status change that is also a lifecycle transition
    (Phase 2.2): the event goes in the SAME update as the status; the caller's filter on the prior status pins it."""
    at = change.get("updated_at") or desk.utcnow().isoformat()
    events = lifecycle.ticket_step(ticket, to, at=at, reason=reason, actor=actor, **fields)
    after = {**ticket, **change}
    if events:
        after.update(state=events[-1]["to"], transitions=list(ticket.get("transitions") or []) + events)
    return lifecycle.update_for(events, change), after


async def _open_paper_trade(uid: str, ticket: Dict[str, Any], strategy_doc: Dict[str, Any],
                            risk: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """The paper trade a cleared ticket opens, through the desk's own validator so the document is a real desk trade
    (PRD F4.2). In assisted mode this is the shadow of the order the user places at their broker.

    A `desk.DeskInputError` is left to the caller: it is one ticket the desk will not take, and only the caller knows
    whether a ticket it had already claimed has to be released first. `risk` carries the F&O risk gate's
    correlation_id and risk_decision_id when the gate judged this trade."""
    rationale = (f"AI Trader {ticket['mode']} signal from {strategy_doc.get('name') or 'a strategy'} "
                 f"({strategy_doc.get('version')}) on {ticket['signal_date']}; risk governor "
                 f"{(ticket.get('decision') or {}).get('action')}.")
    # The strategy's own exits (time in sessions, the ATR trail) travel with the paper trade (N15).
    trade = desk.new_trade(uid, execution.trade_body(ticket, rationale=rationale[:desk.NOTE_MAX],
                                                     exit_spec=(strategy_doc.get("spec") or {}).get("exit")))
    trade.update(risk or {})
    # This path inserts into desk.TRADES directly rather than through POST /api/desk/paper-trades, so
    # it has to charge the paper account itself. Without this the AI trader could open positions the
    # account never funded while the desk route was constrained — the same "governed on one path only"
    # shape the risk work has been closing (docs/RISK_CONTROL_INVENTORY.md).
    need = pacct.reservation_for(trade, None)
    try:
        trade["paper_reserved_rs"] = await pacct.reserve(db, uid, need, trade_id=trade["_id"],
                                                         symbol=trade.get("symbol"))
    except pacct.InsufficientFunds as short:
        raise desk.DeskInputError("insufficient_paper_funds") from short
    trade["ticket_id"] = ticket["_id"]                  # candidate (ticket) → position, linked by a stable id
    desk.open_lifecycle(trade)
    await db[desk.TRADES].insert_one(trade)
    return trade


async def _reject_by_desk(uid: str, ticket: Dict[str, Any], code: str) -> Dict[str, Any]:
    """Record a ticket the desk's validator refused, so no ticket is left in the transient "confirmed" state with no
    paper trade behind it. Returns the change, which the caller also applies to its copy."""
    logger.error("ai_trader: ticket %s could not be turned into a paper trade: %s", ticket["_id"], code)
    stamp = desk.utcnow().isoformat()
    change = {"status": "rejected", "governor_cleared": False, "rejected_by": "desk", "reject_reason": code,
              "rejected_at": stamp, "updated_at": stamp}
    upd, after = _ticket_change(ticket, lifecycle.REJECTED, change, reason=f"The desk refused the paper trade ({code}).",
                                actor="desk", rejection_reasons=[code])
    await db[execution.TICKETS].update_one({"_id": ticket["_id"], "user_id": uid, "status": "confirmed"}, upd)
    return {k: after[k] for k in after if k in change or k in ("state", "transitions")}


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
    upd, after = _ticket_change(ticket, lifecycle.REJECTED, change, reason="Expired: not confirmed in its session.",
                                actor="ai_trader", rejection_reasons=["expired"])
    await db[execution.TICKETS].update_one(
        {"_id": ticket["_id"], "user_id": ticket["user_id"], "status": "awaiting_confirmation"}, upd)
    return after


@router.post("/tickets/{ticket_id}/confirm")
async def confirm_ticket(ticket_id: str, request: Request, user: dict = Depends(get_current_user)) -> Dict[str, Any]:
    """Confirm an assisted ticket (PRD F5.2). The governor is re-run against the book as it stands now, not as it was
    when the ticket was made; only then is a paper-shadow trade recorded and the copy-ready order returned. Nothing
    is sent to a broker, whatever the answer."""
    uid = user["user_id"]
    ticket = await _expire_if_due(await _own_ticket(uid, ticket_id))
    if ticket["status"] == "expired":
        raise HTTPException(status_code=409, detail="ticket_expired")
    if ticket["status"] != "awaiting_confirmation":
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    doc = await _own_strategy(uid, ticket["strategy_id"])
    capital = float((doc.get("config") or {}).get("initial_capital") or 0)

    intent = Intent(symbol=ticket["symbol"], quantity=int(ticket["requested_quantity"]),
                    entry_price=float(ticket["entry_price"]), stop_price=float(ticket["stop_price"]),
                    target_price=float(ticket["target_price"]) if ticket.get("target_price") is not None else None,
                    sector=ticket.get("sector"), avg_daily_value=ticket.get("avg_daily_value"))
    market = await asyncio.to_thread(_market, _today_ist().isoformat())
    decision = evaluate(intent, await _portfolio(uid, capital), market, DEFAULT_LIMITS)
    approved_at_signal = int(ticket["quantity"])
    if decision.approved_qty > approved_at_signal:
        # The re-run is here to make the decision worse if the book or the market got worse, never better (PRD F5.2).
        # It starts from the size the strategy asked for, so a rule that cut the size on the signal date and cannot
        # be checked today (no VIX row yet, no regime) would otherwise hand those shares back.
        decision = dataclasses.replace(
            decision, action="reduce", approved_qty=approved_at_signal,
            reasons=list(decision.reasons) + [Reason(
                "SIZE_CAPPED_AT_SIGNAL", "Size is held at the quantity the governor approved on the signal date.",
                "reduce", approved_at_signal)])
    stamp = desk.utcnow().isoformat()
    # Recorded AFTER the re-run adjustment, so the figure on record is the one actually used, not the
    # raw evaluation the cap may have overridden.
    await rc.record_decision(
        db, uid, action="ai_trader_confirm",
        outcome="allowed" if (decision.action in execution.ACTIONABLE and decision.approved_qty >= 1) else "refused",
        symbol=ticket.get("symbol"), requested_qty=decision.requested_qty,
        approved_qty=decision.approved_qty,
        reasons=[dataclasses.asdict(r) for r in decision.reasons],
        limits_version=decision.limits_version, correlation_id=ticket_id,
        detail={"approved_at_signal": approved_at_signal})
    if decision.action not in execution.ACTIONABLE or decision.approved_qty < 1:
        # The ticket stays open until its session ends: the book may free up before then. The refusal is recorded.
        change = {"last_decision": decision.to_dict(), "last_decision_at": stamp, "updated_at": stamp}
        await db[execution.TICKETS].update_one({"_id": ticket_id, "user_id": uid}, {"$set": change})
        raise HTTPException(status_code=409, detail={"code": "risk_refused", "decision": decision.to_dict(),
                                                    "reason_codes": [r.code for r in decision.reasons]})

    # The F&O risk gate, when on, judges the size the governor now approves; a block leaves the ticket waiting.
    risk: Optional[Dict[str, str]] = None
    if await risk_gate.enabled_for(db, user):
        verdict = await risk_gate.enforce(db, risk_gate.cash_request(
            user, risk_gate.correlation_id(request), path="ai_trader_confirm", mode=ticket.get("mode") or "assisted",
            action="open", symbol=ticket["symbol"], quantity=decision.approved_qty,
            capital_at_risk_rs=decision.approved_qty * float(ticket["entry_price"])))
        risk = {"correlation_id": verdict.correlation_id, "risk_decision_id": verdict.decision_id}

    # Claim the ticket before anything is recorded, with the status in the filter: two confirms racing leave one
    # shadow trade, not two.
    claim = {"status": "confirmed", "quantity": decision.approved_qty, "decision": decision.to_dict(),
             "reason_codes": [r.code for r in decision.reasons], "last_decision": decision.to_dict(),
             "last_decision_at": stamp, "updated_at": stamp, **(risk or {})}
    claim_upd, confirmed = _ticket_change(ticket, lifecycle.TRIGGERED, claim, reason="Confirmed by you; the governor re-ran.",
                                          actor=uid, risk_decision_id=(risk or {}).get("risk_decision_id"))
    res = await db[execution.TICKETS].update_one(
        {"_id": ticket_id, "user_id": uid, "status": "awaiting_confirmation"}, claim_upd)
    if not res.matched_count:
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    try:
        trade = await _open_paper_trade(uid, confirmed, doc, risk)
    except Exception as exc:  # noqa: BLE001 — the claim is released whatever went wrong, then the error stands
        # "confirmed" is a transient status no route can answer, so a failed write must not leave the ticket in it:
        # put it back to awaiting_confirmation with the size the governor approved on the signal date, where it can
        # be confirmed again or expire with its session.
        release_upd, _ = _ticket_change(confirmed, lifecycle.ELIGIBLE,
                                        {"status": "awaiting_confirmation", "quantity": approved_at_signal,
                                         "updated_at": desk.utcnow().isoformat()},
                                        reason=f"The paper trade could not be recorded ({type(exc).__name__}); the claim is released.",
                                        actor="ai_trader")
        await db[execution.TICKETS].update_one({"_id": ticket_id, "user_id": uid, "status": "confirmed"}, release_upd)
        if isinstance(exc, desk.DeskInputError):
            raise HTTPException(status_code=422, detail=exc.code)
        raise
    executed = execution.mark_executed(confirmed, trade)
    exec_upd, after = _ticket_change(confirmed, lifecycle.OPEN, executed, reason=f"Paper shadow trade {trade['_id']} recorded.",
                                     actor=uid, fill_price=trade.get("entry_price"))
    confirmed.update(after)
    await db[execution.TICKETS].update_one({"_id": ticket_id, "user_id": uid, "status": "confirmed"}, exec_upd)
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
    upd, after = _ticket_change(ticket, lifecycle.REJECTED, change, reason="Turned down by you.", actor=uid,
                                rejection_reasons=[reason] if reason else ["user_rejected"])
    res = await db[execution.TICKETS].update_one(
        {"_id": ticket_id, "user_id": uid, "status": "awaiting_confirmation"}, upd)
    if not res.matched_count:
        # A confirm that landed between the read and this write has the ticket; saying "rejected" would be a status
        # the database does not hold.
        raise HTTPException(status_code=409, detail="ticket_not_awaiting_confirmation")
    return {"ticket": _public_ticket(after)}


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
