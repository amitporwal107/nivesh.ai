# READ-ONLY: exit blocks of the stored DSL strategy versions behind the three runs.
import asyncio, sys, json
sys.path.insert(0, "/app")
from services import pg_client
async def m():
    pool = await pg_client.get_pool()
    async with pool.acquire() as c:
        cols = [r["column_name"] for r in await c.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='strategy_versions' ORDER BY ordinal_position")]
        print("strategy_versions cols:", cols)
        speccol = next((x for x in ("spec", "spec_json", "definition") if x in cols), None)
        for r in await c.fetch(f"SELECT v.id::text AS vid, v.{speccol} AS spec FROM strategy_versions v WHERE v.id IN (SELECT version_id FROM strategy_runs)"):
            spec = json.loads(r["spec"]) if isinstance(r["spec"], str) else r["spec"]
            print(r["vid"][:8], "exit:", (spec or {}).get("exit"))
asyncio.run(m())
