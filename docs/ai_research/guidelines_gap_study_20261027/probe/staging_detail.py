# READ-ONLY. Allow-list projections; user ids hashed; free-text fields not printed.
import os, asyncio, hashlib
from motor.motor_asyncio import AsyncIOMotorClient
H = lambda u: hashlib.sha256(str(u).encode()).hexdigest()[:8]
async def m():
    d = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    proj = {"_id": 0, "user_id": 1, "kind": 1, "status": 1, "symbol": 1, "quantity": 1, "entry_price": 1, "stop_price": 1,
            "target_price": 1, "opened_at": 1, "closed_at": 1, "paper_reserved_rs": 1, "source.kind": 1, "exit_reason": 1,
            "realized_pnl_rs": 1, "family": 1, "legs.kind": 1, "legs.side": 1, "legs.lots": 1, "legs.lot_size": 1,
            "legs.entry_price": 1, "legs.strike": 1, "legs.option_type": 1, "risk_decision_id": 1, "entry_rule": 1}
    trades = [t async for t in d.desk_paper_trades.find({}, proj).sort("opened_at", 1)]
    accts = {a["user_id"]: a async for a in d.paper_accounts.find({}, {"_id": 0, "user_id": 1, "starting_capital_rs": 1, "cash_rs": 1, "blocked_rs": 1})}
    print("ALL desk_paper_trades (oldest first):")
    for t in trades:
        k = t.get("kind") or "cash"
        if k == "cash":
            e, s, q = t["entry_price"], t["stop_price"], t["quantity"]
            tgt = t.get("target_price")
            rr = round((tgt - e) / (e - s), 2) if tgt else None
            print(f"  u={H(t['user_id'])} {k} {t['status']:6} {t['symbol']:12} qty={q} entry={e} stop={s} tgt={tgt} RR={rr} "
                  f"notional={q*e:,.0f} stop_risk={q*(e-s):,.0f} stop_dist%={round((e-s)/e*100,2)} reserved={t.get('paper_reserved_rs')} "
                  f"src={(t.get('source') or {}).get('kind')} rule={t.get('entry_rule')} opened={t['opened_at'][:16]} exit={t.get('exit_reason')} pnl={t.get('realized_pnl_rs')} gate_id={'yes' if t.get('risk_decision_id') else 'no'}")
        else:
            print(f"  u={H(t['user_id'])} {k} {t['status']:6} {t.get('symbol')} family={t.get('family')} legs={[(l.get('kind'), l.get('side'), l.get('lots'), l.get('lot_size'), l.get('entry_price'), l.get('strike'), l.get('option_type')) for l in t.get('legs') or []]} "
                  f"reserved={t.get('paper_reserved_rs')} opened={t['opened_at'][:16]} exit={t.get('exit_reason')} pnl={t.get('realized_pnl_rs')} gate_id={'yes' if t.get('risk_decision_id') else 'no'}")
    for uid, a in accts.items():
        open_res = sum(float(t.get("paper_reserved_rs") or 0) for t in trades if t["user_id"] == uid and t["status"] == "open")
        cap = a.get("starting_capital_rs")
        opn = [t for t in trades if t["user_id"] == uid and t["status"] == "open" and (t.get("kind") or "cash") == "cash"]
        tot_risk = sum(t["quantity"] * (t["entry_price"] - t["stop_price"]) for t in opn)
        tot_notional = sum(t["quantity"] * t["entry_price"] for t in opn)
        print(f"paper_account u={H(uid)} starting={cap} cash={a.get('cash_rs')} blocked={a.get('blocked_rs')} | sum(open paper_reserved_rs)={open_res} "
              f"| open cash positions={len(opn)} total open stop-risk={tot_risk:,.0f} ({tot_risk/cap*100:.2f}% of starting) gross={tot_notional:,.0f} ({tot_notional/cap*100:.1f}%)")
    print("risk_decisions (allow-list):")
    async for r in d.risk_decisions.find({}, {"_id": 0, "user_id": 1, "at": 1, "action": 1, "outcome": 1, "source": 1, "reasons.code": 1,
                                              "path": 1, "mode": 1, "symbol": 1, "detail.capital_at_risk_rs": 1, "detail.code": 1, "detail.kill_switch": 1,
                                              "detail.halted": 1, "policy_version": 1, "snapshot_version": 1, "correlation_id": 1}).sort("at", 1):
        print(f"  {r.get('at','')[:19]} u={H(r.get('user_id'))} {r.get('action')} {r.get('outcome')} src={r.get('source')} sym={r.get('symbol')} "
              f"codes={[x.get('code') for x in r.get('reasons') or []]} car={(r.get('detail') or {}).get('capital_at_risk_rs')} ks={(r.get('detail') or {}).get('kill_switch')} "
              f"pv={r.get('policy_version')} snap={r.get('snapshot_version')} cid={'yes' if r.get('correlation_id') else 'no'}")
    print("risk_control_audit (allow-list):")
    async for r in d.risk_control_audit.find({}, {"_id": 0, "user_id": 1, "at": 1, "action": 1, "field": 1, "before": 1, "after": 1, "actor": 1}).sort("at", 1):
        print(f"  {r.get('at','')[:19]} u={H(r.get('user_id'))} actor={H(r.get('actor'))} {r.get('action')} {r.get('before')}->{r.get('after')}")
    print("paper_account_ledger:")
    async for r in d.paper_account_ledger.find({}, {"_id": 0, "at": 1, "action": 1, "amount_rs": 1, "net_pnl_rs": 1, "symbol": 1}).sort("at", 1):
        print(f"  {r.get('at','')[:19]} {r.get('action')} amt={r.get('amount_rs')} pnl={r.get('net_pnl_rs')} {r.get('symbol')}")
asyncio.run(m())
