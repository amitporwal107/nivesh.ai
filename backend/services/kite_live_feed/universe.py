"""What the feed subscribes to: indices + Nifty 500 + F&O underlyings + the near-month futures + any symbol a screen asked for,
plus the index options around the money (NIFTY and BANKNIFTY by default)."""
from __future__ import annotations

import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from .config import MAX_INSTRUMENTS
from .gateway import canon

logger = logging.getLogger(__name__)

_SKIP_INDEX_TAGS = (" LEV", " INV", "BHARATBOND", "-NAV", " TR ", "NIFTY50 PR", "NIFTY GS", " USD")


def index_symbols(nse_rows: List[dict]) -> List[str]:
    out = []
    for r in nse_rows:
        if r.get("segment") != "INDICES":
            continue
        s = canon(r.get("tradingsymbol"))
        if s and not any(tag in s + " " for tag in _SKIP_INDEX_TAGS):
            out.append(s)
    return out


def fno_underlyings(nfo_rows: List[dict]) -> List[str]:
    return sorted({canon(r.get("name")) for r in nfo_rows if r.get("instrument_type") == "FUT" and r.get("name")})


def _day(v: Any) -> Optional[str]:
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str) and len(v) >= 10:
        return v[:10]
    return None


def near_month_futures(nfo_rows: List[dict], today: date) -> List[dict]:
    """The nearest unexpired FUT contract of every F&O underlying (index futures included):
    [{symbol, token, underlying, expiry, lot_size}]. A row Kite sent without a symbol, token or expiry is skipped, never guessed."""
    best: Dict[str, dict] = {}
    for r in nfo_rows:
        if r.get("instrument_type") != "FUT":
            continue
        try:
            name, sym, token = canon(r["name"]), canon(r["tradingsymbol"]), int(r["instrument_token"])
        except (KeyError, TypeError, ValueError):
            continue
        day = _day(r.get("expiry"))
        if not name or not sym or day is None or day < today.isoformat():
            continue
        if name not in best or day < best[name]["expiry"]:
            best[name] = {"symbol": sym, "token": token, "underlying": name, "expiry": day, "lot_size": _lot(r.get("lot_size"))}
    return sorted(best.values(), key=lambda b: b["underlying"])


# The index an option underlying is priced against (its at-the-money reference). Any other underlying is its own cash symbol.
OPTION_SPOT = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FIN SERVICE",
               "MIDCPNIFTY": "NIFTY MID SELECT", "NIFTYNXT50": "NIFTY NEXT 50"}


def _lot(v: Any) -> Optional[int]:
    try:
        n = int(float(v))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def option_contracts(nfo_rows: List[dict], underlyings: List[str], today: date, expiries: int) -> Dict[str, Dict[str, List[dict]]]:
    """{underlying: {expiry: [contract]}} for the `expiries` nearest unexpired expiries of each named underlying, where a
    contract is {symbol, token, underlying, expiry, strike, option_type, lot_size}. Built from Kite's own rows (weekly and
    monthly symbols follow different patterns, so a symbol is never assembled by hand); an incomplete row is skipped."""
    want = {canon(u) for u in underlyings}
    found: Dict[str, Dict[str, List[dict]]] = {}
    if not want or expiries <= 0:
        return {}
    for r in nfo_rows:
        typ = r.get("instrument_type")
        if typ not in ("CE", "PE"):
            continue
        try:
            name, sym, token, strike = canon(r["name"]), canon(r["tradingsymbol"]), int(r["instrument_token"]), float(r["strike"])
        except (KeyError, TypeError, ValueError):
            continue
        day = _day(r.get("expiry"))
        if name not in want or not sym or day is None or day < today.isoformat() or not strike > 0:
            continue
        found.setdefault(name, {}).setdefault(day, []).append(
            {"symbol": sym, "token": token, "underlying": name, "expiry": day, "strike": strike, "option_type": typ,
             "lot_size": _lot(r.get("lot_size"))})
    return {name: {d: by_day[d] for d in sorted(by_day)[:expiries]} for name, by_day in found.items()}


def atm_strike(strikes: List[float], spot: Optional[float]) -> Optional[float]:
    """The listed strike nearest the spot (a tie takes the lower one); None without strikes or a spot."""
    if not strikes or spot is None or not spot > 0:
        return None
    return min(strikes, key=lambda k: (abs(k - spot), k))


def select_options(chains: Dict[str, Dict[str, List[dict]]], spots: Dict[str, Optional[float]],
                   each_side: int) -> Tuple[List[dict], List[str]]:
    """(contracts within `each_side` strikes of the money, CE and PE, per expiry; underlyings left out for want of a spot).
    Ordered underlying, expiry, strike, CE before PE. A missing spot leaves that underlying out: the window is never guessed."""
    picked: List[dict] = []
    missing: List[str] = []
    for name in sorted(chains):
        spot = spots.get(name)
        if spot is None or not spot > 0:
            missing.append(name)
            continue
        for day in sorted(chains[name]):
            rows = chains[name][day]
            strikes = sorted({c["strike"] for c in rows})
            atm = atm_strike(strikes, spot)
            if atm is None:
                continue
            i = strikes.index(atm)
            keep = set(strikes[max(0, i - each_side): i + each_side + 1])
            picked += sorted((c for c in rows if c["strike"] in keep), key=lambda c: (c["strike"], c["option_type"]))
    return picked, missing


async def nifty500_symbols() -> List[str]:
    """Nifty 500 constituents from the data platform. Raises when unreadable (the caller reports a partial universe)."""
    from services.copilot_tools import daas_client
    if not daas_client.is_configured():
        raise RuntimeError("data platform not configured")
    status, body = await daas_client.get_raw("/desk/sector-heatmap", {"index": "Nifty 500"}, timeout=30.0)
    if status != 200 or not isinstance(body, dict) or not isinstance(body.get("stocks"), list):
        raise RuntimeError(f"nifty 500 members: HTTP {status}")
    return [canon(s["symbol"]) for s in body["stocks"] if isinstance(s, dict) and s.get("symbol")]


def assemble(indices: List[str], wanted: List[str], nifty500: List[str], fno: List[str],
             token_map: Dict[str, int], futures: Optional[List[str]] = None,
             options: Optional[List[str]] = None) -> Tuple[List[str], Dict[str, List[str]], List[str]]:
    """(ordered symbols to subscribe, named sets, unresolved). Priority when capped: indices, wanted, Nifty 500, F&O, futures,
    options (so the options are dropped first, then the futures)."""
    sets = {"indices": [], "nifty500": [], "fno": [], "wanted": [], "futures": [], "options": []}
    ordered: List[str] = []
    seen = set()
    unresolved: List[str] = []
    for key, syms in (("indices", indices), ("wanted", wanted), ("nifty500", nifty500), ("fno", fno), ("futures", futures or []),
                      ("options", options or [])):
        for s in syms:
            if s not in token_map:
                unresolved.append(s)
                continue
            sets[key].append(s)
            if s not in seen:
                seen.add(s)
                ordered.append(s)
    if len(ordered) > MAX_INSTRUMENTS:
        logger.warning("live feed universe capped at %d (wanted %d)", MAX_INSTRUMENTS, len(ordered))
        ordered = ordered[:MAX_INSTRUMENTS]
    return ordered, sets, unresolved
