"""What the feed subscribes to: indices + Nifty 500 + F&O underlyings + any symbol a screen asked for."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

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
             token_map: Dict[str, int]) -> Tuple[List[str], Dict[str, List[str]], List[str]]:
    """(ordered symbols to subscribe, named sets, unresolved). Priority when capped: indices, wanted, Nifty 500, F&O."""
    sets = {"indices": [], "nifty500": [], "fno": [], "wanted": []}
    ordered: List[str] = []
    seen = set()
    unresolved: List[str] = []
    for key, syms in (("indices", indices), ("wanted", wanted), ("nifty500", nifty500), ("fno", fno)):
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
