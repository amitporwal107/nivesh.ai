"""NSE Bhavcopy ingester (best-effort, optional).

Pulls the daily 'sec_bhavdata_full' file from NSE archives — a single CSV
with OHLC, volume, and DELIV_PER for every cash-segment symbol. This is
the cheapest authoritative source for the positional engine.

The fetcher is intentionally **best-effort**: if NSE blocks the request
(geofencing / TLS rotation / rate limits), it returns 0 written and logs
the error. Operators can fall back to manual CSV upload via the API.

We do NOT depend on any non-stdlib network library — uses urllib only.
"""
from __future__ import annotations

import csv
import io
import logging
import urllib.request
from datetime import date, datetime
from typing import List, Optional

from . import ohlcv_store

logger = logging.getLogger(__name__)

# NSE archive URL pattern (public, ~13:00 IST daily).
BHAV_URL_FMT = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/csv,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _fetch(url: str, timeout: int = 30) -> Optional[str]:
    req = urllib.request.Request(url, headers=_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        logger.warning("bhavcopy fetch failed for %s: %s", url, e)
        return None


def parse_bhavcopy_csv(blob: str, on_date: date) -> List[dict]:
    """Parse NSE sec_bhavdata_full CSV → list of bar dicts.

    The file ships EQ + BE + SM + ST series. We keep EQ and BE (regular
    and trade-to-trade); skip SM/ST (SME) and others.
    """
    reader = csv.DictReader(io.StringIO(blob))
    out: List[dict] = []
    for row in reader:
        # Column names in the bhavcopy have leading spaces
        clean = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in row.items()}
        series = (clean.get("SERIES") or "").upper()
        if series not in ("EQ", "BE"):
            continue
        sym = clean.get("SYMBOL")
        if not sym:
            continue
        try:
            bar = {
                "nse_symbol": sym.upper(),
                "bar_date": on_date,
                "open":  float(clean["OPEN_PRICE"]),
                "high":  float(clean["HIGH_PRICE"]),
                "low":   float(clean["LOW_PRICE"]),
                "close": float(clean["CLOSE_PRICE"]),
                "volume": int(float(clean.get("TTL_TRD_QNTY") or 0)),
                "delivery_qty": (int(float(clean["DELIV_QTY"]))
                                  if (clean.get("DELIV_QTY") or "").replace(".", "").isdigit()
                                  else None),
                "delivery_pct": (float(clean["DELIV_PER"])
                                  if clean.get("DELIV_PER") not in (None, "", "-")
                                  else None),
                "source": "bhavcopy",
            }
        except (ValueError, KeyError) as e:
            logger.debug("skipping bhavcopy row %s: %s", sym, e)
            continue
        out.append(bar)
    return out


async def ingest_for_date(on_date: date) -> int:
    """Fetch + parse + persist bhavcopy for `on_date`. Returns rows written."""
    ddmmyyyy = on_date.strftime("%d%m%Y")
    url = BHAV_URL_FMT.format(ddmmyyyy=ddmmyyyy)
    blob = _fetch(url)
    if not blob:
        return 0
    bars = parse_bhavcopy_csv(blob, on_date)
    if not bars:
        logger.warning("bhavcopy %s parsed 0 rows", on_date)
        return 0
    return await ohlcv_store.upsert_bars(bars)
