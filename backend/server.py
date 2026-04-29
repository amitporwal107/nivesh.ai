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

# Ensure poppler-utils is installed (needed for image-based CAS PDFs)
try:
    subprocess.run(["which", "pdftoppm"], check=True, capture_output=True)
except subprocess.CalledProcessError:
    subprocess.run(["apt-get", "update", "-qq"], capture_output=True)
    subprocess.run(["apt-get", "install", "-y", "poppler-utils"], capture_output=True)

from middleware import RateLimitMiddleware, validate_env

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
from routes.copilot_prompts import router as copilot_prompts_router
from routes.copilot import router as copilot_router  # Nivesh Copilot (CIO Assistant)
from routes.gmail import router as gmail_router
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
from routes.portfolio_snapshots import router as portfolio_snapshots_router  # Time-Machine
from routes.portfolio_export import router as portfolio_export_router  # CSV/XLSX export
from routes.client_cas_invite import mfd_router as cas_invite_mfd_router, public_router as cas_invite_public_router
from routes.data_health import router as data_health_router  # Global stale-data banner
from routes.cas_transactions import router as cas_transactions_router  # SIP detection + txn history
from routes.cas_snapshots import router as cas_snapshots_router  # CAS Time-Machine endpoints

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="nivesh.ai API", version="2.0")

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
app.include_router(copilot_prompts_router)
app.include_router(copilot_router)
app.include_router(gmail_router)
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
app.include_router(portfolio_snapshots_router)  # Portfolio Time-Machine
app.include_router(cas_invite_mfd_router)       # Client CAS invite (MFD side)
app.include_router(cas_invite_public_router)    # Client CAS invite (public, no auth)
app.include_router(data_health_router)           # Global stale-data banner
app.include_router(cas_transactions_router)      # SIP detection + txn history
app.include_router(cas_snapshots_router)          # CAS Time-Machine endpoints


# Root endpoint
@app.get("/api/")
async def root():
    return {"message": "nivesh.ai API"}


# Middleware
app.add_middleware(RateLimitMiddleware)

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
        logger.warning(f"Config hydrate failed: {e}")
    # Start MF scheduler if Postgres is configured
    try:
        from services import pg_client, mf_scheduler
        pool = await pg_client.get_pool()
        if pool is not None:
            mf_scheduler.start()
    except Exception as e:
        logger.warning(f"MF scheduler start failed: {e}")
    # Portfolio snapshot indexes (cheap, idempotent)
    try:
        from services import portfolio_snapshot as _snap
        await _snap.ensure_indexes()
    except Exception as e:
        logger.warning(f"portfolio_snapshot index ensure failed: {e}")


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
