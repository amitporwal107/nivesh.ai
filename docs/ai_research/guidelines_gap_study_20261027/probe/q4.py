# READ-ONLY SELECTs on the app Postgres (portfolio DB) through the backend's own pool; nothing printed from env.
import asyncio, sys
sys.path.insert(0, "/app")
from services import pg_client
SYMS = ["ICICIBANK","SGMART","KOTAKBANK","LAURUSLABS","FEDERALBNK","UNIONBANK","COFORGE","CRISIL","MPHASIS","ACUTAAS"]
async def m():
    pool = await pg_client.get_pool()
    async with pool.acquire() as c:
        print("latest signal_date:", await c.fetchval("SELECT MAX(signal_date) FROM positional_signals"))
        rows = await c.fetch("""SELECT nse_symbol, signal_date, stage, entry_price, stoploss, target_price, risk_reward, engine_version
                                FROM positional_signals WHERE nse_symbol = ANY($1::text[]) AND signal_date >= '2026-10-20'
                                ORDER BY nse_symbol, signal_date""", SYMS)
        for r in rows:
            print(dict(r))
        print("--- tables:", [r["table_name"] for r in await c.fetch("""SELECT table_name FROM information_schema.tables
             WHERE table_schema='public' AND (table_name LIKE '%strategy%' OR table_name LIKE '%trade%' OR table_name LIKE '%signal%' OR table_name LIKE '%journal%')""")])
        for tname in ("strategy_runs", "strategy_trades"):
            try:
                print(tname, await c.fetchval(f"SELECT COUNT(*) FROM {tname}"))
            except Exception as e:
                print(tname, "error", type(e).__name__)
        try:
            print("strategy_trades exit_reason:", [dict(r) for r in await c.fetch("SELECT exit_reason, COUNT(*) n FROM strategy_trades GROUP BY 1 ORDER BY 2 DESC")])
        except Exception as e:
            print("exit_reason query error", type(e).__name__)
asyncio.run(m())
