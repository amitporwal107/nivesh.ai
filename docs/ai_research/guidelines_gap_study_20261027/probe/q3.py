# READ-ONLY: the stored AI watchlist day(s): cash and F&O rows, allow-listed fields only.
import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    for day in await d["ai_watchlist_days"].find({}, {"_id":0,"list_date":1,"built_at":1,"cash":1,"fno":1,"notes.cash_rules_version":1,"notes.fno_rules_version":1,"notes.cash_data_as_of":1}).to_list(10):
        print("list_date", day.get("list_date"), "built_at", day.get("built_at"), "rules", day.get("notes"))
        for e in day.get("cash") or []:
            sc = e.get("scanner") or {}
            pf = e.get("preferred") or {}
            print(" CASH", e.get("rank"), e.get("symbol"), "bucket", sc.get("bucket"), "close", sc.get("close"), sc.get("close_date"),
                  "| scanner entry", sc.get("entry"), "stop", sc.get("stop"), "target", sc.get("target"), "rr", sc.get("risk_reward"),
                  "| plan", e.get("plan_status"), "| pref", pf.get("id"), pf.get("label"), "max_loss", pf.get("max_loss"), "rr_net", pf.get("reward_risk_net"),
                  "| sized", e.get("sized_shares"), "| keys", sorted(e.keys()))
        for e in (day.get("fno") or [])[:10]:
            print(" FNO", e.get("rank"), e.get("underlying"), e.get("structure"), "view", e.get("view"), "max_loss", e.get("max_loss"), "rr", e.get("reward_risk"),
                  "stop?", any(k in e for k in ("stop","stop_underlying","levels")), "| keys", sorted(e.keys()))
asyncio.run(m())
