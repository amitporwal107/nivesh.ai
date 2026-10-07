"""Read-only chart API over the committed snapshot (research/charting/export.py WRITES it,
services/research_chart.py READS + validates it).

    GET /api/research/chart/run                                manifest, minus per-file integrity hashes
    GET /api/research/chart/symbols                             manifest.symbols
    GET /api/research/chart/{symbol}/ohlcv?timeframe=1D|1W|1M    bars, statuses, findings, provenance
    GET /api/research/chart/{symbol}/indicators?timeframe=&ids=  one or more indicator series
    GET /api/research/chart/{symbol}/patterns                   detected patterns (v1: always [], daily only)

Nothing is computed at request time -- no DB, no network, no other file (the Sim Lab rule,
backend/routes/sim_lab.py). Kite-derived prices (NI-1): gated behind require_feature("charting"),
admins included, same posture as sim_lab. Symbol path params are validated
`^[A-Z0-9&\\-]{1,32}$` before any file is touched. A malformed or missing snapshot is 503
snapshot_unavailable, never a partial response; a symbol the manifest never listed is 404
unknown_symbol.

`timeframe` (§38.7, §38.11): one of `1D` (default -- existing callers that never pass this
param are unaffected), `1W`, `1M`. Weekly/monthly bars are resampled and hashed into the
snapshot at export time (research/charting/resample.py); this route never resamples. An unknown
timeframe is 400 `unknown_timeframe: <value>` (§27, same reason-code style as `unknown_indicator`).
Patterns stay daily-only (§38.7) -- /patterns has no `timeframe` param.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import Path as PathParam

from feature_gate import require_feature
from services.research_chart import (
    TIMEFRAMES, catalogue_view, indicators_view, load_manifest, load_symbol, manifest_view, ohlcv_view,
    patterns_view,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research/chart", tags=["research_chart"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
SymbolPath = PathParam(..., pattern=SYMBOL_PATTERN)


def _timeframe(timeframe: str) -> str:
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"unknown_timeframe: {timeframe}")
    return timeframe


def _manifest() -> dict:
    manifest = load_manifest()
    if manifest is None:
        raise HTTPException(status_code=503, detail="snapshot_unavailable")
    return manifest


def _manifest_and_symbol(symbol: str) -> dict:
    manifest = _manifest()
    for e in manifest["symbols"]:
        if e["symbol"] == symbol:
            return manifest
    raise HTTPException(status_code=404, detail="unknown_symbol")


def _payload(symbol: str) -> dict:
    """The symbol's own file must load and validate cleanly too -- a symbol the manifest DOES
    list but whose file is missing/corrupt/hash-mismatched is a snapshot-integrity problem, so
    it's 503 (never a partial response), not a 404 (that's reserved for a symbol the manifest
    never listed at all)."""
    payload = load_symbol(symbol)
    if payload is None:
        raise HTTPException(status_code=503, detail="snapshot_unavailable")
    return payload


@router.get("/run")
async def run(user: dict = Depends(require_feature(FLAG))):
    return manifest_view(_manifest())


@router.get("/catalogue")
async def catalogue(user: dict = Depends(require_feature(FLAG))):
    """The controlled indicator preset catalogue (§38.5, D-3) that this snapshot's series were built
    from. Read straight off the manifest -- nothing is computed here, same as every other route."""
    view = catalogue_view(_manifest())
    if view is None:
        raise HTTPException(status_code=503, detail="catalogue_unavailable")
    return view


@router.get("/symbols")
async def symbols(user: dict = Depends(require_feature(FLAG))):
    return {"symbols": _manifest()["symbols"]}


@router.get("/{symbol}/ohlcv")
async def ohlcv(symbol: str = SymbolPath, timeframe: str = Query("1D"),
                user: dict = Depends(require_feature(FLAG))):
    tf = _timeframe(timeframe)
    manifest = _manifest_and_symbol(symbol)
    return ohlcv_view(manifest, _payload(symbol), tf)


@router.get("/{symbol}/indicators")
async def indicators(symbol: str = SymbolPath, timeframe: str = Query("1D"), ids: Optional[str] = Query(None),
                     user: dict = Depends(require_feature(FLAG))):
    tf = _timeframe(timeframe)
    _manifest_and_symbol(symbol)
    payload = _payload(symbol)
    available = indicators_view(payload, None, tf)["indicators"]
    wanted = [i.strip() for i in ids.split(",") if i.strip()] if ids else None
    if wanted:
        unknown = [i for i in wanted if i not in available]
        if unknown:
            raise HTTPException(status_code=400, detail=f"unknown_indicator: {', '.join(unknown)}")
    return indicators_view(payload, wanted, tf)


@router.get("/{symbol}/patterns")
async def patterns(symbol: str = SymbolPath, user: dict = Depends(require_feature(FLAG))):
    _manifest_and_symbol(symbol)
    return patterns_view(_payload(symbol))
