"""Execution adapters (ARCH §9.1–9.2, §10.4). The mode router picks exactly one from the server-side account row; client
input never chooses. There are paper adapters and a shadow stub. No adapter can reach a broker and none exists that could:
LIVE_EXECUTION_AVAILABLE stays False (owner rule: Zerodha gives quotes only, read-only).

The contract's verbs are submit / amend / withdraw (the order-path guard reserves the broker names for services/oms/adapters).
ARCH §9.2's read methods (status, positions, funds, fills, margin) are the schema itself here: a paper adapter has no
external state to ask, so `reports.py` and the API read the ledger and the order tables.

SimulationPaperAdapter  prices from the session's daily row (market/session_bars). Refuses an order with no simulation id.
LivePaperAdapter        prices from live quotes (market/live_quotes). Refuses an order that has a simulation id.
ShadowAdapter           Phase 4 stub: refuses everything, so a SHADOW account cannot create orders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional, Protocol

from ..market.live_quotes import QuoteAnswer, check_quote
from ..market.session_bars import SessionBarSource
from ..market.view import DataUnavailable
from . import fill_model as fm
from . import orders as ord_

LIVE_EXECUTION_AVAILABLE = False


class AdapterRefused(RuntimeError):
    """This adapter does not take this order."""


@dataclass
class Priced:
    """One pricing pass over an intent's working orders."""
    fills: list[tuple[dict, fm.Decision]] = field(default_factory=list)
    rests: list[tuple[dict, fm.Decision]] = field(default_factory=list)
    reject: Optional[fm.Decision] = None


class ExecutionAdapter(Protocol):
    name: str

    async def submit(self, order: dict, idempotency_key: str) -> dict: ...
    async def amend(self, order: dict, changes: dict, idempotency_key: str) -> dict: ...
    async def withdraw(self, order: dict, idempotency_key: str) -> dict: ...
    async def health_check(self) -> dict: ...


class _PaperBase:
    name = "PAPER"

    async def amend(self, order: dict, changes: dict, idempotency_key: str) -> dict:
        raise AdapterRefused("changing a working paper order is not available in Phase 2; withdraw it instead")

    async def withdraw(self, order: dict, idempotency_key: str) -> dict:
        return {"accepted": True, "adapter": self.name, "order_id": order["order_id"], "simulated": True}


class SimulationPaperAdapter(_PaperBase):
    name = "PAPER_SIM"

    def __init__(self, bars: Optional[SessionBarSource], params: fm.FillParams):
        self.bars, self.params = bars, params

    async def health_check(self) -> dict:
        return {"adapter": self.name, "ok": self.bars is not None, "simulated": True, "broker": None}

    async def submit(self, order: dict, idempotency_key: str) -> dict:
        if not order.get("simulation_id"):
            raise AdapterRefused("the simulation adapter takes only orders of a simulation")
        return {"accepted": True, "adapter": self.name, "order_id": order["order_id"], "simulated": True}

    async def _print(self, o: dict, session: date) -> tuple[fm.OpenPrint, Optional[Any]]:
        bar = await self.bars.bar(ord_.leg_ref(o), session, clock_session=session)
        if bar is None:
            return fm.OpenPrint(exists=False), None
        return fm.OpenPrint(exists=True, open=bar.open, prev_close=bar.prev_close, traded=bar.traded,
                            traded_units=bar.traded_units, lot_size=bar.lot_size, source=bar.source), bar

    async def price_open(self, orders_: list[dict], *, session: date, seed: int, net_limit: Optional[Decimal],
                         invalidation: Optional[Decimal]) -> Priced:
        out = Priced()
        basket = len(orders_) > 1
        pairs: list[tuple[dict, fm.OrderView, fm.Decision]] = []
        for o in orders_:
            v = ord_.view(o, invalidation)
            try:
                p, _ = await self._print(o, session)
            except DataUnavailable as e:
                d = fm.rest("DATA_UNAVAILABLE", f"the data platform did not answer: {e}")
                if basket:
                    d = fm.reject("DATA_UNAVAILABLE", d.reason)
                pairs.append((o, v, d))
                continue
            pairs.append((o, v, fm.decide_open(v, p, self.params, fm.rng_for(seed, session, v.key, v.side))))
        if basket:
            bad, _net = fm.basket_finish([(v, d) for _o, v, d in pairs], net_limit)
            if bad is not None:
                out.reject = bad
                return out
        for o, _v, d in pairs:
            if d.action == "FILL":
                out.fills.append((o, d))
            elif d.action == "REJECT":
                out.reject = d
            else:
                out.rests.append((o, d))
        return out

    async def price_close(self, orders_: list[dict], *, session: date) -> Priced:
        """A resting limit, now the whole bar has happened. Several legs never rest."""
        out = Priced()
        for o in orders_:
            try:
                bar = await self.bars.bar(ord_.leg_ref(o), session, clock_session=session)
            except DataUnavailable as e:
                out.rests.append((o, fm.rest("DATA_UNAVAILABLE", f"the data platform did not answer: {e}")))
                continue
            r = fm.CloseRange(low=bar.low if bar else None, high=bar.high if bar else None,
                              traded=bar.traded if bar else False, traded_units=bar.traded_units if bar else 0,
                              source=bar.source if bar else "")
            d = fm.decide_close(ord_.view(o), r, self.params)
            (out.fills if d.action == "FILL" else out.rests).append((o, d))
        return out


class LivePaperAdapter(_PaperBase):
    name = "PAPER_LIVE"

    def __init__(self, quotes: Any, params: fm.FillParams):
        self.quotes, self.params = quotes, params

    async def health_check(self) -> dict:
        return {"adapter": self.name, "ok": self.quotes is not None, "simulated": True, "broker": None,
                "prices": "live quotes, read only"}

    async def submit(self, order: dict, idempotency_key: str) -> dict:
        if order.get("simulation_id"):
            raise AdapterRefused("the live desk's paper adapter refuses an order of a simulation")
        return {"accepted": True, "adapter": self.name, "order_id": order["order_id"], "simulated": True}

    def price(self, orders_: list[dict], answer: QuoteAnswer, *, now, net_limit: Optional[Decimal],
              invalidation: Optional[Decimal]) -> Priced:
        """Only a fresh quote can price. Anything else rests: the order retries on the next tick."""
        out = Priced()
        basket = len(orders_) > 1
        pairs: list[tuple[dict, fm.OrderView, fm.Decision]] = []
        for o in orders_:
            v = ord_.view(o, invalidation)
            q = answer.quotes.get(v.key)
            problem = check_quote(q, now)
            if problem:
                why = answer.problems.get(v.key) or answer.problems.get("*") or "no usable quote for this instrument"
                pairs.append((o, v, fm.rest(problem, why)))
                continue
            pairs.append((o, v, fm.decide_quote(v, q, self.params, whole=basket, last_quote_ref=o.get("last_quote_ref"))))
        if basket:
            waiting = [(o, d) for o, _v, d in pairs if d.action == "REST"]
            if waiting:                                  # all legs together or none: every leg waits, with the reason
                reason = waiting[0][1]
                out.rests = [(o, d if d.action == "REST" else fm.rest(reason.code or "BASKET_WAITING",
                                                                       f"another leg is waiting: {reason.reason}"))
                             for o, _v, d in pairs]
                return out
            rej = next((d for _o, _v, d in pairs if d.action == "REJECT"), None)
            if rej is not None:
                out.reject = rej
                return out
            net = sum((d.price * d.qty * (1 if v.side == "BUY" else -1) for _o, v, d in pairs), Decimal("0"))
            if net_limit is not None and net > net_limit:
                out.rests = [(o, fm.rest("BASKET_NET_LIMIT", f"net value {net} is past the net limit {net_limit}"))
                             for o, _v, _d in pairs]
                return out
        for o, _v, d in pairs:
            if d.action == "FILL":
                out.fills.append((o, d))
            elif d.action == "REJECT":
                out.reject = d
            else:
                out.rests.append((o, d))
        return out


class ShadowAdapter:
    """Phase 4 stub. Live shadow records hypothetical outcomes; it never creates an order."""
    name = "SHADOW"

    async def health_check(self) -> dict:
        return {"adapter": self.name, "ok": False, "note": "not available until Phase 4", "broker": None}

    async def submit(self, order: dict, idempotency_key: str) -> dict:
        raise AdapterRefused("the shadow adapter creates no orders; it is a Phase 4 stub")

    async def amend(self, order: dict, changes: dict, idempotency_key: str) -> dict:
        raise AdapterRefused("the shadow adapter has no orders")

    async def withdraw(self, order: dict, idempotency_key: str) -> dict:
        raise AdapterRefused("the shadow adapter has no orders")


ADAPTER_OF_KIND = {"SIMULATION": "PAPER_SIM", "PAPER": "PAPER_LIVE", "SHADOW": "SHADOW"}
EXECUTION_MODE_OF_KIND = {"SIMULATION": "SIMULATION", "PAPER": "PAPER", "SHADOW": "SHADOW"}


def route_name(account: dict) -> str:
    """Mode router: server-side, from the account row (ARCH §9.1, §12.3). Takes no client input."""
    return ADAPTER_OF_KIND[account["kind"]]


def known_adapters() -> Iterable[str]:
    return tuple(ADAPTER_OF_KIND.values())
