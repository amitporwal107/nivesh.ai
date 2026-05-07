"""Admin → NIDP diagnostics.

One-button trigger for the dump_for_claude.sh script that lives at
backend/nidp/deploy/gcp/dump_for_claude.sh on the VM. Returns the
private-gist URL so the admin can paste it into chat for Claude to read.

The script does heavy work (psql across 7 tables + several gcloud calls
+ gh gist upload) and typically takes 30-90 seconds. We run it sync
with a generous timeout — simpler than background-task plumbing for
v1, and the admin is sitting at the screen anyway.

Endpoints:
  POST /api/admin/nidp/dump      — run dump_for_claude.sh, return URL
  GET  /api/admin/nidp/script    — health probe (does the script exist
                                   on this host? is gh CLI auth'd?)
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from deps import require_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/nidp", tags=["admin-nidp"])

# Repo root resolution: server.py lives at backend/server.py, this file
# at backend/routes/admin_nidp.py. The script is at
# backend/nidp/deploy/gcp/dump_for_claude.sh — three levels up from here.
_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = _REPO_ROOT / "backend" / "nidp" / "deploy" / "gcp" / "dump_for_claude.sh"
DUMP_TIMEOUT_S = 180   # 3 min hard cap; script normally finishes in 30-90s

_GIST_RE = re.compile(r"https://gist\.github\.com/[A-Za-z0-9_/-]+")


@router.get("/script")
async def script_health(request: Request) -> Dict[str, Any]:
    """Pre-flight check the UI can hit before showing the Run button —
    confirms the script exists and is executable, plus whether `gh` is
    on PATH (without that, the script will print to /tmp instead of
    uploading)."""
    await require_admin(request)
    return {
        "script_path": str(SCRIPT_PATH),
        "exists":      SCRIPT_PATH.exists(),
        "executable":  SCRIPT_PATH.exists() and os.access(SCRIPT_PATH, os.X_OK),
        "gh_on_path":  shutil.which("gh") is not None,
    }


@router.post("/dump")
async def trigger_dump(request: Request) -> Dict[str, Any]:
    """Run dump_for_claude.sh and return the gist URL it printed.

    The script writes a /tmp/nidp_dump_*.md file *and* (when gh is
    available) uploads it to a private gist. We capture both stdout
    and stderr and surface the gist URL to the caller.
    """
    await require_admin(request)

    if not SCRIPT_PATH.exists():
        raise HTTPException(status_code=500, detail=f"script missing: {SCRIPT_PATH}")
    if not os.access(SCRIPT_PATH, os.X_OK):
        raise HTTPException(status_code=500, detail=f"script not executable: {SCRIPT_PATH}")

    logger.info("admin/nidp: running dump_for_claude.sh")
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                "bash", str(SCRIPT_PATH),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(_REPO_ROOT),
            ),
            timeout=10,   # process spawn only — actual run is below
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="failed to spawn dump script")

    try:
        stdout_b, _ = await asyncio.wait_for(proc.communicate(), timeout=DUMP_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise HTTPException(
            status_code=504,
            detail=f"dump script exceeded {DUMP_TIMEOUT_S}s timeout — check VM perms (sudo docker, gcloud)",
        )

    output = stdout_b.decode("utf-8", errors="replace")
    rc = proc.returncode

    # The script prints a URL line like:  https://gist.github.com/<u>/<id>
    gist_match = _GIST_RE.search(output)
    gist_url = gist_match.group(0) if gist_match else None

    # Locate the /tmp file path the script always prints, even when gh
    # isn't installed — useful as a fallback for the admin to cat/copy.
    tmp_match = re.search(r"/tmp/nidp_dump_\d+_\d+\.md", output)
    tmp_path = tmp_match.group(0) if tmp_match else None

    if rc != 0 and not gist_url:
        # Truncate output to keep the response small but informative.
        snippet = output[-2000:] if len(output) > 2000 else output
        raise HTTPException(
            status_code=500,
            detail=f"dump script exited with {rc}.\n--- last output ---\n{snippet}",
        )

    return {
        "ok":         True,
        "gist_url":   gist_url,
        "tmp_path":   tmp_path,
        "rc":         rc,
        "stdout_tail": output[-1500:] if len(output) > 1500 else output,
    }
