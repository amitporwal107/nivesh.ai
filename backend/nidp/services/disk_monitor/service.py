"""disk_monitor — off-DB disk-space alarm.

The dominant NIDP outage is the VM root disk filling to 100% → Postgres
crash-loops → everything down — and NOTHING alerted on it (both incidents were
found only by manual SSH). This monitor is deliberately **DB-independent**: it
reads free space with `shutil.disk_usage` and alerts via `nidp.shared.notify`
(email/Telegram), so it fires exactly when the DB is dying. It writes NO job_log
row on purpose — a monitor must not depend on the resource it monitors.

Run it FREQUENTLY from its own cron line (not through run_service.sh, which
would retry it):

    */10 * * * *  nidp  /opt/nidp/venv/bin/python -m nidp.services.disk_monitor

Config (env / nidp.env):
    NIDP_DISK_MONITOR_PATHS  comma list (default "/,/mnt/nidp-nfs")
    NIDP_DISK_WARN_PCT       free%% at/below which to WARN     (default 15)
    NIDP_DISK_CRIT_PCT       free%% at/below which to CRITICAL (default 10)
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import List, Optional

from nidp.shared import notify as _notify

logger = logging.getLogger(__name__)

DEFAULT_PATHS = ["/", "/mnt/nidp-nfs"]
DEFAULT_WARN_PCT = 15.0
DEFAULT_CRIT_PCT = 10.0

_GB = 1024 ** 3


def evaluate(path: str, free_bytes: int, total_bytes: int,
             warn_pct: float, crit_pct: float) -> Optional[dict]:
    """Return a finding dict if free% is at/below a threshold, else None."""
    if not total_bytes:
        return None
    free_pct = 100.0 * free_bytes / total_bytes
    base = {
        "path": path,
        "free_pct": round(free_pct, 1),
        "free_gb": round(free_bytes / _GB, 1),
        "total_gb": round(total_bytes / _GB, 1),
    }
    if free_pct <= crit_pct:
        return {**base, "severity": "CRITICAL"}
    if free_pct <= warn_pct:
        return {**base, "severity": "WARN"}
    return None


def check_disk(paths: List[str], warn_pct: float, crit_pct: float) -> List[dict]:
    """Evaluate each path; missing/unreadable paths are skipped."""
    findings: List[dict] = []
    for p in paths:
        try:
            u = shutil.disk_usage(p)
        except (FileNotFoundError, PermissionError, OSError):
            continue
        f = evaluate(p, u.free, u.total, warn_pct, crit_pct)
        if f:
            findings.append(f)
    return findings


def _configured_paths() -> List[str]:
    raw = os.environ.get("NIDP_DISK_MONITOR_PATHS", "")
    if raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()]
    return list(DEFAULT_PATHS)


def _pct(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def run() -> dict:
    """Check all configured paths, log every reading, alert on any breach.
    Returns a report dict. Never writes to the DB."""
    paths = _configured_paths()
    warn = _pct("NIDP_DISK_WARN_PCT", DEFAULT_WARN_PCT)
    crit = _pct("NIDP_DISK_CRIT_PCT", DEFAULT_CRIT_PCT)

    # Log every reading so healthy runs are still observable in the log file.
    for p in paths:
        try:
            u = shutil.disk_usage(p)
            logger.info("disk %s: %.1f%% free (%.1fG / %.1fG)",
                        p, 100.0 * u.free / u.total, u.free / _GB, u.total / _GB)
        except OSError:
            logger.warning("disk %s: not readable — skipping", p)

    findings = check_disk(paths, warn, crit)
    if findings:
        crit_n = sum(1 for f in findings if f["severity"] == "CRITICAL")
        prefix = "🔴 CRITICAL" if crit_n else "⚠"
        subject = f"{prefix} NIDP disk low: " + ", ".join(
            f"{f['path']} {f['free_pct']}% free" for f in findings)
        body = "\n".join(
            f"{f['severity']}: {f['path']} — {f['free_pct']}% free "
            f"({f['free_gb']}G / {f['total_gb']}G)" for f in findings
        ) + (
            "\n\nDisk-full → Postgres crash-loop is the dominant NIDP outage. "
            "Reclaim space (truncate container logs / journalctl vacuum) or grow the PD."
        )
        _notify.notify(subject, body)
        logger.error("disk_monitor: %d breach(es) — alerted: %s", len(findings),
                     [f"{f['path']}={f['free_pct']}%" for f in findings])

    return {"paths": paths, "warn_pct": warn, "crit_pct": crit, "findings": findings}
