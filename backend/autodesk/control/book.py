"""The account book the risk engine checks a new plan against.

Phase 1 has no fills, so there are no positions and equity is the starting capital. What a new plan competes with is
the account's COMMITMENTS: plans already APPROVED whose approval has not expired (they would be entered in Phase 2).
Read-only: this module never writes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

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
    basis: str = "Phase 1: equity = starting capital; commitments = approved, unexpired plans (no fills yet)"

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
                   pending=[Commitment(trade_id=c["trade_id"], plan_version=int(c["plan_version"]),
                                       instrument=c["instrument"], sector=c["sector"],
                                       strategy_type=c["strategy_type"], max_loss_rs=Decimal(str(c["max_loss_rs"])),
                                       capital_rs=Decimal(str(c["capital_rs"])), fno=bool(c["fno"]))
                            for c in d.get("pending", [])])


async def load_book(conn, tenant_id: str, account_id: str, as_of: datetime) -> Book:
    acc = await store.get_account(conn, tenant_id, account_id)
    rows = await conn.fetch(
        """SELECT p.trade_id, p.current_version, p.instrument, p.strategy_type, v.body
           FROM autodesk.trade_plans p
           JOIN autodesk.trade_plan_versions v ON v.trade_id = p.trade_id AND v.version = p.current_version
           WHERE p.tenant_id=$1 AND p.account_id=$2 AND p.status='APPROVED'
             AND EXISTS (SELECT 1 FROM autodesk.approvals a WHERE a.trade_id=p.trade_id
                         AND a.plan_version=p.current_version AND a.status='APPROVED'
                         AND (a.expires_at IS NULL OR a.expires_at > $3))""",
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
    cap = Decimal(str(acc["starting_capital_rs"]))
    return Book(account_id=account_id, equity_rs=cap, starting_capital_rs=cap, pending=pending)
