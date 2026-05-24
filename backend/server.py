"""nivesh.ai API — Entry point. Routes are organized in /routes/ modules."""
from fastapi import FastAPI
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
import os
import logging
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# Structured JSON logging must be configured before any module acquires a logger.
from core.logging_config import configure_logging
configure_logging(service="nivesh-api")

# Ensure poppler-utils is installed (needed for image-based CAS PDFs)
try:
    subprocess.run(["which", "pdftoppm"], check=True, capture_output=True)
except subprocess.CalledProcessError:
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
    subprocess.run(["apt-get", "install", "-y", "poppler-utils"], capture_output=True)

from middleware import RateLimitMiddleware, SecurityHeadersMiddleware, RequestLoggingMiddleware, validate_env

# Validate env on startup
validate_env()

# Import deps to initialize DB connection
from deps import db, client, seed_admin_and_whitelist

# Import all route modules
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.admin_v3_master import router as admin_v3_master_router
from routes.admin_v3_weights import router as admin_v3_weights_router
from routes.admin_v3_stock import router as admin_v3_stock_router
from routes.admin_datastores import router as admin_datastores_router
from routes.admin_rules import router as admin_rules_router
from routes.admin_users import router as admin_users_router
from routes.admin_data_pipeline import router as admin_pipeline_router
from routes.admin_nidp import router as admin_nidp_router  # NIDP one-click diagnostic dump
from routes.admin_nidp_replay import router as admin_nidp_replay_router  # NIDP 90-day replay engine
from routes.admin_nidp_backfill import router as admin_nidp_backfill_router  # NIDP backfill status proxy
from routes.copilot_prompts import router as copilot_prompts_router
from routes.copilot import router as copilot_router  # Nivesh Copilot (CIO Assistant)
from routes.gmail import router as gmail_router
from routes.onboarding_gmail import router as onboarding_gmail_router  # wrapped Gmail onboarding (no SDK popup)
from routes.portfolio import router as portfolio_router
from routes.upload import router as upload_router
from routes.analytics import router as analytics_router
from routes.chat import router as chat_router
from routes.user import router as user_router
from routes.insights import router as insights_router
from routes.scenarios import router as scenarios_router
from routes.mf_data import router as mf_data_router
from routes.intelligence import router as intelligence_router
from routes.plans import router as plans_router  # V2: Action Plans
from routes.goals import router as goals_router  # Goal-Based Investment Planning
from routes.compliance import router as compliance_router  # DPDP Act 2023 compliance
from routes.mfd import router as mfd_router  # MFD multi-client layer
from routes.advisor import router as advisor_router  # Advisor Home insight cards
from routes.portfolio_builder import router as portfolio_builder_router  # AI Portfolio Builder + risk chat + sim + export
from routes.macro import router as macro_router, stock_router as macro_stock_router  # Macro Intelligence Layer
from routes.portfolio_snapshots import router as portfolio_snapshots_router  # Time-Machine
from routes.portfolio_export import router as portfolio_export_router  # CSV/XLSX export
from routes.client_cas_invite import mfd_router as cas_invite_mfd_router, public_router as cas_invite_public_router
from routes.data_health import router as data_health_router  # Global stale-data banner
from routes.cas_transactions import router as cas_transactions_router  # SIP detection + txn history
from routes.cas_snapshots import router as cas_snapshots_router  # CAS Time-Machine endpoints
from routes.benchmarks import router as benchmarks_router  # Benchmark Index Data Service
from routes.positional import router as positional_router  # Positional Trading Engine (technical, 5-30d)
from routes.positional_journal import router as positional_journal_router  # Trade Journal (staged-entry tracker)
from routes.strategy_builder import router as strategy_builder_router  # Strategy Builder (multi-asset DSL + backtest)
from routes.feeds import router as feeds_router  # Generic feed-subscription RAG (S4/S5 corpus + structured)
from routes.broker_connect import router as broker_connect_router  # Secure Portfolio Connect: read-only broker holdings via OpenAlgo
from routes.broker_native import router as broker_native_router  # Native broker connect (no OpenAlgo) — direct broker OAuth + SDK adapters
from routes.openalgo_proxy import router as openalgo_proxy_router  # Public reverse-proxy for the Nivesh-hosted OpenAlgo dashboard
from routes.market_events import router as market_events_router  # Market Event Intelligence — corporate events, AI signals, breakout feed
from routes.portfolio_exposure import router as portfolio_exposure_router  # Diversification & Concentration analytics — AMC / Sector / Company exposure
from routes.portfolio_risk_analytics import router as portfolio_risk_analytics_router  # V3 risk analytics — beta/sharpe/volatility from DAAS
from routes.admin_nidp_stock_primitives import router as admin_nidp_stock_primitives_router  # NIDP stock primitives completeness check
from routes.copilot_agents import router as copilot_agents_router  # Copilot agent + model picker (Intelligence Layer Phase A/B)
from routes.copilot_widgets import router as copilot_widgets_router  # Copilot embedded-widget producers (Fund card, Market brief, ...)
from routes.admin_swagger import router as admin_swagger_router  # Admin-only Swagger UI (/api/admin/swagger)

# ── CAS ingestion module ──────────────────────────────────────────────
# Used to be a standalone FastAPI service in its own container; now mounted
# in-process on this app. Same DB, same endpoints (/api/cas/sdk-callback,
# /api/casparser/token, /api/portfolio/me, /api/portfolio/snapshots,
# /api/admin/jobs|/verify, /webhooks/casparser/*, /api/healthz, /api/readyz).
from portfolio_ingestion.api.sdk_callback   import router as cas_sdk_router
from portfolio_ingestion.api.uploads        import router as cas_uploads_router
from portfolio_ingestion.api.portfolio      import router as cas_portfolio_router
from portfolio_ingestion.api.token          import router as cas_token_router
from portfolio_ingestion.api.webhooks       import router as cas_webhooks_router
from portfolio_ingestion.api.admin          import router as cas_admin_router
from portfolio_ingestion.api.health         import router as cas_health_router
from portfolio_ingestion.db.migrations.runner import apply_pending as _cas_apply_migrations

from core.correlation import CorrelationMiddleware
from core.error_handlers import register_error_handlers

logger = logging.getLogger(__name__)

app = FastAPI(title="nivesh.ai API", version="2.0")
register_error_handlers(app)

# Include all routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_users_router)
app.include_router(admin_v3_master_router)
app.include_router(admin_v3_weights_router)
app.include_router(admin_v3_stock_router)
app.include_router(admin_datastores_router)
app.include_router(admin_rules_router)
app.include_router(admin_pipeline_router)
app.include_router(admin_nidp_router)
app.include_router(admin_nidp_replay_router)
app.include_router(admin_nidp_backfill_router)
app.include_router(copilot_prompts_router)
app.include_router(copilot_router)
app.include_router(gmail_router)
app.include_router(onboarding_gmail_router)
app.include_router(portfolio_router)
app.include_router(portfolio_export_router)
app.include_router(upload_router)
app.include_router(analytics_router)
app.include_router(chat_router)
app.include_router(user_router)
app.include_router(insights_router)
app.include_router(scenarios_router)
app.include_router(mf_data_router)
app.include_router(intelligence_router)
app.include_router(plans_router)  # V2: Action Plans
app.include_router(goals_router)  # Goal-Based Investment Planning
app.include_router(compliance_router)  # DPDP: consent / audit / PAN / export
app.include_router(mfd_router)  # MFD multi-client layer (User → Workspace → Profile)
app.include_router(advisor_router)  # Advisor Home insight cards (today / aum / underperformers / rebalance)
app.include_router(portfolio_builder_router)  # AI Portfolio Builder + conversational risk chat + simulation + PDF/WA export
app.include_router(macro_router)  # Macro Intelligence Layer (daily regime + features for the positional engine)
app.include_router(macro_stock_router)  # /api/stock/{symbol}/why — explainability tied to macro
app.include_router(portfolio_snapshots_router)  # Portfolio Time-Machine
app.include_router(cas_invite_mfd_router)       # Client CAS invite (MFD side)
app.include_router(cas_invite_public_router)    # Client CAS invite (public, no auth)
app.include_router(data_health_router)           # Global stale-data banner
app.include_router(cas_transactions_router)      # SIP detection + txn history
app.include_router(cas_snapshots_router)          # CAS Time-Machine endpoints
app.include_router(benchmarks_router)             # Benchmark Index Data Service
app.include_router(positional_router)              # Positional Trading Engine
app.include_router(positional_journal_router)      # Trade Journal (staged-entry tracker)
app.include_router(strategy_builder_router)        # Strategy Builder (Phase 1: stock DSL + backtest)
app.include_router(feeds_router)                   # Feed catalog + subscriptions + content RAG search
app.include_router(broker_connect_router)          # Secure Portfolio Connect — broker holdings via OpenAlgo
app.include_router(broker_native_router)           # Native broker connect (no OpenAlgo) — preferred path for SPC retail
app.include_router(openalgo_proxy_router)          # /api/openalgo/* → http://127.0.0.1:5000/api/openalgo/* (reverse proxy)
app.include_router(market_events_router)           # Market Event Intelligence feed (/api/market/events, /signals)
app.include_router(portfolio_exposure_router)      # Diversification & Concentration analytics (/api/portfolio/exposure/concentration)
app.include_router(portfolio_risk_analytics_router) # V3 risk analytics (/api/portfolio/risk-analytics) — beta/sharpe/vol from DAAS
app.include_router(admin_nidp_stock_primitives_router)  # NIDP stock primitives completeness (/api/admin/nidp/stock-primitives/completeness)
app.include_router(copilot_agents_router)          # Copilot agent + model picker
app.include_router(copilot_widgets_router)         # Copilot widget envelopes (fund_card, market_brief, ...)
app.include_router(admin_swagger_router)           # Admin-only Swagger UI + OpenAPI YAML serving

# CAS ingestion routers — same domain as V2 backend, no separate container.
app.include_router(cas_sdk_router)        # POST /api/cas/sdk-callback
app.include_router(cas_uploads_router)    # POST /api/cas/uploads/init|complete
app.include_router(cas_portfolio_router)  # GET  /api/portfolio/me|snapshots|snapshots/{id}
app.include_router(cas_token_router)      # POST /api/casparser/token
app.include_router(cas_webhooks_router)   # POST /webhooks/casparser/inbound-email (PI_WEBHOOK_ENABLED-gated)
app.include_router(cas_admin_router)      # GET  /api/admin/jobs/stale|summary, /api/admin/verify
app.include_router(cas_health_router)     # GET  /api/healthz, /api/readyz (CAS-specific; V2 has none)


# Root endpoint
@app.get("/api/")
async def root():
    return {"message": "nivesh.ai API"}


# Middleware (Starlette runs middleware in REVERSE add order).
# Execution order on request:
#   Correlation → RequestLogging → RateLimit → SecurityHeaders → route
# CorrelationMiddleware is outermost so the ID is available to all layers.
# RequestLoggingMiddleware wraps everything below it to measure true latency.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationMiddleware)

_cors_env = os.environ.get('CORS_ORIGINS', '')
_cors_origin_regex: str | None = None
if _cors_env == '' or _cors_env == '*':
    # Allow all origins. CORS spec forbids `allow_credentials=True` with
    # `allow_origins=["*"]`, so we use a regex to echo whichever origin
    # made the request. This keeps cookies working across preview URLs,
    # custom domains, and local dev without per-environment config.
    _cors_origins = []
    _cors_origin_regex = r".*"
else:
    _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
    allow_origin_regex=_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_seed():
    logger.info("Connected to MongoDB")
    await seed_admin_and_whitelist()
    # CAS ingestion schema migrations — idempotent. Applies
    # backend/portfolio_ingestion/db/migrations/*.sql against the same
    # Postgres connection. Already-applied migrations are skipped in <1ms.
    try:
        if os.environ.get("PI_POSTGRES_URL"):
            await _cas_apply_migrations()
            logger.info("CAS ingestion migrations: applied/skipped")
    except Exception as e:
        logger.warning("CAS ingestion migration runner failed: %s", e)
    # Hydrate admin-managed config from DB
    try:
        from helpers import secrets as _secrets
        import feature_flags as _ff
        from services import cas_api_client, v3_weights as _v3w, stock_scoring as _sscore
        await _secrets.hydrate_from_db(db)
        await _ff.hydrate_from_db(db)
        await _v3w.hydrate_from_db(db)
        await _sscore.hydrate_from_db(db)
        cas_cfg = await db.system_config.find_one({"key": "cas_parser"}, {"_id": 0})
        if cas_cfg and "use_sandbox" in cas_cfg:
            cas_api_client.set_override(use_sandbox=cas_cfg["use_sandbox"])
        logger.info("Secrets + feature flags + V3 weights hydrated from DB")
    except Exception as e:
        logger.warning("Config hydrate failed: %s", e)
    # Start MF scheduler. PG-dependent jobs (drain / v3_rescore /
    # nifty100_refresh) wrap their own work in try/except so if Postgres
    # is misconfigured or temporarily down they degrade gracefully —
    # while non-PG jobs (AMFI NAV, benchmark indices, gmail_auto_import,
    # portfolio_snapshot) keep running on schedule.
    try:
        from services import mf_scheduler
        mf_scheduler.start()
    except Exception as e:
        logger.warning("MF scheduler start failed: %s", e)
    # Portfolio snapshot indexes (cheap, idempotent)
    try:
        from services import portfolio_snapshot as _snap
        await _snap.ensure_indexes()
    except Exception as e:
        logger.warning("portfolio_snapshot index ensure failed: %s", e)
    # Benchmark Index Data Service — run migration 014 once on startup,
    # idempotent. The daily refresh job is wired into mf_scheduler.
    try:
        from services import benchmark_index as _bm
        await _bm.ensure_schema()
    except Exception as e:
        logger.warning("benchmark schema ensure failed: %s", e)
    # Macro Intelligence Layer — apply migration 016 once on startup.
    # The daily ingest+regime job is wired into mf_scheduler at 18:35 IST.
    try:
        from services import macro_engine as _macro
        await _macro.ensure_schema()
    except Exception as e:
        logger.warning("macro schema ensure failed: %s", e)
    # Identity uniqueness indexes (email_norm / mobile_norm / pan_norm)
    try:
        from services import identity_uniqueness as _iu
        await _iu.ensure_identity_indexes()
    except Exception as e:
        logger.warning("identity index ensure failed: %s", e)
    # Datastore isolation — refuse to start production when Postgres /
    # Redis / Mongo are shared with the preview environment. Preview
    # deploys log a warning and continue.
    try:
        from helpers import datastore_isolation as _di
        await _di.enforce_isolation_at_startup(db)
    except RuntimeError:
        # Production-side hard fail — re-raise so supervisor restarts
        # us until the operator fixes the secrets doc.
        raise
    except Exception as e:
        logger.warning("datastore isolation audit failed: %s", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    try:
        from services import mf_scheduler, pg_client, redis_client
        mf_scheduler.stop()
        await pg_client.close_pool()
        await redis_client.close_client()
    except Exception:
        pass
    client.close()
