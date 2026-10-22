"""Live bid/ask for option contracts from the signed-in user's OWN connected broker session. Read only.

The F&O data in this system is one end-of-day NSE file with no bid or ask. A broker's quote API does carry the best bid and offer, so
when the user has a live native session with a broker whose quote read is wired here, the plan's `bid_ask` evidence is read from it,
labelled live or delayed with the quote's own trade time. Otherwise the snapshot is a failure with the reason and the evidence stays
`unavailable`. Nothing is stored, nothing is ordered: the only broker calls are the holdings read (to learn the broker's own stock
code for the underlying) and the quotes read.

Brokers wired: ICICI Direct (Breeze `/quotes`, which returns best_bid_price / best_offer_price). Zerodha's adapter has no quote read
in this repository and the other adapters carry none; each is a one-class addition to `default_readers()`.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .evidence import num, src_fail, src_ok
from .rules import RULES

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
VERSION = "broker-quote-v1"


class QuoteUnavailable(Exception):
    """A broker cannot give this quote, with the plain reason."""


def _int(v: Any) -> Optional[int]:
    f = num(v)
    return int(f) if f is not None else None


def _ist_iso(text: Any, fmt: str) -> Optional[str]:
    try:
        return datetime.strptime(str(text).strip(), fmt).replace(tzinfo=IST).isoformat()
    except (TypeError, ValueError):
        return None


class IciciDepthReader:
    """ICICI Direct (Breeze). The stock code of the underlying is ICICI's own (not the NSE symbol); it is read from the user's own ICICI
    holdings by ISIN. The adapter functions are injectable for tests."""

    def __init__(self, fetch_holdings: Optional[Callable] = None, signed_get: Optional[Callable] = None,
                 payload: Optional[Callable] = None, contract_ref: Optional[Callable] = None, pause_seconds: float = 0.3):
        self._fetch_holdings, self._signed_get, self._payload, self._ref = fetch_holdings, signed_get, payload, contract_ref
        self._pause = pause_seconds

    def _wire(self) -> None:
        if self._signed_get is None:
            from services.brokers import icicidirect as ic
            self._fetch_holdings = self._fetch_holdings or ic.fetch_holdings
            self._signed_get, self._payload, self._ref = ic._signed_get, ic._contract_payload, ic.ContractRef

    async def _code(self, token: Any, underlying: str, isin: Optional[str]) -> str:
        if not isin:
            raise QuoteUnavailable(f"ICICI Direct's stock code for {underlying} cannot be found: the underlying's ISIN is unknown")
        for h in await self._fetch_holdings(token) or []:
            if str(getattr(h, "isin", "") or "").upper() == isin.upper() and getattr(h, "symbol", None):
                return str(h.symbol).upper()
        raise QuoteUnavailable(f"ICICI Direct's stock code for {underlying} is not known: this repository has no NSE-symbol to ICICI-code map, "
                               f"so it is read from the user's own ICICI holdings and {underlying} is not held there")

    async def read(self, token: Any, underlying: str, isin: Optional[str], contracts: List[Dict[str, Any]]) -> List[Optional[Dict[str, Any]]]:
        self._wire()
        code = await self._code(token, underlying, isin)
        out: List[Optional[Dict[str, Any]]] = []
        for i, c in enumerate(contracts):
            if i:
                await asyncio.sleep(self._pause)           # a burst of /quotes reads answered 503 in earlier recordings
            ref = self._ref(symbol=code, exchange="NFO", instrument_type=c["instrument_type"], expiry=c["expiry"], strike=c.get("strike"))
            rows = await self._signed_get("quotes", self._payload(ref), token, "quote")
            row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
            out.append(None if row is None else {
                "bid": num(row.get("best_bid_price")), "ask": num(row.get("best_offer_price")),
                "bid_qty": _int(row.get("best_bid_quantity")), "ask_qty": _int(row.get("best_offer_quantity")),
                "ltp": num(row.get("ltp")), "last_traded_at": _ist_iso(row.get("ltt"), "%d-%b-%Y %H:%M:%S")})
        return out


def default_readers() -> Dict[str, Tuple[str, Any]]:
    return {"icicidirect": ("ICICI Direct", IciciDepthReader())}


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=IST)


def _shape(c: Dict[str, Any], q: Optional[Dict[str, Any]], now: datetime) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """(quote, None) or (None, why it was skipped). A book with no bid, no ask or a crossed book is skipped, never repaired."""
    if not q:
        return None, f"{c['label']}: the broker returned no quote"
    bid, ask = num(q.get("bid")), num(q.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None, f"{c['label']}: no bid or ask in the order book"
    if ask < bid:
        return None, f"{c['label']}: crossed book (ask {ask:g} below bid {bid:g})"
    mid = (bid + ask) / 2
    when = _parse(q.get("last_traded_at"))
    age = round((now - when).total_seconds()) if when else None
    mode = "untimed" if age is None else "live" if 0 <= age <= RULES["quotes"]["live_max_age_seconds"] else "delayed"
    return ({"label": c["label"], "instrument_type": c["instrument_type"], "strike": c.get("strike"), "expiry": c["expiry"], "bid": bid, "ask": ask,
             "bid_qty": q.get("bid_qty"), "ask_qty": q.get("ask_qty"), "ltp": num(q.get("ltp")), "last_traded_at": q.get("last_traded_at"),
             "mode": mode, "age_seconds": age, "spread": round(ask - bid, 2), "spread_pct": round((ask - bid) / mid * 100, 2)}, None)


async def read_option_bid_ask(accounts: List[Dict[str, Any]], underlying: str, isin: Optional[str], contracts: List[Dict[str, Any]], *,
                              load_token: Callable[[Dict[str, Any]], Any], is_live: Callable[[Dict[str, Any]], bool],
                              readers: Optional[Dict[str, Tuple[str, Any]]] = None, now: Optional[datetime] = None,
                              timeout: Optional[float] = None) -> Dict[str, Any]:
    """A source snapshot (evidence.src_ok / src_fail). Never raises."""
    readers = readers if readers is not None else default_readers()
    now = (now or datetime.now(timezone.utc)).astimezone(IST)
    timeout = timeout if timeout is not None else RULES["quotes"]["read_timeout_seconds"]
    src = "broker quote API via the user's own live session (read-only; nothing is ordered)"
    usable = [a for a in accounts if a.get("broker") in readers and is_live(a)]
    names = ", ".join(sorted(d for d, _ in readers.values()))
    if not usable:
        return src_fail(f"no connected broker with a live session can quote option contracts (supported: {names})", src)
    errors: List[str] = []
    for acc in usable:
        display, reader = readers[acc["broker"]]
        try:
            rows = await asyncio.wait_for(reader.read(load_token(acc), underlying, isin, contracts), timeout)
        except asyncio.TimeoutError:
            errors.append(f"{display}: quote read timed out after {timeout:g}s")
            continue
        except QuoteUnavailable as e:
            errors.append(f"{display}: {e}")
            continue
        except Exception as e:  # noqa: BLE001 — a failed broker read is unavailable evidence, never a failed plan; the message never carries a token
            logger.warning("strategy plan broker quote failed broker=%s error=%s", acc.get("broker"), type(e).__name__)
            errors.append(f"{display}: {type(e).__name__}: {str(e)[:120]}")
            continue
        quotes, skipped = [], []
        for c, q in zip(contracts, rows):
            shaped, why = _shape(c, q, now)
            if shaped:
                quotes.append(shaped)
            else:
                skipped.append(why)
        return src_ok({"broker": acc["broker"], "display": display, "read_at": now.isoformat(timespec="seconds"), "quotes": quotes, "skipped": skipped},
                      f"{display} quote API via the user's own live session (read-only; nothing is ordered)", now.date().isoformat(), VERSION)
    return src_fail("; ".join(errors), src)
