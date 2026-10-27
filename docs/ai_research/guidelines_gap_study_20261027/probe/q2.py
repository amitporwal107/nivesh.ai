# READ-ONLY: open desk paper trades vs their levels; shapes of kite_live_close / snapshot (keys only).
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    t = d["desk_paper_trades"]
    proj = {"_id":1,"kind":1,"symbol":1,"status":1,"entry_price":1,"stop_price":1,"target_price":1,"quantity":1,"opened_at":1,
            "closed_at":1,"exit_reason":1,"exit_price":1,"exit_session":1,"checked_through":1,"entry_status":1,"flags":1,
            "realized_pnl_rs":1,"costs_rs":1,"net_pnl_rs":1,"source":1,"paper_reserved_rs":1,"sim_entry_price":1}
    for r in await t.find({}, proj).sort("opened_at", 1).to_list(100):
        r["_id"] = str(r["_id"])[:8]
        fl = [f.get("code") for f in (r.pop("flags", None) or [])]
        print(r, "flags:", fl)
    for n in ("kite_live_close", "kite_live_snapshot"):
        doc = await d[n].find_one({}, {"_id": 1})
        one = await d[n].find_one({})
        print("\n", n, "keys:", sorted(one.keys()) if one else None)
asyncio.run(m())
