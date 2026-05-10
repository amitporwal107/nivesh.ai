"""Raw-feed archiver — write every external download to durable disk.

Layout:
    /opt/nidp/archive/<ingester>/<YYYY-MM-DD>/<filename>

Use:

    from nidp.shared.archive import archive_raw

    body = await fetch_url(url)
    archive_raw("bhavcopy", target_date, "BhavCopy_NSE_CM_2026-05-08.csv", body)

If `target_date` is unknown at fetch time, pass `None` and the archiver
uses today's IST date.

Errors are logged but never raise — archiving must never break a feed.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)

NIDP_HOME    = Path(os.environ.get("NIDP_HOME", "/opt/nidp"))
ARCHIVE_ROOT = NIDP_HOME / "archive"
_IST         = timezone(timedelta(hours=5, minutes=30))


def _coerce_date(d: Optional[Union[str, date, datetime]]) -> str:
    if d is None:
        return datetime.now(_IST).date().isoformat()
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return str(d)


def archive_raw(
    ingester: str,
    target_date: Optional[Union[str, date, datetime]],
    filename: str,
    content: Union[bytes, str],
) -> Optional[Path]:
    """Persist `content` under /opt/nidp/archive/<ingester>/<date>/<filename>.

    Returns the on-disk Path on success, or None on failure (logged,
    not raised).
    """
    if not ingester or "/" in ingester or "\\" in ingester:
        logger.warning("archive_raw: invalid ingester %r — skipping", ingester)
        return None
    safe_filename = Path(filename).name  # strip any directory traversal
    if not safe_filename:
        logger.warning("archive_raw: empty filename for %s — skipping", ingester)
        return None

    date_str = _coerce_date(target_date)
    day_dir  = ARCHIVE_ROOT / ingester / date_str
    try:
        day_dir.mkdir(parents=True, exist_ok=True)
        target = day_dir / safe_filename
        if isinstance(content, str):
            target.write_text(content, encoding="utf-8")
        else:
            target.write_bytes(content)
        logger.info(
            "archive_raw: %s / %s / %s (%d bytes)",
            ingester, date_str, safe_filename, len(content),
        )
        return target
    except OSError as e:
        logger.warning(
            "archive_raw FAILED for %s/%s/%s: %s",
            ingester, date_str, safe_filename, e,
        )
        return None
