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
from routes.admin_datastores import router as admin_datastores_router
from routes.admin_rules import router as admin_rules_router
from routes.admin_users import router as admin_users_router
from routes.copilot_prompts import router as copilot_prompts_router
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

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="nivesh.ai API", version="2.0")

# Include all routers
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(admin_datastores_router)
app.include_router(admin_rules_router)
app.include_router(copilot_prompts_router)
app.include_router(gmail_router)
app.include_router(portfolio_router)
app.include_router(upload_router)
app.include_router(analytics_router)
app.include_router(chat_router)
app.include_router(user_router)
app.include_router(insights_router)
app.include_router(scenarios_router)
app.include_router(mf_data_router)
app.include_router(intelligence_router)
app.include_router(plans_router)  # V2: Action Plans


# Root endpoint
@app.get("/api/")
async def root():
    return {"message": "nivesh.ai API"}


# Middleware
app.add_middleware(RateLimitMiddleware)

_cors_env = os.environ.get('CORS_ORIGINS', '')
if _cors_env == '*':
    _cors_origins = ["https://nivesh-ai-preview.preview.emergentagent.com", "http://localhost:3000"]
else:
    _cors_origins = [o.strip() for o in _cors_env.split(',') if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=_cors_origins,
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
        from services import cas_api_client
        await _secrets.hydrate_from_db(db)
        await _ff.hydrate_from_db(db)
        cas_cfg = await db.system_config.find_one({"key": "cas_parser"}, {"_id": 0})
        if cas_cfg and "use_sandbox" in cas_cfg:
            cas_api_client.set_override(use_sandbox=cas_cfg["use_sandbox"])
        logger.info("Secrets + feature flags hydrated from DB")
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
