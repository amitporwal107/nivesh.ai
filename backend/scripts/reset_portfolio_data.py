"""
Reset portfolio analysis data for ALL users.

What it WIPES (portfolio analysis state):
  • holdings, portfolios, upload_tasks
  • ai_insights, portfolio_analysis
  • chat_sessions, chat_messages, fund_performance_cache
  • gmail_imports

What it RESETS on user_profiles (onboarding flags):
  • onboarding_completed   → False
  • journey_type           → None
  • risk_profile           → None
  • playbook / goals / derived onboarding fields → cleared

What it PRESERVES:
  • users (accounts stay)
  • user_sessions (active logins stay)
  • whitelisted_users
  • gmail_tokens (so users don't have to reconnect Gmail)

Usage:
  cd /app/backend && python -m scripts.reset_portfolio_data
  cd /app/backend && python -m scripts.reset_portfolio_data --dry-run
"""
import asyncio
import argparse
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv("/app/backend/.env")

from motor.motor_asyncio import AsyncIOMotorClient

WIPE_COLLECTIONS = [
    "holdings",
    "portfolios",
    "upload_tasks",
    "ai_insights",
    "portfolio_analysis",
    "chat_sessions",
    "chat_messages",
    "fund_performance_cache",
    "gmail_imports",
    "gmail_oauth_states",  # transient state; safe to clear
]

RESET_ONBOARDING_FIELDS = {
    "onboarding_completed": False,
    "journey_type": None,
    "risk_profile": None,
    "playbook": None,
    "goals": [],
    "selected_sources": [],
}


async def run(dry_run: bool):
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        print("ERROR: MONGO_URL / DB_NAME not set in /app/backend/.env")
        sys.exit(1)

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]

    print(f"DB: {db_name}  mode: {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print("-" * 60)

    # Preview counts
    total_before = {}
    for col in WIPE_COLLECTIONS + ["users", "user_profiles", "user_sessions", "whitelisted_users", "gmail_tokens"]:
        total_before[col] = await db[col].count_documents({})

    print("Pre-state:")
    for col in sorted(total_before):
        print(f"  {col:<28} {total_before[col]:>8} docs")

    print("\nPortfolio analysis collections to wipe:")
    for col in WIPE_COLLECTIONS:
        print(f"  DELETE {col:<28} ({total_before[col]} docs)")
    print(f"\nOnboarding reset on `user_profiles` ({total_before['user_profiles']} docs):")
    for k, v in RESET_ONBOARDING_FIELDS.items():
        print(f"  SET {k} = {v!r}")
    print(f"\nPreserved: users, user_sessions, whitelisted_users, gmail_tokens")

    if dry_run:
        print("\n(dry-run) No writes performed.")
        return

    print("\nExecuting...")

    # 1. Wipe portfolio/analysis collections
    wiped = {}
    for col in WIPE_COLLECTIONS:
        res = await db[col].delete_many({})
        wiped[col] = res.deleted_count
        print(f"  ✓ {col:<28} deleted {res.deleted_count}")

    # 2. Reset onboarding flags on user_profiles
    now = datetime.now(timezone.utc).isoformat()
    update = {"$set": {**RESET_ONBOARDING_FIELDS, "updated_at": now}}
    reset_res = await db.user_profiles.update_many({}, update)
    print(f"  ✓ user_profiles reset       matched={reset_res.matched_count} modified={reset_res.modified_count}")

    print("\nPost-state:")
    for col in sorted(total_before):
        after = await db[col].count_documents({})
        diff = after - total_before[col]
        marker = "-" if diff < 0 else (" " if diff == 0 else "+")
        print(f"  {col:<28} {after:>8} docs   ({marker}{abs(diff)})")

    print("\nAll users will re-run onboarding on next login.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="preview only, no writes")
    args = parser.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
