"""Server-resolved inputs of a risk decision: never taken from the request (Phase 1 item 1.1).

    instrument(symbol)  the last close and its date, the average daily traded value (ADV) over the last ADV_SESSIONS
                        sessions, from the end-of-day bars the desk itself books against (nidp.prices_eod through the
                        data platform, services/desk_trading.fetch_bars)
    sector_of(symbol)   the NSE industry classification of the share, from the latest constituent list of
                        SECTOR_INDICES (nidp.index_constituents through DaaS /v1/indices/{index}/constituents), read
                        once per process per SECTOR_TTL_S. A share on none of the lists has no sector (the decision
                        then blocks: sector_unknown).
    market_state()      India VIX and the market regime the desk uses (macro_engine.classify_desk_regime through
                        services/strategy_plan/regime_fit.read_regime), with its as-of date.

Every function returns what it read and never raises for a missing value: the decision judges the value through
services/data_freshness and blocks with a specific reason. Tests replace these three functions in one place.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from services import desk_trading as desk
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

ADV_SESSIONS = 20
BAR_LOOKBACK_DAYS = 45
SECTOR_INDICES = ("Nifty Total Market", "Nifty 500")
SECTOR_SOURCE = "NSE industry classification, nidp.index_constituents (DaaS /v1/indices/{index}/constituents)"
SECTOR_TTL_S = 6 * 3600
SECTOR_PAGE = 1000
MARKET_SOURCE = "macro_engine.classify_desk_regime (services/strategy_plan/regime_fit.read_regime)"
BARS_SOURCE = "NSE end-of-day bhavcopy, raw traded prices (nidp.prices_eod via the data platform)"

_sector_cache: Dict[str, Any] = {"at": 0.0, "map": None, "as_of": None, "index": None}
_sector_lock = asyncio.Lock()


#: F&O index underlyings: nidp.prices_eod has no rows for them (checked on staging 2026-10-27: BANKNIFTY, NIFTY and
#: FINNIFTY returned no bars), so their last close comes from the NSE index itself (nidp.index_eod, DaaS
#: /v1/indices/{index}/eod), which was current to the last session.
INDEX_UNDERLYINGS = {"NIFTY": "Nifty 50", "BANKNIFTY": "Nifty Bank", "FINNIFTY": "Nifty Financial Services",
                     "MIDCPNIFTY": "Nifty Midcap Select", "NIFTYNXT50": "Nifty Next 50"}
#: Their sector for the concentration limit (they are on no constituent list): a sectoral index is its sector (a bank
#: index concentrates in Financial Services like the banks in it); a broad index is "Broad market index". Versioned.
INDEX_SECTORS_VERSION = "index-sectors-v1"
INDEX_SECTORS = {"NIFTY": "Broad market index", "BANKNIFTY": "Financial Services", "FINNIFTY": "Financial Services",
                 "MIDCPNIFTY": "Broad market index", "NIFTYNXT50": "Broad market index"}
INDEX_SOURCE = "NSE index end-of-day (nidp.index_eod via DaaS /v1/indices/{index}/eod)"


async def _index_bars(symbol: str, today: date) -> Dict[str, Any]:
    out: Dict[str, Any] = {"bars": [], "last_close": None, "last_close_as_of": None, "adv_rs": None, "adv_sessions": 0,
                           "source": INDEX_SOURCE, "error": None}
    index = INDEX_UNDERLYINGS[symbol]
    try:
        body = await daas_client._get(f"/indices/{quote(index, safe='')}/eod",
                                      params={"start": (today - timedelta(days=BAR_LOOKBACK_DAYS)).isoformat(),
                                              "limit": 100}, timeout=15.0)
    except Exception as exc:  # noqa: BLE001 — reported as unreadable, the decision blocks
        out["error"] = f"the index's end-of-day closes could not be read ({type(exc).__name__})"
        return out
    rows = [r for r in ((body or {}).get("data") or []) if isinstance(r, dict) and r.get("close_price")]
    bars = sorted(({"date": date.fromisoformat(str(r["as_of_date"])[:10]), "open": r.get("open_price"),
                    "high": r.get("high_price"), "low": r.get("low_price"), "close": float(r["close_price"]),
                    "volume": None, "series": "INDEX"} for r in rows), key=lambda b: b["date"])
    out["bars"] = bars
    if bars:
        out["last_close"], out["last_close_as_of"] = bars[-1]["close"], bars[-1]["date"].isoformat()
    return out


async def instrument(symbol: str, today: date) -> Dict[str, Any]:
    """{bars, last_close, last_close_as_of, adv_rs, adv_sessions, source, error}. An F&O index underlying reads its
    NSE index's closes (INDEX_UNDERLYINGS); it has no traded value (adv_rs None: the liquidity rule is for shares)."""
    if symbol.upper() in INDEX_UNDERLYINGS:
        return await _index_bars(symbol.upper(), today)
    out: Dict[str, Any] = {"bars": [], "last_close": None, "last_close_as_of": None, "adv_rs": None, "adv_sessions": 0,
                           "source": BARS_SOURCE, "error": None}
    try:
        bars = await desk.fetch_bars(symbol, today - timedelta(days=BAR_LOOKBACK_DAYS))
    except desk.PricesUnavailable as exc:
        out["error"] = f"the end-of-day bars could not be read ({exc})"
        return out
    except Exception as exc:  # noqa: BLE001 — reported as unreadable, the decision blocks
        logger.warning("risk inputs: bars for %s failed (%s)", symbol, type(exc).__name__)
        out["error"] = f"the end-of-day bars could not be read ({type(exc).__name__})"
        return out
    out["bars"] = bars
    last = desk.last_close(bars)
    if last is not None:
        out["last_close"], out["last_close_as_of"] = float(last["close"]), last["date"].isoformat()
    traded = [b["close"] * b["volume"] for b in bars if b.get("close") and b.get("volume")][-ADV_SESSIONS:]
    if traded:
        out["adv_rs"], out["adv_sessions"] = round(sum(traded) / len(traded), 2), len(traded)
    return out


async def _index_rows(index: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    sc = daas_client.strategy_creds()
    for _ in range(5):
        body = await daas_client._get(f"/indices/{quote(index, safe='')}/constituents",
                                      params={"limit": SECTOR_PAGE, "offset": offset}, timeout=15.0, creds=sc)
        data = (body or {}).get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            break
        rows.extend(r for r in data if isinstance(r, dict))
        nxt = ((body or {}).get("pagination") or {}).get("next_offset")
        if nxt is None:
            break
        offset = int(nxt)
    return rows


async def _sector_map() -> Dict[str, Any]:
    async with _sector_lock:
        if _sector_cache["map"] is not None and time.monotonic() - _sector_cache["at"] < SECTOR_TTL_S:
            return _sector_cache
        mapping: Dict[str, Dict[str, Any]] = {}
        errors: List[str] = []
        for index in SECTOR_INDICES:
            try:
                rows = await _index_rows(index)
            except Exception as exc:  # noqa: BLE001 — one list unreadable; the next may still classify
                errors.append(f"{index}: {type(exc).__name__}")
                continue
            for r in rows:
                sym, industry = str(r.get("symbol") or "").upper(), r.get("industry")
                if sym and industry and sym not in mapping:
                    mapping[sym] = {"sector": str(industry).strip(), "as_of": r.get("as_of_date"), "index": index}
        if mapping:
            _sector_cache.update(at=time.monotonic(), map=mapping, errors=errors)
        else:
            _sector_cache.update(at=0.0, map=None, errors=errors)
        return {**_sector_cache, "map": mapping, "errors": errors}


async def sector_of(symbol: str) -> Dict[str, Any]:
    """{sector, as_of, source, error}. sector None when the share is on no list or the lists cannot be read. An F&O index
    underlying has the sector INDEX_SECTORS names."""
    if symbol.upper() in INDEX_SECTORS:
        return {"sector": INDEX_SECTORS[symbol.upper()], "as_of": None, "source": f"{INDEX_SECTORS_VERSION} (index underlying)",
                "error": None}
    if not daas_client.is_configured():
        return {"sector": None, "as_of": None, "source": SECTOR_SOURCE, "error": "the data platform is not configured"}
    try:
        cache = await _sector_map()
    except Exception as exc:  # noqa: BLE001
        return {"sector": None, "as_of": None, "source": SECTOR_SOURCE, "error": f"unreadable ({type(exc).__name__})"}
    hit = (cache.get("map") or {}).get(symbol.upper())
    if hit:
        return {"sector": hit["sector"], "as_of": hit["as_of"], "source": f"{SECTOR_SOURCE}, {hit['index']}", "error": None}
    why = ("the constituent lists could not be read: " + "; ".join(cache.get("errors") or [])) if not cache.get("map") \
        else f"{symbol} is on none of {', '.join(SECTOR_INDICES)}"
    return {"sector": None, "as_of": None, "source": SECTOR_SOURCE, "error": why}


def regime_label(trend: Any) -> Optional[str]:
    """The governor's words (BULL / BEAR / SIDEWAYS) from the desk regime's trend (up / down / flat)."""
    return {"up": "BULL", "down": "BEAR", "flat": "SIDEWAYS"}.get(str(trend or "").lower())


async def market_state() -> Dict[str, Any]:
    """{vix, regime, as_of, key, source, error}."""
    try:
        from services.strategy_plan import regime_fit
        reg = await regime_fit.read_regime()
    except Exception as exc:  # noqa: BLE001
        return {"vix": None, "regime": None, "as_of": None, "key": None, "source": MARKET_SOURCE,
                "error": f"unreadable ({type(exc).__name__})"}
    if not reg.get("available"):
        return {"vix": None, "regime": None, "as_of": None, "key": None, "source": MARKET_SOURCE,
                "error": reg.get("reason") or "the desk regime is unavailable"}
    vix = reg.get("india_vix")
    return {"vix": float(vix) if isinstance(vix, (int, float)) and not isinstance(vix, bool) else None,
            "regime": regime_label(reg.get("trend")), "as_of": reg.get("as_of"), "key": reg.get("key"),
            "source": MARKET_SOURCE, "error": None}
