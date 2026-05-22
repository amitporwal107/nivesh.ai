"""FastAPI application entrypoint for the portfolio_ingestion service.

Runs standalone, doesn't import or affect the main nivesh.ai backend at
``backend/server.py``. Mounted at the root; nginx in front rewrites paths.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from . import __service_name__, __version__
from .api.health import router as health_router
from .config import get_settings
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
        logging.getLogger(__name__).info(
            "portfolio_ingestion starting",
            extra={
                "eventType": "SERVICE_START",
                "service": settings.service_name,
                "version": settings.version,
                "env": settings.app_env,
            },
        )

    app.include_router(health_router)
    return app


app = create_app()


__all__ = ["app", "create_app", "__service_name__", "__version__"]
