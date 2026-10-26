import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    async for t in d.desk_paper_trades.find({}, {"_id": 0, "symbol": 1, "opened_at": 1, "closed_at": 1, "exit_session": 1, "status": 1, "net_pnl_rs": 1}).sort("opened_at", 1):
        print(t.get("symbol"), t.get("status"), str(t.get("opened_at"))[:19], str(t.get("closed_at"))[:19], t.get("exit_session"), t.get("net_pnl_rs"))
asyncio.run(m())
