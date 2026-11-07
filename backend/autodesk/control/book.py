"""The account book the risk engine checks a new plan against.

Equity is read from the capital ledger (execution/capital.py). What a new plan competes with is the account's
COMMITMENTS: approved plans not yet handed to execution, active reservations and open positions. Read-only.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from .. import store


@dataclass
class Commitment:
    trade_id: str
    plan_version: int
    instrument: str
    sector: str
    strategy_type: str
    max_loss_rs: Decimal
    capital_rs: Decimal
    fno: bool


@dataclass
class Book:
    account_id: str
    equity_rs: Decimal
    starting_capital_rs: Decimal
    pending: list[Commitment] = field(default_factory=list)
    basis: str = "equity from the capital ledger; commitments = approved plans, reservations, open positions"
    loss_limits: Optional[dict] = None    # Phase 3: {"daily_loss"|"weekly_loss"|"drawdown": detail when breached, else None}

    @property
    def pending_risk_rs(self) -> Decimal:
        return sum((c.max_loss_rs for c in self.pending), Decimal("0"))

    @property
    def pending_fno_capital_rs(self) -> Decimal:
        return sum((c.capital_rs for c in self.pending if c.fno), Decimal("0"))

    def sector_capital_rs(self, sector: str) -> Decimal:
        return sum((c.capital_rs for c in self.pending if c.sector == sector), Decimal("0"))

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["equity_rs"] = str(self.equity_rs)
        d["starting_capital_rs"] = str(self.starting_capital_rs)
        d["pending"] = [{**asdict(c), "max_loss_rs": str(c.max_loss_rs), "capital_rs": str(c.capital_rs)}
                        for c in self.pending]
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Book":
        return cls(account_id=d["account_id"], equity_rs=Decimal(str(d["equity_rs"])),
                   starting_capital_rs=Decimal(str(d["starting_capital_rs"])), basis=d.get("basis", ""),
                   loss_limits=d.get("loss_limits"),
                   pending=[Commitment(trade_id=c["trade_id"], plan_version=int(c["plan_version"]),
                                       instrument=c["instrument"], sector=c["sector"],
                                       strategy_type=c["strategy_type"], max_loss_rs=Decimal(str(c["max_loss_rs"])),
                                       capital_rs=Decimal(str(c["capital_rs"])), fno=bool(c["fno"]))
                            for c in d.get("pending", [])])


async def load_book(conn, tenant_id: str, account_id: str, as_of: datetime) -> Book:
    """Equity comes from the capital ledger and the position marks. What a new plan competes with is the account's
    commitments: approved plans that have no execution intent yet, plus the remaining risk and capital of every active
    reservation and open position (so a filled plan stays counted after its plan row expires)."""
    from ..execution import capital
    acc = await store.get_account(conn, tenant_id, account_id)
    view = await capital.balances(conn, tenant_id, account_id)
    rows = await conn.fetch(
        """SELECT p.trade_id, p.current_version, p.instrument, p.strategy_type, v.body
           FROM autodesk.trade_plans p
           JOIN autodesk.trade_plan_versions v ON v.trade_id = p.trade_id AND v.version = p.current_version
           WHERE p.tenant_id=$1 AND p.account_id=$2 AND p.status='APPROVED'
             AND EXISTS (SELECT 1 FROM autodesk.approvals a WHERE a.trade_id=p.trade_id
                         AND a.plan_version=p.current_version AND a.status='APPROVED'
                         AND (a.expires_at IS NULL OR a.expires_at > $3))
             AND NOT EXISTS (SELECT 1 FROM autodesk.execution_intents i WHERE i.trade_id=p.trade_id
                             AND i.plan_version=p.current_version AND i.status<>'REFUSED')""",
        tenant_id, account_id, as_of)
    pending = []
    for r in rows:
        b = r["body"]
        margin = b.get("margin_estimate") or {}
        pending.append(Commitment(
            trade_id=r["trade_id"], plan_version=r["current_version"], instrument=r["instrument"],
            sector=(b.get("market_context") or {}).get("sector") or "UNCLASSIFIED", strategy_type=r["strategy_type"],
            max_loss_rs=Decimal(str(b["max_loss_rs"])),
            capital_rs=Decimal(str(margin.get("amount_rs") or b["capital_required_rs"])),
            fno=bool(margin.get("fno", b.get("segment") != "CASH"))))
    for r in await conn.fetch(
            """SELECT r.trade_id, r.plan_version, r.instrument, r.sector, r.fno, r.risk_rs - r.risk_moved_rs AS risk_left,
                      r.capital_rs * (1 - r.risk_moved_rs / NULLIF(r.risk_rs, 0)) AS capital_left, p.strategy_type
               FROM autodesk.capital_reservations r JOIN autodesk.trade_plans p USING (trade_id)
               WHERE r.tenant_id=$1 AND r.account_id=$2 AND r.status='ACTIVE' AND r.risk_rs > r.risk_moved_rs""",
            tenant_id, account_id):
        pending.append(Commitment(trade_id=r["trade_id"], plan_version=r["plan_version"], instrument=r["instrument"],
                                  sector=r["sector"], strategy_type=r["strategy_type"], max_loss_rs=r["risk_left"],
                                  capital_rs=r["capital_left"] or Decimal("0"), fno=r["fno"]))
    for r in await conn.fetch(
            """SELECT trade_id, plan_version, instrument, sector, fno, strategy_type, open_risk_rs, capital_rs
               FROM autodesk.trade_positions WHERE tenant_id=$1 AND account_id=$2 AND status='OPEN'""",
            tenant_id, account_id):
        pending.append(Commitment(trade_id=r["trade_id"], plan_version=r["plan_version"], instrument=r["instrument"],
                                  sector=r["sector"], strategy_type=r["strategy_type"], max_loss_rs=r["open_risk_rs"],
                                  capital_rs=r["capital_rs"], fno=r["fno"]))
    from ..lifecycle import limits as loss
    from ..market.view import IST
    cur = await loss.current(conn, tenant_id=tenant_id, account_id=account_id, session=as_of.astimezone(IST).date())
    codes = {b["code"]: b["detail"] for b in cur["blocks"]}
    dd = cur["measures"]["drawdown"]
    loss_limits = {"daily_loss": codes.get("DAILY_LOSS_LIMIT"), "weekly_loss": codes.get("WEEKLY_LOSS_LIMIT"),
                   "drawdown": (f"drawdown {dd['loss_pct']}% reached the {dd['limit_pct']}% limit" if dd["breached"] else None)}
    return Book(account_id=account_id, equity_rs=view.equity_rs, loss_limits=loss_limits,
                starting_capital_rs=Decimal(str(acc["starting_capital_rs"])), pending=pending,
                basis="equity from the capital ledger and position marks; commitments = approved plans without an intent, "
                      "remaining risk of active reservations, open positions")
