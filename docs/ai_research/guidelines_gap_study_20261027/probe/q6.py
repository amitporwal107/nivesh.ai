# READ-ONLY: the 26 Oct list's regime note and, for symbols on both boards, the two directions.
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    day = await d["ai_watchlist_days"].find_one({"list_date": "2026-10-26"}, {"_id":0,"notes.regime":1,"cash.symbol":1,"cash.scanner.bucket":1,"cash.plan_status":1,"cash.direction":1,"fno.underlying":1,"fno.structure":1,"fno.view":1,"fno.fit":1})
    print("regime:", (day.get("notes") or {}).get("regime"))
    cash = {e["symbol"]: e for e in day["cash"]}
    for f in day["fno"]:
        c = cash.get(f["underlying"])
        if c:
            print(f["underlying"], "| cash board:", c.get("direction"), (c.get("scanner") or {}).get("bucket"), "plan", c.get("plan_status"),
                  "| F&O board:", f["structure"], "view", f["view"], "fit", (f.get("fit") or {}).get("score"))
    f0 = day["fno"][0]
    print("fit.because[0..3] for", f0["underlying"], [(b.get("factor"), b.get("state")) for b in ((f0.get("fit") or {}).get("because") or [])][:4])
asyncio.run(m())
