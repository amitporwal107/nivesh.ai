"""The exchange's lot size and listed expiries for an underlying: what the gate checks a structure's legs against.

Two sources, in this order:
  1. the NFO instrument list services/fno_margin.py keeps in this worker's memory for today (Kite Connect), when it
     has been loaded today. Read in process, never fetched from here: the gate does not depend on a Kite session.
  2. the NSE F&O bhavcopy (nidp.fno_bhavcopy, column new_board_lot_qty) through the data platform's
     GET /v1/fno/{symbol}?expiry=, which answers with the contracts of that expiry on the latest bhavcopy day.

Per expiry the answer is {listed, lot_size, source, as_of, error}. `listed` is True / False when a source answered
and None when nothing could be verified; `lot_size` is None whenever it could not be read as one positive whole
number. The gate BLOCKS on None in either (lot_size_unverified / expiry_unverified): an unknown is never a pass.
A bhavcopy older than REFERENCE_MAX_AGE_DAYS calendar days is treated as unverifiable.
"""
from __future__ import annotations

import logging
import math
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from services import fno_margin
from services.copilot_tools import daas_client

logger = logging.getLogger(__name__)

KITE_SOURCE = "kite_nfo_instruments"
BHAVCOPY_SOURCE = "nse_fno_bhavcopy"
REFERENCE_MAX_AGE_DAYS = 7
REFERENCE_TIMEOUT_S = 10.0
_ROWS_PER_EXPIRY = 20


def _unverified(error: str) -> Dict[str, Any]:
    return {"listed": None, "lot_size": None, "source": None, "as_of": None, "error": error}


def _day(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None
    return None


def _lot(value: Any) -> Optional[int]:
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0
            or value != int(value)):
        return None
    return int(value)


def _one_lot(rows: Iterable[Dict[str, Any]], field: str) -> Optional[int]:
    lots = {lot for lot in (_lot(r.get(field)) for r in rows) if lot is not None}
    return lots.pop() if len(lots) == 1 else None


def from_instruments(rows: List[Dict[str, Any]], underlying: str, expiry: str, today: date) -> Dict[str, Any]:
    match = [r for r in rows if r.get("name") == underlying and _day(r.get("expiry")) == expiry]
    if not match:
        return {"listed": False, "lot_size": None, "source": KITE_SOURCE, "as_of": today.isoformat(),
                "error": "no contract with that expiry is in today's instrument list"}
    lot = _one_lot(match, "lot_size")
    return {"listed": True, "lot_size": lot, "source": KITE_SOURCE, "as_of": today.isoformat(),
            "error": None if lot else "the instrument list has no single lot size for that expiry"}


async def from_bhavcopy(underlying: str, expiry: str, today: date) -> Dict[str, Any]:
    if not daas_client.is_configured():
        return _unverified("the data platform is not configured")
    try:
        status, body = await daas_client.get_raw(f"/fno/{quote(underlying, safe='')}",
                                                 {"expiry": expiry, "limit": _ROWS_PER_EXPIRY},
                                                 timeout=REFERENCE_TIMEOUT_S)
    except Exception as e:  # noqa: BLE001 — fail closed: the leg is blocked as unverifiable
        logger.warning("risk_gate: bhavcopy read for %s %s failed (%s)", underlying, expiry, type(e).__name__)
        return _unverified("the data platform could not be read")
    if status != 200 or not isinstance(body, dict):
        return _unverified(f"the data platform answered HTTP {status}")
    as_of = _day(body.get("as_of"))
    if as_of is None:
        return _unverified("the data platform has no F&O rows for this underlying")
    if (today - date.fromisoformat(as_of)).days > REFERENCE_MAX_AGE_DAYS:
        return _unverified(f"the latest bhavcopy for this underlying is {as_of}, older than "
                           f"{REFERENCE_MAX_AGE_DAYS} days")
    rows = [r for r in (body.get("data") or []) if isinstance(r, dict)]
    if not rows:
        return {"listed": False, "lot_size": None, "source": BHAVCOPY_SOURCE, "as_of": as_of,
                "error": f"no contract with that expiry on the latest bhavcopy day ({as_of})"}
    lot = _one_lot(rows, "new_board_lot_qty")
    return {"listed": True, "lot_size": lot, "source": BHAVCOPY_SOURCE, "as_of": as_of,
            "error": None if lot else "the bhavcopy has no single lot size for that contract"}


async def lookup(underlying: str, expiries: Iterable[str], today: date) -> Dict[str, Dict[str, Any]]:
    """{expiry: reference} for each expiry asked for."""
    wanted = sorted(set(expiries))
    rows = fno_margin.cached_instruments()
    if rows is not None:
        return {e: from_instruments(rows, underlying, e, today) for e in wanted}
    return {e: await from_bhavcopy(underlying, e, today) for e in wanted}
