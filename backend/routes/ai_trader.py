"""AI Trader, Phase 1: read-only evidence endpoints (docs/prd/AI_TRADER_PHASE1.prd.md). Nothing here places an order.

Endpoints (all under /api/ai-trader, signed-in users only):
    GET  /evidence?symbol=&as_of=YYYY-MM-DD   — {as_of, symbol, evidence: [Evidence], notes}: market regime, trend, VIX,
                                                breadth, the sector rotation table and (with `symbol`) the daily/weekly/
                                                monthly trend and any timeframe conflicts. Each item is an Evidence
                                                record or UNAVAILABLE with a reason_code; a value is never filled in.
    POST /calibration  {predictions: [{confidence, hit}]}
                                              — reliability bins, Brier score and calibration error.
    POST /pattern-validation {events: [{symbol, signal_date, direction?, regime?}], horizon_sessions?}
                                              — hit rate, shrunk hit rate and expectancy net of costs (long only).

Errors: 422 on a missing/invalid as_of or body; 404 `unknown_symbol` when the bars source is present but the symbol is
not in it; 503 `research_engine_unavailable` when the research package cannot be imported. When the bars source itself
is missing the symbol-level items are returned UNAVAILABLE (BARS_SOURCE_MISSING) and `notes` says so.
"""
from __future__ import annotations

import asyncio
import re
from datetime import date
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_current_user
from services.ai_trader import _research
from services.ai_trader.calibration import CalibrationError, calibration_report
from services.ai_trader.context import market_context
from services.ai_trader.evidence import unavailable
from services.ai_trader.sector import sector_rotation
from services.ai_trader.timeframes import timeframe_evidence
from services.ai_trader.validation import evaluate_events

router = APIRouter(prefix="/api/ai-trader", tags=["ai-trader"])

_SYMBOL = re.compile(r"^[A-Za-z0-9&_-]{1,20}$")
MAX_EVENTS = 500
MAX_PREDICTIONS = 100_000


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
