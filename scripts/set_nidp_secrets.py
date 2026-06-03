#!/usr/bin/env python3
"""
One-shot script: set NIDP_QUERY_API_URL + NIDP_QUERY_API_TOKEN in the
backend's MongoDB system_config so the NIDP Console works.

Run ON the Nivesh app VM (or inside the backend Docker container):

  # Option A — inside the Docker container:
  docker exec -it nivesh-backend \
    python3 /app/backend/scripts/set_nidp_secrets.py

  # Option B — on the host VM with the backend venv:
  cd /opt/nivesh/repo
  MONGO_URL="$(grep MONGO_URL /opt/nivesh/.env.prod | cut -d= -f2-)" \
    python3 backend/scripts/set_nidp_secrets.py

Env vars (all optional — script has safe defaults):
  MONGO_URL            — MongoDB connection string (reads from .env.prod if unset)
  DB_NAME              — database name (default: nivesh_prod)
  NIDP_QUERY_API_URL   — override URL   (default: http://10.160.0.3:8090)
  NIDP_QUERY_API_TOKEN — override token (reads from /opt/nidp/query_api.env if unset)
  TARGET_ENV           — production | preview (default: production)
"""
from __future__ import annotations
import os, sys, asyncio
from datetime import datetime, timezone

NIDP_VM_IP    = "10.160.0.3"
QUERY_API_PORT = 8090
TOKEN_FILE    = "/opt/nidp/query_api.env"

def read_token_from_file() -> str | None:
    try:
        with open(TOKEN_FILE) as f:
            for line in f:
                if line.startswith("NIDP_QUERY_API_TOKEN="):
                    return line.strip().split("=", 1)[1]
    except FileNotFoundError:
        pass
    return None

async def main() -> None:
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        print("ERROR: motor not installed. Run: pip install motor")
        sys.exit(1)

    # --- values to set ---
    url   = os.environ.get("NIDP_QUERY_API_URL")   or f"http://{NIDP_VM_IP}:{QUERY_API_PORT}"
    token = os.environ.get("NIDP_QUERY_API_TOKEN") or read_token_from_file()
    if not token:
        print("ERROR: NIDP_QUERY_API_TOKEN not found in env or", TOKEN_FILE)
        sys.exit(1)

    target_env = os.environ.get("TARGET_ENV", "production").lower()
    doc_key    = f"secrets_{target_env}"

    # --- MongoDB connection ---
    mongo_url = os.environ.get("MONGO_URL")
    if not mongo_url:
        # Try to read from .env.prod
        env_prod = "/opt/nivesh/.env.prod"
        try:
            with open(env_prod) as f:
                for line in f:
                    if line.startswith("MONGO_URL="):
                        mongo_url = line.strip().split("=", 1)[1]
                        break
        except FileNotFoundError:
            pass
    if not mongo_url:
        print("ERROR: MONGO_URL not set and /opt/nivesh/.env.prod not found.")
        sys.exit(1)

    db_name = os.environ.get("DB_NAME", "nivesh_prod")
    client  = AsyncIOMotorClient(mongo_url)
    db      = client[db_name]
    now     = datetime.now(timezone.utc).isoformat()

    for key, val in [("NIDP_QUERY_API_URL", url), ("NIDP_QUERY_API_TOKEN", token)]:
        await db.system_config.update_one(
            {"key": doc_key},
            {
                "$set": {
                    f"values.{key}": val,
                    "env":        target_env,
                    "updated_at": now,
                    "updated_by": "set_nidp_secrets.py",
                },
                "$setOnInsert": {"key": doc_key},
            },
            upsert=True,
        )
        masked = val if key == "NIDP_QUERY_API_URL" else f"{val[:8]}…"
        print(f"  ✓  {key} = {masked}  →  system_config[{doc_key}]")

    client.close()
    print(f"\nDone. Restart the backend container to reload secrets from DB:")
    print(f"  docker restart nivesh-backend")

if __name__ == "__main__":
    asyncio.run(main())
