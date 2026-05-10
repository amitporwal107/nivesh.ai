"""On-VM tail + execute trigger for NIDP services running via cron.

Replaces the gcloud-driven Cloud Run logs/execute path (admin_nidp.py)
with VM-native equivalents:

  - GET  /feeds/{ingester}/logs?lines=N — tail /opt/nidp/logs/<ingester>/<ingester>.log
  - POST /feeds/{ingester}/execute      — fork run_service.sh detached

Both auth-gated. Service runs as user `nidp` (see nidp-query-api.service)
so it has read access to the log files and can invoke run_service.sh.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query

from nidp.services.query_api.auth import require_bearer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="", tags=["vm-ops"], dependencies=[Depends(require_bearer)])


NIDP_HOME = Path(os.environ.get("NIDP_HOME", "/opt/nidp"))
LOGS_DIR  = NIDP_HOME / "logs"
RUN_SCRIPT = NIDP_HOME / "repo" / "backend" / "nidp" / "deploy" / "vm" / "run_service.sh"


# Lock down ingester names to alnum + underscore so we can never shell-
# inject through a path component.
import re as _re
_VALID_NAME = _re.compile(r"^[A-Za-z0-9_]+$")


def _validate(ingester: str) -> str:
    if not _VALID_NAME.match(ingester):
        raise HTTPException(status_code=400, detail="invalid ingester name")
    return ingester


@router.get("/feeds/{ingester}/logs")
async def feed_logs(
    ingester: str,
    lines: int = Query(200, ge=1, le=2000),
) -> Dict[str, Any]:
    """Tail the last N lines of the ingester's VM log file.

    Returns 404 with a clear message if the log doesn't exist yet
    (service has never run on this VM)."""
    _validate(ingester)
    log_path = LOGS_DIR / ingester / f"{ingester}.log"
    if not log_path.exists():
        return {
            "ingester": ingester,
            "log_path": str(log_path),
            "lines":    [],
            "error":    f"log file not found: {log_path} (service may not have run yet)",
        }

    try:
        # Use tail(1) for efficient large-file reads. Fallback to Python
        # if tail isn't installed (shouldn't happen on Debian).
        proc = await asyncio.create_subprocess_exec(
            "tail", "-n", str(lines), str(log_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(err_b.decode("utf-8", errors="replace")[:200])
        text = out_b.decode("utf-8", errors="replace")
    except FileNotFoundError:
        # tail not on path — Python fallback
        text = ""
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = 64 * 1024
            buf = b""
            while size > 0 and buf.count(b"\n") <= lines:
                step = min(block, size)
                size -= step
                f.seek(size)
                buf = f.read(step) + buf
            tail_lines = buf.splitlines()[-lines:]
            text = b"\n".join(tail_lines).decode("utf-8", errors="replace")
    except Exception as e:                                            # noqa: BLE001
        logger.warning("feed_logs(%s): %s", ingester, e)
        return {
            "ingester": ingester,
            "log_path": str(log_path),
            "lines":    [],
            "error":    f"{type(e).__name__}: {str(e)[:200]}",
        }

    return {
        "ingester":   ingester,
        "log_path":   str(log_path),
        "lines":      [ln for ln in text.splitlines() if ln],
        "lines_count": text.count("\n"),
        "error":      None,
    }


@router.post("/feeds/{ingester}/execute")
async def feed_execute(
    ingester: str,
    target_date: str | None = None,
) -> Dict[str, Any]:
    """Spawn run_service.sh <ingester> [--date YYYY-MM-DD] in the
    background. Returns 202 immediately; UI polls
    /feeds/{ingester}/runs to see results land in nidp.job_log when
    the job completes."""
    _validate(ingester)
    if not RUN_SCRIPT.exists():
        raise HTTPException(
            status_code=500,
            detail=f"run_service.sh missing on VM at {RUN_SCRIPT}",
        )

    if target_date is not None and not _re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date must be YYYY-MM-DD")

    # Fork-detach so the python process exits after starting the job.
    # nohup + setsid keeps the child alive after we return.
    args = [shlex.quote(str(RUN_SCRIPT)), shlex.quote(ingester)]
    if target_date:
        args += ["--date", shlex.quote(target_date)]
    cmd = "nohup setsid " + " ".join(args) + " >/dev/null 2>&1 &"
    proc = await asyncio.create_subprocess_shell(
        cmd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass

    logger.info("feed_execute: spawned %s (date=%s) via %s", ingester, target_date or "default", RUN_SCRIPT)
    return {
        "ok":          True,
        "ingester":    ingester,
        "target_date": target_date,
        "status":      "spawned",
        "hint":        "poll /feeds/{ingester}/runs for completion (writes to nidp.job_log)",
    }


@router.get("/feeds/{ingester}/log_path")
async def feed_log_path(ingester: str) -> Dict[str, Any]:
    """Return the on-disk log path for the ingester (exists or not).
    Convenience for ops who want to ssh in and tail manually."""
    _validate(ingester)
    log_path = LOGS_DIR / ingester / f"{ingester}.log"
    return {
        "ingester": ingester,
        "log_path": str(log_path),
        "exists":   log_path.exists(),
        "size_bytes": log_path.stat().st_size if log_path.exists() else 0,
    }
