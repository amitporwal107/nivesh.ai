"""NIDP Data-as-a-Service API — public read-only HTTPS over the warehouse.

Layout:

    /health                       (no auth)
    /admin/keys                   — key lifecycle (NIDP_DAAS_INTERNAL_TOKEN)
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
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from nidp.shared.storage.pg import close_pool, get_pool
from nidp.services.daas_api.middleware import RequestContextMiddleware
from nidp.services.daas_api.dq_middleware import DQStatusMiddleware
from nidp.services.daas_api.routers import (
    admin,
    analytics,
    announcements,
    backfill,
    catalog,
    corporate_actions,
    dq_ai,
    events,
    features,
    financials,
    flows,
    fno,
    health,
    indices,
    intelligence,
    macro,
    market_pulse,
    me,
    mf,
    portfolio_risk,
    mf_performance,
    mf_scores,
    prices,
    reference,
    replay,
    snapshots,
    stock_scores,
    stock_v3_scores,
    dq_status,
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


_TAGS = [
    {"name": "admin",            "description": "Key lifecycle management. Requires `NIDP_DAAS_INTERNAL_TOKEN` (Bearer auth). Use the 🔒 **Authorize** button → paste the internal token under **BearerAuth**."},
    {"name": "health",           "description": "Liveness probe — no auth required."},
    {"name": "me",               "description": "Caller identity, plan, and daily usage."},
    {"name": "catalog",          "description": "Dataset index with live row counts."},
    {"name": "prices",           "description": "NSE EOD OHLCV — raw bhavcopy and split/bonus/dividend-adjusted series."},
    {"name": "corporate_actions","description": "Dividend, split, bonus, and rights calendar."},
    {"name": "indices",          "description": "Index list and effective-dated constituent membership."},
    {"name": "reference",        "description": "Symbol master, sector list, and NSE trading holidays."},
    {"name": "financials",       "description": "Quarterly financials and shareholding pattern."},
    {"name": "fno",              "description": "F&O bhavcopy — futures and options OHLCV, options chain, expiry calendar."},
    {"name": "flows",            "description": "FII / DII net flows, bulk deals, and block deals."},
    {"name": "announcements",    "description": "NSE + BSE corporate filings and exchange announcements."},
    {"name": "macro",            "description": "RBI G-Sec yields and global macro series from FRED."},
    {"name": "snapshots",        "description": "Pre-computed market-wide and per-stock daily snapshots."},
    {"name": "features",         "description": "Engineered features from the Nivesh S4/S5 strategy pipeline."},
    {"name": "mutual_funds",     "description": "Mutual fund AMCs, schemes, daily NAV, monthly holdings, portfolio overlap, lifecycle events, TER/risk-o-meter snapshots, AMFI circulars."},
    {"name": "dq",               "description": "Data Quality gate verdicts, DLQ findings, and snapshot status (Gate 6 envelope)."},
]

app = FastAPI(
    title="NIDP Data-as-a-Service API",
    version="1.0.0",
    description=_DESCRIPTION,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    contact={"name": "Nivesh", "url": "https://nivesh.com"},
    license_info={"name": "Commercial — see Nivesh DaaS terms"},
    openapi_tags=_TAGS,
    lifespan=lifespan,
    # Behind nginx at https://data.niveshcopilot.com/daas — also passed
    # as --root-path /daas to uvicorn for ASGI scope. Setting it here
    # makes app.root_path available to the custom openapi builder.
    root_path=os.environ.get("ROOT_PATH", ""),
)


def _custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    # Honour --root-path so the `servers` block in the spec points at the
    # external URL (e.g. /daas) when behind nginx. Otherwise Swagger UI's
    # "Try it out" buttons hit /v1/catalog instead of /daas/v1/catalog.
    servers = [{"url": app.root_path}] if app.root_path else None
    schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        contact=app.contact,
        license_info=app.license_info,
        tags=_TAGS,
        routes=app.routes,
        servers=servers,
    )
    # Inject both security schemes so Swagger UI shows the Authorize button
    schema.setdefault("components", {}).setdefault("securitySchemes", {}).update({
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": "Pass your `nvd_...` token in the **X-API-Key** header. Issued via `POST /admin/keys`.",
        },
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "description": "Internal admin token (`NIDP_DAAS_INTERNAL_TOKEN`). Required for `/admin/*` endpoints only.",
        },
    })
    # Apply ApiKeyAuth globally to all /v1/* operations; BearerAuth to /admin/*
    for path, methods in schema.get("paths", {}).items():
        for method, op in methods.items():
            if method == "parameters":
                continue
            tags = op.get("tags", [])
            if "admin" in tags:
                op.setdefault("security", [{"BearerAuth": []}])
            elif path.startswith("/v1/"):
                op.setdefault("security", [{"ApiKeyAuth": []}])
    app.openapi_schema = schema
    return schema


app.openapi = _custom_openapi


# ── Middleware ──────────────────────────────────────────────────────
_cors_origins = [
    o.strip() for o in os.environ.get("NIDP_DAAS_CORS_ORIGINS", "*").split(",")
    if o.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,                  # API-key auth — no cookies
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=[
        "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
        "X-Daily-Limit", "X-Daily-Remaining",
        "X-Request-Id", "Retry-After",
        "X-DQ-Status", "X-DQ-As-Of-Date", "X-DQ-Snapshot-Id",
    ],
)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(DQStatusMiddleware)


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
    # Pydantic V2 may embed raw exceptions inside `ctx` (e.g. when a
    # field_validator raises ValueError). Coerce any non-JSON-friendly
    # values to str so JSONResponse doesn't fail with TypeError.
    safe_errors = []
    for err in exc.errors():
        e = dict(err)
        ctx = e.get("ctx")
        if isinstance(ctx, dict):
            e["ctx"] = {k: (str(v) if isinstance(v, BaseException) else v) for k, v in ctx.items()}
        safe_errors.append(e)
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "status":     400,
                "message":    "validation_error",
                "details":    safe_errors,
                "request_id": request_id,
            }
        },
    )


# ── Routes ──────────────────────────────────────────────────────────
# Public, no auth
app.include_router(health.router)

# Admin — internal token only (key lifecycle management)
app.include_router(admin.router)


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
app.include_router(market_pulse.router, prefix=v1_prefix)
app.include_router(indices.router, prefix=v1_prefix)
app.include_router(reference.router, prefix=v1_prefix)
app.include_router(intelligence.router, prefix=v1_prefix)
app.include_router(dq_ai.router, prefix=v1_prefix)
app.include_router(replay.router, prefix=v1_prefix)
app.include_router(backfill.router, prefix=v1_prefix)
app.include_router(financials.router, prefix=v1_prefix)
app.include_router(fno.router, prefix=v1_prefix)
app.include_router(flows.router, prefix=v1_prefix)
app.include_router(announcements.router, prefix=v1_prefix)
app.include_router(macro.router, prefix=v1_prefix)
app.include_router(snapshots.router, prefix=v1_prefix)
app.include_router(features.router, prefix=v1_prefix)
app.include_router(events.router, prefix=v1_prefix)
app.include_router(mf.router, prefix=v1_prefix)
app.include_router(mf_performance.router, prefix=v1_prefix)
app.include_router(mf_scores.router, prefix=v1_prefix)
app.include_router(stock_scores.router, prefix=v1_prefix)
app.include_router(stock_v3_scores.router, prefix=v1_prefix)
app.include_router(analytics.router, prefix=v1_prefix)
app.include_router(dq_status.router, prefix=v1_prefix)
app.include_router(portfolio_risk.router, prefix=v1_prefix)
