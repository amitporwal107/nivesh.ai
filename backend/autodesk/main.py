"""Entry point of the Autonomous Trading Desk service — a separate application from the main Nivesh API.

    uvicorn autodesk.main:app --host 0.0.0.0 --port 8010      (cwd = backend/, same image as the main backend)

Start-up: hydrate admin-managed secrets (the data-API credentials live there), open the autodesk Postgres pool, apply
the autodesk migrations, register the five agents, and fail closed any task a previous process left unfinished.
Single instance in Phase 1 (recovery assumes no other live instance).
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional

from fastapi import FastAPI

from . import APP_NAME, APP_VERSION
from . import config as cfgmod
from .routers.api import error_handlers, router

log = logging.getLogger(__name__)


@dataclass
class DeskState:
    pool: Any
    orchestrator: Any
    simulator: Any
    market_factory: Callable[[datetime], Any]
    next_session: Callable[[datetime], Awaitable[date]]
    background: dict = field(default_factory=dict)


def production_agents() -> dict:
    from .agents.registry import default_agents
    return default_agents()


def build_state(pool, *, agents: dict, market_factory, sessions_provider, next_session, settings=None,
                load_book=None, scope_builder=None) -> DeskState:
    from .orchestrator.engine import Orchestrator
    from .simulator.manager import SimulationManager

    orch = Orchestrator(pool, agents, market_factory, settings=settings, load_book=load_book,
                        scope_builder=scope_builder,
                        task_deadline_s=getattr(settings, "task_deadline_s", 30.0) if settings else 30.0)

    def versions() -> dict:
        v: dict[str, Any] = {"app": APP_VERSION,
                             "agents": {k.value: a.descriptor.version for k, a in agents.items()},
                             "market_view": "point-in-time; cash EOD visible 18:30 IST, F&O EOD 19:30 IST"}
        try:
            from .control.risk_engine import ENGINE_VERSION
            v["risk_engine"] = ENGINE_VERSION
        except ImportError:
            pass
        try:
            from .agents.ai_trader import RULE_VERSION
            v["scan_rules"] = RULE_VERSION
        except ImportError:
            pass
        return v

    sim = SimulationManager(pool, orch, sessions_provider, versions=versions)
    return DeskState(pool=pool, orchestrator=orch, simulator=sim, market_factory=market_factory,
                     next_session=next_session)


def create_app(state_factory: Optional[Callable[[], Awaitable[DeskState]]] = None) -> FastAPI:
    """`state_factory` lets tests inject a pool and test doubles; production builds everything from the environment."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if state_factory is not None:
            app.state.desk = await state_factory()
            yield
            return
        settings = cfgmod.load()
        try:   # data-API credentials are admin-managed secrets in Mongo, as in the main app
            from deps import db
            from helpers import secrets as _secrets
            await _secrets.hydrate_from_db(db)
        except Exception as e:  # noqa: BLE001 — the env may already carry them; the health check shows data status
            log.warning("secret hydrate failed: %s", e)
        from .db import close_pool, open_pool
        from .db.migrate import apply_pending
        from .market.calendar import next_session_for, sessions_between
        from .market.pit import PitMarketView

        pool = await open_pool(settings.pg_url)
        if settings.auto_migrate:
            applied = await apply_pending(pool)
            log.info("autodesk migrations applied: %s", applied or "none")
        st = build_state(pool, agents=production_agents(), market_factory=lambda as_of: PitMarketView(as_of),
                         sessions_provider=sessions_between, next_session=next_session_for, settings=settings)
        await st.orchestrator.register_agents()
        touched = await st.orchestrator.recover()
        if touched:
            log.warning("recovery failed closed %d interrupted tasks", len(touched))
        app.state.desk = st
        try:
            yield
        finally:
            for t in st.background.values():
                t.cancel()
            await close_pool()

    app = FastAPI(title="Nivesh Autonomous Trading Desk API", version=APP_VERSION, lifespan=lifespan,
                  description="Separate application. Phase 1: agents, orchestrator, risk, approvals, simulator. "
                              "No orders are placed anywhere.")
    try:
        from middleware import BodySizeLimitMiddleware, CsrfProtectMiddleware, SecurityHeadersMiddleware
        app.add_middleware(CsrfProtectMiddleware)
        app.add_middleware(BodySizeLimitMiddleware)
        app.add_middleware(SecurityHeadersMiddleware)
    except Exception as e:  # noqa: BLE001
        log.warning("shared middleware unavailable: %s", e)
    try:
        from core.correlation import CorrelationMiddleware
        app.add_middleware(CorrelationMiddleware)
    except Exception as e:  # noqa: BLE001
        log.warning("correlation middleware unavailable: %s", e)
    error_handlers(app)
    app.include_router(router)
    return app


def _make_app() -> FastAPI:
    from core.logging_config import configure_logging
    configure_logging(service=APP_NAME)
    return create_app()


app = _make_app()
