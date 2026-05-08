"""NIDP Data-as-a-Service API — public read-only HTTPS over the warehouse.

Layout:

    /health                       (no auth)
    /v1/me                        — identity + rate-limit state
    /v1/me/usage                  — daily request counters
    /v1/catalog                   — datasets + coverage
    /v1/prices/...                — EOD OHLCV (raw + adjusted), indices, delivery
    /v1/corporate-actions/...     — split / bonus / dividend calendar
    /v1/indices/...               — index list + constituents
    /v1/holidays, /symbols, /sectors
    /v1/financials/{symbol}, /shareholding/{symbol}
    /v1/fno/{symbol}, /fno/{symbol}/chain, /fno/{symbol}/expiries
    /v1/flows/fii-dii, /flows/bulk-deals, /flows/block-deals
    /v1/announcements
    /v1/macro/rbi-yields, /macro/fred
    /v1/snapshots/market, /snapshots/stock/{symbol}
    /v1/features/stocks/{symbol}

Auth: X-API-Key (or Authorization: Bearer). Per-key rate limit (rpm) and
daily quota; both surface as response headers. Keys are issued via
`python -m nidp.cli daas-keygen ...` and the cleartext token is shown
exactly once."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from nidp.shared.storage.pg import close_pool, get_pool
from nidp.services.daas_api.middleware import RequestContextMiddleware
from nidp.services.daas_api.routers import (
    announcements,
    catalog,
    corporate_actions,
    features,
    financials,
    flows,
    fno,
    health,
    indices,
    macro,
    me,
    prices,
    reference,
    snapshots,
)


logger = logging.getLogger(__name__)


_DESCRIPTION = """
**NIDP Data-as-a-Service** — programmatic access to the Nivesh Indian-market
data warehouse: NSE + BSE end-of-day, F&O bhavcopy, corporate actions,
quarterly financials, shareholding, FII/DII flows, bulk/block deals,
RBI + FRED macro, and the engineered feature set used by Nivesh's
strategy engine.

### Authentication

Every `/v1/*` endpoint requires an API key. Pass it as either:

    X-API-Key: nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    Authorization: Bearer nvd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

Keys are issued by Nivesh ops; the cleartext is shown exactly once at
issuance. Lost keys can be revoked, not recovered.

### Rate limits

Each key has a per-minute rate (`X-RateLimit-Limit`) and a daily quota
(`X-Daily-Limit`). Both are surfaced on every response. A 429 response
includes a `Retry-After` header.

### Pagination

List endpoints accept `limit` (1–5000, default 100) and `offset`. The
response envelope includes `pagination.next_offset` when more rows are
available.

### Conventions

* Dates are `YYYY-MM-DD`; timestamps are ISO 8601 UTC.
* Numeric values are decoded from `NUMERIC` to JSON numbers. For exact
  fidelity, use the per-row `decimal_places` derivable from the schema.
* Symbols are canonical NSE tickers, upper-cased server-side.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await get_pool()
        logger.info("nidp-daas-api: pg pool warm")
    except Exception as e:                                            # noqa: BLE001
        logger.warning("nidp-daas-api: pg pool warm-up failed: %s", e)
    yield
    try:
        await close_pool()
    except Exception:                                                  # noqa: BLE001
        pass


app = FastAPI(
    title="NIDP Data-as-a-Service API",
    version="1.0.0",
    description=_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Nivesh", "url": "https://nivesh.com"},
    license_info={"name": "Commercial — see Nivesh DaaS terms"},
    lifespan=lifespan,
)


# ── Middleware ──────────────────────────────────────────────────────
_cors_origins = [
    o.strip() for o in os.environ.get("NIDP_DAAS_CORS_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,                  # API-key auth — no cookies
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
        "X-Daily-Limit", "X-Daily-Remaining",
        "X-Request-Id", "Retry-After",
    ],
)
app.add_middleware(RequestContextMiddleware)


# ── Error normalisation ─────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def _http_exc_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "status":     exc.status_code,
                "message":    exc.detail if isinstance(exc.detail, str) else str(exc.detail),
                "request_id": request_id,
            }
        },
        headers=exc.headers or {},
    )


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "status":     400,
                "message":    "validation_error",
                "details":    exc.errors(),
                "request_id": request_id,
            }
        },
    )


# ── Routes ──────────────────────────────────────────────────────────
# Public, no auth
app.include_router(health.router)


@app.get("/", include_in_schema=False)
async def root():
    return {
        "service":   "nidp-daas-api",
        "version":   "1.0.0",
        "docs":      "/docs",
        "openapi":   "/openapi.json",
        "v1":        "/v1",
    }


# All authenticated routes hang off /v1
v1_prefix = "/v1"
app.include_router(me.router, prefix=v1_prefix)
app.include_router(catalog.router, prefix=v1_prefix)
app.include_router(prices.router, prefix=v1_prefix)
app.include_router(corporate_actions.router, prefix=v1_prefix)
app.include_router(indices.router, prefix=v1_prefix)
app.include_router(reference.router, prefix=v1_prefix)
app.include_router(financials.router, prefix=v1_prefix)
app.include_router(fno.router, prefix=v1_prefix)
app.include_router(flows.router, prefix=v1_prefix)
app.include_router(announcements.router, prefix=v1_prefix)
app.include_router(macro.router, prefix=v1_prefix)
app.include_router(snapshots.router, prefix=v1_prefix)
app.include_router(features.router, prefix=v1_prefix)
