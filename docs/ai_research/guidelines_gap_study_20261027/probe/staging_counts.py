# READ-ONLY. Allow-list projections only. User ids are hashed. No env values are printed.
import os, asyncio, hashlib, collections, json
from motor.motor_asyncio import AsyncIOMotorClient
H = lambda u: hashlib.sha256(str(u).encode()).hexdigest()[:8]
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    names = set(await d.list_collection_names())
    wanted = ["desk_paper_trades","ai_trader_tickets","ai_trader_strategies","trade_journal","paper_accounts","paper_account_ledger",
              "risk_controls","risk_control_audit","risk_decisions","risk_equity_peaks","oms_orders","live_authorizations","desk_strategy_plans"]
    print("collections present:", {w: (w in names) for w in wanted})
    # feature flag: mode + allowlist size only
    ff = await d.system_config.find_one({"key": "feature_flags"}, {"_id": 0, "flags.fno_risk_gate": 1, "updated_at": 1})
    g = ((ff or {}).get("flags") or {}).get("fno_risk_gate")
    print("fno_risk_gate persisted:", None if g is None else {"mode": g.get("mode"), "allowlist_len": len(g.get("allowlist") or [])}, "| system_config.updated_at:", (ff or {}).get("updated_at"))
    # desk paper trades
    agg = d.desk_paper_trades.aggregate([{"$group": {"_id": {"kind": {"$ifNull": ["$kind", "cash"]}, "status": "$status", "src": "$source.kind"}, "n": {"$sum": 1}}}])
    print("desk_paper_trades by kind/status/source.kind:", sorted([(r["_id"].get("kind"), r["_id"].get("status"), r["_id"].get("src"), r["n"]) async for r in agg], key=str))
    print("desk_paper_trades distinct users:", len(await d.desk_paper_trades.distinct("user_id")))
    print("desk_paper_trades with risk_decision_id:", await d.desk_paper_trades.count_documents({"risk_decision_id": {"$exists": True}}),
          "| with paper_reserved_rs:", await d.desk_paper_trades.count_documents({"paper_reserved_rs": {"$ne": None, "$exists": True}}),
          "| open without paper_reserved_rs:", await d.desk_paper_trades.count_documents({"status": "open", "$or": [{"paper_reserved_rs": None}, {"paper_reserved_rs": {"$exists": False}}]}))
    # AI trader
    agg = d.ai_trader_tickets.aggregate([{"$group": {"_id": {"status": "$status", "mode": "$mode", "by": "$rejected_by"}, "n": {"$sum": 1}}}])
    print("ai_trader_tickets by status/mode/rejected_by:", sorted([(r["_id"].get("status"), r["_id"].get("mode"), r["_id"].get("by"), r["n"]) async for r in agg], key=str))
    print("ai_trader_strategies:", await d.ai_trader_strategies.count_documents({}), "| by stage:", sorted([(r["_id"], r["n"]) async for r in d.ai_trader_strategies.aggregate([{"$group": {"_id": "$stage", "n": {"$sum": 1}}}])], key=str))
    caps = [r.get("config", {}).get("initial_capital") async for r in d.ai_trader_strategies.find({}, {"_id": 0, "config.initial_capital": 1})]
    print("ai_trader_strategies initial_capital values:", collections.Counter(caps).most_common(10))
    # journal
    agg = d.trade_journal.aggregate([{"$group": {"_id": "$status", "n": {"$sum": 1}}}])
    print("trade_journal by status:", sorted([(r["_id"], r["n"]) async for r in agg], key=str))
    # paper accounts
    accts = [r async for r in d.paper_accounts.find({}, {"_id": 0, "user_id": 1, "starting_capital_rs": 1, "cash_rs": 1, "blocked_rs": 1})]
    print("paper_accounts:", len(accts), "| starting_capital values:", collections.Counter(a.get("starting_capital_rs") for a in accts).most_common(5))
    print("paper_account_ledger by action:", sorted([(r["_id"], r["n"]) async for r in d.paper_account_ledger.aggregate([{"$group": {"_id": "$action", "n": {"$sum": 1}}}])], key=str))
    # controls
    print("risk_controls rows:", await d.risk_controls.count_documents({}), "| kill_switch on:", await d.risk_controls.count_documents({"kill_switch": True}), "| halted:", await d.risk_controls.count_documents({"halted": True}))
    print("risk_control_audit rows:", await d.risk_control_audit.count_documents({}))
    agg = d.risk_decisions.aggregate([{"$group": {"_id": {"action": "$action", "outcome": "$outcome", "source": "$source"}, "n": {"$sum": 1}}}])
    print("risk_decisions by action/outcome/source:", sorted([(r["_id"].get("action"), r["_id"].get("outcome"), r["_id"].get("source"), r["n"]) async for r in agg], key=str))
    print("risk_equity_peaks:", await d.risk_equity_peaks.count_documents({}), "| oms_orders:", await d.oms_orders.count_documents({}),
          "| live_authorizations granted:", await d.live_authorizations.count_documents({"granted": True}))
    return d, accts
asyncio.run(m())
