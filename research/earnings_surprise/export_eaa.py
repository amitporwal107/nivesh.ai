"""Read-only export of Mongo event_ai_analysis RESULTS docs (the tracker's outlook proxy) as CSV on stdout.

Run inside the staging backend container (it holds MONGO_URL):
    sudo docker cp research/earnings_surprise/export_eaa.py nivesh-staging-app-backend:/tmp/export_eaa.py
    sudo docker exec -w /app/backend nivesh-staging-app-backend python /tmp/export_eaa.py > <data>/eaa.csv
Used only by exploratory test E2 (pre-registration §7): the docs were generated in Oct 2026, so they are not point-in-time.
"""
import asyncio
import csv
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

FIELDS = ("symbol", "event_ts", "analyzed_at", "net_impact_score", "net_band", "confidence_score", "materiality_score",
          "model_tag", "tool_isolation", "announcement_id", "exchange_category", "event_subtype")


async def main() -> None:
    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ.get("DB_NAME", "nivesh")]
    w = csv.writer(sys.stdout)
    w.writerow(FIELDS)
    cur = db["event_ai_analysis"].find({"event_type": "RESULTS", "mode": "single_full"}, {f: 1 for f in FIELDS})
    async for d in cur:
        w.writerow([d.get(f) for f in FIELDS])


asyncio.run(main())
