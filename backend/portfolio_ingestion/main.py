"""FastAPI application entrypoint for the portfolio_ingestion service.

Runs standalone, doesn't import or affect the main nivesh.ai backend at
``backend/server.py``. Mounted at the root; nginx in front rewrites paths.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __service_name__, __version__
from .api.health import router as health_router
from .api.portfolio import router as portfolio_router
from .api.sdk_callback import router as sdk_callback_router
from .api.token import router as token_router
from .api.uploads import router as uploads_router
from .api.webhooks import router as webhooks_router
from .config import get_settings
from .db.migrations.runner import apply_pending as _run_migrations
from .logging_setup import configure as configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Portfolio Ingestion",
        description="CAS ingestion, snapshot engine and portfolio read APIs.",
        version=settings.version,
    )

    @app.on_event("startup")
    async def _startup() -> None:
        log = logging.getLogger(__name__)
        log.info(
            "portfolio_ingestion starting",
            extra={
                "eventType": "SERVICE_START",
                "service": settings.service_name,
                "version": settings.version,
                "env": settings.app_env,
            },
        )
        # Run pending DB migrations on every boot. Idempotent — already-applied
        # migrations are skipped in < 1 ms; new ones run exactly once.
        if settings.postgres_url:
            await _run_migrations()

    app.include_router(health_router)
    app.include_router(sdk_callback_router)
    app.include_router(uploads_router)
    app.include_router(webhooks_router)
    app.include_router(token_router)
    app.include_router(portfolio_router)
    return app


app = create_app()


__all__ = ["app", "create_app", "__service_name__", "__version__"]
