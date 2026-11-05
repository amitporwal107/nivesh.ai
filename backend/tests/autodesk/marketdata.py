"""TEST DATA — crafted market data for the agent and risk-engine tests. NOT real market data.

Option closes are Black-76 prices from services/option_pricing.py at a fixed volatility, so the chains are internally
consistent (put-call parity, smile-free). One F&O stock (ACME, lot 500, spot 1000), one cash-only stock (PLAINCO) and
one index (IDX, lot 65, spot 24000). Plans are built for SD from the F&O bhavcopy of FNO_DAY.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Iterable, Optional

from services import option_pricing as op

from autodesk import contracts as C
from autodesk.accounts import default_policy_body
from autodesk.agents.base import AgentContext
from autodesk.market.view import IST, Bar, FnoContract, FrozenMarketView, published_at

FNO_DAY = date(2026, 11, 5)
SD = date(2026, 11, 6)                      # the session the plans are for
AS_OF = datetime(2026, 11, 6, 8, 45, tzinfo=IST).astimezone(timezone.utc)
NEAR = date(2026, 11, 10)                   # 4 days after SD: below min_days_to_expiry (7)
EXP = date(2026, 11, 24)
CAPITAL = Decimal("10000000")               # ₹1.00 Cr, as in the owner's design


def _sessions() -> list[date]:
    d, out = date(2026, 6, 1), []
    while d <= SD:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


SESSIONS = _sessions()


def bars(close: Decimal, *, step: Decimal = Decimal("2"), volume: int = 2_000_000) -> list[Bar]:
    """A gentle up-trend ending at `close` on FNO_DAY."""
    days = [d for d in SESSIONS if d <= FNO_DAY]
    out = []
    for i, d in enumerate(days):
        px = close - step * (len(days) - 1 - i)
        out.append(Bar(day=d, open=px - 1, high=px + 5, low=px - 5, close=px, volume=volume,
                       turnover_rs=px * volume))
    return out


def chain(underlying: str, *, spot: Decimal, fut: Decimal, step: int, n: int, vol: float, lot: int, expiry: date,
          untraded: Iterable[tuple[int, str]] = ()) -> list[FnoContract]:
    untraded = set(untraded)
    t = op.year_fraction(op.days_between(FNO_DAY, expiry))
    rows = [FnoContract(day=FNO_DAY, underlying=underlying, kind="FUT", expiry=expiry, strike=None, close=fut,
                        settle=fut, underlying_price=spot, open_interest=1_000_000, change_in_oi=0,
                        traded_volume=5000, lot_size=lot)]
    for i in range(-n, n + 1):
        k = int(spot) + step * i
        for kind in ("CE", "PE"):
            px = max(round(op.price(kind, float(fut), float(k), t, vol), 2), 0.05)
            rows.append(FnoContract(day=FNO_DAY, underlying=underlying, kind=kind, expiry=expiry,
                                    strike=Decimal(k), close=Decimal(str(px)), settle=Decimal(str(px)),
                                    underlying_price=spot, open_interest=50_000, change_in_oi=0,
                                    traded_volume=0 if (k, kind) in untraded else 1000, lot_size=lot))
    return rows


def acme_fno(**kw) -> list[FnoContract]:
    near = chain("ACME", spot=Decimal("1000"), fut=Decimal("1001"), step=20, n=8, vol=0.25, lot=500, expiry=NEAR)
    return near + chain("ACME", spot=Decimal("1000"), fut=Decimal("1005"), step=20, n=8, vol=0.25, lot=500,
                        expiry=EXP, **kw)


def idx_fno(vol: float = 0.13) -> list[FnoContract]:
    return chain("IDX", spot=Decimal("24000"), fut=Decimal("24050"), step=50, n=40, vol=vol, lot=65, expiry=EXP)


def data(*, acme: Optional[list] = None, idx: Optional[list] = None) -> dict[str, Any]:
    return {"sessions": SESSIONS,
            "bars": {"ACME": bars(Decimal("1000")), "PLAINCO": bars(Decimal("500"), step=Decimal("1"))},
            "fno": {"ACME": acme if acme is not None else acme_fno(), "IDX": idx if idx is not None else idx_fno()},
            "vix": {d: Decimal("13.2") for d in SESSIONS},
            "sector": {"ACME": "Capital Goods", "PLAINCO": "Textiles"}}


def view(d: Optional[dict] = None, as_of: datetime = AS_OF) -> FrozenMarketView:
    return FrozenMarketView(as_of, d or data())


def account(**over) -> dict:
    a = {"account_id": "ACC-T", "tenant_id": "t-agents", "name": "desk", "kind": "PAPER",
         "operating_mode": "AUTONOMOUS_PAPER", "status": "ACTIVE", "starting_capital_rs": CAPITAL}
    a.update(over)
    return a


def policy(**over) -> dict:
    body = default_policy_body()
    body.update(over)
    return {"policy_id": "POL-T", "version": 1, "body": C.PolicyBody.model_validate(body).model_dump(mode="json")}


def signal(instrument: str, segment: C.Segment, direction: C.Direction, *, ref: Optional[str], inv: Optional[str],
           targets: Iterable[str] = (), category: C.SignalCategory = C.SignalCategory.BREAKOUT, score: int = 75,
           sector: Optional[str] = None) -> C.Signal:
    r = Decimal(ref) if ref else None
    return C.Signal(tenant_id="t-agents", instrument=instrument, segment=segment, direction=direction,
                    category=category, signal_score=Decimal(score),
                    entry_zone={"low": r * Decimal("0.99"), "high": r * Decimal("1.005")} if r else None,
                    invalidation_price=Decimal(inv) if inv else None, targets=[Decimal(t) for t in targets],
                    reference_price=r, fno_eligible=segment != C.Segment.CASH, sector=sector,
                    data_as_of=published_at(FNO_DAY, "cash"), session_date=SD, model_version="test",
                    rule_version="test", expires_at=datetime(2026, 11, 6, 15, 30, tzinfo=IST))


def ctx(market: FrozenMarketView, inputs: dict, *, acct: Optional[dict] = None, pol: Optional[dict] = None) -> AgentContext:
    return AgentContext(tenant_id="t-agents", account=acct or account(), policy=pol or policy(), market=market,
                        as_of=AS_OF, workflow_id="WF-T", inputs=inputs)


def task(task_type: C.TaskType) -> C.TaskSpec:
    owner = C.TASK_OWNER[task_type]
    schema = C.TASK_OUTPUT_SCHEMA[task_type]
    return C.TaskSpec(workflow_id="WF-T", tenant_id="t-agents", account_id="ACC-T", to_agent=owner,
                      task_type=task_type, required_output_schema=schema)
