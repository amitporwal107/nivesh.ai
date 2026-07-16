"""
annual_reports — the missing annual-report feed.

BSE exposes a company's full annual-report history at
    GET https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode={code}
returning rows with Year + PDFDownload (a bseindia-hosted PDF URL). LIVE-VERIFIED
2026-07 from the build env: fields Table / Year / PDFDownload; ~20-30 years of
history per scrip (e.g. TCS 23, Reliance 30 rows).

This ingester sweeps that endpoint across the equity universe
(ref.security_master.bse_code) and inserts each AR straight into nidp.documents
pre-typed doc_type='annual_report', parse_status='pending'. The existing
document_parser then downloads + extracts + chunks + embeds the PDF like any
other doc, and its content classifier confirms the annual_report type.

Idempotent: ON CONFLICT (source_url) DO NOTHING — each PDF URL is ingested once,
so re-running (weekly during AGM season) only picks up newly-filed reports.
Graceful: a failing scrip is logged and skipped; one bad company never aborts
the sweep.
"""
from __future__ import annotations

import argparse  # noqa: F401 — kept for symmetry with __main__ import surface
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import aiohttp

from nidp.shared.storage.pg import get_pool

logger = logging.getLogger(__name__)
IST = ZoneInfo("Asia/Kolkata")

AR_URL = "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}
# Live-verified BSE AnnualReport_New/w field names (2026-07).
_FIELD_TABLE = "Table"
_FIELD_YEAR = "Year"
_FIELD_PDF = "PDFDownload"
_FIELD_DATE = "Fld_AuthoriseDate"

_THROTTLE_S = 1.0                                     # polite: <= 1 req/sec
_HTTP_TIMEOUT = aiohttp.ClientTimeout(total=30)

_UNIVERSE_SQL = """
SELECT bse_code, nse_symbol, security_name
  FROM ref.security_master
 WHERE entity_type = 'EQUITY'
   AND is_active
   AND bse_code IS NOT NULL
 ORDER BY nse_symbol
"""

_INSERT_SQL = """
INSERT INTO nidp.documents (
    source_url, doc_type, ticker_symbol, scrip_code, company_name,
    filed_at, parse_status, source_run_id
) VALUES ($1, 'annual_report', $2, $3, $4, $5, 'pending', $6)
ON CONFLICT (source_url) DO NOTHING
RETURNING doc_id
"""


def _parse_dt(raw) -> datetime | None:
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST).astimezone(timezone.utc)
        except ValueError:
            continue
    return None


async def _fetch_company_ars(sess: aiohttp.ClientSession, scrip_code: str) -> list[dict]:
    async with sess.get(AR_URL, params={"scripcode": scrip_code}) as resp:
        resp.raise_for_status()
        data = await resp.json(content_type=None)   # BSE serves JSON as text/plain
    rows = (data or {}).get(_FIELD_TABLE) or []
    out: list[dict] = []
    for row in rows:
        pdf = (row.get(_FIELD_PDF) or "").strip()
        if not pdf:
            continue
        out.append({
            "url": pdf,
            "year": str(row.get(_FIELD_YEAR, "")).strip(),
            "filed_at": _parse_dt(row.get(_FIELD_DATE)),
        })
    return out


async def run_once(latest_only: bool = False, limit: int = 0) -> dict:
    """Sweep the equity universe and register annual reports as pending documents."""
    run_id = uuid.uuid4()
    pool = await get_pool()
    async with pool.acquire() as conn:
        companies = await conn.fetch(_UNIVERSE_SQL)
    if limit:
        companies = companies[:limit]
    logger.info("annual_reports: sweeping %d companies (latest_only=%s)",
                len(companies), latest_only)

    inserted = seen = failed = 0
    async with aiohttp.ClientSession(timeout=_HTTP_TIMEOUT, headers=_HEADERS) as sess:
        for i, c in enumerate(companies, 1):
            code = str(c["bse_code"]).strip()
            try:
                ars = await _fetch_company_ars(sess, code)
            except Exception as e:  # noqa: BLE001 — one scrip must not abort the sweep
                failed += 1
                logger.warning("annual_reports: %s (%s) failed: %s", c["nse_symbol"], code, e)
                await asyncio.sleep(_THROTTLE_S)
                continue
            if latest_only and ars:
                ars = ars[:1]
            seen += len(ars)
            if ars:
                async with pool.acquire() as conn:
                    for ar in ars:
                        row = await conn.fetchrow(
                            _INSERT_SQL, ar["url"], c["nse_symbol"], code,
                            c["security_name"], ar["filed_at"], run_id,
                        )
                        if row:
                            inserted += 1
            if i % 50 == 0:
                logger.info("annual_reports: %d/%d swept, %d new docs so far",
                            i, len(companies), inserted)
            await asyncio.sleep(_THROTTLE_S)

    result = {"companies": len(companies), "ars_seen": seen,
              "inserted": inserted, "failed": failed}
    logger.info("annual_reports: done %s", result)
    return result
