# READ-ONLY: counts on staging Mongo. Allow-list projections; no user ids, tokens or env printed.
import os, asyncio, collections
from motor.motor_asyncio import AsyncIOMotorClient
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    names = set(await d.list_collection_names())
    want = ["desk_paper_trades","ai_trader_tickets","ai_trader_strategies","desk_strategy_plans","ai_watchlist_days","trade_journal",
            "paper_accounts","paper_account_ledger","risk_decisions","desk_price_alerts","kite_live_snapshot","kite_live_close"]
    for n in want:
        print(n, "exists" if n in names else "MISSING", (await d[n].estimated_document_count()) if n in names else "")
    print("other trade-ish collections:", sorted(x for x in names if any(k in x for k in ("trade","paper","ticket","plan","signal","journal","risk","order"))))
    t = d["desk_paper_trades"]
    proj = {"_id":0,"kind":1,"status":1,"exit_reason":1,"source.kind":1,"entry_rule":1,"max_hold_sessions":1,"rules_version":1,
            "strategy_version":1,"strategy_plan_id":1,"stop_underlying":1,"target_underlying":1,"note":1,"risk_decision_id":1,"user_id":1}
    rows = await t.find({}, proj).to_list(100000)
    c = collections.Counter((r.get("kind") or "cash", r.get("status"), r.get("exit_reason")) for r in rows)
    print("\n(kind, status, exit_reason) ->", sorted(c.items(), key=lambda x: -x[1]))
    print("source.kind:", collections.Counter(((r.get("source") or {}).get("kind")) for r in rows).most_common())
    print("rules_version:", collections.Counter(r.get("rules_version") for r in rows).most_common())
    print("entry_rule:", collections.Counter(r.get("entry_rule") for r in rows).most_common())
    print("max_hold_sessions set:", sum(1 for r in rows if r.get("max_hold_sessions")), "of", len(rows))
    print("strategy_version set:", sum(1 for r in rows if r.get("strategy_version")), "| risk_decision_id set:", sum(1 for r in rows if r.get("risk_decision_id")))
    strat = [r for r in rows if r.get("kind") == "strategy"]
    print("strategy trades:", len(strat), "with plan id:", sum(1 for r in strat if r.get("strategy_plan_id")),
          "with stop_underlying:", sum(1 for r in strat if r.get("stop_underlying") is not None),
          "with note 'Top by regime':", sum(1 for r in strat if str(r.get("note") or "").startswith("Top by regime")))
    print("distinct users with trades:", len({r.get('user_id') for r in rows}))
    tk = d["ai_trader_tickets"]
    trows = await tk.find({}, {"_id":0,"status":1,"mode":1,"trade_id":1,"rejected_by":1}).to_list(100000)
    print("\nai_trader_tickets (status, mode):", collections.Counter((r.get("status"), r.get("mode")) for r in trows).most_common())
    print("rejected_by:", collections.Counter(r.get("rejected_by") for r in trows if r.get("status")=="rejected").most_common())
    tids = [r["trade_id"] for r in trows if r.get("trade_id")]
    found = await t.count_documents({"_id": {"$in": tids}}) if tids else 0
    print("tickets with trade_id:", len(tids), "-> found in desk_paper_trades:", found)
    st = d["ai_trader_strategies"]
    srows = await st.find({}, {"_id":0,"stage":1,"runs":1,"spec.exit":1}).to_list(10000)
    print("\nai_trader_strategies:", len(srows), "stages:", collections.Counter(r.get("stage") for r in srows).most_common(),
          "runs total:", sum(len(r.get("runs") or []) for r in srows))
    print("spec.exit keys seen:", collections.Counter(tuple(sorted(((r.get("spec") or {}).get("exit") or {}).keys())) for r in srows).most_common())
    pl = d["desk_strategy_plans"]
    prow = await pl.find({}, {"_id":0,"plan.lifecycle.status":1,"plan.status":1}).to_list(10000)
    print("\ndesk_strategy_plans:", len(prow), "lifecycle.status:", collections.Counter(((r.get("plan") or {}).get("lifecycle") or {}).get("status") for r in prow).most_common(),
          "plan.status:", collections.Counter((r.get("plan") or {}).get("status") for r in prow).most_common())
    tj = d["trade_journal"]
    print("\ntrade_journal status:", collections.Counter(r.get("status") for r in await tj.find({}, {"_id":0,"status":1}).to_list(10000)).most_common())
asyncio.run(m())
