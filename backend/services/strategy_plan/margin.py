"""Required margin for a candidate's legs, from the user's OWN Zerodha session through Kite's margin CALCULATOR. Read only.

Kite Connect's basket margin endpoint (`basket_order_margins`) works out the margin a set of orders WOULD need. It is a calculator:
it places, modifies and cancels nothing, and it is the only Kite method this module calls. With `consider_positions=False` the figure
is the requirement of the legs on their own, not netted against the account's open positions. Nothing is stored. No SPAN formula is
written here: the number is the broker's, labelled as an estimate from the broker's calculator, or it is null with the reason.

Kite names a stock contract by its monthly trading symbol (`RELIANCE26OCT1300CE`, `RELIANCE26OCTFUT`); stock F&O expires monthly, so
that is exact for stocks. Index contracts also trade weekly under a different symbol, which is not resolved here, so an index
underlying is reported as not attempted rather than guessed.

Called by live_reads.attach_live_reads on a built plan, only when the plan asked for live broker reads (inputs.live_broker_reads).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .evidence import item, src_fail, src_ok, unavailable

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))
INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50", "SENSEX", "BANKEX"}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
SOURCE = "estimate from {broker}'s margin calculator, read-only; no order is placed"
BROKER = "Zerodha"


def _strike(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def kite_symbol(underlying: str, leg: Dict[str, Any]) -> str:
    """Kite's monthly trading symbol for a stock future or option leg. Raises ValueError for anything it cannot name."""
    try:
        exp = date.fromisoformat(str(leg.get("expiry")))
    except ValueError:
        raise ValueError("the leg has no valid expiry date") from None
    stem = f"{underlying}{exp.year % 100:02d}{MONTHS[exp.month - 1]}"
    if leg.get("kind") == "future":
        return stem + "FUT"
    strike, right = leg.get("strike"), {"call": "CE", "put": "PE"}.get(str(leg.get("option_type")))
    if leg.get("kind") != "option" or not isinstance(strike, (int, float)) or right is None:
        raise ValueError("the leg is not a future or a complete option")
    return f"{stem}{_strike(strike)}{right}"


def _result(reason: Optional[str], estimate: Optional[float] = None, before: Optional[float] = None, now: Optional[datetime] = None, n: int = 0, called: bool = False) -> Dict[str, Any]:
    return {"called": called, "estimate": estimate, "before_offset": before, "broker": "zerodha", "source": SOURCE.format(broker=BROKER), "reason": reason,
            "as_of": (now or datetime.now(timezone.utc)).astimezone(IST).isoformat(timespec="seconds"), "legs": n}


def _default_kite(token: Any):
    from services.brokers import zerodha
    return zerodha._kite(getattr(token, "token", token))


async def read_margin_estimate(accounts: List[Dict[str, Any]], underlying: str, legs: List[Dict[str, Any]], *,
                               load_token: Callable[[Dict[str, Any]], Any], is_live: Callable[[Dict[str, Any]], bool],
                               kite_factory: Optional[Callable[[Any], Any]] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """{"estimate": float | None, "before_offset", "broker", "source", "reason", "as_of", "legs"}. Never raises; null carries the reason."""
    sym = str(underlying or "").upper()
    if not legs:
        return _result("no legs to price", now=now)
    if any(l.get("kind") == "cash" for l in legs):
        return _result("a cash leg needs no derivatives margin; only futures and option legs are priced by the calculator", now=now, n=len(legs))
    if sym in INDEX_UNDERLYINGS:
        return _result(f"{sym} is an index: its weekly and monthly contracts use different symbols and are not resolved, so no margin is asked for", now=now, n=len(legs))
    usable = [a for a in accounts if a.get("broker") == "zerodha" and is_live(a)]
    if not usable:
        return _result("no connected Zerodha account with a live session; Zerodha's calculator is the only margin source wired", now=now, n=len(legs))
    try:
        params = [{"exchange": "NFO", "tradingsymbol": kite_symbol(sym, l), "transaction_type": "BUY" if l.get("side") == "buy" else "SELL",
                   "variety": "regular", "product": "NRML", "order_type": "MARKET", "quantity": int(round(float(l["quantity"]) * float(l.get("lot_size") or 1)))}
                  for l in legs]
    except (ValueError, KeyError, TypeError) as e:
        return _result(f"the legs cannot be named for Zerodha's calculator: {e}", now=now, n=len(legs))
    factory = kite_factory or _default_kite
    try:
        kc = factory(load_token(usable[0]))
        res = await asyncio.to_thread(kc.basket_order_margins, params, False)
    except Exception as e:  # noqa: BLE001 — a failed calculator call is a null estimate with the reason; the message never carries a token
        logger.warning("strategy plan margin calculator failed error=%s", type(e).__name__)
        return _result(f"Zerodha's margin calculator could not be read ({type(e).__name__}: {str(e)[:120]})", now=now, n=len(legs), called=True)
    final = ((res or {}).get("final") or {}) if isinstance(res, dict) else {}
    initial = ((res or {}).get("initial") or {}) if isinstance(res, dict) else {}
    total = final.get("total")
    if isinstance(total, bool) or not isinstance(total, (int, float)):
        return _result("Zerodha's margin calculator returned no total for these legs", now=now, n=len(legs), called=True)
    before = initial.get("total")
    return _result(None, round(float(total), 2), round(float(before), 2) if isinstance(before, (int, float)) and not isinstance(before, bool) else None, now, len(legs), True)


def margin_item(r: Dict[str, Any]) -> Dict[str, Any]:
    """The ledger item (group derivatives, key margin_estimate) for a `read_margin_estimate` result."""
    s = src_ok(None, r["source"], str(r["as_of"])[:10], "kite-basket-margins") if r["estimate"] is not None else src_fail(r["reason"] or "no estimate", r["source"])
    if r["estimate"] is None:
        return unavailable("derivatives", "margin_estimate", f"No margin estimate: {r['reason']}. Nothing is estimated without the broker's calculator.", s)
    extra = f" Before the offset between legs: {r['before_offset']:,.2f}." if r.get("before_offset") is not None else ""
    return item("derivatives", "margin_estimate", {"estimate": r["estimate"], "before_offset": r["before_offset"], "broker": r["broker"], "legs": r["legs"]},
                f"Required margin {r['estimate']:,.2f} INR for {r['legs']} leg(s), {r['source']}.{extra} It is an estimate for these legs alone (open positions not netted) "
                "and is not the maximum loss.", "neutral", s)
