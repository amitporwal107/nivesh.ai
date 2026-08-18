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

import json
import logging
import os
import shutil
import time
from typing import List, Optional

from nidp.shared import notify as _notify

logger = logging.getLogger(__name__)

DEFAULT_PATHS = ["/", "/mnt/nidp-nfs"]
# How long to stay quiet after alerting on an unchanged situation. The
# monitor runs every 10 minutes; before this existed it sent one email per
# run, so a single multi-day disk incident produced hundreds of identical
# "CRITICAL / 2.4% free" mails. That volume is what makes an alert
# ignorable — the 2026-08 disk-full outage was alerted 123+ times and
# still ran to 100% full, taking out MinIO, nse_shareholding and the
# nightly analytics chain. Re-alert on escalation immediately; otherwise
# repeat at most once per window.
DEFAULT_REALERT_HOURS = 6.0
_STATE_FILE = os.environ.get(
    "NIDP_DISK_ALERT_STATE", "/tmp/nidp_disk_monitor_alert_state.json")
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


def _alert_signature(findings: List[dict]) -> str:
    """Identity of a breach situation: which paths, at which severity."""
    return "|".join(sorted(f"{f['path']}={f['severity']}" for f in findings))


def _clear_alert_state() -> None:
    """Forget the last alert once every path is healthy again.

    Without this, a disk that breaches, recovers, then breaches again
    inside the re-alert window is silently suppressed — the second
    incident is genuinely new and must page immediately.
    """
    try:
        os.remove(_STATE_FILE)
    except OSError:
        pass


def _load_alert_state() -> dict:
    try:
        with open(_STATE_FILE) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _should_alert(findings: List[dict]) -> bool:
    """True when this breach deserves an email now.

    Always alert if the situation is new or has escalated (a WARN that
    became CRITICAL, or a newly breaching path). Otherwise repeat only
    once per re-alert window, so an ongoing incident stays visible without
    burying the inbox.
    """
    window_h = _pct("NIDP_DISK_REALERT_HOURS", DEFAULT_REALERT_HOURS)
    sig = _alert_signature(findings)
    state = _load_alert_state()
    last_sig = state.get("signature")
    last_at = state.get("alerted_at", 0.0)

    escalated = sig != last_sig
    stale = (time.time() - float(last_at)) >= window_h * 3600.0
    if not (escalated or stale):
        return False
    try:
        with open(_STATE_FILE, "w") as fh:
            json.dump({"signature": sig, "alerted_at": time.time()}, fh)
    except OSError:
        # A full disk is exactly when this write can fail. Alerting is more
        # important than throttling, so fall through and send.
        logger.warning("disk_monitor: could not persist alert state to %s",
                       _STATE_FILE)
    return True


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
    if not findings:
        # All clear — reset so the next breach is treated as a new incident.
        _clear_alert_state()
    if findings and not _should_alert(findings):
        logger.info(
            "disk_monitor: %d breach(es) still present but already alerted "
            "recently at the same severity — suppressing duplicate alert",
            len(findings),
        )
        return {"paths": paths, "warn_pct": warn, "crit_pct": crit,
                "findings": findings, "alert_suppressed": True}
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
