"""BSE source URLs + fetcher.

BSE is reachable from hosts NSE's edge has blocked, and publishes the
same SEBI-standard bhavcopy layout NSE does (identical column names,
plus ISIN *and* ticker), which is what makes it usable as a fallback
for nidp.prices_eod.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, Tuple

from nidp.shared.sources.plain_http import fetch_bytes as _fetch

BSE_WWW = "https://www.bseindia.com"

# SEBI-standard daily equity bhavcopy (same layout as NSE's _F_0000 file).
BSE_BHAVCOPY_URL = (
    BSE_WWW + "/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
)
# Daily delivery position, pipe-delimited TXT inside a ZIP, keyed by scrip code.
BSE_DELIVERY_URL = BSE_WWW + "/BSEDATA/gross/{yyyy}/SCBSEALL{ddmm}.zip"


def bhavcopy_url(d: date) -> str:
    return BSE_BHAVCOPY_URL.format(yyyymmdd=d.strftime("%Y%m%d"))


def delivery_url(d: date) -> str:
    return BSE_DELIVERY_URL.format(yyyy=d.strftime("%Y"), ddmm=d.strftime("%d%m"))


async def fetch_bytes(url: str, *, referer: Optional[str] = None
                      ) -> Tuple[bytes, int]:
    return await _fetch(url, referer=referer or (BSE_WWW + "/"), label="BSE")
