"""DaaS — regulator circulars (SEBI), read from nidp.sebi_circulars.

Endpoints
  GET /v1/circulars/sebi?days=30&limit=50   SEBI circulars and master circulars issued in the last
                                            `days` days (IST), newest first

The table is filled by services/sebi_circulars (migration 163) from SEBI's RSS feed, every 3 h
Mon-Sat, plus a one-off backfill of page 1 of the Circulars and Master Circulars listings. Only
links under /legal/circulars/ and /legal/master-circulars/ are stored.

`as_of` is the IST day of the last run that read SEBI successfully (job_log status OK, PARTIAL or
SKIPPED — SKIPPED means the feed was read and held no circular), and `checked_at` that run's end.
Both are null when the feed has never been read. A row's `issued_on` is the date SEBI shows for
it; a row without one is placed by the day it was first seen. `department` is null: neither SEBI
source says which department issued an item.

Read-only. Filled in by the desk backend work (2026-10-14).
"""
from __future__ import annotations

from datetime import timedelta, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

import nidp.shared.storage.pg as pg
from nidp.services.daas_api.auth import require_api_key
from nidp.services.daas_api.responses import jsonify, row_to_dict

router = APIRouter(prefix="/circulars", tags=["circulars"], dependencies=[Depends(require_api_key)])

SERVICE_NAME = "sebi_circulars"
_IST = timezone(timedelta(hours=5, minutes=30))
_SOURCE_LABEL = {
    "sebi_rss": "SEBI RSS (sebi.gov.in)",
    "sebi_listing": "SEBI Circulars and Master Circulars listings (sebi.gov.in)",
}
_SOURCE_SUFFIX = " — circulars and master circulars"

_META_SQL = """
SELECT (NOW() AT TIME ZONE 'Asia/Kolkata')::date - $1::int AS from_day,
       (SELECT MAX(finished_at) FROM nidp.job_log
         WHERE ingester = $2 AND status IN ('OK', 'PARTIAL', 'SKIPPED')) AS checked_at
"""

_ROWS_SQL = """
SELECT title, url, kind, issued_on, department, source
  FROM nidp.sebi_circulars
 WHERE COALESCE(issued_on, (first_seen_at AT TIME ZONE 'Asia/Kolkata')::date) >= $1::date
 ORDER BY issued_on DESC NULLS LAST, first_seen_at DESC, url
 LIMIT $2
"""


def source_text(sources: List[str]) -> str:
    """The source line for the rows sent: the RSS feed, plus the listings when a backfilled row is among them."""
    labels = [_SOURCE_LABEL[s] for s in ("sebi_rss", "sebi_listing") if s in sources]
    return (" and ".join(labels) or _SOURCE_LABEL["sebi_rss"]) + _SOURCE_SUFFIX


@router.get("/sebi", summary="SEBI circulars and master circulars issued in the last N days")
async def sebi_circulars(
    days: int = Query(30, ge=1, le=365, description="Look-back in days (IST), by issue date"),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    pool = await pg.get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchrow(_META_SQL, days, SERVICE_NAME)
        rows = await conn.fetch(_ROWS_SQL, meta["from_day"], limit)
    checked_at = meta["checked_at"]
    out_rows = [row_to_dict(r) for r in rows]
    sources = {r.pop("source") for r in out_rows}
    return {
        "as_of": checked_at.astimezone(_IST).date().isoformat() if checked_at else None,
        "checked_at": jsonify(checked_at),
        "source": source_text(sorted(sources)),
        "days": days,
        "from": jsonify(meta["from_day"]),
        "count": len(out_rows),
        "rows": out_rows,
    }
