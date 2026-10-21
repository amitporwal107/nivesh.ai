"""Research → data providers (docs/charting.md §32.13, Phase A endpoints only).

    GET  /api/research/providers                              the providers and what each is used for
    GET  /api/research/providers/health                       configured / reachable / auth state
    POST /api/research/providers/kite/sync-instruments        Kite instrument master
    POST /api/research/providers/kite/fetch-candles           Kite historical candles, chunked
    POST /api/research/providers/trendlyne/search-entity      resolve a name/symbol to identifiers
    POST /api/research/providers/trendlyne/search-parameters  resolve a metric name to a parameter token
    POST /api/research/providers/trendlyne/fetch-parameters   parameter values for up to 10 stocks
    POST /api/research/providers/trendlyne/fetch-events       corporate events for one stock
    POST /api/research/providers/trendlyne/search-documents   filings / reports semantic search

Not built here (Phases B-D): reconcile, provenance lookup, PIT validation.

Research/data-service only — nothing here places an order. Provider data is internal-use and not
redistributable, so every route sits behind the allowlist-only `charting` flag (same posture as
research_chart.py). Every call, success or failure, is written to the provider request log before
the response is returned; a provider failure is an HTTP error carrying `error_code`, `retryable`
and the `request_id` of its log entry — never a 200 with empty data.
"""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any, Awaitable, Callable, Dict, List, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from deps import db
from feature_gate import require_feature
from services.providers import contract as c
from services.providers import request_log
from services.providers.kite_adapter import EXCHANGES, KiteMarketDataAdapter, default_token
from services.providers.trendlyne_adapter import (
    ENTITY_TYPES, MAX_PARAMETERS, MAX_STOCK_CODES, READ_TOOLS, TrendlyneResearchAdapter, default_url,
)

router = APIRouter(prefix="/api/research/providers", tags=["research_providers"])
FLAG = "charting"

SYMBOL_PATTERN = r"^[A-Z0-9&\-]{1,32}$"
STOCK_CODE_PATTERN = r"^[A-Za-z0-9&\-]{1,32}$"
INSTRUMENT_PREVIEW = 20       # sync-instruments answers with counts + a preview, not ~9k rows

_HTTP_STATUS = {
    c.INVALID_REQUEST: 400, c.IDENTIFIER_NOT_RESOLVED: 404, c.RATE_LIMITED: 429,
    c.NOT_CONFIGURED: 503, c.AUTH_EXPIRED: 503, c.PROVIDER_UNAVAILABLE: 503,
    c.TOOL_SCHEMA_CHANGED: 502, c.INVALID_PAYLOAD: 502, c.EMPTY_RESPONSE: 502, c.PROVIDER_ERROR: 502,
}


def _kite() -> KiteMarketDataAdapter:
    return KiteMarketDataAdapter()


def _trendlyne() -> TrendlyneResearchAdapter:
    return TrendlyneResearchAdapter()


async def _run(provider_id: str, operation: str, params: Dict[str, Any], user: dict,
               call: Callable[[], Awaitable[c.ProviderResult]]) -> c.ProviderResult:
    """Execute one adapter call and log it. A ProviderError becomes an HTTP error after logging."""
    requested_at = c.utcnow()
    try:
        result = await call()
    except c.ProviderError as e:
        request_id = c.new_request_id()
        await request_log.record(db, operation=operation, params=params, user_id=user.get("user_id"), error=e,
                                 provider_id=provider_id, request_id=request_id, requested_at=requested_at)
        raise HTTPException(status_code=_HTTP_STATUS.get(e.code, 502), detail={
            "error_code": e.code, "message": request_log.redact(e.message), "retryable": e.retryable,
            "provider_id": provider_id, "request_id": request_id})
    await request_log.record(db, operation=operation, params=params, user_id=user.get("user_id"), result=result)
    return result


# ── request models ───────────────────────────────────────────────────────
class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SyncInstruments(_Body):
    exchange: Literal["NSE", "BSE"] = "NSE"


class FetchCandles(_Body):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    start: date
    end: date
    interval: Literal["minute", "3minute", "5minute", "15minute", "60minute", "day"] = "day"
    exchange: Literal["NSE", "BSE"] = "NSE"


class SearchEntity(_Body):
    query: str = Field(min_length=1, max_length=120)
    entity_type: Literal["stock", "etf", "index"] = "stock"
    limit: int = Field(default=10, ge=1, le=50)


class Query(_Body):
    query: str = Field(min_length=1, max_length=300)


class FetchParameters(_Body):
    stock_codes: List[str] = Field(min_length=1, max_length=MAX_STOCK_CODES)
    parameters: List[str] = Field(min_length=1, max_length=MAX_PARAMETERS)


class FetchEvents(_Body):
    stock_code: str = Field(pattern=STOCK_CODE_PATTERN)


# ── catalogue + health ───────────────────────────────────────────────────
@router.get("")
async def providers(user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    """What each provider is used for (§32.2) and whether it is configured. No secret values."""
    return {"providers": [
        {"provider_id": c.PROVIDER_KITE, "role": "market candles and instrument master",
         "configured": bool(default_token()), "exchanges": list(EXCHANGES),
         "operations": ["sync-instruments", "fetch-candles"],
         "limits": "access token expires daily (~06:00 IST) and needs an interactive login",
         "pit_status": "candle timestamp is the event; price adjustment UNVERIFIED"},
        {"provider_id": c.PROVIDER_TRENDLYNE, "role": "enrichment: entities, parameters, events, documents",
         "configured": bool(default_url()), "entity_types": list(ENTITY_TYPES),
         "operations": ["search-entity", "search-parameters", "fetch-parameters", "fetch-events", "search-documents"],
         "tools": sorted(READ_TOOLS),
         "limits": f"{MAX_STOCK_CODES} stock codes x {MAX_PARAMETERS} parameters per call; EOD; no as-of parameter",
         "pit_status": c.PIT_UNVERIFIED},
    ]}


@router.get("/health")
async def health(user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    """Live state of each provider. Kite is probed with the instrument master only when a token
    exists; Trendlyne with initialize + tools/list (no data call)."""
    kite: Dict[str, Any] = {"provider_id": c.PROVIDER_KITE, "configured": bool(default_token())}
    if not kite["configured"]:
        kite.update(reachable=False, error_code=c.AUTH_EXPIRED,
                    detail="no Kite access token; the daily login handshake has not been run")
    else:
        try:
            result = await asyncio.to_thread(_kite().sync_instruments, "NSE")
            kite.update(reachable=True, error_code=result.error_code, instruments=len(result.normalized_records))
        except c.ProviderError as e:
            kite.update(reachable=False, error_code=e.code, detail=request_log.redact(e.message), retryable=e.retryable)
    return {"checked_at": c.utcnow().isoformat(), "providers": [kite, await _trendlyne().health()]}


# ── Kite ─────────────────────────────────────────────────────────────────
@router.post("/kite/sync-instruments")
async def kite_sync_instruments(body: SyncInstruments, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_KITE, "sync-instruments", body.model_dump(), user,
                        lambda: asyncio.to_thread(_kite().sync_instruments, body.exchange))
    out = result.to_dict()
    out["meta"]["record_count"] = len(result.normalized_records)
    out["meta"]["records_previewed"] = min(INSTRUMENT_PREVIEW, len(result.normalized_records))
    out["normalized_records"] = result.normalized_records[:INSTRUMENT_PREVIEW]
    return out


@router.post("/kite/fetch-candles")
async def kite_fetch_candles(body: FetchCandles, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(
        c.PROVIDER_KITE, "fetch-candles", body.model_dump(mode="json"), user,
        lambda: asyncio.to_thread(_kite().fetch_candles, body.symbol, body.start, body.end, body.interval, body.exchange))
    return result.to_dict()


# ── Trendlyne ────────────────────────────────────────────────────────────
@router.post("/trendlyne/search-entity")
async def trendlyne_search_entity(body: SearchEntity, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_TRENDLYNE, "search-entity", body.model_dump(), user,
                        lambda: _trendlyne().search_entity(body.query, body.entity_type, body.limit))
    return result.to_dict()


@router.post("/trendlyne/search-parameters")
async def trendlyne_search_parameters(body: Query, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_TRENDLYNE, "search-parameters", body.model_dump(), user,
                        lambda: _trendlyne().search_parameters(body.query))
    return result.to_dict()


@router.post("/trendlyne/fetch-parameters")
async def trendlyne_fetch_parameters(body: FetchParameters, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_TRENDLYNE, "fetch-parameters", body.model_dump(), user,
                        lambda: _trendlyne().fetch_parameters(body.stock_codes, body.parameters))
    return result.to_dict()


@router.post("/trendlyne/fetch-events")
async def trendlyne_fetch_events(body: FetchEvents, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_TRENDLYNE, "fetch-events", body.model_dump(), user,
                        lambda: _trendlyne().fetch_events(body.stock_code))
    return result.to_dict()


@router.post("/trendlyne/search-documents")
async def trendlyne_search_documents(body: Query, user: dict = Depends(require_feature(FLAG))) -> Dict[str, Any]:
    result = await _run(c.PROVIDER_TRENDLYNE, "search-documents", body.model_dump(), user,
                        lambda: _trendlyne().search_documents(body.query))
    return result.to_dict()
