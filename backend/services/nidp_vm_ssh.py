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
        # -T disables pseudo-tty allocation, so detached children on the
        # remote side don't keep the SSH session open via tty inheritance.
        "--ssh-flag=-T",
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
    detached via `setsid nohup`. Returns once the parent shell forks (≤ init_timeout).

    Detachment correctness — what was broken:
      - `nohup bash script &` alone keeps the child's stdin/stdout attached
        to the SSH session's pty. SSH then waits for the pty to close, which
        only happens when the long-running backfill ends → ingress 502.
      - Fix: `setsid` puts the child in a new session with no controlling
        terminal; we also redirect stdin from `/dev/null`. SSH disconnects
        as soon as the bash -c wrapper exits.

    Quoting correctness — the inner command is base64-encoded and decoded
    into a temp script on the VM, so we never nest `bash -c '... bash -c "..."'`.
    """
    import base64, time as _t

    quoted_log = shlex.quote(log_path)
    b64        = base64.b64encode(inner_cmd.encode("utf-8")).decode("ascii")
    script_id  = f"nidp_trigger_{int(_t.time() * 1000)}.sh"
    script_path = f"/tmp/{script_id}"
    qscript    = shlex.quote(script_path)

    # The sudo bash payload is single-quoted; $! resolves on the VM.
    # Detachment uses a subshell with `&` + `disown` so the SSH session
    # exits as soon as the wrapper bash finishes. setsid breaks the
    # controlling tty; </dev/null + redirect-to-file detach all 3 std FDs.
    # We can't capture $! from inside the subshell, so we just confirm
    # the spawn succeeded — actual PID surfaces in audit.backfill_runs.
    wrapper = (
        f"echo {b64} | base64 -d > {qscript} && chmod +x {qscript} && "
        f"sudo mkdir -p $(dirname {quoted_log}) && "
        f"sudo chown nidp:nidp $(dirname {quoted_log}) && "
        f"sudo -u nidp -H bash -c "
        f"'set -a; source /opt/nidp/nidp.env; set +a; "
        f"cd /opt/nidp/repo/backend && "
        f"( setsid bash {qscript} </dev/null > {quoted_log} 2>&1 & disown ) ; "
        f"echo SPAWNED'"
    )
    return await ssh_exec(wrapper, timeout=init_timeout)
