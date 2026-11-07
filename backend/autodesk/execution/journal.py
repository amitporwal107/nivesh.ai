"""Trade journal (PRD §12.1): the chain Signal → Plan versions → Risk assessments → Approvals → Intent → Reservation →
Orders → Fills → Position → Marks, one append-only row per link. Summaries are narrative: AD-92 words stay out."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


async def record(c, *, tenant_id: str, account_id: str, simulation_id: Optional[str], trade_id: str, kind: str,
                 ref_id: str, summary: str, data: Optional[dict] = None, sim_time: Optional[datetime] = None) -> None:
    await c.execute(
        """INSERT INTO autodesk.trade_journal_entries (tenant_id, account_id, simulation_id, trade_id, kind, ref_id,
               summary, data, sim_time) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
           ON CONFLICT (trade_id, kind, ref_id) DO NOTHING""",
        tenant_id, account_id, simulation_id, trade_id, kind, ref_id, summary, data or {}, sim_time)


async def record_chain(c, *, tenant_id: str, plan: dict, sim_time: Optional[datetime]) -> None:
    """The links that exist before execution starts: signal, every plan version, every assessment, every approval row."""
    base = dict(tenant_id=tenant_id, account_id=plan["account_id"], simulation_id=plan["simulation_id"],
                trade_id=plan["trade_id"], sim_time=sim_time)
    if plan.get("signal_id"):
        s = await c.fetchrow("SELECT signal_id, instrument, category, signal_score, session_date FROM autodesk.signals "
                             "WHERE signal_id=$1 AND tenant_id=$2", plan["signal_id"], tenant_id)
        if s is not None:
            await record(c, **base, kind="SIGNAL", ref_id=s["signal_id"],
                         summary=f"{s['instrument']}: {s['category']} signal scored {s['signal_score']} "
                                 f"for the {s['session_date']} session",
                         data={"signal_score": str(s["signal_score"]), "category": s["category"]})
    for v in await c.fetch("""SELECT version, strategy_type, max_loss_rs, capital_required_rs, created_by, change_reason
                              FROM autodesk.trade_plan_versions WHERE trade_id=$1 ORDER BY version""", plan["trade_id"]):
        await record(c, **base, kind="PLAN_VERSION", ref_id=f"{plan['trade_id']}@{v['version']}",
                     summary=f"plan version {v['version']}: {v['strategy_type']} on {plan['instrument']}, "
                             f"maximum loss {v['max_loss_rs']}, capital {v['capital_required_rs']}",
                     data={"version": v["version"], "created_by": v["created_by"], "change_reason": v["change_reason"]})
    for a in await c.fetch("""SELECT assessment_id, plan_version, verdict, policy_version, engine_version
                              FROM autodesk.risk_assessments WHERE trade_id=$1 AND tenant_id=$2 ORDER BY created_at""",
                           plan["trade_id"], tenant_id):
        await record(c, **base, kind="RISK_ASSESSMENT", ref_id=a["assessment_id"],
                     summary=f"risk {a['verdict']} on version {a['plan_version']} ({a['engine_version']})",
                     data={"plan_version": a["plan_version"], "verdict": a["verdict"],
                           "policy_version": a["policy_version"]})
    for a in await c.fetch("""SELECT approval_id, plan_version, status, decided_by, created_at FROM autodesk.approvals
                              WHERE trade_id=$1 AND tenant_id=$2 ORDER BY created_at""", plan["trade_id"], tenant_id):
        await record(c, **base, kind="APPROVAL", ref_id=a["approval_id"],
                     summary=f"{a['status']} on version {a['plan_version']} by {a['decided_by']}",
                     data={"status": a["status"], "decided_by": a["decided_by"]})


async def list_entries(c, tenant_id: str, *, trade_id: Optional[str] = None, account_id: Optional[str] = None,
                       simulation_id: Optional[str] = None, after_seq: Optional[int] = None, limit: int = 500
                       ) -> list[dict[str, Any]]:
    """Oldest first from the cursor; with no cursor, the newest `limit` rows (ascending). Desk and simulated rows never
    mix, unless the read names one trade."""
    q, args = ["SELECT * FROM autodesk.trade_journal_entries WHERE tenant_id=$1 AND seq>$2"], [tenant_id, after_seq or 0]
    if trade_id is not None:
        args.append(trade_id); q.append(f"AND trade_id=${len(args)}")
    elif simulation_id is not None:
        args.append(simulation_id); q.append(f"AND simulation_id=${len(args)}")
    else:
        q.append("AND simulation_id IS NULL")
    if account_id is not None:
        args.append(account_id); q.append(f"AND account_id=${len(args)}")
    args.append(min(max(limit, 1), 5000))
    q.append(f"ORDER BY seq {'' if after_seq is not None else 'DESC '}LIMIT ${len(args)}")
    rows = [dict(r) for r in await c.fetch(" ".join(q), *args)]
    return rows if after_seq is not None else rows[::-1]
