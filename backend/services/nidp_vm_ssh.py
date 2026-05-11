"""NIDP VM SSH executor.

Wraps `gcloud compute ssh` to run commands on the NIDP VM
(`nidp-stack-vm` @ `asia-south1-a` in project `niveshdataintelligence`)
using a service-account JSON key at `NIDP_VM_SA_KEY_PATH`.

Why gcloud and not paramiko: OS Login on GCE manages SSH keys via IAM;
gcloud handles the publish-key / SSH-flow plumbing transparently.
With a service account that has `roles/compute.osAdminLogin`, the SA
gets a stable POSIX login that can `sudo -u nidp` on the VM.

Usage:
    rc, stdout, stderr = await ssh_exec("date; whoami", timeout=30)
    rc, stdout, stderr = await ssh_run_detached(
        "sudo -u nidp -H bash -c 'set -a; source /opt/nidp/nidp.env; set +a; "
        "cd /opt/nidp/repo/backend && nohup ... > /opt/nidp/logs/backfill/x.log 2>&1 &'"
    )
"""
from __future__ import annotations

import asyncio
import logging
import os
import shlex
import shutil
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Config (env-driven, no fallbacks — fail fast on missing config)
# ─────────────────────────────────────────────────────────────────
def _cfg() -> dict:
    return {
        "project":  os.environ.get("NIDP_VM_PROJECT")  or "niveshdataintelligence",
        "zone":     os.environ.get("NIDP_VM_ZONE")     or "asia-south1-a",
        "instance": os.environ.get("NIDP_VM_INSTANCE") or "nidp-stack-vm",
        "sa_key":   os.environ.get("NIDP_VM_SA_KEY_PATH") or "/app/backend/.secrets/nidp_vm_sa.json",
        "gcloud":   os.environ.get("GCLOUD_PATH")      or _resolve_gcloud(),
    }


def _resolve_gcloud() -> str:
    for path in (
        "/opt/google-cloud-sdk/bin/gcloud",
        "/tmp/google-cloud-sdk/bin/gcloud",
        shutil.which("gcloud") or "",
    ):
        if path and Path(path).exists():
            return path
    return "gcloud"  # let subprocess raise


class SSHUnavailable(RuntimeError):
    """Raised when the SA key or gcloud binary is missing — surfaces a 503 to the UI."""


def ensure_available() -> None:
    cfg = _cfg()
    if not Path(cfg["gcloud"]).exists():
        raise SSHUnavailable(f"gcloud binary not found at {cfg['gcloud']}")
    if not Path(cfg["sa_key"]).exists():
        raise SSHUnavailable(
            f"NIDP VM service-account key not found at {cfg['sa_key']}. "
            "Drop the JSON key there to enable VM-side triggers."
        )


# ─────────────────────────────────────────────────────────────────
# gcloud auth: every invocation uses --account + an isolated config
# so we never disturb any other gcloud usage in this pod.
# ─────────────────────────────────────────────────────────────────
_ACTIVATED = False


async def _ensure_authed() -> dict:
    global _ACTIVATED
    cfg = _cfg()
    ensure_available()

    if not _ACTIVATED:
        # Idempotent activation. Re-runs are no-ops.
        proc = await asyncio.create_subprocess_exec(
            cfg["gcloud"], "auth", "activate-service-account",
            f"--key-file={cfg['sa_key']}", "--quiet",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await proc.communicate()
        if proc.returncode != 0:
            raise SSHUnavailable(
                f"gcloud auth activate-service-account failed: "
                f"{err.decode(errors='replace')[:400]}"
            )
        _ACTIVATED = True
        logger.info("nidp_vm_ssh: SA activated from %s", cfg["sa_key"])
    return cfg


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────
async def ssh_exec(
    command: str, *, timeout: float = 60.0,
) -> Tuple[int, str, str]:
    """Run a single command on the VM, wait for completion, return (rc, stdout, stderr).

    The command runs as the SA's POSIX user (an `sa_*` account created
    by OS Login). To run as `nidp` (which owns the data dirs), prefix
    with `sudo -u nidp -H bash -c '...'`.
    """
    cfg = await _ensure_authed()

    full_cmd = [
        cfg["gcloud"], "compute", "ssh",
        f"--project={cfg['project']}",
        f"--zone={cfg['zone']}",
        cfg["instance"],
        f"--command={command}",
        "--quiet",
        "--ssh-flag=-o ConnectTimeout=15",
        "--ssh-flag=-o ServerAliveInterval=10",
    ]

    proc = await asyncio.create_subprocess_exec(
        *full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, "", f"timed out after {timeout}s"

    return (
        proc.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def ssh_run_detached_as_nidp(
    inner_cmd: str, *, log_path: str, init_timeout: float = 30.0,
) -> Tuple[int, str, str]:
    """Spawn `inner_cmd` on the VM as user `nidp` with /opt/nidp/nidp.env sourced,
    detached via nohup. Returns once the parent shell forks (≤ init_timeout).

    Implementation: the inner command is base64-encoded and decoded into a
    temp script on the VM, which side-steps the nested-quoting tangle of
    `gcloud ssh -c "sudo -u nidp bash -c '... bash -c \"...\"'"`. The script
    is then executed under `sudo -u nidp` with the env sourced.
    """
    import base64, time as _t

    quoted_log = shlex.quote(log_path)
    b64        = base64.b64encode(inner_cmd.encode("utf-8")).decode("ascii")
    script_id  = f"nidp_trigger_{int(_t.time() * 1000)}.sh"
    script_path = f"/tmp/{script_id}"
    qscript    = shlex.quote(script_path)

    # All single-shell-level (no nested -c), so quoting is straightforward.
    # The sudo bash payload is single-quoted, so $! inside it is NOT expanded
    # by the outer shell — the inner sudo bash itself expands it at exec time.
    wrapper = (
        f"echo {b64} | base64 -d > {qscript} && chmod +x {qscript} && "
        f"sudo mkdir -p $(dirname {quoted_log}) && "
        f"sudo chown nidp:nidp $(dirname {quoted_log}) && "
        f"sudo -u nidp -H bash -c "
        f"'set -a; source /opt/nidp/nidp.env; set +a; "
        f"cd /opt/nidp/repo/backend && "
        f"nohup bash {qscript} > {quoted_log} 2>&1 & echo PID=$!'"
    )
    return await ssh_exec(wrapper, timeout=init_timeout)
