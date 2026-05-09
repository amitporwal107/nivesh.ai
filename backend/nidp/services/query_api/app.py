"""NIDP Query API — read-only HTTPS surface over the NIDP warehouse.

Runs as a Cloud Run service inside the same VPC as the Postgres VM.
Auth: bearer token from NIDP_QUERY_API_TOKEN secret. Mounts the same
nidp.shared.storage.pg pool every NIDP ingester uses, so it sees the
exact same data the jobs write."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from nidp.shared.storage.pg import get_pool, close_pool
from nidp.services.query_api.routers import catalog, feeds, validation, health, quality


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await get_pool()
        logger.info("nidp-query-api: pg pool warm")
    except Exception as e:                                            # noqa: BLE001
        # Don't crash on startup — /health will surface the failure and
        # individual endpoints will return their own errors. This lets
        # the service come up even if the DB is briefly unreachable.
        logger.warning("nidp-query-api: pg pool warm-up failed: %s", e)
    yield
    try:
        await close_pool()
    except Exception:                                                  # noqa: BLE001
        pass


app = FastAPI(
    title="NIDP Query API",
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(catalog.router)
app.include_router(feeds.router)
app.include_router(validation.router)
app.include_router(quality.router)
