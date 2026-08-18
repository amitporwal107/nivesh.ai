"""Shared NSDL fetcher.

NSDL's FPI/DII reporting site (www.fpi.nsdl.co.in) is a plain ASP.NET
WebForms app — no Akamai bot-management, no cookie-prime dance, no
per-IP reputation blocking. It therefore stays reachable from hosts
that NSE's edge has blocked, which is exactly why the FII/DII feed
falls back to it.

Kept separate from `nse_fetcher` on purpose: that module's whole reason
for existing (cookie priming, 403 re-prime, Akamai handling) is dead
weight here, and folding NSDL into it would mean NSDL requests inherit
NSE's retry semantics.
"""
from __future__ import annotations

from typing import Optional, Tuple

from nidp.shared.sources.plain_http import fetch_bytes as _fetch

NSDL_FPI_BASE = "https://www.fpi.nsdl.co.in"
NSDL_FPI_LATEST = f"{NSDL_FPI_BASE}/web/Reports/Latest.aspx"
NSDL_DII_LATEST = f"{NSDL_FPI_BASE}/web/Users/DIIGenerateReport.aspx?Rep=L"


async def fetch_bytes(url: str, *, referer: Optional[str] = None
                      ) -> Tuple[bytes, int]:
    return await _fetch(url, referer=referer or (NSDL_FPI_BASE + "/"),
                        label="NSDL")
