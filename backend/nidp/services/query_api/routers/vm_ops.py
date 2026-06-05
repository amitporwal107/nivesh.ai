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
    the job completes.

    On VMs run_service.sh is used (handles flock, logging, venv).
    In Docker/dev environments it falls back to spawning the current
    Python interpreter directly so the sync works without the VM wrapper."""
    _validate(ingester)

    if target_date is not None and not _re.match(r"^\d{4}-\d{2}-\d{2}$", target_date):
        raise HTTPException(status_code=400, detail="target_date must be YYYY-MM-DD")

    if RUN_SCRIPT.exists():
        # VM path: use run_service.sh wrapper (flock + logging + venv)
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
        runner = "run_service.sh"
    else:
        # Docker/dev path: invoke current Python directly.
        # pra_engine is a VM-only nightly job and does not exist as a
        # Python module inside the Query API container — reject early.
        VM_ONLY_INGESTERS = {"pra_engine"}
        if ingester in VM_ONLY_INGESTERS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{ingester} is a VM-only job and can only be triggered when "
                    f"run_service.sh is present ({RUN_SCRIPT}). "
                    "Ensure the NIDP VM is the target, not a Docker/Cloud Run container."
                ),
            )
        import sys as _sys
        py_args = [_sys.executable, "-m", f"nidp.services.{ingester}"]
        if target_date:
            py_args += ["--date", target_date]
        log_dir = LOGS_DIR / ingester
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / f"{ingester}.log"
            _lf = open(log_path, "ab")
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Cannot open log file for {ingester}: {exc}",
            ) from exc
        try:
            proc = await asyncio.create_subprocess_exec(
                *py_args,
                stdout=_lf,
                stderr=_lf,
                start_new_session=True,
            )
        except Exception as exc:
            _lf.close()
            raise HTTPException(
                status_code=500,
                detail=f"Failed to spawn {ingester}: {exc}",
            ) from exc
        _lf.close()
        runner = f"python -m nidp.services.{ingester}"

    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        pass

    logger.info("feed_execute: spawned %s (date=%s) via %s", ingester, target_date or "default", runner)
    return {
        "ok":          True,
        "ingester":    ingester,
        "target_date": target_date,
        "status":      "spawned",
        "runner":      runner,
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
