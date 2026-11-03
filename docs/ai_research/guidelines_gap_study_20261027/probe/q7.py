# READ-ONLY: the DSL backtest runs' exit specs (allow-listed keys) and their trades' exit reasons per run.
import asyncio, sys, json
sys.path.insert(0, "/app")
from services import pg_client
async def m():
    pool = await pg_client.get_pool()
    async with pool.acquire() as c:
        cols = [r["column_name"] for r in await c.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='strategy_runs' ORDER BY ordinal_position")]
        print("strategy_runs cols:", cols)
        tcols = [r["column_name"] for r in await c.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='strategy_trades' ORDER BY ordinal_position")]
        print("strategy_trades cols:", tcols)
        spec_col = "spec_snapshot" if "spec_snapshot" in cols else ("spec" if "spec" in cols else None)
        sel = "id" + (f", {spec_col}" if spec_col else "") + (", created_at" if "created_at" in cols else "")
        for r in await c.fetch(f"SELECT {sel} FROM strategy_runs"):
            spec = r.get(spec_col) if spec_col else None
            spec = json.loads(spec) if isinstance(spec, str) else spec
            print("run", str(r["id"])[:8], "exit:", (spec or {}).get("exit"), r.get("created_at"))
        print([dict(x) for x in await c.fetch("SELECT run_id::text AS run, exit_reason, COUNT(*) n FROM strategy_trades GROUP BY 1,2 ORDER BY 1,3 DESC")])
asyncio.run(m())
