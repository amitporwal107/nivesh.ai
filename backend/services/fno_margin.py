"""Margin and charges for an option/futures basket from Zerodha's margin CALCULATOR (Kite Connect `basket_order_margins`): the exchange margin (SPAN + exposure) and the order charges
(STT, exchange, SEBI, GST, brokerage, stamp duty). It is a calculation: it places, modifies and cancels nothing, and `Calculator` exposes only that and the instrument list.
The figure is Zerodha's for the platform account's rules; it is not an exchange-published number and not a quote, and it needs the platform's daily Kite session."""
from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

MAX_LEGS = 10    # an ANALYSIS limit (what the margin calculator prices), not the strategy limit: services/strategy_limits
_INSTRUMENTS: Dict[str, Any] = {"day": None, "rows": None}


class NoSession(Exception):
    """No usable platform Kite session (not logged in today, or the token was refused)."""


class CalcError(Exception):
    """Kite answered with an error (message kept for the log only)."""


class Calculator:
    """The only Kite surface this module uses: the NFO instrument list and the basket margin calculation. No order, GTT, position or holdings method is exposed."""

    def __init__(self, kc: Any):
        self._kc = kc

    def instruments(self) -> List[dict]:
        return self._kc.instruments("NFO")

    def basket_margins(self, params: List[dict]) -> dict:
        return self._kc.basket_order_margins(params, consider_positions=False, mode="compact")


def _iso(v: Any) -> Optional[str]:
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v)[:10] if v else None


def instruments_today(calc: Calculator, today: Optional[date] = None) -> List[dict]:
    """The NFO instrument list, read once a day."""
    day = (today or date.today()).isoformat()
    if _INSTRUMENTS["day"] != day or _INSTRUMENTS["rows"] is None:
        _INSTRUMENTS["rows"] = [r for r in calc.instruments() if r.get("instrument_type") in ("CE", "PE", "FUT")]
        _INSTRUMENTS["day"] = day
    return _INSTRUMENTS["rows"]


def cached_instruments(today: Optional[date] = None) -> Optional[List[dict]]:
    """Today's NFO instrument list if this worker has already loaded it, else None. Never calls Kite (the risk gate
    reads lot sizes and expiries from it when it is there)."""
    day = (today or date.today()).isoformat()
    return _INSTRUMENTS["rows"] if _INSTRUMENTS["day"] == day else None


def map_legs(rows: Sequence[dict], legs: Sequence[Dict[str, Any]], underlying: str) -> Tuple[List[dict], List[str]]:
    """(Kite order params, names of legs with no listed contract). Quantity = lots x the contract's lot size."""
    by: Dict[Tuple[str, str, float, str], dict] = {}
    for r in rows:
        if r.get("name") == underlying:
            by[(r["name"], _iso(r.get("expiry")) or "", float(r.get("strike") or 0), r["instrument_type"])] = r
    params: List[dict] = []
    missing: List[str] = []
    for l in legs:
        kind = "CE" if l["option_type"] == "call" else "PE" if l["option_type"] == "put" else "FUT"
        r = by.get((underlying, l["expiry"], float(l.get("strike") or 0), kind))
        if r is None:
            missing.append(f"{l['expiry']} {l.get('strike')} {kind}")
            continue
        params.append({"exchange": "NFO", "tradingsymbol": r["tradingsymbol"], "transaction_type": "BUY" if l["side"] == "buy" else "SELL",
                       "variety": "regular", "product": "NRML", "order_type": "MARKET", "quantity": int(l["lots"]) * int(r["lot_size"])})
    return params, missing


def _n(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v else None


def _charges(c: Any) -> Dict[str, Optional[float]]:
    c = c if isinstance(c, dict) else {}
    g = c.get("gst") if isinstance(c.get("gst"), dict) else {}
    return {"brokerage": _n(c.get("brokerage")), "stt": _n(c.get("transaction_tax")), "exchange": _n(c.get("exchange_turnover_charge")), "sebi": _n(c.get("sebi_turnover_charge")),
            "stamp_duty": _n(c.get("stamp_duty")), "gst": _n(g.get("total")), "total": _n(c.get("total"))}


def shape(raw: Dict[str, Any], as_of: str) -> Dict[str, Any]:
    """The route's answer from Kite's: required margin (the final figure), initial margin, the hedge benefit (initial − final), per-order charges and their sum. A missing number is None."""
    orders = [{"tradingsymbol": o.get("tradingsymbol"), "charges": _charges(o.get("charges"))} for o in (raw.get("orders") or []) if isinstance(o, dict)]
    totals: Dict[str, Optional[float]] = {}
    for key in ("brokerage", "stt", "exchange", "sebi", "stamp_duty", "gst", "total"):
        vals = [o["charges"][key] for o in orders]
        totals[key] = None if not vals or any(v is None for v in vals) else round(sum(vals), 2)
    required = _n((raw.get("final") or {}).get("total"))
    initial = _n((raw.get("initial") or {}).get("total"))
    # Kite's basket margin: `initial` is the orders' margin without the spread benefit, `final` with it; the difference is the
    # hedge benefit the design shows. None when either figure is missing (never a guess).
    hedge = round(initial - required, 2) if initial is not None and required is not None else None
    return {"required_margin": required, "initial_margin": initial,
            "hedge_benefit": hedge, "hedge_benefit_basis": "Zerodha's initial margin (the orders without the spread benefit) less its final margin (with it)",
            "charges": {"per_order": orders, "total": totals}, "as_of": as_of, "source": "Zerodha margin calculator (Kite Connect): exchange SPAN + exposure margin and order charges",
            "note": "A calculation for the platform account's rules, not an exchange-published figure and not a quote. Nothing is placed.", "sent_to_broker": False}


def run(calc: Calculator, underlying: str, legs: Sequence[Dict[str, Any]], today: Optional[date] = None) -> Dict[str, Any]:
    rows = instruments_today(calc, today)
    params, missing = map_legs(rows, legs, underlying)
    if missing:
        return {"ok": False, "missing_contracts": missing}
    try:
        raw = calc.basket_margins(params)
    except Exception as e:  # noqa: BLE001
        name = type(e).__name__
        if name in ("TokenException", "PermissionException"):
            raise NoSession(name)
        raise CalcError(name)
    return {"ok": True, **shape(raw if isinstance(raw, dict) else {}, (today or date.today()).isoformat())}


def default_calculator() -> Calculator:
    """A calculator on the platform's Kite session, or NoSession when there is none."""
    from services.kite_live_feed import config as cfg
    try:
        from kiteconnect import KiteConnect
    except ImportError as e:  # pragma: no cover
        raise NoSession("kiteconnect_missing") from e
    key, token = cfg.get_api_key(), cfg.get_token()
    if not key or not token:
        raise NoSession("no_token")
    kc = KiteConnect(api_key=key)
    kc.set_access_token(token)
    return Calculator(kc)
