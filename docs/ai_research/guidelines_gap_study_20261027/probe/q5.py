# READ-ONLY: ICICIBANK features on 26 Oct, then the shipped pure functions applied to them (no I/O beyond the SELECT).
import asyncio, sys, json
sys.path.insert(0, "/app")
from services import pg_client
from services.positional_engine import trade_planner, setup_rules
from services.strategy_plan.candidates import scenario_levels
from services.strategy_plan.rules import RULES
async def m():
    pool = await pg_client.get_pool()
    async with pool.acquire() as c:
        cols = [r["column_name"] for r in await c.fetch("SELECT column_name FROM information_schema.columns WHERE table_name='stock_technical_features'")]
        print("stf columns:", cols)
        r = await c.fetchrow("SELECT * FROM stock_technical_features WHERE nse_symbol='ICICIBANK' AND as_of_date='2026-10-26'")
    d = dict(r)
    raw = d.get("components")
    raw = json.loads(raw) if isinstance(raw, str) else raw
    feats = (raw or {}).get("raw") or {}
    keys = ["close","atr_14","atr_pct","high_20d","swing_low_20","swing_high_20","high_52w","sma_50","ema_20"]
    f = {k: feats.get(k, d.get(k)) for k in keys}
    print("features:", f, "| stage:", d.get("stage"), "| resistance_level:", d.get("resistance_level"))
    p = trade_planner.plan(d.get("stage"), {k: (float(v) if v is not None else None) for k, v in f.items()})
    print("trade_planner.plan ->", p)
    atr = float(f["atr_14"]); entry = p["entry"]; stop = p["stoploss"]
    print("pick stop distance / ATR =", round((entry - stop) / atr, 3), " | entry-1.5ATR =", round(entry - 1.5 * atr, 2), " swing_low*0.995 =", round(float(f["swing_low_20"]) * 0.995, 2) if f.get("swing_low_20") else None)
    print("plan stop_basis label says:", f"{RULES['targets']['stop_atr_multiple']:g} x ATR below the trigger/EMA20", "| watchlist rule stop_atr_multiple:", setup_rules.WATCHLIST["stop_atr_multiple"])
    close = 1403.0  # the stored 26 Oct list's close for ICICIBANK
    print("strategy-plan cash candidate levels (entry = last close, stop = the pick's stop):",
          scenario_levels(close, True, stop, atr, float(d["resistance_level"]) if d.get("resistance_level") is not None else None, None))
asyncio.run(m())
