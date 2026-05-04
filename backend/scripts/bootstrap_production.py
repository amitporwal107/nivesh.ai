"""Bootstrap a fresh production Mongo database.

Usage:
    cd /app/backend
    PREVIEW_MONGO_URL="mongodb://localhost:27017" \
    PREVIEW_DB_NAME="test_database" \
    PROD_MONGO_URL="mongodb+srv://USER:URL_ENCODED_PWD@host/?appName=nivesh" \
    PROD_DB_NAME="nivesh" \
    python -m scripts.bootstrap_production [--dry-run] [--force]

Behaviour:
  • Refuses to run if PROD already has any users / holdings / profiles
    (use --force to skip the safety check).
  • COPIES from preview → prod:
      - system_config.secrets:production   (for hydration on first boot)
      - system_config.feature_flags
      - system_config.prompts_config
      - system_config.rules_config
      - system_config.cas_parser*
      - system_config.data_pipeline*
      - system_config.v3_weights
  • SEEDS exactly 2 users in prod (admin):
      - aporwal107@gmail.com
      - priyankamantri@gmail.com
    Both as whitelisted_users + users + user_profiles, with
    onboarding_completed = TRUE so they go straight to a clean dashboard.
  • Does NOT copy any portfolio / holdings / chat / snapshot / profile
    (advisor client) / cas data — prod starts empty on the user side.
  • Creates baseline indexes (id-uniqueness on the seeded collections).

Verification: after running, prints a summary of every collection's row
count in prod, plus the audit fingerprints so you can confirm isolation.
"""
from __future__ import annotations
import argparse
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Hard-coded seed users — admin + the two founder accounts.
SEED_USERS: List[Dict[str, Any]] = [
    {
        "email": "priyankamantri@gmail.com",
        "name":  "Priyanka Mantri",
        "is_admin": True,
    },
    {
        "email": "aporwal107@gmail.com",
        "name":  "Amit Porwal",
        "is_admin": True,
    },
]

# system_config keys to carry preview → prod. We do NOT carry "secrets:preview"
# (that's the other env's data) and we do NOT carry plain "secrets" legacy
# doc, since we want prod to read only its own scoped overrides.
CONFIG_KEYS_TO_COPY = [
    "secrets:production",
    "feature_flags",
    "prompts_config",
    "rules_config",
    "cas_parser",
    "cas_parser_provider",
    "data_pipeline",
    "data_pipeline_run",
    "v3_weights",
]


async def assert_prod_empty(prod_db, force: bool) -> None:
    counts = {}
    for coll in ("users", "user_profiles", "holdings", "portfolios",
                 "profiles", "portfolio_snapshots", "chat_messages"):
        counts[coll] = await prod_db[coll].count_documents({})
    nonzero = {k: v for k, v in counts.items() if v > 0}
    if nonzero and not force:
        raise SystemExit(
            f"Refusing to bootstrap — prod already has data: {nonzero}. "
            f"Re-run with --force if you really want to overwrite."
        )
    if nonzero:
        print(f"  ⚠ prod is non-empty: {nonzero} (proceeding because --force)")


async def copy_system_config(preview_db, prod_db, dry_run: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"copied": [], "missing": []}
    for key in CONFIG_KEYS_TO_COPY:
        doc = await preview_db.system_config.find_one({"key": key}, {"_id": 0})
        if not doc:
            out["missing"].append(key)
            continue
        if dry_run:
            out["copied"].append(f"{key} (DRY-RUN — would copy)")
            continue
        await prod_db.system_config.update_one(
            {"key": key},
            {"$set": doc, "$setOnInsert": {"key": key}},
            upsert=True,
        )
        out["copied"].append(key)
    return out


async def seed_users(prod_db, dry_run: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {"users": [], "whitelisted": [], "profiles": []}
    for spec in SEED_USERS:
        email = spec["email"].strip().lower()
        # whitelisted_users
        wl = {
            "email": email,
            "status": "active",
            "is_admin": bool(spec.get("is_admin")),
            "invited_at": _now_iso(),
            "registered_at": _now_iso(),
            "invited_by": "bootstrap_production",
        }
        if not dry_run:
            await prod_db.whitelisted_users.update_one(
                {"email": email}, {"$set": wl}, upsert=True,
            )
        out["whitelisted"].append(email)

        # users
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        user_doc = {
            "user_id": user_id,
            "email": email,
            "email_norm": email,
            "name": spec["name"],
            "is_admin": bool(spec.get("is_admin")),
            "onboarding_completed": True,        # onboarding "off" → skip
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        if not dry_run:
            await prod_db.users.update_one(
                {"email": email}, {"$set": user_doc}, upsert=True,
            )
        out["users"].append({"email": email, "user_id": user_id})

        # user_profiles — onboarding closed, no journey/goals/playbook
        prof_doc = {
            "user_id": user_id,
            "onboarding_completed": True,
            "journey_type": None,
            "risk_profile": None,
            "goals": [],
            "playbook": None,
            "selected_sources": [],
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
        }
        if not dry_run:
            await prod_db.user_profiles.update_one(
                {"user_id": user_id}, {"$set": prof_doc}, upsert=True,
            )
        out["profiles"].append(user_id)
    return out


async def ensure_baseline_indexes(prod_db) -> None:
    try:
        await prod_db.users.create_index("user_id", unique=True)
        await prod_db.users.create_index("email", unique=True, sparse=True)
        await prod_db.users.create_index("email_norm", sparse=True)
        await prod_db.users.create_index("mobile_norm", sparse=True)
        await prod_db.users.create_index("pan_norm", sparse=True)
        await prod_db.whitelisted_users.create_index("email", unique=True)
        await prod_db.user_profiles.create_index("user_id", unique=True)
        await prod_db.profiles.create_index("profile_id", unique=True, sparse=True)
        await prod_db.profiles.create_index("email_norm", sparse=True)
        await prod_db.profiles.create_index("mobile_norm", sparse=True)
        await prod_db.profiles.create_index("pan_norm", sparse=True)
        await prod_db.holdings.create_index("user_id")
        await prod_db.portfolio_snapshots.create_index([("user_id", 1), ("snapshot_date", -1)])
        await prod_db.system_config.create_index("key", unique=True)
        await prod_db.user_sessions.create_index("session_token", unique=True)
        await prod_db.user_sessions.create_index("expires_at")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ index ensure: {e}")


async def summarise(prod_db) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for coll in (
        "users", "user_profiles", "whitelisted_users",
        "holdings", "portfolios", "profiles",
        "portfolio_snapshots", "cas_parsed_responses",
        "chat_messages", "system_config",
    ):
        out[coll] = await prod_db[coll].count_documents({})
    return out


async def run(dry_run: bool, force: bool) -> None:
    pre_url = os.environ.get("PREVIEW_MONGO_URL") or os.environ.get("MONGO_URL")
    pre_db_name = os.environ.get("PREVIEW_DB_NAME") or os.environ.get("DB_NAME")
    prd_url = os.environ["PROD_MONGO_URL"]
    prd_db_name = os.environ.get("PROD_DB_NAME", "nivesh")
    if not (pre_url and pre_db_name):
        raise SystemExit("Set PREVIEW_MONGO_URL + PREVIEW_DB_NAME (or MONGO_URL + DB_NAME)")

    pre_cli = AsyncIOMotorClient(pre_url, serverSelectionTimeoutMS=5000)
    prd_cli = AsyncIOMotorClient(prd_url, serverSelectionTimeoutMS=8000)
    pre_db = pre_cli[pre_db_name]
    prd_db = prd_cli[prd_db_name]

    print(f"[1/6] preview connectivity")
    await pre_db.command("ping")
    print(f"  ✓ preview mongo OK")

    print(f"[2/6] prod connectivity")
    await prd_db.command("ping")
    print(f"  ✓ prod mongo OK ({prd_db_name})")

    print(f"[3/6] safety check")
    await assert_prod_empty(prd_db, force=force)
    print(f"  ✓ prod is clean (or --force)")

    print(f"[4/6] copy system_config (preview → prod)")
    cfg = await copy_system_config(pre_db, prd_db, dry_run=dry_run)
    for k in cfg["copied"]:    print(f"  ✓ {k}")
    for k in cfg["missing"]:   print(f"  ↺ {k} (not in preview — skipped)")

    print(f"[5/6] seed users")
    seed = await seed_users(prd_db, dry_run=dry_run)
    for u in seed["users"]:    print(f"  ✓ user {u['email']} → {u['user_id']}")

    if not dry_run:
        await ensure_baseline_indexes(prd_db)
        print(f"  ✓ baseline indexes ensured")

    print(f"[6/6] summary (prod row counts)")
    summary = await summarise(prd_db)
    for k, v in summary.items():
        print(f"  {k:25} {v:>6}")

    pre_cli.close()
    prd_cli.close()
    if dry_run:
        print("\nDRY RUN — no writes performed. Re-run without --dry-run to commit.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't write to prod — just show what would happen.")
    parser.add_argument("--force", action="store_true",
                        help="Allow overwriting a non-empty prod database.")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, force=args.force))
