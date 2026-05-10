"""Raw-feed-file archive listing + download.

Layout on disk:
    /opt/nidp/archive/<ingester>/<YYYY-MM-DD>/<filename>

Both endpoints are bearer-token gated like the rest of the query_api.
"""
from __future__ import annotations

import logging
import os
import re as _re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from nidp.services.query_api.auth import require_bearer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/archive", tags=["archive"], dependencies=[Depends(require_bearer)])

NIDP_HOME    = Path(os.environ.get("NIDP_HOME", "/opt/nidp"))
ARCHIVE_ROOT = NIDP_HOME / "archive"

_VALID_NAME = _re.compile(r"^[A-Za-z0-9_]+$")
_VALID_DATE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_ingester(ingester: str) -> None:
    if not _VALID_NAME.match(ingester):
        raise HTTPException(status_code=400, detail="invalid ingester name")


@router.get("/{ingester}")
async def list_archive(
    ingester: str,
    target_date: Optional[str] = Query(None, regex=r"^\d{4}-\d{2}-\d{2}$"),
    limit_dates: int = Query(30, ge=1, le=365),
) -> Dict[str, Any]:
    _validate_ingester(ingester)
    base = ARCHIVE_ROOT / ingester
    if not base.exists():
        return {
            "ingester":    ingester,
            "archive_root": str(base),
            "exists":      False,
            "dates":       [],
            "files":       [],
        }

    if target_date:
        day_dir = base / target_date
        if not day_dir.exists():
            return {
                "ingester":     ingester,
                "target_date":  target_date,
                "archive_root": str(day_dir),
                "exists":       False,
                "files":        [],
            }
        files = _list_files(day_dir)
        return {
            "ingester":     ingester,
            "target_date":  target_date,
            "archive_root": str(day_dir),
            "exists":       True,
            "files":        files,
        }

    # No date filter: return last N days (sorted desc by mtime).
    day_dirs = [
        d for d in base.iterdir()
        if d.is_dir() and _VALID_DATE.match(d.name)
    ]
    day_dirs.sort(key=lambda d: d.name, reverse=True)
    dates = []
    for d in day_dirs[:limit_dates]:
        files = _list_files(d)
        dates.append({
            "target_date": d.name,
            "file_count":  len(files),
            "total_bytes": sum(f["size_bytes"] for f in files),
            "files":       files,
        })
    return {
        "ingester":    ingester,
        "archive_root": str(base),
        "exists":      True,
        "dates":       dates,
    }


def _list_files(day_dir: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for entry in sorted(day_dir.rglob("*")):
        if entry.is_file():
            stat = entry.stat()
            rel  = entry.relative_to(day_dir)
            out.append({
                "filename":   str(rel),
                "size_bytes": stat.st_size,
                "mtime":      int(stat.st_mtime),
            })
    return out


@router.get("/{ingester}/{target_date}/{filename:path}")
async def download_archive(ingester: str, target_date: str, filename: str):
    _validate_ingester(ingester)
    if not _VALID_DATE.match(target_date):
        raise HTTPException(status_code=400, detail="invalid target_date")
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid filename")

    file_path = (ARCHIVE_ROOT / ingester / target_date / filename).resolve()
    # Defence-in-depth path-traversal check
    base = (ARCHIVE_ROOT / ingester / target_date).resolve()
    if not str(file_path).startswith(str(base) + os.sep) and file_path != base:
        raise HTTPException(status_code=400, detail="path traversal")
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"file not found: {filename}")

    return FileResponse(
        path=str(file_path),
        filename=Path(filename).name,
        media_type="application/octet-stream",
    )
